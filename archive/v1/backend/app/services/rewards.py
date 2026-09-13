"""Driver rewards, penalty points, badges and the leaderboard (Section 4g).

Points are an incentive each Organization tunes for itself, so every weight
comes from ``OrganizationSettings`` and none is hardcoded (Section 9). The
ledger is append-only: a balance nobody can explain is a balance drivers will
dispute, so every change records what caused it.

This reads the same ``DriverEvent`` stream the safety score reads - one
pipeline, two consumers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import TenantScope
from app.models.driver import Driver, DriverBadge, DriverEvent, PointsLedgerEntry
from app.models.enums import VIOLATION_EVENT_TYPES, DriverEventType
from app.models.organization import OrganizationSettings
from app.models.tracking import Trip

#: The shipped badge catalogue. Backend-defined on purpose: a badge-authoring
#: UI is explicitly out of scope for MVP (Section 4g).
BADGES: dict[str, dict[str, str]] = {
    "clean_streak_7": {
        "name": "7-Day Clean Streak",
        "description": "Seven consecutive days with no violations.",
    },
    "eco_driver_month": {
        "name": "Eco Driver of the Month",
        "description": "Lowest fuel burn per 100 km across the fleet this month.",
    },
    "most_improved": {
        "name": "Most Improved",
        "description": "Largest month-over-month gain in points.",
    },
    "spotless_month": {
        "name": "Spotless Month",
        "description": "A full calendar month with no violations at all.",
    },
}

#: Days without a violation that earn the clean-streak reward.
CLEAN_STREAK_DAYS = 7


def utcnow() -> datetime:
    return datetime.now(UTC)


def period_of(moment: datetime | date | None = None) -> str:
    value = moment or utcnow()
    if isinstance(value, datetime):
        value = value.date()
    return f"{value.year:04d}-{value.month:02d}"


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass(slots=True)
class PointsOutcome:
    driver_id: uuid.UUID
    events_applied: int
    delta: int
    balance: int
    badges_awarded: list[str]


async def _settings(
    db: AsyncSession, organization_id: uuid.UUID
) -> OrganizationSettings | None:
    result = await db.execute(
        sa.select(OrganizationSettings)
        .where(OrganizationSettings.organization_id == organization_id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _record(
    db: AsyncSession,
    *,
    driver: Driver,
    delta: int,
    reason: str,
    period: str,
    event_id: uuid.UUID | None = None,
) -> int:
    """Apply a points change and append the ledger entry explaining it."""
    # Points floor at zero (Section 4g): a balance that can go negative stops
    # motivating anyone once it does.
    new_balance = max(0, driver.points_balance + delta)
    applied = new_balance - driver.points_balance
    driver.points_balance = new_balance
    driver.points_month = period

    db.add(
        PointsLedgerEntry(
            organization_id=driver.organization_id,
            driver_id=driver.id,
            driver_event_id=event_id,
            delta=applied,
            balance_after=new_balance,
            reason=reason[:200],
            period_month=period,
        )
    )
    return applied


async def apply_pending_events(
    db: AsyncSession, organization_id: uuid.UUID, *, now: datetime | None = None
) -> list[PointsOutcome]:
    """Consume unprocessed driver events into points.

    ``DriverEvent.points_applied`` is the idempotency guard: an event is
    counted exactly once no matter how often this runs.
    """
    moment = now or utcnow()
    period = period_of(moment)
    settings_row = await _settings(db, organization_id)

    rows = await db.execute(
        sa.select(DriverEvent)
        .where(
            DriverEvent.organization_id == organization_id,
            DriverEvent.points_applied.is_(False),
            DriverEvent.driver_id.is_not(None),
        )
        .order_by(DriverEvent.occurred_at)
    )
    events = list(rows.scalars().all())
    if not events:
        return []

    driver_ids = {e.driver_id for e in events if e.driver_id}
    drivers = {
        d.id: d
        for d in (
            await db.execute(sa.select(Driver).where(Driver.id.in_(driver_ids)))
        )
        .scalars()
        .all()
    }

    outcomes: dict[uuid.UUID, PointsOutcome] = {}
    for event in events:
        driver = drivers.get(event.driver_id)
        if driver is None:
            # The driver was removed; mark it handled so it is not retried.
            event.points_applied = True
            continue

        weight = (
            settings_row.point_weight(event.event_type)
            if settings_row
            else _default_weight(event.event_type)
        )
        event.points_applied = True
        if weight == 0:
            continue

        label = event.event_type.replace("_", " ")
        applied = await _record(
            db,
            driver=driver,
            delta=weight,
            reason=f"{label.capitalize()} on {_aware(event.occurred_at):%Y-%m-%d}"
            if _aware(event.occurred_at)
            else label.capitalize(),
            period=period,
            event_id=event.id,
        )

        outcome = outcomes.setdefault(
            driver.id,
            PointsOutcome(
                driver_id=driver.id,
                events_applied=0,
                delta=0,
                balance=driver.points_balance,
                badges_awarded=[],
            ),
        )
        outcome.events_applied += 1
        outcome.delta += applied
        outcome.balance = driver.points_balance

    await db.flush()
    return list(outcomes.values())


def _default_weight(event_type: str) -> int:
    from app.models.organization import DEFAULT_POINT_WEIGHTS

    return int(DEFAULT_POINT_WEIGHTS.get(event_type, 0))


async def award_clean_streaks(
    db: AsyncSession, organization_id: uuid.UUID, *, now: datetime | None = None
) -> list[tuple[uuid.UUID, str]]:
    """Reward drivers who have driven violation-free for the streak window.

    The reward is granted once per streak window rather than daily, so it
    stays meaningful instead of becoming a participation trophy.
    """
    moment = now or utcnow()
    period = period_of(moment)
    window_start = moment - timedelta(days=CLEAN_STREAK_DAYS)
    settings_row = await _settings(db, organization_id)
    reward = (
        settings_row.point_weight(DriverEventType.CLEAN_STREAK)
        if settings_row
        else _default_weight(DriverEventType.CLEAN_STREAK)
    )

    drivers = list(
        (
            await db.execute(
                sa.select(Driver).where(Driver.organization_id == organization_id)
            )
        )
        .scalars()
        .all()
    )
    if not drivers or reward <= 0:
        return []

    driver_ids = [d.id for d in drivers]

    violations = {
        row[0]
        for row in (
            await db.execute(
                sa.select(DriverEvent.driver_id)
                .where(
                    DriverEvent.driver_id.in_(driver_ids),
                    DriverEvent.occurred_at >= window_start,
                    DriverEvent.event_type.in_(list(VIOLATION_EVENT_TYPES)),
                )
                .distinct()
            )
        ).all()
    }

    # Only count drivers who actually drove in the window - a parked driver
    # has not earned a safe-driving reward.
    drove = {
        row[0]
        for row in (
            await db.execute(
                sa.select(Trip.driver_id)
                .where(
                    Trip.driver_id.in_(driver_ids),
                    Trip.started_at >= window_start,
                    Trip.distance_km > 0,
                )
                .distinct()
            )
        ).all()
    }

    awarded: list[tuple[uuid.UUID, str]] = []
    for driver in drivers:
        if driver.id in violations or driver.id not in drove:
            continue
        if await _has_badge(db, driver.id, "clean_streak_7", period):
            continue

        await _record(
            db,
            driver=driver,
            delta=reward,
            reason=f"{CLEAN_STREAK_DAYS}-day violation-free streak",
            period=period,
        )
        db.add(
            DriverBadge(
                organization_id=organization_id,
                driver_id=driver.id,
                badge_code="clean_streak_7",
                period_month=period,
                awarded_at=moment,
                context={"window_days": CLEAN_STREAK_DAYS},
            )
        )
        awarded.append((driver.id, "clean_streak_7"))

    await db.flush()
    return awarded


async def _has_badge(
    db: AsyncSession, driver_id: uuid.UUID, code: str, period: str
) -> bool:
    result = await db.execute(
        sa.select(DriverBadge.id)
        .where(
            DriverBadge.driver_id == driver_id,
            DriverBadge.badge_code == code,
            DriverBadge.period_month == period,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def leaderboard(
    db: AsyncSession,
    scope: TenantScope,
    *,
    period: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Ranked drivers for the current month, with their badges."""
    current = period or period_of()

    drivers = list(
        (
            await db.execute(
                scope.select(Driver).order_by(
                    Driver.points_balance.desc(), Driver.full_name
                )
            )
        )
        .scalars()
        .all()
    )[:limit]
    if not drivers:
        return []

    badge_rows = await db.execute(
        scope.select(DriverBadge).where(
            DriverBadge.driver_id.in_([d.id for d in drivers]),
            DriverBadge.period_month == current,
        )
    )
    badges: dict[uuid.UUID, list[str]] = {}
    for badge in badge_rows.scalars().all():
        badges.setdefault(badge.driver_id, []).append(badge.badge_code)

    # Ties share a rank: two drivers on 118 points are not first and second.
    rows: list[dict] = []
    last_points: int | None = None
    last_rank = 0
    for index, driver in enumerate(drivers, start=1):
        if driver.points_balance != last_points:
            last_rank = index
            last_points = driver.points_balance
        rows.append(
            {
                "rank": last_rank,
                "driver_id": driver.id,
                "driver_name": driver.full_name,
                "points_balance": driver.points_balance,
                "safety_score": driver.safety_score,
                "fatigue_risk_level": driver.fatigue_risk_level,
                "badges": badges.get(driver.id, []),
            }
        )
    return rows


