"""Vehicle registry API (customer-facing, tenant-scoped)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    Principal,
    get_tenant_scope,
    require_dashboard_user,
    require_org_admin,
)
from app.core.tenancy import TenantScope
from app.db.session import get_db
from app.models.enums import VehicleStatus
from app.models.vehicle import Vehicle
from app.schemas.common import Page
from app.schemas.vehicle import (
    VehicleCreate,
    VehicleDeviceOut,
    VehicleOut,
    VehicleUpdate,
)
from app.services import vehicles as vehicle_service

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


def serialize(vehicle: Vehicle, *, has_active_alert: bool = False) -> VehicleOut:
    """Attach the derived tracking fields the map and list views depend on.

    Columns are read explicitly rather than via ``from_attributes`` so that a
    just-created vehicle (whose ``device`` relationship has not been loaded)
    never triggers lazy IO inside serialization.
    """
    state = sa.inspect(vehicle)
    data = {attr.key: getattr(vehicle, attr.key) for attr in state.mapper.column_attrs}

    device = None if "device" in state.unloaded else vehicle.device
    is_tracked = bool(device and device.is_live)

    data["is_tracked"] = is_tracked
    data["live_status"] = vehicle_service.live_status(
        vehicle, is_tracked=is_tracked, has_active_alert=has_active_alert
    )
    if device is not None:
        # Read-only for customers: they can never mutate this (Section 9).
        data["device"] = VehicleDeviceOut(
            id=device.id,
            serial_number=device.serial_number,
            model=device.model,
            status=device.status,
            last_signal_at=device.last_signal_at,
        )
    return VehicleOut.model_validate(data)


@router.get("", response_model=Page[VehicleOut], summary="List vehicles")
async def list_vehicles(
    status_filter: VehicleStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> Page[VehicleOut]:
    items, total = await vehicle_service.list_vehicles(
        db, scope, status=status_filter, search=search, limit=limit, offset=offset
    )
    return Page[VehicleOut](
        items=[serialize(v) for v in items], total=total, limit=limit, offset=offset
    )


@router.post(
    "",
    response_model=VehicleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a vehicle to the registry",
)
async def create_vehicle(
    payload: VehicleCreate,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> VehicleOut:
    vehicle = await vehicle_service.create_vehicle(
        db,
        scope,
        data=payload.model_dump(exclude_unset=False),
        principal=principal,
        request=request,
    )
    return serialize(vehicle)


@router.get("/{vehicle_id}", response_model=VehicleOut, summary="Get one vehicle")
async def get_vehicle(
    vehicle_id: uuid.UUID,
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> VehicleOut:
    return serialize(await vehicle_service.get_vehicle(db, scope, vehicle_id))


@router.patch("/{vehicle_id}", response_model=VehicleOut, summary="Update a vehicle")
async def update_vehicle(
    vehicle_id: uuid.UUID,
    payload: VehicleUpdate,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> VehicleOut:
    vehicle = await vehicle_service.update_vehicle(
        db,
        scope,
        vehicle_id=vehicle_id,
        data=payload.model_dump(exclude_unset=True),
        principal=principal,
        request=request,
    )
    return serialize(vehicle)


@router.delete(
    "/{vehicle_id}",
    response_model=VehicleOut,
    summary="Retire a vehicle (never hard-deleted - history must survive)",
)
async def retire_vehicle(
    vehicle_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> VehicleOut:
    vehicle = await vehicle_service.retire_vehicle(
        db, scope, vehicle_id=vehicle_id, principal=principal, request=request
    )
    return serialize(vehicle)
