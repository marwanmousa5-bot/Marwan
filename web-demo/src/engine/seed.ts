// Builds the demo tenant: a Helsinki last-mile courier operator that has been
// running for about seven months. Customer sites, depots and workshops are real
// OpenStreetMap places from the bundled extract; routes are genuinely routed
// over the real street graph.

import { DEFAULT_SETTINGS, DRIVER_SEEDS, MAINTENANCE_TEMPLATES, PARTS_CATALOG,
         RULE_CATALOG, TECHNICIANS, VEHICLE_SEEDS } from './catalog';
import { documentStatus, maintenanceStatus, safetyScore, slaState } from './derive';
import { circlePolygon, haversine } from './geo';
import { Rng } from './rng';
import type { StreetGraph } from './router';
import { Store, type State } from './store';
import type {
  AlertRule, ChargingSession, Customer, Device, Driver, FleetDocument,
  FuelTransaction, Geofence, Incident, MaintenanceRecord, MaintenanceSchedule,
  Place, Task, TaskKind, Trip, TripPosition, User, Vehicle, VehicleType,
  WeatherCell, WorkOrder, Workshop,
} from './types';

export interface RawPlace {
  name: string; cat: string; kind: string; lon: number; lat: number;
  street?: string | null; hn?: string | null;
}

const DAY = 86400000;
const HOUR = 3600000;
const MIN = 60000;

/** Business categories that make believable courier customers. */
const CUSTOMER_KINDS = new Set([
  'department_store', 'supermarket', 'convenience', 'clothes', 'electronics',
  'books', 'furniture', 'hotel', 'pharmacy', 'mall', 'bakery', 'hardware',
  'doityourself', 'jewelry', 'shoes', 'optician', 'company', 'bank',
]);

function iso(ts: number): string {
  return new Date(ts).toISOString().slice(0, 10);
}

function addressOf(p: RawPlace): string {
  if (p.street) return `${p.street}${p.hn ? ' ' + p.hn : ''}, Helsinki`;
  return 'Helsinki';
}

export function buildWorld(graph: StreetGraph, rawPlaces: RawPlace[], now: number): Store {
  const rng = new Rng(0xf1ee7b);
  const state = emptyState(now);
  const store = new Store(state, graph);

  // ---- organization & users ------------------------------------------------
  state.org = {
    id: 'org_kaiku',
    name: 'Kaiku Logistics Oy',
    city: 'Helsinki',
    country: 'Finland',
    settings: { ...DEFAULT_SETTINGS },
  };

  const admin: User = {
    id: 'usr_admin', email: 'hanna.laakso@kaikulogistics.fi',
    fullName: 'Hanna Laakso', role: 'org_admin', avatarColor: '#1E90FF',
  };
  const dispatcher: User = {
    id: 'usr_dispatch', email: 'petri.aalto@kaikulogistics.fi',
    fullName: 'Petri Aalto', role: 'dispatcher', avatarColor: '#F5A623',
  };
  state.users = [admin, dispatcher];
  state.currentUserId = admin.id;

  // ---- places from the real extract ---------------------------------------
  const named = rawPlaces.filter((p) => p.name && p.name.length > 2);
  const candidates = named.filter((p) => CUSTOMER_KINDS.has(p.kind));
  const parking = named.filter((p) => p.kind === 'parking');

  // Depots: real parking structures on the edge of the operating area.
  const depotSpots = parking.length >= 2 ? rng.pickMany(parking, 2) : rng.pickMany(named, 2);
  const depots: Place[] = depotSpots.map((p, i) => ({
    id: store.id('pl'),
    name: i === 0 ? 'Kaiku Depot — Kaisaniemi' : 'Kaiku Depot — Kamppi',
    category: 'depot',
    address: addressOf(p),
    lat: p.lat, lon: p.lon,
    contactName: i === 0 ? 'Hanna Laakso' : 'Petri Aalto',
    contactPhone: i === 0 ? '+358 9 4241 8800' : '+358 9 4241 8820',
    active: true,
  }));

  const customerPlaces: Place[] = rng.pickMany(candidates, 26).map((p) => ({
    id: store.id('pl'),
    name: p.name,
    category: 'customer_site' as const,
    address: addressOf(p),
    lat: p.lat, lon: p.lon,
    contactPhone: `+358 9 ${rng.int(200, 899)} ${rng.int(1000, 9999)}`,
    active: true,
  }));

  const repairSpots = named.filter((p) => p.kind === 'car_repair');
  const workshopSpots = repairSpots.length
    ? repairSpots
    : rng.pickMany(parking.length ? parking : named, 1);
  const workshopPlaces: Place[] = [
    {
      id: store.id('pl'), name: 'Kaiku Workshop — Kaisaniemi',
      category: 'workshop', address: depots[0].address,
      lat: depots[0].lat + 0.0004, lon: depots[0].lon + 0.0006, active: true,
    },
    {
      id: store.id('pl'), name: workshopSpots[0].name,
      category: 'workshop', address: addressOf(workshopSpots[0] as RawPlace),
      lat: workshopSpots[0].lat, lon: workshopSpots[0].lon, active: true,
    },
  ];

  // Fuel and charging points placed on real roadside locations in the area.
  const fuelSpots = rng.pickMany(parking.length >= 3 ? parking : named, 3);
  const fuelPlaces: Place[] = fuelSpots.map((p, i) => ({
    id: store.id('pl'),
    name: ['Neste Express Kaisaniemi', 'St1 Kamppi', 'ABC Hakaniemi'][i],
    category: 'fuel_station' as const,
    address: addressOf(p as RawPlace),
    lat: p.lat, lon: p.lon, active: true,
  }));

  state.places = [...depots, ...customerPlaces, ...workshopPlaces, ...fuelPlaces];

  state.workshops = workshopPlaces.map((p, i): Workshop => ({
    id: store.id('ws'), name: p.name, address: p.address!, lat: p.lat, lon: p.lon,
    contactName: i === 0 ? 'Pekka Rantanen' : 'Jarkko Laine',
    contactPhone: `+358 9 ${rng.int(300, 799)} ${rng.int(1000, 9999)}`,
    dailyCapacity: i === 0 ? 3 : 6,
    openingTime: '07:00', closingTime: i === 0 ? '16:00' : '18:00',
    services: i === 0
      ? ['Servicing', 'Tyres', 'Diagnostics']
      : ['Servicing', 'Bodywork', 'Brakes', 'Transmission', 'Diagnostics'],
    internal: i === 0, active: true,
  }));

  state.customers = customerPlaces.map((p): Customer => ({
    id: store.id('cu'), name: p.name,
    contactName: `${rng.pick(['Anu', 'Timo', 'Riikka', 'Janne', 'Leena', 'Ville',
                              'Maria', 'Samuli'])} ${rng.pick(['Korhonen', 'Nieminen',
                              'Mäkinen', 'Hämäläinen', 'Laine', 'Saari'])}`,
    contactPhone: p.contactPhone!,
    placeId: p.id,
    accountRef: `KL-${rng.int(1000, 9999)}`,
  }));

  // ---- drivers -------------------------------------------------------------
  state.drivers = DRIVER_SEEDS.map((d, i): Driver => {
    const hired = now - rng.int(120, 1500) * DAY;
    return {
      id: store.id('dr'),
      employeeNo: `KL-${(101 + i).toString()}`,
      fullName: d.name,
      email: `${d.name.toLowerCase().replace(/[^a-z ]/g, '').replace(/ /g, '.')}@kaikulogistics.fi`,
      phone: d.phone,
      status: 'off_duty',
      licenseNumber: `FI${rng.int(1000000, 9999999)}`,
      licenseClass: i === 9 ? 'C' : 'B',
      licenseExpiry: iso(now + rng.int(-8, 900) * DAY),
      hiredOn: iso(hired),
      safetyScore: 100,
      previousSafetyScore: 100,
      points: DEFAULT_SETTINGS.driverPointsStart,
      dutyHoursToday: 0,
      shiftStart: rng.pick(['06:30', '07:00', '07:30', '08:00']),
      shiftEnd: rng.pick(['15:30', '16:00', '16:30', '17:00']),
      avatarColor: d.colour,
    };
  });

  // Give each driver a sign-in account so the driver app is reachable.
  state.drivers.forEach((d) => {
    const u: User = {
      id: store.id('usr'), email: d.email, fullName: d.fullName,
      role: 'driver', avatarColor: d.avatarColor, driverId: d.id,
    };
    d.userId = u.id;
    state.users.push(u);
  });

  // ---- devices & vehicles --------------------------------------------------
  state.vehicles = VEHICLE_SEEDS.map((s, i): Vehicle => {
    const purchase = now - rng.int(200, 2000) * DAY;
    const odo = rng.int(18000, 186000);
    return {
      id: store.id('vh'),
      name: s.name, plate: s.plate, vin: `VF1${rng.int(100000, 999999)}${rng.int(10000, 99999)}`,
      type: s.type as VehicleType, make: s.make, model: s.model, year: s.year,
      colour: s.colour, fuelType: s.fuel as Vehicle['fuelType'],
      lifecycle: 'active',
      odometerKm: odo,
      tankCapacityL: s.tank,
      avgConsumption: s.consumption,
      batteryCapacityKwh: s.batteryKwh,
      stateOfChargePct: s.batteryKwh ? rng.int(38, 96) : undefined,
      rangeKm: s.batteryKwh ? Math.round((s.batteryKwh * 0.75) / 0.21) : undefined,
      chargingStatus: s.batteryKwh ? 'idle' : undefined,
      ownership: i % 4 === 0 ? 'leased' : 'owned',
      purchaseDate: iso(purchase),
      purchaseValue: s.value,
      residualValue: s.residual,
      depreciationYears: 7,
      annualInsurance: Math.round(s.value * 0.041),
      annualRegistration: rng.int(180, 520),
      heading: rng.int(0, 359),
      speedKph: 0,
      satellites: rng.int(9, 14),
      ignitionOn: false,
      homePlaceId: depots[i % depots.length].id,
    };
  });

  state.devices = state.vehicles.map((v, i): Device => ({
    id: store.id('dv'),
    serial: `FB-GPS-${(90210 + i * 37).toString()}`,
    imei: `35${rng.int(100000000000, 999999999999)}`,
    model: rng.pick(['FleetBeat Link 4G', 'FleetBeat Link 4G+', 'FleetBeat Nano']),
    firmware: rng.pick(['3.2.1', '3.2.4', '3.3.0']),
    status: 'active',
    orgId: state.org.id,
    vehicleId: v.id,
    lastSignalAt: now - rng.int(5, 90) * 1000,
  }));
  state.vehicles.forEach((v, i) => { v.deviceId = state.devices[i].id; });

  // three spares in stock, held by the platform, not the tenant
  for (let i = 0; i < 3; i++) {
    state.devices.push({
      id: store.id('dv'),
      serial: `FB-GPS-${(91500 + i * 11).toString()}`,
      imei: `35${rng.int(100000000000, 999999999999)}`,
      model: 'FleetBeat Link 4G+', firmware: '3.3.0', status: 'in_stock',
    });
  }

  // pair drivers to vehicles; two vehicles deliberately start unassigned
  const pairing = rng.shuffle([...state.drivers]);
  state.vehicles.forEach((v, i) => {
    if (i < pairing.length - 2) {
      v.driverId = pairing[i].id;
      pairing[i].status = 'available';
    }
  });

  // ---- geofences -----------------------------------------------------------
  state.geofences = buildGeofences(store, depots, customerPlaces, rng);

  // ---- alert rules ---------------------------------------------------------
  state.alertRules = RULE_CATALOG.map((r): AlertRule => ({
    ...r,
    id: store.id('ar'),
    vehicleIds: [], driverIds: [],
    notifyRoles: ['org_admin', 'dispatcher'],
    notifyChannels: ['in_app'],
    escalationMinutes: r.severity === 'high' || r.severity === 'critical' ? [5, 10] : [],
    active: true, system: true,
  }));

  // ---- maintenance schedules ----------------------------------------------
  seedMaintenance(store, rng, now);

  // ---- history: trips, fuel, costs, records, events ------------------------
  seedHistory(store, graph, rng, now, depots, customerPlaces);

  // ---- documents -----------------------------------------------------------
  seedDocuments(store, rng, now);

  // ---- incidents -----------------------------------------------------------
  seedIncidents(store, rng, now);

  // ---- today's operation ---------------------------------------------------
  seedToday(store, graph, rng, now, depots);

  // ---- disruptions & weather ----------------------------------------------
  seedConditions(store, graph, rng, now);

  // ---- derived scores ------------------------------------------------------
  recomputeAllScores(store, now);

  state.savedViews = [
    { id: store.id('sv'), name: 'Needs attention now', surface: 'live_tracking',
      filters: { risk: ['alert', 'critical_alert'], status: ['moving', 'idle'] }, shared: true },
    { id: store.id('sv'), name: 'Late deliveries', surface: 'live_tracking',
      filters: { operational: ['late_task'] }, shared: true },
    { id: store.id('sv'), name: 'Maintenance due', surface: 'live_tracking',
      filters: { risk: ['maintenance_due'] }, shared: true },
    { id: store.id('sv'), name: 'Idle without work', surface: 'live_tracking',
      filters: { status: ['idle', 'stopped'], operational: ['no_task'] }, shared: false },
  ];

  return store;
}

