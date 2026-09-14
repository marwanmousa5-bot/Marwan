"""Dispatch: resources, board, drag-and-drop impact, exception centre."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_or_404
from app.auth.deps import Principal, require_operator, require_tenant
from app.core.enums import (ACTIVE_TASK_STATUSES, DriverStatus, OPEN_ALERT_STATUSES,
                            OPEN_WORK_ORDER_STATUSES, Severity, SlaState, TaskStatus,
                            VehicleLifecycle)
from app.db.base import get_session
from app.models import (Alert, Driver, Route, Task, Vehicle, WorkOrder)
from app.services import routes as route_svc, tasks as task_svc
from app.services.derive import vehicle_status

router = APIRouter()


@router.get("/resources")
async def resources(principal: Principal = Depends(require_tenant),
                    session: AsyncSession = Depends(get_session)):
    """Who and what is available, with real workload numbers (spec 4.3)."""
    org_id = principal.org_id
    now = datetime.now(timezone.utc)
    drivers = (await session.execute(
        select(Driver).where(Driver.organization_id == org_id)
        .order_by(Driver.full_name))).scalars().all()
    vehicles = (await session.execute(
        select(Vehicle).where(Vehicle.organization_id == org_id)
        .order_by(Vehicle.name))).scalars().all()
    tasks = (await session.execute(
        select(Task).where(Task.organization_id == org_id,
                           Task.status.in_(ACTIVE_TASK_STATUSES)))).scalars().all()
    wo_vehicles = set((await session.execute(
        select(WorkOrder.vehicle_id).where(
            WorkOrder.organization_id == org_id,
            WorkOrder.status.in_(OPEN_WORK_ORDER_STATUSES)))).scalars().all())

    by_driver: dict[uuid.UUID, list[Task]] = {}
    by_vehicle: dict[uuid.UUID, list[Task]] = {}
    for t in tasks:
        if t.driver_id:
            by_driver.setdefault(t.driver_id, []).append(t)
        if t.vehicle_id:
            by_vehicle.setdefault(t.vehicle_id, []).append(t)

    vehicle_by_driver = {v.driver_id: v for v in vehicles if v.driver_id}

    driver_rows = []
    for d in drivers:
        dts = by_driver.get(d.id, [])
        late = [t for t in dts if t.sla_state in (SlaState.AT_RISK, SlaState.BREACHED)]
        v = vehicle_by_driver.get(d.id)
        driver_rows.append({
            "id": str(d.id), "name": d.full_name, "status": d.status,
            "avatar_color": d.avatar_color, "phone": d.phone,
            "active_tasks": len(dts), "late_tasks": len(late),
            "workload_pct": min(100, round(len(dts) / 6 * 100)),
            "duty_hours_today": round(d.duty_hours_today, 1),
            "fatigue_risk": d.fatigue_risk,
            "safety_score": d.safety_score,
            "vehicle": {"id": str(v.id), "name": v.name, "plate": v.plate} if v else None,
            "available": d.status in (DriverStatus.AVAILABLE, DriverStatus.DRIVING),
        })

    vehicle_rows = []
    for v in vehicles:
        st = vehicle_status(v, has_open_work_order=v.id in wo_vehicles, now=now)
        vts = by_vehicle.get(v.id, [])
        vehicle_rows.append({
            "id": str(v.id), "name": v.name, "plate": v.plate, "type": v.type,
            "status": st, "lifecycle": v.lifecycle, "active_tasks": len(vts),
            "driver_id": str(v.driver_id) if v.driver_id else None,
            "lat": v.last_lat, "lon": v.last_lon, "street": v.last_street,
            "available": st not in ("maintenance", "offline")
            and v.lifecycle == VehicleLifecycle.ACTIVE,
        })

    return {
        "drivers": driver_rows, "vehicles": vehicle_rows,
        "summary": {
            "drivers_available": sum(1 for d in driver_rows if d["available"]),
            "drivers_total": len(driver_rows),
            "vehicles_available": sum(1 for v in vehicle_rows if v["available"]),
            "vehicles_total": len(vehicle_rows),
        },
    }


@router.get("/exceptions")
async def exceptions(principal: Principal = Depends(require_tenant),
                     session: AsyncSession = Depends(get_session)):
    """Everything that needs a dispatcher's attention right now (spec 4.6)."""
    org_id = principal.org_id
    now = datetime.now(timezone.utc)
    out: list[dict] = []

    unassigned = (await session.execute(
        select(Task).where(Task.organization_id == org_id,
                           Task.status == TaskStatus.UNASSIGNED)
        .order_by(Task.scheduled_for.nullslast()))).scalars().all()
    for t in unassigned:
        urgent = t.scheduled_for and t.scheduled_for <= now + timedelta(hours=2)
        out.append({
            "type": "unassigned_task", "severity": "high" if urgent else "medium",
            "title": f"{t.reference} is unassigned",
            "detail": t.title + (f" — due {t.scheduled_for.strftime('%H:%M')}"
                                 if t.scheduled_for else ""),
            "entity_type": "task", "entity_id": str(t.id),
            "lat": t.lat, "lon": t.lon,
        })

    at_risk = (await session.execute(
        select(Task).where(Task.organization_id == org_id,
                           Task.status.in_(ACTIVE_TASK_STATUSES),
                           Task.sla_state.in_([SlaState.AT_RISK, SlaState.BREACHED]))
    )).scalars().all()
    for t in at_risk:
        out.append({
            "type": "sla_risk",
            "severity": "critical" if t.sla_state == SlaState.BREACHED else "high",
            "title": f"{t.reference} SLA {t.sla_state.replace('_', ' ')}",
            "detail": f"{t.title} — ETA "
                      f"{t.eta.strftime('%H:%M') if t.eta else 'unknown'}, deadline "
                      f"{t.sla_due_at.strftime('%H:%M') if t.sla_due_at else 'n/a'}",
            "entity_type": "task", "entity_id": str(t.id),
            "lat": t.lat, "lon": t.lon,
        })

    critical_alerts = (await session.execute(
        select(Alert).where(Alert.organization_id == org_id,
                            Alert.status.in_(tuple(OPEN_ALERT_STATUSES)),
                            Alert.severity.in_([Severity.HIGH, Severity.CRITICAL]))
        .order_by(Alert.triggered_at.desc()).limit(25))).scalars().all()
    for a in critical_alerts:
        out.append({
            "type": "alert", "severity": a.severity, "title": a.title,
            "detail": a.detail or "", "entity_type": "alert", "entity_id": str(a.id),
            "lat": a.lat, "lon": a.lon,
        })

    unavailable = (await session.execute(
        select(Vehicle).where(Vehicle.organization_id == org_id,
                              Vehicle.lifecycle.in_([VehicleLifecycle.MAINTENANCE,
                                                     VehicleLifecycle.SUSPENDED]))
    )).scalars().all()
    for v in unavailable:
        n = (await session.execute(
            select(func.count()).select_from(Task).where(
                Task.vehicle_id == v.id, Task.status.in_(ACTIVE_TASK_STATUSES)))).scalar_one()
        if n:
            out.append({
                "type": "vehicle_unavailable", "severity": "high",
                "title": f"{v.name} is {v.lifecycle} with {n} active task"
                         f"{'s' if n != 1 else ''}",
                "detail": "Reassign the work to keep the schedule intact.",
                "entity_type": "vehicle", "entity_id": str(v.id),
                "lat": v.last_lat, "lon": v.last_lon,
            })

    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    out.sort(key=lambda e: rank.get(e["severity"], 4))
    return {"exceptions": out, "count": len(out),
            "counts_by_type": {t: sum(1 for e in out if e["type"] == t)
                               for t in {e["type"] for e in out}}}


