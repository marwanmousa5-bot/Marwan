"""Platform Admin Console API - `super_admin` only (Section 4a).

This is the only place an Organization or its first Org Admin can be created,
and (from Phase 2) the only place GPS devices are managed.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal, require_super_admin
from app.core.errors import NotFoundError, PermissionDeniedError
from app.db.session import get_db
from app.models.device import Device
from app.models.driver import Driver
from app.models.enums import (
    AuditAction,
    DeviceStatus,
    OrganizationStatus,
    UserRole,
    UserStatus,
)
from app.models.organization import Organization
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.auth import TokenPair, UserOut
from app.schemas.common import Page
from app.schemas.device import (
    DeviceAssign,
    DeviceCreate,
    DeviceDetailOut,
    DeviceStatusUpdate,
)
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationHealth,
    OrganizationOut,
    OrganizationProvisionResponse,
    OrganizationUpdate,
)
from app.schemas.platform import (
    ImpersonationResponse,
    PlatformOverview,
    ResendActivationResponse,
)
from app.services import audit, provisioning
from app.services import auth as auth_service
from app.services import devices as device_service

router = APIRouter(prefix="/platform-admin", tags=["platform-admin"])


@router.get(
    "/overview",
    response_model=PlatformOverview,
    summary="Platform-wide counts (Section 4a item 4)",
)
async def overview(
    _: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> PlatformOverview:
    async def _count(stmt: sa.Select) -> int:
        return int((await db.execute(stmt)).scalar_one())

    return PlatformOverview(
        total_organizations=await _count(
            sa.select(sa.func.count()).select_from(Organization)
        ),
        active_organizations=await _count(
            sa.select(sa.func.count())
            .select_from(Organization)
            .where(Organization.status == OrganizationStatus.ACTIVE)
        ),
        total_vehicles=await _count(sa.select(sa.func.count()).select_from(Vehicle)),
        total_drivers=await _count(sa.select(sa.func.count()).select_from(Driver)),
        total_users=await _count(sa.select(sa.func.count()).select_from(User)),
        total_devices=await _count(sa.select(sa.func.count()).select_from(Device)),
        active_devices=await _count(
            sa.select(sa.func.count())
            .select_from(Device)
            .where(Device.status == DeviceStatus.ACTIVE)
        ),
        devices_in_stock=await _count(
            sa.select(sa.func.count())
            .select_from(Device)
            .where(Device.status == DeviceStatus.IN_STOCK)
        ),
    )


@router.get(
    "/organizations",
    response_model=list[OrganizationHealth],
    summary="List all organizations with health indicators",
)
async def list_organizations(
    search: str | None = Query(default=None, max_length=120),
    status_filter: OrganizationStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> list[OrganizationHealth]:
    stmt = sa.select(Organization)
    if search:
        pattern = f"%{search.strip().lower()}%"
        stmt = stmt.where(sa.func.lower(Organization.name).like(pattern))
    if status_filter is not None:
        stmt = stmt.where(Organization.status == status_filter)

    result = await db.execute(stmt.order_by(Organization.name).limit(limit).offset(offset))
    organizations = list(result.scalars().all())
    if not organizations:
        return []

    org_ids = [o.id for o in organizations]

    async def _grouped(stmt_: sa.Select) -> dict[uuid.UUID, int]:
        rows = await db.execute(stmt_)
        return {row[0]: int(row[1]) for row in rows.all()}

    vehicle_counts = await _grouped(
        sa.select(Vehicle.organization_id, sa.func.count())
        .where(Vehicle.organization_id.in_(org_ids))
        .group_by(Vehicle.organization_id)
    )
    device_counts = await _grouped(
        sa.select(Device.organization_id, sa.func.count())
        .where(
            Device.organization_id.in_(org_ids),
            Device.status == DeviceStatus.ACTIVE,
        )
        .group_by(Device.organization_id)
    )
    user_counts = await _grouped(
        sa.select(User.organization_id, sa.func.count())
        .where(User.organization_id.in_(org_ids))
        .group_by(User.organization_id)
    )
    last_login_rows = await db.execute(
        sa.select(User.organization_id, sa.func.max(User.last_login_at))
        .where(User.organization_id.in_(org_ids))
        .group_by(User.organization_id)
    )
    last_logins = {row[0]: row[1] for row in last_login_rows.all()}

    return [
        OrganizationHealth(
            organization=OrganizationOut.model_validate(org),
            vehicle_count=vehicle_counts.get(org.id, 0),
            active_device_count=device_counts.get(org.id, 0),
            user_count=user_counts.get(org.id, 0),
            last_login_at=last_logins.get(org.id),
        )
        for org in organizations
    ]


@router.post(
    "/organizations",
    response_model=OrganizationProvisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Provision a new customer organization and its first Org Admin",
)
async def create_organization(
    payload: OrganizationCreate,
    request: Request,
    principal: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> OrganizationProvisionResponse:
    organization, admin, activation_url = await provisioning.create_organization(
        db,
        name=payload.name,
        admin_email=str(payload.admin_email),
        admin_full_name=payload.admin_full_name,
        industry=payload.industry,
        timezone_name=payload.timezone,
        contact_name=payload.contact_name,
        contact_email=str(payload.contact_email) if payload.contact_email else None,
        contact_phone=payload.contact_phone,
        plan=payload.plan,
        principal=principal,
        request=request,
    )
    return OrganizationProvisionResponse(
        organization=OrganizationOut.model_validate(organization),
        admin_user=UserOut.model_validate(admin),
        activation_url=activation_url,
    )


@router.get(
    "/organizations/{organization_id}",
    response_model=OrganizationOut,
    summary="Get one organization",
)
async def get_organization(
    organization_id: uuid.UUID,
    _: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> OrganizationOut:
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise NotFoundError("Organization not found")
    return OrganizationOut.model_validate(organization)


@router.patch(
    "/organizations/{organization_id}",
    response_model=OrganizationOut,
    summary="Edit an organization",
)
async def update_organization(
    organization_id: uuid.UUID,
    payload: OrganizationUpdate,
    request: Request,
    principal: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> OrganizationOut:
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise NotFoundError("Organization not found")

    fields = ["name", "industry", "timezone", "contact_name", "contact_email",
              "contact_phone", "logo_url", "plan"]
    before = audit.snapshot(organization, fields)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(organization, key, value)
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        organization_id=organization.id,
        entity_type="organization",
        entity_id=organization.id,
        summary=f"Organization '{organization.name}' edited by platform staff",
        changes=audit.diff(before, audit.snapshot(organization, fields)),
        request=request,
    )
    return OrganizationOut.model_validate(organization)


@router.post(
    "/organizations/{organization_id}/suspend",
    response_model=OrganizationOut,
    summary="Suspend an organization (blocks all of its logins)",
)
async def suspend_organization(
    organization_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> OrganizationOut:
    organization = await provisioning.set_organization_status(
        db,
        organization_id=organization_id,
        status=OrganizationStatus.SUSPENDED,
        principal=principal,
        request=request,
    )
    return OrganizationOut.model_validate(organization)


@router.post(
    "/organizations/{organization_id}/reactivate",
    response_model=OrganizationOut,
    summary="Reactivate a suspended organization",
)
async def reactivate_organization(
    organization_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> OrganizationOut:
    organization = await provisioning.set_organization_status(
        db,
        organization_id=organization_id,
        status=OrganizationStatus.ACTIVE,
        principal=principal,
        request=request,
    )
    return OrganizationOut.model_validate(organization)


@router.get(
    "/organizations/{organization_id}/users",
    response_model=list[UserOut],
    summary="List an organization's users",
)
async def list_organization_users(
    organization_id: uuid.UUID,
    _: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> list[UserOut]:
    result = await db.execute(
        sa.select(User)
        .where(User.organization_id == organization_id)
        .order_by(User.full_name)
    )
    return [UserOut.model_validate(u) for u in result.scalars().all()]


@router.post(
    "/users/{user_id}/activation-link",
    response_model=ResendActivationResponse,
    summary="Re-issue a one-time activation link for a customer user",
)
async def reissue_activation_link(
    user_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ResendActivationResponse:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    if user.role == UserRole.SUPER_ADMIN:
        raise PermissionDeniedError(
            "Platform staff accounts cannot be re-activated from this endpoint"
        )

    url, _token = await auth_service.create_activation_link(
        db, user=user, purpose="activation", issued_by_user_id=principal.user_id
    )
    user.status = UserStatus.PENDING_ACTIVATION
    await audit.record(
        db,
        action=AuditAction.PASSWORD_RESET_REQUESTED,
        principal=principal,
        organization_id=user.organization_id,
        entity_type="user",
        entity_id=user.id,
        summary=f"Activation link re-issued for {user.email}",
        request=request,
    )
    return ResendActivationResponse(user=UserOut.model_validate(user), activation_url=url)


@router.post(
    "/organizations/{organization_id}/impersonate",
    response_model=ImpersonationResponse,
    summary="Log in as an organization's admin for support (audited)",
)
async def impersonate_organization(
    organization_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ImpersonationResponse:
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise NotFoundError("Organization not found")

    result = await db.execute(
        sa.select(User)
        .where(
            User.organization_id == organization_id,
            User.role == UserRole.ORG_ADMIN,
            User.status == UserStatus.ACTIVE,
        )
        .order_by(User.created_at)
        .limit(1)
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise NotFoundError(
            "This organization has no activated administrator to impersonate yet"
        )

    access, refresh = await auth_service.issue_tokens(
        db, user=target, impersonator_id=principal.user_id
    )
    # Every impersonation event is logged for audit purposes (Section 4a).
    await audit.record(
        db,
        action=AuditAction.IMPERSONATION_STARTED,
        principal=principal,
        organization_id=organization.id,
        entity_type="user",
        entity_id=target.id,
        summary=(
            f"{principal.email} started impersonating {target.email} "
            f"at '{organization.name}'"
        ),
        request=request,
    )
    from app.core.config import settings

    return ImpersonationResponse(
        organization=OrganizationOut.model_validate(organization),
        impersonated_user=UserOut.model_validate(target),
        tokens=TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=settings.access_token_expire_minutes * 60,
        ),
    )


# ---------------------------------------------------------------------------
# Device inventory (Section 4a item 2)
#
# Every route here is `super_admin`-only. Customers get read-only visibility
# of the device fitted to their own vehicle through `/vehicles`, and have no
# way to add, remove or reassign one (Section 9).
# ---------------------------------------------------------------------------


async def _decorate(db: AsyncSession, devices: list[Device]) -> list[DeviceDetailOut]:
    """Attach organization and vehicle names for the inventory table."""
    org_ids = {d.organization_id for d in devices if d.organization_id}
    vehicle_ids = {d.vehicle_id for d in devices if d.vehicle_id}

    org_names: dict[uuid.UUID, str] = {}
    if org_ids:
        rows = await db.execute(
            sa.select(Organization.id, Organization.name).where(
                Organization.id.in_(org_ids)
            )
        )
        org_names = {row[0]: row[1] for row in rows.all()}

    vehicles: dict[uuid.UUID, tuple[str, str]] = {}
    if vehicle_ids:
        rows = await db.execute(
            sa.select(Vehicle.id, Vehicle.name, Vehicle.license_plate).where(
                Vehicle.id.in_(vehicle_ids)
            )
        )
        vehicles = {row[0]: (row[1], row[2]) for row in rows.all()}

    out: list[DeviceDetailOut] = []
    for device in devices:
        detail = DeviceDetailOut.model_validate(device)
        if device.organization_id:
            detail.organization_name = org_names.get(device.organization_id)
        if device.vehicle_id and device.vehicle_id in vehicles:
            detail.vehicle_name, detail.vehicle_plate = vehicles[device.vehicle_id]
        out.append(detail)
    return out


@router.get(
    "/devices",
    response_model=Page[DeviceDetailOut],
    summary="GPS device inventory",
)
async def list_devices(
    status_filter: DeviceStatus | None = Query(default=None, alias="status"),
    organization_id: uuid.UUID | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> Page[DeviceDetailOut]:
    devices, total = await device_service.list_devices(
        db,
        status=status_filter,
        organization_id=organization_id,
        search=search,
        limit=limit,
        offset=offset,
    )
    return Page[DeviceDetailOut](
        items=await _decorate(db, devices), total=total, limit=limit, offset=offset
    )


@router.post(
    "/devices",
    response_model=DeviceDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Receive a new device into inventory",
)
async def add_device(
    payload: DeviceCreate,
    request: Request,
    principal: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> DeviceDetailOut:
    device = await device_service.add_device(
        db,
        serial_number=payload.serial_number,
        imei=payload.imei,
        model=payload.model,
        firmware_version=payload.firmware_version,
        notes=payload.notes,
        principal=principal,
        request=request,
    )
    return (await _decorate(db, [device]))[0]


@router.post(
    "/devices/{device_id}/assign",
    response_model=DeviceDetailOut,
    summary="Fit a device to a customer's vehicle and take it live",
)
async def assign_device(
    device_id: uuid.UUID,
    payload: DeviceAssign,
    request: Request,
    principal: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> DeviceDetailOut:
    device = await device_service.assign_device(
        db,
        device_id=device_id,
        organization_id=payload.organization_id,
        vehicle_id=payload.vehicle_id,
        activate=payload.activate,
        principal=principal,
        request=request,
    )
    return (await _decorate(db, [device]))[0]


@router.post(
    "/devices/{device_id}/unassign",
    response_model=DeviceDetailOut,
    summary="Remove a device from a vehicle and return it to stock",
)
async def unassign_device(
    device_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> DeviceDetailOut:
    device = await device_service.unassign_device(
        db, device_id=device_id, principal=principal, request=request
    )
    return (await _decorate(db, [device]))[0]


@router.patch(
    "/devices/{device_id}/status",
    response_model=DeviceDetailOut,
    summary="Mark a device in stock, faulty or retired",
)
async def update_device_status(
    device_id: uuid.UUID,
    payload: DeviceStatusUpdate,
    request: Request,
    principal: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> DeviceDetailOut:
    device = await device_service.set_device_status(
        db,
        device_id=device_id,
        status=payload.status,
        notes=payload.notes,
        principal=principal,
        request=request,
    )
    return (await _decorate(db, [device]))[0]


@router.get(
    "/organizations/{organization_id}/vehicles",
    response_model=list[dict],
    summary="An organization's vehicles, for the device assignment picker",
)
async def list_organization_vehicles(
    organization_id: uuid.UUID,
    _: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(
        sa.select(Vehicle.id, Vehicle.name, Vehicle.license_plate)
        .where(Vehicle.organization_id == organization_id)
        .order_by(Vehicle.name)
    )
    return [
        {"id": str(row[0]), "name": row[1], "license_plate": row[2]}
        for row in result.all()
    ]
