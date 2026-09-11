"""AI Fleet Copilot (Section 4e) and Maintenance Copilot (Section 5, item 2).

Both follow the same division of labour, and it is the important part: *our*
rule-based comparison against the plan decides what is happening; the model
only phrases and ranks it. An LLM asked to work out whether a van is late
would occasionally invent a delay, and a panel that invents delays is worse
than no panel.

Neither copilot changes anything. Recommendations are proposals with an
explicit Apply step (Section 9), and the Maintenance Copilot only creates a
work order by itself when the Organization has opted into auto-booking -
which is off by default, because an auto-created work order costs real money.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import get_claude_client
from app.ai.predictive import forecast_due_maintenance
from app.models.ai import Recommendation
from app.models.alert import Alert
from app.models.driver import Driver
from app.models.enums import (
    AlertStatus,
    RecommendationKind,
    RecommendationStatus,
    TaskStatus,
    WorkOrderStatus,
)
from app.models.maintenance import WorkOrder
from app.models.organization import OrganizationSettings
from app.models.task import Task
from app.models.vehicle import Vehicle
from app.models.weather import WeatherZone
from app.services import geo

#: A task is "trending late" once its ETA is this far past its due time.
LATE_THRESHOLD = timedelta(minutes=10)
#: Recommendations go stale quickly - the situation they describe moves.
RECOMMENDATION_TTL = timedelta(hours=2)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass(slots=True)
class Signal:
    """One rule-derived fact about the fleet, ready to be phrased."""

    kind: str
    title: str
    detail: str
    impact_minutes: int = 0
    vehicle_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    dedupe_key: str = ""
    suggested_action: str | None = None
    action_payload: dict | None = None
    facts: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Signal gathering - all of this is ours, none of it is the model's
# ---------------------------------------------------------------------------

async def gather_signals(
    db: AsyncSession, organization_id: uuid.UUID, *, now: datetime | None = None
) -> list[Signal]:
    """Compare the fleet against its plan and return what has diverged."""
    moment = now or utcnow()
    signals: list[Signal] = []

    open_tasks = (
        await db.execute(
            sa.select(Task).where(
                Task.organization_id == organization_id,
                Task.status.in_(
                    [TaskStatus.ASSIGNED, TaskStatus.ACCEPTED, TaskStatus.EN_ROUTE]
                ),
            )
        )
    ).scalars().all()

    vehicles = {
        v.id: v
        for v in (
            await db.execute(
                sa.select(Vehicle).where(Vehicle.organization_id == organization_id)
            )
        ).scalars().all()
    }
    drivers = {
        d.id: d
        for d in (
            await db.execute(
                sa.select(Driver).where(Driver.organization_id == organization_id)
            )
        ).scalars().all()
    }

    # --- tasks trending late against their own ETA ---
    late: list[Task] = []
    for task in open_tasks:
        due = _aware(task.due_at)
        eta = _aware(task.eta)
        if due is None or eta is None:
            continue
        drift = eta - due
        if drift > LATE_THRESHOLD:
            late.append(task)
            driver = drivers.get(task.driver_id) if task.driver_id else None
            signals.append(
                Signal(
                    kind="late_task",
                    title=f"{task.title} is trending late",
                    detail=(
                        f"ETA {eta:%H:%M} against a {due:%H:%M} due time - "
                        f"about {int(drift.total_seconds() // 60)} minutes over."
                    ),
                    impact_minutes=int(drift.total_seconds() // 60),
                    vehicle_id=task.vehicle_id,
                    task_id=task.id,
                    driver_id=task.driver_id,
                    dedupe_key=f"late:{task.id}:{moment:%Y%m%d%H}",
                    facts={
                        "task": task.title,
                        "driver": driver.full_name if driver else None,
                        "minutes_late": int(drift.total_seconds() // 60),
                    },
                )
            )

    # --- vehicles driving into adverse weather ---
    zones = (
        await db.execute(
            sa.select(WeatherZone).where(
                WeatherZone.organization_id == organization_id
            )
        )
    ).scalars().all()
    for task in open_tasks:
        vehicle = vehicles.get(task.vehicle_id) if task.vehicle_id else None
        if vehicle is None or vehicle.last_latitude is None:
            continue
        for zone in zones:
            if geo.point_in_circle(
                vehicle.last_latitude,
                vehicle.last_longitude,
                [zone.longitude, zone.latitude],
                zone.radius_m,
            ):
                signals.append(
                    Signal(
                        kind="weather_delay",
                        title=f"{vehicle.name} is in {zone.condition.replace('_', ' ')}",
                        detail=(
                            f"Expect roughly {zone.expected_delay_minutes} minutes "
                            f"of delay on '{task.title}'."
                        ),
                        impact_minutes=zone.expected_delay_minutes,
                        vehicle_id=vehicle.id,
                        task_id=task.id,
                        dedupe_key=f"weather:{task.id}:{zone.condition}:{moment:%Y%m%d%H}",
                        facts={
                            "vehicle": vehicle.name,
                            "condition": zone.condition,
                            "expected_delay_minutes": zone.expected_delay_minutes,
                        },
                    )
                )
                break

    # --- an unassigned task while a driver sits idle ---
    unassigned = [t for t in open_tasks if t.driver_id is None]
    busy_driver_ids = {t.driver_id for t in open_tasks if t.driver_id}
    idle_drivers = [
        d
        for d in drivers.values()
        if d.id not in busy_driver_ids and d.assigned_vehicle_id is not None
    ]
    for task in unassigned:
        if not idle_drivers:
            break
        candidate = idle_drivers[0]
        signals.append(
            Signal(
                kind="unassigned_task",
                title=f"{task.title} has no driver",
                detail=(
                    f"{candidate.full_name} has no open work and a vehicle "
                    "assigned."
                ),
                impact_minutes=0,
                task_id=task.id,
                driver_id=candidate.id,
                dedupe_key=f"unassigned:{task.id}",
                suggested_action=f"Assign this task to {candidate.full_name}",
                action_payload={
                    "op": "assign_task",
                    "task_id": str(task.id),
                    "driver_id": str(candidate.id),
                },
                facts={"task": task.title, "candidate": candidate.full_name},
            )
        )

    # --- a vehicle carrying several active alerts at once ---
    alert_rows = await db.execute(
        sa.select(Alert.vehicle_id, sa.func.count())
        .where(
            Alert.organization_id == organization_id,
            Alert.status == AlertStatus.ACTIVE,
            Alert.vehicle_id.is_not(None),
        )
        .group_by(Alert.vehicle_id)
    )
    for vehicle_id, count in alert_rows.all():
        if count < 3:
            continue
        vehicle = vehicles.get(vehicle_id)
        if vehicle is None:
            continue
        signals.append(
            Signal(
                kind="alert_cluster",
                title=f"{vehicle.name} has {count} open alerts",
                detail="Several unresolved alerts on one vehicle usually means "
                "one underlying problem.",
                vehicle_id=vehicle_id,
                dedupe_key=f"alerts:{vehicle_id}:{moment:%Y%m%d}",
                facts={"vehicle": vehicle.name, "open_alerts": int(count)},
            )
        )

    signals.sort(key=lambda s: s.impact_minutes, reverse=True)
    return signals


# ---------------------------------------------------------------------------
# Turning signals into recommendation cards
# ---------------------------------------------------------------------------

async def run_copilot(
    db: AsyncSession, organization_id: uuid.UUID, *, now: datetime | None = None
) -> list[Recommendation]:
    """One analysis pass. Returns the recommendations it created."""
    moment = now or utcnow()
    signals = await gather_signals(db, organization_id, now=moment)
    if not signals:
        return []

    phrasing = await _phrase(organization_id, signals)

    created: list[Recommendation] = []
    ranked_keys: list[str] = []
    for index, signal in enumerate(signals[:5]):
        existing = (
            await db.execute(
                sa.select(Recommendation)
                .where(
                    Recommendation.organization_id == organization_id,
                    Recommendation.dedupe_key == signal.dedupe_key,
                    Recommendation.status == RecommendationStatus.PENDING,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        ranked_keys.append(signal.dedupe_key)
        if existing is not None:
            # The card is already on screen. Re-rank it against this pass -
            # skipping it outright would leave a stale rank colliding with a
            # newly created card.
            existing.rank = index
            continue

        text = phrasing.get(signal.dedupe_key, {})
        recommendation = Recommendation(
            organization_id=organization_id,
            kind=RecommendationKind.COPILOT,
            status=RecommendationStatus.PENDING,
            rank=index,
            title=text.get("title") or signal.title,
            summary=text.get("summary") or signal.detail,
            suggested_action=text.get("action") or signal.suggested_action,
            estimated_benefit=(
                f"~{signal.impact_minutes} min" if signal.impact_minutes else None
            ),
            action_payload=signal.action_payload,
            signals=signal.facts,
            vehicle_id=signal.vehicle_id,
            driver_id=signal.driver_id,
            task_id=signal.task_id,
            dedupe_key=signal.dedupe_key,
            expires_at=moment + RECOMMENDATION_TTL,
        )
        db.add(recommendation)
        created.append(recommendation)

    # Cards whose signal has gone quiet stay until their TTL, but they sort
    # below everything the fleet is doing right now, and they never share a
    # rank with a live card.
    stale = (
        await db.execute(
            sa.select(Recommendation)
            .where(
                Recommendation.organization_id == organization_id,
                Recommendation.status == RecommendationStatus.PENDING,
                Recommendation.dedupe_key.not_in(ranked_keys) if ranked_keys else sa.true(),
            )
            .order_by(Recommendation.created_at.desc())
        )
    ).scalars().all()
    for offset, recommendation in enumerate(stale):
        recommendation.rank = len(ranked_keys) + offset

    await db.flush()
    return created


async def _phrase(
    organization_id: uuid.UUID, signals: list[Signal]
) -> dict[str, dict[str, str]]:
    """Ask the model to word and rank the cards. Facts are already fixed."""
    payload = [
        {
            "id": signal.dedupe_key,
            "kind": signal.kind,
            "facts": signal.facts,
            "impact_minutes": signal.impact_minutes,
            "suggested_action": signal.suggested_action,
        }
        for signal in signals[:5]
    ]

    schema = {
        "type": "object",
        "properties": {
            "cards": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "action": {"type": "string"},
                    },
                    "required": ["id", "title", "summary"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["cards"],
        "additionalProperties": False,
    }

    response = await get_claude_client().complete(
        organization_id=organization_id,
        system=(
            "You write short, plain-language recommendation cards for a fleet "
            "dispatcher. Use ONLY the facts given - never add a number, a "
            "vehicle, or a cause that is not in them. One sentence of "
            "situation, one of suggested action. No preamble."
        ),
        prompt=f"Situations detected:\n{json.dumps(payload, default=str)}",
        json_schema=schema,
        max_tokens=1200,
        effort="low",
    )

    if not response.data:
        return {}
    return {
        card["id"]: card
        for card in response.data.get("cards", [])
        if isinstance(card, dict) and "id" in card
    }


async def list_recommendations(
    db: AsyncSession, organization_id: uuid.UUID
) -> list[Recommendation]:
    result = await db.execute(
        sa.select(Recommendation)
        .where(
            Recommendation.organization_id == organization_id,
            Recommendation.status == RecommendationStatus.PENDING,
        )
        .order_by(Recommendation.rank, Recommendation.created_at.desc())
    )
    now = utcnow()
    live = []
    for recommendation in result.scalars().all():
        expires = _aware(recommendation.expires_at)
        if expires and expires < now:
            recommendation.status = RecommendationStatus.EXPIRED
            continue
        live.append(recommendation)
    return live


# ---------------------------------------------------------------------------
# Maintenance Copilot (Section 5, item 2)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class MaintenanceProposal:
    vehicle_id: uuid.UUID
    vehicle_name: str
    schedule_id: uuid.UUID
    schedule_name: str
    proposed_date: date
    rationale: str
    tasks_that_day: int
    auto_booked: bool = False
    work_order_id: uuid.UUID | None = None


async def propose_maintenance_windows(
    db: AsyncSession,
    organization_id: uuid.UUID,
    *,
    now: datetime | None = None,
    horizon_days: int = 21,
) -> list[MaintenanceProposal]:
    """Suggest the lowest-impact day for each service that is coming due.

    Lowest-impact means fewest assigned tasks: booking a van in on the day it
    has four deliveries is how a maintenance reminder gets ignored.
    """
    moment = now or utcnow()
    forecasts = await forecast_due_maintenance(
        db, organization_id, horizon_days=horizon_days, now=moment
    )
    if not forecasts:
        return []

    settings_row = (
        await db.execute(
            sa.select(OrganizationSettings)
            .where(OrganizationSettings.organization_id == organization_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    auto_book = bool(settings_row and settings_row.maintenance_auto_book_enabled)

    tasks = (
        await db.execute(
            sa.select(Task).where(
                Task.organization_id == organization_id,
                Task.status.in_(
                    [TaskStatus.ASSIGNED, TaskStatus.ACCEPTED, TaskStatus.EN_ROUTE]
                ),
                Task.due_at.is_not(None),
            )
        )
    ).scalars().all()

    load: dict[tuple[uuid.UUID, date], int] = {}
    for task in tasks:
        due = _aware(task.due_at)
        if due is None or task.vehicle_id is None:
            continue
        key = (task.vehicle_id, due.date())
        load[key] = load.get(key, 0) + 1

    proposals: list[MaintenanceProposal] = []
    for forecast in forecasts:
        # Consider the week around the projected due date and take the
        # quietest day, preferring the earliest when several tie.
        candidates = [
            forecast.predicted_due_on + timedelta(days=offset)
            for offset in range(-3, 4)
            if forecast.predicted_due_on + timedelta(days=offset) >= moment.date()
        ]
        if not candidates:
            candidates = [forecast.predicted_due_on]

        best = min(
            candidates,
            key=lambda day: (load.get((forecast.vehicle_id, day), 0), day),
        )
        busy = load.get((forecast.vehicle_id, best), 0)

        proposal = MaintenanceProposal(
            vehicle_id=forecast.vehicle_id,
            vehicle_name=forecast.vehicle_name,
            schedule_id=forecast.schedule_id,
            schedule_name=forecast.schedule_name,
            proposed_date=best,
            tasks_that_day=busy,
            rationale=(
                f"{forecast.summary} {best:%-d %b} is the quietest day in that "
                f"window for {forecast.vehicle_name}"
                + (
                    " - it has no assigned work."
                    if busy == 0
                    else f" - {busy} task(s) assigned."
                )
            ),
        )

        if auto_book:
            work_order = WorkOrder(
                organization_id=organization_id,
                vehicle_id=forecast.vehicle_id,
                schedule_id=forecast.schedule_id,
                title=forecast.schedule_name,
                status=WorkOrderStatus.OPEN,
                scheduled_for=datetime.combine(best, datetime.min.time(), tzinfo=UTC),
                created_by_copilot=True,
                copilot_rationale=proposal.rationale,
            )
            db.add(work_order)
            await db.flush()
            proposal.auto_booked = True
            proposal.work_order_id = work_order.id
        else:
            # Not booked: recorded as a proposal the Org Admin approves with
            # one click. Auto-booking is opt-in precisely because a work
            # order has a real cost attached.
            recommendation = Recommendation(
                organization_id=organization_id,
                kind=RecommendationKind.MAINTENANCE_WINDOW,
                status=RecommendationStatus.PENDING,
                title=f"Book {forecast.schedule_name} for {forecast.vehicle_name}",
                summary=proposal.rationale,
                suggested_action=f"Open a work order for {best:%-d %b}",
                estimated_benefit=(
                    "No disruption to assigned work"
                    if busy == 0
                    else f"Avoids {busy} task clash(es)"
                ),
                action_payload={
                    "op": "create_work_order",
                    "vehicle_id": str(forecast.vehicle_id),
                    "schedule_id": str(forecast.schedule_id),
                    "scheduled_for": best.isoformat(),
                    "title": forecast.schedule_name,
                },
                signals={
                    "days_away": forecast.days_away,
                    "tasks_that_day": busy,
                    "basis": forecast.basis,
                },
                vehicle_id=forecast.vehicle_id,
                dedupe_key=f"maintenance-window:{forecast.schedule_id}:{best}",
                expires_at=moment + timedelta(days=3),
            )
            existing = await db.execute(
                sa.select(Recommendation.id)
                .where(
                    Recommendation.organization_id == organization_id,
                    Recommendation.dedupe_key == recommendation.dedupe_key,
                    Recommendation.status == RecommendationStatus.PENDING,
                )
                .limit(1)
            )
            if existing.scalar_one_or_none() is None:
                db.add(recommendation)

        proposals.append(proposal)

    await db.flush()
    return proposals
