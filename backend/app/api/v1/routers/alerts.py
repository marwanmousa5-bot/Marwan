"""Alert Operations Centre: inbox, detail, lifecycle, bulk actions, rule builder."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_or_404, paginate
from app.auth.deps import Principal, require_admin_of_org, require_operator, require_tenant
from app.core.enums import (AlertCategory, AlertStatus, OPEN_ALERT_STATUSES, Severity)
from app.db.base import get_session
from app.models import (Alert, AlertRule, Driver, Geofence, Task, TimelineEvent, Trip,
                        User, Vehicle, WorkOrder)
from app.schemas.common import Message
from app.services import alerts as alert_svc, audit
from app.websocket import events as ev
from app.websocket.events import bus

router = APIRouter()
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _row(a: Alert, vehicle=None, driver=None, assignee=None) -> dict:
    return {
        "id": str(a.id), "code": a.code, "category": a.category, "severity": a.severity,
        "status": a.status, "title": a.title, "detail": a.detail,
        "triggered_at": a.triggered_at.isoformat(),
        "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
        "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
        "snoozed_until": a.snoozed_until.isoformat() if a.snoozed_until else None,
        "escalation_level": a.escalation_level,
        "occurrence_count": a.occurrence_count,
        "lat": a.lat, "lon": a.lon, "street": a.street,
        "vehicle": {"id": str(vehicle.id), "name": vehicle.name,
                    "plate": vehicle.plate} if vehicle else None,
        "driver": {"id": str(driver.id), "name": driver.full_name} if driver else None,
        "assignee": {"id": str(assignee.id), "name": assignee.full_name}
        if assignee else None,
    }


@router.get("/summary")
async def summary(principal: Principal = Depends(require_tenant),
                  session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    by_sev = await alert_svc.open_counts(session, org_id)
    unacked = (await session.execute(
        select(func.count()).select_from(Alert).where(
            Alert.organization_id == org_id, Alert.status == AlertStatus.TRIGGERED))
    ).scalar_one()
    escalated = (await session.execute(
        select(func.count()).select_from(Alert).where(
            Alert.organization_id == org_id, Alert.status == AlertStatus.ESCALATED))
    ).scalar_one()
    resolved_today = (await session.execute(
        select(func.count()).select_from(Alert).where(
            Alert.organization_id == org_id, Alert.resolved_at >= day_start))).scalar_one()
    active = (await session.execute(
        select(func.count()).select_from(Alert).where(
            Alert.organization_id == org_id,
            Alert.status.in_(tuple(OPEN_ALERT_STATUSES))))).scalar_one()
    by_cat = dict((await session.execute(
        select(Alert.category, func.count()).where(
            Alert.organization_id == org_id,
            Alert.status.in_(tuple(OPEN_ALERT_STATUSES))).group_by(Alert.category))).all())
    return {
        "critical": by_sev.get(Severity.CRITICAL, 0), "high": by_sev.get(Severity.HIGH, 0),
        "medium": by_sev.get(Severity.MEDIUM, 0), "low": by_sev.get(Severity.LOW, 0),
        "active": active, "unacknowledged": unacked, "escalated": escalated,
        "resolved_today": resolved_today, "by_category": by_cat,
    }


@router.get("")
async def list_alerts(
    view: str = Query("active", pattern="^(all|active|unacknowledged|mine|escalated|snoozed|resolved)$"),
    q: str | None = None,
    severity: str | None = None,
    category: str | None = None,
    vehicle_id: uuid.UUID | None = None,
    driver_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
):
    org_id = principal.org_id
    stmt = select(Alert).where(Alert.organization_id == org_id)
    if view == "active":
        stmt = stmt.where(Alert.status.in_(tuple(OPEN_ALERT_STATUSES)))
    elif view == "unacknowledged":
        stmt = stmt.where(Alert.status == AlertStatus.TRIGGERED)
    elif view == "mine":
        stmt = stmt.where(Alert.assigned_to_id == principal.user.id,
                          Alert.status.in_(tuple(OPEN_ALERT_STATUSES)))
    elif view == "escalated":
        stmt = stmt.where(Alert.status == AlertStatus.ESCALATED)
    elif view == "snoozed":
        stmt = stmt.where(Alert.status == AlertStatus.SNOOZED)
    elif view == "resolved":
        stmt = stmt.where(Alert.status == AlertStatus.RESOLVED)
    if severity:
        stmt = stmt.where(Alert.severity.in_(severity.split(",")))
    if category:
        stmt = stmt.where(Alert.category.in_(category.split(",")))
    if vehicle_id:
        stmt = stmt.where(Alert.vehicle_id == vehicle_id)
    if driver_id:
        stmt = stmt.where(Alert.driver_id == driver_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Alert.title.ilike(like), Alert.detail.ilike(like),
                              Alert.street.ilike(like)))

    # Severity first, then newest (spec 6.1). Ordering in SQL keeps pagination
    # correct - sorting only the current page would interleave pages wrongly.
    rank = case(SEVERITY_ORDER, value=Alert.severity, else_=4)
    stmt = stmt.order_by(rank.asc(), Alert.triggered_at.desc())
    result = await paginate(session, stmt, page, size)

    vehicles = {v.id: v for v in (await session.execute(
        select(Vehicle).where(Vehicle.organization_id == org_id))).scalars().all()}
    drivers = {d.id: d for d in (await session.execute(
        select(Driver).where(Driver.organization_id == org_id))).scalars().all()}
    users = {u.id: u for u in (await session.execute(
        select(User).where(User.organization_id == org_id))).scalars().all()}
    result["items"] = [_row(a, vehicles.get(a.vehicle_id), drivers.get(a.driver_id),
                            users.get(a.assigned_to_id)) for a in result["items"]]
    return result


@router.get("/{alert_id}")
async def alert_detail(alert_id: uuid.UUID,
                       principal: Principal = Depends(require_tenant),
                       session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    a: Alert = await get_or_404(session, Alert, alert_id, org_id, "Alert")
    vehicle = await session.get(Vehicle, a.vehicle_id) if a.vehicle_id else None
    driver = await session.get(Driver, a.driver_id) if a.driver_id else None
    assignee = await session.get(User, a.assigned_to_id) if a.assigned_to_id else None
    rule = await session.get(AlertRule, a.rule_id) if a.rule_id else None
    trip = await session.get(Trip, a.trip_id) if a.trip_id else None
    task = await session.get(Task, a.task_id) if a.task_id else None
    fence = await session.get(Geofence, a.geofence_id) if a.geofence_id else None
    wo = await session.get(WorkOrder, a.work_order_id) if a.work_order_id else None
    timeline = (await session.execute(
        select(TimelineEvent).where(TimelineEvent.entity_type == "alert",
                                    TimelineEvent.entity_id == a.id)
        .order_by(TimelineEvent.occurred_at))).scalars().all()

    body = _row(a, vehicle, driver, assignee)
    body.update({
        "recommended_action": a.recommended_action,
        "evidence": a.evidence,
        "first_occurrence_at": a.first_occurrence_at.isoformat()
        if a.first_occurrence_at else None,
        "last_occurrence_at": a.last_occurrence_at.isoformat()
        if a.last_occurrence_at else None,
        "resolution_note": a.resolution_note,
        "rule": {"id": str(rule.id), "name": rule.name, "expression": rule.describe(),
                 "severity": rule.severity, "category": rule.category,
                 "cooldown_s": rule.cooldown_s} if rule else None,
        "trip": {"id": str(trip.id), "reference": trip.reference} if trip else None,
        "task": {"id": str(task.id), "reference": task.reference,
                 "title": task.title} if task else None,
        "geofence": {"id": str(fence.id), "name": fence.name} if fence else None,
        "work_order": {"id": str(wo.id), "reference": wo.reference} if wo else None,
        "timeline": [{"id": str(e.id), "occurred_at": e.occurred_at.isoformat(),
                      "actor_name": e.actor_name, "actor_type": e.actor_type,
                      "action": e.action, "description": e.description} for e in timeline],
    })
    return body


async def _lifecycle(session: AsyncSession, principal: Principal, alert: Alert,
                     action: str, description: str) -> None:
    await audit.timeline(session, organization_id=principal.org_id, entity_type="alert",
                         entity_id=alert.id, action=action, actor=principal.user,
                         description=description)
    await audit.record(session, action=f"alert.{action}",
                       organization_id=principal.org_id, actor=principal.user,
                       entity_type="alert", entity_id=alert.id, entity_label=alert.title,
                       summary=description)
    await bus.publish(principal.org_id, ev.ALERT_UPDATED,
                      {"id": str(alert.id), "status": alert.status})


class NoteIn(BaseModel):
    note: str | None = None


@router.post("/{alert_id}/acknowledge")
async def acknowledge(alert_id: uuid.UUID, payload: NoteIn,
                      principal: Principal = Depends(require_operator),
                      session: AsyncSession = Depends(get_session)):
    a: Alert = await get_or_404(session, Alert, alert_id, principal.org_id, "Alert")
    if a.status == AlertStatus.RESOLVED:
        raise HTTPException(status.HTTP_409_CONFLICT, "This alert is already resolved.")
    a.status = AlertStatus.ACKNOWLEDGED
    a.acknowledged_at = datetime.now(timezone.utc)
    a.acknowledged_by_id = principal.user.id
    await _lifecycle(session, principal, a, "acknowledged",
                     f"Acknowledged by {principal.label()}."
                     + (f" {payload.note}" if payload.note else ""))
    await session.commit()
    return {"id": str(a.id), "status": a.status}


class AssignAlertIn(BaseModel):
    user_id: uuid.UUID


@router.post("/{alert_id}/assign")
async def assign_alert(alert_id: uuid.UUID, payload: AssignAlertIn,
                       principal: Principal = Depends(require_operator),
                       session: AsyncSession = Depends(get_session)):
    a: Alert = await get_or_404(session, Alert, alert_id, principal.org_id, "Alert")
    target = await session.get(User, payload.user_id)
    if target is None or target.organization_id != principal.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That user is not in your organization.")
    a.assigned_to_id = target.id
    if a.status == AlertStatus.TRIGGERED:
        a.status = AlertStatus.INVESTIGATING
    await _lifecycle(session, principal, a, "assigned",
                     f"Assigned to {target.full_name} by {principal.label()}.")
    await session.commit()
    return {"id": str(a.id), "status": a.status, "assignee": target.full_name}


class SnoozeIn(BaseModel):
    minutes: int = Field(ge=5, le=1440)
    note: str | None = None


@router.post("/{alert_id}/snooze")
async def snooze(alert_id: uuid.UUID, payload: SnoozeIn,
                 principal: Principal = Depends(require_operator),
                 session: AsyncSession = Depends(get_session)):
    a: Alert = await get_or_404(session, Alert, alert_id, principal.org_id, "Alert")
    if a.severity == Severity.CRITICAL:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Critical alerts cannot be snoozed. Acknowledge or resolve it.")
    until = datetime.now(timezone.utc) + timedelta(minutes=payload.minutes)
    a.status = AlertStatus.SNOOZED
    a.snoozed_until = until
    await _lifecycle(session, principal, a, "snoozed",
                     f"Snoozed for {payload.minutes} minutes by {principal.label()}.")
    await session.commit()
    return {"id": str(a.id), "status": a.status, "snoozed_until": until.isoformat()}


@router.post("/{alert_id}/escalate")
async def escalate(alert_id: uuid.UUID, payload: NoteIn,
                   principal: Principal = Depends(require_operator),
                   session: AsyncSession = Depends(get_session)):
    a: Alert = await get_or_404(session, Alert, alert_id, principal.org_id, "Alert")
    a.status = AlertStatus.ESCALATED
    a.escalated_at = datetime.now(timezone.utc)
    a.escalation_level += 1
    await _lifecycle(session, principal, a, "escalated",
                     f"Escalated to level {a.escalation_level} by {principal.label()}."
                     + (f" {payload.note}" if payload.note else ""))
    await session.commit()
    return {"id": str(a.id), "status": a.status, "escalation_level": a.escalation_level}


class ResolveIn(BaseModel):
    note: str = Field(min_length=1, max_length=1000)


@router.post("/{alert_id}/resolve")
async def resolve(alert_id: uuid.UUID, payload: ResolveIn,
                  principal: Principal = Depends(require_operator),
                  session: AsyncSession = Depends(get_session)):
    a: Alert = await get_or_404(session, Alert, alert_id, principal.org_id, "Alert")
    if a.status == AlertStatus.RESOLVED:
        raise HTTPException(status.HTTP_409_CONFLICT, "This alert is already resolved.")
    a.status = AlertStatus.RESOLVED
    a.resolved_at = datetime.now(timezone.utc)
    a.resolved_by_id = principal.user.id
    a.resolution_note = payload.note
    await _lifecycle(session, principal, a, "resolved",
                     f"Resolved by {principal.label()}: {payload.note}")
    await bus.publish(principal.org_id, ev.ALERT_RESOLVED, {"id": str(a.id)})
    await session.commit()
    return {"id": str(a.id), "status": a.status}


class BulkIn(BaseModel):
    alert_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    action: str = Field(pattern="^(acknowledge|assign|snooze|resolve)$")
    user_id: uuid.UUID | None = None
    minutes: int | None = None
    note: str | None = None
    confirm_critical: bool = False


@router.post("/bulk")
async def bulk(payload: BulkIn,
               principal: Principal = Depends(require_operator),
               session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    alerts = (await session.execute(
        select(Alert).where(Alert.organization_id == org_id,
                            Alert.id.in_(payload.alert_ids)))).scalars().all()
    if not alerts:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No matching alerts found.")

    criticals = [a for a in alerts if a.severity == Severity.CRITICAL]
    if payload.action == "resolve" and criticals and not payload.confirm_critical:
        raise HTTPException(
            status.HTTP_428_PRECONDITION_REQUIRED,
            f"{len(criticals)} of these alerts are critical. Confirm explicitly to "
            f"resolve them in bulk.",
        )
    if payload.action == "resolve" and not payload.note:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "A resolution note is required.")

    now = datetime.now(timezone.utc)
    changed = 0
    for a in alerts:
        if payload.action == "acknowledge":
            if a.status == AlertStatus.RESOLVED:
                continue
            a.status = AlertStatus.ACKNOWLEDGED
            a.acknowledged_at, a.acknowledged_by_id = now, principal.user.id
            desc = f"Acknowledged by {principal.label()} (bulk)."
        elif payload.action == "assign":
            if not payload.user_id:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    "Choose a user to assign to.")
            a.assigned_to_id = payload.user_id
            desc = f"Assigned by {principal.label()} (bulk)."
        elif payload.action == "snooze":
            if a.severity == Severity.CRITICAL:
                continue
            a.status = AlertStatus.SNOOZED
            a.snoozed_until = now + timedelta(minutes=payload.minutes or 60)
            desc = f"Snoozed by {principal.label()} (bulk)."
        else:
            a.status = AlertStatus.RESOLVED
            a.resolved_at, a.resolved_by_id = now, principal.user.id
            a.resolution_note = payload.note
            desc = f"Resolved by {principal.label()} (bulk): {payload.note}"
        changed += 1
        await audit.timeline(session, organization_id=org_id, entity_type="alert",
                             entity_id=a.id, action=payload.action, actor=principal.user,
                             description=desc)
    await audit.record(session, action=f"alert.bulk_{payload.action}",
                       organization_id=org_id, actor=principal.user,
                       summary=f"{changed} alerts {payload.action}d in bulk")
    await session.commit()
    return {"updated": changed, "skipped": len(alerts) - changed}


# --- rules -----------------------------------------------------------------
class RuleIn(BaseModel):
    name: str
    code: str | None = None
    category: AlertCategory
    severity: Severity = Severity.MEDIUM
    description: str | None = None
    metric: str
    operator: str = ">"
    threshold: float | None = None
    threshold_unit: str | None = None
    duration_s: int = 0
    vehicle_ids: list[uuid.UUID] = Field(default_factory=list)
    driver_ids: list[uuid.UUID] = Field(default_factory=list)
    geofence_ids: list[uuid.UUID] = Field(default_factory=list)
    notify_roles: list[str] = Field(default_factory=list)
    notify_channels: list[str] = Field(default_factory=lambda: ["in_app"])
    escalation_minutes: list[int] = Field(default_factory=list)
    cooldown_s: int = 300
    dedupe_window_s: int = 120
    recommended_action: str | None = None
    is_active: bool = True


@router.get("/rules/list")
async def list_rules(principal: Principal = Depends(require_tenant),
                     session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(AlertRule).where(AlertRule.organization_id == principal.org_id)
        .order_by(AlertRule.category, AlertRule.name))).scalars().all()
    counts = dict((await session.execute(
        select(Alert.rule_id, func.count()).where(
            Alert.organization_id == principal.org_id,
            Alert.triggered_at >= datetime.now(timezone.utc) - timedelta(days=30)
        ).group_by(Alert.rule_id))).all())
    return [{"id": str(r.id), "name": r.name, "code": r.code, "category": r.category,
             "severity": r.severity, "description": r.description,
             "metric": r.metric, "operator": r.operator, "threshold": r.threshold,
             "threshold_unit": r.threshold_unit, "duration_s": r.duration_s,
             "expression": r.describe(), "cooldown_s": r.cooldown_s,
             "dedupe_window_s": r.dedupe_window_s,
             "escalation_minutes": r.escalation_minutes,
             "notify_roles": r.notify_roles, "notify_channels": r.notify_channels,
             "vehicle_ids": r.vehicle_ids, "driver_ids": r.driver_ids,
             "geofence_ids": r.geofence_ids,
             "recommended_action": r.recommended_action,
             "is_active": r.is_active, "is_system": r.is_system,
             "fired_30d": counts.get(r.id, 0)} for r in rows]


@router.post("/rules/list", status_code=status.HTTP_201_CREATED)
async def create_rule(payload: RuleIn,
                      principal: Principal = Depends(require_admin_of_org),
                      session: AsyncSession = Depends(get_session)):
    data = payload.model_dump()
    data["code"] = (data.get("code") or payload.name.lower().replace(" ", "_"))[:60]
    for key in ("vehicle_ids", "driver_ids", "geofence_ids"):
        data[key] = [str(v) for v in data[key]]
    rule = AlertRule(organization_id=principal.org_id, is_system=False, **data)
    session.add(rule)
    await session.flush()
    await audit.record(session, action="alert_rule.created",
                       organization_id=principal.org_id, actor=principal.user,
                       entity_type="alert_rule", entity_id=rule.id,
                       entity_label=rule.name,
                       summary=f"Alert rule created: {rule.describe()}")
    await session.commit()
    return {"id": str(rule.id), "expression": rule.describe()}


class RuleUpdate(BaseModel):
    name: str | None = None
    severity: Severity | None = None
    threshold: float | None = None
    duration_s: int | None = None
    cooldown_s: int | None = None
    dedupe_window_s: int | None = None
    escalation_minutes: list[int] | None = None
    notify_roles: list[str] | None = None
    notify_channels: list[str] | None = None
    vehicle_ids: list[uuid.UUID] | None = None
    driver_ids: list[uuid.UUID] | None = None
    recommended_action: str | None = None
    is_active: bool | None = None


@router.patch("/rules/{rule_id}")
async def update_rule(rule_id: uuid.UUID, payload: RuleUpdate,
                      principal: Principal = Depends(require_admin_of_org),
                      session: AsyncSession = Depends(get_session)):
    rule: AlertRule = await get_or_404(session, AlertRule, rule_id, principal.org_id,
                                       "Alert rule")
    fields = ["name", "severity", "threshold", "duration_s", "cooldown_s", "is_active"]
    before = audit.snapshot(rule, fields)
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        if k in ("vehicle_ids", "driver_ids") and v is not None:
            v = [str(x) for x in v]
        setattr(rule, k, v)
    await session.flush()
    await audit.record(session, action="alert_rule.updated",
                       organization_id=principal.org_id, actor=principal.user,
                       entity_type="alert_rule", entity_id=rule.id,
                       entity_label=rule.name, before=before,
                       after=audit.snapshot(rule, fields),
                       summary=f"Alert rule updated: {rule.describe()}")
    await session.commit()
    return {"id": str(rule.id), "expression": rule.describe(), "is_active": rule.is_active}


@router.delete("/rules/{rule_id}", response_model=Message)
async def delete_rule(rule_id: uuid.UUID,
                      principal: Principal = Depends(require_admin_of_org),
                      session: AsyncSession = Depends(get_session)):
    rule: AlertRule = await get_or_404(session, AlertRule, rule_id, principal.org_id,
                                       "Alert rule")
    if rule.is_system:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Built-in rules cannot be deleted. Deactivate it instead.")
    name = rule.name
    await session.delete(rule)
    await audit.record(session, action="alert_rule.deleted",
                       organization_id=principal.org_id, actor=principal.user,
                       entity_type="alert_rule", entity_id=rule_id, entity_label=name,
                       summary=f"Alert rule deleted: {name}")
    await session.commit()
    return Message(detail=f"Rule “{name}” deleted.")
