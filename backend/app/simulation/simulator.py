"""Simulated GPS feed (Section 6).

This is one implementation of ``LocationProvider``. It knows nothing about
the database, HTTP or WebSockets: it advances a per-vehicle state machine and
yields ``PositionUpdate`` / ``TelemetryEvent`` values. That keeps it
deterministic under test, and means replacing it with real telemetry is a
matter of writing a different provider - the runner, trip assembly, geofence
evaluation and fan-out downstream are untouched.

The motion model is randomized waypoint interpolation with acceleration
limits, dwell stops and occasional behavioural events. It does not snap to
real roads: for a live map, a smoothly moving marker with plausible speed and
heading is indistinguishable from road-snapped movement at city zoom, and
road-snapping the *position feed* would duplicate what OSRM already does for
the routes that matter (Section 4f).
"""

from __future__ import annotations

import random
import uuid
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from app.models.enums import DriverEventType
from app.services.geo import bearing_deg, destination_point, haversine_m
from app.simulation.provider import (
    LocationProvider,
    PositionUpdate,
    TelemetryEvent,
)


class Phase(StrEnum):
    DRIVING = "driving"
    DWELLING = "dwelling"


@dataclass(slots=True)
class VehicleProfile:
    """What the engine needs to know about one live vehicle."""

    vehicle_id: uuid.UUID
    organization_id: uuid.UUID
    home_latitude: float
    home_longitude: float
    #: Seeds the RNG so a vehicle's behaviour is reproducible across restarts.
    seed: int = 0
    cruise_speed_kph: float = 55.0
    #: Radius within which this vehicle's waypoints are generated.
    operating_radius_m: float = 9_000.0


@dataclass(slots=True)
class VehicleState:
    profile: VehicleProfile
    latitude: float
    longitude: float
    heading: float = 0.0
    speed_kph: float = 0.0
    phase: Phase = Phase.DRIVING
    target_latitude: float = 0.0
    target_longitude: float = 0.0
    dwell_until: datetime | None = None
    rng: random.Random = field(default_factory=random.Random)
    #: Set for exactly one tick after a stop, so the runner can close a trip.
    just_stopped: bool = False
    just_departed: bool = False


#: Below this, a vehicle counts as stopped rather than crawling.
MOVING_THRESHOLD_KPH = 3.0
#: Metres from the target at which a waypoint counts as reached.
ARRIVAL_RADIUS_M = 60.0
#: Speed change limits per tick, in km/h per second - keeps motion plausible.
MAX_ACCEL_KPH_PER_S = 9.0
MAX_DECEL_KPH_PER_S = 14.0