function emptyState(now: number): State {
  return {
    org: { id: '', name: '', city: '', country: '', settings: { ...DEFAULT_SETTINGS } },
    users: [], currentUserId: '', vehicles: [], drivers: [], devices: [], places: [],
    customers: [], geofences: [], geofenceInside: {}, workshops: [], routes: [],
    trips: [], tasks: [], alertRules: [], alerts: [], driverEvents: [],
    pointTransactions: [], badges: [], schedules: [], workOrders: [],
    maintenanceRecords: [], fuel: [], charging: [], documents: [], incidents: [],
    inspections: [], costs: [], recommendations: [], timeline: [], audit: [],
    notifications: [], disruptions: [], weather: [], savedViews: [],
    now, simRunning: true, simSpeed: 8, ticks: 0, connection: 'live',
    lastEventAt: now, counters: {},
  };
}

function buildGeofences(store: Store, depots: Place[], customers: Place[], rng: Rng): Geofence[] {
  const out: Geofence[] = [];
  depots.forEach((d) => {
    out.push({
      id: store.id('gf'), name: `${d.name} yard`, kind: 'circle', trigger: 'both',
      colour: '#1E90FF', centreLat: d.lat, centreLon: d.lon, radiusM: 110,
      vehicleIds: [], active: true, restricted: false,
      description: 'Depot yard — arrival and departure are logged for shift reporting.',
    });
  });
  const core = customers[0];
  out.push({
    id: store.id('gf'), name: 'City centre low-emission zone', kind: 'circle',
    trigger: 'enter', colour: '#2ECC71',
    centreLat: core.lat, centreLon: core.lon, radiusM: 380,
    vehicleIds: [], active: true, restricted: false,
    description: 'Helsinki centre. Electric vehicles are preferred inside this zone.',
  });
  const restricted = customers[4] ?? customers[0];
  out.push({
    id: store.id('gf'), name: 'Pedestrian precinct — no vehicles', kind: 'polygon',
    trigger: 'enter', colour: '#E74C3C',
    polygon: circlePolygon(restricted.lon, restricted.lat, 95, 9).map(
      (p) => [Math.round(p[0] * 1e6) / 1e6, Math.round(p[1] * 1e6) / 1e6] as [number, number]),
    vehicleIds: [], active: true, restricted: true,
    description: 'Vehicles are not permitted here during trading hours.',
  });
  return out;
}

