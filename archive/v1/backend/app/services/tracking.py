"""Ingesting a position feed: trips, history, geofences and live status.

This module is the seam between *any* ``LocationProvider`` and the database.
It is written against ``PositionUpdate`` / ``TelemetryEvent``, so it does not
know or care whether the feed is simulated or real hardware (Section 6).

Section 6 is explicit that every sample is persisted and tied to a Trip -
Trip History Playback (Section 4c) reconstructs a route from those rows, so
overwriting a single "current position" field would make the feature
impossible. ``Vehicle.last_*`` is only a cache for fast map bootstrapping.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.driver import Driver, DriverEvent
from app.models.enums import (
    AlertRuleType,
    AlertSeverity,
    AlertStatus,
    DriverEventType,
    GeofenceTrigger,
    TripStatus,
)
from app.models.tracking import Geofence, GeofenceEvent, PositionSample, Trip
from app.models.vehicle import Vehicle
from app.services import alerts as alert_service
from app.services import geo
from app.simulation.provider import PositionUpdate, TelemetryEvent

#: A vehicle below this speed is stopped, not crawling.
MOVING_THRESHOLD_KPH = 3.0
#: Stopped for longer than this and the current trip is closed.
TRIP_IDLE_TIMEOUT = timedelta(minutes=5)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; normalise before arithmetic."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass(slots=True)
class VehicleRuntime:
    """Per-vehicle bookkeeping the ingest loop carries between ticks."""

    vehicle_id: uuid.UUID
    organization_id: uuid.UUID
    driver_id: uuid.UUID | None = None
    trip_id: uuid.UUID | None = None
    last_latitude: float | None = None
    last_longitude: float | None = None
    last_seen_at: datetime | None = None
    stopped_since: datetime | None = None
    #: geofence_id -> whether the vehicle was inside on the previous sample.
    inside_geofences: dict[uuid.UUID, bool] = field(default_factory=dict)


@dataclass(slots=True)
class IngestResult:
    samples_written: int = 0
    trips_opened: int = 0
    trips_closed: int = 0
    driver_events: int = 0
    geofence_events: int = 0
    alerts: int = 0
    #: Per-organization payloads to fan out over WebSocket.
    broadcasts: dict[uuid.UUID, list[dict]] = field(default_factory=dict)

    def add_broadcast(self, organization_id: uuid.UUID, message: dict) -> None:
        self.broadcasts.setdefault(organization_id, []).append(message)


async def load_runtimes(
    db: AsyncSession, vehicle_ids: list[uuid.UUID]
) -> dict[uuid.UUID, VehicleRuntime]:
    """Rebuild per-vehicle state after a restart, including any open trip."""
    if not vehicle_ids:
        return {}

    runtimes: dict[uuid.UUID, VehicleRuntime] = {}
    vehicles = await db.execute(sa.select(Vehicle).where(Vehicle.id.in_(vehicle_ids)))
    for vehicle in vehicles.scalars().all():
        runtimes[vehicle.id] = VehicleRuntime(
            vehicle_id=vehicle.id,
            organization_id=vehicle.organization_id,
            driver_id=vehicle.primary_driver_id,
            last_latitude=vehicle.last_latitude,
            last_longitude=vehicle.last_longitude,
            last_seen_at=_aware(vehicle.last_position_at),
            stopped_since=_aware(vehicle.stopped_since),
        )

    open_trips = await db.execute(
        sa.select(Trip).where(
            Trip.vehicle_id.in_(vehicle_ids), Trip.status == TripStatus.IN_PROGRESS
        )
    )
    for trip in open_trips.scalars().all():
        runtime = runtimes.get(trip.vehicle_id)
        if runtime is not None:
            runtime.trip_id = trip.id

    # A driver assigned to the vehicle takes precedence over the vehicle's
    # own primary_driver_id, since that is the day-to-day assignment.
    assigned = await db.execute(
        sa.select(Driver.id, Driver.assigned_vehicle_id).where(
            Driver.assigned_vehicle_id.in_(vehicle_ids)
        )
    )
    for driver_id, vehicle_id in assigned.all():
        runtime = runtimes.get(vehicle_id)
        if runtime is not None:
            runtime.driver_id = driver_id

    return runtimes


async def load_geofences(
    db: AsyncSession, organization_ids: set[uuid.UUID]
) -> dict[uuid.UUID, list[Geofence]]:
    if not organization_ids:
        return {}
    result = await db.execute(
        sa.select(Geofence).where(
            Geofence.organization_id.in_(organization_ids),
            Geofence.is_active.is_(True),
        )
    )
    by_org: dict[uuid.UUID, list[Geofence]] = {}
    for fence in result.scalars().all():
        by_org.setdefault(fence.organization_id, []).append(fence)
    return by_org


async def ingest(
    db: AsyncSession,
    *,
    positions: list[PositionUpdate],
    events: list[TelemetryEvent],
    runtimes: dict[uuid.UUID, VehicleRuntime],
    geofences: dict[uuid.UUID, list[Geofence]],
    speed_limits: dict[uuid.UUID, float],
) -> IngestResult:
    """Persist one batch of feed output and derive everything downstream."""
    result = IngestResult()
    vehicles = await _load_vehicles(db, [p.vehicle_id for p in positions])

    for position in positions:
        runtime = runtimes.get(position.vehicle_id)
        vehicle = vehicles.get(position.vehicle_id)
        if runtime is None or vehicle is None:
            continue
        await _ingest_position(
            db,
            position=position,
            runtime=runtime,
            vehicle=vehicle,
            geofences=geofences.get(position.organization_id, []),
            result=result,
        )

    for event in events:
        runtime = runtimes.get(event.vehicle_id)
        if runtime is None:
            continue
        await _ingest_event(
            db,
            event=event,
            runtime=runtime,
            speed_limit=speed_limits.get(event.organization_id, 110.0),
            result=result,
        )

    await db.flush()
    return result


async def _load_vehicles(
    db: AsyncSession, vehicle_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Vehicle]:
    if not vehicle_ids:
        return {}
    result = await db.execute(sa.select(Vehicle).where(Vehicle.id.in_(vehicle_ids)))
    return {v.id: v for v in result.scalars().all()}


async def _ingest_position(
    db: AsyncSession,
    *,
    position: PositionUpdate,
    runtime: VehicleRuntime,
    vehicle: Vehicle,
    geofences: list[Geofence],
    result: IngestResult,
) -> None:
    moving = position.speed_kph > MOVING_THRESHOLD_KPH
    now = position.recorded_at

    # --- trip lifecycle -----------------------------------------------
    if moving and runtime.trip_id is None:
        trip = Trip(
            organization_id=position.organization_id,
            vehicle_id=position.vehicle_id,
            driver_id=runtime.driver_id,
            status=TripStatus.IN_PROGRESS,
            started_at=now,
            start_latitude=position.latitude,
            start_longitude=position.longitude,
            start_odometer_km=vehicle.odometer_km,
        )
        db.add(trip)
        await db.flush()
        runtime.trip_id = trip.id
        result.trips_opened += 1
        result.add_broadcast(
            position.organization_id,
            {
                "type": "trip.started",
                "vehicle_id": str(position.vehicle_id),
                "trip_id": str(trip.id),
                "at": now.isoformat(),
            },
        )

    if moving:
        runtime.stopped_since = None
    elif runtime.stopped_since is None:
        runtime.stopped_since = now

    # --- distance since the previous sample ---------------------------
    step_km = 0.0
    if runtime.last_latitude is not None and runtime.last_longitude is not None:
        step_km = geo.haversine_km(
            runtime.last_latitude,
            runtime.last_longitude,
            position.latitude,
            position.longitude,
        )

    # --- persist the sample (never overwritten - Section 6) ------------
    if runtime.trip_id is not None:
        db.add(
            PositionSample(
                organization_id=position.organization_id,
                trip_id=runtime.trip_id,
                vehicle_id=position.vehicle_id,
                latitude=position.latitude,
                longitude=position.longitude,
                speed_kph=position.speed_kph,
                heading=position.heading,
                altitude_m=position.altitude_m,
                accuracy_m=position.accuracy_m,
                ignition_on=position.ignition_on,
                recorded_at=now,
                source=position.source,
            )
        )
        result.samples_written += 1
        await _update_trip(
            db,
            trip_id=runtime.trip_id,
            step_km=step_km,
            speed_kph=position.speed_kph,
            moving=moving,
            now=now,
            latitude=position.latitude,
            longitude=position.longitude,
        )

    # --- refresh the denormalised cache on the vehicle -----------------
    vehicle.last_latitude = position.latitude
    vehicle.last_longitude = position.longitude
    vehicle.last_heading = position.heading
    vehicle.last_speed_kph = position.speed_kph
    vehicle.last_position_at = now
    vehicle.stopped_since = runtime.stopped_since
    if step_km > 0:
        vehicle.odometer_km = (vehicle.odometer_km or 0.0) + step_km

    # --- close a trip once the vehicle has been stopped long enough ----
    if (
        runtime.trip_id is not None
        and not moving
        and runtime.stopped_since is not None
        and now - runtime.stopped_since >= TRIP_IDLE_TIMEOUT
    ):
        await close_trip(
            db,
            trip_id=runtime.trip_id,
            ended_at=now,
            latitude=position.latitude,
            longitude=position.longitude,
            odometer_km=vehicle.odometer_km,
        )
        result.trips_closed += 1
        result.add_broadcast(
            position.organization_id,
            {
                "type": "trip.ended",
                "vehicle_id": str(position.vehicle_id),
                "trip_id": str(runtime.trip_id),
                "at": now.isoformat(),
            },
        )
        runtime.trip_id = None

    # --- geofences -----------------------------------------------------
    await _evaluate_geofences(
        db, position=position, runtime=runtime, geofences=geofences, result=result
    )

    runtime.last_latitude = position.latitude
    runtime.last_longitude = position.longitude
    runtime.last_seen_at = now

    result.add_broadcast(
        position.organization_id,
        {
            "type": "position",
            "vehicle_id": str(position.vehicle_id),
            "lat": position.latitude,
            "lng": position.longitude,
            "speed_kph": position.speed_kph,
            "heading": position.heading,
            "moving": moving,
            "trip_id": str(runtime.trip_id) if runtime.trip_id else None,
            "at": now.isoformat(),
        },
    )


async def _update_trip(
    db: AsyncSession,
    *,
    trip_id: uuid.UUID,
    step_km: float,
    speed_kph: float,
    moving: bool,
    now: datetime,
    latitude: float,
    longitude: float,
) -> None:
    trip = await db.get(Trip, trip_id)
    if trip is None:
        return

    trip.distance_km = (trip.distance_km or 0.0) + step_km
    trip.max_speed_kph = max(trip.max_speed_kph or 0.0, speed_kph)
    started = _aware(trip.started_at)
    if started:
        trip.duration_seconds = max(0, int((now - started).total_seconds()))
    if trip.duration_seconds:
        trip.average_speed_kph = trip.distance_km / (trip.duration_seconds / 3600.0)
    if not moving:
        trip.idle_seconds = (trip.idle_seconds or 0) + 1
    trip.end_latitude = latitude
    trip.end_longitude = longitude


async def close_trip(
    db: AsyncSession,
    *,
    trip_id: uuid.UUID,
    ended_at: datetime,
    latitude: float | None = None,
    longitude: float | None = None,
    odometer_km: float | None = None,
) -> Trip | None:
    trip = await db.get(Trip, trip_id)
    if trip is None or trip.status != TripStatus.IN_PROGRESS:
        return trip

    trip.status = TripStatus.COMPLETED
    trip.ended_at = ended_at
    if latitude is not None:
        trip.end_latitude = latitude
    if longitude is not None:
        trip.end_longitude = longitude
    if odometer_km is not None:
        trip.end_odometer_km = odometer_km

    started = _aware(trip.started_at)
    if started:
        trip.duration_seconds = max(0, int((ended_at - started).total_seconds()))
    if trip.duration_seconds:
        trip.average_speed_kph = trip.distance_km / (trip.duration_seconds / 3600.0)
    return trip


async def _evaluate_geofences(
    db: AsyncSession,
    *,
    position: PositionUpdate,
    runtime: VehicleRuntime,
    geofences: list[Geofence],
    result: IngestResult,
) -> None:
    for fence in geofences:
        # An empty vehicle list means the fence applies to the whole fleet.
        scoped_to = fence.vehicle_ids or []
        if scoped_to and str(position.vehicle_id) not in {str(v) for v in scoped_to}:
            continue

        inside_now = geo.contains(fence.geometry, position.latitude, position.longitude)
        was_inside = runtime.inside_geofences.get(fence.id)
        runtime.inside_geofences[fence.id] = inside_now

        # First sample only establishes the baseline - it is not a crossing.
        if was_inside is None or was_inside == inside_now:
            continue

        direction = "enter" if inside_now else "exit"
        wants = (
            fence.trigger == GeofenceTrigger.BOTH
            or (fence.trigger == GeofenceTrigger.ON_ENTER and inside_now)
            or (fence.trigger == GeofenceTrigger.ON_EXIT and not inside_now)
        )
        if not wants:
            continue

        db.add(
            GeofenceEvent(
                organization_id=position.organization_id,
                geofence_id=fence.id,
                vehicle_id=position.vehicle_id,
                driver_id=runtime.driver_id,
                direction=direction,
                latitude=position.latitude,
                longitude=position.longitude,
                occurred_at=position.recorded_at,
            )
        )
        result.geofence_events += 1

        # Feeds both the safety score and the points system (Section 4g).
        db.add(
            DriverEvent(
                organization_id=position.organization_id,
                driver_id=runtime.driver_id,
                vehicle_id=position.vehicle_id,
                trip_id=runtime.trip_id,
                event_type=DriverEventType.GEOFENCE_BREACH,
                severity=AlertSeverity.WARNING,
                occurred_at=position.recorded_at,
                latitude=position.latitude,
                longitude=position.longitude,
                speed_kph=position.speed_kph,
                details={"geofence": fence.name, "direction": direction},
            )
        )
        result.driver_events += 1

        alert = await alert_service.raise_alert(
            db,
            organization_id=position.organization_id,
            rule_type=AlertRuleType.GEOFENCE_BREACH,
            title=f"Geofence {direction}: {fence.name}",
            message=f"A vehicle {'entered' if inside_now else 'left'} '{fence.name}'.",
            vehicle_id=position.vehicle_id,
            driver_id=runtime.driver_id,
            subject_type="geofence",
            subject_id=fence.id,
            dedupe_key=(
                f"geofence:{fence.id}:{position.vehicle_id}:{direction}:"
                f"{position.recorded_at:%Y%m%d%H%M}"
            ),
            context={"direction": direction, "geofence": fence.name},
        )
        if alert is not None:
            result.alerts += 1
            result.add_broadcast(
                position.organization_id, _alert_message(alert)
            )


async def _ingest_event(
    db: AsyncSession,
    *,
    event: TelemetryEvent,
    runtime: VehicleRuntime,
    speed_limit: float,
    result: IngestResult,
) -> None:
    severity = (
        AlertSeverity.CRITICAL
        if event.event_type == DriverEventType.SPEEDING
        and (event.speed_kph or 0) > speed_limit + 20
        else AlertSeverity.WARNING
    )

    db.add(
        DriverEvent(
            organization_id=event.organization_id,
            driver_id=runtime.driver_id,
            vehicle_id=event.vehicle_id,
            trip_id=runtime.trip_id,
            event_type=event.event_type,
            severity=severity,
            occurred_at=event.occurred_at,
            latitude=event.latitude,
            longitude=event.longitude,
            speed_kph=event.speed_kph,
            magnitude=event.magnitude,
            details=event.details or None,
        )
    )
    result.driver_events += 1

    rule_type = (
        AlertRuleType.SPEEDING
        if event.event_type == DriverEventType.SPEEDING
        else AlertRuleType.HARSH_DRIVING
    )
    label = event.event_type.value.replace("_", " ")
    alert = await alert_service.raise_alert(
        db,
        organization_id=event.organization_id,
        rule_type=rule_type,
        severity=severity,
        title=f"{label.title()} detected",
        message=(
            f"{label.title()} at {event.speed_kph:.0f} km/h."
            if event.speed_kph is not None
            else f"{label.title()} detected."
        ),
        vehicle_id=event.vehicle_id,
        driver_id=runtime.driver_id,
        subject_type="driver_event",
        # One alert per vehicle per event type per minute: a burst of harsh
        # braking in traffic is one situation, not fifteen.
        dedupe_key=(
            f"{event.event_type}:{event.vehicle_id}:{event.occurred_at:%Y%m%d%H%M}"
        ),
        context={"speed_kph": event.speed_kph, "magnitude": event.magnitude},
    )
    if alert is not None:
        result.alerts += 1
        result.add_broadcast(event.organization_id, _alert_message(alert))


def _alert_message(alert: Alert) -> dict:
    return {
        "type": "alert",
        "id": str(alert.id),
        "rule_type": alert.rule_type,
        "severity": alert.severity,
        "title": alert.title,
        "message": alert.message,
        "vehicle_id": str(alert.vehicle_id) if alert.vehicle_id else None,
        "status": AlertStatus.ACTIVE.value,
        "at": (alert.created_at or utcnow()).isoformat()
        if isinstance(alert.created_at, datetime)
        else utcnow().isoformat(),
    }