class SimulatedLocationProvider(LocationProvider):
    """Drives a fleet of simulated vehicles."""

    name = "simulated"

    def __init__(
        self,
        *,
        tick_seconds: float = 3.0,
        event_probability: float = 0.02,
        speeding_threshold_kph: float = 110.0,
        seed: int | None = None,
    ) -> None:
        self.tick_seconds = tick_seconds
        self.event_probability = event_probability
        self.speeding_threshold_kph = speeding_threshold_kph
        self._states: dict[uuid.UUID, VehicleState] = {}
        self._master_rng = random.Random(seed)
        self._running = False

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    @property
    def vehicle_count(self) -> int:
        return len(self._states)

    def tracked_vehicle_ids(self) -> set[uuid.UUID]:
        return set(self._states)

    # -- fleet membership --------------------------------------------------

    def sync_fleet(self, profiles: Iterable[VehicleProfile]) -> None:
        """Reconcile the simulated fleet with the currently live vehicles.

        Called on every refresh so that a device assigned or unassigned in the
        Platform Admin Console takes effect without a restart.
        """
        wanted = {p.vehicle_id: p for p in profiles}

        for vehicle_id in list(self._states):
            if vehicle_id not in wanted:
                del self._states[vehicle_id]

        for vehicle_id, profile in wanted.items():
            if vehicle_id not in self._states:
                self._states[vehicle_id] = self._spawn(profile)
            else:
                self._states[vehicle_id].profile = profile

    def _spawn(self, profile: VehicleProfile) -> VehicleState:
        rng = random.Random(profile.seed or self._master_rng.randrange(1 << 30))
        state = VehicleState(
            profile=profile,
            latitude=profile.home_latitude,
            longitude=profile.home_longitude,
            rng=rng,
            # Stagger departures so a fleet does not move in lockstep.
            phase=Phase.DWELLING,
            dwell_until=datetime.now(UTC)
            + timedelta(seconds=rng.uniform(0, 45)),
        )
        self._pick_target(state)
        return state

    def _pick_target(self, state: VehicleState) -> None:
        """Choose the next waypoint within the vehicle's operating radius."""
        rng = state.rng
        bearing = rng.uniform(0, 360)
        distance = rng.uniform(
            state.profile.operating_radius_m * 0.25,
            state.profile.operating_radius_m,
        )
        lat, lng = destination_point(
            state.profile.home_latitude,
            state.profile.home_longitude,
            bearing,
            distance,
        )
        state.target_latitude = lat
        state.target_longitude = lng

    # -- ticking -----------------------------------------------------------

    def tick(
        self, now: datetime | None = None
    ) -> tuple[list[PositionUpdate], list[TelemetryEvent]]:
        """Advance every vehicle by one interval.

        Returns the positions produced and any behavioural events raised.
        Synchronous and side-effect-free beyond its own state, so tests can
        drive it directly.
        """
        moment = now or datetime.now(UTC)
        positions: list[PositionUpdate] = []
        events: list[TelemetryEvent] = []

        for state in self._states.values():
            event = self._advance(state, moment)
            positions.append(
                PositionUpdate(
                    vehicle_id=state.profile.vehicle_id,
                    organization_id=state.profile.organization_id,
                    latitude=round(state.latitude, 6),
                    longitude=round(state.longitude, 6),
                    speed_kph=round(state.speed_kph, 1),
                    heading=round(state.heading, 1),
                    recorded_at=moment,
                    ignition_on=state.phase == Phase.DRIVING,
                    accuracy_m=round(state.rng.uniform(2.5, 8.0), 1),
                    source=self.name,
                )
            )
            if event is not None:
                events.append(event)

        return positions, events

    def _advance(self, state: VehicleState, now: datetime) -> TelemetryEvent | None:
        state.just_stopped = False
        state.just_departed = False

        if state.phase == Phase.DWELLING:
            if state.dwell_until and now < state.dwell_until:
                state.speed_kph = 0.0
                return None
            # Time to set off again.
            state.phase = Phase.DRIVING
            state.just_departed = True
            state.dwell_until = None
            self._pick_target(state)

        rng = state.rng
        distance_to_target = haversine_m(
            state.latitude, state.longitude, state.target_latitude, state.target_longitude
        )

        if distance_to_target <= ARRIVAL_RADIUS_M:
            # Arrived: stop and dwell for a while before the next leg.
            state.speed_kph = 0.0
            state.phase = Phase.DWELLING
            state.just_stopped = True
            state.dwell_until = now + timedelta(seconds=rng.uniform(45, 300))
            return None

        state.heading = bearing_deg(
            state.latitude, state.longitude, state.target_latitude, state.target_longitude
        )

        event = self._choose_speed(state, distance_to_target, now)

        travelled = state.speed_kph / 3.6 * self.tick_seconds
        if travelled > 0:
            state.latitude, state.longitude = destination_point(
                state.latitude, state.longitude, state.heading, travelled
            )
        return event

    def _choose_speed(
        self, state: VehicleState, distance_to_target: float, now: datetime
    ) -> TelemetryEvent | None:
        """Pick this tick's speed and raise a behavioural event if one fires."""
        rng = state.rng
        target_speed = state.profile.cruise_speed_kph * rng.uniform(0.75, 1.15)

        # Ease off on the approach so arrivals are not abrupt.
        if distance_to_target < 400.0:
            target_speed = min(target_speed, 25.0)

        event_type: DriverEventType | None = None
        if rng.random() < self.event_probability:
            event_type = rng.choice(
                [
                    DriverEventType.HARSH_BRAKING,
                    DriverEventType.HARSH_ACCELERATION,
                    DriverEventType.SPEEDING,
                ]
            )
            if event_type == DriverEventType.HARSH_BRAKING:
                target_speed = max(0.0, state.speed_kph - rng.uniform(35, 55))
            elif event_type == DriverEventType.HARSH_ACCELERATION:
                target_speed = state.speed_kph + rng.uniform(35, 50)
            else:
                target_speed = self.speeding_threshold_kph + rng.uniform(6, 28)

        delta = target_speed - state.speed_kph
        max_up = MAX_ACCEL_KPH_PER_S * self.tick_seconds
        max_down = MAX_DECEL_KPH_PER_S * self.tick_seconds
        # A harsh event is precisely the case where the limiter should not
        # smooth the change away - that abruptness is the signal.
        if event_type is None:
            delta = max(-max_down, min(max_up, delta))

        state.speed_kph = max(0.0, state.speed_kph + delta)

        if event_type is None:
            return None

        magnitude = abs(delta) / (3.6 * self.tick_seconds)  # m/s^2
        return TelemetryEvent(
            vehicle_id=state.profile.vehicle_id,
            organization_id=state.profile.organization_id,
            event_type=event_type,
            occurred_at=now,
            latitude=round(state.latitude, 6),
            longitude=round(state.longitude, 6),
            speed_kph=round(state.speed_kph, 1),
            magnitude=round(
                -magnitude if event_type == DriverEventType.HARSH_BRAKING else magnitude,
                2,
            ),
            details={"simulated": True},
        )

    def is_moving(self, vehicle_id: uuid.UUID) -> bool:
        state = self._states.get(vehicle_id)
        return bool(state and state.speed_kph > MOVING_THRESHOLD_KPH)

    def just_stopped(self, vehicle_id: uuid.UUID) -> bool:
        state = self._states.get(vehicle_id)
        return bool(state and state.just_stopped)

    def just_departed(self, vehicle_id: uuid.UUID) -> bool:
        state = self._states.get(vehicle_id)
        return bool(state and state.just_departed)

    def seed_position(
        self, vehicle_id: uuid.UUID, latitude: float, longitude: float, heading: float
    ) -> None:
        """Resume a vehicle from its last persisted position after a restart."""
        state = self._states.get(vehicle_id)
        if state is None:
            return
        state.latitude = latitude
        state.longitude = longitude
        state.heading = heading

    async def stream(self) -> AsyncIterator[PositionUpdate | TelemetryEvent]:
        """Async view over ``tick`` for callers that prefer a stream."""
        import asyncio

        while self._running:
            positions, events = self.tick()
            for item in (*positions, *events):
                yield item
            await asyncio.sleep(self.tick_seconds)


