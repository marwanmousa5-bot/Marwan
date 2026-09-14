"""GPS simulation.

Only the *position* is simulated. Vehicles are driven along genuinely routed
paths over the real OSM street graph, at speeds derived from the real road
class, and every sample is persisted against a Trip. The map, the routing and
the geocoding are all real.
"""
from __future__ import annotations

import asyncio
import contextlib
import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import (ACTIVE_TASK_STATUSES, DriverStatus, TaskStatus,
                            TripStatus, VehicleLifecycle)
from app.db.base import SessionLocal
from app.models import (Driver, Geofence, GeofenceState, Organization, Place, Task,
                        Trip, TripPosition, Vehicle)
from app.routing.engine import StreetGraph, bearing, get_router, haversine
from app.simulation.provider import PositionSample
from app.services import alerts as alert_svc
from app.services import audit, geofencing, maintenance as maint_svc
from app.services import routes as route_svc
from app.services import scoring, tasks as task_svc
from app.core.enums import DriverEventType, Severity
from app.websocket import events as ev
from app.websocket.events import bus

# Behaviour knobs. Every value here shapes only the *simulated* motion.
DWELL_SECONDS = (45, 180)
IDLE_CHANCE = 0.06
HARSH_EVENT_CHANCE = 0.012
OVERSPEED_CHANCE = 0.02
SPEED_JITTER = 0.18


@dataclass
class VehicleSim:
    """Per-vehicle motion state, held in memory between ticks."""
    vehicle_id: uuid.UUID
    org_id: uuid.UUID
    path: list[list[float]] = field(default_factory=list)
    seg: int = 0
    seg_progress_m: float = 0.0
    speed_kph: float = 0.0
    target_kph: float = 30.0
    heading: float = 0.0
    dwell_until: datetime | None = None
    trip_id: uuid.UUID | None = None
    odometer_km: float = 0.0
    destination_name: str = ""
    task_id: uuid.UUID | None = None
    last_sample_at: datetime | None = None
    max_speed_seen: float = 0.0
    idle_seconds: float = 0.0
    parked: bool = False
    overspeed_since: datetime | None = None

    def current_point(self) -> tuple[float, float] | None:
        if not self.path or self.seg >= len(self.path) - 1:
            return (self.path[-1][0], self.path[-1][1]) if self.path else None
        a, b = self.path[self.seg], self.path[self.seg + 1]
        seg_len = haversine(a[0], a[1], b[0], b[1]) or 1e-6
        t = min(1.0, self.seg_progress_m / seg_len)
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    def remaining_m(self) -> float:
        if not self.path:
            return 0.0
        total = 0.0
        for i in range(self.seg, len(self.path) - 1):
            a, b = self.path[i], self.path[i + 1]
            total += haversine(a[0], a[1], b[0], b[1])
        return max(0.0, total - self.seg_progress_m)

    def advance(self, metres: float) -> bool:
        """Walk along the path. Returns True when the destination is reached."""
        while metres > 0 and self.seg < len(self.path) - 1:
            a, b = self.path[self.seg], self.path[self.seg + 1]
            seg_len = haversine(a[0], a[1], b[0], b[1])
            left = seg_len - self.seg_progress_m
            if metres < left:
                self.seg_progress_m += metres
                self.heading = bearing(a[0], a[1], b[0], b[1])
                return False
            metres -= left
            self.seg += 1
            self.seg_progress_m = 0.0
            if self.seg < len(self.path) - 1:
                n = self.path[self.seg + 1]
                self.heading = bearing(self.path[self.seg][0], self.path[self.seg][1],
                                       n[0], n[1])
        return self.seg >= len(self.path) - 1


