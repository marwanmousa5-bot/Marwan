// Read models. Every figure the UI shows is computed here from the same state,
// so no two modules can disagree about the fleet.

import { isOpen } from './alerts';
import {
  annualDepreciation, bookValue, documentStatus, gpsFreshness, maintenanceHealth,
  maintenanceStatus, slaMinutesRemaining, vehicleStatus, worstMaintenance,
} from './derive';
import { routeProgress } from './router';
import type { Store } from './store';
import type {
  Alert, Driver, MaintenanceStatus, Severity, Task, Vehicle, VehicleStatus,
} from './types';

const DAY = 86400000;
const HOUR = 3600000;

export const ACTIVE_TASK_STATUSES: Task['status'][] =
  ['assigned', 'accepted', 'en_route', 'arrived', 'in_progress', 'delayed'];

export const OPEN_WO_STATUSES = [
  'requested', 'approved', 'scheduled', 'in_progress', 'waiting_for_parts',
];

export interface FleetRow {
  vehicle: Vehicle;
  status: VehicleStatus;
  freshness: ReturnType<typeof gpsFreshness>;
  driver?: Driver;
  task?: Task;
  taskCount: number;
  lateTaskCount: number;
  alertCount: number;
  worstAlert?: Severity;
  maintenance: MaintenanceStatus;
  routeProgressPct?: number;
  remainingKm?: number;
  deviationM?: number;
  destination?: string;
  eta?: number;
}

export function fleetRows(store: Store): FleetRow[] {
  const s = store.state;
  const now = s.now;
  const openWO = new Set(
    s.workOrders.filter((w) => OPEN_WO_STATUSES.includes(w.status)).map((w) => w.vehicleId));

  const alertsByVehicle = new Map<string, { count: number; worst: Severity }>();
  const rank: Record<Severity, number> = { low: 0, medium: 1, high: 2, critical: 3 };
  s.alerts.forEach((a) => {
    if (!a.vehicleId || !isOpen(a)) return;
    const cur = alertsByVehicle.get(a.vehicleId);
    if (!cur) alertsByVehicle.set(a.vehicleId, { count: 1, worst: a.severity });
    else {
      cur.count++;
      if (rank[a.severity] > rank[cur.worst]) cur.worst = a.severity;
    }
  });

  const tasksByVehicle = new Map<string, Task[]>();
  s.tasks.forEach((t) => {
    if (!t.vehicleId || !ACTIVE_TASK_STATUSES.includes(t.status)) return;
    const list = tasksByVehicle.get(t.vehicleId) ?? [];
    list.push(t);
    tasksByVehicle.set(t.vehicleId, list);
  });

  const maintByVehicle = new Map<string, MaintenanceStatus>();
  s.schedules.forEach((sc) => {
    if (!sc.active) return;
    const status = sc.status === 'in_workshop'
      ? sc.status : maintenanceStatus(sc, store.vehicle(sc.vehicleId)?.odometerKm ?? 0,
                                      now, s.org.settings);
    const cur = maintByVehicle.get(sc.vehicleId);
    maintByVehicle.set(sc.vehicleId, cur ? worstMaintenance(cur, status) : status);
  });

  return s.vehicles.map((v): FleetRow => {
    const tasks = (tasksByVehicle.get(v.id) ?? [])
      .sort((a, b) => (a.scheduledFor ?? 0) - (b.scheduledFor ?? 0));
    const task = tasks[0];
    const alerts = alertsByVehicle.get(v.id);
    const route = store.route(task?.routeId);
    let progressPct: number | undefined;
    let remainingKm: number | undefined;
    let deviationM: number | undefined;
    if (route?.geometry.length && v.lat != null) {
      const p = routeProgress(route.geometry, v.lat, v.lon!);
      progressPct = Math.round(p.pct);
      remainingKm = Math.round((p.remainingM / 1000) * 100) / 100;
      deviationM = Math.round(p.deviationM);
    }
    return {
      vehicle: v,
      status: vehicleStatus(v, { openWorkOrder: openWO.has(v.id), now, settings: s.org.settings }),
      freshness: gpsFreshness(v.lastPositionAt, now,
                              s.org.settings.gpsLiveThresholdS, s.org.settings.gpsStaleThresholdS),
      driver: store.driver(v.driverId),
      task,
      taskCount: tasks.length,
      lateTaskCount: tasks.filter((t) => t.slaState === 'at_risk' || t.slaState === 'breached').length,
      alertCount: alerts?.count ?? 0,
      worstAlert: alerts?.worst,
      maintenance: maintByVehicle.get(v.id) ?? 'healthy',
      routeProgressPct: progressPct,
      remainingKm,
      deviationM,
      destination: route?.destName ?? task?.address,
      eta: task?.eta,
    };
  });
}