class MoveRequest(BaseModel):
    task_id: uuid.UUID
    driver_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID | None = None


@router.post("/move-preview")
async def move_preview(payload: MoveRequest,
                       principal: Principal = Depends(require_operator),
                       session: AsyncSession = Depends(get_session)):
    """Impact of a drag-and-drop before it is committed (spec 4.5)."""
    org_id = principal.org_id
    task: Task = await get_or_404(session, Task, payload.task_id, org_id, "Task")
    new_driver = await get_or_404(session, Driver, payload.driver_id, org_id, "Driver") \
        if payload.driver_id else None
    new_vehicle = await get_or_404(session, Vehicle, payload.vehicle_id, org_id, "Vehicle") \
        if payload.vehicle_id else None
    if new_vehicle is None and new_driver is not None:
        new_vehicle = (await session.execute(
            select(Vehicle).where(Vehicle.driver_id == new_driver.id))).scalars().first()

    current_driver = await session.get(Driver, task.driver_id) if task.driver_id else None
    current_vehicle = await session.get(Vehicle, task.vehicle_id) if task.vehicle_id else None

    preview = await task_svc.assignment_preview(session, org_id=org_id, task=task,
                                                driver=new_driver, vehicle=new_vehicle)
    delta = None
    if current_vehicle and current_vehicle.last_lat and new_vehicle and new_vehicle.last_lat \
            and task.lat is not None:
        before = route_svc.calculate([(current_vehicle.last_lon, current_vehicle.last_lat),
                                      (task.lon, task.lat)])
        after = route_svc.calculate([(new_vehicle.last_lon, new_vehicle.last_lat),
                                     (task.lon, task.lat)])
        if before.ok and after.ok:
            delta = {
                "distance_km": round((after.distance_m - before.distance_m) / 1000, 2),
                "duration_min": round((after.duration_s - before.duration_s) / 60),
            }
    preview["from"] = {"driver": current_driver.full_name if current_driver else None,
                       "vehicle": current_vehicle.name if current_vehicle else None}
    preview["to"] = {"driver": new_driver.full_name if new_driver else None,
                     "vehicle": new_vehicle.name if new_vehicle else None}
    preview["delta"] = delta
    return preview


@router.post("/move")
async def move(payload: MoveRequest,
               principal: Principal = Depends(require_operator),
               session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    task: Task = await get_or_404(session, Task, payload.task_id, org_id, "Task")
    driver = await get_or_404(session, Driver, payload.driver_id, org_id, "Driver") \
        if payload.driver_id else None
    vehicle = await get_or_404(session, Vehicle, payload.vehicle_id, org_id, "Vehicle") \
        if payload.vehicle_id else None
    if vehicle is None and driver is not None:
        vehicle = (await session.execute(
            select(Vehicle).where(Vehicle.driver_id == driver.id))).scalars().first()
    if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"A {task.status} task cannot be moved.")
    await task_svc.assign(session, org_id=org_id, task=task, driver=driver,
                          vehicle=vehicle, actor=principal.user)
    await session.commit()
    return {"id": str(task.id), "status": task.status,
            "driver_id": str(task.driver_id) if task.driver_id else None,
            "vehicle_id": str(task.vehicle_id) if task.vehicle_id else None}
