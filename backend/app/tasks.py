"""Celery task registry.

Phase 1 registers the task *names* the beat schedule refers to so the worker
starts cleanly; each body is filled in by the phase that owns the feature.
Keeping them here (rather than adding schedule entries later) means the
scheduling contract is visible from day one.
"""

from __future__ import annotations

import logging

from app.worker import celery_app

logger = logging.getLogger("fleetbeat.tasks")


@celery_app.task(name="fleetbeat.maintenance.scan_due")
def scan_maintenance_due() -> dict[str, int]:
    """Phase 2: raise maintenance-due alerts from schedules vs. odometer/date."""
    logger.debug("maintenance scan: not implemented until Phase 2")
    return {"alerts_created": 0}


@celery_app.task(name="fleetbeat.compliance.scan_expiring_documents")
def scan_expiring_documents() -> dict[str, int]:
    """Phase 2: raise document-expiry alerts inside the warning window."""
    logger.debug("document expiry scan: not implemented until Phase 2")
    return {"alerts_created": 0}


@celery_app.task(name="fleetbeat.weather.refresh_zones")
def refresh_weather_zones() -> dict[str, int]:
    """Phase 2: refresh adverse-weather zones from Open-Meteo (Section 4e)."""
    logger.debug("weather refresh: not implemented until Phase 2")
    return {"zones": 0}


@celery_app.task(name="fleetbeat.ai.run_copilot")
def run_fleet_copilot() -> dict[str, int]:
    """Phase 5: AI Fleet Copilot recommendation pass (Section 4e)."""
    logger.debug("fleet copilot: not implemented until Phase 5")
    return {"recommendations": 0}


@celery_app.task(name="fleetbeat.ai.recompute_driver_scores")
def recompute_driver_scores() -> dict[str, int]:
    """Phase 4: safety score, fatigue indicator and points (Sections 4g/5.1)."""
    logger.debug("driver scoring: not implemented until Phase 4")
    return {"drivers": 0}
