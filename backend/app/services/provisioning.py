"""Organization provisioning - the ONLY way a customer comes into existence.

Section 4a: a ``super_admin`` creates an Organization together with its first
``org_admin``, and receives a one-time activation link to hand over manually.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal
from app.core.errors import ConflictError, NotFoundError
from app.models.alert import AlertRule
from app.models.enums import (
    AlertRuleType,
    AlertSeverity,
    AuditAction,
    OrganizationStatus,
    UserRole,
    UserStatus,
)
from app.models.organization import Organization, OrganizationSettings
from app.models.user import User
from app.services import audit
from app.services.auth import create_activation_link

#: Rules every new Organization starts with (Section 4 item 12).
DEFAULT_ALERT_RULES: tuple[tuple[AlertRuleType, AlertSeverity], ...] = (
    (AlertRuleType.MAINTENANCE_DUE, AlertSeverity.WARNING),
    (AlertRuleType.DOCUMENT_EXPIRING, AlertSeverity.WARNING),
    (AlertRuleType.GEOFENCE_BREACH, AlertSeverity.WARNING),
    (AlertRuleType.HARSH_DRIVING, AlertSeverity.INFO),
    (AlertRuleType.SPEEDING, AlertSeverity.WARNING),
    (AlertRuleType.IDLE_TOO_LONG, AlertSeverity.INFO),
    (AlertRuleType.WEATHER_DELAY, AlertSeverity.INFO),
    (AlertRuleType.ANOMALY, AlertSeverity.INFO),
    (AlertRuleType.SUSPICIOUS_LOGIN, AlertSeverity.WARNING),
    (AlertRuleType.FATIGUE_RISK, AlertSeverity.WARNING),
)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "organization"


async def _unique_slug(db: AsyncSession, base: str) -> str:
    slug = base
    suffix = 2
    while True:
        exists = await db.execute(
            sa.select(Organization.id).where(Organization.slug == slug).limit(1)
        )
        if exists.scalar_one_or_none() is None:
            return slug
        slug = f"{base}-{suffix}"
        suffix += 1


async def create_organization(
    db: AsyncSession,
    *,
    name: str,
    admin_email: str,
    admin_full_name: str,
    industry: str | None = None,
    timezone_name: str = "UTC",
    contact_name: str | None = None,
    contact_email: str | None = None,
    contact_phone: str | None = None,
    plan: str = "standard",
    principal: Principal | None = None,
    request: Request | None = None,
) -> tuple[Organization, User, str]:
    """Create Organization + first Org Admin + activation link.

    Returns ``(organization, admin_user, activation_url)``. The URL is shown
    once in the Platform Admin Console; it is not emailed in this phase.
    """
    normalised_email = admin_email.strip().lower()
    existing = await db.execute(
        sa.select(User.id).where(sa.func.lower(User.email) == normalised_email).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError(f"A user with the email {normalised_email} already exists")

    organization = Organization(
        name=name.strip(),
        slug=await _unique_slug(db, slugify(name)),
        industry=industry,
        timezone=timezone_name,
        contact_name=contact_name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        plan=plan,
        status=OrganizationStatus.ACTIVE,
    )
    db.add(organization)
    await db.flush()

    db.add(OrganizationSettings(organization_id=organization.id))
    for rule_type, severity in DEFAULT_ALERT_RULES:
        db.add(
            AlertRule(
                organization_id=organization.id,
                rule_type=rule_type,
                severity=severity,
                is_enabled=True,
                parameters={},
            )
        )

    admin = User(
        organization_id=organization.id,
        email=normalised_email,
        full_name=admin_full_name.strip(),
        role=UserRole.ORG_ADMIN,
        status=UserStatus.PENDING_ACTIVATION,
        created_by_user_id=principal.user_id if principal else None,
    )
    db.add(admin)
    await db.flush()

    activation_url, _ = await create_activation_link(
        db,
        user=admin,
        purpose="activation",
        issued_by_user_id=principal.user_id if principal else None,
    )

    await audit.record(
        db,
        action=AuditAction.ORGANIZATION_CREATED,
        principal=principal,
        organization_id=organization.id,
        entity_type="organization",
        entity_id=organization.id,
        summary=f"Organization '{organization.name}' provisioned with admin {admin.email}",
        changes={"after": {"name": organization.name, "admin_email": admin.email}},
        request=request,
    )
    return organization, admin, activation_url


async def set_organization_status(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    status: OrganizationStatus,
    principal: Principal | None = None,
    request: Request | None = None,
) -> Organization:
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise NotFoundError("Organization not found")

    before = organization.status
    organization.status = status
    organization.updated_at = datetime.now(UTC)

    await audit.record(
        db,
        action=(
            AuditAction.ORGANIZATION_SUSPENDED
            if status == OrganizationStatus.SUSPENDED
            else AuditAction.ORGANIZATION_REACTIVATED
        ),
        principal=principal,
        organization_id=organization.id,
        entity_type="organization",
        entity_id=organization.id,
        summary=f"Organization status changed from {before} to {status}",
        changes={"before": {"status": before}, "after": {"status": str(status)}},
        request=request,
    )
    return organization