function seedMaintenance(store: Store, rng: Rng, now: number) {
  const s = store.state;
  s.vehicles.forEach((v) => {
    const templates = v.fuelType === 'electric'
      ? [MAINTENANCE_TEMPLATES[3], MAINTENANCE_TEMPLATES[2]]
      : [MAINTENANCE_TEMPLATES[0], MAINTENANCE_TEMPLATES[2],
         ...(rng.chance(0.5) ? [MAINTENANCE_TEMPLATES[1]] : [])];
    templates.forEach((tpl) => {
      tpl.items.forEach((item) => {
        // stagger last-service points so the fleet is not all due at once
        const sinceKm = rng.int(Math.round(tpl.intervalKm * 0.25),
                                Math.round(tpl.intervalKm * 1.08));
        const lastKm = Math.max(0, v.odometerKm - sinceKm);
        const lastDate = now - rng.int(20, Math.round(tpl.intervalMonths * 30)) * DAY;
        const sched: MaintenanceSchedule = {
          id: store.id('ms'), vehicleId: v.id, name: item.label,
          category: item.category,
          intervalKm: tpl.intervalKm, intervalMonths: tpl.intervalMonths,
          lastServiceKm: lastKm, lastServiceDate: iso(lastDate),
          dueAtKm: lastKm + tpl.intervalKm,
          dueAtDate: iso(lastDate + tpl.intervalMonths * 30 * DAY),
          status: 'healthy',
          priority: item.category.includes('brake') ? 'high' : 'normal',
          estimatedCost: item.cost, estimatedMinutes: item.minutes, active: true,
        };
        sched.status = maintenanceStatus(sched, v.odometerKm, now, s.org.settings);
        sched.lastAlertedStatus = sched.status === 'healthy' ? undefined : sched.status;
        s.schedules.push(sched);
      });
    });
  });
}

function seedHistory(
  store: Store, graph: StreetGraph, rng: Rng, now: number,
  depots: Place[], customers: Place[],
) {
  const s = store.state;
  // Four months of operating history. The bundled OpenStreetMap extract covers
  // central Helsinki — roughly 1.6 km by 1 km — so Kaiku is modelled as what
  // actually operates in that footprint: a last-mile courier fleet doing many
  // short drops a day, not a long-haul operation with 300 km runs.
  const HISTORY_DAYS = 120;
  const activeVehicles = s.vehicles;

  // Historical trips: real routed geometry, sampled positions for playback.
  const TRIPS_WITH_GEOMETRY = 160;
  let geometryBudget = TRIPS_WITH_GEOMETRY;

  for (let day = HISTORY_DAYS; day >= 1; day--) {
    const dayStart = now - day * DAY;
    const weekday = new Date(dayStart).getUTCDay();
    if (weekday === 0) continue;                       // Sundays off
    const load = weekday === 6 ? 0.35 : 1;             // light Saturdays

    activeVehicles.forEach((v) => {
      const driver = s.drivers.find((d) => d.id === v.driverId) ?? rng.pick(s.drivers);
      const runs = Math.round(rng.int(10, 20) * load);
      let clock = dayStart + 7 * HOUR + rng.int(0, 50) * MIN;
      for (let r = 0; r < runs; r++) {
        const from = r === 0 ? depots[0] : rng.pick(customers);
        const to = rng.pick(customers);
        if (from.id === to.id) continue;
        const distanceKm = haversine(from.lon, from.lat, to.lon, to.lat) / 1000 * rng.float(1.25, 1.8);
        if (distanceKm < 0.12) continue;
        const avgSpeed = rng.float(16, 31);
        const durationS = (distanceKm / avgSpeed) * 3600;
        const startedAt = clock;
        const endedAt = startedAt + durationS * 1000;
        const consumption = v.avgConsumption ?? 9;
        const fuelUsed = v.fuelType === 'electric' ? 0 : (distanceKm * consumption) / 100;
        const energyUsed = v.fuelType === 'electric' ? distanceKm * 0.21 : 0;

        const trip: Trip = {
          id: store.id('tr'),
          reference: `TRP-${9000 + store.seq('trip')}`,
          vehicleId: v.id, driverId: driver.id, status: 'completed',
          startedAt, endedAt,
          startLat: from.lat, startLon: from.lon, startAddress: from.name,
          endLat: to.lat, endLon: to.lon, endAddress: to.name,
          distanceKm: Math.round(distanceKm * 100) / 100,
          durationS: Math.round(durationS),
          idleS: Math.round(durationS * rng.float(0.05, 0.28)),
          avgSpeedKph: Math.round(avgSpeed * 10) / 10,
          maxSpeedKph: Math.round(avgSpeed * rng.float(1.5, 2.2) * 10) / 10,
          stopCount: 1, eventCount: 0,
          fuelUsedL: Math.round(fuelUsed * 1000) / 1000,
          energyUsedKwh: Math.round(energyUsed * 1000) / 1000,
          co2Kg: Math.round((v.fuelType === 'electric'
            ? energyUsed * s.org.settings.co2PerKwh
            : fuelUsed * s.org.settings.co2PerLitreDiesel) * 1000) / 1000,
          startOdometerKm: 0, endOdometerKm: 0,
          positions: [],
        };

        // The most recent trips carry real geometry so playback works on them.
        if (geometryBudget > 0 && day <= 14) {
          const routed = graph.route([[from.lon, from.lat], [to.lon, to.lat]]);
          if (routed.ok && routed.geometry.length > 2) {
            geometryBudget--;
            trip.distanceKm = Math.round((routed.distanceM / 1000) * 100) / 100;
            trip.durationS = Math.round(routed.durationS);
            trip.endedAt = startedAt + trip.durationS * 1000;
            trip.positions = samplePositions(routed.geometry, startedAt, trip.durationS,
                                             graph, rng);
            trip.avgSpeedKph = Math.round((trip.distanceKm / (trip.durationS / 3600)) * 10) / 10;
            trip.maxSpeedKph = Math.round(
              Math.max(...trip.positions.map((p) => p.speedKph), 10) * 10) / 10;
            // Driver events along the recorded track. These are exceptions, not the
            // norm: a courier covering ~0.7 km per drop should log a handful of
            // harsh-braking events a month, not one on every run.
            const evCount = rng.chance(0.22) ? rng.int(1, 2) : 0;
            for (let e = 0; e < evCount; e++) {
              const p = rng.pick(trip.positions);
              const kind = rng.pick(['overspeed', 'harsh_braking', 'harsh_acceleration',
                                     'harsh_cornering'] as const);
              s.driverEvents.push({
                id: store.id('de'), driverId: driver.id, vehicleId: v.id, tripId: trip.id,
                kind, severity: kind === 'overspeed' ? 'high' : 'medium',
                occurredAt: p.t, lat: p.lat, lon: p.lon, street: p.street,
                value: kind === 'overspeed' ? Math.round(p.speedKph + rng.int(8, 22))
                                            : Math.round(rng.float(3.3, 5.2) * 10) / 10,
                threshold: kind === 'overspeed' ? 30 : 3.5,
                detail: kind === 'overspeed'
                  ? `${Math.round(p.speedKph + rng.int(8, 22))} km/h in a 30 km/h zone${p.street ? ` on ${p.street}` : ''}.`
                  : `${kind.replace('_', ' ')} recorded${p.street ? ` on ${p.street}` : ''}.`,
              });
              trip.eventCount++;
            }
          }
        } else if (rng.chance(0.018)) {
          // events still recorded for summary-only trips, for analytics honesty
          const kind = rng.pick(['overspeed', 'harsh_braking', 'harsh_acceleration',
                                 'harsh_cornering'] as const);
          s.driverEvents.push({
            id: store.id('de'), driverId: driver.id, vehicleId: v.id, tripId: trip.id,
            kind, severity: kind === 'overspeed' ? 'high' : 'medium',
            occurredAt: startedAt + rng.int(60, Math.max(120, trip.durationS)) * 1000,
            lat: to.lat, lon: to.lon,
            value: kind === 'overspeed' ? rng.int(42, 68) : Math.round(rng.float(3.3, 5) * 10) / 10,
            threshold: kind === 'overspeed' ? 30 : 3.5,
            detail: `${kind.replace('_', ' ')} recorded during ${trip.reference}.`,
          });
          trip.eventCount++;
        }

        s.trips.push(trip);
        clock = endedAt + rng.int(8, 26) * MIN;   // drop, sign, load the next one
        if (clock > dayStart + 17 * HOUR) break;
      }
    });
  }

  // Walk odometers backwards so history and the current reading agree.
  const byVehicle = new Map<string, Trip[]>();
  s.trips.forEach((t) => {
    const list = byVehicle.get(t.vehicleId) ?? [];
    list.push(t);
    byVehicle.set(t.vehicleId, list);
  });
  byVehicle.forEach((trips, vid) => {
    const v = s.vehicles.find((x) => x.id === vid)!;
    trips.sort((a, b) => a.startedAt - b.startedAt);
    const total = trips.reduce((sum, t) => sum + t.distanceKm, 0);
    let odo = Math.max(1000, v.odometerKm - total);
    trips.forEach((t) => {
      t.startOdometerKm = Math.round(odo * 100) / 100;
      odo += t.distanceKm;
      t.endOdometerKm = Math.round(odo * 100) / 100;
      t.positions.forEach((p, i) => {
        p.odometerKm = Math.round((t.startOdometerKm! + (t.distanceKm * i) /
          Math.max(1, t.positions.length - 1)) * 100) / 100;
      });
    });
    v.odometerKm = Math.round(odo * 100) / 100;
  });

  seedFuelAndCosts(store, rng, now);
  seedMaintenanceHistory(store, rng, now);
}

