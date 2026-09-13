"""Customer-side Organization endpoints: own profile, settings and users.

An Org Admin can only ever see and change their OWN Organization - the id is
never accepted from the client.
"""

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
from app.core.errors import NotFoundError
from app.core.tenancy import TenantScope
from app.db.session import get_db
from app.models.enums import AuditAction, UserRole, UserStatus
from app.models.organization import Organization, OrganizationSettings
from app.schemas.auth import InviteUserRequest, InviteUserResponse, UserOut
from app.schemas.organization import (
    OrganizationOut,
    OrganizationSettingsOut,
    OrganizationSettingsUpdate,
    OrganizationUpdate,
)
from app.services import audit
from app.services import users as user_service

router = APIRouter(prefix="/organization", tags=["organization"])


async def _load_settings(
    db: AsyncSession, scope: TenantScope
) -> OrganizationSettings:
    result = await db.execute(
        sa.select(OrganizationSettings)
        .where(OrganizationSettings.organization_id == scope.organization_id)
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        # Self-heal for Organizations provisioned before settings existed.
        row = OrganizationSettings(organization_id=scope.organization_id)
        db.add(row)
        await db.flush()
    return row


@router.get("", response_model=OrganizationOut, summary="Your organization profile")
async def get_organization(
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> OrganizationOut:
    organization = await db.get(Organization, scope.organization_id)
    if organization is None:
        raise NotFoundError("Organization not found")
    return OrganizationOut.model_validate(organization)


@router.patch("", response_model=OrganizationOut, summary="Update your organization")
async def update_organization(
    payload: OrganizationUpdate,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> OrganizationOut:
    organization = await db.get(Organization, scope.organization_id)
    if organization is None:
        raise NotFoundError("Organization not found")

    fields = ["name", "industry", "timezone", "contact_name", "contact_email",
              "contact_phone", "logo_url"]
    before = audit.snapshot(organization, fields)
    # ``plan`` is deliberately not settable by a customer - billing is out of
    # scope and the field exists only for a future phase (Section 2).
    for key, value in payload.model_dump(exclude_unset=True, exclude={"plan"}).items():
        setattr(organization, key, value)
    await db.flush()

    changes = audit.diff(before, audit.snapshot(organization, fields))
    if changes:
        await audit.record(
            db,
            action=AuditAction.UPDATE,
            principal=principal,
            organization_id=organization.id,
            entity_type="organization",
            entity_id=organization.id,
            summary="Organization profile updated",
            changes=changes,
            request=request,
        )
    return OrganizationOut.model_validate(organization)


@router.get(
    "/settings",
    response_model=OrganizationSettingsOut,
    summary="Organization settings (point weights, thresholds, leaderboard)",
)
async def get_settings(
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> OrganizationSettingsOut:
    return OrganizationSettingsOut.model_validate(await _load_settings(db, scope))


@router.patch(
    "/settings",
    response_model=OrganizationSettingsOut,
    summary="Tune organization settings (Org Admin only)",
)
async def update_settings(
    payload: OrganizationSettingsUpdate,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> OrganizationSettingsOut:
    row = await _load_settings(db, scope)
    fields = [
        "distance_unit",
        "currency",
        "show_leaderboard_to_drivers",
        "driver_points_baseline",
        "maintenance_auto_book_enabled",
    ]
    before = audit.snapshot(row, fields)
    updates = payload.model_dump(exclude_unset=True)

    # Merge dict-valued settings rather than replacing wholesale, so a client
    # can tune one weight without resending the whole map.
    for dict_field in ("point_weights", "alert_thresholds", "co2_emission_factors"):
        if dict_field in updates and updates[dict_field] is not None:
            merged = dict(getattr(row, dict_field) or {})
            merged.update(updates.pop(dict_field))
            setattr(row, dict_field, merged)

    for key, value in updates.items():
        setattr(row, key, value)
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="organization_settings",
        entity_id=row.id,
        summary="Organization settings updated",
        changes=audit.diff(before, audit.snapshot(row, fields)),
        request=request,
    )
    return OrganizationSettingsOut.model_validate(row)


@router.get("/users", response_model=list[UserOut], summary="List users in your org")
async def list_users(
    role: UserRole | None = Query(default=None),
    _: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[UserOut]:
    users = await user_service.list_users(db, scope, role=role)
    return [UserOut.model_validate(u) for u in users]


@router.post(
    "/users",
    response_model=InviteUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a dispatcher or driver into your organization",
)
async def invite_user(
    payload: InviteUserRequest,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> InviteUserResponse:
    user, activation_url = await user_service.invite_user(
        db,
        scope,
        email=payload.email,
        full_name=payload.full_name,
        role=payload.role,
        phone=payload.phone,
        principal=principal,
        request=request,
    )
    return InviteUserResponse(
        user=UserOut.model_validate(user), activation_url=activation_url
    )


@router.post(
    "/users/{user_id}/suspend", response_model=UserOut, summary="Suspend a user"
)
async def suspend_user(
    user_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    user = await user_service.set_user_status(
        db,
        scope,
        user_id=user_id,
        status=UserStatus.SUSPENDED,
        principal=principal,
        request=request,
    )
    return UserOut.model_validate(user)


@router.post(
    "/users/{user_id}/reactivate", response_model=UserOut, summary="Reactivate a user"
)
async def reactivate_user(
    user_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    user = await user_service.set_user_status(
        db,
        scope,
        user_id=user_id,
        status=UserStatus.ACTIVE,
        principal=principal,
        request=request,
    )
    return UserOut.model_validate(user)
