"""Task lifecycle, assignment, conflict detection and SLA monitoring.

Every transition is timestamped, written to the task timeline and published on
the event bus, so Dispatch, Live Tracking and Analytics all see the same truth.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status as http
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (ACTIVE_TASK_STATUSES, DriverStatus, NotificationType,
                            Severity, SlaState, TaskStatus, VehicleLifecycle)
from app.models import (Driver, Notification, Route, RouteStop, Task, Vehicle)
from app.services import alerts as alert_svc
from app.services import audit
from app.services import routes as route_svc
from app.services.derive import sla_minutes_remaining, sla_state
from app.websocket import events as ev
from app.websocket.events import bus

# Which transitions the lifecycle permits (spec 11.2).
ALLOWED: dict[str, set[str]] = {
    TaskStatus.UNASSIGNED: {TaskStatus.ASSIGNED, TaskStatus.CANCELLED},
    TaskStatus.ASSIGNED: {TaskStatus.ACCEPTED, TaskStatus.UNASSIGNED,
                          TaskStatus.CANCELLED, TaskStatus.DELAYED, TaskStatus.FAILED},
    TaskStatus.ACCEPTED: {TaskStatus.EN_ROUTE, TaskStatus.UNASSIGNED,
                          TaskStatus.CANCELLED, TaskStatus.DELAYED, TaskStatus.FAILED},
    TaskStatus.EN_ROUTE: {TaskStatus.ARRIVED, TaskStatus.DELAYED,
                          TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.ARRIVED: {TaskStatus.IN_PROGRESS, TaskStatus.FAILED,
                         TaskStatus.DELAYED, TaskStatus.CANCELLED},
    TaskStatus.IN_PROGRESS: {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.DELAYED},
    TaskStatus.DELAYED: {TaskStatus.EN_ROUTE, TaskStatus.ARRIVED, TaskStatus.IN_PROGRESS,
                         TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED,
                         TaskStatus.UNASSIGNED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: {TaskStatus.UNASSIGNED, TaskStatus.ASSIGNED},
    TaskStatus.CANCELLED: set(),
}

FAILURE_REASONS = [
    "customer_unavailable", "access_issue", "vehicle_issue", "wrong_address",
    "customer_refused", "safety_issue", "other",
]

TIMESTAMP_FIELD = {
    TaskStatus.ASSIGNED: "assigned_at",
    TaskStatus.ACCEPTED: "accepted_at",
    TaskStatus.EN_ROUTE: "started_at",
    TaskStatus.ARRIVED: "arrived_at",
    TaskStatus.COMPLETED: "completed_at",
    TaskStatus.CANCELLED: "cancelled_at",
}


async def next_reference(session: AsyncSession, org_id: uuid.UUID) -> str:
    n = (await session.execute(
        select(func.count()).select_from(Task).where(Task.organization_id == org_id)
    )).scalar_one()
    return f"TSK-{1000 + n + 1}"


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED.get(current, set())


async def assignment_preview(session: AsyncSession, *, org_id: uuid.UUID, task: Task,
                             driver: Driver | None, vehicle: Vehicle | None,
                             now: datetime | None = None) -> dict:
    """Everything a dispatcher must see before committing (spec 10.2 / 4.5)."""
    now = now or datetime.now(timezone.utc)
    conflicts: list[dict] = []
    warnings: list[str] = []

    workload = None
    if driver is not None:
        active = (await session.execute(
            select(Task).where(Task.driver_id == driver.id,
                               Task.status.in_(ACTIVE_TASK_STATUSES),
                               Task.id != task.id)
            .order_by(Task.scheduled_for)
        )).scalars().all()
        late = [t for t in active if t.sla_due_at and t.sla_due_at < now]
        workload = {
            "driver": driver.full_name, "status": driver.status,
            "active_tasks": len(active), "late_tasks": len(late),
            "duty_hours_today": round(driver.duty_hours_today, 1),
            "fatigue_risk": driver.fatigue_risk,
            "load_pct": min(100, round(len(active) / 6 * 100)),
        }
        if driver.status in (DriverStatus.OFF_DUTY, DriverStatus.UNAVAILABLE):
            warnings.append(f"{driver.full_name} is currently {driver.status.replace('_', ' ')}.")
        if driver.fatigue_risk == "high":
            warnings.append(f"{driver.full_name} has driven {driver.duty_hours_today:.1f} h today - "
                            "fatigue risk is high.")
        if task.scheduled_for:
            for other in active:
                if not other.scheduled_for:
                    continue
                gap = abs((other.scheduled_for - task.scheduled_for).total_seconds()) / 60
                if gap < 30:
                    conflicts.append({
                        "type": "schedule_overlap", "task_id": str(other.id),
                        "reference": other.reference,
                        "message": f"{driver.full_name} already has {other.reference} "
                                   f"scheduled at {other.scheduled_for.strftime('%H:%M')}.",
                        "minutes_apart": round(gap),
                    })

    eta = None
    route_impact = None
    if vehicle is not None:
        if vehicle.lifecycle != VehicleLifecycle.ACTIVE:
            warnings.append(f"{vehicle.name} is {vehicle.lifecycle} and not available for work.")
        if vehicle.last_lat is not None and task.lat is not None:
            r = route_svc.calculate([(vehicle.last_lon, vehicle.last_lat), (task.lon, task.lat)])
            if r.ok:
                eta = now + timedelta(seconds=r.duration_s)
                route_impact = {
                    "distance_km": round(r.distance_m / 1000, 2),
                    "duration_minutes": round(r.duration_s / 60),
                    "via": r.street_names[:4],
                }
            else:
                warnings.append(r.message)
        if driver is not None and vehicle.driver_id and vehicle.driver_id != driver.id:
            conflicts.append({
                "type": "vehicle_driver_mismatch",
                "message": f"{vehicle.name} is currently assigned to a different driver. "
                           "Assigning will reassign the vehicle.",
            })

    sla_risk = None
    if task.sla_due_at and eta:
        margin = (task.sla_due_at - eta).total_seconds() / 60
        sla_risk = {"minutes_of_margin": round(margin),
                    "state": SlaState.BREACHED if margin < 0
                    else (SlaState.AT_RISK if margin < 15 else SlaState.ON_TRACK)}
        if margin < 0:
            conflicts.append({
                "type": "sla_breach",
                "message": f"Projected arrival is {abs(round(margin))} minutes after the "
                           f"SLA deadline.",
            })

    return {
        "task": {"id": str(task.id), "reference": task.reference, "title": task.title},
        "workload": workload,
        "eta": eta.isoformat() if eta else None,
        "estimated_completion": (eta + timedelta(minutes=task.service_minutes)).isoformat()
        if eta else None,
        "route_impact": route_impact,
        "sla": sla_risk,
        "conflicts": conflicts,
        "warnings": warnings,
        "has_conflict": bool(conflicts),
    }


async def assign(session: AsyncSession, *, org_id: uuid.UUID, task: Task,
                 driver: Driver | None, vehicle: Vehicle | None, actor=None,
                 build_route: bool = True, now: datetime | None = None) -> Task:
    """Assign driver+vehicle, build the route, and ripple the change outward."""
    now = now or datetime.now(timezone.utc)
    before = audit.snapshot(task, ["status", "driver_id", "vehicle_id"])
    previous_driver = task.driver_id

    task.driver_id = driver.id if driver else None
    task.vehicle_id = vehicle.id if vehicle else None
    if task.status in (TaskStatus.UNASSIGNED, TaskStatus.FAILED):
        task.status = TaskStatus.ASSIGNED
        task.assigned_at = now
    elif task.assigned_at is None:
        task.assigned_at = now

    # Keep vehicle<->driver consistent everywhere (spec 7 cross-module rule).
    if vehicle is not None and driver is not None and vehicle.driver_id != driver.id:
        vehicle.driver_id = driver.id
        await audit.timeline(
            session, organization_id=org_id, entity_type="vehicle", entity_id=vehicle.id,
            action="driver_assigned", actor=actor, occurred_at=now,
            description=f"{driver.full_name} assigned as driver.",
            related_type="driver", related_id=driver.id,
        )

    if build_route and vehicle is not None and task.lat is not None:
        await _build_task_route(session, org_id=org_id, task=task, vehicle=vehicle,
                                driver=driver, now=now)

    task.sla_state = sla_state(task, now=now)
    await session.flush()

    verb = "reassigned" if previous_driver and previous_driver != task.driver_id else "assigned"
    who = driver.full_name if driver else "nobody"
    await audit.timeline(
        session, organization_id=org_id, entity_type="task", entity_id=task.id,
        action=verb, actor=actor, occurred_at=now,
        description=f"Task {verb} to {who}"
                    + (f" with {vehicle.name}." if vehicle else "."),
        related_type="driver", related_id=driver.id if driver else None,
    )
    await audit.record(
        session, action=f"task.{verb}", organization_id=org_id, actor=actor,
        entity_type="task", entity_id=task.id, entity_label=task.reference,
        summary=f"{task.reference} {verb} to {who}",
        before=before, after=audit.snapshot(task, ["status", "driver_id", "vehicle_id"]),
    )
    if driver and driver.user_id:
        session.add(Notification(
            organization_id=org_id, user_id=driver.user_id,
            type=NotificationType.TASK_REASSIGNED if verb == "reassigned"
            else NotificationType.TASK_ASSIGNED,
            title=f"{'Reassigned' if verb == 'reassigned' else 'New task'}: {task.reference}",
            body=f"{task.title} — {task.address or ''}".strip(" —"),
            link=f"/driver/tasks/{task.id}", entity_type="task", entity_id=task.id,
        ))
    await bus.publish(org_id, ev.TASK_ASSIGNED, {
        "id": str(task.id), "reference": task.reference, "status": task.status,
        "driver_id": str(task.driver_id) if task.driver_id else None,
        "vehicle_id": str(task.vehicle_id) if task.vehicle_id else None,
    })
    return task


async def _build_task_route(session: AsyncSession, *, org_id, task: Task,
                            vehicle: Vehicle, driver: Driver | None, now: datetime) -> None:
    origin = (vehicle.last_lon, vehicle.last_lat)
    if origin[0] is None:
        return
    result = route_svc.calculate([origin, (task.lon, task.lat)])
    if not result.ok:
        return
    route = None
    if task.route_id:
        route = await session.get(Route, task.route_id)
    if route is None:
        route = Route(organization_id=org_id, name=f"Route for {task.reference}",
                      origin_lat=origin[1], origin_lon=origin[0],
                      origin_name=vehicle.last_street or "Current position",
                      dest_lat=task.lat, dest_lon=task.lon,
                      dest_name=task.address or task.title)
        session.add(route)
        await session.flush()
        task.route_id = route.id
    route.vehicle_id = vehicle.id
    route.driver_id = driver.id if driver else None
    route.origin_lat, route.origin_lon = origin[1], origin[0]
    route.dest_lat, route.dest_lon = task.lat, task.lon
    route.geometry = result.geometry
    route.distance_m = result.distance_m
    route.duration_s = result.duration_s
    route.legs = [{"distance_m": round(l.distance_m, 1),
                   "duration_s": round(l.duration_s, 1)} for l in result.legs]
    task.eta = now + timedelta(seconds=result.duration_s)


async def transition(session: AsyncSession, *, org_id: uuid.UUID, task: Task, target: str,
                     actor=None, actor_name: str | None = None, now: datetime | None = None,
                     note: str | None = None, strict: bool = True, **extra) -> Task:
    """Move a task through its lifecycle, recording the change everywhere."""
    now = now or datetime.now(timezone.utc)
    if task.status == target:
        return task
    if strict and not can_transition(task.status, target):
        raise HTTPException(
            http.HTTP_409_CONFLICT,
            f"A {task.status.replace('_', ' ')} task cannot move to "
            f"{target.replace('_', ' ')}.",
        )
    before = audit.snapshot(task, ["status"])
    previous = task.status
    task.status = target
    field = TIMESTAMP_FIELD.get(target)
    if field and getattr(task, field, None) is None:
        setattr(task, field, now)
    for k, v in extra.items():
        setattr(task, k, v)
    task.sla_state = sla_state(task, now=now)
    await session.flush()

    label = target.replace("_", " ")
    await audit.timeline(
        session, organization_id=org_id, entity_type="task", entity_id=task.id,
        action=target, actor=actor, actor_name=actor_name, occurred_at=now,
        description=note or f"Task moved to {label}.",
    )
    await audit.record(
        session, action="task.status_changed", organization_id=org_id, actor=actor,
        entity_type="task", entity_id=task.id, entity_label=task.reference,
        summary=f"{task.reference}: {previous.replace('_', ' ')} → {label}",
        before=before, after={"status": target},
    )
    event_map = {
        TaskStatus.ACCEPTED: ev.TASK_ACCEPTED, TaskStatus.EN_ROUTE: ev.TASK_STARTED,
        TaskStatus.COMPLETED: ev.TASK_COMPLETED, TaskStatus.FAILED: ev.TASK_FAILED,
    }
    await bus.publish(org_id, event_map.get(target, ev.TASK_UPDATED), {
        "id": str(task.id), "reference": task.reference, "status": target,
        "driver_id": str(task.driver_id) if task.driver_id else None,
        "vehicle_id": str(task.vehicle_id) if task.vehicle_id else None,
    })
    return task


async def refresh_sla(session: AsyncSession, *, org_id: uuid.UUID, task: Task,
                      org_settings: dict | None = None,
                      now: datetime | None = None) -> str:
    """Recompute SLA state; raise an alert the first time it turns bad."""
    now = now or datetime.now(timezone.utc)
    cfg = org_settings or {}
    previous = task.sla_state
    task.sla_state = sla_state(task, now=now,
                               at_risk_minutes=cfg.get("sla_at_risk_minutes", 15))
    if task.sla_state == previous:
        return task.sla_state
    if task.sla_state in (SlaState.AT_RISK, SlaState.BREACHED):
        remaining = sla_minutes_remaining(task, now)
        await alert_svc.raise_alert(
            session, org_id=org_id,
            code="sla_breach_risk" if task.sla_state == SlaState.AT_RISK else "task_delayed",
            severity=Severity.HIGH if task.sla_state == SlaState.AT_RISK else Severity.CRITICAL,
            title=f"{task.reference} SLA {'at risk' if task.sla_state == SlaState.AT_RISK else 'breached'}",
            detail=f"{task.title} — projected arrival "
                   f"{task.eta.strftime('%H:%M') if task.eta else 'unknown'}, "
                   f"deadline {task.sla_due_at.strftime('%H:%M') if task.sla_due_at else 'n/a'}.",
            vehicle_id=task.vehicle_id, driver_id=task.driver_id, task_id=task.id,
            lat=task.lat, lon=task.lon, dedupe_extra=f"task:{task.id}",
            evidence={"sla_due_at": task.sla_due_at.isoformat() if task.sla_due_at else None,
                      "eta": task.eta.isoformat() if task.eta else None,
                      "minutes_remaining": remaining},
            now=now,
        )
        await audit.timeline(
            session, organization_id=org_id, entity_type="task", entity_id=task.id,
            action="sla_changed", occurred_at=now,
            description=f"Task marked {task.sla_state.replace('_', ' ')}."
                        + (f" ETA moved to {task.eta.strftime('%H:%M')}." if task.eta else ""),
        )
    return task.sla_state