function samplePositions(
  geometry: [number, number][], startedAt: number, durationS: number,
  graph: StreetGraph, rng: Rng,
): TripPosition[] {
  const out: TripPosition[] = [];
  const steps = Math.min(90, Math.max(12, Math.round(durationS / 8)));
  let totalLen = 0;
  const cum: number[] = [0];
  for (let i = 0; i < geometry.length - 1; i++) {
    totalLen += haversine(geometry[i][0], geometry[i][1], geometry[i + 1][0], geometry[i + 1][1]);
    cum.push(totalLen);
  }
  for (let s = 0; s <= steps; s++) {
    const frac = s / steps;
    const target = frac * totalLen;
    let idx = 0;
    while (idx < cum.length - 2 && cum[idx + 1] < target) idx++;
    const segLen = (cum[idx + 1] ?? totalLen) - cum[idx] || 1;
    const t = (target - cum[idx]) / segLen;
    const a = geometry[idx];
    const b = geometry[Math.min(idx + 1, geometry.length - 1)];
    const lon = a[0] + (b[0] - a[0]) * t;
    const lat = a[1] + (b[1] - a[1]) * t;
    // speed profile: pull away, cruise, slow to the stop
    const shape = Math.sin(Math.PI * Math.min(1, Math.max(0, frac))) ** 0.6;
    const speed = Math.max(0, shape * rng.float(26, 46) + rng.float(-3, 3));
    out.push({
      t: startedAt + frac * durationS * 1000,
      lat: Math.round(lat * 1e6) / 1e6,
      lon: Math.round(lon * 1e6) / 1e6,
      speedKph: Math.round(speed * 10) / 10,
      heading: 0,
      odometerKm: 0,
      street: s % 6 === 0 ? graph.streetAt(lon, lat) || undefined : undefined,
      ignition: true,
    });
  }
  for (let i = 0; i < out.length - 1; i++) {
    const dx = out[i + 1].lon - out[i].lon;
    const dy = out[i + 1].lat - out[i].lat;
    out[i].heading = Math.round(((Math.atan2(dx, dy) * 180) / Math.PI + 360) % 360);
  }
  if (out.length > 1) out[out.length - 1].heading = out[out.length - 2].heading;
  return out;
}

function seedFuelAndCosts(store: Store, rng: Rng, now: number) {
  const s = store.state;
  const stations = s.places.filter((p) => p.category === 'fuel_station');
  s.vehicles.forEach((v) => {
    const trips = s.trips.filter((t) => t.vehicleId === v.id)
      .sort((a, b) => a.startedAt - b.startedAt);
    if (!trips.length) return;

    if (v.fuelType === 'electric') {
      let lastOdo = trips[0].startOdometerKm ?? 0;
      for (let i = 6; i < trips.length; i += rng.int(5, 9)) {
        const t = trips[i];
        const kwh = Math.round(((t.endOdometerKm! - lastOdo) * 0.21 + rng.float(-1, 2)) * 10) / 10;
        if (kwh < 2) continue;
        const price = s.org.settings.energyPricePerKwh * rng.float(0.85, 1.25);
        const startSoc = rng.int(14, 44);
        const cs: ChargingSession = {
          id: store.id('cs'), vehicleId: v.id, driverId: t.driverId,
          startedAt: t.endedAt! + rng.int(5, 50) * MIN,
          endedAt: t.endedAt! + rng.int(60, 180) * MIN,
          locationName: rng.pick(['Kaiku Depot — Kaisaniemi', 'Virta charge point, Kamppi',
                                  'Helen charge point, Hakaniemi']),
          energyKwh: kwh, pricePerKwh: Math.round(price * 1000) / 1000,
          totalCost: Math.round(kwh * price * 100) / 100,
          startSocPct: startSoc,
          endSocPct: Math.min(100, startSoc + Math.round((kwh / (v.batteryCapacityKwh ?? 40)) * 100)),
          odometerKm: t.endOdometerKm!,
        };
        s.charging.push(cs);
        s.costs.push({
          id: store.id('co'), vehicleId: v.id, category: 'energy',
          incurredOn: iso(cs.startedAt), amount: cs.totalCost,
          description: `Charging — ${cs.locationName}`, sourceType: 'charging_session',
          sourceId: cs.id,
        });
        lastOdo = t.endOdometerKm!;
      }
    } else {
      let lastOdo = trips[0].startOdometerKm ?? 0;
      for (let i = 8; i < trips.length; i += rng.int(7, 13)) {
        const t = trips[i];
        const since = (t.endOdometerKm ?? 0) - lastOdo;
        if (since < 40) continue;
        const litres = Math.round(((since * (v.avgConsumption ?? 9)) / 100) * rng.float(0.92, 1.1) * 10) / 10;
        const price = Math.round(s.org.settings.fuelPricePerLitre * rng.float(0.9, 1.12) * 1000) / 1000;
        const station = rng.pick(stations);
        const tx: FuelTransaction = {
          id: store.id('ft'), vehicleId: v.id, driverId: t.driverId,
          occurredAt: t.endedAt! + rng.int(2, 30) * MIN,
          stationName: station.name, fuelType: v.fuelType,
          litres, pricePerLitre: price,
          totalCost: Math.round(litres * price * 100) / 100,
          odometerKm: t.endOdometerKm!,
          distanceSinceLastKm: Math.round(since * 10) / 10,
          fullTank: true,
          reference: `FC${rng.int(100000, 999999)}`,
        };
        s.fuel.push(tx);
        s.costs.push({
          id: store.id('co'), vehicleId: v.id, category: 'fuel',
          incurredOn: iso(tx.occurredAt), amount: tx.totalCost,
          description: `Fuel — ${station.name}`, sourceType: 'fuel_transaction',
          sourceId: tx.id, odometerKm: tx.odometerKm,
        });
        lastOdo = t.endOdometerKm!;
      }
    }

    // fixed costs, charged monthly
    for (let m = 7; m >= 0; m--) {
      const when = now - m * 30 * DAY;
      s.costs.push({
        id: store.id('co'), vehicleId: v.id, category: 'insurance',
        incurredOn: iso(when), amount: Math.round((v.annualInsurance / 12) * 100) / 100,
        description: 'Insurance premium',
      });
      if (m % 12 === 0) {
        s.costs.push({
          id: store.id('co'), vehicleId: v.id, category: 'registration',
          incurredOn: iso(when), amount: v.annualRegistration,
          description: 'Vehicle tax & registration',
        });
      }
    }
  });
  s.fuel.sort((a, b) => b.occurredAt - a.occurredAt);
  s.charging.sort((a, b) => b.startedAt - a.startedAt);
}

