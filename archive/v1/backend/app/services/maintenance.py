"""Preventive maintenance scheduling and work orders (Section 4 item 6)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal
from app.core.errors import NotFoundError, ValidationError
from app.core.tenancy import TenantScope
from app.models.enums import (
    AuditAction,
    MaintenanceIntervalType,
    VehicleStatus,
    WorkOrderStatus,
)
from app.models.maintenance import MaintenanceSchedule, ServiceRecord, WorkOrder
from app.models.vehicle import Vehicle
from app.services import audit


def utcnow() -> datetime:
    return datetime.now(UTC)


def compute_next_due(
    schedule: MaintenanceSchedule, vehicle: Vehicle
) -> tuple[float | None, date | None]:
    """Work out when this schedule next falls due.

    Mileage schedules count from the last service reading, falling back to the
    vehicle's current odometer for a schedule that has never been serviced -
    otherwise a brand-new schedule on a high-mileage vehicle would look
    immediately overdue.
    """
    next_km: float | None = None
    next_date: date | None = None

    if schedule.interval_type == MaintenanceIntervalType.MILEAGE:
        if not schedule.interval_km:
            raise ValidationError("A mileage-based schedule needs an interval in km")
        base_km = (
            schedule.last_service_odometer_km
            if schedule.last_service_odometer_km is not None
            else (vehicle.odometer_km or 0.0)
        )
        next_km = base_km + schedule.interval_km
    else:
        if not schedule.interval_days:
            raise ValidationError("A time-based schedule needs an interval in days")
        base_date = schedule.last_service_date or utcnow().date()
        next_date = base_date + timedelta(days=schedule.interval_days)

    return next_km, next_date


async def list_schedules(
    db: AsyncSession, scope: TenantScope, *, vehicle_id: uuid.UUID | None = None
) -> list[MaintenanceSchedule]:
    stmt = scope.select(MaintenanceSchedule)
    if vehicle_id is not None:
        stmt = stmt.where(MaintenanceSchedule.vehicle_id == vehicle_id)
    result = await db.execute(stmt.order_by(MaintenanceSchedule.name))
    return list(result.scalars().all())


async def create_schedule(
    db: AsyncSession,
    scope: TenantScope,
    *,
    data: dict,
    principal: Principal | None = None,
    request: Request | None = None,
) -> MaintenanceSchedule:
    vehicle = await scope.get(db, Vehicle, data["vehicle_id"])
    if vehicle is None:
        raise NotFoundError("Vehicle not found")

    schedule = MaintenanceSchedule(**data)
    scope.assign(schedule)
    schedule.next_due_odometer_km, schedule.next_due_date = compute_next_due(
        schedule, vehicle
    )
    db.add(schedule)
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="maintenance_schedule",
        entity_id=schedule.id,
        summary=f"Maintenance schedule '{schedule.name}' created for {vehicle.name}",
        request=request,
    )
    return schedule


async def update_schedule(
    db: AsyncSession,
    scope: TenantScope,
    *,
    schedule_id: uuid.UUID,
    data: dict,
    principal: Principal | None = None,
    request: Request | None = None,
) -> MaintenanceSchedule:
    schedule = await scope.get_or_404(
        db, MaintenanceSchedule, schedule_id, label="Maintenance schedule"
    )
    for key, value in data.items():
        setattr(schedule, key, value)

    vehicle = await scope.get(db, Vehicle, schedule.vehicle_id)
    if vehicle is not None:
        schedule.next_due_odometer_km, schedule.next_due_date = compute_next_due(
            schedule, vehicle
        )
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="maintenance_schedule",
        entity_id=schedule.id,
        summary=f"Maintenance schedule '{schedule.name}' updated",
        request=request,
    )
    return schedule


async def list_work_orders(
    db: AsyncSession,
    scope: TenantScope,
    *,
    vehicle_id: uuid.UUID | None = None,
    status: WorkOrderStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[WorkOrder], int]:
    stmt = scope.select(WorkOrder)
    if vehicle_id is not None:
        stmt = stmt.where(WorkOrder.vehicle_id == vehicle_id)
    if status is not None:
        stmt = stmt.where(WorkOrder.status == status)

    total = int(
        (await db.execute(sa.select(sa.func.count()).select_from(stmt.subquery())))
        .scalar_one()
    )
    result = await db.execute(
        stmt.order_by(WorkOrder.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all()), total


async def create_work_order(
    db: AsyncSession,
    scope: TenantScope,
    *,
    data: dict,
    principal: Principal | None = None,
    request: Request | None = None,
) -> WorkOrder:
    vehicle = await scope.get(db, Vehicle, data["vehicle_id"])
    if vehicle is None:
        raise NotFoundError("Vehicle not found")

    work_order = WorkOrder(
        **data, created_by_user_id=principal.user_id if principal else None
    )
    scope.assign(work_order)
    db.add(work_order)
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="work_order",
        entity_id=work_order.id,
        summary=f"Work order '{work_order.title}' opened for {vehicle.name}",
        request=request,
    )
    return work_order


async def update_work_order(
    db: AsyncSession,
    scope: TenantScope,
    *,
    work_order_id: uuid.UUID,
    data: dict,
    principal: Principal | None = None,
    request: Request | None = None,
) -> WorkOrder:
    work_order = await scope.get_or_404(
        db, WorkOrder, work_order_id, label="Work order"
    )
    before_status = work_order.status

    for key, value in data.items():
        setattr(work_order, key, value)

    labour = float(work_order.labour_cost or 0)
    parts = float(work_order.parts_cost or 0)
    if labour or parts:
        work_order.total_cost = labour + parts

    # Completing a work order is what actually advances the schedule and
    # writes history - doing it here keeps the two from drifting apart.
    if (
        work_order.status == WorkOrderStatus.COMPLETED
        and before_status != WorkOrderStatus.COMPLETED
    ):
        await _complete_work_order(db, scope, work_order)

    await db.flush()
    await audit.record(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="work_order",
        entity_id=work_order.id,
        summary=f"Work order '{work_order.title}': {before_status} -> {work_order.status}",
        changes={
            "before": {"status": before_status},
            "after": {"status": str(work_order.status)},
        },
        request=request,
    )
    return work_order


async def _complete_work_order(
    db: AsyncSession, scope: TenantScope, work_order: WorkOrder
) -> None:
    now = utcnow()
    work_order.completed_at = work_order.completed_at or now

    vehicle = await scope.get(db, Vehicle, work_order.vehicle_id)
    odometer = work_order.odometer_km or (vehicle.odometer_km if vehicle else None)

    db.add(
        ServiceRecord(
            organization_id=scope.organization_id,
            vehicle_id=work_order.vehicle_id,
            work_order_id=work_order.id,
            performed_on=now.date(),
            odometer_km=odometer,
            summary=work_order.title,
            total_cost=work_order.total_cost,
            details={"vendor": work_order.vendor} if work_order.vendor else None,
        )
    )

    if vehicle is not None and vehicle.status == VehicleStatus.IN_MAINTENANCE:
        vehicle.status = VehicleStatus.ACTIVE

    if work_order.schedule_id:
        schedule = await scope.get(db, MaintenanceSchedule, work_order.schedule_id)
        if schedule is not None and vehicle is not None:
            schedule.last_service_date = now.date()
            if odometer is not None:
                schedule.last_service_odometer_km = odometer
            schedule.next_due_odometer_km, schedule.next_due_date = compute_next_due(
                schedule, vehicle
            )


async def list_service_records(
    db: AsyncSession, scope: TenantScope, *, vehicle_id: uuid.UUID | None = None
) -> list[ServiceRecord]:
    stmt = scope.select(ServiceRecord)
    if vehicle_id is not None:
        stmt = stmt.where(ServiceRecord.vehicle_id == vehicle_id)
    result = await db.execute(stmt.order_by(ServiceRecord.performed_on.desc()))
    return list(result.scalars().all())
