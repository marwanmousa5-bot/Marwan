"""Celery application and beat schedule.

Decision (Section 3 asked for one to be made and stated): **Celery + Redis**,
not APScheduler. Two reasons:

1. Several later phases are genuinely job-shaped and need retries, a result
   backend and horizontal workers - the AI Copilot analysis pass, weekly
   report generation, predictive-maintenance scans, weather refreshes.
   APScheduler would have to be replaced once any of those need to survive a
   restart or run on more than one process.
2. Redis is already in the stack for WebSocket fan-out.

The high-frequency GPS simulation tick (Section 6) is deliberately NOT a
Celery task: dispatching a task every few seconds per vehicle would spend
more time on broker round-trips than on work. It runs instead as a single
long-lived asyncio loop (``app.simulation.runner``) behind the same
``LocationProvider`` abstraction, which a real hardware feed would replace.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "fleetbeat",
    broker=settings.broker_url,
    backend=settings.result_backend,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
)

#: Scheduled work. Entries are added as each phase lands; the tasks
#: themselves live in ``app.tasks``.
celery_app.conf.beat_schedule = {
    "scan-maintenance-due": {
        "task": "fleetbeat.maintenance.scan_due",
        "schedule": crontab(minute=0, hour="*/6"),
    },
    "scan-document-expiry": {
        "task": "fleetbeat.compliance.scan_expiring_documents",
        "schedule": crontab(minute=15, hour=6),
    },
    "refresh-weather-zones": {
        "task": "fleetbeat.weather.refresh_zones",
        "schedule": crontab(minute="*/30"),
    },
    "sweep-momentary-alerts": {
        "task": "fleetbeat.alerts.sweep_momentary",
        "schedule": crontab(minute="*/10"),
    },
    "run-fleet-copilot": {
        "task": "fleetbeat.ai.run_copilot",
        "schedule": 120.0,  # every 2 minutes (Section 4e)
    },
    "recompute-driver-scores": {
        "task": "fleetbeat.ai.recompute_driver_scores",
        "schedule": crontab(minute=5, hour="*"),
    },
    "scan-anomalies": {
        "task": "fleetbeat.ai.scan_anomalies",
        "schedule": crontab(minute=25, hour="*/4"),
    },
    "forecast-maintenance": {
        "task": "fleetbeat.maintenance.forecast",
        "schedule": crontab(minute=40, hour=5),
    },
}
