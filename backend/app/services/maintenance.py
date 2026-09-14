"""Maintenance engine: schedule evaluation, alerts, work orders, impact analysis."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (ACTIVE_TASK_STATUSES, MaintenanceStatus,
                            OPEN_WORK_ORDER_STATUSES, Priority, Severity,
                            VehicleLifecycle, WorkOrderStatus)
from app.models import (Alert, MaintenanceRecord, MaintenanceSchedule, Task,
                        Vehicle, WorkOrder, Workshop)
from app.services import alerts as alert_svc
from app.services import audit
from app.services.derive import maintenance_health, maintenance_status
from app.websocket import events as ev
from app.websocket.events import bus

STATUS_TO_ALERT = {
    MaintenanceStatus.DUE_SOON: ("maintenance_due_soon", Severity.LOW),
    MaintenanceStatus.DUE: ("maintenance_due", Severity.MEDIUM),
    MaintenanceStatus.OVERDUE: ("maintenance_overdue", Severity.HIGH),
    MaintenanceStatus.CRITICAL: ("maintenance_critical", Severity.CRITICAL),
}


def describe_due(schedule: MaintenanceSchedule, odometer: float,
                 today: date | None = None) -> str:
    today = today or date.today()
    bits = []
    km = schedule.km_remaining(odometer)
    if km is not None:
        bits.append(f"{abs(km):,.0f} km {'overdue' if km < 0 else 'remaining'}")
    days = schedule.days_remaining(today)
    if days is not None:
        bits.append(f"{abs(days)} days {'overdue' if days < 0 else 'remaining'}")
    return " · ".join(bits) or "No threshold set"


async def evaluate_vehicle(session: AsyncSession, *, org_id: uuid.UUID, vehicle: Vehicle,
                           org_settings: dict | None = None,
                           now: datetime | None = None) -> list[MaintenanceSchedule]:
    """Recompute every schedule for one vehicle and raise alerts on transitions."""
    now = now or datetime.now(timezone.utc)
    today = now.date()
    cfg = org_settings or {}
    schedules = (await session.execute(
        select(MaintenanceSchedule).where(
            MaintenanceSchedule.vehicle_id == vehicle.id,
            MaintenanceSchedule.is_active.is_(True),
        )
    )).scalars().all()

    changed: list[MaintenanceSchedule] = []
    for s in schedules:
        if s.status == MaintenanceStatus.IN_WORKSHOP:
            continue
        new_status = maintenance_status(
            s, vehicle.odometer_km, today=today,
            due_soon_km=cfg.get("maintenance_due_soon_km", 500),
            due_soon_days=cfg.get("maintenance_due_soon_days", 14),
        )
        if new_status == s.status:
            continue
        previous, s.status = s.status, new_status
        changed.append(s)
        if new_status in STATUS_TO_ALERT and s.last_alerted_status != new_status:
            code, severity = STATUS_TO_ALERT[new_status]
            s.last_alerted_status = new_status
            await alert_svc.raise_alert(
                session, org_id=org_id, code=code, severity=severity,
                title=f"{vehicle.name}: {s.name} {new_status.replace('_', ' ')}",
                detail=f"{s.name} on {vehicle.name} ({vehicle.plate}) is "
                       f"{new_status.replace('_', ' ')} - {describe_due(s, vehicle.odometer_km, today)}.",
                vehicle_id=vehicle.id, driver_id=vehicle.driver_id,
                dedupe_extra=f"schedule:{s.id}",
                evidence={"schedule": s.name, "status": new_status,
                          "odometer_km": round(vehicle.odometer_km, 1),
                          "due_at_km": s.due_at_km,
                          "due_at_date": s.due_at_date.isoformat() if s.due_at_date else None},
                now=now,
            )
            await bus.publish(org_id, ev.MAINTENANCE_DUE, {
                "vehicle_id": str(vehicle.id), "schedule_id": str(s.id),
                "status": new_status, "name": s.name,
            })
        await audit.timeline(
            session, organization_id=org_id, entity_type="vehicle", entity_id=vehicle.id,
            action="maintenance_status_changed",
            description=f"{s.name}: {previous.replace('_', ' ')} → {new_status.replace('_', ' ')}.",
            occurred_at=now, meta={"schedule_id": str(s.id)},
        )
    return changed


async def vehicle_health(session: AsyncSession, vehicle: Vehicle,
                         org_settings: dict | None = None) -> dict:
    """Maintenance health score plus the counts behind it (spec 7.2)."""
    rows = (await session.execute(
        select(MaintenanceSchedule.status, func.count()).where(
            MaintenanceSchedule.vehicle_id == vehicle.id,
            MaintenanceSchedule.is_active.is_(True),
        ).group_by(MaintenanceSchedule.status)
    )).all()
    counts = {status: n for status, n in rows}
    open_wo = (await session.execute(
        select(func.count()).select_from(WorkOrder).where(
            WorkOrder.vehicle_id == vehicle.id,
            WorkOrder.status.in_(OPEN_WORK_ORDER_STATUSES),
        )
    )).scalar_one()
    # a category serviced 3+ times in 180 days counts as a repeat failure
    since = date.today() - timedelta(days=180)
    repeats = (await session.execute(
        select(MaintenanceRecord.category, func.count()).where(
            MaintenanceRecord.vehicle_id == vehicle.id,
            MaintenanceRecord.service_date >= since,
        ).group_by(MaintenanceRecord.category).having(func.count() >= 3)
    )).all()

    score = maintenance_health(
        overdue=counts.get(MaintenanceStatus.OVERDUE, 0),
        critical=counts.get(MaintenanceStatus.CRITICAL, 0),
        due=counts.get(MaintenanceStatus.DUE, 0),
        due_soon=counts.get(MaintenanceStatus.DUE_SOON, 0),
        open_work_orders=open_wo,
        repeat_failures=len(repeats),
        weights=(org_settings or {}).get("maintenance_health_weights"),
    )
    return {
        "score": score, "counts": counts, "open_work_orders": open_wo,
        "repeat_categories": [{"category": c, "count": n} for c, n in repeats],
    }


async def impact_analysis(session: AsyncSession, *, org_id: uuid.UUID, vehicle: Vehicle,
                          start: datetime, duration_minutes: int) -> dict:
    """What does taking this vehicle off the road actually cost? (spec 7.13/7.14)"""
    end = start + timedelta(minutes=duration_minutes)
    conflicting = (await session.execute(
        select(Task).where(
            Task.organization_id == org_id,
            Task.vehicle_id == vehicle.id,
            Task.status.in_(ACTIVE_TASK_STATUSES + (
                __import__("app.core.enums", fromlist=["TaskStatus"]).TaskStatus.UNASSIGNED,)),
            Task.scheduled_for.isnot(None),
            Task.scheduled_for >= start - timedelta(hours=1),
            Task.scheduled_for <= end,
        ).order_by(Task.scheduled_for)
    )).scalars().all()

    # candidate replacement: an active vehicle of the same type with the lightest load
    candidates = (await session.execute(
        select(Vehicle).where(
            Vehicle.organization_id == org_id,
            Vehicle.id != vehicle.id,
            Vehicle.lifecycle == VehicleLifecycle.ACTIVE,
            Vehicle.type == vehicle.type,
        )
    )).scalars().all()
    alternative = None
    if candidates:
        loads = []
        for c in candidates:
            n = (await session.execute(
                select(func.count()).select_from(Task).where(
                    Task.vehicle_id == c.id,
                    Task.status.in_(ACTIVE_TASK_STATUSES),
                )
            )).scalar_one()
            loads.append((n, c))
        loads.sort(key=lambda r: r[0])
        n, best = loads[0]
        alternative = {"id": str(best.id), "name": best.name, "plate": best.plate,
                       "active_tasks": n}

    return {
        "vehicle": {"id": str(vehicle.id), "name": vehicle.name, "plate": vehicle.plate},
        "window": {"start": start.isoformat(), "end": end.isoformat(),
                   "duration_minutes": duration_minutes},
        "affected_tasks": [
            {"id": str(t.id), "reference": t.reference, "title": t.title,
             "scheduled_for": t.scheduled_for.isoformat() if t.scheduled_for else None,
             "priority": t.priority, "status": t.status}
            for t in conflicting
        ],
        "affected_task_count": len(conflicting),
        "has_conflict": bool(conflicting),
        "alternative_vehicle": alternative,
    }


async def apply_work_order_costs(work_order: WorkOrder) -> None:
    work_order.parts_cost = round(sum(p.quantity * p.unit_cost for p in work_order.parts), 2)
    work_order.labor_cost = round(work_order.labor_hours * work_order.labor_rate, 2)
    work_order.total_cost = round(work_order.parts_cost + work_order.labor_cost, 2)


def next_reference(prefix: str, count: int) -> str:
    return f"{prefix}-{count + 1:05d}"
