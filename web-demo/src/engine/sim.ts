// GPS simulation.
//
// Only the *position* is simulated. Vehicles are driven along genuinely routed
// paths over the real OSM street graph, at speeds taken from the real road
// class, and every sample is persisted against a Trip. Movement is interpolated
// so vehicles never teleport between points.

import { escalateDue, raiseAlert, wakeSnoozed } from './alerts';
import { evaluateMaintenance, recordDriverEvent, refreshSlas, transitionTask } from './actions';
import { angleDelta, advanceAlong, haversine, pointAt, pointInPolygon } from './geo';
import type { Store } from './store';
import type { Geofence, Task, Trip, Vehicle } from './types';

const MIN = 60000;

interface SimState {
  path: [number, number][];
  seg: number;
  progressM: number;
  speedKph: number;
  heading: number;
  dwellUntil?: number;
  tripId?: string;
  taskId?: string;
  destination: string;
  idleSeconds: number;
  overspeedSince?: number;
  parked: boolean;
  maxSpeedSeen: number;
  lastSampleAt: number;
  positions: number;
  /** Last time each behaviour event was reported, per kind, in simulated ms. */
  lastEventAt: Record<string, number>;
}

/**
 * A real telematics unit reports one event per manoeuvre. The detector below runs
 * on every tick, so without this refractory window a single hard stop would log a
 * dozen harsh-braking events and destroy the driver's score.
 */
const EVENT_REFRACTORY_S = 90;

const DWELL_MIN_S = 40;
const DWELL_MAX_S = 150;
const IDLE_CHANCE = 0.05;
const OVERSPEED_CHANCE = 0.022;

export class Simulation {
  private sims = new Map<string, SimState>();
  private acc = 0;

  constructor(private store: Store) {}

  get tracked(): number { return this.sims.size; }

  /** Advance the world by `deltaMs` of wall time, scaled by the sim speed. */
  tick(deltaMs: number) {
    const s = this.store.state;
    if (!s.simRunning) return;
    const dt = (deltaMs / 1000) * s.simSpeed;   // simulated seconds this tick
    s.now += dt * 1000;
    s.ticks += 1;

    s.vehicles.forEach((v) => this.stepVehicle(v, dt));

    // periodic housekeeping, roughly once a simulated minute
    this.acc += dt;
    if (this.acc >= 45) {
      this.acc = 0;
      refreshSlas(this.store);
      escalateDue(this.store);
      wakeSnoozed(this.store);
      this.accrueDuty(dt);
    }
    s.connection = 'live';
    this.store.emit();
  }

  private accrueDuty(_dt: number) {
    const s = this.store.state;
    s.drivers.forEach((d) => {
      const v = s.vehicles.find((x) => x.driverId === d.id);
      if (v && v.ignitionOn) {
        d.dutyHoursToday = Math.min(14, d.dutyHoursToday + 45 / 3600);
        if (d.dutyHoursToday > 9) {
          raiseAlert(this.store, {
            code: 'fatigue_risk', severity: 'high',
            title: `${d.fullName} has exceeded the safe duty window`,
            detail: `${d.dutyHoursToday.toFixed(1)} hours driven today. A rest break is required.`,
            driverId: d.id, vehicleId: v.id, dedupeExtra: `fatigue:${d.id}`,
            evidence: { duty_hours: Math.round(d.dutyHoursToday * 10) / 10 },
          });
        }
      }
    });
  }

  private simFor(v: Vehicle): SimState {
    let sim = this.sims.get(v.id);
    if (!sim) {
      sim = {
        path: v.lon != null ? [[v.lon, v.lat!]] : [],
        seg: 0, progressM: 0, speedKph: 0, heading: v.heading,
        destination: '', idleSeconds: 0, parked: !v.driverId,
        maxSpeedSeen: 0, lastSampleAt: this.store.state.now, positions: 0,
        lastEventAt: {},
      };
      this.sims.set(v.id, sim);
    }
    return sim;
  }

