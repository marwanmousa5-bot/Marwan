"""GPS device inventory - a `super_admin`-only domain (Section 4a item 2).

Customers never call into this module's mutating functions. The only
customer-visible surface is the read-only device summary attached to their
own vehicles, which is assembled in the vehicle serializer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.device import Device
from app.models.enums import AuditAction, DeviceStatus
from app.models.organization import Organization
from app.models.vehicle import Vehicle
from app.services import audit

#: Statuses a device may be moved to manually. ASSIGNED/ACTIVE are reached
#: through assign()/activate() so the vehicle link cannot drift out of step.
MANUAL_STATUSES = frozenset(
    {DeviceStatus.IN_STOCK, DeviceStatus.FAULTY, DeviceStatus.RETIRED}
)


def utcnow() -> datetime:
    return datetime.now(UTC)


async def list_devices(
    db: AsyncSession,
    *,
    status: DeviceStatus | None = None,
    organization_id: uuid.UUID | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Device], int]:
    stmt = sa.select(Device)
    if status is not None:
        stmt = stmt.where(Device.status == status)
    if organization_id is not None:
        stmt = stmt.where(Device.organization_id == organization_id)
    if search:
        pattern = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            sa.or_(
                sa.func.lower(Device.serial_number).like(pattern),
                sa.func.lower(sa.func.coalesce(Device.imei, "")).like(pattern),
                sa.func.lower(sa.func.coalesce(Device.model, "")).like(pattern),
            )
        )

    total = int(
        (await db.execute(sa.select(sa.func.count()).select_from(stmt.subquery())))
        .scalar_one()
    )
    result = await db.execute(
        stmt.order_by(Device.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all()), total


async def get_device(db: AsyncSession, device_id: uuid.UUID) -> Device:
    device = await db.get(Device, device_id)
    if device is None:
        raise NotFoundError("Device not found")
    return device


async def add_device(
    db: AsyncSession,
    *,
    serial_number: str,
    imei: str | None = None,
    model: str | None = None,
    firmware_version: str | None = None,
    notes: str | None = None,
    principal: Principal | None = None,
    request: Request | None = None,
) -> Device:
    """Receive a new unit into inventory."""
    serial = serial_number.strip()
    existing = await db.execute(
        sa.select(Device.id).where(Device.serial_number == serial).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError(f"A device with serial {serial} is already in inventory")

    if imei:
        clash = await db.execute(
            sa.select(Device.id).where(Device.imei == imei.strip()).limit(1)
        )
        if clash.scalar_one_or_none() is not None:
            raise ConflictError(f"A device with IMEI {imei} is already in inventory")

    device = Device(
        serial_number=serial,
        imei=imei.strip() if imei else None,
        model=model,
        firmware_version=firmware_version,
        notes=notes,
        status=DeviceStatus.IN_STOCK,
    )
    db.add(device)
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        entity_type="device",
        entity_id=device.id,
        summary=f"Device {device.serial_number} added to inventory",
        request=request,
    )
    return device


async def assign_device(
    db: AsyncSession,
    *,
    device_id: uuid.UUID,
    organization_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    activate: bool = True,
    principal: Principal | None = None,
    request: Request | None = None,
) -> Device:
    """Link a device to one vehicle inside one Organization.

    Once ACTIVE, the simulation engine treats that vehicle as live and starts
    producing position data for it (Section 6).
    """
    device = await get_device(db, device_id)
    if device.status in {DeviceStatus.FAULTY, DeviceStatus.RETIRED}:
        raise ValidationError(
            f"A {device.status} device cannot be assigned. Return it to stock first."
        )

    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise NotFoundError("Organization not found")

    vehicle = await db.get(Vehicle, vehicle_id)
    if vehicle is None or vehicle.organization_id != organization_id:
        raise NotFoundError("Vehicle not found in that organization")

    # One device per vehicle: displace any incumbent explicitly rather than
    # silently leaving two devices pointing at the same vehicle.
    incumbent = await db.execute(
        sa.select(Device)
        .where(Device.vehicle_id == vehicle_id, Device.id != device.id)
        .limit(1)
    )
    existing = incumbent.scalar_one_or_none()
    if existing is not None:
        raise ConflictError(
            f"Vehicle '{vehicle.name}' already has device {existing.serial_number} "
            "fitted. Unassign it first."
        )

    device.organization_id = organization_id
    device.vehicle_id = vehicle_id
    device.assigned_at = utcnow()
    device.status = DeviceStatus.ACTIVE if activate else DeviceStatus.ASSIGNED
    if activate:
        device.activated_at = utcnow()

    await audit.record(
        db,
        action=AuditAction.DEVICE_ASSIGNED,
        principal=principal,
        organization_id=organization_id,
        entity_type="device",
        entity_id=device.id,
        summary=(
            f"Device {device.serial_number} assigned to vehicle '{vehicle.name}' "
            f"at '{organization.name}'"
        ),
        changes={
            "after": {
                "organization_id": str(organization_id),
                "vehicle_id": str(vehicle_id),
                "status": str(device.status),
            }
        },
        request=request,
    )
    return device


async def unassign_device(
    db: AsyncSession,
    *,
    device_id: uuid.UUID,
    return_to_stock: bool = True,
    principal: Principal | None = None,
    request: Request | None = None,
) -> Device:
    device = await get_device(db, device_id)
    previous_org = device.organization_id
    previous_vehicle = device.vehicle_id

    device.organization_id = None
    device.vehicle_id = None
    device.assigned_at = None
    device.activated_at = None
    if return_to_stock and device.status not in {
        DeviceStatus.FAULTY,
        DeviceStatus.RETIRED,
    }:
        device.status = DeviceStatus.IN_STOCK

    await audit.record(
        db,
        action=AuditAction.DEVICE_UNASSIGNED,
        principal=principal,
        organization_id=previous_org,
        entity_type="device",
        entity_id=device.id,
        summary=f"Device {device.serial_number} unassigned",
        changes={
            "before": {
                "organization_id": str(previous_org) if previous_org else None,
                "vehicle_id": str(previous_vehicle) if previous_vehicle else None,
            },
            "after": {"status": str(device.status)},
        },
        request=request,
    )
    return device


async def set_device_status(
    db: AsyncSession,
    *,
    device_id: uuid.UUID,
    status: DeviceStatus,
    notes: str | None = None,
    principal: Principal | None = None,
    request: Request | None = None,
) -> Device:
    """Mark a device faulty/retired, or return it to stock."""
    if status not in MANUAL_STATUSES:
        raise ValidationError(
            "Use the assign endpoint to put a device into service; this endpoint "
            "only sets in_stock, faulty or retired."
        )

    device = await get_device(db, device_id)
    before = device.status
    previous_org = device.organization_id

    # A faulty or retired unit must stop being treated as live.
    if device.vehicle_id is not None:
        device.organization_id = None
        device.vehicle_id = None
        device.assigned_at = None
        device.activated_at = None

    device.status = status
    if notes:
        device.notes = notes

    await audit.record(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        organization_id=previous_org,
        entity_type="device",
        entity_id=device.id,
        summary=f"Device {device.serial_number} status {before} -> {status}",
        changes={"before": {"status": before}, "after": {"status": str(status)}},
        request=request,
    )
    return device


async def live_devices(db: AsyncSession) -> list[Device]:
    """Every device the simulation engine should be producing data for."""
    result = await db.execute(
        sa.select(Device).where(
            Device.status == DeviceStatus.ACTIVE, Device.vehicle_id.is_not(None)
        )
    )
    return list(result.scalars().all())
