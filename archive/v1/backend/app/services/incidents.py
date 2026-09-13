"""Incident reporting (Section 4 item 11).

Reported from either side: a dispatcher on the web, or a driver from the
mobile app at the roadside.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal
from app.core.errors import NotFoundError
from app.core.tenancy import TenantScope
from app.models.driver import Driver
from app.models.enums import AuditAction, IncidentStatus
from app.models.incident import Incident, IncidentPhoto
from app.models.vehicle import Vehicle
from app.services import audit


def utcnow() -> datetime:
    return datetime.now(UTC)


async def list_incidents(
    db: AsyncSession,
    scope: TenantScope,
    *,
    status: IncidentStatus | None = None,
    vehicle_id: uuid.UUID | None = None,
    driver_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Incident], int]:
    stmt = scope.select(Incident)
    if status is not None:
        stmt = stmt.where(Incident.status == status)
    if vehicle_id is not None:
        stmt = stmt.where(Incident.vehicle_id == vehicle_id)
    if driver_id is not None:
        stmt = stmt.where(Incident.driver_id == driver_id)

    total = int(
        (await db.execute(sa.select(sa.func.count()).select_from(stmt.subquery())))
        .scalar_one()
    )
    result = await db.execute(
        stmt.order_by(Incident.occurred_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all()), total


async def create_incident(
    db: AsyncSession,
    scope: TenantScope,
    *,
    data: dict,
    photo_urls: list[str] | None = None,
    principal: Principal | None = None,
    request: Request | None = None,
) -> Incident:
    if data.get("vehicle_id") and await scope.get(db, Vehicle, data["vehicle_id"]) is None:
        raise NotFoundError("Vehicle not found")
    if data.get("driver_id") and await scope.get(db, Driver, data["driver_id"]) is None:
        raise NotFoundError("Driver not found")

    incident = Incident(
        **data,
        reported_by_user_id=principal.user_id if principal else None,
    )
    incident.occurred_at = incident.occurred_at or utcnow()
    scope.assign(incident)
    db.add(incident)
    await db.flush()

    for url in photo_urls or []:
        photo = IncidentPhoto(incident_id=incident.id, file_url=url)
        scope.assign(photo)
        db.add(photo)
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="incident",
        entity_id=incident.id,
        summary=f"Incident reported: {incident.title} ({incident.severity})",
        request=request,
    )
    return incident


async def set_status(
    db: AsyncSession,
    scope: TenantScope,
    *,
    incident_id: uuid.UUID,
    status: IncidentStatus,
    estimated_cost: float | None = None,
    principal: Principal | None = None,
    request: Request | None = None,
) -> Incident:
    incident = await scope.get_or_404(db, Incident, incident_id, label="Incident")
    before = incident.status
    incident.status = status
    if estimated_cost is not None:
        incident.estimated_cost = estimated_cost

    await audit.record(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="incident",
        entity_id=incident.id,
        summary=f"Incident '{incident.title}': {before} -> {status}",
        request=request,
    )
    return incident


async def photo_urls_for(
    db: AsyncSession, incident_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    if not incident_ids:
        return {}
    rows = await db.execute(
        sa.select(IncidentPhoto.incident_id, IncidentPhoto.file_url).where(
            IncidentPhoto.incident_id.in_(incident_ids)
        )
    )
    out: dict[uuid.UUID, list[str]] = {}
    for incident_id, url in rows.all():
        out.setdefault(incident_id, []).append(url)
    return out
