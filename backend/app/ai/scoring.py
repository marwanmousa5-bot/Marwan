"""Driver behaviour scoring and the fatigue indicator (Section 5, item 1).

Both are rule-based for MVP, and both are deliberately shaped as pure
functions over a window of events and trips. That is what makes the swap to a
trained model a one-file change: the interfaces below take structured inputs
and return a score plus the evidence behind it, which is also what the UI
needs in order to explain a number to the driver it describes.

Everything reads from the single shared ``DriverEvent`` stream (Section 4g),
so the safety score and the points system can never disagree about what
happened.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import Driver, DriverEvent
from app.models.enums import DriverEventType
from app.models.organization import OrganizationSettings
from app.models.tracking import Trip

#: How far back the rolling safety score looks.
SCORE_WINDOW = timedelta(days=30)

#: Severity weight per violation, before normalising by distance. These are
#: *scoring* weights, distinct from the Org-configurable points weights: a
#: safety score must stay comparable across organizations, while points are a
#: local incentive each Organization tunes for itself (Section 4g).
VIOLATION_WEIGHTS: dict[str, float] = {
    DriverEventType.SPEEDING: 3.0,
    DriverEventType.HARSH_BRAKING: 2.0,
    DriverEventType.HARSH_ACCELERATION: 1.5,
    DriverEventType.GEOFENCE_BREACH: 1.0,
}

#: Weighted violations per 100 km at which the score reaches 0. Chosen so a
#: normal fleet sits in the 80-100 band and a genuinely poor driver is
#: visibly separated, rather than everyone clustering near 100.
ZERO_SCORE_RATE = 12.0

#: Below this distance a per-100 km rate is too noisy to be fair. Two events
#: over 25 km reads as a catastrophic driver; over 250 km - a few days of real
#: work - the same two events read as what they are. Until a driver clears
#: this, the score stays provisional rather than being invented from a handful
#: of samples.
MIN_DISTANCE_KM = 250.0


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass(slots=True)
class SafetyScore:
    driver_id: uuid.UUID
    score: float
    distance_km: float
    violations: dict[str, int] = field(default_factory=dict)
    weighted_rate: float = 0.0
    #: True when there was too little driving to judge; score stays at the
    #: baseline rather than being invented from one or two events.
    provisional: bool = True

    @property
    def band(self) -> str:
        if self.score >= 90:
            return "excellent"
        if self.score >= 75:
            return "good"
        if self.score >= 60:
            return "needs_attention"
        return "at_risk"


@dataclass(slots=True)
class FatigueAssessment:
    driver_id: uuid.UUID
    level: str  # low | moderate | high
    longest_continuous_hours: float
    shortest_rest_hours: float | None
    hours_last_24: float
    reasons: list[str] = field(default_factory=list)


def compute_safety_score(
    *,
    driver_id: uuid.UUID,
    violations: dict[str, int],
    distance_km: float,
    baseline: float = 100.0,
) -> SafetyScore:
    """Weighted violations per 100 km, mapped onto 0-100.

    Normalising by distance is the whole point: a long-haul driver will
    always accumulate more raw events than a depot shuttle, and ranking them
    by raw counts would punish the person who drives the most.
    """
    if distance_km < MIN_DISTANCE_KM:
        return SafetyScore(
            driver_id=driver_id,
            score=baseline,
            distance_km=distance_km,
            violations=violations,
            provisional=True,
        )

    weighted = sum(
        VIOLATION_WEIGHTS.get(event_type, 1.0) * count
        for event_type, count in violations.items()
    )
    rate = weighted / (distance_km / 100.0)
    score = max(0.0, min(100.0, baseline * (1.0 - rate / ZERO_SCORE_RATE)))

    return SafetyScore(
        driver_id=driver_id,
        score=round(score, 1),
        distance_km=round(distance_km, 1),
        violations=violations,
        weighted_rate=round(rate, 2),
        provisional=False,
    )


def assess_fatigue(
    *,
    driver_id: uuid.UUID,
    trips: list[tuple[datetime, datetime]],
    max_continuous_hours: float,
    min_rest_hours: float,
    now: datetime | None = None,
) -> FatigueAssessment:
    """Rule-based fatigue risk from driving-hour patterns.

    ``trips`` is ``(started_at, ended_at)`` pairs, most recent last.
    Consecutive trips separated by less than 15 minutes are treated as one
    continuous stint - a delivery stop is not a rest break.
    """
    moment = now or utcnow()
    reasons: list[str] = []

    ordered = sorted(
        (
            (_aware(start), _aware(end) or moment)
            for start, end in trips
            if start is not None
        ),
        key=lambda pair: pair[0],
    )

    longest = 0.0
    shortest_rest: float | None = None
    hours_last_24 = 0.0
    day_ago = moment - timedelta(hours=24)

    stint_start: datetime | None = None
    stint_end: datetime | None = None

    for start, end in ordered:
        overlap_start = max(start, day_ago)
        if end > overlap_start:
            hours_last_24 += (end - overlap_start).total_seconds() / 3600.0

        if stint_start is None:
            stint_start, stint_end = start, end
            continue

        gap_hours = (start - stint_end).total_seconds() / 3600.0
        if gap_hours <= 0.25:
            stint_end = max(stint_end, end)
            continue

        longest = max(longest, (stint_end - stint_start).total_seconds() / 3600.0)
        shortest_rest = (
            gap_hours if shortest_rest is None else min(shortest_rest, gap_hours)
        )
        stint_start, stint_end = start, end

    if stint_start is not None and stint_end is not None:
        longest = max(longest, (stint_end - stint_start).total_seconds() / 3600.0)

    level = "low"
    if longest >= max_continuous_hours:
        level = "high" if longest >= max_continuous_hours * 1.3 else "moderate"
        reasons.append(
            f"{longest:.1f}h of continuous driving "
            f"(limit {max_continuous_hours:.1f}h)"
        )
    if shortest_rest is not None and shortest_rest < min_rest_hours:
        level = "high" if level == "moderate" else max(level, "moderate", key=_rank)
        reasons.append(
            f"only {shortest_rest:.1f}h rest between shifts "
            f"(minimum {min_rest_hours:.1f}h)"
        )
    if hours_last_24 >= max_continuous_hours * 2:
        level = "high"
        reasons.append(f"{hours_last_24:.1f}h driven in the last 24 hours")

    return FatigueAssessment(
        driver_id=driver_id,
        level=level,
        longest_continuous_hours=round(longest, 2),
        shortest_rest_hours=round(shortest_rest, 2) if shortest_rest is not None else None,
        hours_last_24=round(hours_last_24, 2),
        reasons=reasons,
    )


def _rank(level: str) -> int:
    return {"low": 0, "moderate": 1, "high": 2}.get(level, 0)


# ---------------------------------------------------------------------------
# Database-backed entry points
# ---------------------------------------------------------------------------

async def score_organization_drivers(
    db: AsyncSession, organization_id: uuid.UUID, *, now: datetime | None = None
) -> list[tuple[Driver, SafetyScore, FatigueAssessment]]:
    """Recompute every driver's score and fatigue level for one Organization."""
    moment = now or utcnow()
    window_start = moment - SCORE_WINDOW

    settings_row = (
        await db.execute(
            sa.select(OrganizationSettings)
            .where(OrganizationSettings.organization_id == organization_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    max_continuous = (
        settings_row.threshold("fatigue_continuous_driving_hours")
        if settings_row
        else 4.5
    )
    min_rest = settings_row.threshold("fatigue_min_rest_hours") if settings_row else 8.0

    drivers = list(
        (
            await db.execute(
                sa.select(Driver).where(Driver.organization_id == organization_id)
            )
        )
        .scalars()
        .all()
    )
    if not drivers:
        return []

    driver_ids = [d.id for d in drivers]

    violation_rows = await db.execute(
        sa.select(DriverEvent.driver_id, DriverEvent.event_type, sa.func.count())
        .where(
            DriverEvent.driver_id.in_(driver_ids),
            DriverEvent.occurred_at >= window_start,
            DriverEvent.event_type.in_(list(VIOLATION_WEIGHTS)),
        )
        .group_by(DriverEvent.driver_id, DriverEvent.event_type)
    )
    violations: dict[uuid.UUID, dict[str, int]] = {}
    for driver_id, event_type, count in violation_rows.all():
        violations.setdefault(driver_id, {})[event_type] = int(count)

    distance_rows = await db.execute(
        sa.select(
            Trip.driver_id, sa.func.coalesce(sa.func.sum(Trip.distance_km), 0.0)
        )
        .where(Trip.driver_id.in_(driver_ids), Trip.started_at >= window_start)
        .group_by(Trip.driver_id)
    )
    distances = {row[0]: float(row[1]) for row in distance_rows.all()}

    trip_rows = await db.execute(
        sa.select(Trip.driver_id, Trip.started_at, Trip.ended_at)
        .where(
            Trip.driver_id.in_(driver_ids),
            Trip.started_at >= moment - timedelta(days=3),
        )
        .order_by(Trip.started_at)
    )
    trips_by_driver: dict[uuid.UUID, list[tuple[datetime, datetime]]] = {}
    for driver_id, started, ended in trip_rows.all():
        trips_by_driver.setdefault(driver_id, []).append((started, ended))

    results = []
    for driver in drivers:
        score = compute_safety_score(
            driver_id=driver.id,
            violations=violations.get(driver.id, {}),
            distance_km=distances.get(driver.id, 0.0),
        )
        fatigue = assess_fatigue(
            driver_id=driver.id,
            trips=trips_by_driver.get(driver.id, []),
            max_continuous_hours=max_continuous,
            min_rest_hours=min_rest,
            now=moment,
        )

        driver.safety_score = score.score
        driver.fatigue_risk_level = fatigue.level
        driver.fatigue_computed_at = moment
        results.append((driver, score, fatigue))

    await db.flush()
    return results