async def driver_ledger(
    db: AsyncSession, scope: TenantScope, *, driver_id: uuid.UUID, limit: int = 50
) -> list[PointsLedgerEntry]:
    result = await db.execute(
        scope.select(PointsLedgerEntry)
        .where(PointsLedgerEntry.driver_id == driver_id)
        .order_by(PointsLedgerEntry.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def reset_monthly_balances(
    db: AsyncSession, organization_id: uuid.UUID, *, now: datetime | None = None
) -> int:
    """Reset balances to the Organization's baseline at the start of a month.

    The leaderboard resets monthly (Section 4g), but the ledger does not: last
    month's entries stay, so a driver can still see how they got there.
    """
    moment = now or utcnow()
    period = period_of(moment)
    settings_row = await _settings(db, organization_id)
    baseline = settings_row.driver_points_baseline if settings_row else 100

    drivers = list(
        (
            await db.execute(
                sa.select(Driver).where(
                    Driver.organization_id == organization_id,
                    sa.or_(Driver.points_month.is_(None), Driver.points_month != period),
                )
            )
        )
        .scalars()
        .all()
    )

    for driver in drivers:
        # "Most Improved" is judged on where they finished last month.
        db.add(
            PointsLedgerEntry(
                organization_id=organization_id,
                driver_id=driver.id,
                delta=baseline - driver.points_balance,
                balance_after=baseline,
                reason=f"Monthly reset to baseline for {period}",
                period_month=period,
            )
        )
        driver.points_balance = baseline
        driver.points_month = period

    await db.flush()
    return len(drivers)
