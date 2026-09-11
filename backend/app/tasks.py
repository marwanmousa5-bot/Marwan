"""Celery task bodies.

Celery workers are synchronous, but the whole data layer is async, so each
task opens its own event loop for one unit of work. That is cheap at these
cadences (minutes, not milliseconds) and keeps a single set of async services
serving both the API and the scheduler - no duplicated sync query layer.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import sqlalchemy as sa

from app.db.session import SessionLocal
from app.models.enums import OrganizationStatus
from app.models.organization import Organization
from app.worker import celery_app

logger = logging.getLogger("fleetbeat.tasks")

T = TypeVar("T")


def run_async(coro_factory: Callable[[], Awaitable[T]]) -> T:
    """Run one coroutine to completion inside a Celery worker."""
    return asyncio.run(coro_factory())


async def _active_organization_ids(db) -> list:
    result = await db.execute(
        sa.select(Organization.id).where(
            Organization.status == OrganizationStatus.ACTIVE
        )
    )
    return [row[0] for row in result.all()]


async def _for_each_organization(
    handler: Callable[[Any, Any], Awaitable[int]],
) -> dict[str, int]:
    """Run one per-Organization handler across the platform.

    A failure in one tenant is logged and skipped rather than aborting the
    sweep - one customer's bad data must not stop every other customer's
    alerts from being raised.
    """
    processed = 0
    produced = 0
    async with SessionLocal() as db:
        organization_ids = await _active_organization_ids(db)
        for organization_id in organization_ids:
            try:
                produced += await handler(db, organization_id)
                await db.commit()
                processed += 1
            except Exception:
                await db.rollback()
                logger.exception(
                    "Task failed for organization %s; continuing", organization_id
                )
    return {"organizations": processed, "produced": produced}


@celery_app.task(name="fleetbeat.maintenance.scan_due")
def scan_maintenance_due() -> dict[str, int]:
    """Raise maintenance-due alerts from schedules vs. odometer and date."""
    from app.services.alerts import scan_maintenance_due as scan

    result = run_async(lambda: _for_each_organization(scan))
    logger.info("Maintenance scan: %s", result)
    return result


@celery_app.task(name="fleetbeat.compliance.scan_expiring_documents")
def scan_expiring_documents() -> dict[str, int]:
    """Raise document-expiry alerts inside each Organization's warning window."""
    from app.services.alerts import scan_expiring_documents as scan

    result = run_async(lambda: _for_each_organization(scan))
    logger.info("Document expiry scan: %s", result)
    return result


@celery_app.task(name="fleetbeat.weather.refresh_zones")
def refresh_weather_zones() -> dict[str, int]:
    """Refresh adverse-weather zones and raise predicted-delay alerts."""
    from app.services import weather

    async def handle(db, organization_id) -> int:
        zones = await weather.refresh_zones_for_organization(db, organization_id)
        alerts = await weather.raise_weather_delay_alerts(db, organization_id)
        return zones + alerts

    async def run() -> dict[str, int]:
        outcome = await _for_each_organization(handle)
        async with SessionLocal() as db:
            expired = await weather.expire_stale_zones(db)
            await db.commit()
        return {**outcome, "expired_zones": expired}

    result = run_async(run)
    logger.info("Weather refresh: %s", result)
    return result


@celery_app.task(name="fleetbeat.alerts.sweep_momentary")
def sweep_momentary_alerts() -> dict[str, int]:
    """Resolve aged-out momentary alerts so the feed stays meaningful."""
    from app.services.alerts import auto_resolve_momentary_alerts

    async def run() -> dict[str, int]:
        async with SessionLocal() as db:
            resolved = await auto_resolve_momentary_alerts(db)
            await db.commit()
        return {"resolved": resolved}

    result = run_async(run)
    if result["resolved"]:
        logger.info("Momentary alert sweep: %s", result)
    return result