  private stepVehicle(v: Vehicle, dt: number) {
    const s = this.store.state;
    if (v.lifecycle !== 'active') return;
    if (v.lon == null) return;
    const sim = this.simFor(v);

    // Parked: wait until dispatch gives this vehicle work.
    if (sim.parked) {
      const task = this.pendingTask(v);
      if (!task) return;
      sim.parked = false;
      this.routeToTask(v, sim, task);
      if (!sim.path.length) { sim.parked = true; return; }
    }

    if (sim.dwellUntil && s.now < sim.dwellUntil) {
      sim.speedKph = 0;
      sim.idleSeconds += dt;
      this.emitSample(v, sim, true);
      if (sim.idleSeconds > 15 * 60) {
        raiseAlert(this.store, {
          code: 'excessive_idling',
          title: `${v.name} idling`,
          detail: `${v.name} has been idling for ${Math.round(sim.idleSeconds / 60)} minutes` +
                  (v.street ? ` on ${v.street}` : '') + '.',
          vehicleId: v.id, driverId: v.driverId, lat: v.lat, lon: v.lon,
          evidence: { idle_minutes: Math.round(sim.idleSeconds / 60) },
        });
        if (v.driverId) {
          recordDriverEvent(this.store, {
            driverId: v.driverId, kind: 'idling', vehicleId: v.id, tripId: sim.tripId,
            severity: 'low', lat: v.lat, lon: v.lon, street: v.street,
            value: Math.round(sim.idleSeconds / 60), threshold: 15,
            detail: `Idled for ${Math.round(sim.idleSeconds / 60)} minutes.`,
          });
        }
        sim.idleSeconds = 0;
      }
      return;
    }
    sim.dwellUntil = undefined;

    // Need a destination?
    if (!sim.path.length || sim.seg >= sim.path.length - 1) {
      const task = this.pendingTask(v);
      if (task) this.routeToTask(v, sim, task);
      else this.routeToPlace(v, sim);
      if (!sim.path.length) { sim.parked = true; return; }
    }

    const limit = this.roadLimit(sim);
    let target = limit * (0.72 + Math.random() * 0.28);
    if (Math.random() < OVERSPEED_CHANCE) target = limit * (1.25 + Math.random() * 0.25);
    const prevSpeed = sim.speedKph;
    sim.speedKph += (target - sim.speedKph) * 0.32;
    if (Math.random() < IDLE_CHANCE) sim.speedKph = 0;
    sim.speedKph = Math.max(0, Math.min(sim.speedKph, limit * 1.6));

    const accel = (sim.speedKph - prevSpeed) / 3.6 / Math.max(dt, 0.001);
    const prevHeading = sim.heading;
    const metres = (sim.speedKph / 3.6) * dt;

    const moved = advanceAlong(sim.path, sim.seg, sim.progressM, metres);
    sim.seg = moved.seg;
    sim.progressM = moved.progress;
    sim.heading = moved.heading || sim.heading;
    v.odometerKm += metres / 1000;
    sim.maxSpeedSeen = Math.max(sim.maxSpeedSeen, sim.speedKph);
    sim.idleSeconds = sim.speedKph < 3 ? sim.idleSeconds + dt : 0;

    const turn = Math.abs(angleDelta(prevHeading, sim.heading));
    const lateralG = ((sim.speedKph / 3.6) * (turn * Math.PI / 180)) / Math.max(dt, 0.001) / 9.81;

    this.emitSample(v, sim, true);
    this.detectEvents(v, sim, accel, lateralG, limit, dt);

    if (moved.done) this.onArrival(v, sim);
  }

  private roadLimit(sim: SimState): number {
    const p = pointAt(sim.path, sim.seg, sim.progressM);
    const snapped = this.store.graph.snap(p[0], p[1]);
    if (snapped.edge < 0 || snapped.distance > 70) return 30;
    return this.store.graph.edges[snapped.edge].v;
  }

  private pendingTask(v: Vehicle): Task | undefined {
    const order = { urgent: 0, high: 1, normal: 2, low: 3 };
    return this.store.state.tasks
      .filter((t) => t.vehicleId === v.id && (t.status === 'accepted' || t.status === 'en_route'))
      .sort((a, b) => (order[a.priority] - order[b.priority]) ||
                      ((a.scheduledFor ?? 0) - (b.scheduledFor ?? 0)))[0];
  }

  private routeToTask(v: Vehicle, sim: SimState, task: Task) {
    const r = this.store.graph.route([[v.lon!, v.lat!], [task.lon, task.lat]]);
    if (!r.ok || r.geometry.length < 2) { sim.path = []; return; }
    sim.path = r.geometry;
    sim.seg = 0;
    sim.progressM = 0;
    sim.destination = task.address || task.title;
    sim.taskId = task.id;
    if (task.status === 'accepted') {
      try {
        transitionTask(this.store, task, 'en_route', {
          note: 'Driver started travelling to the customer.',
          actorType: 'driver',
          actorName: this.store.driver(task.driverId)?.fullName ?? 'Driver',
        });
      } catch { /* a concurrent change already moved it */ }
    }
    task.eta = this.store.state.now + r.durationS * 1000;
    const route = this.store.route(task.routeId);
    if (route) {
      route.geometry = r.geometry;
      route.distanceM = r.distanceM;
      route.durationS = r.durationS;
      route.originLat = v.lat!;
      route.originLon = v.lon!;
      route.active = true;
    }
    this.ensureTrip(v, sim, task.id);
  }

