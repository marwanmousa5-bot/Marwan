"""GPS simulation engine and the tracking ingest path (Sections 6, 4b, 4c).

These tests drive the real provider and the real ingest service, so they
prove the property Section 6 is strictest about: every sample is persisted
against a Trip, so a completed trip can be replayed later.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.models.driver import Driver, DriverEvent
from app.models.enums import (
    DeviceStatus,
    DriverEventType,
    GeofenceTrigger,
    TripStatus,
    UserRole,
)
from app.models.tracking import Geofence, GeofenceEvent, PositionSample, Trip
from app.models.vehicle import Vehicle
from app.services import tracking
from app.simulation.provider import PositionUpdate, TelemetryEvent
from app.simulation.simulator import SimulatedLocationProvider, build_profiles
from tests.conftest import auth, login, make_organization, make_user

AMSTERDAM = (52.3676, 4.9041)


# ---------------------------------------------------------------------------
# The provider on its own
# ---------------------------------------------------------------------------

def test_provider_only_tracks_vehicles_it_is_given() -> None:
    provider = SimulatedLocationProvider(seed=1)
    assert provider.vehicle_count == 0

    org_id = uuid.uuid4()
    ids = [uuid.uuid4() for _ in range(3)]
    provider.sync_fleet(
        build_profiles(
            [(vid, org_id, None, None) for vid in ids], default_center=AMSTERDAM
        )
    )
    assert provider.vehicle_count == 3

    # A device unassigned in the Platform Admin Console drops out on the next
    # refresh, without a restart.
    provider.sync_fleet(
        build_profiles([(ids[0], org_id, None, None)], default_center=AMSTERDAM)
    )
    assert provider.tracked_vehicle_ids() == {ids[0]}


def test_provider_produces_plausible_movement() -> None:
    provider = SimulatedLocationProvider(tick_seconds=3.0, event_probability=0.0, seed=42)
    org_id, vehicle_id = uuid.uuid4(), uuid.uuid4()
    provider.sync_fleet(
        build_profiles([(vehicle_id, org_id, *AMSTERDAM)], default_center=AMSTERDAM)
    )

    now = datetime.now(UTC)
    speeds, positions = [], []
    for i in range(120):
        batch, _ = provider.tick(now + timedelta(seconds=3 * i))
        speeds.append(batch[0].speed_kph)
        positions.append((batch[0].latitude, batch[0].longitude))

    assert max(speeds) > 20.0, "the vehicle should actually drive"
    assert len(set(positions)) > 50, "the vehicle should move between samples"
    assert all(0 <= s <= 200 for s in speeds), "speeds must stay plausible"
    assert all(-90 <= lat <= 90 and -180 <= lng <= 180 for lat, lng in positions)


def test_provider_emits_behavioural_events() -> None:
    provider = SimulatedLocationProvider(tick_seconds=3.0, event_probability=0.3, seed=9)
    org_id, vehicle_id = uuid.uuid4(), uuid.uuid4()
    provider.sync_fleet(
        build_profiles([(vehicle_id, org_id, *AMSTERDAM)], default_center=AMSTERDAM)
    )

    now = datetime.now(UTC)
    kinds: set[str] = set()
    for i in range(200):
        _, events = provider.tick(now + timedelta(seconds=3 * i))
        kinds.update(e.event_type for e in events)

    assert DriverEventType.SPEEDING in kinds
    assert {DriverEventType.HARSH_BRAKING, DriverEventType.HARSH_ACCELERATION} & kinds


# ---------------------------------------------------------------------------
# Ingest into the database
# ---------------------------------------------------------------------------

@pytest.fixture
async def tracked_vehicle(db: AsyncSession):
    org = await make_organization(db, "Acme Logistics")
    await make_user(
        db, email="admin@acme.example.com", role=UserRole.ORG_ADMIN, organization=org
    )
    vehicle = Vehicle(
        organization_id=org.id, name="Van 01", license_plate="ACM-001", odometer_km=1000
    )
    db.add(vehicle)
    await db.flush()
    driver = Driver(
        organization_id=org.id, full_name="Dee Driver", assigned_vehicle_id=vehicle.id
    )
    db.add(driver)
    db.add(
        Device(
            serial_number="FB-0001",
            status=DeviceStatus.ACTIVE,
            organization_id=org.id,
            vehicle_id=vehicle.id,
        )
    )
    await db.commit()
    return {"org": org, "vehicle": vehicle, "driver": driver}


def _position(vehicle, org, lat, lng, speed, at) -> PositionUpdate:
    return PositionUpdate(
        vehicle_id=vehicle.id,
        organization_id=org.id,
        latitude=lat,
        longitude=lng,
        speed_kph=speed,
        heading=90.0,
        recorded_at=at,
    )


@pytest.mark.asyncio
async def test_every_sample_is_persisted_against_a_trip(
    db: AsyncSession, tracked_vehicle
) -> None:
    """Section 6: history must be replayable, so nothing may be overwritten."""
    org, vehicle = tracked_vehicle["org"], tracked_vehicle["vehicle"]
    runtimes = await tracking.load_runtimes(db, [vehicle.id])

    now = datetime.now(UTC)
    lat, lng = AMSTERDAM
    for i in range(10):
        await tracking.ingest(
            db,
            positions=[
                _position(
                    vehicle, org, lat + i * 0.001, lng, 50.0, now + timedelta(seconds=3 * i)
                )
            ],
            events=[],
            runtimes=runtimes,
            geofences={},
            speed_limits={org.id: 110.0},
        )
    await db.commit()

    samples = (
        await db.execute(
            sa.select(PositionSample).where(PositionSample.vehicle_id == vehicle.id)
        )
    ).scalars().all()
    assert len(samples) == 10, "each sample is a row, not an overwrite"

    trips = (
        await db.execute(sa.select(Trip).where(Trip.vehicle_id == vehicle.id))
    ).scalars().all()
    assert len(trips) == 1
    assert trips[0].status == TripStatus.IN_PROGRESS
    assert trips[0].distance_km > 0
    assert all(s.trip_id == trips[0].id for s in samples)

    # The denormalised cache tracks the latest fix.
    await db.refresh(vehicle)
    assert vehicle.last_latitude == pytest.approx(lat + 0.009)
    assert vehicle.odometer_km > 1000


@pytest.mark.asyncio
async def test_trip_opens_on_movement_and_closes_after_a_long_stop(
    db: AsyncSession, tracked_vehicle
) -> None:
    org, vehicle = tracked_vehicle["org"], tracked_vehicle["vehicle"]
    runtimes = await tracking.load_runtimes(db, [vehicle.id])
    now = datetime.now(UTC)
    lat, lng = AMSTERDAM

    async def feed(speed: float, at: datetime, offset: float = 0.0):
        return await tracking.ingest(
            db,
            positions=[_position(vehicle, org, lat + offset, lng, speed, at)],
            events=[],
            runtimes=runtimes,
            geofences={},
            speed_limits={org.id: 110.0},
        )

    # Stationary: no trip yet.
    await feed(0.0, now)
    assert (
        await db.execute(sa.select(sa.func.count()).select_from(Trip))
    ).scalar_one() == 0

    opened = await feed(45.0, now + timedelta(seconds=3), 0.001)
    assert opened.trips_opened == 1

    # Stopped, but not yet past the idle timeout.
    await feed(0.0, now + timedelta(minutes=1), 0.002)
    trip = (await db.execute(sa.select(Trip))).scalar_one()
    assert trip.status == TripStatus.IN_PROGRESS

    closed = await feed(0.0, now + timedelta(minutes=8), 0.002)
    assert closed.trips_closed == 1
    await db.refresh(trip)
    assert trip.status == TripStatus.COMPLETED
    assert trip.ended_at is not None
    assert trip.duration_seconds > 0


@pytest.mark.asyncio
async def test_telemetry_events_become_driver_events_and_alerts(
    db: AsyncSession, tracked_vehicle
) -> None:
    org, vehicle = tracked_vehicle["org"], tracked_vehicle["vehicle"]
    runtimes = await tracking.load_runtimes(db, [vehicle.id])
    now = datetime.now(UTC)

    result = await tracking.ingest(
        db,
        positions=[_position(vehicle, org, *AMSTERDAM, 120.0, now)],
        events=[
            TelemetryEvent(
                vehicle_id=vehicle.id,
                organization_id=org.id,
                event_type=DriverEventType.SPEEDING,
                occurred_at=now,
                latitude=AMSTERDAM[0],
                longitude=AMSTERDAM[1],
                speed_kph=138.0,
            )
        ],
        runtimes=runtimes,
        geofences={},
        speed_limits={org.id: 110.0},
    )
    await db.commit()

    assert result.driver_events == 1
    assert result.alerts == 1

    event = (await db.execute(sa.select(DriverEvent))).scalar_one()
    assert event.event_type == DriverEventType.SPEEDING
    # The event is attributed to the driver assigned to that vehicle, which is
    # what the points system and safety score both read (Section 4g).
    assert event.driver_id == tracked_vehicle["driver"].id
    assert event.points_applied is False


@pytest.mark.asyncio
async def test_geofence_crossing_raises_one_event_per_transition(
    db: AsyncSession, tracked_vehicle
) -> None:
    org, vehicle = tracked_vehicle["org"], tracked_vehicle["vehicle"]
    fence = Geofence(
        organization_id=org.id,
        name="Depot",
        shape="circle",
        geometry={"center": [AMSTERDAM[1], AMSTERDAM[0]], "radius_m": 500},
        trigger=GeofenceTrigger.BOTH,
    )
    db.add(fence)
    await db.commit()

    runtimes = await tracking.load_runtimes(db, [vehicle.id])
    geofences = await tracking.load_geofences(db, {org.id})
    now = datetime.now(UTC)

    async def feed(lat, lng, at):
        return await tracking.ingest(
            db,
            positions=[_position(vehicle, org, lat, lng, 30.0, at)],
            events=[],
            runtimes=runtimes,
            geofences=geofences,
            speed_limits={org.id: 110.0},
        )

    # Outside: the first sample only establishes the baseline.
    first = await feed(52.4200, 4.9041, now)
    assert first.geofence_events == 0

    entered = await feed(*AMSTERDAM, now + timedelta(seconds=3))
    assert entered.geofence_events == 1

    # Staying inside must not re-fire.
    stayed = await feed(52.3680, 4.9045, now + timedelta(seconds=6))
    assert stayed.geofence_events == 0

    left = await feed(52.4200, 4.9041, now + timedelta(seconds=9))
    assert left.geofence_events == 1
    await db.commit()

    events = (await db.execute(sa.select(GeofenceEvent))).scalars().all()
    assert [e.direction for e in events] == ["enter", "exit"]

    breaches = (
        await db.execute(
            sa.select(DriverEvent).where(
                DriverEvent.event_type == DriverEventType.GEOFENCE_BREACH
            )
        )
    ).scalars().all()
    assert len(breaches) == 2


@pytest.mark.asyncio
async def test_geofence_scoped_to_other_vehicles_is_ignored(
    db: AsyncSession, tracked_vehicle
) -> None:
    org, vehicle = tracked_vehicle["org"], tracked_vehicle["vehicle"]
    db.add(
        Geofence(
            organization_id=org.id,
            name="Other vehicles only",
            shape="circle",
            geometry={"center": [AMSTERDAM[1], AMSTERDAM[0]], "radius_m": 500},
            trigger=GeofenceTrigger.BOTH,
            vehicle_ids=[str(uuid.uuid4())],
        )
    )
    await db.commit()

    runtimes = await tracking.load_runtimes(db, [vehicle.id])
    geofences = await tracking.load_geofences(db, {org.id})
    now = datetime.now(UTC)

    for lat, lng, offset in ((52.42, 4.9041, 0), (*AMSTERDAM, 3)):
        result = await tracking.ingest(
            db,
            positions=[
                _position(vehicle, org, lat, lng, 30.0, now + timedelta(seconds=offset))
            ],
            events=[],
            runtimes=runtimes,
            geofences=geofences,
            speed_limits={org.id: 110.0},
        )
        assert result.geofence_events == 0


@pytest.mark.asyncio
async def test_ingest_broadcasts_are_scoped_to_one_organization(
    db: AsyncSession, tracked_vehicle
) -> None:
    """A live feed must never leak across tenants."""
    org, vehicle = tracked_vehicle["org"], tracked_vehicle["vehicle"]
    runtimes = await tracking.load_runtimes(db, [vehicle.id])

    result = await tracking.ingest(
        db,
        positions=[_position(vehicle, org, *AMSTERDAM, 40.0, datetime.now(UTC))],
        events=[],
        runtimes=runtimes,
        geofences={},
        speed_limits={org.id: 110.0},
    )
    assert set(result.broadcasts) == {org.id}


# ---------------------------------------------------------------------------
# The live API on top
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_snapshot_classifies_vehicles(
    client: AsyncClient, db: AsyncSession, tracked_vehicle
) -> None:
    org, vehicle = tracked_vehicle["org"], tracked_vehicle["vehicle"]
    # A second vehicle with no device must show as "Not Tracked".
    db.add(Vehicle(organization_id=org.id, name="Van 02", license_plate="ACM-002"))
    await db.commit()

    runtimes = await tracking.load_runtimes(db, [vehicle.id])
    await tracking.ingest(
        db,
        positions=[_position(vehicle, org, *AMSTERDAM, 52.0, datetime.now(UTC))],
        events=[],
        runtimes=runtimes,
        geofences={},
        speed_limits={org.id: 110.0},
    )
    await db.commit()

    token = await login(client, "admin@acme.example.com")
    response = await client.get("/api/v1/live/snapshot", headers=auth(token))
    assert response.status_code == 200, response.text
    body = response.json()

    by_name = {v["name"]: v for v in body["vehicles"]}
    assert by_name["Van 01"]["live_status"] == "moving"
    assert by_name["Van 01"]["driver_name"] == "Dee Driver"
    assert by_name["Van 01"]["device_serial"] == "FB-0001"
    assert by_name["Van 02"]["live_status"] == "not_tracked"

    assert body["kpis"]["total_vehicles"] == 2
    assert body["kpis"]["active_now"] == 1
    assert body["kpis"]["not_tracked"] == 1


@pytest.mark.asyncio
async def test_trip_playback_returns_the_full_route(
    client: AsyncClient, db: AsyncSession, tracked_vehicle
) -> None:
    """Section 4c replays a recorded trip from its persisted samples."""
    org, vehicle = tracked_vehicle["org"], tracked_vehicle["vehicle"]
    runtimes = await tracking.load_runtimes(db, [vehicle.id])
    now = datetime.now(UTC)
    lat, lng = AMSTERDAM

    for i in range(8):
        await tracking.ingest(
            db,
            positions=[
                _position(
                    vehicle, org, lat + i * 0.002, lng, 48.0, now + timedelta(seconds=3 * i)
                )
            ],
            events=(
                [
                    TelemetryEvent(
                        vehicle_id=vehicle.id,
                        organization_id=org.id,
                        event_type=DriverEventType.HARSH_BRAKING,
                        occurred_at=now + timedelta(seconds=3 * i),
                        latitude=lat + i * 0.002,
                        longitude=lng,
                        speed_kph=30.0,
                        magnitude=-4.2,
                    )
                ]
                if i == 4
                else []
            ),
            runtimes=runtimes,
            geofences={},
            speed_limits={org.id: 110.0},
        )
    await db.commit()

    token = await login(client, "admin@acme.example.com")
    trips = await client.get("/api/v1/trips", headers=auth(token))
    assert trips.json()["total"] == 1
    trip_id = trips.json()["items"][0]["id"]

    playback = await client.get(
        f"/api/v1/trips/{trip_id}/playback", headers=auth(token)
    )
    assert playback.status_code == 200
    body = playback.json()
    assert body["vehicle_name"] == "Van 01"
    assert len(body["points"]) == 8
    assert body["points"][0]["at"] < body["points"][-1]["at"]
    # Event markers are what the playback scrubber jumps between.
    assert len(body["events"]) == 1
    assert body["events"][0]["event_type"] == "harsh_braking"


@pytest.mark.asyncio
async def test_trip_playback_is_tenant_scoped(
    client: AsyncClient, db: AsyncSession, tracked_vehicle
) -> None:
    org, vehicle = tracked_vehicle["org"], tracked_vehicle["vehicle"]
    runtimes = await tracking.load_runtimes(db, [vehicle.id])
    await tracking.ingest(
        db,
        positions=[_position(vehicle, org, *AMSTERDAM, 40.0, datetime.now(UTC))],
        events=[],
        runtimes=runtimes,
        geofences={},
        speed_limits={org.id: 110.0},
    )
    trip = (await db.execute(sa.select(Trip))).scalar_one()

    rival = await make_organization(db, "Rival Freight")
    await make_user(
        db, email="rex@rival.example.com", role=UserRole.ORG_ADMIN, organization=rival
    )
    await db.commit()

    token = await login(client, "rex@rival.example.com")
    response = await client.get(
        f"/api/v1/trips/{trip.id}/playback", headers=auth(token)
    )
    assert response.status_code == 404


def test_the_feed_can_be_replayed_from_a_point_in_the_past() -> None:
    """Backfilling demo history must actually produce movement.

    Regression: a newly spawned vehicle staggered its first departure against
    the wall clock, so a replay driven from an hour ago sat inside that dwell
    window on every tick and the whole fleet stayed parked - silently, since
    the provider still emitted a position for each stationary vehicle.
    """
    provider = SimulatedLocationProvider(tick_seconds=5.0, event_probability=0.0, seed=7)
    org_id, vehicle_id = uuid.uuid4(), uuid.uuid4()

    start = datetime.now(UTC) - timedelta(minutes=45)
    provider.sync_fleet(
        build_profiles([(vehicle_id, org_id, *AMSTERDAM)], default_center=AMSTERDAM),
        now=start,
    )

    speeds = []
    for step in range(200):
        batch, _ = provider.tick(start + timedelta(seconds=5 * step))
        speeds.append(batch[0].speed_kph)

    assert max(speeds) > 20.0, "a replayed fleet must drive, not sit parked"


def test_a_live_fleet_still_staggers_against_the_wall_clock() -> None:
    """The default has to keep working: no `now` means real time."""
    provider = SimulatedLocationProvider(tick_seconds=5.0, event_probability=0.0, seed=7)
    org_id, vehicle_id = uuid.uuid4(), uuid.uuid4()
    provider.sync_fleet(
        build_profiles([(vehicle_id, org_id, *AMSTERDAM)], default_center=AMSTERDAM)
    )

    now = datetime.now(UTC)
    speeds = [
        provider.tick(now + timedelta(seconds=5 * step))[0][0].speed_kph
        for step in range(200)
    ]
    assert max(speeds) > 20.0
