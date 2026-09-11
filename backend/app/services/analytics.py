"""Analytics, cost/TCO and sustainability (Section 4 items 10, 13, 15, 17)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import TenantScope
from app.models.alert import Alert
from app.models.compliance import ComplianceDocument
from app.models.device import Device
from app.models.driver import DriverEvent
from app.models.enums import (
    AlertStatus,
    DeviceStatus,
    FuelType,
    VehicleStatus,
    VehicleType,
)
from app.models.fuel import FuelLog
from app.models.maintenance import WorkOrder
from app.models.tracking import Trip
from app.models.vehicle import Vehicle

#: A vehicle whose daily distance stays this far inside its usable EV range
#: is a comfortable electrification candidate. The margin matters: real range
#: falls in winter and with a load, so recommending on the nominal figure
#: would strand someone.
EV_RANGE_SAFETY_FACTOR = 0.7
#: Typical usable range assumed for a replacement EV when none is specified.
ASSUMED_EV_RANGE_KM = 250.0
#: Days of history needed before an electrification call is worth making.
EV_MIN_HISTORY_DAYS = 21
#: Distance below which a per-km rate is noise rather than a figure.
MIN_DISTANCE_FOR_RATE_KM = 100.0


def utcnow() -> datetime:
    return datetime.now(UTC)


def day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


@dataclass(slots=True)
class VehicleCost:
    vehicle_id: uuid.UUID
    vehicle_name: str
    license_plate: str
    fuel_cost: float = 0.0
    maintenance_cost: float = 0.0
    compliance_cost: float = 0.0
    distance_km: float = 0.0
    depreciation: float = 0.0

    @property
    def total_cost(self) -> float:
        return round(
            self.fuel_cost + self.maintenance_cost + self.compliance_cost, 2
        )

    @property
    def cost_per_km(self) -> float | None:
        """Cost per km, or None when the distance is too small to divide by.

        A vehicle with 25 km of recorded driving and a serviced gearbox
        produces a per-km figure in the tens - arithmetically correct and
        completely useless. Below the floor the answer is "not enough
        distance", not a number.
        """
        if self.distance_km < MIN_DISTANCE_FOR_RATE_KM:
            return None
        return round(self.total_cost / self.distance_km, 3)


@dataclass(slots=True)
class FleetKpis:
    total_vehicles: int
    active_vehicles: int
    tracked_vehicles: int
    total_drivers: int
    trips: int
    distance_km: float
    driving_hours: float
    #: Share of active vehicles that moved at all in the period.
    utilisation_percent: float
    total_cost: float
    cost_per_km: float | None
    fuel_cost: float
    maintenance_cost: float
    co2_kg: float
    active_alerts: int
    violations: int
    average_safety_score: float


@dataclass(slots=True)
class TrendPoint:
    period: str
    distance_km: float = 0.0
    cost: float = 0.0
    co2_kg: float = 0.0
    violations: int = 0


@dataclass(slots=True)
class EvCandidate:
    vehicle_id: uuid.UUID
    vehicle_name: str
    license_plate: str
    days_observed: int
    average_daily_km: float
    max_daily_km: float
    assumed_range_km: float
    annual_fuel_cost: float
    rationale: str


@dataclass(slots=True)
class AssetSummary:
    vehicle_id: uuid.UUID
    vehicle_name: str
    purchase_value: float | None
    age_years: float | None
    annual_depreciation: float | None
    book_value: float | None
    odometer_km: float
    replacement_recommended: bool
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Cost / TCO
# ---------------------------------------------------------------------------

async def vehicle_costs(
    db: AsyncSession,
    scope: TenantScope,
    *,
    date_from: date,
    date_to: date,
) -> list[VehicleCost]:
    """Total cost of ownership per vehicle over a period."""
    start, end = day_start(date_from), day_start(date_to + timedelta(days=1))

    vehicles = list(
        (await db.execute(scope.select(Vehicle).order_by(Vehicle.name)))
        .scalars()
        .all()
    )
    costs = {
        v.id: VehicleCost(
            vehicle_id=v.id, vehicle_name=v.name, license_plate=v.license_plate
        )
        for v in vehicles
    }

    fuel_rows = await db.execute(
        sa.select(FuelLog.vehicle_id, sa.func.coalesce(sa.func.sum(FuelLog.total_cost), 0))
        .where(
            FuelLog.organization_id == scope.organization_id,
            FuelLog.filled_at >= start,
            FuelLog.filled_at < end,
        )
        .group_by(FuelLog.vehicle_id)
    )
    for vehicle_id, total in fuel_rows.all():
        if vehicle_id in costs:
            costs[vehicle_id].fuel_cost = float(total)

    work_rows = await db.execute(
        sa.select(
            WorkOrder.vehicle_id, sa.func.coalesce(sa.func.sum(WorkOrder.total_cost), 0)
        )
        .where(
            WorkOrder.organization_id == scope.organization_id,
            WorkOrder.completed_at >= start,
            WorkOrder.completed_at < end,
        )
        .group_by(WorkOrder.vehicle_id)
    )
    for vehicle_id, total in work_rows.all():
        if vehicle_id in costs:
            costs[vehicle_id].maintenance_cost = float(total)

    document_rows = await db.execute(
        sa.select(
            ComplianceDocument.vehicle_id,
            sa.func.coalesce(sa.func.sum(ComplianceDocument.cost), 0),
        )
        .where(
            ComplianceDocument.organization_id == scope.organization_id,
            ComplianceDocument.vehicle_id.is_not(None),
            ComplianceDocument.issued_on >= date_from,
            ComplianceDocument.issued_on <= date_to,
        )
        .group_by(ComplianceDocument.vehicle_id)
    )
    for vehicle_id, total in document_rows.all():
        if vehicle_id in costs:
            costs[vehicle_id].compliance_cost = float(total)

    distance_rows = await db.execute(
        sa.select(Trip.vehicle_id, sa.func.coalesce(sa.func.sum(Trip.distance_km), 0.0))
        .where(
            Trip.organization_id == scope.organization_id,
            Trip.started_at >= start,
            Trip.started_at < end,
        )
        .group_by(Trip.vehicle_id)
    )
    for vehicle_id, total in distance_rows.all():
        if vehicle_id in costs:
            costs[vehicle_id].distance_km = round(float(total), 1)

    # Straight-line depreciation, apportioned to the period (Section 4.15).
    period_days = max(1, (date_to - date_from).days + 1)
    for vehicle in vehicles:
        if vehicle.purchase_value and vehicle.useful_life_years:
            residual = float(vehicle.residual_value or 0)
            annual = (float(vehicle.purchase_value) - residual) / vehicle.useful_life_years
            costs[vehicle.id].depreciation = round(annual / 365.0 * period_days, 2)

    return list(costs.values())


# ---------------------------------------------------------------------------
# Fleet KPIs and trends
# ---------------------------------------------------------------------------

async def fleet_kpis(
    db: AsyncSession, scope: TenantScope, *, date_from: date, date_to: date
) -> FleetKpis:
    start, end = day_start(date_from), day_start(date_to + timedelta(days=1))

    async def scalar(stmt: sa.Select) -> float:
        return float((await db.execute(stmt)).scalar_one() or 0)

    total_vehicles = int(await scalar(
        sa.select(sa.func.count()).select_from(Vehicle).where(
            Vehicle.organization_id == scope.organization_id
        )
    ))
    active_vehicles = int(await scalar(
        sa.select(sa.func.count()).select_from(Vehicle).where(
            Vehicle.organization_id == scope.organization_id,
            Vehicle.status == VehicleStatus.ACTIVE,
        )
    ))
    tracked = int(await scalar(
        sa.select(sa.func.count())
        .select_from(Device)
        .where(
            Device.organization_id == scope.organization_id,
            Device.status == DeviceStatus.ACTIVE,
        )
    ))

    from app.models.driver import Driver

    total_drivers = int(await scalar(
        sa.select(sa.func.count()).select_from(Driver).where(
            Driver.organization_id == scope.organization_id
        )
    ))
    average_score = await scalar(
        sa.select(sa.func.coalesce(sa.func.avg(Driver.safety_score), 100.0)).where(
            Driver.organization_id == scope.organization_id
        )
    )

    trip_stats = (
        await db.execute(
            sa.select(
                sa.func.count(Trip.id),
                sa.func.coalesce(sa.func.sum(Trip.distance_km), 0.0),
                sa.func.coalesce(sa.func.sum(Trip.duration_seconds), 0),
                sa.func.count(sa.distinct(Trip.vehicle_id)),
            ).where(
                Trip.organization_id == scope.organization_id,
                Trip.started_at >= start,
                Trip.started_at < end,
            )
        )
    ).one()
    trips, distance, duration_seconds, vehicles_moved = trip_stats

    fuel_cost = await scalar(
        sa.select(sa.func.coalesce(sa.func.sum(FuelLog.total_cost), 0)).where(
            FuelLog.organization_id == scope.organization_id,
            FuelLog.filled_at >= start,
            FuelLog.filled_at < end,
        )
    )
    co2 = await scalar(
        sa.select(sa.func.coalesce(sa.func.sum(FuelLog.co2_kg), 0.0)).where(
            FuelLog.organization_id == scope.organization_id,
            FuelLog.filled_at >= start,
            FuelLog.filled_at < end,
        )
    )
    maintenance_cost = await scalar(
        sa.select(sa.func.coalesce(sa.func.sum(WorkOrder.total_cost), 0)).where(
            WorkOrder.organization_id == scope.organization_id,
            WorkOrder.completed_at >= start,
            WorkOrder.completed_at < end,
        )
    )
    active_alerts = int(await scalar(
        sa.select(sa.func.count()).select_from(Alert).where(
            Alert.organization_id == scope.organization_id,
            Alert.status == AlertStatus.ACTIVE,
        )
    ))
    violations = int(await scalar(
        sa.select(sa.func.count()).select_from(DriverEvent).where(
            DriverEvent.organization_id == scope.organization_id,
            DriverEvent.occurred_at >= start,
            DriverEvent.occurred_at < end,
        )
    ))

    total_cost = float(fuel_cost) + float(maintenance_cost)
    distance_km = round(float(distance), 1)

    return FleetKpis(
        total_vehicles=total_vehicles,
        active_vehicles=active_vehicles,
        tracked_vehicles=tracked,
        total_drivers=total_drivers,
        trips=int(trips),
        distance_km=distance_km,
        driving_hours=round(float(duration_seconds) / 3600.0, 1),
        utilisation_percent=(
            round(int(vehicles_moved) / active_vehicles * 100.0, 1)
            if active_vehicles
            else 0.0
        ),
        total_cost=round(total_cost, 2),
        cost_per_km=(
            round(total_cost / distance_km, 3)
            if distance_km >= MIN_DISTANCE_FOR_RATE_KM
            else None
        ),
        fuel_cost=round(float(fuel_cost), 2),
        maintenance_cost=round(float(maintenance_cost), 2),
        co2_kg=round(float(co2), 1),
        active_alerts=active_alerts,
        violations=violations,
        average_safety_score=round(float(average_score), 1),
    )


async def monthly_trends(
    db: AsyncSession, scope: TenantScope, *, months: int = 6
) -> list[TrendPoint]:
    """Month-by-month distance, cost, CO2 and violations.

    Bucketed in Python rather than SQL so the same code runs on Postgres and
    on the SQLite used by the test suite.
    """
    now = utcnow()
    start = (now.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1)

    buckets: dict[str, TrendPoint] = {}
    cursor = start
    while cursor <= now:
        key = f"{cursor.year:04d}-{cursor.month:02d}"
        buckets[key] = TrendPoint(period=key)
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)

    def bucket_for(value: datetime | None) -> TrendPoint | None:
        if value is None:
            return None
        return buckets.get(f"{value.year:04d}-{value.month:02d}")

    trips = await db.execute(
        sa.select(Trip.started_at, Trip.distance_km).where(
            Trip.organization_id == scope.organization_id, Trip.started_at >= start
        )
    )
    for started_at, distance in trips.all():
        point = bucket_for(started_at)
        if point:
            point.distance_km += float(distance or 0)

    fuel = await db.execute(
        sa.select(FuelLog.filled_at, FuelLog.total_cost, FuelLog.co2_kg).where(
            FuelLog.organization_id == scope.organization_id, FuelLog.filled_at >= start
        )
    )
    for filled_at, cost, co2 in fuel.all():
        point = bucket_for(filled_at)
        if point:
            point.cost += float(cost or 0)
            point.co2_kg += float(co2 or 0)

    work = await db.execute(
        sa.select(WorkOrder.completed_at, WorkOrder.total_cost).where(
            WorkOrder.organization_id == scope.organization_id,
            WorkOrder.completed_at.is_not(None),
            WorkOrder.completed_at >= start,
        )
    )
    for completed_at, cost in work.all():
        point = bucket_for(completed_at)
        if point:
            point.cost += float(cost or 0)

    events = await db.execute(
        sa.select(DriverEvent.occurred_at).where(
            DriverEvent.organization_id == scope.organization_id,
            DriverEvent.occurred_at >= start,
        )
    )
    for (occurred_at,) in events.all():
        point = bucket_for(occurred_at)
        if point:
            point.violations += 1

    ordered = sorted(buckets.values(), key=lambda p: p.period)
    for point in ordered:
        point.distance_km = round(point.distance_km, 1)
        point.cost = round(point.cost, 2)
        point.co2_kg = round(point.co2_kg, 1)
    return ordered


# ---------------------------------------------------------------------------
# Sustainability (Section 4 item 17)
# ---------------------------------------------------------------------------

async def ev_transition_candidates(
    db: AsyncSession, scope: TenantScope, *, now: datetime | None = None
) -> list[EvCandidate]:
    """Flag non-EV vehicles whose usage pattern fits an EV comfortably.

    Rule-based, not ML (Section 4 item 17). The test is the *worst* day, not
    the average: a van that averages 90 km but hits 400 km once a fortnight
    would strand a driver, and a recommendation that does that once is a
    recommendation nobody trusts again.
    """
    moment = now or utcnow()
    window_start = moment - timedelta(days=90)

    vehicles = [
        v
        for v in (
            await db.execute(
                scope.select(Vehicle).where(
                    Vehicle.vehicle_type != VehicleType.EV,
                    Vehicle.status == VehicleStatus.ACTIVE,
                )
            )
        )
        .scalars()
        .all()
        if v.fuel_type != FuelType.ELECTRIC
    ]
    if not vehicles:
        return []

    trips = await db.execute(
        sa.select(Trip.vehicle_id, Trip.started_at, Trip.distance_km).where(
            Trip.organization_id == scope.organization_id,
            Trip.vehicle_id.in_([v.id for v in vehicles]),
            Trip.started_at >= window_start,
        )
    )

    daily: dict[uuid.UUID, dict[date, float]] = {}
    for vehicle_id, started_at, distance in trips.all():
        day = (started_at.date() if started_at else moment.date())
        daily.setdefault(vehicle_id, {}).setdefault(day, 0.0)
        daily[vehicle_id][day] += float(distance or 0)

    fuel_rows = await db.execute(
        sa.select(FuelLog.vehicle_id, sa.func.coalesce(sa.func.sum(FuelLog.total_cost), 0))
        .where(
            FuelLog.organization_id == scope.organization_id,
            FuelLog.filled_at >= window_start,
        )
        .group_by(FuelLog.vehicle_id)
    )
    fuel_spend = {row[0]: float(row[1]) for row in fuel_rows.all()}

    candidates: list[EvCandidate] = []
    for vehicle in vehicles:
        days = daily.get(vehicle.id, {})
        if len(days) < EV_MIN_HISTORY_DAYS:
            continue

        distances = list(days.values())
        average = sum(distances) / len(distances)
        worst = max(distances)
        usable_range = (vehicle.ev_range_km or ASSUMED_EV_RANGE_KM) * EV_RANGE_SAFETY_FACTOR

        if worst > usable_range:
            continue

        candidates.append(
            EvCandidate(
                vehicle_id=vehicle.id,
                vehicle_name=vehicle.name,
                license_plate=vehicle.license_plate,
                days_observed=len(days),
                average_daily_km=round(average, 1),
                max_daily_km=round(worst, 1),
                assumed_range_km=round(usable_range, 0),
                annual_fuel_cost=round(fuel_spend.get(vehicle.id, 0.0) * 4, 2),
                rationale=(
                    f"Busiest day in {len(days)} days of driving was "
                    f"{worst:.0f} km, comfortably inside a usable "
                    f"{usable_range:.0f} km EV range."
                ),
            )
        )

    candidates.sort(key=lambda c: c.annual_fuel_cost, reverse=True)
    return candidates


async def asset_lifecycle(
    db: AsyncSession, scope: TenantScope, *, now: datetime | None = None
) -> list[AssetSummary]:
    """Straight-line depreciation and replacement flags (Section 4 item 15)."""
    moment = now or utcnow()
    today = moment.date()

    vehicles = list(
        (await db.execute(scope.select(Vehicle).order_by(Vehicle.name))).scalars().all()
    )

    summaries: list[AssetSummary] = []
    for vehicle in vehicles:
        age_years: float | None = None
        annual: float | None = None
        book: float | None = None
        reasons: list[str] = []

        if vehicle.purchase_date:
            age_years = round((today - vehicle.purchase_date).days / 365.25, 2)

        if vehicle.purchase_value and vehicle.useful_life_years:
            residual = float(vehicle.residual_value or 0)
            annual = round(
                (float(vehicle.purchase_value) - residual) / vehicle.useful_life_years, 2
            )
            if age_years is not None:
                book = round(
                    max(residual, float(vehicle.purchase_value) - annual * age_years), 2
                )

        if (
            age_years is not None
            and vehicle.useful_life_years
            and age_years >= vehicle.useful_life_years
        ):
            reasons.append(
                f"Past its {vehicle.useful_life_years}-year useful life "
                f"({age_years:.1f} years old)"
            )
        if book is not None and vehicle.residual_value and book <= float(
            vehicle.residual_value
        ):
            reasons.append("Fully depreciated to residual value")
        if vehicle.odometer_km >= 300_000:
            reasons.append(f"High mileage ({vehicle.odometer_km:,.0f} km)")

        # The flag is stored so other views agree with this one.
        vehicle.replacement_recommended = bool(reasons)

        summaries.append(
            AssetSummary(
                vehicle_id=vehicle.id,
                vehicle_name=vehicle.name,
                purchase_value=(
                    float(vehicle.purchase_value) if vehicle.purchase_value else None
                ),
                age_years=age_years,
                annual_depreciation=annual,
                book_value=book,
                odometer_km=round(vehicle.odometer_km or 0.0, 1),
                replacement_recommended=bool(reasons),
                reasons=reasons,
            )
        )

    await db.flush()
    return summaries