export function liveKpis(store: Store, rows: FleetRow[]) {
  const s = store.state;
  const dayStart = new Date(s.now).setUTCHours(0, 0, 0, 0);
  const distanceToday = s.trips
    .filter((t) => t.startedAt >= dayStart)
    .reduce((a, t) => a + t.distanceKm, 0);
  const count = (st: VehicleStatus) => rows.filter((r) => r.status === st).length;
  return {
    activeVehicles: count('moving') + count('idle') + count('stopped'),
    moving: count('moving'),
    idle: count('idle'),
    stopped: count('stopped'),
    offline: count('offline'),
    notTracked: count('not_tracked'),
    withAlerts: rows.filter((r) => r.alertCount > 0).length,
    inMaintenance: count('maintenance'),
    distanceTodayKm: Math.round(distanceToday * 10) / 10,
    activeTasks: rows.reduce((a, r) => a + r.taskCount, 0),
    lateTasks: rows.reduce((a, r) => a + r.lateTaskCount, 0),
  };
}

export function alertSummary(store: Store) {
  const s = store.state;
  const dayStart = new Date(s.now).setUTCHours(0, 0, 0, 0);
  const open = s.alerts.filter(isOpen);
  const bySeverity = (sev: Severity) => open.filter((a) => a.severity === sev).length;
  const byCategory: Record<string, number> = {};
  open.forEach((a) => { byCategory[a.category] = (byCategory[a.category] ?? 0) + 1; });
  return {
    critical: bySeverity('critical'),
    high: bySeverity('high'),
    medium: bySeverity('medium'),
    low: bySeverity('low'),
    active: open.length,
    unacknowledged: s.alerts.filter((a) => a.status === 'triggered').length,
    escalated: s.alerts.filter((a) => a.status === 'escalated').length,
    snoozed: s.alerts.filter((a) => a.status === 'snoozed').length,
    resolvedToday: s.alerts.filter((a) => (a.resolvedAt ?? 0) >= dayStart).length,
    byCategory,
  };
}

export function maintenanceSummary(store: Store) {
  const s = store.state;
  const today = new Date(s.now).toISOString().slice(0, 10);
  const week = new Date(s.now + 7 * DAY).toISOString().slice(0, 10);
  const month = new Date(s.now + 30 * DAY).toISOString().slice(0, 10);
  const active = s.schedules.filter((x) => x.active);
  const by = (st: MaintenanceStatus) => active.filter((x) => x.status === st).length;
  const openWO = s.workOrders.filter((w) => OPEN_WO_STATUSES.includes(w.status));
  return {
    overdue: by('overdue'),
    critical: by('critical'),
    due: by('due'),
    dueSoon: by('due_soon'),
    healthy: by('healthy'),
    dueToday: active.filter((x) => x.dueAtDate === today).length,
    dueThisWeek: active.filter((x) => x.dueAtDate && x.dueAtDate > today && x.dueAtDate <= week).length,
    dueThisMonth: active.filter((x) => x.dueAtDate && x.dueAtDate > today && x.dueAtDate <= month).length,
    inWorkshop: new Set(s.workOrders
      .filter((w) => w.status === 'in_progress' || w.status === 'waiting_for_parts')
      .map((w) => w.vehicleId)).size,
    openWorkOrders: openWO.length,
    estimatedCost: Math.round(openWO.reduce((a, w) => a + (w.estimatedCost || w.totalCost), 0)),
    spend30d: Math.round(s.maintenanceRecords
      .filter((r) => Date.parse(r.serviceDate) >= s.now - 30 * DAY)
      .reduce((a, r) => a + r.totalCost, 0)),
  };
}

