"""Task Manager: creation workflow, lifecycle, SLA, proof of delivery."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_or_404, paginate
from app.auth.deps import Principal, require_operator, require_tenant
from app.core.enums import (ACTIVE_TASK_STATUSES, Priority, SlaState, TaskStatus,
                            TaskType)
from app.db.base import get_session
from app.models import (Customer, Driver, Place, Route, RouteStop, Task,
                        TimelineEvent, Trip, Vehicle)
from app.schemas.common import Message
from app.services import audit, routes as route_svc, tasks as task_svc
from app.services.derive import sla_minutes_remaining

router = APIRouter()


class StopIn(BaseModel):
    name: str
    lat: float
    lon: float
    stop_type: str = "delivery"
    service_minutes: int = 5
    notes: str | None = None


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    type: TaskType = TaskType.DELIVERY
    priority: Priority = Priority.NORMAL
    description: str | None = None
    customer_id: uuid.UUID | None = None
    place_id: uuid.UUID | None = None
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    driver_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID | None = None
    scheduled_for: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    sla_minutes: int | None = None
    service_minutes: int = 10
    instructions: str | None = None
    stops: list[StopIn] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    title: str | None = None
    priority: Priority | None = None
    description: str | None = None
    instructions: str | None = None
    scheduled_for: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    sla_minutes: int | None = None
    contact_name: str | None = None
    contact_phone: str | None = None


def _serialise(t: Task, *, driver=None, vehicle=None, customer=None, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "id": str(t.id), "reference": t.reference, "title": t.title, "type": t.type,
        "status": t.status, "priority": t.priority, "sla_state": t.sla_state,
        "sla_minutes_remaining": sla_minutes_remaining(t, now),
        "sla_due_at": t.sla_due_at.isoformat() if t.sla_due_at else None,
        "address": t.address, "lat": t.lat, "lon": t.lon,
        "contact_name": t.contact_name, "contact_phone": t.contact_phone,
        "scheduled_for": t.scheduled_for.isoformat() if t.scheduled_for else None,
        "window_start": t.window_start.isoformat() if t.window_start else None,
        "window_end": t.window_end.isoformat() if t.window_end else None,
        "eta": t.eta.isoformat() if t.eta else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "service_minutes": t.service_minutes,
        "driver": {"id": str(driver.id), "name": driver.full_name,
                   "avatar_color": driver.avatar_color} if driver else None,
        "vehicle": {"id": str(vehicle.id), "name": vehicle.name,
                    "plate": vehicle.plate} if vehicle else None,
        "customer": {"id": str(customer.id), "name": customer.name} if customer else None,
        "has_pod": t.pod_at is not None,
        "failure_reason": t.failure_reason,
    }


@router.get("")
async def list_tasks(
    q: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    priority: str | None = None,
    driver_id: uuid.UUID | None = None,
    vehicle_id: uuid.UUID | None = None,
    sla: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
):
    org_id = principal.org_id
    stmt = select(Task).where(Task.organization_id == org_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Task.title.ilike(like), Task.reference.ilike(like),
                              Task.address.ilike(like)))
    if status_filter:
        stmt = stmt.where(Task.status.in_(status_filter.split(",")))
    if priority:
        stmt = stmt.where(Task.priority == priority)
    if driver_id:
        stmt = stmt.where(Task.driver_id == driver_id)
    if vehicle_id:
        stmt = stmt.where(Task.vehicle_id == vehicle_id)
    if sla:
        stmt = stmt.where(Task.sla_state == sla)
    if date_from:
        stmt = stmt.where(Task.scheduled_for >= date_from)
    if date_to:
        stmt = stmt.where(Task.scheduled_for <= date_to)

    result = await paginate(session, stmt.order_by(Task.scheduled_for.desc().nullslast(),
                                                   Task.created_at.desc()), page, size)
    drivers = {d.id: d for d in (await session.execute(
        select(Driver).where(Driver.organization_id == org_id))).scalars().all()}
    vehicles = {v.id: v for v in (await session.execute(
        select(Vehicle).where(Vehicle.organization_id == org_id))).scalars().all()}
    customers = {c.id: c for c in (await session.execute(
        select(Customer).where(Customer.organization_id == org_id))).scalars().all()}
    now = datetime.now(timezone.utc)
    result["items"] = [
        _serialise(t, driver=drivers.get(t.driver_id), vehicle=vehicles.get(t.vehicle_id),
                   customer=customers.get(t.customer_id), now=now)
        for t in result["items"]
    ]
    return result


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskIn,
                      principal: Principal = Depends(require_operator),
                      session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    now = datetime.now(timezone.utc)
    data = payload.model_dump()
    stops = data.pop("stops", [])
    driver_id = data.pop("driver_id", None)
    vehicle_id = data.pop("vehicle_id", None)

    place = None
    if data.get("place_id"):
        place = await get_or_404(session, Place, data["place_id"], org_id, "Place")
        data.setdefault("address", place.address or place.name)
        if data.get("lat") is None:
            data["lat"], data["lon"] = place.lat, place.lon
    if data.get("customer_id"):
        customer = await get_or_404(session, Customer, data["customer_id"], org_id, "Customer")
        if data.get("lat") is None and customer.place_id:
            cp = await session.get(Place, customer.place_id)
            if cp:
                data["lat"], data["lon"] = cp.lat, cp.lon
                data.setdefault("address", cp.address or cp.name)
        data.setdefault("contact_name", customer.contact_name)
        data.setdefault("contact_phone", customer.contact_phone)

    if data.get("lat") is None or data.get("lon") is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "A task needs a destination. Pick a customer, a saved place, "
                            "or a point on the map.")

    sla_minutes = data.pop("sla_minutes", None)
    task = Task(organization_id=org_id, reference=await task_svc.next_reference(session, org_id),
                created_by_id=principal.user.id, **data)
    task.sla_minutes = sla_minutes
    if sla_minutes:
        base = task.scheduled_for or now
        task.sla_due_at = base + timedelta(minutes=sla_minutes)
    elif task.window_end:
        task.sla_due_at = task.window_end
    session.add(task)
    await session.flush()

    if stops:
        route = Route(organization_id=org_id, name=f"Route for {task.reference}",
                      origin_lat=stops[0]["lat"], origin_lon=stops[0]["lon"],
                      origin_name=stops[0]["name"],
                      dest_lat=task.lat, dest_lon=task.lon,
                      dest_name=task.address or task.title)
        session.add(route)
        await session.flush()
        for i, s in enumerate(stops, start=1):
            session.add(RouteStop(organization_id=org_id, route_id=route.id, sequence=i,
                                  task_id=task.id, **s))
        await session.flush()
        await session.refresh(route, ["stops"])
        await route_svc.recalculate(session, route)
        task.route_id = route.id

    await audit.record(session, action="task.created", organization_id=org_id,
                       actor=principal.user, entity_type="task", entity_id=task.id,
                       entity_label=task.reference,
                       summary=f"{task.reference} created: {task.title}")
    await audit.timeline(session, organization_id=org_id, entity_type="task",
                         entity_id=task.id, action="created", actor=principal.user,
                         occurred_at=now, description=f"Task created — {task.title}.")

    if driver_id or vehicle_id:
        driver = await get_or_404(session, Driver, driver_id, org_id, "Driver") if driver_id else None
        vehicle = await get_or_404(session, Vehicle, vehicle_id, org_id, "Vehicle") if vehicle_id else None
        await task_svc.assign(session, org_id=org_id, task=task, driver=driver,
                              vehicle=vehicle, actor=principal.user, now=now)
    from app.websocket import events as ev
    from app.websocket.events import bus
    await bus.publish(org_id, ev.TASK_CREATED, {"id": str(task.id),
                                                "reference": task.reference})
    await session.commit()
    return {"id": str(task.id), "reference": task.reference, "status": task.status}


@router.get("/{task_id}")
async def task_detail(task_id: uuid.UUID,
                      principal: Principal = Depends(require_tenant),
                      session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    t: Task = await get_or_404(session, Task, task_id, org_id, "Task")
    driver = await session.get(Driver, t.driver_id) if t.driver_id else None
    vehicle = await session.get(Vehicle, t.vehicle_id) if t.vehicle_id else None
    customer = await session.get(Customer, t.customer_id) if t.customer_id else None
    route = await session.get(Route, t.route_id) if t.route_id else None
    trip = (await session.execute(
        select(Trip).where(Trip.task_id == t.id).order_by(Trip.started_at.desc()).limit(1)
    )).scalars().first()
    timeline = (await session.execute(
        select(TimelineEvent).where(TimelineEvent.entity_type == "task",
                                    TimelineEvent.entity_id == t.id)
        .order_by(TimelineEvent.occurred_at))).scalars().all()

    body = _serialise(t, driver=driver, vehicle=vehicle, customer=customer)
    body.update({
        "description": t.description,
        "instructions": t.instructions,
        "attachments": t.attachments,
        "assigned_at": t.assigned_at.isoformat() if t.assigned_at else None,
        "accepted_at": t.accepted_at.isoformat() if t.accepted_at else None,
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "arrived_at": t.arrived_at.isoformat() if t.arrived_at else None,
        "cancelled_at": t.cancelled_at.isoformat() if t.cancelled_at else None,
        "failure_note": t.failure_note,
        "cancel_reason": t.cancel_reason,
        "pod": {"recipient": t.pod_recipient, "notes": t.pod_notes,
                "photo": t.pod_photo, "signature": t.pod_signature,
                "lat": t.pod_lat, "lon": t.pod_lon,
                "at": t.pod_at.isoformat()} if t.pod_at else None,
        "route": {"id": str(route.id), "geometry": route.geometry,
                  "distance_km": round(route.distance_m / 1000, 2),
                  "duration_min": round(route.duration_s / 60),
                  "origin_name": route.origin_name, "dest_name": route.dest_name,
                  "stops": [{"id": str(s.id), "sequence": s.sequence, "name": s.name,
                             "lat": s.lat, "lon": s.lon, "type": s.stop_type,
                             "service_minutes": s.service_minutes,
                             "planned_arrival": s.planned_arrival.isoformat()
                             if s.planned_arrival else None,
                             "arrived_at": s.arrived_at.isoformat()
                             if s.arrived_at else None,
                             "notes": s.notes} for s in route.stops]} if route else None,
        "trip": {"id": str(trip.id), "reference": trip.reference,
                 "distance_km": trip.distance_km} if trip else None,
        "timeline": [{"id": str(e.id), "occurred_at": e.occurred_at.isoformat(),
                      "actor_type": e.actor_type, "actor_name": e.actor_name,
                      "action": e.action, "description": e.description} for e in timeline],
    })
    return body


@router.patch("/{task_id}")
async def update_task(task_id: uuid.UUID, payload: TaskUpdate,
                      principal: Principal = Depends(require_operator),
                      session: AsyncSession = Depends(get_session)):
    t: Task = await get_or_404(session, Task, task_id, principal.org_id, "Task")
    if t.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"A {t.status} task can no longer be edited.")
    fields = ["title", "priority", "scheduled_for", "sla_due_at", "instructions"]
    before = audit.snapshot(t, fields)
    changes = payload.model_dump(exclude_unset=True)
    sla_minutes = changes.pop("sla_minutes", None)
    for k, v in changes.items():
        setattr(t, k, v)
    if sla_minutes is not None:
        t.sla_minutes = sla_minutes
        base = t.scheduled_for or datetime.now(timezone.utc)
        t.sla_due_at = base + timedelta(minutes=sla_minutes)
    await task_svc.refresh_sla(session, org_id=principal.org_id, task=t,
                               org_settings=principal.organization.settings)
    await audit.record(session, action="task.updated", organization_id=principal.org_id,
                       actor=principal.user, entity_type="task", entity_id=t.id,
                       entity_label=t.reference, before=before,
                       after=audit.snapshot(t, fields),
                       summary=f"{t.reference} updated")
    await audit.timeline(session, organization_id=principal.org_id, entity_type="task",
                         entity_id=t.id, action="updated", actor=principal.user,
                         description="Task details updated: " + ", ".join(
                             k.replace('_', ' ') for k in list(changes)
                             + (["sla"] if sla_minutes is not None else [])))
    await session.commit()
    return {"id": str(t.id), "sla_state": t.sla_state}


class AssignIn(BaseModel):
    driver_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID | None = None


@router.post("/{task_id}/assignment-preview")
async def preview_assignment(task_id: uuid.UUID, payload: AssignIn,
                             principal: Principal = Depends(require_operator),
                             session: AsyncSession = Depends(get_session)):
    """Shows conflicts and impact before anything is committed (spec 10.2)."""
    org_id = principal.org_id
    t: Task = await get_or_404(session, Task, task_id, org_id, "Task")
    driver = await get_or_404(session, Driver, payload.driver_id, org_id, "Driver") \
        if payload.driver_id else None
    vehicle = await get_or_404(session, Vehicle, payload.vehicle_id, org_id, "Vehicle") \
        if payload.vehicle_id else None
    return await task_svc.assignment_preview(session, org_id=org_id, task=t,
                                             driver=driver, vehicle=vehicle)


@router.post("/{task_id}/assign")
async def assign_task(task_id: uuid.UUID, payload: AssignIn,
                      principal: Principal = Depends(require_operator),
                      session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    t: Task = await get_or_404(session, Task, task_id, org_id, "Task")
    if t.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"A {t.status} task cannot be reassigned.")
    driver = await get_or_404(session, Driver, payload.driver_id, org_id, "Driver") \
        if payload.driver_id else None
    vehicle = await get_or_404(session, Vehicle, payload.vehicle_id, org_id, "Vehicle") \
        if payload.vehicle_id else None
    if driver is None and vehicle is None:
        await task_svc.transition(session, org_id=org_id, task=t,
                                  target=TaskStatus.UNASSIGNED, actor=principal.user,
                                  note="Returned to the unassigned queue.", strict=False)
        t.driver_id = t.vehicle_id = None
    else:
        await task_svc.assign(session, org_id=org_id, task=t, driver=driver,
                              vehicle=vehicle, actor=principal.user)
    await session.commit()
    return {"id": str(t.id), "status": t.status,
            "driver_id": str(t.driver_id) if t.driver_id else None,
            "vehicle_id": str(t.vehicle_id) if t.vehicle_id else None,
            "eta": t.eta.isoformat() if t.eta else None}


class StatusIn(BaseModel):
    status: TaskStatus
    note: str | None = None


@router.post("/{task_id}/status")
async def set_status(task_id: uuid.UUID, payload: StatusIn,
                     principal: Principal = Depends(require_operator),
                     session: AsyncSession = Depends(get_session)):
    t: Task = await get_or_404(session, Task, task_id, principal.org_id, "Task")
    await task_svc.transition(session, org_id=principal.org_id, task=t,
                              target=payload.status, actor=principal.user,
                              note=payload.note)
    await session.commit()
    return {"id": str(t.id), "status": t.status}


class CancelIn(BaseModel):
    reason: str = Field(min_length=1)


@router.post("/{task_id}/cancel", response_model=Message)
async def cancel_task(task_id: uuid.UUID, payload: CancelIn,
                      principal: Principal = Depends(require_operator),
                      session: AsyncSession = Depends(get_session)):
    t: Task = await get_or_404(session, Task, task_id, principal.org_id, "Task")
    if t.status == TaskStatus.COMPLETED:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "A completed task cannot be cancelled.")
    await task_svc.transition(session, org_id=principal.org_id, task=t,
                              target=TaskStatus.CANCELLED, actor=principal.user,
                              note=f"Cancelled: {payload.reason}",
                              cancel_reason=payload.reason, strict=False)
    await session.commit()
    return Message(detail=f"{t.reference} cancelled.")


@router.get("/board/columns")
async def board(principal: Principal = Depends(require_tenant),
                session: AsyncSession = Depends(get_session)):
    """Board view grouped by lifecycle column."""
    org_id = principal.org_id
    tasks = (await session.execute(
        select(Task).where(Task.organization_id == org_id,
                           Task.status != TaskStatus.CANCELLED)
        .order_by(Task.priority.desc(), Task.scheduled_for.nullslast()))).scalars().all()
    drivers = {d.id: d for d in (await session.execute(
        select(Driver).where(Driver.organization_id == org_id))).scalars().all()}
    vehicles = {v.id: v for v in (await session.execute(
        select(Vehicle).where(Vehicle.organization_id == org_id))).scalars().all()}
    now = datetime.now(timezone.utc)
    columns = [TaskStatus.UNASSIGNED, TaskStatus.ASSIGNED, TaskStatus.ACCEPTED,
               TaskStatus.EN_ROUTE, TaskStatus.ARRIVED, TaskStatus.IN_PROGRESS,
               TaskStatus.COMPLETED]
    grouped = {c: [] for c in columns}
    exceptions = []
    for t in tasks:
        card = _serialise(t, driver=drivers.get(t.driver_id),
                          vehicle=vehicles.get(t.vehicle_id), now=now)
        if t.status in (TaskStatus.DELAYED, TaskStatus.FAILED):
            exceptions.append(card)
        else:
            grouped.setdefault(t.status, []).append(card)
    return {"columns": [{"key": c, "label": c.replace("_", " ").title(),
                         "tasks": grouped.get(c, [])} for c in columns],
            "exceptions": exceptions}