function seedMaintenanceHistory(store: Store, rng: Rng, now: number) {
  const s = store.state;
  s.vehicles.forEach((v) => {
    const services = rng.int(2, 5);
    for (let i = services; i >= 1; i--) {
      const when = now - i * rng.int(35, 80) * DAY;
      const tpl = rng.pick(MAINTENANCE_TEMPLATES);
      const item = rng.pick(tpl.items);
      const partsCost = Math.round(item.cost * rng.float(0.6, 1.15) * 100) / 100;
      const labourHours = Math.round((item.minutes / 60) * rng.float(0.8, 1.4) * 10) / 10;
      const labourCost = Math.round(labourHours * s.org.settings.labourRate * 100) / 100;
      const workshop = rng.pick(s.workshops);
      const rec: MaintenanceRecord = {
        id: store.id('mr'), vehicleId: v.id, category: item.category,
        serviceDate: iso(when),
        odometerKm: Math.max(0, Math.round(v.odometerKm - i * rng.int(2200, 6800))),
        workPerformed: item.label,
        partsCost, labourCost,
        totalCost: Math.round((partsCost + labourCost) * 100) / 100,
        downtimeHours: Math.round(rng.float(1.5, 9) * 10) / 10,
        workshopName: workshop.name,
        technician: rng.pick(TECHNICIANS),
      };
      s.maintenanceRecords.push(rec);
      s.costs.push({
        id: store.id('co'), vehicleId: v.id, category: 'maintenance',
        incurredOn: rec.serviceDate, amount: rec.totalCost,
        description: `${rec.workPerformed} — ${workshop.name}`,
        sourceType: 'maintenance_record', sourceId: rec.id, odometerKm: rec.odometerKm,
      });
    }
  });

  // One vehicle carries a repeat brake problem, which the maintenance copilot finds.
  const repeatVehicle = s.vehicles[6];
  for (let i = 0; i < 3; i++) {
    const when = now - (20 + i * 48) * DAY;
    const rec: MaintenanceRecord = {
      id: store.id('mr'), vehicleId: repeatVehicle.id, category: 'brake_pads',
      serviceDate: iso(when),
      odometerKm: Math.round(repeatVehicle.odometerKm - i * 4200),
      workPerformed: 'Front brake pads replaced — uneven wear reported again',
      partsCost: 96, labourCost: 156,
      totalCost: 252, downtimeHours: 4.5,
      workshopName: s.workshops[1].name, technician: 'Jarkko Laine',
    };
    s.maintenanceRecords.push(rec);
    s.costs.push({
      id: store.id('co'), vehicleId: repeatVehicle.id, category: 'maintenance',
      incurredOn: rec.serviceDate, amount: rec.totalCost,
      description: rec.workPerformed, sourceType: 'maintenance_record', sourceId: rec.id,
    });
  }
  s.maintenanceRecords.sort((a, b) => b.serviceDate.localeCompare(a.serviceDate));
}

function seedDocuments(store: Store, rng: Rng, now: number) {
  const s = store.state;
  const warn = Math.max(...s.org.settings.documentAlertDays);
  const push = (d: Omit<FleetDocument, 'id' | 'status'>) => {
    s.documents.push({ ...d, id: store.id('doc'),
                       status: documentStatus(d.expiryDate, now, warn) });
  };
  s.vehicles.forEach((v, i) => {
    // a couple of documents are deliberately close to expiry, one is past it
    const regOffset = i === 3 ? -6 : i === 7 ? 11 : rng.int(40, 700);
    push({
      kind: 'registration', name: `Registration — ${v.plate}`, entityType: 'vehicle',
      vehicleId: v.id, issuer: 'Traficom', reference: `TR-${rng.int(100000, 999999)}`,
      issueDate: iso(now - rng.int(200, 900) * DAY), expiryDate: iso(now + regOffset * DAY),
      cost: v.annualRegistration,
    });
    const insOffset = i === 1 ? 9 : i === 9 ? 24 : rng.int(50, 640);
    push({
      kind: 'insurance', name: `Motor insurance — ${v.plate}`, entityType: 'vehicle',
      vehicleId: v.id, issuer: rng.pick(['LähiTapiola', 'OP Vakuutus', 'If Vahinkovakuutus']),
      reference: `POL-${rng.int(1000000, 9999999)}`,
      issueDate: iso(now - rng.int(100, 360) * DAY), expiryDate: iso(now + insOffset * DAY),
      cost: v.annualInsurance,
    });
    push({
      kind: 'inspection', name: `Roadworthiness — ${v.plate}`, entityType: 'vehicle',
      vehicleId: v.id, issuer: 'A-Katsastus', reference: `KAT-${rng.int(10000, 99999)}`,
      issueDate: iso(now - rng.int(30, 340) * DAY),
      expiryDate: iso(now + (i === 5 ? 3 : rng.int(30, 380)) * DAY),
      cost: rng.int(65, 120),
    });
  });
  s.drivers.forEach((d) => {
    push({
      kind: 'driver_license', name: `Driving licence — ${d.fullName}`, entityType: 'driver',
      driverId: d.id, issuer: 'Traficom', reference: d.licenseNumber,
      issueDate: iso(now - rng.int(400, 3000) * DAY), expiryDate: d.licenseExpiry,
    });
    if (rng.chance(0.45)) {
      push({
        kind: 'certification', name: `ADR dangerous goods — ${d.fullName}`,
        entityType: 'driver', driverId: d.id, issuer: 'SKAL',
        reference: `ADR-${rng.int(10000, 99999)}`,
        issueDate: iso(now - rng.int(100, 1200) * DAY),
        expiryDate: iso(now + rng.int(-15, 800) * DAY),
      });
    }
  });
  push({
    kind: 'permit', name: 'Goods transport operator licence', entityType: 'organization',
    issuer: 'Traficom', reference: 'LIIK-2024-88213',
    issueDate: iso(now - 500 * DAY), expiryDate: iso(now + 220 * DAY), cost: 450,
  });
  s.documents.sort((a, b) => a.expiryDate.localeCompare(b.expiryDate));
}