class SimulationEngine:
    """Drives every tracked vehicle in every active organization."""

    name = "simulation"

    def __init__(self) -> None:
        self.state: dict[uuid.UUID, VehicleSim] = {}
        self._task: asyncio.Task | None = None
        self._running = False
        self.tick_count = 0
        self.graph = StreetGraph.instance()
        self.router = get_router()
        self._destinations: dict[uuid.UUID, list[Place]] = {}

    # --- lifecycle --------------------------------------------------------
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="fleetbeat-simulation")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    @property
    def running(self) -> bool:
        return self._running

    async def _loop(self) -> None:
        # let the API finish booting before the first tick
        await asyncio.sleep(2)
        while self._running:
            started = asyncio.get_event_loop().time()
            try:
                async with SessionLocal() as session:
                    await self.tick(session)
                    await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the loop must survive
                import logging
                logging.getLogger("fleetbeat.sim").exception("simulation tick failed: %s", exc)
            elapsed = asyncio.get_event_loop().time() - started
            await asyncio.sleep(max(0.2, settings.simulation_tick_seconds - elapsed))

    # --- one tick ---------------------------------------------------------
    async def tick(self, session: AsyncSession, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        self.tick_count += 1
        dt = settings.simulation_tick_seconds * settings.simulation_speed_factor

        orgs = (await session.execute(
            select(Organization).where(Organization.status == "active")
        )).scalars().all()

        moved = 0
        for org in orgs:
            vehicles = (await session.execute(
                select(Vehicle).where(
                    Vehicle.organization_id == org.id,
                    Vehicle.lifecycle.in_([VehicleLifecycle.ACTIVE,
                                           VehicleLifecycle.MAINTENANCE]),
                )
            )).scalars().all()
            if not vehicles:
                continue
            fences = (await session.execute(
                select(Geofence).where(Geofence.organization_id == org.id,
                                       Geofence.is_active.is_(True))
            )).scalars().all()
            fence_states: dict = {}
            for row in (await session.execute(
                select(GeofenceState).where(GeofenceState.organization_id == org.id)
            )).scalars().all():
                fence_states[(row.geofence_id, row.vehicle_id)] = row

            cfg = {**org.settings} if org.settings else {}
            for vehicle in vehicles:
                if vehicle.lifecycle == VehicleLifecycle.MAINTENANCE:
                    continue
                if await self._step_vehicle(session, org=org, cfg=cfg, vehicle=vehicle,
                                            dt=dt, now=now, fences=fences,
                                            fence_states=fence_states):
                    moved += 1
        return moved

    async def _destination_pool(self, session: AsyncSession, org_id: uuid.UUID) -> list[Place]:
        if org_id not in self._destinations:
            self._destinations[org_id] = (await session.execute(
                select(Place).where(Place.organization_id == org_id,
                                    Place.is_active.is_(True))
            )).scalars().all()
        return self._destinations[org_id]

    async def _step_vehicle(self, session: AsyncSession, *, org, cfg: dict, vehicle: Vehicle,
                            dt: float, now: datetime, fences, fence_states) -> bool:
        sim = self.state.get(vehicle.id)
        if sim is None:
            sim = await self._init_vehicle(session, org.id, vehicle, now)
            if sim is None:
                return False
            self.state[vehicle.id] = sim

        # parked vehicles stay put until dispatch gives them something to do
        if sim.parked:
            task = await self._pending_task(session, vehicle)
            if task is None:
                return False
            sim.parked = False
            await self._route_to_task(session, org.id, vehicle, sim, task, now)
            if not sim.path:
                sim.parked = True
                return False

        if sim.dwell_until and now < sim.dwell_until:
            sim.speed_kph = 0.0
            sim.idle_seconds += dt
            await self._emit(session, org=org, cfg=cfg, vehicle=vehicle, sim=sim, now=now,
                             fences=fences, fence_states=fence_states, ignition=True)
            if sim.idle_seconds > 15 * 60:
                await self._raise_idle(session, org.id, cfg, vehicle, sim, now)
            return True

        # choose a fresh destination when idle with nothing queued
        if not sim.path or sim.seg >= len(sim.path) - 1:
            task = await self._pending_task(session, vehicle)
            if task is not None:
                await self._route_to_task(session, org.id, vehicle, sim, task, now)
            else:
                await self._route_to_random(session, org.id, vehicle, sim, now)
            if not sim.path:
                sim.parked = True
                return False

        # --- motion ---
        road_limit = self._road_limit(sim)
        sim.target_kph = road_limit * random.uniform(0.75, 1.0)
        if random.random() < OVERSPEED_CHANCE:
            sim.target_kph = road_limit * random.uniform(1.25, 1.5)
        prev_speed = sim.speed_kph
        # smooth approach to the target, with a little jitter
        sim.speed_kph += (sim.target_kph - sim.speed_kph) * 0.35
        sim.speed_kph *= random.uniform(1 - SPEED_JITTER * 0.2, 1 + SPEED_JITTER * 0.2)
        sim.speed_kph = max(0.0, min(sim.speed_kph, road_limit * 1.6))
        if random.random() < IDLE_CHANCE:
            sim.speed_kph = 0.0

        accel = (sim.speed_kph - prev_speed) / 3.6 / max(dt, 1e-6)
        prev_heading = sim.heading
        distance_m = sim.speed_kph / 3.6 * dt
        arrived = sim.advance(distance_m)
        sim.odometer_km += distance_m / 1000.0
        sim.max_speed_seen = max(sim.max_speed_seen, sim.speed_kph)
        if sim.speed_kph < 3:
            sim.idle_seconds += dt
        else:
            sim.idle_seconds = 0.0

        turn = abs((sim.heading - prev_heading + 180) % 360 - 180)
        lateral_g = (sim.speed_kph / 3.6) * math.radians(turn) / max(dt, 1e-6) / 9.81

        await self._emit(session, org=org, cfg=cfg, vehicle=vehicle, sim=sim, now=now,
                         fences=fences, fence_states=fence_states, ignition=True,
                         acceleration=accel, lateral_g=lateral_g)

        await self._detect_events(session, org=org, cfg=cfg, vehicle=vehicle, sim=sim,
                                  now=now, accel=accel, lateral_g=lateral_g,
                                  road_limit=road_limit, dt=dt)

        if arrived:
            await self._on_arrival(session, org.id, cfg, vehicle, sim, now)
        return True

    def _road_limit(self, sim: VehicleSim) -> float:
        pt = sim.current_point()
        if not pt:
            return 30.0
        eid, dist, _ = self.graph.snap_to_edge(pt[0], pt[1])
        if dist > 60:
            return 30.0
        return float(self.graph.edges[eid]["v"])

    # --- routing helpers --------------------------------------------------
    async def _init_vehicle(self, session: AsyncSession, org_id, vehicle: Vehicle,
                            now: datetime) -> VehicleSim | None:
        if vehicle.last_lat is None:
            places = await self._destination_pool(session, org_id)
            if not places:
                return None
            home = random.choice(places)
            vehicle.last_lat, vehicle.last_lon = home.lat, home.lon
        sim = VehicleSim(vehicle_id=vehicle.id, org_id=org_id,
                         odometer_km=vehicle.odometer_km or 0.0)
        sim.path = [[vehicle.last_lon, vehicle.last_lat]]
        sim.parked = vehicle.driver_id is None
        return sim

    async def _pending_task(self, session: AsyncSession, vehicle: Vehicle) -> Task | None:
        return (await session.execute(
            select(Task).where(
                Task.vehicle_id == vehicle.id,
                Task.status.in_([TaskStatus.ACCEPTED, TaskStatus.EN_ROUTE]),
                Task.lat.isnot(None),
            ).order_by(Task.priority.desc(), Task.scheduled_for).limit(1)
        )).scalars().first()

    async def _route_to_task(self, session, org_id, vehicle, sim: VehicleSim,
                             task: Task, now: datetime) -> None:
        pt = sim.current_point() or (vehicle.last_lon, vehicle.last_lat)
        result = self.router.route([pt, (task.lon, task.lat)])
        if not result.ok or len(result.geometry) < 2:
            sim.path = []
            return
        sim.path = result.geometry
        sim.seg = 0
        sim.seg_progress_m = 0.0
        sim.destination_name = task.address or task.title
        sim.task_id = task.id
        if task.status == TaskStatus.ACCEPTED:
            await task_svc.transition(session, org_id=org_id, task=task,
                                      target=TaskStatus.EN_ROUTE, now=now,
                                      actor_name="Driver app",
                                      note="Driver started travelling to the customer.")
        task.eta = now + timedelta(seconds=result.duration_s)
        if task.route_id:
            route = await session.get(__import__("app.models", fromlist=["Route"]).Route,
                                      task.route_id)
            if route:
                route.is_active = True
        await self._ensure_trip(session, org_id, vehicle, sim, now, task_id=task.id)

    async def _route_to_random(self, session, org_id, vehicle, sim: VehicleSim,
                               now: datetime) -> None:
        places = await self._destination_pool(session, org_id)
        if not places:
            sim.path = []
            return
        pt = sim.current_point() or (vehicle.last_lon, vehicle.last_lat)
        for _ in range(4):
            dest = random.choice(places)
            if haversine(pt[0], pt[1], dest.lon, dest.lat) < 250:
                continue
            result = self.router.route([pt, (dest.lon, dest.lat)])
            if result.ok and len(result.geometry) >= 2:
                sim.path = result.geometry
                sim.seg = 0
                sim.seg_progress_m = 0.0
                sim.destination_name = dest.name
                sim.task_id = None
                await self._ensure_trip(session, org_id, vehicle, sim, now)
                return
        sim.path = []

    async def _ensure_trip(self, session: AsyncSession, org_id, vehicle: Vehicle,
                           sim: VehicleSim, now: datetime,
                           task_id: uuid.UUID | None = None) -> None:
        if sim.trip_id is not None:
            return
        from app.geo.basemap import gazetteer
        n = (await session.execute(
            select(Trip).where(Trip.organization_id == org_id)
        )).scalars().all()
        reference = f"TRP-{9000 + len(n) + 1}"
        pt = sim.current_point() or (vehicle.last_lon, vehicle.last_lat)
        trip = Trip(
            organization_id=org_id, reference=reference, vehicle_id=vehicle.id,
            driver_id=vehicle.driver_id, task_id=task_id, status=TripStatus.ACTIVE,
            started_at=now, start_lat=pt[1], start_lon=pt[0],
            start_address=gazetteer().reverse(pt[0], pt[1]),
            start_odometer_km=sim.odometer_km,
        )
        session.add(trip)
        await session.flush()
        sim.trip_id = trip.id
        sim.max_speed_seen = 0.0
        await bus.publish(org_id, ev.TRIP_STARTED,
                          {"id": str(trip.id), "reference": reference,
                           "vehicle_id": str(vehicle.id)})
        await audit.timeline(
            session, organization_id=org_id, entity_type="vehicle", entity_id=vehicle.id,
            action="trip_started", occurred_at=now,
            description=f"Trip {reference} started from {trip.start_address}.",
            related_type="trip", related_id=trip.id,
        )

    async def _close_trip(self, session: AsyncSession, org_id, vehicle: Vehicle,
                          sim: VehicleSim, now: datetime) -> None:
        if sim.trip_id is None:
            return
        from app.geo.basemap import gazetteer
        trip = await session.get(Trip, sim.trip_id)
        if trip is None:
            sim.trip_id = None
            return
        pt = sim.current_point() or (vehicle.last_lon, vehicle.last_lat)
        trip.status = TripStatus.COMPLETED
        trip.ended_at = now
        trip.end_lat, trip.end_lon = pt[1], pt[0]
        trip.end_address = gazetteer().reverse(pt[0], pt[1])
        trip.end_odometer_km = sim.odometer_km
        trip.distance_km = round(max(0.0, sim.odometer_km - (trip.start_odometer_km or 0)), 3)
        trip.duration_s = (now - trip.started_at).total_seconds()
        trip.idle_s = sim.idle_seconds
        trip.max_speed_kph = round(sim.max_speed_seen, 1)
        trip.avg_speed_kph = round(trip.distance_km / (trip.duration_s / 3600), 1) \
            if trip.duration_s > 60 else round(sim.max_speed_seen * 0.6, 1)
        trip.stop_count += 1

        org = await session.get(Organization, org_id)
        cfg = org.settings if org else {}
        if vehicle.is_ev:
            trip.energy_used_kwh = round(trip.distance_km * 0.21, 3)
            trip.co2_kg = round(trip.energy_used_kwh * cfg.get("co2_kg_per_kwh", 0.061), 3)
            if vehicle.battery_capacity_kwh:
                vehicle.state_of_charge_pct = max(
                    5.0, (vehicle.state_of_charge_pct or 100)
                    - trip.energy_used_kwh / vehicle.battery_capacity_kwh * 100)
                vehicle.range_km = round((vehicle.state_of_charge_pct / 100)
                                         * vehicle.battery_capacity_kwh / 0.21, 0)
        else:
            rate = (vehicle.avg_consumption_l_100km or 9.5) / 100
            trip.fuel_used_l = round(trip.distance_km * rate, 3)
            factor = cfg.get("co2_kg_per_litre_petrol", 2.31) if vehicle.fuel_type == "petrol" \
                else cfg.get("co2_kg_per_litre_diesel", 2.68)
            trip.co2_kg = round(trip.fuel_used_l * factor, 3)

        await bus.publish(org_id, ev.TRIP_COMPLETED,
                          {"id": str(trip.id), "reference": trip.reference,
                           "vehicle_id": str(vehicle.id),
                           "distance_km": trip.distance_km})
        sim.trip_id = None

    # --- persistence + fan-out -------------------------------------------
    async def _emit(self, session: AsyncSession, *, org, cfg: dict, vehicle: Vehicle,
                    sim: VehicleSim, now: datetime, fences, fence_states,
                    ignition: bool, acceleration: float = 0.0,
                    lateral_g: float = 0.0) -> None:
        pt = sim.current_point()
        if pt is None:
            return
        lon, lat = pt
        street = self.graph.street_at(lon, lat)

        vehicle.last_lat, vehicle.last_lon = round(lat, 6), round(lon, 6)
        vehicle.last_speed_kph = round(sim.speed_kph, 1)
        vehicle.last_heading = round(sim.heading, 1)
        vehicle.last_position_at = now
        vehicle.last_street = street or None
        vehicle.odometer_km = round(sim.odometer_km, 2)
        vehicle.ignition_on = ignition
        vehicle.gps_satellites = random.randint(8, 14)
        if sim.speed_kph < 3:
            vehicle.idle_since = vehicle.idle_since or now
        else:
            vehicle.idle_since = None

        if sim.trip_id is not None:
            session.add(TripPosition(
                organization_id=org.id, trip_id=sim.trip_id, vehicle_id=vehicle.id,
                recorded_at=now, lat=round(lat, 6), lon=round(lon, 6),
                speed_kph=round(sim.speed_kph, 1), heading=round(sim.heading, 1),
                odometer_km=round(sim.odometer_km, 2),
                satellites=vehicle.gps_satellites, ignition=ignition, street=street or None,
            ))
        sim.last_sample_at = now

        await bus.publish(org.id, ev.VEHICLE_LOCATION_UPDATED, {
            "vehicle_id": str(vehicle.id), "lat": round(lat, 6), "lon": round(lon, 6),
            "speed_kph": round(sim.speed_kph, 1), "heading": round(sim.heading, 1),
            "street": street, "odometer_km": round(sim.odometer_km, 2),
            "recorded_at": now.isoformat(), "trip_id": str(sim.trip_id) if sim.trip_id else None,
            "task_id": str(sim.task_id) if sim.task_id else None,
            "ignition": ignition,
        })

        await geofencing.evaluate(session, org_id=org.id, vehicle=vehicle, lon=lon, lat=lat,
                                  fences=fences, states=fence_states, now=now)

    async def _detect_events(self, session: AsyncSession, *, org, cfg: dict, vehicle: Vehicle,
                             sim: VehicleSim, now: datetime, accel: float,
                             lateral_g: float, road_limit: float, dt: float) -> None:
        driver = await session.get(Driver, vehicle.driver_id) if vehicle.driver_id else None
        if driver is None:
            return
        pt = sim.current_point()
        lon, lat = pt if pt else (None, None)
        street = vehicle.last_street

        async def emit(event_type: str, severity: str, value: float, threshold: float,
                       detail: str, alert_code: str | None = None,
                       duration: float | None = None) -> None:
            alert = None
            if alert_code:
                alert = await alert_svc.raise_alert(
                    session, org_id=org.id, code=alert_code, severity=severity,
                    title=f"{vehicle.name}: {event_type.replace('_', ' ')}",
                    detail=detail, vehicle_id=vehicle.id, driver_id=driver.id,
                    trip_id=sim.trip_id, task_id=sim.task_id, lat=lat, lon=lon,
                    street=street, now=now,
                    evidence={"value": round(value, 2), "threshold": threshold,
                              "street": street, "speed_kph": round(sim.speed_kph, 1),
                              "duration_s": round(duration or 0, 1)},
                )
            event = await scoring.record_event(
                session, org_id=org.id, driver=driver, event_type=event_type,
                occurred_at=now, org_settings=cfg, vehicle_id=vehicle.id,
                trip_id=sim.trip_id, alert_id=alert.id if alert else None,
                lat=lat, lon=lon, street=street, value=round(value, 2),
                threshold=threshold, duration_s=duration, severity=severity, detail=detail,
            )
            if sim.trip_id:
                trip = await session.get(Trip, sim.trip_id)
                if trip:
                    trip.event_count += 1
            await bus.publish(org.id, ev.DRIVER_EVENT_CREATED, {
                "id": str(event.id), "driver_id": str(driver.id),
                "vehicle_id": str(vehicle.id), "type": event_type,
                "severity": severity, "lat": lat, "lon": lon,
            })

        # sustained overspeed against the real posted/derived road limit
        limit = road_limit
        if sim.speed_kph > limit * 1.15:
            sim.overspeed_since = sim.overspeed_since or now
            held = (now - sim.overspeed_since).total_seconds()
            if held >= 20:
                await emit(DriverEventType.OVERSPEED,
                           Severity.HIGH if sim.speed_kph > limit * 1.4 else Severity.MEDIUM,
                           sim.speed_kph, limit,
                           f"{sim.speed_kph:.0f} km/h in a {limit:.0f} km/h zone"
                           + (f" on {street}" if street else "") + ".",
                           alert_code="overspeed", duration=held)
                sim.overspeed_since = None
        else:
            sim.overspeed_since = None

        if accel < -3.5 and random.random() < 0.5:
            await emit(DriverEventType.HARSH_BRAKING, Severity.MEDIUM, abs(accel), 3.5,
                       f"Deceleration of {abs(accel):.1f} m/s²"
                       + (f" on {street}" if street else "") + ".",
                       alert_code="harsh_braking")
        elif accel > 3.2 and random.random() < 0.4:
            await emit(DriverEventType.HARSH_ACCELERATION, Severity.LOW, accel, 3.2,
                       f"Acceleration of {accel:.1f} m/s².",
                       alert_code="harsh_acceleration")
        if lateral_g > 0.45 and sim.speed_kph > 20 and random.random() < 0.5:
            await emit(DriverEventType.HARSH_CORNERING, Severity.LOW, lateral_g, 0.45,
                       f"Lateral force of {lateral_g:.2f} g through a turn.",
                       alert_code="harsh_cornering")

    async def _raise_idle(self, session, org_id, cfg, vehicle, sim, now) -> None:
        await alert_svc.raise_alert(
            session, org_id=org_id, code="excessive_idling", title=f"{vehicle.name} idling",
            detail=f"{vehicle.name} has been idling for {sim.idle_seconds / 60:.0f} minutes"
                   + (f" on {vehicle.last_street}" if vehicle.last_street else "") + ".",
            vehicle_id=vehicle.id, driver_id=vehicle.driver_id,
            lat=vehicle.last_lat, lon=vehicle.last_lon, now=now,
            evidence={"idle_minutes": round(sim.idle_seconds / 60, 1)},
        )
        sim.idle_seconds = 0.0

    async def _on_arrival(self, session: AsyncSession, org_id, cfg: dict, vehicle: Vehicle,
                          sim: VehicleSim, now: datetime) -> None:
        sim.speed_kph = 0.0
        sim.dwell_until = now + timedelta(seconds=random.randint(*DWELL_SECONDS))
        await self._close_trip(session, org_id, vehicle, sim, now)

        if sim.task_id:
            task = await session.get(Task, sim.task_id)
            if task and task.status == TaskStatus.EN_ROUTE:
                await task_svc.transition(session, org_id=org_id, task=task,
                                          target=TaskStatus.ARRIVED, now=now,
                                          actor_name="Driver app",
                                          note=f"Arrived at {task.address or task.title}.")
            sim.task_id = None

        # odometer moved, so maintenance thresholds may have been crossed
        await maint_svc.evaluate_vehicle(session, org_id=org_id, vehicle=vehicle,
                                         org_settings=cfg, now=now)
        await bus.publish(org_id, ev.VEHICLE_STATUS_CHANGED,
                          {"vehicle_id": str(vehicle.id), "status": "stopped"})

    # --- provider interface ----------------------------------------------
    async def poll(self) -> list[PositionSample]:  # pragma: no cover - parity shim
        out = []
        for sim in self.state.values():
            pt = sim.current_point()
            if pt and sim.last_sample_at:
                out.append(PositionSample(
                    vehicle_id=sim.vehicle_id, lon=pt[0], lat=pt[1],
                    speed_kph=sim.speed_kph, heading=sim.heading,
                    recorded_at=sim.last_sample_at, odometer_km=sim.odometer_km,
                ))
        return out


engine = SimulationEngine()
