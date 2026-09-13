"""Anomaly detection (Section 5, item 4).

Statistical thresholds, not a model: a z-score against each vehicle's *own*
history. Comparing a vehicle to itself rather than to the fleet is what makes
this usable on a mixed fleet, where a truck and a van have no business being
held to the same fuel figure.
"""

from __future__ import annotations

import statistics
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fuel import FuelLog
from app.models.tracking import Trip
from app.models.vehicle import Vehicle

#: Standard deviations from a vehicle's own mean before it is flagged.
Z_THRESHOLD = 2.5
#: Fewer samples than this and the mean is not worth trusting.
MIN_SAMPLES = 5
#: How far back the baseline is drawn from.
BASELINE_WINDOW = timedelta(days=120)


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class Anomaly:
    kind: str  # fuel_consumption | idle_time
    vehicle_id: uuid.UUID
    vehicle_name: str
    value: float
    mean: float
    stdev: float
    z_score: float
    subject_id: uuid.UUID | None = None
    observed_at: datetime | None = None

    @property
    def summary(self) -> str:
        direction = "higher" if self.z_score > 0 else "lower"
        return (
            f"{self.value:.1f} is {abs(self.z_score):.1f} standard deviations "
            f"{direction} than this vehicle's usual {self.mean:.1f}"
        )


def z_scores(values: list[float]) -> tuple[float, float]:
    """Mean and population standard deviation, guarding the degenerate case."""
    if len(values) < 2:
        return (values[0] if values else 0.0), 0.0
    return statistics.fmean(values), statistics.pstdev(values)


def find_outliers(
    samples: list[tuple[uuid.UUID, float, datetime]],
    *,
    threshold: float = Z_THRESHOLD,
) -> list[tuple[uuid.UUID, float, float, float, float, datetime]]:
    """Return ``(id, value, mean, stdev, z, at)`` for samples beyond threshold.

    The baseline excludes the sample being judged, so one extreme reading
    cannot pull the mean far enough to hide itself.
    """
    if len(samples) < MIN_SAMPLES:
        return []

    out = []
    for index, (sample_id, value, at) in enumerate(samples):
        others = [v for i, (_, v, _) in enumerate(samples) if i != index]
        mean, stdev = z_scores(others)
        if stdev <= 0:
            continue
        z = (value - mean) / stdev
        if abs(z) >= threshold:
            out.append((sample_id, value, mean, stdev, round(z, 2), at))
    return out


async def detect_fuel_anomalies(
    db: AsyncSession, organization_id: uuid.UUID, *, now: datetime | None = None
) -> list[Anomaly]:
    """Flag fill-ups that are unusual for that vehicle's own history."""
    moment = now or utcnow()
    rows = await db.execute(
        sa.select(FuelLog, Vehicle.name)
        .join(Vehicle, Vehicle.id == FuelLog.vehicle_id)
        .where(
            FuelLog.organization_id == organization_id,
            FuelLog.filled_at >= moment - BASELINE_WINDOW,
        )
        .order_by(FuelLog.vehicle_id, FuelLog.filled_at)
    )

    by_vehicle: dict[uuid.UUID, list[tuple[uuid.UUID, float, datetime]]] = {}
    names: dict[uuid.UUID, str] = {}
    for log, vehicle_name in rows.all():
        names[log.vehicle_id] = vehicle_name
        by_vehicle.setdefault(log.vehicle_id, []).append(
            (log.id, float(log.quantity), log.filled_at)
        )

    anomalies: list[Anomaly] = []
    for vehicle_id, samples in by_vehicle.items():
        for log_id, value, mean, stdev, z, at in find_outliers(samples):
            anomalies.append(
                Anomaly(
                    kind="fuel_consumption",
                    vehicle_id=vehicle_id,
                    vehicle_name=names[vehicle_id],
                    value=round(value, 2),
                    mean=round(mean, 2),
                    stdev=round(stdev, 2),
                    z_score=z,
                    subject_id=log_id,
                    observed_at=at,
                )
            )
    return anomalies


async def detect_idle_anomalies(
    db: AsyncSession, organization_id: uuid.UUID, *, now: datetime | None = None
) -> list[Anomaly]:
    """Flag trips with unusual idle time for that vehicle."""
    moment = now or utcnow()
    rows = await db.execute(
        sa.select(Trip, Vehicle.name)
        .join(Vehicle, Vehicle.id == Trip.vehicle_id)
        .where(
            Trip.organization_id == organization_id,
            Trip.started_at >= moment - BASELINE_WINDOW,
            Trip.duration_seconds > 0,
        )
        .order_by(Trip.vehicle_id, Trip.started_at)
    )

    by_vehicle: dict[uuid.UUID, list[tuple[uuid.UUID, float, datetime]]] = {}
    names: dict[uuid.UUID, str] = {}
    for trip, vehicle_name in rows.all():
        names[trip.vehicle_id] = vehicle_name
        # Idle *share* of the trip, so a long trip is not flagged merely for
        # being long.
        share = (trip.idle_seconds or 0) / max(1, trip.duration_seconds) * 100.0
        by_vehicle.setdefault(trip.vehicle_id, []).append(
            (trip.id, share, trip.started_at)
        )

    anomalies: list[Anomaly] = []
    for vehicle_id, samples in by_vehicle.items():
        for trip_id, value, mean, stdev, z, at in find_outliers(samples):
            if z <= 0:
                continue  # unusually *little* idling is not a problem
            anomalies.append(
                Anomaly(
                    kind="idle_time",
                    vehicle_id=vehicle_id,
                    vehicle_name=names[vehicle_id],
                    value=round(value, 1),
                    mean=round(mean, 1),
                    stdev=round(stdev, 1),
                    z_score=z,
                    subject_id=trip_id,
                    observed_at=at,
                )
            )
    return anomalies