function seedIncidents(store: Store, rng: Rng, now: number) {
  const s = store.state;
  const specs: {
    kind: string; severity: Incident['severity']; status: Incident['status'];
    title: string; description: string; daysAgo: number; cost?: number;
  }[] = [
    { kind: 'collision', severity: 'medium', status: 'under_investigation',
      title: 'Low-speed contact with a bollard while reversing',
      description: 'Rear offside panel scuffed while reversing into a loading bay. No injuries; third party not involved.',
      daysAgo: 4, cost: 850 },
    { kind: 'cargo_damage', severity: 'low', status: 'resolved',
      title: 'Two parcels damaged by water ingress',
      description: 'Rear door seal let water in during heavy rain. Parcels replaced and the seal was renewed.',
      daysAgo: 18, cost: 220 },
    { kind: 'breakdown', severity: 'high', status: 'closed',
      title: 'Alternator failure on Mannerheimintie',
      description: 'Vehicle lost electrical power in traffic and was recovered. Alternator replaced under warranty.',
      daysAgo: 34, cost: 640 },
    { kind: 'near_miss', severity: 'medium', status: 'action_required',
      title: 'Cyclist near miss at an unmarked junction',
      description: 'Driver reported a cyclist crossing without signalling. No contact. Junction flagged for a route review.',
      daysAgo: 2 },
    { kind: 'vandalism', severity: 'low', status: 'closed',
      title: 'Graffiti on the nearside panel',
      description: 'Applied overnight in the depot yard. Cleaned; yard lighting was reviewed.',
      daysAgo: 51, cost: 180 },
  ];
  specs.forEach((spec, i) => {
    const v = s.vehicles[(i * 3) % s.vehicles.length];
    const d = s.drivers.find((x) => x.id === v.driverId) ?? s.drivers[i];
    const place = rng.pick(s.places.filter((p) => p.category === 'customer_site'));
    const at = now - spec.daysAgo * DAY - rng.int(1, 8) * HOUR;
    s.incidents.push({
      id: store.id('in'), reference: `INC-${1000 + i + 1}`,
      kind: spec.kind, severity: spec.severity, status: spec.status,
      title: spec.title, description: spec.description, occurredAt: at,
      lat: place.lat, lon: place.lon, address: place.address,
      vehicleId: v.id, driverId: d.id, photos: [], witnesses: [],
      estimatedCost: spec.cost,
      reportedBy: s.users[1].id,
      resolvedAt: spec.status === 'resolved' || spec.status === 'closed'
        ? at + rng.int(1, 6) * DAY : undefined,
      resolutionNote: spec.status === 'closed' ? 'Closed after repair and review.' : undefined,
    });
    store.timeline({
      entityType: 'incident', entityId: s.incidents[s.incidents.length - 1].id,
      action: 'reported', description: `Incident reported — ${spec.title}.`,
      actorType: 'user', actorName: 'Petri Aalto', at,
    });
    store.timeline({
      entityType: 'vehicle', entityId: v.id, action: 'incident_reported',
      description: `INC-${1000 + i + 1}: ${spec.title}`,
      actorType: 'user', actorName: 'Petri Aalto', at,
      relatedType: 'incident', relatedId: s.incidents[s.incidents.length - 1].id,
    });
    if (spec.cost) {
      s.costs.push({
        id: store.id('co'), vehicleId: v.id, category: 'other',
        incurredOn: iso(at), amount: spec.cost,
        description: `Incident ${`INC-${1000 + i + 1}`} — ${spec.title}`,
        sourceType: 'incident',
      });
    }
  });
  s.incidents.sort((a, b) => b.occurredAt - a.occurredAt);
}

const TASK_TITLES: Record<string, string[]> = {
  delivery: ['Parcel delivery', 'Palletised goods delivery', 'Retail restock',
             'Same-day delivery', 'Stock transfer'],
  pickup: ['Returns collection', 'Parcel pickup', 'Empty crate collection'],
  service_call: ['Equipment service call', 'On-site maintenance visit'],
  inspection: ['Site access inspection', 'Loading bay survey'],
  collection: ['Cash collection', 'Document collection'],
};

