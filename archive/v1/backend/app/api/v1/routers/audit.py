"""Audit log and login-activity viewing (Section 4 item 18, Section 7).

Two audiences, one store:

* ``org_admin`` sees their own Organization's trail and nothing else - the
  query is tenant-scoped, and the platform-level rows (which carry no
  ``organization_id``) are invisible to them.
* ``super_admin`` sees the platform-wide trail across every tenant, and can
  narrow it to one Organization.

The log is append-only: there is no endpoint here that writes, edits or
deletes a row, by design.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    Principal,
    get_tenant_scope,
    require_org_admin,
    require_super_admin,
)
from app.core.tenancy import TenantScope
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.organization import Organization
from app.models.user import KnownDevice, LoginAttempt, User
from app.schemas.audit import (
    AuditLogOut,
    KnownDeviceOut,
    LoginAttemptOut,
    SecurityOverview,
)
from app.schemas.common import Page

router = APIRouter(tags=["audit"])

#: The window the security screens summarise.
SECURITY_WINDOW = timedelta(days=7)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _apply_filters(
    stmt: sa.Select,
    *,
    action: str | None,
    entity_type: str | None,
    actor_email: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> sa.Select:
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if actor_email:
        stmt = stmt.where(AuditLog.actor_email.ilike(f"%{actor_email}%"))
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= date_to)
    return stmt


# ---------------------------------------------------------------------------
# Organization-scoped trail
# ---------------------------------------------------------------------------

@router.get(
    "/audit-log",
    response_model=Page[AuditLogOut],
    summary="Your organisation's audit trail",
)
async def organization_audit_log(
    action: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    actor_email: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> Page[AuditLogOut]:
    base = sa.select(AuditLog).where(AuditLog.organization_id == scope.organization_id)
    base = _apply_filters(
        base,
        action=action,
        entity_type=entity_type,
        actor_email=actor_email,
        date_from=date_from,
        date_to=date_to,
    )

    total = (
        await db.execute(
            sa.select(sa.func.count()).select_from(base.subquery())
        )
    ).scalar_one()
    rows = (
        await db.execute(
            base.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()

    return Page[AuditLogOut](
        items=[AuditLogOut.model_validate(r) for r in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/audit-log/actions",
    response_model=list[str],
    summary="Action verbs present in your trail, for the filter",
)
async def organization_audit_actions(
    _: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    rows = await db.execute(
        sa.select(AuditLog.action)
        .where(AuditLog.organization_id == scope.organization_id)
        .distinct()
        .order_by(AuditLog.action)
    )
    return [r for (r,) in rows.all()]


# ---------------------------------------------------------------------------
# Security / login activity
# ---------------------------------------------------------------------------

@router.get(
    "/security/login-activity",
    response_model=Page[LoginAttemptOut],
    summary="Recent sign-in attempts for your organisation's users",
)
async def organization_login_activity(
    suspicious_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> Page[LoginAttemptOut]:
    """Scoped through the user table.

    ``login_attempts`` deliberately has no ``organization_id``: an attempt can
    arrive for an address that belongs to no user at all. Joining to users is
    what keeps one tenant's admin from reading another tenant's sign-ins.
    """
    base = (
        sa.select(LoginAttempt)
        .join(User, User.id == LoginAttempt.user_id)
        .where(User.organization_id == scope.organization_id)
    )
    if suspicious_only:
        base = base.where(LoginAttempt.suspicious.is_(True))

    total = (
        await db.execute(sa.select(sa.func.count()).select_from(base.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            base.order_by(LoginAttempt.attempted_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()

    return Page[LoginAttemptOut](
        items=[LoginAttemptOut.model_validate(r) for r in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/security/overview",
    response_model=SecurityOverview,
    summary="Sign-in health for your organisation",
)
async def organization_security_overview(
    _: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> SecurityOverview:
    since = utcnow() - SECURITY_WINDOW
    user_ids = sa.select(User.id).where(User.organization_id == scope.organization_id)

    suspicious = (
        await db.execute(
            sa.select(sa.func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.user_id.in_(user_ids),
                LoginAttempt.suspicious.is_(True),
                LoginAttempt.attempted_at >= since,
            )
        )
    ).scalar_one()
    failed = (
        await db.execute(
            sa.select(sa.func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.user_id.in_(user_ids),
                LoginAttempt.successful.is_(False),
                LoginAttempt.attempted_at >= since,
            )
        )
    ).scalar_one()
    locked = (
        await db.execute(
            sa.select(sa.func.count())
            .select_from(User)
            .where(
                User.organization_id == scope.organization_id,
                # Lockout is a timestamp, not a status: the account unlocks
                # itself when it passes.
                User.locked_until > utcnow(),
            )
        )
    ).scalar_one()
    without_device = (
        await db.execute(
            sa.select(sa.func.count())
            .select_from(User)
            .where(
                User.organization_id == scope.organization_id,
                ~sa.exists().where(KnownDevice.user_id == User.id),
            )
        )
    ).scalar_one()

    return SecurityOverview(
        suspicious_logins_7d=int(suspicious),
        failed_logins_7d=int(failed),
        locked_accounts=int(locked),
        users_without_a_known_device=int(without_device),
    )


@router.get(
    "/security/known-devices",
    response_model=list[KnownDeviceOut],
    summary="Devices your organisation's users have signed in from",
)
async def organization_known_devices(
    _: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[KnownDeviceOut]:
    rows = await db.execute(
        sa.select(KnownDevice)
        .join(User, User.id == KnownDevice.user_id)
        .where(User.organization_id == scope.organization_id)
        .order_by(KnownDevice.last_seen_at.desc())
        .limit(200)
    )
    return [KnownDeviceOut.model_validate(d) for d in rows.scalars().all()]


# ---------------------------------------------------------------------------
# Platform-wide trail (super_admin only)
# ---------------------------------------------------------------------------

@router.get(
    "/platform/audit-log",
    response_model=Page[AuditLogOut],
    summary="Platform-wide audit trail across every organisation",
)
async def platform_audit_log(
    organization_id: uuid.UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    actor_email: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> Page[AuditLogOut]:
    base = sa.select(AuditLog)
    if organization_id is not None:
        base = base.where(AuditLog.organization_id == organization_id)
    base = _apply_filters(
        base,
        action=action,
        entity_type=entity_type,
        actor_email=actor_email,
        date_from=date_from,
        date_to=date_to,
    )

    total = (
        await db.execute(sa.select(sa.func.count()).select_from(base.subquery()))
    ).scalar_one()

    rows = (
        await db.execute(
            base.add_columns(Organization.name)
            .outerjoin(Organization, Organization.id == AuditLog.organization_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    items = []
    for entry, organization_name in rows:
        item = AuditLogOut.model_validate(entry)
        item.organization_name = organization_name
        items.append(item)

    return Page[AuditLogOut](
        items=items, total=int(total), limit=limit, offset=offset
    )


@router.get(
    "/platform/security/login-activity",
    response_model=Page[LoginAttemptOut],
    summary="Sign-in attempts across the platform, including unknown addresses",
)
async def platform_login_activity(
    suspicious_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> Page[LoginAttemptOut]:
    base = sa.select(LoginAttempt)
    if suspicious_only:
        base = base.where(LoginAttempt.suspicious.is_(True))

    total = (
        await db.execute(sa.select(sa.func.count()).select_from(base.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            base.order_by(LoginAttempt.attempted_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()

    return Page[LoginAttemptOut](
        items=[LoginAttemptOut.model_validate(r) for r in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )
