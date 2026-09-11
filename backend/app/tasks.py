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
            resolved = await weather.auto_resolve_stale_alerts(db)
            await db.commit()
        return {**outcome, "expired_zones": expired, "auto_resolved_alerts": resolved}

    result = run_async(run)
    logger.info("Weather refresh: %s", result)
    return result


@celery_app.task(name="fleetbeat.ai.run_copilot")
def run_fleet_copilot() -> dict[str, int]:
    """Phase 5: AI Fleet Copilot recommendation pass (Section 4e)."""
    logger.debug("fleet copilot: not implemented until Phase 5")
    return {"recommendations": 0}


@celery_app.task(name="fleetbeat.ai.recompute_driver_scores")
def recompute_driver_scores() -> dict[str, int]:
    """Phase 4: safety score, fatigue indicator and points (Sections 4g / 5.1)."""
    logger.debug("driver scoring: not implemented until Phase 4")
    return {"drivers": 0}