  private routeToPlace(v: Vehicle, sim: SimState) {
    const s = this.store.state;
    const pool = s.places.filter((p) => p.active);
    if (!pool.length) { sim.path = []; return; }
    for (let attempt = 0; attempt < 5; attempt++) {
      const dest = pool[Math.floor(Math.random() * pool.length)];
      if (haversine(v.lon!, v.lat!, dest.lon, dest.lat) < 220) continue;
      const r = this.store.graph.route([[v.lon!, v.lat!], [dest.lon, dest.lat]]);
      if (r.ok && r.geometry.length >= 2) {
        sim.path = r.geometry;
        sim.seg = 0;
        sim.progressM = 0;
        sim.destination = dest.name;
        sim.taskId = undefined;
        this.ensureTrip(v, sim);
        return;
      }
    }
    sim.path = [];
  }

  private ensureTrip(v: Vehicle, sim: SimState, taskId?: string) {
    if (sim.tripId) return;
    const s = this.store.state;
    const trip: Trip = {
      id: this.store.id('tr'),
      reference: `TRP-${9000 + this.store.seq('trip')}`,
      vehicleId: v.id, driverId: v.driverId, taskId,
      routeId: taskId ? this.store.task(taskId)?.routeId : undefined,
      status: 'active', startedAt: s.now,
      startLat: v.lat!, startLon: v.lon!,
      startAddress: v.street || this.store.graph.streetAt(v.lon!, v.lat!) || 'Helsinki',
      distanceKm: 0, durationS: 0, idleS: 0, avgSpeedKph: 0, maxSpeedKph: 0,
      stopCount: 0, eventCount: 0, fuelUsedL: 0, energyUsedKwh: 0, co2Kg: 0,
      startOdometerKm: v.odometerKm, positions: [],
    };
    s.trips.unshift(trip);
    sim.tripId = trip.id;
    sim.maxSpeedSeen = 0;
    sim.positions = 0;
    this.store.timeline({
      entityType: 'vehicle', entityId: v.id, action: 'trip_started',
      description: `Trip ${trip.reference} started from ${trip.startAddress}.`,
      relatedType: 'trip', relatedId: trip.id,
    });
    const d = this.store.driver(v.driverId);
    if (d && d.status === 'available') d.status = 'driving';
  }

  private closeTrip(v: Vehicle, sim: SimState) {
    if (!sim.tripId) return;
    const s = this.store.state;
    const trip = this.store.trip(sim.tripId);
    sim.tripId = undefined;
    if (!trip) return;
    trip.status = 'completed';
    trip.endedAt = s.now;
    trip.endLat = v.lat;
    trip.endLon = v.lon;
    trip.endAddress = sim.destination || v.street || 'Helsinki';
    trip.endOdometerKm = Math.round(v.odometerKm * 100) / 100;
    trip.distanceKm = Math.round(Math.max(0, v.odometerKm - trip.startOdometerKm) * 100) / 100;
    trip.durationS = Math.round((s.now - trip.startedAt) / 1000);
    trip.idleS = Math.round(sim.idleSeconds);
    trip.maxSpeedKph = Math.round(sim.maxSpeedSeen * 10) / 10;
    trip.avgSpeedKph = trip.durationS > 30
      ? Math.round((trip.distanceKm / (trip.durationS / 3600)) * 10) / 10 : 0;
    trip.stopCount += 1;

    const settings = s.org.settings;
    if (v.fuelType === 'electric') {
      trip.energyUsedKwh = Math.round(trip.distanceKm * 0.21 * 1000) / 1000;
      trip.co2Kg = Math.round(trip.energyUsedKwh * settings.co2PerKwh * 1000) / 1000;
      if (v.batteryCapacityKwh) {
        v.stateOfChargePct = Math.max(
          5, (v.stateOfChargePct ?? 100) - (trip.energyUsedKwh / v.batteryCapacityKwh) * 100);
        v.rangeKm = Math.round(((v.stateOfChargePct / 100) * v.batteryCapacityKwh) / 0.21);
      }
    } else {
      const rate = (v.avgConsumption ?? 9.5) / 100;
      trip.fuelUsedL = Math.round(trip.distanceKm * rate * 1000) / 1000;
      const factor = v.fuelType === 'petrol'
        ? settings.co2PerLitrePetrol : settings.co2PerLitreDiesel;
      trip.co2Kg = Math.round(trip.fuelUsedL * factor * 1000) / 1000;
    }
    // Trips are pushed oldest-first, so trim from the front: truncating the tail
    // would throw away the newest history and leave the app showing only the past.
    if (s.trips.length > 30000) s.trips.splice(0, s.trips.length - 24000);
  }

