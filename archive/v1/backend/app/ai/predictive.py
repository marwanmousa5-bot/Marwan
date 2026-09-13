"""Predictive maintenance (Section 5, item 2 - the prediction half).

Rule-based for MVP, as the spec allows: project each vehicle's recent daily
mileage forward and flag the schedules that will fall due inside the horizon.
The interface returns a projection with its inputs, so replacing the rule with
a trained model later means changing this function and nothing downstream.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import MaintenanceIntervalType
from app.models.maintenance import MaintenanceSchedule
from app.models.tracking import Trip
from app.models.vehicle import Vehicle

#: How far ahead to look.
HORIZON_DAYS = 30
#: Recent window used to estimate daily mileage.
USAGE_WINDOW_DAYS = 30


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class MaintenanceForecast:
    vehicle_id: uuid.UUID
    vehicle_name: str
    schedule_id: uuid.UUID
    schedule_name: str
    #: Projected date the service falls due.
    predicted_due_on: date
    days_away: int
    daily_km: float
    remaining_km: float | None
    basis: str

    @property
    def summary(self) -> str:
        if self.remaining_km is not None:
            return (
                f"{self.schedule_name} for {self.vehicle_name} is about "
                f"{self.remaining_km:.0f} km away; at its recent "
                f"{self.daily_km:.0f} km/day that lands around "
                f"{self.predicted_due_on:%-d %b}."
            )
        return (
            f"{self.schedule_name} for {self.vehicle_name} falls due on "
            f"{self.predicted_due_on:%-d %b}."
        )


async def forecast_due_maintenance(
    db: AsyncSession,
    organization_id: uuid.UUID,
    *,
    horizon_days: int = HORIZON_DAYS,
    now: datetime | None = None,
) -> list[MaintenanceForecast]:
    """Project which services will fall due within the horizon."""
    moment = now or utcnow()
    today = moment.date()
    window_start = moment - timedelta(days=USAGE_WINDOW_DAYS)

    usage_rows = await db.execute(
        sa.select(Trip.vehicle_id, sa.func.coalesce(sa.func.sum(Trip.distance_km), 0.0))
        .where(Trip.organization_id == organization_id, Trip.started_at >= window_start)
        .group_by(Trip.vehicle_id)
    )
    daily_km = {
        row[0]: float(row[1]) / USAGE_WINDOW_DAYS for row in usage_rows.all()
    }

    rows = await db.execute(
        sa.select(MaintenanceSchedule, Vehicle)
        .join(Vehicle, Vehicle.id == MaintenanceSchedule.vehicle_id)
        .where(
            MaintenanceSchedule.organization_id == organization_id,
            MaintenanceSchedule.is_active.is_(True),
        )
    )

    forecasts: list[MaintenanceForecast] = []
    for schedule, vehicle in rows.all():
        if (
            schedule.interval_type == MaintenanceIntervalType.MILEAGE
            and schedule.next_due_odometer_km is not None
        ):
            remaining = schedule.next_due_odometer_km - (vehicle.odometer_km or 0.0)
            rate = daily_km.get(vehicle.id, 0.0)
            if rate <= 0.1:
                # A vehicle that is not moving will not reach a mileage
                # service; projecting from a zero rate would be meaningless.
                continue
            days_away = int(max(0, remaining) / rate)
            basis = f"{rate:.0f} km/day over the last {USAGE_WINDOW_DAYS} days"
            predicted = today + timedelta(days=days_away)
        elif schedule.next_due_date is not None:
            predicted = schedule.next_due_date
            days_away = (predicted - today).days
            remaining = None
            rate = daily_km.get(vehicle.id, 0.0)
            basis = "fixed service interval"
        else:
            continue

        if days_away > horizon_days:
            continue

        forecasts.append(
            MaintenanceForecast(
                vehicle_id=vehicle.id,
                vehicle_name=vehicle.name,
                schedule_id=schedule.id,
                schedule_name=schedule.name,
                predicted_due_on=predicted,
                days_away=days_away,
                daily_km=round(rate, 1),
                remaining_km=round(remaining, 1) if remaining is not None else None,
                basis=basis,
            )
        )

    forecasts.sort(key=lambda f: f.days_away)
    return forecasts