function seedToday(
  store: Store, graph: StreetGraph, rng: Rng, now: number, depots: Place[],
) {
  const s = store.state;
  const customers = s.customers;
  const dayStart = new Date(now);
  dayStart.setUTCHours(6, 0, 0, 0);
  const start = dayStart.getTime();

  // Yesterday's completed work, so charts and SLA stats have same-day depth.
  for (let i = 0; i < 26; i++) {
    const c = rng.pick(customers);
    const place = store.place(c.placeId)!;
    const v = rng.pick(s.vehicles);
    const d = store.driver(v.driverId) ?? rng.pick(s.drivers);
    const sched = start - DAY + rng.int(2, 9) * HOUR;
    const kind = rng.pick(Object.keys(TASK_TITLES)) as TaskKind;
    const completed = sched + rng.int(20, 150) * MIN;
    const slaDue = sched + rng.int(60, 180) * MIN;
    const failed = rng.chance(0.08);
    s.tasks.push({
      id: store.id('tk'), reference: `TSK-${1000 + store.seq('task')}`,
      title: `${rng.pick(TASK_TITLES[kind])} — ${c.name}`,
      kind, status: failed ? 'failed' : 'completed',
      priority: rng.pick(['low', 'normal', 'normal', 'high'] as const),
      customerId: c.id, placeId: place.id, address: place.address!,
      lat: place.lat, lon: place.lon,
      contactName: c.contactName, contactPhone: c.contactPhone,
      driverId: d.id, vehicleId: v.id,
      scheduledFor: sched, slaDueAt: slaDue, slaMinutes: Math.round((slaDue - sched) / MIN),
      slaState: failed ? 'none' : (completed <= slaDue ? 'met' : 'breached'),
      serviceMinutes: rng.int(5, 20),
      assignedAt: sched - 40 * MIN, acceptedAt: sched - 30 * MIN,
      startedAt: sched, arrivedAt: completed - 8 * MIN,
      completedAt: failed ? undefined : completed,
      failureReason: failed ? rng.pick(['customer_unavailable', 'access_issue',
                                        'wrong_address']) : undefined,
      failureNote: failed ? 'Driver could not complete the drop; rescheduled.' : undefined,
      createdAt: sched - 3 * HOUR,
      pod: failed ? undefined : {
        recipient: c.contactName, notes: 'Left with reception.',
        lat: place.lat, lon: place.lon, at: completed,
      },
    });
  }

  // Today's live board.
  const activeVehicles = s.vehicles.filter((v) => v.driverId);
  let created = 0;
  activeVehicles.forEach((v, vi) => {
    const d = store.driver(v.driverId)!;
    const count = rng.int(2, 4);
    for (let i = 0; i < count; i++) {
      const c = rng.pick(customers);
      const place = store.place(c.placeId)!;
      const kind = rng.pick(Object.keys(TASK_TITLES)) as TaskKind;
      const sched = now + (i - 1) * rng.int(35, 80) * MIN + rng.int(-20, 40) * MIN;
      const slaMinutes = rng.int(60, 180);
      const priority = rng.pick(['normal', 'normal', 'high', 'urgent', 'low'] as const);

      // a spread of lifecycle states so the board is believable
      let status: Task['status'];
      if (i === 0 && vi % 4 !== 3) status = rng.pick(['en_route', 'accepted', 'arrived'] as const);
      else if (i === 0) status = 'in_progress';
      else status = rng.pick(['assigned', 'assigned', 'accepted'] as const);

      const t: Task = {
        id: store.id('tk'), reference: `TSK-${1000 + store.seq('task')}`,
        title: `${rng.pick(TASK_TITLES[kind])} — ${c.name}`,
        kind, status, priority,
        customerId: c.id, placeId: place.id, address: place.address!,
        lat: place.lat, lon: place.lon,
        contactName: c.contactName, contactPhone: c.contactPhone,
        driverId: d.id, vehicleId: v.id,
        scheduledFor: sched,
        windowStart: sched - 30 * MIN, windowEnd: sched + 60 * MIN,
        slaDueAt: sched + slaMinutes * MIN, slaMinutes,
        slaState: 'on_track',
        serviceMinutes: rng.int(5, 20),
        instructions: rng.pick([
          'Use the rear loading bay; buzz for the goods lift.',
          'Ask for the duty manager at the service desk.',
          'Delivery window is strict — do not arrive before the slot opens.',
          'Parking is limited; the loading bay is on the north side.',
          '',
        ]) || undefined,
        assignedAt: now - rng.int(30, 180) * MIN,
        acceptedAt: status !== 'assigned' ? now - rng.int(20, 90) * MIN : undefined,
        startedAt: ['en_route', 'arrived', 'in_progress'].includes(status)
          ? now - rng.int(8, 45) * MIN : undefined,
        arrivedAt: ['arrived', 'in_progress'].includes(status)
          ? now - rng.int(2, 15) * MIN : undefined,
        createdAt: now - rng.int(2, 8) * HOUR,
      };
      s.tasks.push(t);
      created++;
    }
  });

  // A handful of unassigned work so Dispatch has something to place.
  for (let i = 0; i < 6; i++) {
    const c = rng.pick(customers);
    const place = store.place(c.placeId)!;
    const kind = rng.pick(Object.keys(TASK_TITLES)) as TaskKind;
    const sched = now + rng.int(30, 240) * MIN;
    const slaMinutes = rng.int(60, 150);
    s.tasks.push({
      id: store.id('tk'), reference: `TSK-${1000 + store.seq('task')}`,
      title: `${rng.pick(TASK_TITLES[kind])} — ${c.name}`,
      kind, status: 'unassigned',
      priority: i < 2 ? 'urgent' : rng.pick(['normal', 'high'] as const),
      customerId: c.id, placeId: place.id, address: place.address!,
      lat: place.lat, lon: place.lon,
      contactName: c.contactName, contactPhone: c.contactPhone,
      scheduledFor: sched,
      windowStart: sched - 20 * MIN, windowEnd: sched + 50 * MIN,
      slaDueAt: sched + slaMinutes * MIN, slaMinutes, slaState: 'on_track',
      serviceMinutes: rng.int(5, 20),
      createdAt: now - rng.int(10, 120) * MIN,
    });
  }

  // Position vehicles on the network and build live routes for active work.
  s.vehicles.forEach((v, i) => {
    const home = depots[i % depots.length];
    const jitter = () => rng.float(-0.0025, 0.0025);
    const snapped = graph.snap(home.lon + jitter(), home.lat + jitter());
    const pt = snapped.edge >= 0 ? snapped.point : [home.lon, home.lat];
    v.lon = Math.round(pt[0] * 1e6) / 1e6;
    v.lat = Math.round(pt[1] * 1e6) / 1e6;
    v.street = graph.streetAt(v.lon, v.lat) || undefined;
    v.lastPositionAt = now - rng.int(2, 30) * 1000;
    v.ignitionOn = Boolean(v.driverId);
    v.speedKph = 0;
  });

  // Two vehicles are deliberately stale/offline so the freshness rules are visible.
  const offline = s.vehicles[s.vehicles.length - 1];
  offline.lastPositionAt = now - 22 * MIN;
  offline.ignitionOn = false;
  const stale = s.vehicles[s.vehicles.length - 2];
  stale.lastPositionAt = now - 95 * 1000;

  // timeline seeds for today's tasks
  s.tasks.filter((t) => t.createdAt >= start - DAY).forEach((t) => {
    store.timeline({ entityType: 'task', entityId: t.id, action: 'created',
                     description: `Task created — ${t.title}.`,
                     actorType: 'user', actorName: 'Petri Aalto', at: t.createdAt });
    if (t.assignedAt) {
      const d = store.driver(t.driverId);
      store.timeline({ entityType: 'task', entityId: t.id, action: 'assigned',
                       description: `Task assigned to ${d?.fullName ?? 'a driver'}.`,
                       actorType: 'user', actorName: 'Petri Aalto', at: t.assignedAt });
    }
    if (t.acceptedAt) {
      store.timeline({ entityType: 'task', entityId: t.id, action: 'accepted',
                       description: 'Driver accepted the task.',
                       actorType: 'driver',
                       actorName: store.driver(t.driverId)?.fullName ?? 'Driver',
                       at: t.acceptedAt });
    }
    if (t.startedAt) {
      store.timeline({ entityType: 'task', entityId: t.id, action: 'en_route',
                       description: 'Driver started travelling to the customer.',
                       actorType: 'driver',
                       actorName: store.driver(t.driverId)?.fullName ?? 'Driver',
                       at: t.startedAt });
    }
    if (t.arrivedAt) {
      store.timeline({ entityType: 'task', entityId: t.id, action: 'arrived',
                       description: `Arrived at ${t.address}.`, actorType: 'driver',
                       actorName: store.driver(t.driverId)?.fullName ?? 'Driver',
                       at: t.arrivedAt });
    }
    if (t.completedAt) {
      store.timeline({ entityType: 'task', entityId: t.id, action: 'completed',
                       description: 'Task completed and proof of delivery captured.',
                       actorType: 'driver',
                       actorName: store.driver(t.driverId)?.fullName ?? 'Driver',
                       at: t.completedAt });
    }
  });

  // A couple of open work orders so the workshop has a queue.
  seedWorkOrders(store, rng, now);
  void created;
}

function seedWorkOrders(store: Store, rng: Rng, now: number) {
  const s = store.state;
  const overdue = s.schedules
    .filter((x) => x.status === 'overdue' || x.status === 'critical')
    .slice(0, 3);
  const specs: { sched?: MaintenanceSchedule; status: WorkOrder['status']; title: string;
                 problem: string; daysOffset: number }[] = [
    { sched: overdue[0], status: 'in_progress',
      title: overdue[0]?.name ?? 'Brake inspection',
      problem: 'Preventive service overdue. Driver also reports a squeal under braking.',
      daysOffset: 0 },
    { sched: overdue[1], status: 'scheduled',
      title: overdue[1]?.name ?? 'Engine oil & filter',
      problem: 'Preventive service threshold passed.', daysOffset: 1 },
    { sched: undefined, status: 'waiting_for_parts',
      title: 'Sliding door mechanism repair',
      problem: 'Nearside sliding door binds and will not latch reliably.', daysOffset: -1 },
    { sched: undefined, status: 'requested',
      title: 'Windscreen chip repair',
      problem: 'Stone chip in the driver sight line, spreading.', daysOffset: 2 },
  ];

  specs.forEach((spec, i) => {
    const v = spec.sched
      ? s.vehicles.find((x) => x.id === spec.sched!.vehicleId)!
      : s.vehicles[(i * 5 + 2) % s.vehicles.length];
    const workshop = rng.pick(s.workshops);
    const scheduledStart = now + spec.daysOffset * DAY + rng.int(-3, 5) * HOUR;
    const labourHours = Math.round(rng.float(1, 5) * 10) / 10;
    const wo: WorkOrder = {
      id: store.id('wo'), reference: `WO-${(store.seq('wo') + 840).toString().padStart(5, '0')}`,
      vehicleId: v.id, scheduleId: spec.sched?.id, workshopId: workshop.id,
      status: spec.status,
      priority: spec.status === 'in_progress' ? 'high' : rng.pick(['normal', 'high'] as const),
      category: spec.sched?.category ?? 'general_inspection',
      title: spec.title, problem: spec.problem,
      technician: rng.pick(TECHNICIANS),
      scheduledStart,
      expectedCompletion: scheduledStart + rng.int(2, 8) * HOUR,
      actualStart: spec.status === 'in_progress' || spec.status === 'waiting_for_parts'
        ? now - rng.int(1, 5) * HOUR : undefined,
      labourHours, labourRate: s.org.settings.labourRate,
      labourCost: Math.round(labourHours * s.org.settings.labourRate * 100) / 100,
      partsCost: 0, totalCost: 0,
      estimatedCost: spec.sched?.estimatedCost ?? rng.int(120, 640),
      odometerKm: v.odometerKm,
      parts: [], createdAt: now - rng.int(1, 4) * DAY,
    };
    const partCount = spec.status === 'requested' ? 0 : rng.int(1, 3);
    for (let p = 0; p < partCount; p++) {
      const part = rng.pick(PARTS_CATALOG);
      wo.parts.push({
        id: store.id('wp'), name: part.name, sku: part.sku,
        quantity: rng.int(1, 2), unitCost: part.cost, supplier: part.supplier,
        warrantyMonths: rng.pick([12, 24, undefined]) as number | undefined,
      });
    }
    wo.partsCost = Math.round(wo.parts.reduce((a, p) => a + p.quantity * p.unitCost, 0) * 100) / 100;
    wo.totalCost = Math.round((wo.partsCost + wo.labourCost) * 100) / 100;
    s.workOrders.push(wo);

    if (spec.sched) spec.sched.status = 'in_workshop';
    if (spec.status === 'in_progress') v.lifecycle = 'maintenance';

    store.timeline({ entityType: 'work_order', entityId: wo.id, action: 'requested',
                     description: `Work order raised: ${wo.title}.`, actorType: 'user',
                     actorName: 'Hanna Laakso', at: wo.createdAt });
    store.timeline({ entityType: 'vehicle', entityId: v.id, action: 'work_order_created',
                     description: `Work order ${wo.reference} raised: ${wo.title}.`,
                     actorType: 'user', actorName: 'Hanna Laakso', at: wo.createdAt,
                     relatedType: 'work_order', relatedId: wo.id });
  });
}