  private emitSample(v: Vehicle, sim: SimState, ignition: boolean) {
    const s = this.store.state;
    const p = pointAt(sim.path, sim.seg, sim.progressM);
    v.lon = Math.round(p[0] * 1e6) / 1e6;
    v.lat = Math.round(p[1] * 1e6) / 1e6;
    v.speedKph = Math.round(sim.speedKph * 10) / 10;
    v.heading = Math.round(sim.heading);
    v.lastPositionAt = s.now;
    v.ignitionOn = ignition;
    v.satellites = 9 + Math.floor(Math.random() * 6);
    if (sim.positions % 5 === 0) {
      v.street = this.store.graph.streetAt(v.lon, v.lat) || v.street;
    }
    v.idleSince = sim.speedKph < 3 ? (v.idleSince ?? s.now) : undefined;

    const trip = this.store.trip(sim.tripId);
    if (trip && s.now - sim.lastSampleAt >= 4000) {
      sim.lastSampleAt = s.now;
      trip.positions.push({
        t: s.now, lat: v.lat, lon: v.lon, speedKph: v.speedKph,
        heading: v.heading, odometerKm: Math.round(v.odometerKm * 100) / 100,
        street: v.street, ignition,
      });
      if (trip.positions.length > 400) trip.positions.splice(0, 100);
    }
    sim.positions++;
    this.checkGeofences(v);
    s.lastEventAt = s.now;
  }

  private checkGeofences(v: Vehicle) {
    const s = this.store.state;
    s.geofences.forEach((fence) => {
      if (!fence.active) return;
      if (fence.vehicleIds.length && !fence.vehicleIds.includes(v.id)) return;
      const inside = containsPoint(fence, v.lon!, v.lat!);
      const key = `${fence.id}:${v.id}`;
      const was = s.geofenceInside[key];
      if (was === undefined) { s.geofenceInside[key] = inside; return; }
      if (was === inside) return;
      s.geofenceInside[key] = inside;
      const direction = inside ? 'enter' : 'exit';
      if (fence.trigger !== 'both' && fence.trigger !== direction) return;

      if (fence.restricted && inside) {
        raiseAlert(this.store, {
          code: 'geofence_unauthorized', severity: 'critical',
          title: `${v.name} entered restricted zone ${fence.name}`,
          detail: `${fence.description ?? 'This zone is not permitted for vehicles.'}`,
          vehicleId: v.id, driverId: v.driverId, geofenceId: fence.id,
          lat: v.lat, lon: v.lon, street: v.street,
          dedupeExtra: `${fence.id}:enter`,
          evidence: { geofence: fence.name, direction },
        });
        if (v.driverId) {
          recordDriverEvent(this.store, {
            driverId: v.driverId, kind: 'geofence_breach', vehicleId: v.id,
            severity: 'high', lat: v.lat, lon: v.lon, street: v.street,
            detail: `Entered restricted zone ${fence.name}.`,
          });
        }
      } else {
        raiseAlert(this.store, {
          code: `geofence_${direction}`,
          title: `${v.name} ${inside ? 'entered' : 'left'} ${fence.name}`,
          vehicleId: v.id, driverId: v.driverId, geofenceId: fence.id,
          lat: v.lat, lon: v.lon, street: v.street,
          dedupeExtra: `${fence.id}:${direction}`,
          evidence: { geofence: fence.name, direction },
        });
      }
      this.store.timeline({
        entityType: 'vehicle', entityId: v.id, action: `geofence_${direction}`,
        description: `${inside ? 'Entered' : 'Left'} ${fence.name}.`,
      });
    });
  }

