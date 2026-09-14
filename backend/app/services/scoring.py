"""Driver safety score, points, badges and leaderboard.

Weights are organization settings, never hardcoded (spec 13.2).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DriverEventType, Severity
from app.models import (Badge, Driver, DriverEvent, DriverPointTransaction,
                        DriverScoreSnapshot, Incident, Trip)
from app.services import audit
from app.services.derive import safety_score

BADGES = {
    "clean_streak_7": ("7-Day Clean Streak", "Seven consecutive days with no safety events.", "shield"),
    "eco_driver": ("Eco Driver", "Consumption in the fleet's best quartile this month.", "leaf"),
    "most_improved": ("Most Improved", "Largest safety-score gain this month.", "trending-up"),
    "safety_champion": ("Safety Champion", "Highest safety score in the fleet this month.", "award"),
}

PENALTY_EVENTS = {
    DriverEventType.OVERSPEED, DriverEventType.HARSH_BRAKING,
    DriverEventType.HARSH_ACCELERATION, DriverEventType.HARSH_CORNERING,
    DriverEventType.GEOFENCE_BREACH, DriverEventType.ROUTE_DEVIATION,
    DriverEventType.IDLING,
}


async def record_event(
    session: AsyncSession, *, org_id: uuid.UUID, driver: Driver, event_type: str,
    occurred_at: datetime, org_settings: dict | None = None,
    vehicle_id: uuid.UUID | None = None, trip_id: uuid.UUID | None = None,
    alert_id: uuid.UUID | None = None, lat: float | None = None, lon: float | None = None,
    street: str | None = None, value: float | None = None, threshold: float | None = None,
    duration_s: float | None = None, severity: str = Severity.MEDIUM,
    detail: str | None = None,
) -> DriverEvent:
    """One driver event -> event row + points transaction + score recalculation."""
    cfg = org_settings or {}
    event = DriverEvent(
        organization_id=org_id, driver_id=driver.id, vehicle_id=vehicle_id,
        trip_id=trip_id, alert_id=alert_id, type=event_type, severity=severity,
        occurred_at=occurred_at, lat=lat, lon=lon, street=street, value=value,
        threshold=threshold, duration_s=duration_s, detail=detail,
    )
    session.add(event)
    await session.flush()

    points_map = cfg.get("driver_points", {})
    delta = int(points_map.get(event_type, 0))
    if delta:
        driver.points_balance = max(0, driver.points_balance + delta)
        session.add(DriverPointTransaction(
            organization_id=org_id, driver_id=driver.id, event_id=event.id,
            points=delta, balance_after=driver.points_balance,
            reason=event_type, detail=detail, occurred_at=occurred_at,
        ))

    await recalculate_score(session, org_id=org_id, driver=driver, org_settings=cfg)
    await audit.timeline(
        session, organization_id=org_id, entity_type="driver", entity_id=driver.id,
        action=event_type, occurred_at=occurred_at,
        description=detail or f"{event_type.replace('_', ' ').title()} recorded.",
        related_type="driver_event", related_id=event.id,
        meta={"points": delta, "value": value},
    )
    return event


async def recalculate_score(session: AsyncSession, *, org_id: uuid.UUID, driver: Driver,
                            org_settings: dict | None = None, window_days: int = 30) -> float:
    """Rolling 30-day score, normalised by distance driven."""
    cfg = org_settings or {}
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    rows = (await session.execute(
        select(DriverEvent.type, func.count()).where(
            DriverEvent.driver_id == driver.id,
            DriverEvent.occurred_at >= since,
            DriverEvent.type.in_(tuple(PENALTY_EVENTS)),
        ).group_by(DriverEvent.type)
    )).all()
    counts = {t: n for t, n in rows}
    incidents = (await session.execute(
        select(func.count()).select_from(Incident).where(
            Incident.driver_id == driver.id, Incident.occurred_at >= since
        )
    )).scalar_one()
    if incidents:
        counts["incident"] = incidents
    distance = (await session.execute(
        select(func.coalesce(func.sum(Trip.distance_km), 0.0)).where(
            Trip.driver_id == driver.id, Trip.started_at >= since
        )
    )).scalar_one()

    score = safety_score(counts, float(distance), cfg.get("safety_weights"))
    if abs(score - driver.safety_score) >= 0.05:
        driver.previous_safety_score = driver.safety_score
    driver.safety_score = score

    today = date.today()
    snapshot = (await session.execute(
        select(DriverScoreSnapshot).where(DriverScoreSnapshot.driver_id == driver.id,
                                          DriverScoreSnapshot.day == today)
    )).scalars().first()
    if snapshot is None:
        session.add(DriverScoreSnapshot(
            organization_id=org_id, driver_id=driver.id, day=today, score=score,
            distance_km=float(distance), event_counts=counts,
        ))
    else:
        snapshot.score = score
        snapshot.distance_km = float(distance)
        snapshot.event_counts = counts
    return score


async def award_badge(session: AsyncSession, *, org_id: uuid.UUID, driver: Driver,
                      code: str, period: str | None = None,
                      now: datetime | None = None) -> Badge | None:
    now = now or datetime.now(timezone.utc)
    period = period or now.strftime("%Y-%m")
    existing = (await session.execute(
        select(Badge).where(Badge.driver_id == driver.id, Badge.code == code,
                            Badge.period == period)
    )).scalars().first()
    if existing:
        return None
    name, description, icon = BADGES[code]
    badge = Badge(organization_id=org_id, driver_id=driver.id, code=code, name=name,
                  description=description, icon=icon, awarded_at=now, period=period)
    session.add(badge)
    return badge


async def evaluate_badges(session: AsyncSession, *, org_id: uuid.UUID,
                          now: datetime | None = None) -> list[Badge]:
    """Runs the badge rules across the org. Idempotent per period."""
    now = now or datetime.now(timezone.utc)
    period = now.strftime("%Y-%m")
    drivers = (await session.execute(
        select(Driver).where(Driver.organization_id == org_id)
    )).scalars().all()
    if not drivers:
        return []
    awarded: list[Badge] = []

    week_ago = now - timedelta(days=7)
    for d in drivers:
        n = (await session.execute(
            select(func.count()).select_from(DriverEvent).where(
                DriverEvent.driver_id == d.id, DriverEvent.occurred_at >= week_ago,
                DriverEvent.type.in_(tuple(PENALTY_EVENTS)),
            )
        )).scalar_one()
        drove = (await session.execute(
            select(func.count()).select_from(Trip).where(
                Trip.driver_id == d.id, Trip.started_at >= week_ago)
        )).scalar_one()
        if n == 0 and drove > 0:
            b = await award_badge(session, org_id=org_id, driver=d,
                                  code="clean_streak_7", period=period, now=now)
            if b:
                awarded.append(b)

    champion = max(drivers, key=lambda d: d.safety_score)
    if champion.safety_score >= 90:
        b = await award_badge(session, org_id=org_id, driver=champion,
                              code="safety_champion", period=period, now=now)
        if b:
            awarded.append(b)

    improved = max(drivers, key=lambda d: d.safety_score - d.previous_safety_score)
    if improved.safety_score - improved.previous_safety_score >= 3:
        b = await award_badge(session, org_id=org_id, driver=improved,
                              code="most_improved", period=period, now=now)
        if b:
            awarded.append(b)
    return awarded


async def leaderboard(session: AsyncSession, org_id: uuid.UUID, limit: int = 20) -> list[dict]:
    """Monthly standings. Visibility to drivers is an org setting."""
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0,
                                                     microsecond=0)
    drivers = (await session.execute(
        select(Driver).where(Driver.organization_id == org_id)
        .order_by(Driver.safety_score.desc(), Driver.points_balance.desc()).limit(limit)
    )).scalars().all()
    out = []
    for rank, d in enumerate(drivers, start=1):
        km = (await session.execute(
            select(func.coalesce(func.sum(Trip.distance_km), 0.0)).where(
                Trip.driver_id == d.id, Trip.started_at >= month_start)
        )).scalar_one()
        events = (await session.execute(
            select(func.count()).select_from(DriverEvent).where(
                DriverEvent.driver_id == d.id, DriverEvent.occurred_at >= month_start,
                DriverEvent.type.in_(tuple(PENALTY_EVENTS)))
        )).scalar_one()
        out.append({
            "rank": rank, "driver_id": str(d.id), "name": d.full_name,
            "safety_score": d.safety_score, "points": d.points_balance,
            "distance_km": round(float(km), 1), "events": events,
            "trend": round(d.safety_score - d.previous_safety_score, 1),
            "avatar_color": d.avatar_color,
        })
    return out
