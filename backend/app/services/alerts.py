"""Centralised alerts engine (Section 4 item 12).

Every alert in the system is raised through ``raise_alert`` so that three
properties hold everywhere, rather than being re-implemented per feature:

* the Organization's rule for that type must be enabled;
* a recurring condition de-duplicates against its still-active alert instead
  of spamming a new row every scan;
* severity comes from the Organization's own rule configuration.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.tenancy import TenantScope
from app.models.alert import Alert, AlertRule
from app.models.compliance import ComplianceDocument
from app.models.enums import (
    AlertRuleType,
    AlertSeverity,
    AlertStatus,
    MaintenanceIntervalType,
)
from app.models.maintenance import MaintenanceSchedule
from app.models.organization import DEFAULT_ALERT_THRESHOLDS, OrganizationSettings
from app.models.vehicle import Vehicle


def utcnow() -> datetime:
    return datetime.now(UTC)


async def _rule(
    db: AsyncSession, organization_id: uuid.UUID, rule_type: AlertRuleType
) -> AlertRule | None:
    result = await db.execute(
        sa.select(AlertRule)
        .where(
            AlertRule.organization_id == organization_id,
            AlertRule.rule_type == rule_type,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def settings_for(
    db: AsyncSession, organization_id: uuid.UUID
) -> OrganizationSettings | None:
    result = await db.execute(
        sa.select(OrganizationSettings)
        .where(OrganizationSettings.organization_id == organization_id)
        .limit(1)
    )
    return result.scalar_one_or_none()


def threshold(settings: OrganizationSettings | None, key: str) -> float:
    if settings is None:
        return float(DEFAULT_ALERT_THRESHOLDS[key])
    return settings.threshold(key)


async def raise_alert(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    rule_type: AlertRuleType,
    title: str,
    message: str,
    severity: AlertSeverity | None = None,
    vehicle_id: uuid.UUID | None = None,
    driver_id: uuid.UUID | None = None,
    subject_type: str | None = None,
    subject_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
    context: dict | None = None,
) -> Alert | None:
    """Create an alert unless the rule is off or an identical one is open.

    Returns the new alert, or ``None`` when it was suppressed.
    """
    rule = await _rule(db, organization_id, rule_type)
    if rule is not None and not rule.is_enabled:
        return None

    if dedupe_key:
        existing = await db.execute(
            sa.select(Alert.id)
            .where(
                Alert.organization_id == organization_id,
                Alert.dedupe_key == dedupe_key,
                Alert.status != AlertStatus.RESOLVED,
            )
            .limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            return None

    alert = Alert(
        organization_id=organization_id,
        rule_type=rule_type,
        severity=severity or (rule.severity if rule else AlertSeverity.WARNING),
        status=AlertStatus.ACTIVE,
        title=title[:200],
        message=message,
        vehicle_id=vehicle_id,
        driver_id=driver_id,
        subject_type=subject_type,
        subject_id=subject_id,
        dedupe_key=dedupe_key,
        context=context,
    )
    db.add(alert)
    await db.flush()
    return alert


async def list_alerts(
    db: AsyncSession,
    scope: TenantScope,
    *,
    status: AlertStatus | None = AlertStatus.ACTIVE,
    vehicle_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Alert], int]:
    stmt = scope.select(Alert)
    if status is not None:
        stmt = stmt.where(Alert.status == status)
    if vehicle_id is not None:
        stmt = stmt.where(Alert.vehicle_id == vehicle_id)

    total = int(
        (await db.execute(sa.select(sa.func.count()).select_from(stmt.subquery())))
        .scalar_one()
    )
    result = await db.execute(
        stmt.order_by(Alert.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all()), total


async def active_alert_vehicle_ids(
    db: AsyncSession, scope: TenantScope
) -> set[uuid.UUID]:
    """Vehicles that should render red on the live map (Section 4b)."""
    result = await db.execute(
        sa.select(Alert.vehicle_id).where(
            Alert.organization_id == scope.organization_id,
            Alert.status == AlertStatus.ACTIVE,
            Alert.vehicle_id.is_not(None),
        )
    )
    return {row[0] for row in result.all()}


async def set_alert_status(
    db: AsyncSession,
    scope: TenantScope,
    *,
    alert_id: uuid.UUID,
    status: AlertStatus,
    user_id: uuid.UUID | None = None,
) -> Alert:
    alert = await scope.get_or_404(db, Alert, alert_id, label="Alert")
    alert.status = status
    if status == AlertStatus.ACKNOWLEDGED:
        alert.acknowledged_at = utcnow()
        alert.acknowledged_by_user_id = user_id
    elif status == AlertStatus.RESOLVED:
        alert.resolved_at = utcnow()
    return alert


async def list_rules(db: AsyncSession, scope: TenantScope) -> list[AlertRule]:
    result = await db.execute(scope.select(AlertRule).order_by(AlertRule.rule_type))
    return list(result.scalars().all())


async def update_rule(
    db: AsyncSession,
    scope: TenantScope,
    *,
    rule_type: AlertRuleType,
    is_enabled: bool | None = None,
    severity: AlertSeverity | None = None,
    parameters: dict | None = None,
) -> AlertRule:
    result = await db.execute(
        scope.select(AlertRule).where(AlertRule.rule_type == rule_type).limit(1)
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise NotFoundError("Alert rule not found")

    if is_enabled is not None:
        rule.is_enabled = is_enabled
    if severity is not None:
        rule.severity = severity
    if parameters is not None:
        rule.parameters = {**(rule.parameters or {}), **parameters}
    return rule


# ---------------------------------------------------------------------------
# Scheduled scans (driven by Celery beat, see app/tasks.py)
# ---------------------------------------------------------------------------

async def scan_maintenance_due(
    db: AsyncSession, organization_id: uuid.UUID, *, today: date | None = None
) -> int:
    """Raise an alert for each schedule approaching its next service."""
    today = today or utcnow().date()
    settings = await settings_for(db, organization_id)
    km_window = threshold(settings, "maintenance_due_km")
    day_window = int(threshold(settings, "maintenance_due_days"))

    rows = await db.execute(
        sa.select(MaintenanceSchedule, Vehicle)
        .join(Vehicle, Vehicle.id == MaintenanceSchedule.vehicle_id)
        .where(
            MaintenanceSchedule.organization_id == organization_id,
            MaintenanceSchedule.is_active.is_(True),
        )
    )

    raised = 0
    for schedule, vehicle in rows.all():
        due_reason: str | None = None

        if (
            schedule.interval_type == MaintenanceIntervalType.MILEAGE
            and schedule.next_due_odometer_km is not None
        ):
            remaining = schedule.next_due_odometer_km - vehicle.odometer_km
            if remaining <= km_window:
                due_reason = (
                    f"due in {max(0, int(remaining))} km "
                    f"(at {int(schedule.next_due_odometer_km):,} km)"
                    if remaining > 0
                    else f"overdue by {abs(int(remaining)):,} km"
                )
        elif schedule.next_due_date is not None:
            remaining_days = (schedule.next_due_date - today).days
            if remaining_days <= day_window:
                due_reason = (
                    f"due in {remaining_days} days ({schedule.next_due_date})"
                    if remaining_days > 0
                    else f"overdue by {abs(remaining_days)} days"
                )

        if due_reason is None:
            continue

        alert = await raise_alert(
            db,
            organization_id=organization_id,
            rule_type=AlertRuleType.MAINTENANCE_DUE,
            title=f"{schedule.name} due: {vehicle.name}",
            message=(
                f"{vehicle.name} ({vehicle.license_plate}) - "
                f"{schedule.name} {due_reason}."
            ),
            vehicle_id=vehicle.id,
            subject_type="maintenance_schedule",
            subject_id=schedule.id,
            # Re-alerting is keyed to the service occurrence, so one due
            # service produces one alert no matter how often the scan runs.
            dedupe_key=(
                f"maintenance:{schedule.id}:"
                f"{schedule.next_due_odometer_km or schedule.next_due_date}"
            ),
            context={"schedule": schedule.name, "reason": due_reason},
        )
        if alert is not None:
            raised += 1
    return raised


async def scan_expiring_documents(
    db: AsyncSession, organization_id: uuid.UUID, *, today: date | None = None
) -> int:
    """Raise an alert for each compliance document nearing expiry."""
    today = today or utcnow().date()
    settings = await settings_for(db, organization_id)
    window_days = int(threshold(settings, "document_expiry_warning_days"))
    cutoff = today + timedelta(days=window_days)

    result = await db.execute(
        sa.select(ComplianceDocument).where(
            ComplianceDocument.organization_id == organization_id,
            ComplianceDocument.expires_on.is_not(None),
            ComplianceDocument.expires_on <= cutoff,
        )
    )

    raised = 0
    for document in result.scalars().all():
        days_left = (document.expires_on - today).days
        expired = days_left < 0
        alert = await raise_alert(
            db,
            organization_id=organization_id,
            rule_type=AlertRuleType.DOCUMENT_EXPIRING,
            severity=AlertSeverity.CRITICAL if expired else None,
            title=f"{document.title} {'expired' if expired else 'expiring'}",
            message=(
                f"{document.title} "
                + (
                    f"expired {abs(days_left)} days ago ({document.expires_on})."
                    if expired
                    else f"expires in {days_left} days ({document.expires_on})."
                )
            ),
            vehicle_id=document.vehicle_id,
            driver_id=document.driver_id,
            subject_type="compliance_document",
            subject_id=document.id,
            dedupe_key=f"document:{document.id}:{document.expires_on}",
            context={"document_type": document.document_type, "days_left": days_left},
        )
        if alert is not None:
            raised += 1
    return raised