  private detectEvents(
    v: Vehicle, sim: SimState, accel: number, lateralG: number, limit: number, _dt: number,
  ) {
    const s = this.store.state;
    if (!v.driverId) {
      // Movement with nobody assigned is a security matter.
      if (sim.speedKph > 5) {
        raiseAlert(this.store, {
          code: 'unauthorized_movement', severity: 'critical',
          title: `${v.name} is moving with no driver assigned`,
          detail: 'The vehicle reported movement without an accepted task or assigned driver.',
          vehicleId: v.id, lat: v.lat, lon: v.lon, street: v.street,
          evidence: { speed_kph: Math.round(sim.speedKph) },
        });
      }
      return;
    }
    const recently = (kind: string) =>
      s.now - (sim.lastEventAt[kind] ?? -Infinity) < EVENT_REFRACTORY_S * 1000;

    const emit = (
      kind: string, severity: 'low' | 'medium' | 'high', value: number,
      threshold: number, detail: string, alertCode?: string, durationS?: number,
    ) => {
      if (recently(kind)) return;
      let alertId: string | undefined;
      if (alertCode) {
        const a = raiseAlert(this.store, {
          code: alertCode, severity,
          title: `${v.name}: ${kind.replace(/_/g, ' ')}`,
          detail, vehicleId: v.id, driverId: v.driverId, tripId: sim.tripId,
          taskId: sim.taskId, lat: v.lat, lon: v.lon, street: v.street,
          evidence: {
            value: Math.round(value * 10) / 10, threshold,
            street: v.street, speed_kph: Math.round(sim.speedKph),
            duration_s: durationS ? Math.round(durationS) : undefined,
          },
        });
        alertId = a?.id;
      }
      sim.lastEventAt[kind] = s.now;
      recordDriverEvent(this.store, {
        driverId: v.driverId!, kind, vehicleId: v.id, tripId: sim.tripId,
        alertId, severity, lat: v.lat, lon: v.lon, street: v.street,
        value: Math.round(value * 10) / 10, threshold, durationS, detail,
      });
      const trip = this.store.trip(sim.tripId);
      if (trip) trip.eventCount++;
    };

    if (sim.speedKph > limit * 1.15) {
      sim.overspeedSince = sim.overspeedSince ?? s.now;
      const heldS = (s.now - sim.overspeedSince) / 1000;
      if (heldS >= 20) {
        emit('overspeed', sim.speedKph > limit * 1.4 ? 'high' : 'medium',
             sim.speedKph, limit,
             `${Math.round(sim.speedKph)} km/h in a ${Math.round(limit)} km/h zone` +
             (v.street ? ` on ${v.street}` : '') + '.',
             'overspeed', heldS);
        sim.overspeedSince = undefined;
      }
    } else {
      sim.overspeedSince = undefined;
    }

    if (accel < -3.5) {
      emit('harsh_braking', 'medium', Math.abs(accel), 3.5,
           `Deceleration of ${Math.abs(accel).toFixed(1)} m/s²` +
           (v.street ? ` on ${v.street}` : '') + '.', 'harsh_braking');
    } else if (accel > 3.2) {
      emit('harsh_acceleration', 'low', accel, 3.2,
           `Acceleration of ${accel.toFixed(1)} m/s².`, 'harsh_acceleration');
    }
    if (lateralG > 0.45 && sim.speedKph > 20) {
      emit('harsh_cornering', 'low', lateralG, 0.45,
           `Lateral force of ${lateralG.toFixed(2)} g through a turn.`, 'harsh_cornering');
    }
  }

  private onArrival(v: Vehicle, sim: SimState) {
    const s = this.store.state;
    sim.speedKph = 0;
    sim.dwellUntil = s.now + (DWELL_MIN_S + Math.random() * (DWELL_MAX_S - DWELL_MIN_S)) * 1000;
    this.closeTrip(v, sim);

    if (sim.taskId) {
      const task = this.store.task(sim.taskId);
      if (task && task.status === 'en_route') {
        try {
          transitionTask(this.store, task, 'arrived', {
            note: `Arrived at ${task.address || task.title}.`,
            actorType: 'driver',
            actorName: this.store.driver(task.driverId)?.fullName ?? 'Driver',
          });
        } catch { /* already moved on */ }
      }
      sim.taskId = undefined;
    }
    evaluateMaintenance(this.store, v.id);
  }

  /** Drop a vehicle's cached motion so it re-routes on the next tick. */
  reset(vehicleId: string) {
    this.sims.delete(vehicleId);
  }
}

export function containsPoint(fence: Geofence, lon: number, lat: number): boolean {
  if (fence.kind === 'circle') {
    if (fence.centreLat == null || !fence.radiusM) return false;
    return haversine(lon, lat, fence.centreLon!, fence.centreLat) <= fence.radiusM;
  }
  return pointInPolygon(lon, lat, fence.polygon ?? []);
}

export { MIN };
