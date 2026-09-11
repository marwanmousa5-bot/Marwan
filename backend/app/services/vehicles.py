"""Vehicle registry service - every query goes through the TenantScope."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal
from app.core.errors import ConflictError, NotFoundError
from app.core.tenancy import TenantScope
from app.models.driver import Driver
from app.models.enums import AuditAction, VehicleLiveStatus, VehicleStatus
from app.models.vehicle import Vehicle
from app.services import audit

AUDITED_FIELDS = [
    "name",
    "make",
    "model",
    "year",
    "vin",
    "license_plate",
    "vehicle_type",
    "fuel_type",
    "ownership",
    "status",
    "odometer_km",
    "primary_driver_id",
]

#: Below this speed a vehicle with a live device counts as idle, not moving.
MOVING_SPEED_THRESHOLD_KPH = 3.0


async def list_vehicles(
    db: AsyncSession,
    scope: TenantScope,
    *,
    status: VehicleStatus | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Vehicle], int]:
    stmt = scope.select(Vehicle)
    if status is not None:
        stmt = stmt.where(Vehicle.status == status)
    if search:
        pattern = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            sa.or_(
                sa.func.lower(Vehicle.name).like(pattern),
                sa.func.lower(Vehicle.license_plate).like(pattern),
                sa.func.lower(sa.func.coalesce(Vehicle.vin, "")).like(pattern),
            )
        )

    total_result = await db.execute(
        sa.select(sa.func.count()).select_from(stmt.subquery())
    )
    total = int(total_result.scalar_one())

    result = await db.execute(
        stmt.order_by(Vehicle.name).limit(limit).offset(offset)
    )
    return list(result.scalars().unique().all()), total


async def get_vehicle(
    db: AsyncSession, scope: TenantScope, vehicle_id: uuid.UUID
) -> Vehicle:
    return await scope.get_or_404(db, Vehicle, vehicle_id, label="Vehicle")


async def create_vehicle(
    db: AsyncSession,
    scope: TenantScope,
    *,
    data: dict,
    principal: Principal | None = None,
    request: Request | None = None,
) -> Vehicle:
    await _assert_plate_available(db, scope, data["license_plate"])
    if data.get("primary_driver_id"):
        await _assert_driver_in_scope(db, scope, data["primary_driver_id"])

    vehicle = Vehicle(**data)
    scope.assign(vehicle)
    db.add(vehicle)
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="vehicle",
        entity_id=vehicle.id,
        summary=f"Vehicle '{vehicle.name}' ({vehicle.license_plate}) created",
        changes={"after": audit.snapshot(vehicle, AUDITED_FIELDS)},
        request=request,
    )
    return vehicle


async def update_vehicle(
    db: AsyncSession,
    scope: TenantScope,
    *,
    vehicle_id: uuid.UUID,
    data: dict,
    principal: Principal | None = None,
    request: Request | None = None,
) -> Vehicle:
    vehicle = await get_vehicle(db, scope, vehicle_id)
    before = audit.snapshot(vehicle, AUDITED_FIELDS)

    if "license_plate" in data and data["license_plate"] != vehicle.license_plate:
        await _assert_plate_available(db, scope, data["license_plate"])
    if data.get("primary_driver_id"):
        await _assert_driver_in_scope(db, scope, data["primary_driver_id"])

    for key, value in data.items():
        setattr(vehicle, key, value)
    await db.flush()

    changes = audit.diff(before, audit.snapshot(vehicle, AUDITED_FIELDS))
    if changes:
        await audit.record(
            db,
            action=AuditAction.UPDATE,
            principal=principal,
            organization_id=scope.organization_id,
            entity_type="vehicle",
            entity_id=vehicle.id,
            summary=f"Vehicle '{vehicle.name}' updated",
            changes=changes,
            request=request,
        )
    return vehicle


async def retire_vehicle(
    db: AsyncSession,
    scope: TenantScope,
    *,
    vehicle_id: uuid.UUID,
    principal: Principal | None = None,
    request: Request | None = None,
) -> Vehicle:
    """Vehicles are retired, never hard-deleted: history must survive."""
    vehicle = await get_vehicle(db, scope, vehicle_id)
    vehicle.status = VehicleStatus.RETIRED
    await audit.record(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="vehicle",
        entity_id=vehicle.id,
        summary=f"Vehicle '{vehicle.name}' retired",
        request=request,
    )
    return vehicle


def live_status(
    vehicle: Vehicle,
    *,
    is_tracked: bool | None = None,
    has_active_alert: bool = False,
) -> VehicleLiveStatus:
    """Map-icon status for the Live Tracking view (Section 4b)."""
    tracked = vehicle.is_tracked if is_tracked is None else is_tracked
    if not tracked:
        return VehicleLiveStatus.NOT_TRACKED
    if has_active_alert:
        return VehicleLiveStatus.ALERT
    if (vehicle.last_speed_kph or 0.0) > MOVING_SPEED_THRESHOLD_KPH:
        return VehicleLiveStatus.MOVING
    return VehicleLiveStatus.IDLE


async def _assert_plate_available(
    db: AsyncSession, scope: TenantScope, plate: str
) -> None:
    result = await db.execute(
        scope.select(Vehicle).where(Vehicle.license_plate == plate).limit(1)
    )
    if result.scalar_one_or_none() is not None:
        raise ConflictError(f"A vehicle with plate {plate} already exists")


async def _assert_driver_in_scope(
    db: AsyncSession, scope: TenantScope, driver_id: uuid.UUID
) -> None:
    if await scope.get(db, Driver, driver_id) is None:
        raise NotFoundError("Driver not found")
