"""User management inside an Organization.

An ``org_admin`` may invite ``dispatcher`` and ``driver`` users into their own
Organization - and nothing else. Cross-Organization creation is impossible by
construction: the new user's ``organization_id`` comes from the inviter's
tenant scope, never from the request body (Section 2 / Section 9).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.tenancy import TenantScope
from app.models.driver import Driver
from app.models.enums import AuditAction, UserRole, UserStatus
from app.models.user import User
from app.services import audit
from app.services.auth import create_activation_link

#: The only roles an Org Admin can hand out.
INVITABLE_ROLES = frozenset({UserRole.DISPATCHER, UserRole.DRIVER})


async def invite_user(
    db: AsyncSession,
    scope: TenantScope,
    *,
    email: str,
    full_name: str,
    role: UserRole,
    phone: str | None = None,
    create_driver_profile: bool = True,
    principal: Principal | None = None,
    request: Request | None = None,
) -> tuple[User, str]:
    """Create a pending user in the inviter's Organization + activation link."""
    if role not in INVITABLE_ROLES:
        raise PermissionDeniedError(
            "Only dispatcher and driver accounts can be invited. Organization "
            "administrators are created by FleetBeat during onboarding."
        )

    normalised = email.strip().lower()
    existing = await db.execute(
        sa.select(User.id).where(sa.func.lower(User.email) == normalised).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError(f"A user with the email {normalised} already exists")

    user = User(
        organization_id=scope.organization_id,
        email=normalised,
        full_name=full_name.strip(),
        phone=phone,
        role=role,
        status=UserStatus.PENDING_ACTIVATION,
        created_by_user_id=principal.user_id if principal else None,
    )
    db.add(user)
    await db.flush()

    if role == UserRole.DRIVER and create_driver_profile:
        driver = Driver(
            organization_id=scope.organization_id,
            user_id=user.id,
            full_name=user.full_name,
            phone=phone,
        )
        db.add(driver)
        await db.flush()

    activation_url, _ = await create_activation_link(
        db,
        user=user,
        purpose="activation",
        issued_by_user_id=principal.user_id if principal else None,
    )

    await audit.record(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="user",
        entity_id=user.id,
        summary=f"Invited {role.value} {user.email}",
        request=request,
    )
    return user, activation_url


async def list_users(
    db: AsyncSession, scope: TenantScope, *, role: UserRole | None = None
) -> list[User]:
    stmt = sa.select(User).where(User.organization_id == scope.organization_id)
    if role is not None:
        stmt = stmt.where(User.role == role)
    result = await db.execute(stmt.order_by(User.full_name))
    return list(result.scalars().all())


async def get_user(db: AsyncSession, scope: TenantScope, user_id: uuid.UUID) -> User:
    result = await db.execute(
        sa.select(User)
        .where(User.id == user_id, User.organization_id == scope.organization_id)
        .limit(1)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found")
    return user


async def set_user_status(
    db: AsyncSession,
    scope: TenantScope,
    *,
    user_id: uuid.UUID,
    status: UserStatus,
    principal: Principal | None = None,
    request: Request | None = None,
) -> User:
    user = await get_user(db, scope, user_id)
    if principal and user.id == principal.user_id:
        raise PermissionDeniedError("You cannot change your own account status")
    before = user.status
    user.status = status
    await audit.record(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="user",
        entity_id=user.id,
        summary=f"User status {before} -> {status}",
        changes={"before": {"status": before}, "after": {"status": str(status)}},
        request=request,
    )
    return user