export function vehicleHealth(store: Store, vehicleId: string) {
  const s = store.state;
  const schedules = s.schedules.filter((x) => x.vehicleId === vehicleId && x.active);
  const counts = {
    overdue: schedules.filter((x) => x.status === 'overdue').length,
    critical: schedules.filter((x) => x.status === 'critical').length,
    due: schedules.filter((x) => x.status === 'due').length,
    dueSoon: schedules.filter((x) => x.status === 'due_soon').length,
    openWorkOrders: s.workOrders.filter(
      (w) => w.vehicleId === vehicleId && OPEN_WO_STATUSES.includes(w.status)).length,
    repeatFailures: 0,
  };
  const since = s.now - 180 * DAY;
  const byCategory: Record<string, number> = {};
  s.maintenanceRecords
    .filter((r) => r.vehicleId === vehicleId && Date.parse(r.serviceDate) >= since)
    .forEach((r) => { byCategory[r.category] = (byCategory[r.category] ?? 0) + 1; });
  const repeats = Object.entries(byCategory).filter(([, n]) => n >= 3);
  counts.repeatFailures = repeats.length;
  return {
    score: maintenanceHealth(counts, s.org.settings.maintenanceHealthWeights),
    counts,
    repeatCategories: repeats.map(([category, count]) => ({ category, count })),
  };
}

export function dispatchExceptions(store: Store) {
  const s = store.state;
  const out: {
    type: string; severity: Severity; title: string; detail: string;
    entityType: string; entityId: string; lat?: number; lon?: number;
  }[] = [];

  s.tasks.filter((t) => t.status === 'unassigned').forEach((t) => {
    const urgent = t.scheduledFor && t.scheduledFor <= s.now + 2 * HOUR;
    out.push({
      type: 'unassigned_task', severity: urgent ? 'high' : 'medium',
      title: `${t.reference} is unassigned`,
      detail: t.title + (t.scheduledFor ? ` — due ${fmtHm(t.scheduledFor)}` : ''),
      entityType: 'task', entityId: t.id, lat: t.lat, lon: t.lon,
    });
  });

  s.tasks
    .filter((t) => ACTIVE_TASK_STATUSES.includes(t.status) &&
                   (t.slaState === 'at_risk' || t.slaState === 'breached'))
    .forEach((t) => {
      out.push({
        type: 'sla_risk', severity: t.slaState === 'breached' ? 'critical' : 'high',
        title: `${t.reference} SLA ${t.slaState.replace('_', ' ')}`,
        detail: `${t.title} — ETA ${fmtHm(t.eta)}, deadline ${fmtHm(t.slaDueAt)}`,
        entityType: 'task', entityId: t.id, lat: t.lat, lon: t.lon,
      });
    });

  s.alerts
    .filter((a) => isOpen(a) && (a.severity === 'high' || a.severity === 'critical'))
    .slice(0, 25)
    .forEach((a) => {
      out.push({
        type: 'alert', severity: a.severity, title: a.title, detail: a.detail ?? '',
        entityType: 'alert', entityId: a.id, lat: a.lat, lon: a.lon,
      });
    });

  s.vehicles
    .filter((v) => v.lifecycle === 'maintenance' || v.lifecycle === 'suspended')
    .forEach((v) => {
      const n = s.tasks.filter(
        (t) => t.vehicleId === v.id && ACTIVE_TASK_STATUSES.includes(t.status)).length;
      if (!n) return;
      out.push({
        type: 'vehicle_unavailable', severity: 'high',
        title: `${v.name} is ${v.lifecycle} with ${n} active task${n === 1 ? '' : 's'}`,
        detail: 'Reassign the work to keep the schedule intact.',
        entityType: 'vehicle', entityId: v.id, lat: v.lat, lon: v.lon,
      });
    });

  s.vehicles.forEach((v) => {
    const route = s.routes.find((r) => r.vehicleId === v.id && r.active);
    if (!route?.geometry.length || v.lat == null) return;
    const p = routeProgress(route.geometry, v.lat, v.lon!);
    if (p.deviationM > 250) {
      out.push({
        type: 'route_deviation', severity: 'medium',
        title: `${v.name} is ${Math.round(p.deviationM)} m off its planned route`,
        detail: `Heading to ${route.destName}.`,
        entityType: 'vehicle', entityId: v.id, lat: v.lat, lon: v.lon,
      });
    }
  });

  const rank: Record<Severity, number> = { critical: 0, high: 1, medium: 2, low: 3 };
  out.sort((a, b) => rank[a.severity] - rank[b.severity]);
  return out;
}

