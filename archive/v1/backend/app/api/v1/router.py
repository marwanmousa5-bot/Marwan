"""Versioned API surface.

Everything is mounted under ``/api/v1`` so the API stays externally
consumable later without breaking clients (Section 4 item 16).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routers import (
    ai,
    alerts,
    analytics,
    audit,
    auth,
    driver,
    drivers,
    health,
    maps,
    operations,
    organization,
    platform_admin,
    tasks,
    tracking,
    vehicles,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(organization.router)
api_router.include_router(vehicles.router)
api_router.include_router(drivers.router)
api_router.include_router(tracking.router)
api_router.include_router(maps.router)
api_router.include_router(alerts.router)
api_router.include_router(operations.router)
api_router.include_router(analytics.router)
api_router.include_router(ai.router)
api_router.include_router(tasks.router)
api_router.include_router(driver.router)
api_router.include_router(audit.router)
api_router.include_router(platform_admin.router)