@celery_app.task(name="fleetbeat.ai.run_copilot")
def run_fleet_copilot() -> dict[str, int]:
    """Phase 5: AI Fleet Copilot recommendation pass (Section 4e)."""
    logger.debug("fleet copilot: not implemented until Phase 5")
    return {"recommendations": 0}


@celery_app.task(name="fleetbeat.ai.recompute_driver_scores")
def recompute_driver_scores() -> dict[str, int]:
    """Safety score, fatigue indicator and points (Sections 4g and 5 item 1).

    One pass per Organization: score every driver from the shared event
    stream, convert any unprocessed events into points, award clean-streak
    rewards, and roll balances over at the start of a new month.
    """
    from app.ai import scoring
    from app.services import rewards

    async def handle(db, organization_id) -> int:
        rolled = await rewards.reset_monthly_balances(db, organization_id)
        scored = await scoring.score_organization_drivers(db, organization_id)
        outcomes = await rewards.apply_pending_events(db, organization_id)
        streaks = await rewards.award_clean_streaks(db, organization_id)
        return len(scored) + len(outcomes) + len(streaks) + rolled

    result = run_async(lambda: _for_each_organization(handle))
    logger.info("Driver scoring pass: %s", result)
    return result


@celery_app.task(name="fleetbeat.ai.scan_anomalies")
def scan_anomalies() -> dict[str, int]:
    """Raise alerts for statistically unusual fuel and idle patterns."""
    from app.ai import anomaly
    from app.models.enums import AlertRuleType
    from app.services.alerts import raise_alert

    async def handle(db, organization_id) -> int:
        found = [
            *await anomaly.detect_fuel_anomalies(db, organization_id),
            *await anomaly.detect_idle_anomalies(db, organization_id),
        ]
        raised = 0
        for item in found:
            alert = await raise_alert(
                db,
                organization_id=organization_id,
                rule_type=AlertRuleType.ANOMALY,
                title=f"Unusual {item.kind.replace('_', ' ')}: {item.vehicle_name}",
                message=item.summary,
                vehicle_id=item.vehicle_id,
                subject_type=item.kind,
                subject_id=item.subject_id,
                # Keyed to the sample, so one odd fill-up alerts once.
                dedupe_key=f"anomaly:{item.kind}:{item.subject_id}",
                context={"z_score": item.z_score, "mean": item.mean},
            )
            if alert is not None:
                raised += 1
        return raised

    result = run_async(lambda: _for_each_organization(handle))
    logger.info("Anomaly scan: %s", result)
    return result


@celery_app.task(name="fleetbeat.maintenance.forecast")
def forecast_maintenance() -> dict[str, int]:
    """Predictive maintenance: alert on services projected to fall due soon."""
    from app.ai import predictive
    from app.models.enums import AlertRuleType, AlertSeverity
    from app.services.alerts import raise_alert

    async def handle(db, organization_id) -> int:
        forecasts = await predictive.forecast_due_maintenance(db, organization_id)
        raised = 0
        for forecast in forecasts:
            alert = await raise_alert(
                db,
                organization_id=organization_id,
                rule_type=AlertRuleType.MAINTENANCE_DUE,
                severity=(
                    AlertSeverity.WARNING if forecast.days_away <= 7 else AlertSeverity.INFO
                ),
                title=f"Forecast: {forecast.schedule_name} due for {forecast.vehicle_name}",
                message=forecast.summary,
                vehicle_id=forecast.vehicle_id,
                subject_type="maintenance_schedule",
                subject_id=forecast.schedule_id,
                dedupe_key=(
                    f"forecast:{forecast.schedule_id}:{forecast.predicted_due_on}"
                ),
                context={"days_away": forecast.days_away, "basis": forecast.basis},
            )
            if alert is not None:
                raised += 1
        return raised

    result = run_async(lambda: _for_each_organization(handle))
    logger.info("Maintenance forecast: %s", result)
    return result