def build_profiles(
    rows: Sequence[tuple[uuid.UUID, uuid.UUID, float | None, float | None]],
    *,
    default_center: tuple[float, float],
    spread_m: float = 12_000.0,
) -> list[VehicleProfile]:
    """Turn ``(vehicle_id, organization_id, last_lat, last_lng)`` rows into profiles.

    A vehicle with no recorded position is placed near the default operating
    centre, offset deterministically by its own id so a fleet spreads out
    instead of stacking on one pin.
    """
    profiles: list[VehicleProfile] = []
    for vehicle_id, organization_id, last_lat, last_lng in rows:
        seed = vehicle_id.int % (1 << 30)
        if last_lat is not None and last_lng is not None:
            home_lat, home_lng = last_lat, last_lng
        else:
            jitter = random.Random(seed)
            home_lat, home_lng = destination_point(
                default_center[0],
                default_center[1],
                jitter.uniform(0, 360),
                jitter.uniform(0, spread_m),
            )
        profiles.append(
            VehicleProfile(
                vehicle_id=vehicle_id,
                organization_id=organization_id,
                home_latitude=home_lat,
                home_longitude=home_lng,
                seed=seed,
                cruise_speed_kph=random.Random(seed).uniform(42.0, 68.0),
            )
        )
    return profiles