export function fmtHm(ts?: number): string {
  if (!ts) return '—';
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function driverWorkload(store: Store) {
  const s = store.state;
  return s.drivers.map((d) => {
    const tasks = s.tasks.filter(
      (t) => t.driverId === d.id && ACTIVE_TASK_STATUSES.includes(t.status));
    const late = tasks.filter((t) => t.slaState === 'at_risk' || t.slaState === 'breached');
    const vehicle = s.vehicles.find((v) => v.driverId === d.id);
    return {
      driver: d, vehicle, activeTasks: tasks.length, lateTasks: late.length,
      loadPct: Math.min(100, Math.round((tasks.length / 6) * 100)),
      available: d.status === 'available' || d.status === 'driving',
    };
  });
}

export function fuelSummary(store: Store, days = 30) {
  const s = store.state;
  const since = s.now - days * DAY;
  const fuel = s.fuel.filter((f) => f.occurredAt >= since);
  const charge = s.charging.filter((c) => c.startedAt >= since);
  const trips = s.trips.filter((t) => t.startedAt >= since);
  const litres = fuel.reduce((a, f) => a + f.litres, 0);
  const fuelCost = fuel.reduce((a, f) => a + f.totalCost, 0);
  const kwh = charge.reduce((a, c) => a + c.energyKwh, 0);
  const energyCost = charge.reduce((a, c) => a + c.totalCost, 0);
  const km = trips.reduce((a, t) => a + t.distanceKm, 0);

  const perVehicle = s.vehicles.map((v) => {
    const vTrips = trips.filter((t) => t.vehicleId === v.id);
    const vKm = vTrips.reduce((a, t) => a + t.distanceKm, 0);
    const vL = fuel.filter((f) => f.vehicleId === v.id).reduce((a, f) => a + f.litres, 0);
    const vLCost = fuel.filter((f) => f.vehicleId === v.id).reduce((a, f) => a + f.totalCost, 0);
    const vKwh = charge.filter((c) => c.vehicleId === v.id).reduce((a, c) => a + c.energyKwh, 0);
    const vKwhCost = charge.filter((c) => c.vehicleId === v.id).reduce((a, c) => a + c.totalCost, 0);
    const cost = vLCost + vKwhCost;
    const electric = v.fuelType === 'electric';
    return {
      vehicle: v, distanceKm: vKm, litres: vL, fuelCost: vLCost,
      kwh: vKwh, energyCost: vKwhCost, totalCost: cost,
      costPerKm: vKm > 5 ? cost / vKm : null,
      efficiency: vKm > 5 ? (electric ? (vKwh / vKm) * 100 : (vL / vKm) * 100) : null,
      unit: electric ? 'kWh/100km' : 'L/100km',
      electric,
    };
  }).filter((r) => r.distanceKm > 5);

  const combustion = perVehicle
    .filter((r) => !r.electric && r.efficiency)
    .sort((a, b) => (a.efficiency ?? 0) - (b.efficiency ?? 0));

  return {
    days, litres, fuelCost, kwh, energyCost, km,
    totalCost: fuelCost + energyCost,
    fills: fuel.length, charges: charge.length,
    avgLPer100: km > 5 ? (litres / km) * 100 : null,
    costPerKm: km > 5 ? (fuelCost + energyCost) / km : null,
    perVehicle,
    mostEfficient: combustion.slice(0, 5),
    leastEfficient: [...combustion].reverse().slice(0, 5),
  };
}

export function costSummary(store: Store, months = 12, vehicleId?: string) {
  const s = store.state;
  const since = s.now - months * 30 * DAY;
  const sinceIso = new Date(since).toISOString().slice(0, 10);
  const rows = s.costs.filter(
    (c) => c.incurredOn >= sinceIso && (!vehicleId || c.vehicleId === vehicleId));

  const byCategory: Record<string, number> = {};
  rows.forEach((c) => { byCategory[c.category] = (byCategory[c.category] ?? 0) + c.amount; });

  const vehicles = vehicleId
    ? s.vehicles.filter((v) => v.id === vehicleId) : s.vehicles;
  const depreciation = vehicles.reduce((a, v) => a + (annualDepreciation(v) * months) / 12, 0);
  if (depreciation) byCategory.depreciation = (byCategory.depreciation ?? 0) + depreciation;

  const operating = Object.values(byCategory).reduce((a, b) => a + b, 0);
  const km = s.trips
    .filter((t) => t.startedAt >= since && (!vehicleId || t.vehicleId === vehicleId))
    .reduce((a, t) => a + t.distanceKm, 0);

  const trend: Record<string, { month: string; total: number } & Record<string, number | string>> = {};
  rows.forEach((c) => {
    const key = c.incurredOn.slice(0, 7);
    if (!trend[key]) trend[key] = { month: key, total: 0 };
    trend[key][c.category] = ((trend[key][c.category] as number) ?? 0) + c.amount;
    trend[key].total += c.amount;
  });

  const acquisition = vehicles.reduce((a, v) => a + v.purchaseValue, 0);
  const book = vehicles.reduce((a, v) => a + bookValue(v, s.now), 0);

  return {
    months, byCategory, operating, distanceKm: km,
    costPerKm: km > 1 ? operating / km : null,
    costPerDay: operating / (months * 30),
    acquisition, bookValue: book,
    tco: acquisition + operating - book,
    trend: Object.values(trend).sort((a, b) => a.month.localeCompare(b.month)),
  };
}

export function vehicleCosts(store: Store, vehicleId: string, months = 12) {
  return costSummary(store, months, vehicleId);
}

export function complianceSummary(store: Store) {
  const s = store.state;
  const warn = Math.max(...s.org.settings.documentAlertDays);
  const counts = { valid: 0, expiring_soon: 0, expired: 0 };
  const horizon: Record<string, number> = {
    within_7_days: 0, within_14_days: 0, within_30_days: 0, within_90_days: 0,
  };
  s.documents.forEach((d) => {
    const st = documentStatus(d.expiryDate, s.now, warn);
    counts[st]++;
    const days = Math.round((Date.parse(d.expiryDate) - s.now) / DAY);
    if (days >= 0) {
      if (days <= 7) horizon.within_7_days++;
      if (days <= 14) horizon.within_14_days++;
      if (days <= 30) horizon.within_30_days++;
      if (days <= 90) horizon.within_90_days++;
    }
  });
  const licences = { valid: 0, expiring_soon: 0, expired: 0 };
  s.drivers.forEach((d) => { licences[documentStatus(d.licenseExpiry, s.now, warn)]++; });
  return {
    total: s.documents.length, ...counts, horizon, licences,
    complianceRate: s.documents.length
      ? Math.round((counts.valid / s.documents.length) * 1000) / 10 : 100,
  };
}

export function analytics(store: Store, days = 30) {
  const s = store.state;
  const since = s.now - days * DAY;
  const trips = s.trips.filter((t) => t.startedAt >= since);
  const tasks = s.tasks.filter((t) => t.createdAt >= since);
  const completed = tasks.filter((t) => t.status === 'completed');
  const failed = tasks.filter((t) => t.status === 'failed');
  const events = s.driverEvents.filter((e) => e.occurredAt >= since);
  const km = trips.reduce((a, t) => a + t.distanceKm, 0);
  const driveS = trips.reduce((a, t) => a + t.durationS, 0);
  const idleS = trips.reduce((a, t) => a + t.idleS, 0);

  const dayBuckets = new Map<string, {
    day: string; km: number; trips: number; tasks: number; events: number; co2: number;
  }>();
  for (let i = days - 1; i >= 0; i--) {
    const key = new Date(s.now - i * DAY).toISOString().slice(0, 10);
    dayBuckets.set(key, { day: key, km: 0, trips: 0, tasks: 0, events: 0, co2: 0 });
  }
  trips.forEach((t) => {
    const key = new Date(t.startedAt).toISOString().slice(0, 10);
    const b = dayBuckets.get(key);
    if (b) { b.km += t.distanceKm; b.trips++; b.co2 += t.co2Kg; }
  });
  completed.forEach((t) => {
    const key = new Date(t.completedAt ?? t.createdAt).toISOString().slice(0, 10);
    const b = dayBuckets.get(key);
    if (b) b.tasks++;
  });
  events.forEach((e) => {
    const key = new Date(e.occurredAt).toISOString().slice(0, 10);
    const b = dayBuckets.get(key);
    if (b) b.events++;
  });

  const eventCounts: Record<string, number> = {};
  events.forEach((e) => { eventCounts[e.kind] = (eventCounts[e.kind] ?? 0) + 1; });

  // How many days the fleet actually operated in this window. Using calendar days
  // would punish every vehicle for Sundays, which nobody works.
  const operatingDays = new Set(
    trips.map((t) => new Date(t.startedAt).toISOString().slice(0, 10))).size || 1;

  const activeVehicles = s.vehicles.filter((v) => v.lifecycle !== 'retired');
  const utilisation = activeVehicles.map((v) => {
    const vTrips = trips.filter((t) => t.vehicleId === v.id);
    const drivingS = vTrips.reduce((a, t) => a + t.durationS, 0);

    // Utilisation is on-duty time, not driving time. A last-mile vehicle spends
    // most of its shift parked at a drop; counting only the driving minutes would
    // report 3% for a van that was out on the road for eight hours.
    const perDay = new Map<string, { first: number; last: number }>();
    vTrips.forEach((t) => {
      const key = new Date(t.startedAt).toISOString().slice(0, 10);
      const b = perDay.get(key) ?? { first: t.startedAt, last: t.endedAt ?? t.startedAt };
      b.first = Math.min(b.first, t.startedAt);
      b.last = Math.max(b.last, t.endedAt ?? t.startedAt);
      perDay.set(key, b);
    });
    const dutyS = [...perDay.values()].reduce(
      (a, d) => a + Math.min(12 * 3600, (d.last - d.first) / 1000), 0);

    return {
      vehicle: v,
      distanceKm: vTrips.reduce((a, t) => a + t.distanceKm, 0),
      trips: vTrips.length,
      hours: drivingS / 3600,
      dutyHours: dutyS / 3600,
      daysWorked: perDay.size,
      // a 10-hour operating day, on each day the fleet actually ran
      utilisationPct: Math.min(100, Math.round((dutyS / (operatingDays * 10 * 3600)) * 100)),
    };
  }).sort((a, b) => b.utilisationPct - a.utilisationPct);

  const slaTotal = completed.filter((t) => t.slaDueAt).length;
  const slaMet = completed.filter((t) => t.slaState === 'met').length;

  return {
    days,
    distanceKm: km,
    trips: trips.length,
    drivingHours: driveS / 3600,
    idleHours: idleS / 3600,
    idleSharePct: driveS ? (idleS / driveS) * 100 : 0,
    avgSpeedKph: driveS ? km / (driveS / 3600) : 0,
    tasksCreated: tasks.length,
    tasksCompleted: completed.length,
    tasksFailed: failed.length,
    completionRate: tasks.length ? (completed.length / tasks.length) * 100 : 0,
    slaCompliance: slaTotal ? (slaMet / slaTotal) * 100 : 100,
    events: events.length,
    eventCounts,
    co2Kg: trips.reduce((a, t) => a + t.co2Kg, 0),
    fuelL: trips.reduce((a, t) => a + t.fuelUsedL, 0),
    energyKwh: trips.reduce((a, t) => a + t.energyUsedKwh, 0),
    daily: [...dayBuckets.values()],
    operatingDays,
    utilisation,
    utilisationPct: utilisation.length
      ? utilisation.reduce((a, u) => a + u.utilisationPct, 0) / utilisation.length : 0,
    availabilityPct: activeVehicles.length
      ? (activeVehicles.filter((v) => v.lifecycle === 'active').length / activeVehicles.length) * 100
      : 0,
    fleetSize: activeVehicles.length,
  };
}

export function sustainability(store: Store, days = 90) {
  const s = store.state;
  const since = s.now - days * DAY;
  const trips = s.trips.filter((t) => t.startedAt >= since);
  const perVehicle = s.vehicles.map((v) => {
    const vTrips = trips.filter((t) => t.vehicleId === v.id);
    const km = vTrips.reduce((a, t) => a + t.distanceKm, 0);
    const co2 = vTrips.reduce((a, t) => a + t.co2Kg, 0);
    const dayKm = new Map<string, number>();
    vTrips.forEach((t) => {
      const key = new Date(t.startedAt).toISOString().slice(0, 10);
      dayKm.set(key, (dayKm.get(key) ?? 0) + t.distanceKm);
    });
    const dailies = [...dayKm.values()];
    const avgDaily = dailies.length ? km / dailies.length : 0;
    const maxDaily = dailies.length ? Math.max(...dailies) : 0;
    const fuelL = vTrips.reduce((a, t) => a + t.fuelUsedL, 0);
    const fuelCost = fuelL * s.org.settings.fuelPricePerLitre;
    const evKwh = km * 0.21;
    const evCost = evKwh * s.org.settings.energyPricePerKwh;
    const evCo2 = evKwh * s.org.settings.co2PerKwh;
    return {
      vehicle: v, distanceKm: km, co2Kg: co2,
      co2PerKm: km > 1 ? co2 / km : 0,
      avgDailyKm: avgDaily, maxDailyKm: maxDaily,
      tripCount: vTrips.length,
      fuelCost, evCost, evCo2Kg: evCo2,
      // a rule-based candidacy test, not a claim of machine learning
      evCandidate: v.fuelType !== 'electric' && dailies.length >= 5 &&
                   maxDaily <= s.org.settings.evCandidateDailyKm,
      savingPerYear: (fuelCost - evCost) * (365 / Math.max(1, days)),
      co2SavingPerYear: (co2 - evCo2) * (365 / Math.max(1, days)),
    };
  }).filter((r) => r.distanceKm > 0);

  const monthly = new Map<string, { month: string; co2: number; km: number }>();
  trips.forEach((t) => {
    const key = new Date(t.startedAt).toISOString().slice(0, 7);
    const b = monthly.get(key) ?? { month: key, co2: 0, km: 0 };
    b.co2 += t.co2Kg;
    b.km += t.distanceKm;
    monthly.set(key, b);
  });

  const totalCo2 = perVehicle.reduce((a, r) => a + r.co2Kg, 0);
  const totalKm = perVehicle.reduce((a, r) => a + r.distanceKm, 0);
  return {
    days, totalCo2Kg: totalCo2, totalKm,
    co2PerKm: totalKm > 1 ? totalCo2 / totalKm : 0,
    co2PerTrip: trips.length ? totalCo2 / trips.length : 0,
    perVehicle: perVehicle.sort((a, b) => b.co2Kg - a.co2Kg),
    candidates: perVehicle.filter((r) => r.evCandidate)
      .sort((a, b) => b.savingPerYear - a.savingPerYear),
    monthly: [...monthly.values()].sort((a, b) => a.month.localeCompare(b.month)),
    evShare: s.vehicles.length
      ? (s.vehicles.filter((v) => v.fuelType === 'electric').length / s.vehicles.length) * 100 : 0,
  };
}

export function leaderboard(store: Store) {
  const s = store.state;
  const monthStart = new Date(s.now);
  monthStart.setUTCDate(1);
  monthStart.setUTCHours(0, 0, 0, 0);
  const from = monthStart.getTime();
  return s.drivers.map((d) => {
    const km = s.trips
      .filter((t) => t.driverId === d.id && t.startedAt >= from)
      .reduce((a, t) => a + t.distanceKm, 0);
    const events = s.driverEvents.filter(
      (e) => e.driverId === d.id && e.occurredAt >= from &&
             ['overspeed', 'harsh_braking', 'harsh_acceleration', 'harsh_cornering']
               .includes(e.kind)).length;
    return {
      driver: d, distanceKm: km, events,
      trend: Math.round((d.safetyScore - d.previousSafetyScore) * 10) / 10,
      badges: s.badges.filter((b) => b.driverId === d.id).length,
    };
  }).sort((a, b) => b.driver.safetyScore - a.driver.safetyScore ||
                    b.driver.points - a.driver.points)
    .map((r, i) => ({ ...r, rank: i + 1 }));
}

export function openAlertsFor(store: Store, filter: Partial<{
  vehicleId: string; driverId: string; taskId: string;
}>): Alert[] {
  return store.state.alerts.filter((a) => isOpen(a) &&
    (!filter.vehicleId || a.vehicleId === filter.vehicleId) &&
    (!filter.driverId || a.driverId === filter.driverId) &&
    (!filter.taskId || a.taskId === filter.taskId));
}

export function taskSlaLabel(store: Store, t: Task): string {
  const mins = slaMinutesRemaining(t, store.state.now);
  if (mins == null) return 'No SLA';
  if (t.status === 'completed') return t.slaState === 'met' ? 'Met' : 'Breached';
  if (mins < 0) return `${Math.abs(mins)} min over`;
  return `${mins} min left`;
}
