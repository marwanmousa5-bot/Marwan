"""Driver management and the Driver 360 workspace."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_or_404, paginate
from app.auth.deps import Principal, require_admin_of_org, require_operator, require_tenant
from app.core.enums import (ACTIVE_TASK_STATUSES, DriverStatus, OPEN_ALERT_STATUSES,
                            Role)
from app.db.base import get_session
from app.models import (Alert, Badge, Document, Driver, DriverEvent,
                        DriverPointTransaction, DriverScoreSnapshot, Incident, Task,
                        TimelineEvent, Trip, User, Vehicle)
from app.schemas.common import Message
from app.services import audit, scoring
from app.services.derive import document_status

router = APIRouter()


class DriverIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=160)
    employee_no: str = Field(min_length=1, max_length=30)
    email: EmailStr | None = None
    phone: str | None = None
    license_number: str | None = None
    license_class: str | None = None
    license_expiry: date | None = None
    hired_on: date | None = None
    shift_start: str = "07:00"
    shift_end: str = "16:00"
    notes: str | None = None


class DriverUpdate(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    status: DriverStatus | None = None
    license_number: str | None = None
    license_class: str | None = None
    license_expiry: date | None = None
    shift_start: str | None = None
    shift_end: str | None = None
    notes: str | None = None


@router.get("")
async def list_drivers(q: str | None = None, status_filter: str | None = Query(None, alias="status"),
                       page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
                       principal: Principal = Depends(require_tenant),
                       session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    stmt = select(Driver).where(Driver.organization_id == org_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Driver.full_name.ilike(like), Driver.employee_no.ilike(like),
                              Driver.phone.ilike(like)))
    if status_filter:
        stmt = stmt.where(Driver.status == status_filter)
    result = await paginate(session, stmt.order_by(Driver.full_name), page, size)

    vehicles = {v.driver_id: v for v in (await session.execute(
        select(Vehicle).where(Vehicle.organization_id == org_id,
                              Vehicle.driver_id.isnot(None)))).scalars().all()}
    tasks = (await session.execute(
        select(Task).where(Task.organization_id == org_id,
                           Task.status.in_(ACTIVE_TASK_STATUSES),
                           Task.driver_id.isnot(None)))).scalars().all()
    by_driver: dict[uuid.UUID, list[Task]] = {}
    for t in tasks:
        by_driver.setdefault(t.driver_id, []).append(t)
    alert_counts = dict((await session.execute(
        select(Alert.driver_id, func.count()).where(
            Alert.organization_id == org_id, Alert.driver_id.isnot(None),
            Alert.status.in_(tuple(OPEN_ALERT_STATUSES))).group_by(Alert.driver_id))).all())

    today = date.today()
    items = []
    for d in result["items"]:
        v = vehicles.get(d.id)
        dts = by_driver.get(d.id, [])
        lic = document_status(d.license_expiry, today=today)
        items.append({
            "id": str(d.id), "name": d.full_name, "employee_no": d.employee_no,
            "status": d.status, "phone": d.phone, "email": d.email,
            "avatar_color": d.avatar_color,
            "vehicle": {"id": str(v.id), "name": v.name, "plate": v.plate} if v else None,
            "current_task": {"id": str(dts[0].id), "reference": dts[0].reference,
                             "status": dts[0].status} if dts else None,
            "active_tasks": len(dts),
            "safety_score": d.safety_score,
            "safety_trend": round(d.safety_score - d.previous_safety_score, 1),
            "points": d.points_balance,
            "fatigue_risk": d.fatigue_risk,
            "duty_hours_today": round(d.duty_hours_today, 1),
            "license_status": lic,
            "license_expiry": d.license_expiry.isoformat() if d.license_expiry else None,
            "alert_count": alert_counts.get(d.id, 0),
        })
    result["items"] = items
    return result


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_driver(payload: DriverIn,
                        principal: Principal = Depends(require_admin_of_org),
                        session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    clash = (await session.execute(
        select(Driver).where(Driver.organization_id == org_id,
                             Driver.employee_no == payload.employee_no))).scalars().first()
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Employee number {payload.employee_no} is already used by "
                            f"{clash.full_name}.")
    cfg = principal.organization.settings or {}
    driver = Driver(organization_id=org_id,
                    points_balance=cfg.get("driver_points_start", 100),
                    **payload.model_dump())
    session.add(driver)
    await session.flush()
    await audit.record(session, action="driver.created", organization_id=org_id,
                       actor=principal.user, entity_type="driver", entity_id=driver.id,
                       entity_label=driver.full_name,
                       summary=f"Driver {driver.full_name} added")
    await audit.timeline(session, organization_id=org_id, entity_type="driver",
                         entity_id=driver.id, action="created", actor=principal.user,
                         description=f"{driver.full_name} added to the team.")
    await session.commit()
    return {"id": str(driver.id), "name": driver.full_name}


@router.patch("/{driver_id}")
async def update_driver(driver_id: uuid.UUID, payload: DriverUpdate,
                        principal: Principal = Depends(require_operator),
                        session: AsyncSession = Depends(get_session)):
    driver: Driver = await get_or_404(session, Driver, driver_id, principal.org_id, "Driver")
    fields = ["full_name", "email", "phone", "status", "license_number",
              "license_class", "license_expiry", "shift_start", "shift_end"]
    before = audit.snapshot(driver, fields)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("status") and principal.role not in (Role.ORG_ADMIN, Role.DISPATCHER):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot change driver status.")
    for k, v in changes.items():
        setattr(driver, k, v)
    await session.flush()
    await audit.record(session, action="driver.updated", organization_id=principal.org_id,
                       actor=principal.user, entity_type="driver", entity_id=driver.id,
                       entity_label=driver.full_name,
                       summary=f"{driver.full_name} updated: " + ", ".join(changes),
                       before=before, after=audit.snapshot(driver, fields))
    await audit.timeline(session, organization_id=principal.org_id, entity_type="driver",
                         entity_id=driver.id, action="updated", actor=principal.user,
                         description="Driver record updated: " + ", ".join(
                             k.replace('_', ' ') for k in changes))
    await session.commit()
    return {"id": str(driver.id), "updated": list(changes)}


@router.get("/leaderboard")
async def leaderboard(principal: Principal = Depends(require_tenant),
                      session: AsyncSession = Depends(get_session)):
    cfg = principal.organization.settings or {}
    if principal.role == Role.DRIVER and not cfg.get("show_leaderboard_to_drivers", True):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Your organization has turned off driver standings.")
    return {"period": datetime.now(timezone.utc).strftime("%B %Y"),
            "entries": await scoring.leaderboard(session, principal.org_id)}


@router.get("/{driver_id}")
async def driver_overview(driver_id: uuid.UUID,
                          principal: Principal = Depends(require_tenant),
                          session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    d: Driver = await get_or_404(session, Driver, driver_id, org_id, "Driver")
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=30)

    vehicle = (await session.execute(
        select(Vehicle).where(Vehicle.driver_id == d.id))).scalars().first()
    event_rows = (await session.execute(
        select(DriverEvent.type, func.count()).where(
            DriverEvent.driver_id == d.id, DriverEvent.occurred_at >= since
        ).group_by(DriverEvent.type))).all()
    trips = (await session.execute(
        select(func.count(), func.coalesce(func.sum(Trip.distance_km), 0.0),
               func.coalesce(func.sum(Trip.fuel_used_l), 0.0),
               func.coalesce(func.sum(Trip.duration_s), 0.0)).where(
            Trip.driver_id == d.id, Trip.started_at >= since))).one()
    completed = (await session.execute(
        select(func.count()).select_from(Task).where(
            Task.driver_id == d.id, Task.status == "completed",
            Task.completed_at >= since))).scalar_one()
    badges = (await session.execute(
        select(Badge).where(Badge.driver_id == d.id)
        .order_by(Badge.awarded_at.desc()))).scalars().all()
    history = (await session.execute(
        select(DriverScoreSnapshot).where(
            DriverScoreSnapshot.driver_id == d.id,
            DriverScoreSnapshot.day >= since.date()
        ).order_by(DriverScoreSnapshot.day))).scalars().all()
    incidents = (await session.execute(
        select(func.count()).select_from(Incident).where(
            Incident.driver_id == d.id))).scalar_one()
    open_alerts = (await session.execute(
        select(func.count()).select_from(Alert).where(
            Alert.driver_id == d.id,
            Alert.status.in_(tuple(OPEN_ALERT_STATUSES))))).scalar_one()

    trip_count, km, fuel, duration = trips
    km = float(km)
    return {
        "id": str(d.id), "name": d.full_name, "employee_no": d.employee_no,
        "email": d.email, "phone": d.phone, "status": d.status,
        "avatar_color": d.avatar_color,
        "license": {"number": d.license_number, "class": d.license_class,
                    "expiry": d.license_expiry.isoformat() if d.license_expiry else None,
                    "status": document_status(d.license_expiry)},
        "hired_on": d.hired_on.isoformat() if d.hired_on else None,
        "shift": {"start": d.shift_start, "end": d.shift_end},
        "vehicle": {"id": str(vehicle.id), "name": vehicle.name,
                    "plate": vehicle.plate} if vehicle else None,
        "safety": {
            "score": d.safety_score,
            "previous": d.previous_safety_score,
            "trend": round(d.safety_score - d.previous_safety_score, 1),
            "events": {t: n for t, n in event_rows},
            "history": [{"day": h.day.isoformat(), "score": h.score,
                         "distance_km": h.distance_km} for h in history],
        },
        "fatigue": {"duty_hours_today": round(d.duty_hours_today, 1),
                    "risk": d.fatigue_risk,
                    "duty_started_at": d.duty_started_at.isoformat()
                    if d.duty_started_at else None},
        "points": {"balance": d.points_balance},
        "badges": [{"code": b.code, "name": b.name, "description": b.description,
                    "icon": b.icon, "awarded_at": b.awarded_at.isoformat()}
                   for b in badges],
        "performance_30d": {
            "trips": trip_count, "distance_km": round(km, 1),
            "driving_hours": round(float(duration) / 3600, 1),
            "tasks_completed": completed,
            "fuel_l": round(float(fuel), 1),
            "l_per_100km": round(float(fuel) / km * 100, 2) if km > 5 else None,
        },
        "incidents": incidents,
        "open_alerts": open_alerts,
        "notes": d.notes,
    }


@router.get("/{driver_id}/events")
async def driver_events(driver_id: uuid.UUID, days: int = Query(30, le=180),
                        principal: Principal = Depends(require_tenant),
                        session: AsyncSession = Depends(get_session)):
    await get_or_404(session, Driver, driver_id, principal.org_id, "Driver")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await session.execute(
        select(DriverEvent).where(DriverEvent.driver_id == driver_id,
                                  DriverEvent.occurred_at >= since)
        .order_by(DriverEvent.occurred_at.desc()).limit(200))).scalars().all()
    return [{"id": str(e.id), "type": e.type, "severity": e.severity,
             "occurred_at": e.occurred_at.isoformat(), "street": e.street,
             "lat": e.lat, "lon": e.lon, "value": e.value, "threshold": e.threshold,
             "detail": e.detail, "trip_id": str(e.trip_id) if e.trip_id else None}
            for e in rows]


@router.get("/{driver_id}/points")
async def driver_points(driver_id: uuid.UUID,
                        principal: Principal = Depends(require_tenant),
                        session: AsyncSession = Depends(get_session)):
    d: Driver = await get_or_404(session, Driver, driver_id, principal.org_id, "Driver")
    rows = (await session.execute(
        select(DriverPointTransaction).where(DriverPointTransaction.driver_id == driver_id)
        .order_by(DriverPointTransaction.occurred_at.desc()).limit(100))).scalars().all()
    return {"balance": d.points_balance,
            "transactions": [{"id": str(t.id), "points": t.points,
                              "balance_after": t.balance_after, "reason": t.reason,
                              "detail": t.detail,
                              "occurred_at": t.occurred_at.isoformat()} for t in rows]}


@router.get("/{driver_id}/timeline")
async def driver_timeline(driver_id: uuid.UUID, limit: int = Query(60, le=300),
                          principal: Principal = Depends(require_tenant),
                          session: AsyncSession = Depends(get_session)):
    await get_or_404(session, Driver, driver_id, principal.org_id, "Driver")
    rows = (await session.execute(
        select(TimelineEvent).where(
            TimelineEvent.organization_id == principal.org_id,
            TimelineEvent.entity_type == "driver",
            TimelineEvent.entity_id == driver_id,
        ).order_by(TimelineEvent.occurred_at.desc()).limit(limit))).scalars().all()
    return [{"id": str(r.id), "occurred_at": r.occurred_at.isoformat(),
             "actor_type": r.actor_type, "actor_name": r.actor_name, "action": r.action,
             "description": r.description, "meta": r.meta} for r in rows]
