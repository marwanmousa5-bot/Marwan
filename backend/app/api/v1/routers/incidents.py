"""Incident management."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_or_404, paginate
from app.auth.deps import Principal, require_operator, require_tenant
from app.core.enums import (ACTIVE_TASK_STATUSES, IncidentStatus, IncidentType,
                            Severity, TaskStatus, VehicleLifecycle)
from app.db.base import get_session
from app.models import (Driver, Incident, Task, TimelineEvent, Trip, Vehicle, WorkOrder)
from app.schemas.common import Message
from app.services import alerts as alert_svc, audit
from app.websocket import events as ev
from app.websocket.events import bus

router = APIRouter()

FLOW = {
    IncidentStatus.REPORTED: {IncidentStatus.UNDER_INVESTIGATION,
                              IncidentStatus.ACTION_REQUIRED, IncidentStatus.RESOLVED},
    IncidentStatus.UNDER_INVESTIGATION: {IncidentStatus.ACTION_REQUIRED,
                                         IncidentStatus.RESOLVED},
    IncidentStatus.ACTION_REQUIRED: {IncidentStatus.RESOLVED,
                                     IncidentStatus.UNDER_INVESTIGATION},
    IncidentStatus.RESOLVED: {IncidentStatus.CLOSED, IncidentStatus.UNDER_INVESTIGATION},
    IncidentStatus.CLOSED: set(),
}


class IncidentIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    type: IncidentType = IncidentType.OTHER
    severity: Severity = Severity.MEDIUM
    description: str | None = None
    occurred_at: datetime
    lat: float | None = None
    lon: float | None = None
    address: str | None = None
    vehicle_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    trip_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    photos: list[str] = Field(default_factory=list)
    witnesses: list[dict] = Field(default_factory=list)
    estimated_cost: float | None = None
    take_vehicle_off_road: bool = False


@router.get("/summary")
async def summary(principal: Principal = Depends(require_tenant),
                  session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    by_status = dict((await session.execute(
        select(Incident.status, func.count()).where(
            Incident.organization_id == org_id).group_by(Incident.status))).all())
    by_type = dict((await session.execute(
        select(Incident.type, func.count()).where(
            Incident.organization_id == org_id).group_by(Incident.type))).all())
    by_severity = dict((await session.execute(
        select(Incident.severity, func.count()).where(
            Incident.organization_id == org_id).group_by(Incident.severity))).all())
    cost = (await session.execute(
        select(func.coalesce(func.sum(Incident.estimated_cost), 0.0)).where(
            Incident.organization_id == org_id))).scalar_one()
    open_count = sum(v for k, v in by_status.items()
                     if k not in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED))
    return {"total": sum(by_status.values()), "open": open_count,
            "by_status": by_status, "by_type": by_type, "by_severity": by_severity,
            "estimated_cost": round(float(cost), 2)}


@router.get("")
async def list_incidents(status_filter: str | None = Query(None, alias="status"),
                         type_filter: str | None = Query(None, alias="type"),
                         severity: str | None = None,
                         vehicle_id: uuid.UUID | None = None,
                         driver_id: uuid.UUID | None = None,
                         q: str | None = None,
                         page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
                         principal: Principal = Depends(require_tenant),
                         session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    stmt = select(Incident).where(Incident.organization_id == org_id)
    if status_filter:
        stmt = stmt.where(Incident.status.in_(status_filter.split(",")))
    if type_filter:
        stmt = stmt.where(Incident.type.in_(type_filter.split(",")))
    if severity:
        stmt = stmt.where(Incident.severity.in_(severity.split(",")))
    if vehicle_id:
        stmt = stmt.where(Incident.vehicle_id == vehicle_id)
    if driver_id:
        stmt = stmt.where(Incident.driver_id == driver_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Incident.title.ilike(like), Incident.reference.ilike(like),
                              Incident.description.ilike(like)))
    result = await paginate(session, stmt.order_by(Incident.occurred_at.desc()), page, size)
    vehicles = {v.id: v for v in (await session.execute(
        select(Vehicle).where(Vehicle.organization_id == org_id))).scalars().all()}
    drivers = {d.id: d for d in (await session.execute(
        select(Driver).where(Driver.organization_id == org_id))).scalars().all()}
    result["items"] = [{
        "id": str(i.id), "reference": i.reference, "title": i.title, "type": i.type,
        "severity": i.severity, "status": i.status,
        "occurred_at": i.occurred_at.isoformat(), "address": i.address,
        "lat": i.lat, "lon": i.lon, "estimated_cost": i.estimated_cost,
        "photo_count": len(i.photos or []),
        "vehicle": {"id": str(vehicles[i.vehicle_id].id),
                    "name": vehicles[i.vehicle_id].name,
                    "plate": vehicles[i.vehicle_id].plate}
        if i.vehicle_id in vehicles else None,
        "driver": {"id": str(drivers[i.driver_id].id),
                   "name": drivers[i.driver_id].full_name}
        if i.driver_id in drivers else None,
    } for i in result["items"]]
    return result


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_incident(payload: IncidentIn,
                          principal: Principal = Depends(require_operator),
                          session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    now = datetime.now(timezone.utc)
    data = payload.model_dump()
    off_road = data.pop("take_vehicle_off_road")
    vehicle = None
    if data.get("vehicle_id"):
        vehicle = await get_or_404(session, Vehicle, data["vehicle_id"], org_id, "Vehicle")
    if data.get("driver_id"):
        await get_or_404(session, Driver, data["driver_id"], org_id, "Driver")

    count = (await session.execute(
        select(func.count()).select_from(Incident).where(
            Incident.organization_id == org_id))).scalar_one()
    incident = Incident(organization_id=org_id, reference=f"INC-{1000 + count + 1}",
                        reported_by_id=principal.user.id, **data)
    session.add(incident)
    await session.flush()

    affected_tasks = []
    if vehicle and off_road:
        vehicle.lifecycle = VehicleLifecycle.SUSPENDED
        affected = (await session.execute(
            select(Task).where(Task.vehicle_id == vehicle.id,
                               Task.status.in_(ACTIVE_TASK_STATUSES)))).scalars().all()
        for t in affected:
            t.status = TaskStatus.DELAYED
            affected_tasks.append({"id": str(t.id), "reference": t.reference})
            await audit.timeline(session, organization_id=org_id, entity_type="task",
                                 entity_id=t.id, action="delayed", actor=principal.user,
                                 description=f"Marked delayed — {incident.reference} "
                                             f"took {vehicle.name} off the road.",
                                 related_type="incident", related_id=incident.id)

    await alert_svc.raise_alert(
        session, org_id=org_id, code="unauthorized_movement"
        if incident.type == IncidentType.THEFT else "harsh_braking",
        severity=incident.severity,
        title=f"Incident {incident.reference}: {incident.title}",
        detail=incident.description, vehicle_id=incident.vehicle_id,
        driver_id=incident.driver_id, lat=incident.lat, lon=incident.lon,
        dedupe_extra=f"incident:{incident.id}", now=now,
        evidence={"incident": incident.reference, "type": incident.type},
    ) if incident.severity in (Severity.HIGH, Severity.CRITICAL) else None

    await audit.record(session, action="incident.created", organization_id=org_id,
                       actor=principal.user, entity_type="incident",
                       entity_id=incident.id, entity_label=incident.reference,
                       summary=f"{incident.reference} reported: {incident.title}")
    await audit.timeline(session, organization_id=org_id, entity_type="incident",
                         entity_id=incident.id, action="reported", actor=principal.user,
                         occurred_at=now,
                         description=f"Incident reported — {incident.title}.")
    if vehicle:
        await audit.timeline(session, organization_id=org_id, entity_type="vehicle",
                             entity_id=vehicle.id, action="incident_reported",
                             actor=principal.user, occurred_at=now,
                             description=f"{incident.reference}: {incident.title}"
                                         + (" — vehicle taken off the road."
                                            if off_road else ""),
                             related_type="incident", related_id=incident.id)
    if incident.driver_id:
        await audit.timeline(session, organization_id=org_id, entity_type="driver",
                             entity_id=incident.driver_id, action="incident_reported",
                             actor=principal.user, occurred_at=now,
                             description=f"{incident.reference}: {incident.title}",
                             related_type="incident", related_id=incident.id)
        from app.services import scoring
        driver = await session.get(Driver, incident.driver_id)
        if driver:
            await scoring.recalculate_score(session, org_id=org_id, driver=driver,
                                            org_settings=principal.organization.settings)
    await bus.publish(org_id, ev.INCIDENT_CREATED,
                      {"id": str(incident.id), "reference": incident.reference,
                       "severity": incident.severity})
    await session.commit()
    return {"id": str(incident.id), "reference": incident.reference,
            "vehicle_suspended": off_road, "affected_tasks": affected_tasks}


@router.get("/{incident_id}")
async def incident_detail(incident_id: uuid.UUID,
                          principal: Principal = Depends(require_tenant),
                          session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    i: Incident = await get_or_404(session, Incident, incident_id, org_id, "Incident")
    vehicle = await session.get(Vehicle, i.vehicle_id) if i.vehicle_id else None
    driver = await session.get(Driver, i.driver_id) if i.driver_id else None
    trip = await session.get(Trip, i.trip_id) if i.trip_id else None
    task = await session.get(Task, i.task_id) if i.task_id else None
    wo = await session.get(WorkOrder, i.work_order_id) if i.work_order_id else None
    timeline = (await session.execute(
        select(TimelineEvent).where(TimelineEvent.entity_type == "incident",
                                    TimelineEvent.entity_id == i.id)
        .order_by(TimelineEvent.occurred_at))).scalars().all()
    return {
        "id": str(i.id), "reference": i.reference, "title": i.title, "type": i.type,
        "severity": i.severity, "status": i.status, "description": i.description,
        "occurred_at": i.occurred_at.isoformat(), "lat": i.lat, "lon": i.lon,
        "address": i.address, "photos": i.photos, "documents": i.documents,
        "witnesses": i.witnesses, "estimated_cost": i.estimated_cost,
        "resolution_note": i.resolution_note,
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
        "vehicle": {"id": str(vehicle.id), "name": vehicle.name, "plate": vehicle.plate,
                    "lifecycle": vehicle.lifecycle} if vehicle else None,
        "driver": {"id": str(driver.id), "name": driver.full_name} if driver else None,
        "trip": {"id": str(trip.id), "reference": trip.reference} if trip else None,
        "task": {"id": str(task.id), "reference": task.reference} if task else None,
        "work_order": {"id": str(wo.id), "reference": wo.reference,
                       "status": wo.status} if wo else None,
        "timeline": [{"id": str(e.id), "occurred_at": e.occurred_at.isoformat(),
                      "actor_name": e.actor_name, "actor_type": e.actor_type,
                      "action": e.action, "description": e.description} for e in timeline],
        "allowed_transitions": sorted(FLOW.get(i.status, set())),
    }


class IncidentStatusIn(BaseModel):
    status: IncidentStatus
    note: str | None = None
    restore_vehicle: bool = False


@router.post("/{incident_id}/status")
async def set_status(incident_id: uuid.UUID, payload: IncidentStatusIn,
                     principal: Principal = Depends(require_operator),
                     session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    i: Incident = await get_or_404(session, Incident, incident_id, org_id, "Incident")
    if payload.status not in FLOW.get(i.status, set()):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"An incident that is {i.status.replace('_', ' ')} cannot move to "
            f"{payload.status.replace('_', ' ')}.")
    now = datetime.now(timezone.utc)
    previous, i.status = i.status, payload.status
    if payload.status in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
        i.resolved_at = i.resolved_at or now
        i.resolution_note = payload.note or i.resolution_note
    if payload.restore_vehicle and i.vehicle_id:
        vehicle = await session.get(Vehicle, i.vehicle_id)
        if vehicle and vehicle.lifecycle == VehicleLifecycle.SUSPENDED:
            vehicle.lifecycle = VehicleLifecycle.ACTIVE
            await audit.timeline(session, organization_id=org_id, entity_type="vehicle",
                                 entity_id=vehicle.id, action="returned_to_service",
                                 actor=principal.user, occurred_at=now,
                                 description=f"Returned to service after "
                                             f"{i.reference}.")
    await audit.record(session, action="incident.status_changed", organization_id=org_id,
                       actor=principal.user, entity_type="incident", entity_id=i.id,
                       entity_label=i.reference, before={"status": previous},
                       after={"status": i.status},
                       summary=f"{i.reference}: {previous} → {i.status}")
    await audit.timeline(session, organization_id=org_id, entity_type="incident",
                         entity_id=i.id, action=i.status, actor=principal.user,
                         occurred_at=now,
                         description=payload.note
                         or f"Status changed to {i.status.replace('_', ' ')}.")
    await session.commit()
    return {"id": str(i.id), "status": i.status}


class LinkWorkOrderIn(BaseModel):
    title: str | None = None
    priority: str = "high"


@router.post("/{incident_id}/work-order", status_code=status.HTTP_201_CREATED)
async def raise_work_order(incident_id: uuid.UUID, payload: LinkWorkOrderIn,
                           principal: Principal = Depends(require_operator),
                           session: AsyncSession = Depends(get_session)):
    """Turn an incident into repair work, keeping both records linked."""
    org_id = principal.org_id
    i: Incident = await get_or_404(session, Incident, incident_id, org_id, "Incident")
    if not i.vehicle_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "This incident is not linked to a vehicle.")
    if i.work_order_id:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "A work order already exists for this incident.")
    vehicle = await session.get(Vehicle, i.vehicle_id)
    count = (await session.execute(
        select(func.count()).select_from(WorkOrder).where(
            WorkOrder.organization_id == org_id))).scalar_one()
    from app.services.maintenance import next_reference
    wo = WorkOrder(organization_id=org_id, reference=next_reference("WO", count),
                   vehicle_id=vehicle.id, title=payload.title or f"Repair — {i.title}",
                   problem=i.description, priority=payload.priority,
                   incident_id=i.id, requested_by_id=principal.user.id,
                   odometer_km=vehicle.odometer_km)
    session.add(wo)
    await session.flush()
    i.work_order_id = wo.id
    i.status = IncidentStatus.ACTION_REQUIRED
    await audit.timeline(session, organization_id=org_id, entity_type="incident",
                         entity_id=i.id, action="work_order_raised", actor=principal.user,
                         description=f"Work order {wo.reference} raised.",
                         related_type="work_order", related_id=wo.id)
    await audit.timeline(session, organization_id=org_id, entity_type="work_order",
                         entity_id=wo.id, action="requested", actor=principal.user,
                         description=f"Raised from incident {i.reference}.",
                         related_type="incident", related_id=i.id)
    await audit.record(session, action="work_order.created", organization_id=org_id,
                       actor=principal.user, entity_type="work_order", entity_id=wo.id,
                       entity_label=wo.reference,
                       summary=f"{wo.reference} raised from {i.reference}")
    await session.commit()
    return {"id": str(wo.id), "reference": wo.reference, "incident_status": i.status}
