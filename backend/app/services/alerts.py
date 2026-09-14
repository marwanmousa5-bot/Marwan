"""Alert engine: rule evaluation, deduplication, lifecycle and escalation."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (AlertCategory, AlertStatus, OPEN_ALERT_STATUSES,
                            NotificationType, Role, Severity)
from app.models import Alert, AlertRule, Notification, User
from app.services import audit
from app.websocket import events as ev
from app.websocket.events import bus

SEVERITY_ORDER = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}


# --- the system rule catalogue seeded into every new organization ----------
SYSTEM_RULES: list[dict] = [
    dict(code="overspeed", name="Overspeed", category=AlertCategory.VEHICLE,
         severity=Severity.HIGH, metric="speed_kph", operator=">", threshold=60,
         threshold_unit="km/h", duration_s=20, cooldown_s=300, dedupe_window_s=180,
         recommended_action="Contact the driver and log a coaching note.",
         description="Vehicle exceeded the urban speed limit for a sustained period."),
    dict(code="harsh_braking", name="Harsh braking", category=AlertCategory.DRIVER,
         severity=Severity.MEDIUM, metric="deceleration_ms2", operator=">", threshold=3.5,
         threshold_unit="m/s²", cooldown_s=180, dedupe_window_s=300,
         recommended_action="Review the driver's braking trend this week.",
         description="Rapid deceleration detected."),
    dict(code="harsh_acceleration", name="Harsh acceleration", category=AlertCategory.DRIVER,
         severity=Severity.LOW, metric="acceleration_ms2", operator=">", threshold=3.2,
         threshold_unit="m/s²", cooldown_s=180, dedupe_window_s=300,
         description="Rapid acceleration detected."),
    dict(code="harsh_cornering", name="Harsh cornering", category=AlertCategory.DRIVER,
         severity=Severity.LOW, metric="lateral_g", operator=">", threshold=0.45,
         threshold_unit="g", cooldown_s=180, dedupe_window_s=300,
         description="High lateral force through a turn."),
    dict(code="excessive_idling", name="Excessive idling", category=AlertCategory.VEHICLE,
         severity=Severity.LOW, metric="idle_minutes", operator=">", threshold=15,
         threshold_unit="min", cooldown_s=900, dedupe_window_s=900,
         recommended_action="Ask the driver to switch off the engine while waiting.",
         description="Engine has been idling beyond the permitted window."),
    dict(code="vehicle_offline", name="Vehicle offline", category=AlertCategory.VEHICLE,
         severity=Severity.MEDIUM, metric="gps_age_s", operator=">", threshold=600,
         threshold_unit="s", cooldown_s=1800, dedupe_window_s=1800,
         recommended_action="Check the telematics device and vehicle power.",
         description="No GPS data received for an extended period."),
    dict(code="gps_signal_loss", name="GPS signal degraded", category=AlertCategory.VEHICLE,
         severity=Severity.LOW, metric="satellites", operator="<", threshold=4,
         threshold_unit="sats", cooldown_s=900, dedupe_window_s=900,
         description="Satellite fix quality dropped below the usable threshold."),
    dict(code="unauthorized_movement", name="Unauthorised movement",
         category=AlertCategory.SECURITY, severity=Severity.CRITICAL,
         metric="movement_without_driver", operator="=", threshold=1, cooldown_s=600,
         recommended_action="Verify with the depot, then escalate to security.",
         description="Vehicle moved with no driver assigned or accepted task."),
    dict(code="route_deviation", name="Route deviation", category=AlertCategory.ROUTE,
         severity=Severity.MEDIUM, metric="deviation_m", operator=">", threshold=250,
         threshold_unit="m", duration_s=60, cooldown_s=600, dedupe_window_s=600,
         recommended_action="Confirm the reason with the driver; re-route if needed.",
         description="Vehicle left its planned route corridor."),
    dict(code="task_delayed", name="Delayed arrival", category=AlertCategory.ROUTE,
         severity=Severity.HIGH, metric="eta_overrun_minutes", operator=">", threshold=10,
         threshold_unit="min", cooldown_s=900,
         recommended_action="Notify the customer and consider reassignment.",
         description="Projected arrival is later than the committed window."),
    dict(code="sla_breach_risk", name="SLA at risk", category=AlertCategory.ROUTE,
         severity=Severity.HIGH, metric="sla_minutes_remaining", operator="<", threshold=15,
         threshold_unit="min", cooldown_s=900,
         recommended_action="Reprioritise or reassign the task.",
         description="Task SLA will breach unless action is taken."),
    dict(code="geofence_enter", name="Geofence entry", category=AlertCategory.GEOFENCE,
         severity=Severity.LOW, metric="geofence_enter", operator="=", threshold=1,
         cooldown_s=60, description="Vehicle entered a monitored zone."),
    dict(code="geofence_exit", name="Geofence exit", category=AlertCategory.GEOFENCE,
         severity=Severity.LOW, metric="geofence_exit", operator="=", threshold=1,
         cooldown_s=60, description="Vehicle left a monitored zone."),
    dict(code="geofence_unauthorized", name="Restricted zone breach",
         category=AlertCategory.GEOFENCE, severity=Severity.CRITICAL,
         metric="restricted_zone", operator="=", threshold=1, cooldown_s=300,
         recommended_action="Contact the driver immediately and record the breach.",
         description="Vehicle entered a zone it is not permitted to enter."),
    dict(code="maintenance_due_soon", name="Service due soon",
         category=AlertCategory.MAINTENANCE, severity=Severity.LOW,
         metric="km_to_service", operator="<", threshold=500, threshold_unit="km",
         cooldown_s=86400, recommended_action="Book a workshop slot.",
         description="Preventive service threshold is approaching."),
    dict(code="maintenance_due", name="Service due", category=AlertCategory.MAINTENANCE,
         severity=Severity.MEDIUM, metric="km_to_service", operator="<=", threshold=50,
         threshold_unit="km", cooldown_s=86400,
         recommended_action="Schedule the work order now.",
         description="Preventive service threshold reached."),
    dict(code="maintenance_overdue", name="Service overdue",
         category=AlertCategory.MAINTENANCE, severity=Severity.HIGH,
         metric="km_to_service", operator="<", threshold=0, threshold_unit="km",
         cooldown_s=86400, recommended_action="Take the vehicle off rotation and service it.",
         description="Preventive service is past its threshold."),
    dict(code="maintenance_critical", name="Critical maintenance",
         category=AlertCategory.MAINTENANCE, severity=Severity.CRITICAL,
         metric="km_to_service", operator="<", threshold=-1000, threshold_unit="km",
         cooldown_s=86400, recommended_action="Ground the vehicle until serviced.",
         description="Service is severely overdue - continued use is a risk."),
    dict(code="work_order_overdue", name="Work order overdue",
         category=AlertCategory.MAINTENANCE, severity=Severity.MEDIUM,
         metric="work_order_overrun_hours", operator=">", threshold=2, threshold_unit="h",
         cooldown_s=7200, recommended_action="Chase the workshop for an updated ETA.",
         description="Work order has passed its expected completion time."),
    dict(code="document_expiring", name="Document expiring",
         category=AlertCategory.COMPLIANCE, severity=Severity.MEDIUM,
         metric="days_to_expiry", operator="<=", threshold=30, threshold_unit="days",
         cooldown_s=86400, recommended_action="Renew the document before it lapses.",
         description="A compliance document is approaching its expiry date."),
    dict(code="document_expired", name="Document expired",
         category=AlertCategory.COMPLIANCE, severity=Severity.CRITICAL,
         metric="days_to_expiry", operator="<", threshold=0, threshold_unit="days",
         cooldown_s=86400, recommended_action="Remove the vehicle or driver from service.",
         description="A compliance document has expired."),
    dict(code="license_expiring", name="Driver licence expiring",
         category=AlertCategory.COMPLIANCE, severity=Severity.MEDIUM,
         metric="days_to_expiry", operator="<=", threshold=30, threshold_unit="days",
         cooldown_s=86400, description="A driver licence is approaching expiry."),
    dict(code="fatigue_risk", name="Fatigue risk", category=AlertCategory.DRIVER,
         severity=Severity.HIGH, metric="duty_hours", operator=">", threshold=9,
         threshold_unit="h", cooldown_s=3600,
         recommended_action="Require a rest break before the next task.",
         description="Driver has exceeded the safe continuous duty window."),
    dict(code="suspicious_login", name="Suspicious sign-in", category=AlertCategory.SECURITY,
         severity=Severity.HIGH, metric="failed_logins", operator=">=", threshold=5,
         cooldown_s=900, recommended_action="Verify with the user and reset credentials.",
         description="Repeated failed sign-ins, or a sign-in from a new device."),
]


def default_rules_for_org(org_id: uuid.UUID) -> list[AlertRule]:
    return [
        AlertRule(organization_id=org_id, is_system=True, is_active=True,
                  notify_roles=[Role.ORG_ADMIN, Role.DISPATCHER],
                  escalation_minutes=[5, 10] if spec.get("severity") in
                  (Severity.HIGH, Severity.CRITICAL) else [],
                  **spec)
        for spec in SYSTEM_RULES
    ]


# --------------------------------------------------------------------------- #
async def rule_for(session: AsyncSession, org_id: uuid.UUID, code: str) -> AlertRule | None:
    return (await session.execute(
        select(AlertRule).where(AlertRule.organization_id == org_id,
                                AlertRule.code == code,
                                AlertRule.is_active.is_(True))
    )).scalars().first()


def _dedupe_key(code: str, vehicle_id, driver_id, extra: str | None) -> str:
    return ":".join(str(p) for p in (code, vehicle_id or "-", driver_id or "-", extra or "-"))


async def raise_alert(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    code: str,
    title: str,
    detail: str | None = None,
    severity: str | None = None,
    category: str | None = None,
    vehicle_id: uuid.UUID | None = None,
    driver_id: uuid.UUID | None = None,
    trip_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    geofence_id: uuid.UUID | None = None,
    work_order_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    lat: float | None = None,
    lon: float | None = None,
    street: str | None = None,
    evidence: dict | None = None,
    dedupe_extra: str | None = None,
    now: datetime | None = None,
    notify: bool = True,
) -> Alert | None:
    """Create an alert, or roll it into an existing one inside the dedupe window.

    Returns None when the rule is inactive or still in cooldown - so callers can
    fire freely without spamming the operator (spec 6.8).
    """
    now = now or datetime.now(timezone.utc)
    rule = await rule_for(session, org_id, code)
    if rule is None:
        return None

    # scope checks
    if rule.vehicle_ids and vehicle_id and str(vehicle_id) not in {str(v) for v in rule.vehicle_ids}:
        return None
    if rule.driver_ids and driver_id and str(driver_id) not in {str(d) for d in rule.driver_ids}:
        return None

    key = _dedupe_key(code, vehicle_id, driver_id, dedupe_extra)

    # Roll into an open alert with the same key inside the dedupe window.
    existing = (await session.execute(
        select(Alert).where(
            Alert.organization_id == org_id,
            Alert.dedupe_key == key,
            Alert.status.in_(tuple(OPEN_ALERT_STATUSES)),
        ).order_by(Alert.triggered_at.desc()).limit(1)
    )).scalars().first()

    if existing is not None:
        window = timedelta(seconds=max(rule.dedupe_window_s, rule.cooldown_s))
        last = existing.last_occurrence_at or existing.triggered_at
        if now - last <= window:
            existing.occurrence_count += 1
            existing.last_occurrence_at = now
            if lat is not None:
                existing.lat, existing.lon, existing.street = lat, lon, street
            merged = dict(existing.evidence or {})
            merged.update(evidence or {})
            merged["occurrences"] = existing.occurrence_count
            merged["window_s"] = round((now - (existing.first_occurrence_at
                                               or existing.triggered_at)).total_seconds())
            existing.evidence = merged
            await session.flush()
            await bus.publish(org_id, ev.ALERT_UPDATED,
                              {"id": str(existing.id), "occurrence_count": existing.occurrence_count})
            return existing
        # outside the window but still open: cooldown suppresses a duplicate
        if now - last <= timedelta(seconds=rule.cooldown_s):
            return None

    alert = Alert(
        organization_id=org_id, rule_id=rule.id, code=code,
        category=category or rule.category,
        severity=severity or rule.severity,
        status=AlertStatus.TRIGGERED,
        title=title, detail=detail or rule.description,
        recommended_action=rule.recommended_action,
        vehicle_id=vehicle_id, driver_id=driver_id, trip_id=trip_id, task_id=task_id,
        geofence_id=geofence_id, work_order_id=work_order_id, document_id=document_id,
        lat=lat, lon=lon, street=street,
        evidence={**(evidence or {}), "rule": rule.describe()},
        triggered_at=now, first_occurrence_at=now, last_occurrence_at=now,
        occurrence_count=1, dedupe_key=key,
    )
    session.add(alert)
    await session.flush()

    await bus.publish(org_id, ev.ALERT_TRIGGERED, {
        "id": str(alert.id), "code": code, "severity": alert.severity,
        "category": alert.category, "title": title,
        "vehicle_id": str(vehicle_id) if vehicle_id else None,
        "driver_id": str(driver_id) if driver_id else None,
        "lat": lat, "lon": lon,
    })

    if notify and alert.severity in (Severity.HIGH, Severity.CRITICAL):
        await _notify_roles(session, org_id, rule, alert)

    await audit.timeline(
        session, organization_id=org_id, entity_type="alert", entity_id=alert.id,
        action="triggered", description=f"{title} triggered.", occurred_at=now,
        meta={"severity": alert.severity, "rule": rule.describe()},
    )
    if vehicle_id:
        await audit.timeline(
            session, organization_id=org_id, entity_type="vehicle", entity_id=vehicle_id,
            action="alert_triggered", description=f"Alert: {title}",
            related_type="alert", related_id=alert.id, occurred_at=now,
            meta={"severity": alert.severity},
        )
    return alert


async def _notify_roles(session: AsyncSession, org_id: uuid.UUID,
                        rule: AlertRule, alert: Alert) -> None:
    roles = rule.notify_roles or [Role.ORG_ADMIN, Role.DISPATCHER]
    users = (await session.execute(
        select(User).where(User.organization_id == org_id, User.role.in_(roles),
                           User.is_active.is_(True))
    )).scalars().all()
    for u in users:
        session.add(Notification(
            organization_id=org_id, user_id=u.id, type=NotificationType.URGENT_ALERT,
            title=alert.title, body=alert.detail,
            link=f"/alerts?alert={alert.id}",
            entity_type="alert", entity_id=alert.id,
        ))


async def escalate_due_alerts(session: AsyncSession, org_id: uuid.UUID,
                              now: datetime | None = None) -> int:
    """Escalate unacknowledged high/critical alerts per the rule's ladder (6.7)."""
    now = now or datetime.now(timezone.utc)
    rows = (await session.execute(
        select(Alert, AlertRule).join(AlertRule, Alert.rule_id == AlertRule.id).where(
            Alert.organization_id == org_id,
            Alert.status == AlertStatus.TRIGGERED,
            Alert.acknowledged_at.is_(None),
            Alert.severity.in_([Severity.HIGH, Severity.CRITICAL]),
        )
    )).all()
    escalated = 0
    for alert, rule in rows:
        ladder = rule.escalation_minutes or []
        if not ladder:
            continue
        age_min = (now - alert.triggered_at).total_seconds() / 60
        level = sum(1 for step in ladder if age_min >= step)
        if level > alert.escalation_level:
            alert.escalation_level = level
            alert.escalated_at = now
            alert.status = AlertStatus.ESCALATED
            escalated += 1
            await audit.timeline(
                session, organization_id=org_id, entity_type="alert", entity_id=alert.id,
                action="escalated",
                description=f"Unacknowledged for {int(age_min)} minutes - escalated to level {level}.",
                occurred_at=now,
            )
            await bus.publish(org_id, ev.ALERT_UPDATED,
                              {"id": str(alert.id), "status": alert.status,
                               "escalation_level": level})
    return escalated


async def open_counts(session: AsyncSession, org_id: uuid.UUID) -> dict:
    rows = (await session.execute(
        select(Alert.severity, func.count()).where(
            Alert.organization_id == org_id,
            Alert.status.in_(tuple(OPEN_ALERT_STATUSES)),
        ).group_by(Alert.severity)
    )).all()
    return {sev: n for sev, n in rows}