function seedConditions(store: Store, graph: StreetGraph, rng: Rng, now: number) {
  const s = store.state;
  const named = graph.edges.filter((e) => e.name);
  const pick = () => rng.pick(named);

  const closure = pick();
  const mid = closure.geom[Math.floor(closure.geom.length / 2)];
  s.disruptions.push({
    id: store.id('rd'), kind: 'closure',
    title: `${closure.name} closed for resurfacing`,
    description: 'City works between the two junctions. Expect diversions until 18:00.',
    severity: 'high', lat: mid[1], lon: mid[0], radiusM: 60,
    geometry: closure.geom as [number, number][],
    street: closure.name, delayMinutes: 9, active: true,
  });

  const congestion = pick();
  const cmid = congestion.geom[Math.floor(congestion.geom.length / 2)];
  s.disruptions.push({
    id: store.id('rd'), kind: 'congestion',
    title: `Heavy traffic on ${congestion.name}`,
    description: 'Queueing traffic reported towards the city centre.',
    severity: 'medium', lat: cmid[1], lon: cmid[0], radiusM: 60,
    geometry: congestion.geom as [number, number][],
    street: congestion.name, delayMinutes: 5, active: true,
  });

  const b = graph.bounds;
  const conditions: WeatherCell['condition'][] = ['rain', 'clear', 'sleet', 'fog'];
  for (let i = 0; i < 5; i++) {
    const lon = rng.float(b[0], b[2]);
    const lat = rng.float(b[1], b[3]);
    const condition = i === 0 ? 'rain' : rng.pick(conditions);
    s.weather.push({
      id: store.id('wx'), lat, lon, condition,
      temperatureC: Math.round(rng.float(-3, 9) * 10) / 10,
      windKph: Math.round(rng.float(4, 38)),
      precipitationMm: condition === 'clear' ? 0 : Math.round(rng.float(0.4, 6.5) * 10) / 10,
      visibilityM: condition === 'fog' ? rng.int(180, 900) : rng.int(4000, 12000),
      severity: condition === 'clear' ? 'none'
        : condition === 'fog' ? 'high' : rng.pick(['low', 'medium'] as const),
      radiusM: rng.int(420, 900),
      observedAt: now - rng.int(3, 40) * MIN,
    });
  }
}

export function recomputeAllScores(store: Store, now: number) {
  const s = store.state;
  const since = now - 30 * DAY;
  s.drivers.forEach((d) => {
    const events = s.driverEvents.filter((e) => e.driverId === d.id && e.occurredAt >= since);
    const counts: Record<string, number> = {};
    events.forEach((e) => { counts[e.kind] = (counts[e.kind] ?? 0) + 1; });
    const incidents = s.incidents.filter((i) => i.driverId === d.id && i.occurredAt >= since);
    if (incidents.length) counts.incident = incidents.length;
    const km = s.trips
      .filter((t) => t.driverId === d.id && t.startedAt >= since)
      .reduce((a, t) => a + t.distanceKm, 0);
    const score = safetyScore(counts, km, s.org.settings.safetyWeights);
    d.previousSafetyScore = Math.max(0, Math.min(100,
      score + (score > 60 ? -1 : 1) * (Math.abs(score * 7919) % 500) / 100));
    d.safetyScore = score;

    // points reflect the same 30-day event window
    let balance = s.org.settings.driverPointsStart;
    const weights = s.org.settings.driverPoints;
    events.sort((a, b) => a.occurredAt - b.occurredAt).forEach((e) => {
      const delta = weights[e.kind] ?? 0;
      if (!delta) return;
      balance = Math.max(0, balance + delta);
      s.pointTransactions.push({
        id: store.id('pt'), driverId: d.id, points: delta, balanceAfter: balance,
        reason: e.kind, detail: e.detail, occurredAt: e.occurredAt,
      });
    });
    d.points = balance;
  });

  // Badges follow from the same data, so they are earned rather than decorative.
  const period = new Date(now).toISOString().slice(0, 7);
  const weekAgo = now - 7 * DAY;
  const award = (driverId: string, code: string, name: string,
                 description: string, icon: string) => {
    if (s.badges.some((b) => b.driverId === driverId && b.code === code && b.period === period)) return;
    s.badges.push({ id: store.id('bd'), driverId, code, name, description, icon,
                    awardedAt: now - Math.round(Math.random() * 3) * DAY, period });
  };
  s.drivers.forEach((d) => {
    const recentEvents = s.driverEvents.filter(
      (e) => e.driverId === d.id && e.occurredAt >= weekAgo &&
             ['overspeed', 'harsh_braking', 'harsh_acceleration', 'harsh_cornering']
               .includes(e.kind));
    const drove = s.trips.some((t) => t.driverId === d.id && t.startedAt >= weekAgo);
    if (!recentEvents.length && drove) {
      award(d.id, 'clean_streak_7', '7-Day Clean Streak',
            'Seven consecutive days with no safety events.', 'shield');
    }
  });
  const champion = [...s.drivers].sort((a, b) => b.safetyScore - a.safetyScore)[0];
  if (champion && champion.safetyScore >= 85) {
    award(champion.id, 'safety_champion', 'Safety Champion',
          'Highest safety score in the fleet this month.', 'award');
  }
  const improved = [...s.drivers]
    .sort((a, b) => (b.safetyScore - b.previousSafetyScore) -
                    (a.safetyScore - a.previousSafetyScore))[0];
  if (improved) {
    award(improved.id, 'most_improved', 'Most Improved',
          'Largest safety-score gain this month.', 'trending-up');
  }
  // Eco driver: best consumption among combustion vans over the period.
  const eco = s.vehicles
    .filter((v) => v.fuelType !== 'electric' && v.driverId)
    .map((v) => {
      const trips = s.trips.filter((t) => t.vehicleId === v.id && t.startedAt >= since);
      const km = trips.reduce((a, t) => a + t.distanceKm, 0);
      const l = trips.reduce((a, t) => a + t.fuelUsedL, 0);
      return { driverId: v.driverId!, per100: km > 50 ? (l / km) * 100 : Infinity };
    })
    .sort((a, b) => a.per100 - b.per100)[0];
  if (eco && Number.isFinite(eco.per100)) {
    award(eco.driverId, 'eco_driver', 'Eco Driver',
          "Consumption in the fleet's best quartile this month.", 'leaf');
  }

  // SLA state for every task, from one source of truth.
  s.tasks.forEach((t) => { t.slaState = slaState(t, now, s.org.settings.slaAtRiskMinutes); });
}
