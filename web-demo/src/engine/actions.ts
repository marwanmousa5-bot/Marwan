// Every user action in FleetBeat. Each one changes real state, writes a
// timeline entry and an audit record, and ripples to the modules that care.

import { raiseAlert } from './alerts';
import { describeDue, maintenanceStatus, safetyScore, slaState } from './derive';
import { haversine } from './geo';
import { optimiseStops, routeProgress } from './router';
import type { Store } from './store';
import type {
  Alert, Driver, FleetDocument, Incident, MaintenanceSchedule, OrgSettings, Place,
  Role, Route, RouteStop, Task, TaskStatus, Vehicle, WorkOrder, WorkOrderStatus,
} from './types';

const MIN = 60000;
const HOUR = 3600000;
const DAY = 86400000;

export class ActionError extends Error {
  constructor(message: string, readonly hint?: string, readonly payload?: unknown) {
    super(message);
  }
}

// --------------------------------------------------------------------------
// Tasks
// --------------------------------------------------------------------------
export const TASK_FLOW: Record<TaskStatus, TaskStatus[]> = {
  unassigned: ['assigned', 'cancelled'],
  assigned: ['accepted', 'unassigned', 'cancelled', 'delayed', 'failed'],
  accepted: ['en_route', 'unassigned', 'cancelled', 'delayed', 'failed'],
  en_route: ['arrived', 'delayed', 'failed', 'cancelled'],
  arrived: ['in_progress', 'failed', 'delayed', 'cancelled'],
  in_progress: ['completed', 'failed', 'delayed'],
  delayed: ['en_route', 'arrived', 'in_progress', 'completed', 'failed', 'cancelled', 'unassigned'],
  completed: [],
  failed: ['unassigned', 'assigned'],
  cancelled: [],
};

const STAMP: Partial<Record<TaskStatus, keyof Task>> = {
  assigned: 'assignedAt', accepted: 'acceptedAt', en_route: 'startedAt',
  arrived: 'arrivedAt', completed: 'completedAt', cancelled: 'cancelledAt',
  failed: 'failedAt',
};

export function assignmentPreview(
  store: Store, task: Task, driver?: Driver, vehicle?: Vehicle,
) {
  const s = store.state;
  const now = s.now;
  const conflicts: { type: string; message: string; taskId?: string }[] = [];
  const warnings: string[] = [];
  let workload = null;

  if (driver) {
    const active = s.tasks.filter(
      (t) => t.driverId === driver.id && t.id !== task.id &&
             ['assigned', 'accepted', 'en_route', 'arrived', 'in_progress', 'delayed']
               .includes(t.status));
    const late = active.filter((t) => t.slaState === 'at_risk' || t.slaState === 'breached');
    workload = {
      driver: driver.fullName, status: driver.status,
      activeTasks: active.length, lateTasks: late.length,
      dutyHoursToday: Math.round(driver.dutyHoursToday * 10) / 10,
      loadPct: Math.min(100, Math.round((active.length / 6) * 100)),
    };
    if (driver.status === 'off_duty' || driver.status === 'unavailable') {
      warnings.push(`${driver.fullName} is currently ${driver.status.replace('_', ' ')}.`);
    }
    if (driver.dutyHoursToday >= 9) {
      warnings.push(`${driver.fullName} has driven ${driver.dutyHoursToday.toFixed(1)} h today — fatigue risk is high.`);
    }
    if (task.scheduledFor) {
      active.forEach((other) => {
        if (!other.scheduledFor) return;
        const gapMin = Math.abs(other.scheduledFor - task.scheduledFor!) / MIN;
        if (gapMin < 30) {
          conflicts.push({
            type: 'schedule_overlap', taskId: other.id,
            message: `${driver.fullName} already has ${other.reference} scheduled at ` +
                     `${new Date(other.scheduledFor).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}.`,
          });
        }
      });
    }
  }

  let eta: number | null = null;
  let routeImpact: { distanceKm: number; durationMin: number; via: string[] } | null = null;
  if (vehicle) {
    if (vehicle.lifecycle !== 'active') {
      warnings.push(`${vehicle.name} is ${vehicle.lifecycle} and not available for work.`);
    }
    if (vehicle.lat != null && task.lat != null) {
      const r = store.graph.route([[vehicle.lon!, vehicle.lat], [task.lon, task.lat]]);
      if (r.ok) {
        eta = now + r.durationS * 1000;
        routeImpact = {
          distanceKm: Math.round((r.distanceM / 1000) * 100) / 100,
          durationMin: Math.round(r.durationS / 60),
          via: r.streets.slice(0, 4),
        };
      } else warnings.push(r.message);
    }
    if (driver && vehicle.driverId && vehicle.driverId !== driver.id) {
      conflicts.push({
        type: 'vehicle_driver_mismatch',
        message: `${vehicle.name} is currently assigned to a different driver. Assigning will reassign the vehicle.`,
      });
    }
  }

  let sla = null;
  if (task.slaDueAt && eta) {
    const marginMin = Math.round((task.slaDueAt - eta) / MIN);
    sla = { marginMin, state: marginMin < 0 ? 'breached' : marginMin < 15 ? 'at_risk' : 'on_track' };
    if (marginMin < 0) {
      conflicts.push({
        type: 'sla_breach',
        message: `Projected arrival is ${Math.abs(marginMin)} minutes after the SLA deadline.`,
      });
    }
  }

  return {
    workload, eta, routeImpact, sla, conflicts, warnings,
    estimatedCompletion: eta ? eta + task.serviceMinutes * MIN : null,
    hasConflict: conflicts.length > 0,
  };
}

export function assignTask(
  store: Store, taskId: string, driverId?: string, vehicleId?: string,
): Task {
  const s = store.state;
  const task = store.task(taskId);
  if (!task) throw new ActionError('That task no longer exists.');
  if (task.status === 'completed' || task.status === 'cancelled') {
    throw new ActionError(`A ${task.status} task cannot be reassigned.`);
  }
  const driver = store.driver(driverId);
  const vehicle = store.vehicle(vehicleId);
  const previousDriver = task.driverId;
  const before = { status: task.status, driverId: task.driverId, vehicleId: task.vehicleId };

  if (!driver && !vehicle) {
    task.driverId = undefined;
    task.vehicleId = undefined;
    task.routeId = undefined;
    task.eta = undefined;
    transitionTask(store, task, 'unassigned', {
      note: 'Returned to the unassigned queue.', strict: false,
    });
    return task;
  }

  task.driverId = driver?.id;
  task.vehicleId = vehicle?.id;
  if (task.status === 'unassigned' || task.status === 'failed') {
    task.status = 'assigned';
    task.assignedAt = s.now;
  } else if (!task.assignedAt) {
    task.assignedAt = s.now;
  }

  // keep vehicle <-> driver consistent everywhere
  if (vehicle && driver && vehicle.driverId !== driver.id) {
    const previousVehicle = s.vehicles.find((v) => v.driverId === driver.id && v.id !== vehicle.id);
    if (previousVehicle) previousVehicle.driverId = undefined;
    vehicle.driverId = driver.id;
    store.timeline({
      entityType: 'vehicle', entityId: vehicle.id, action: 'driver_assigned',
      description: `${driver.fullName} assigned as driver.`,
      actorType: 'user', actorName: store.me.fullName,
      relatedType: 'driver', relatedId: driver.id,
    });
  }
  if (driver && driver.status === 'off_duty') driver.status = 'available';

  if (vehicle && vehicle.lat != null) buildTaskRoute(store, task, vehicle, driver);

  task.slaState = slaState(task, s.now, s.org.settings.slaAtRiskMinutes);

  const verb = previousDriver && previousDriver !== task.driverId ? 'reassigned' : 'assigned';
  const who = driver?.fullName ?? 'nobody';
  store.timeline({
    entityType: 'task', entityId: task.id, action: verb,
    description: `Task ${verb} to ${who}${vehicle ? ` with ${vehicle.name}` : ''}.`,
    actorType: 'user', actorName: store.me.fullName,
    relatedType: driver ? 'driver' : undefined, relatedId: driver?.id,
  });
  store.audit({
    action: `task.${verb}`, entityType: 'task', entityLabel: task.reference,
    summary: `${task.reference} ${verb} to ${who}`,
    before, after: { status: task.status, driverId: task.driverId, vehicleId: task.vehicleId },
  });
  if (driver?.userId) {
    store.notify(driver.userId, {
      kind: verb === 'reassigned' ? 'task_reassigned' : 'task_assigned',
      title: `${verb === 'reassigned' ? 'Reassigned' : 'New task'}: ${task.reference}`,
      body: `${task.title} — ${task.address}`,
      link: `driver:${task.id}`, entityType: 'task', entityId: task.id,
    });
  }
  store.emit();
  return task;
}

export function buildTaskRoute(store: Store, task: Task, vehicle: Vehicle, driver?: Driver) {
  const s = store.state;
  const r = store.graph.route([[vehicle.lon!, vehicle.lat!], [task.lon, task.lat]]);
  if (!r.ok) return;
  let route = store.route(task.routeId);
  if (!route) {
    route = {
      id: store.id('rt'), name: `Route for ${task.reference}`,
      originLat: vehicle.lat!, originLon: vehicle.lon!,
      originName: vehicle.street ?? 'Current position',
      destLat: task.lat, destLon: task.lon, destName: task.address || task.title,
      geometry: [], distanceM: 0, durationS: 0, legs: [], stops: [],
      active: true, optimized: false, avoidEdges: [],
    };
    s.routes.push(route);
    task.routeId = route.id;
  }
  route.vehicleId = vehicle.id;
  route.driverId = driver?.id;
  route.originLat = vehicle.lat!;
  route.originLon = vehicle.lon!;
  route.destLat = task.lat;
  route.destLon = task.lon;
  route.geometry = r.geometry;
  route.distanceM = r.distanceM;
  route.durationS = r.durationS;
  route.legs = r.legs.map((l) => ({ distanceM: l.distanceM, durationS: l.durationS }));
  route.active = true;
  task.eta = s.now + r.durationS * 1000;
}

export function transitionTask(
  store: Store, task: Task, target: TaskStatus,
  opts: { note?: string; strict?: boolean; actorName?: string;
          actorType?: 'user' | 'driver' | 'system'; extra?: Partial<Task> } = {},
): Task {
  const s = store.state;
  if (task.status === target) return task;
  if ((opts.strict ?? true) && !TASK_FLOW[task.status].includes(target)) {
    throw new ActionError(
      `A ${task.status.replace('_', ' ')} task cannot move to ${target.replace('_', ' ')}.`,
    );
  }
  const before = task.status;
  task.status = target;
  const stamp = STAMP[target];
  if (stamp && !task[stamp]) (task as unknown as Record<string, unknown>)[stamp] = s.now;
  Object.assign(task, opts.extra ?? {});
  task.slaState = slaState(task, s.now, s.org.settings.slaAtRiskMinutes);

  store.timeline({
    entityType: 'task', entityId: task.id, action: target,
    description: opts.note ?? `Task moved to ${target.replace('_', ' ')}.`,
    actorType: opts.actorType ?? 'user',
    actorName: opts.actorName ?? store.me.fullName,
  });
  store.audit({
    action: 'task.status_changed', entityType: 'task', entityLabel: task.reference,
    summary: `${task.reference}: ${before.replace('_', ' ')} → ${target.replace('_', ' ')}`,
    before: { status: before }, after: { status: target },
  });

  if (target === 'completed' || target === 'failed' || target === 'cancelled') {
    const route = store.route(task.routeId);
    if (route) route.active = false;
  }
  if (target === 'completed' && task.driverId) {
    const d = store.driver(task.driverId);
    if (d) {
      store.timeline({
        entityType: 'driver', entityId: d.id, action: 'task_completed',
        description: `Completed ${task.reference} — ${task.title}.`,
        actorType: 'driver', actorName: d.fullName,
        relatedType: 'task', relatedId: task.id,
      });
    }
  }
  s.lastEventAt = s.now;
  store.emit();
  return task;
}

export function createTask(store: Store, input: {
  title: string; kind: Task['kind']; priority: Task['priority'];
  customerId?: string; placeId?: string; lat?: number; lon?: number; address?: string;
  contactName?: string; contactPhone?: string;
  driverId?: string; vehicleId?: string;
  scheduledFor?: number; slaMinutes?: number; serviceMinutes?: number;
  instructions?: string; description?: string;
  stops?: { name: string; lat: number; lon: number; serviceMinutes: number }[];
}): Task {
  const s = store.state;
  let lat = input.lat;
  let lon = input.lon;
  let address = input.address;
  let contactName = input.contactName;
  let contactPhone = input.contactPhone;

  if (input.customerId) {
    const c = store.customer(input.customerId);
    const p = store.place(c?.placeId);
    if (p) { lat = lat ?? p.lat; lon = lon ?? p.lon; address = address ?? p.address; }
    contactName = contactName ?? c?.contactName;
    contactPhone = contactPhone ?? c?.contactPhone;
  } else if (input.placeId) {
    const p = store.place(input.placeId);
    if (p) { lat = lat ?? p.lat; lon = lon ?? p.lon; address = address ?? p.address ?? p.name; }
  }
  if (lat == null || lon == null) {
    throw new ActionError(
      'A task needs a destination.',
      'Pick a customer, a saved place, or a point on the map.',
    );
  }

  const scheduledFor = input.scheduledFor ?? s.now + 30 * MIN;
  const slaMinutes = input.slaMinutes ?? 120;
  const task: Task = {
    id: store.id('tk'), reference: `TSK-${1000 + store.seq('task')}`,
    title: input.title, description: input.description,
    kind: input.kind, status: 'unassigned', priority: input.priority,
    customerId: input.customerId, placeId: input.placeId,
    address: address ?? 'Helsinki', lat, lon,
    contactName, contactPhone,
    scheduledFor, windowStart: scheduledFor - 20 * MIN, windowEnd: scheduledFor + 50 * MIN,
    slaDueAt: scheduledFor + slaMinutes * MIN, slaMinutes, slaState: 'on_track',
    serviceMinutes: input.serviceMinutes ?? 10,
    instructions: input.instructions,
    createdAt: s.now,
  };
  s.tasks.push(task);

  if (input.stops?.length) {
    const route: Route = {
      id: store.id('rt'), name: `Route for ${task.reference}`,
      originLat: input.stops[0].lat, originLon: input.stops[0].lon,
      originName: input.stops[0].name,
      destLat: lat, destLon: lon, destName: address ?? task.title,
      geometry: [], distanceM: 0, durationS: 0, legs: [],
      stops: input.stops.map((st, i): RouteStop => ({
        id: store.id('rs'), sequence: i + 1, name: st.name, lat: st.lat, lon: st.lon,
        kind: 'delivery', serviceMinutes: st.serviceMinutes, taskId: task.id,
      })),
      active: false, optimized: false, avoidEdges: [],
    };
    s.routes.push(route);
    task.routeId = route.id;
    recalculateRoute(store, route);
  }

  store.timeline({
    entityType: 'task', entityId: task.id, action: 'created',
    description: `Task created — ${task.title}.`,
    actorType: 'user', actorName: store.me.fullName,
  });
  store.audit({
    action: 'task.created', entityType: 'task', entityLabel: task.reference,
    summary: `${task.reference} created: ${task.title}`,
  });

  if (input.driverId || input.vehicleId) {
    assignTask(store, task.id, input.driverId, input.vehicleId);
  }
  store.emit();
  return task;
}

export function cancelTask(store: Store, taskId: string, reason: string): Task {
  const task = store.task(taskId);
  if (!task) throw new ActionError('That task no longer exists.');
  if (task.status === 'completed') {
    throw new ActionError('A completed task cannot be cancelled.');
  }
  return transitionTask(store, task, 'cancelled', {
    note: `Cancelled: ${reason}`, strict: false, extra: { cancelReason: reason },
  });
}

export function completeTaskWithPod(store: Store, taskId: string, pod: {
  recipient: string; notes?: string; signature?: string; photo?: string;
}): Task {
  const s = store.state;
  const task = store.task(taskId);
  if (!task) throw new ActionError('That task no longer exists.');
  const vehicle = store.vehicle(task.vehicleId);
  task.pod = {
    recipient: pod.recipient, notes: pod.notes, signature: pod.signature, photo: pod.photo,
    lat: vehicle?.lat ?? task.lat, lon: vehicle?.lon ?? task.lon, at: s.now,
  };
  transitionTask(store, task, 'completed', {
    note: `Completed — proof of delivery captured for ${pod.recipient}.`,
    strict: false, actorType: 'driver',
    actorName: store.driver(task.driverId)?.fullName ?? 'Driver',
  });
  return task;
}

export function failTask(
  store: Store, taskId: string, reason: string, note?: string,
): Task {
  const s = store.state;
  const task = store.task(taskId);
  if (!task) throw new ActionError('That task no longer exists.');
  transitionTask(store, task, 'failed', {
    note: `Marked failed — ${reason.replace(/_/g, ' ')}${note ? `: ${note}` : ''}.`,
    strict: false, actorType: 'driver',
    actorName: store.driver(task.driverId)?.fullName ?? 'Driver',
    extra: { failureReason: reason, failureNote: note },
  });
  raiseAlert(store, {
    code: 'task_delayed', severity: 'high',
    title: `${task.reference} failed — ${reason.replace(/_/g, ' ')}`,
    detail: note ?? `${task.title} could not be completed.`,
    vehicleId: task.vehicleId, driverId: task.driverId, taskId: task.id,
    lat: task.lat, lon: task.lon, dedupeExtra: `fail:${task.id}`,
    evidence: { reason, note },
  });
  s.lastEventAt = s.now;
  return task;
}

/** ETA + SLA refresh for every live task. Raises an alert on the first bad turn. */
export function refreshSlas(store: Store) {
  const s = store.state;
  s.tasks.forEach((t) => {
    if (!['assigned', 'accepted', 'en_route', 'arrived', 'in_progress', 'delayed']
          .includes(t.status)) return;
    const vehicle = store.vehicle(t.vehicleId);
    const route = store.route(t.routeId);
    if (vehicle?.lat != null && route?.geometry.length) {
      const p = routeProgress(route.geometry, vehicle.lat, vehicle.lon!);
      const planned = route.distanceM > 0 && route.durationS > 0
        ? route.distanceM / route.durationS : 8;
      const live = (vehicle.speedKph ?? 0) / 3.6;
      const effective = live > 1 ? Math.max(2, 0.7 * planned + 0.3 * live) : planned;
      t.eta = s.now + (p.remainingM / Math.max(effective, 1)) * 1000;
    }
    const before = t.slaState;
    t.slaState = slaState(t, s.now, s.org.settings.slaAtRiskMinutes);
    if (t.slaState !== before && (t.slaState === 'at_risk' || t.slaState === 'breached')) {
      raiseAlert(store, {
        code: t.slaState === 'at_risk' ? 'sla_breach_risk' : 'task_delayed',
        severity: t.slaState === 'at_risk' ? 'high' : 'critical',
        title: `${t.reference} SLA ${t.slaState === 'at_risk' ? 'at risk' : 'breached'}`,
        detail: `${t.title} — projected arrival ${fmtTime(t.eta)}, deadline ${fmtTime(t.slaDueAt)}.`,
        vehicleId: t.vehicleId, driverId: t.driverId, taskId: t.id,
        lat: t.lat, lon: t.lon, dedupeExtra: `task:${t.id}`,
        evidence: { eta: t.eta, slaDueAt: t.slaDueAt },
      });
      store.timeline({
        entityType: 'task', entityId: t.id, action: 'sla_changed',
        description: `Task marked ${t.slaState.replace('_', ' ')}.` +
                     (t.eta ? ` ETA moved to ${fmtTime(t.eta)}.` : ''),
      });
    }
  });
}

function fmtTime(ts?: number): string {
  if (!ts) return 'unknown';
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// --------------------------------------------------------------------------
// Alerts
// --------------------------------------------------------------------------
export function acknowledgeAlert(store: Store, alertId: string, note?: string): Alert {
  const a = store.alert(alertId);
  if (!a) throw new ActionError('That alert no longer exists.');
  if (a.status === 'resolved') throw new ActionError('This alert is already resolved.');
  a.status = 'acknowledged';
  a.acknowledgedAt = store.state.now;
  a.acknowledgedBy = store.me.id;
  lifecycleAlert(store, a, 'acknowledged',
    `Acknowledged by ${store.me.fullName}.${note ? ' ' + note : ''}`);
  return a;
}

export function assignAlert(store: Store, alertId: string, userId: string): Alert {
  const a = store.alert(alertId);
  if (!a) throw new ActionError('That alert no longer exists.');
  const u = store.user(userId);
  if (!u) throw new ActionError('That user is not in your organization.');
  a.assignedTo = u.id;
  if (a.status === 'triggered') a.status = 'investigating';
  lifecycleAlert(store, a, 'assigned', `Assigned to ${u.fullName} by ${store.me.fullName}.`);
  store.notify(u.id, {
    kind: 'urgent_alert', title: `Assigned to you: ${a.title}`,
    body: a.detail, link: `alerts:${a.id}`, entityType: 'alert', entityId: a.id,
  });
  return a;
}

export function snoozeAlert(store: Store, alertId: string, minutes: number): Alert {
  const a = store.alert(alertId);
  if (!a) throw new ActionError('That alert no longer exists.');
  if (a.severity === 'critical') {
    throw new ActionError('Critical alerts cannot be snoozed.',
                          'Acknowledge it, or resolve it with a note.');
  }
  a.status = 'snoozed';
  a.snoozedUntil = store.state.now + minutes * MIN;
  lifecycleAlert(store, a, 'snoozed',
    `Snoozed for ${minutes} minutes by ${store.me.fullName}.`);
  return a;
}

export function escalateAlert(store: Store, alertId: string, note?: string): Alert {
  const a = store.alert(alertId);
  if (!a) throw new ActionError('That alert no longer exists.');
  a.status = 'escalated';
  a.escalatedAt = store.state.now;
  a.escalationLevel += 1;
  lifecycleAlert(store, a, 'escalated',
    `Escalated to level ${a.escalationLevel} by ${store.me.fullName}.${note ? ' ' + note : ''}`);
  return a;
}

export function resolveAlert(store: Store, alertId: string, note: string): Alert {
  const a = store.alert(alertId);
  if (!a) throw new ActionError('That alert no longer exists.');
  if (a.status === 'resolved') throw new ActionError('This alert is already resolved.');
  if (!note.trim()) throw new ActionError('A resolution note is required.');
  a.status = 'resolved';
  a.resolvedAt = store.state.now;
  a.resolvedBy = store.me.id;
  a.resolutionNote = note;
  lifecycleAlert(store, a, 'resolved', `Resolved by ${store.me.fullName}: ${note}`);
  return a;
}

function lifecycleAlert(store: Store, a: Alert, action: string, description: string) {
  store.timeline({
    entityType: 'alert', entityId: a.id, action, description,
    actorType: 'user', actorName: store.me.fullName,
  });
  store.audit({
    action: `alert.${action}`, entityType: 'alert', entityLabel: a.title,
    summary: description,
  });
  store.emit();
}

export function bulkAlertAction(store: Store, ids: string[], action: {
  kind: 'acknowledge' | 'assign' | 'snooze' | 'resolve';
  userId?: string; minutes?: number; note?: string; confirmCritical?: boolean;
}): { updated: number; skipped: number } {
  const alerts = store.state.alerts.filter((a) => ids.includes(a.id));
  const criticals = alerts.filter((a) => a.severity === 'critical');
  if (action.kind === 'resolve' && criticals.length && !action.confirmCritical) {
    throw new ActionError(
      `${criticals.length} of these alerts are critical.`,
      'Confirm explicitly to resolve critical alerts in bulk.',
      { criticalCount: criticals.length },
    );
  }
  if (action.kind === 'resolve' && !action.note?.trim()) {
    throw new ActionError('A resolution note is required.');
  }
  let updated = 0;
  alerts.forEach((a) => {
    try {
      if (action.kind === 'acknowledge') acknowledgeAlert(store, a.id);
      else if (action.kind === 'assign') assignAlert(store, a.id, action.userId!);
      else if (action.kind === 'snooze') snoozeAlert(store, a.id, action.minutes ?? 60);
      else resolveAlert(store, a.id, action.note!);
      updated++;
    } catch { /* skipped — e.g. a critical alert cannot be snoozed */ }
  });
  store.audit({
    action: `alert.bulk_${action.kind}`,
    summary: `${updated} alerts ${action.kind}d in bulk`,
  });
  return { updated, skipped: alerts.length - updated };
}

// --------------------------------------------------------------------------
// Routes
// --------------------------------------------------------------------------
export function recalculateRoute(store: Store, route: Route): {
  ok: boolean; message: string; deltaM: number; deltaS: number;
} {
  const beforeM = route.distanceM;
  const beforeS = route.durationS;
  const waypoints: [number, number][] = [
    [route.originLon, route.originLat],
    ...route.stops.sort((a, b) => a.sequence - b.sequence).map((s) => [s.lon, s.lat] as [number, number]),
    [route.destLon, route.destLat],
  ];
  const r = store.graph.route(waypoints, route.avoidEdges);
  if (!r.ok) return { ok: false, message: r.message, deltaM: 0, deltaS: 0 };
  route.geometry = r.geometry;
  route.distanceM = r.distanceM;
  route.durationS = r.durationS;
  route.legs = r.legs.map((l) => ({ distanceM: l.distanceM, durationS: l.durationS }));
  projectStopTimes(store, route);
  store.emit();
  return {
    ok: true, message: '',
    deltaM: r.distanceM - beforeM,
    deltaS: r.durationS - beforeS,
  };
}

function projectStopTimes(store: Store, route: Route) {
  let clock = route.startedAt ?? store.state.now;
  route.stops.sort((a, b) => a.sequence - b.sequence).forEach((stop, i) => {
    clock += (route.legs[i]?.durationS ?? 0) * 1000;
    stop.plannedArrival = clock;
    clock += stop.serviceMinutes * MIN;
  });
}

export function addStop(store: Store, routeId: string, stop: {
  name: string; lat: number; lon: number; serviceMinutes?: number; index?: number;
}) {
  const route = store.route(routeId);
  if (!route) throw new ActionError('That route no longer exists.');
  const newStop: RouteStop = {
    id: store.id('rs'), sequence: route.stops.length + 1, name: stop.name,
    lat: stop.lat, lon: stop.lon, kind: 'waypoint',
    serviceMinutes: stop.serviceMinutes ?? 5,
  };
  if (stop.index != null) route.stops.splice(stop.index, 0, newStop);
  else route.stops.push(newStop);
  resequence(route);
  const delta = recalculateRoute(store, route);
  store.audit({
    action: 'route.stop_added', entityType: 'route', entityLabel: route.name,
    summary: `Stop “${stop.name}” added to ${route.name}`,
  });
  return delta;
}

export function removeStop(store: Store, routeId: string, stopId: string) {
  const route = store.route(routeId);
  if (!route) throw new ActionError('That route no longer exists.');
  const idx = route.stops.findIndex((s) => s.id === stopId);
  if (idx < 0) throw new ActionError('That stop is not on this route.');
  const [removed] = route.stops.splice(idx, 1);
  resequence(route);
  const delta = recalculateRoute(store, route);
  store.audit({
    action: 'route.stop_removed', entityType: 'route', entityLabel: route.name,
    summary: `Stop “${removed.name}” removed from ${route.name}`,
  });
  return delta;
}

export function moveStop(store: Store, routeId: string, from: number, to: number) {
  const route = store.route(routeId);
  if (!route) throw new ActionError('That route no longer exists.');
  const stops = route.stops.sort((a, b) => a.sequence - b.sequence);
  const [moved] = stops.splice(from, 1);
  stops.splice(to, 0, moved);
  route.stops = stops;
  resequence(route);
  return recalculateRoute(store, route);
}

function resequence(route: Route) {
  route.stops.forEach((s, i) => { s.sequence = i + 1; });
}

export function previewOptimisation(store: Store, routeId: string) {
  const route = store.route(routeId);
  if (!route) throw new ActionError('That route no longer exists.');
  if (route.stops.length < 2) {
    throw new ActionError('Add at least two stops before optimising.');
  }
  const result = optimiseStops(
    store.graph, [route.originLon, route.originLat],
    route.stops.map((s) => ({ lon: s.lon, lat: s.lat })),
    [route.destLon, route.destLat],
  );
  return {
    ...result,
    beforeKm: route.distanceM / 1000,
    order: result.order,
    stops: result.order.map((i) => route.stops[i]),
  };
}

export function applyOptimisation(store: Store, routeId: string, order: number[]) {
  const route = store.route(routeId);
  if (!route) throw new ActionError('That route no longer exists.');
  const sorted = route.stops.sort((a, b) => a.sequence - b.sequence);
  route.stops = order.map((i) => sorted[i]);
  resequence(route);
  route.optimized = true;
  const delta = recalculateRoute(store, route);
  store.timeline({
    entityType: 'route', entityId: route.id, action: 'optimised',
    description: `Stop order optimised — ${fmtDelta(delta.deltaM, delta.deltaS)}.`,
    actorType: 'user', actorName: store.me.fullName,
  });
  store.audit({
    action: 'route.optimised', entityType: 'route', entityLabel: route.name,
    summary: `${route.name} optimised (${fmtDelta(delta.deltaM, delta.deltaS)})`,
  });
  return delta;
}

export function fmtDelta(deltaM: number, deltaS: number): string {
  const km = deltaM / 1000;
  const min = deltaS / 60;
  const kmStr = `${km >= 0 ? '+' : ''}${km.toFixed(1)} km`;
  const minStr = `${min >= 0 ? '+' : ''}${Math.round(min)} min`;
  return `${kmStr}, ${minStr}`;
}

export function avoidEdgeUnderPoint(store: Store, routeId: string, lon: number, lat: number) {
  const route = store.route(routeId);
  if (!route) throw new ActionError('That route no longer exists.');
  const snapped = store.graph.snap(lon, lat);
  if (snapped.edge < 0) throw new ActionError('No road found at that point.');
  const edge = store.graph.edges[snapped.edge];
  // avoid both directions of the same way
  const ids = store.graph.edges
    .map((e, i) => ({ e, i }))
    .filter(({ e }) => e.name && e.name === edge.name &&
            haversine(e.geom[0][0], e.geom[0][1], lon, lat) < 260)
    .map(({ i }) => i);
  route.avoidEdges = [...new Set([...route.avoidEdges, ...ids])];
  const delta = recalculateRoute(store, route);
  if (!delta.ok) {
    route.avoidEdges = route.avoidEdges.filter((i) => !ids.includes(i));
    recalculateRoute(store, route);
    throw new ActionError(
      `Avoiding ${edge.name || 'that road'} leaves no drivable route.`,
      'The original route has been kept.',
    );
  }
  store.timeline({
    entityType: 'route', entityId: route.id, action: 'avoid_road',
    description: `${edge.name || 'A road'} excluded — ${fmtDelta(delta.deltaM, delta.deltaS)}.`,
    actorType: 'user', actorName: store.me.fullName,
  });
  return { ...delta, road: edge.name || 'that road' };
}

// --------------------------------------------------------------------------
// Vehicles & drivers
// --------------------------------------------------------------------------
export function assignDriverToVehicle(
  store: Store, vehicleId: string, driverId?: string,
): { tasksUpdated: number } {
  const s = store.state;
  const vehicle = store.vehicle(vehicleId);
  if (!vehicle) throw new ActionError('That vehicle no longer exists.');
  const previous = store.driver(vehicle.driverId);
  const driver = store.driver(driverId);

  if (driver) {
    const other = s.vehicles.find((v) => v.driverId === driver.id && v.id !== vehicle.id);
    if (other) {
      other.driverId = undefined;
      store.timeline({
        entityType: 'vehicle', entityId: other.id, action: 'driver_unassigned',
        description: `${driver.fullName} moved to ${vehicle.name}.`,
        actorType: 'user', actorName: store.me.fullName,
      });
    }
  }
  vehicle.driverId = driver?.id;

  const affected = s.tasks.filter(
    (t) => t.vehicleId === vehicle.id &&
           ['assigned', 'accepted', 'en_route', 'arrived', 'in_progress', 'delayed']
             .includes(t.status));
  affected.forEach((t) => {
    t.driverId = driver?.id;
    store.timeline({
      entityType: 'task', entityId: t.id, action: 'driver_changed',
      description: `Driver changed to ${driver?.fullName ?? 'unassigned'} with the vehicle.`,
      actorType: 'user', actorName: store.me.fullName,
    });
  });

  const who = driver?.fullName ?? 'nobody';
  store.audit({
    action: 'vehicle.driver_assigned', entityType: 'vehicle', entityLabel: vehicle.name,
    summary: `${vehicle.name} assigned to ${who}`,
    before: { driver: previous?.fullName ?? null }, after: { driver: who },
  });
  store.timeline({
    entityType: 'vehicle', entityId: vehicle.id, action: 'driver_assigned',
    description: `Driver set to ${who}.`, actorType: 'user', actorName: store.me.fullName,
    relatedType: driver ? 'driver' : undefined, relatedId: driver?.id,
  });
  if (driver) {
    store.timeline({
      entityType: 'driver', entityId: driver.id, action: 'vehicle_assigned',
      description: `Assigned to ${vehicle.name} (${vehicle.plate}).`,
      actorType: 'user', actorName: store.me.fullName,
      relatedType: 'vehicle', relatedId: vehicle.id,
    });
    if (driver.status === 'off_duty') driver.status = 'available';
  }
  if (previous && previous.id !== driver?.id) {
    store.timeline({
      entityType: 'driver', entityId: previous.id, action: 'vehicle_unassigned',
      description: `No longer assigned to ${vehicle.name}.`,
      actorType: 'user', actorName: store.me.fullName,
    });
  }
  store.emit();
  return { tasksUpdated: affected.length };
}

export function retireVehicle(store: Store, vehicleId: string, reason: string) {
  const s = store.state;
  const v = store.vehicle(vehicleId);
  if (!v) throw new ActionError('That vehicle no longer exists.');
  const active = s.tasks.filter(
    (t) => t.vehicleId === v.id &&
           ['assigned', 'accepted', 'en_route', 'arrived', 'in_progress', 'delayed']
             .includes(t.status));
  if (active.length) {
    throw new ActionError(
      `${v.name} still has ${active.length} active task${active.length === 1 ? '' : 's'}.`,
      'Reassign or complete them before retiring the vehicle.',
    );
  }
  v.lifecycle = 'retired';
  v.retiredAt = s.now;
  v.driverId = undefined;
  v.ignitionOn = false;
  v.speedKph = 0;
  store.audit({
    action: 'vehicle.retired', entityType: 'vehicle', entityLabel: v.name,
    summary: `${v.name} retired`, after: { reason },
  });
  store.timeline({
    entityType: 'vehicle', entityId: v.id, action: 'retired',
    description: `Vehicle retired.${reason ? ` Reason: ${reason}` : ''}`,
    actorType: 'user', actorName: store.me.fullName,
  });
  store.emit();
}

export function updateVehicle(store: Store, vehicleId: string, changes: Partial<Vehicle>) {
  const v = store.vehicle(vehicleId);
  if (!v) throw new ActionError('That vehicle no longer exists.');
  const keys = Object.keys(changes) as (keyof Vehicle)[];
  const before: Record<string, unknown> = {};
  keys.forEach((k) => { before[k] = v[k]; });
  Object.assign(v, changes);
  store.audit({
    action: 'vehicle.updated', entityType: 'vehicle', entityLabel: v.name,
    summary: `${v.name} updated: ${keys.join(', ')}`,
    before, after: changes as Record<string, unknown>,
  });
  store.timeline({
    entityType: 'vehicle', entityId: v.id, action: 'updated',
    description: `Vehicle details updated: ${keys.map((k) => String(k).replace(/([A-Z])/g, ' $1').toLowerCase()).join(', ')}.`,
    actorType: 'user', actorName: store.me.fullName,
  });
  store.emit();
}

export function createVehicle(store: Store, input: Partial<Vehicle> & {
  name: string; plate: string;
}): Vehicle {
  const s = store.state;
  if (s.vehicles.some((v) => v.plate.toLowerCase() === input.plate.toLowerCase())) {
    throw new ActionError(`A vehicle with plate ${input.plate} already exists.`);
  }
  const v: Vehicle = {
    id: store.id('vh'), name: input.name, plate: input.plate,
    vin: input.vin ?? '', type: input.type ?? 'van', make: input.make ?? '',
    model: input.model ?? '', year: input.year ?? new Date(s.now).getFullYear(),
    colour: input.colour ?? 'White', fuelType: input.fuelType ?? 'diesel',
    lifecycle: 'active', odometerKm: input.odometerKm ?? 0,
    tankCapacityL: input.tankCapacityL, avgConsumption: input.avgConsumption,
    batteryCapacityKwh: input.batteryCapacityKwh,
    stateOfChargePct: input.batteryCapacityKwh ? 100 : undefined,
    ownership: input.ownership ?? 'owned',
    purchaseDate: input.purchaseDate ?? new Date(s.now).toISOString().slice(0, 10),
    purchaseValue: input.purchaseValue ?? 0, residualValue: input.residualValue ?? 0,
    depreciationYears: input.depreciationYears ?? 7,
    annualInsurance: input.annualInsurance ?? 0,
    annualRegistration: input.annualRegistration ?? 0,
    heading: 0, speedKph: 0, satellites: 0, ignitionOn: false,
    driverId: input.driverId,
  };
  s.vehicles.push(v);
  store.audit({
    action: 'vehicle.created', entityType: 'vehicle', entityLabel: v.name,
    summary: `Vehicle ${v.name} (${v.plate}) added`,
  });
  store.timeline({
    entityType: 'vehicle', entityId: v.id, action: 'created',
    description: `${v.name} added to the fleet.`,
    actorType: 'user', actorName: store.me.fullName,
  });
  store.emit();
  return v;
}

export function setDriverStatus(store: Store, driverId: string, status: Driver['status']) {
  const d = store.driver(driverId);
  if (!d) throw new ActionError('That driver no longer exists.');
  const before = d.status;
  d.status = status;
  store.audit({
    action: 'driver.status_changed', entityType: 'driver', entityLabel: d.fullName,
    summary: `${d.fullName}: ${before.replace('_', ' ')} → ${status.replace('_', ' ')}`,
    before: { status: before }, after: { status },
  });
  store.timeline({
    entityType: 'driver', entityId: d.id, action: 'status_changed',
    description: `Status changed to ${status.replace('_', ' ')}.`,
    actorType: 'user', actorName: store.me.fullName,
  });
  store.emit();
}

// --------------------------------------------------------------------------
// Maintenance
// --------------------------------------------------------------------------
export const WO_FLOW: Record<WorkOrderStatus, WorkOrderStatus[]> = {
  requested: ['approved', 'cancelled'],
  approved: ['scheduled', 'cancelled'],
  scheduled: ['in_progress', 'cancelled'],
  in_progress: ['waiting_for_parts', 'completed', 'cancelled'],
  waiting_for_parts: ['in_progress', 'cancelled'],
  completed: [],
  cancelled: [],
};

export function maintenanceImpact(
  store: Store, vehicleId: string, start: number, durationMinutes: number,
) {
  const s = store.state;
  const vehicle = store.vehicle(vehicleId);
  if (!vehicle) throw new ActionError('That vehicle no longer exists.');
  const end = start + durationMinutes * MIN;
  const affected = s.tasks.filter(
    (t) => t.vehicleId === vehicle.id && t.scheduledFor &&
           t.scheduledFor >= start - HOUR && t.scheduledFor <= end &&
           !['completed', 'cancelled', 'failed'].includes(t.status));

  const candidates = s.vehicles.filter(
    (v) => v.id !== vehicle.id && v.lifecycle === 'active' && v.type === vehicle.type);
  const loads = candidates.map((v) => ({
    v, load: s.tasks.filter((t) => t.vehicleId === v.id &&
      ['assigned', 'accepted', 'en_route', 'arrived', 'in_progress'].includes(t.status)).length,
  })).sort((a, b) => a.load - b.load);

  const affectedDistance = affected.reduce((sum, t) => {
    if (vehicle.lat == null) return sum;
    return sum + haversine(vehicle.lon!, vehicle.lat, t.lon, t.lat) / 1000;
  }, 0);

  return {
    vehicle: { id: vehicle.id, name: vehicle.name, plate: vehicle.plate },
    window: { start, end, durationMinutes },
    affectedTasks: affected,
    affectedTaskCount: affected.length,
    affectedDistanceKm: Math.round(affectedDistance * 10) / 10,
    hasConflict: affected.length > 0,
    alternative: loads[0]
      ? { id: loads[0].v.id, name: loads[0].v.name, plate: loads[0].v.plate,
          activeTasks: loads[0].load }
      : null,
  };
}

export function createWorkOrder(store: Store, input: {
  vehicleId: string; title: string; category?: string; priority?: WorkOrder['priority'];
  problem?: string; scheduleId?: string; workshopId?: string; technician?: string;
  scheduledStart?: number; expectedCompletion?: number; estimatedCost?: number;
  incidentId?: string; acknowledgeConflict?: boolean;
}): WorkOrder {
  const s = store.state;
  const vehicle = store.vehicle(input.vehicleId);
  if (!vehicle) throw new ActionError('That vehicle no longer exists.');

  if (input.scheduledStart && !input.acknowledgeConflict) {
    const minutes = input.expectedCompletion
      ? Math.max(30, Math.round((input.expectedCompletion - input.scheduledStart) / MIN))
      : 120;
    const impact = maintenanceImpact(store, vehicle.id, input.scheduledStart, minutes);
    if (impact.hasConflict) {
      throw new ActionError(
        `${vehicle.name} has ${impact.affectedTaskCount} task` +
        `${impact.affectedTaskCount === 1 ? '' : 's'} scheduled during that window.`,
        'Review the impact, then schedule anyway or pick another slot.',
        impact,
      );
    }
  }

  const wo: WorkOrder = {
    id: store.id('wo'),
    reference: `WO-${(store.seq('wo') + 840).toString().padStart(5, '0')}`,
    vehicleId: vehicle.id, scheduleId: input.scheduleId, workshopId: input.workshopId,
    incidentId: input.incidentId,
    status: 'requested', priority: input.priority ?? 'normal',
    category: input.category ?? 'general_inspection',
    title: input.title, problem: input.problem, technician: input.technician,
    scheduledStart: input.scheduledStart, expectedCompletion: input.expectedCompletion,
    labourHours: 0, labourRate: s.org.settings.labourRate, labourCost: 0,
    partsCost: 0, totalCost: 0, estimatedCost: input.estimatedCost ?? 0,
    odometerKm: vehicle.odometerKm, parts: [], createdAt: s.now,
  };
  s.workOrders.unshift(wo);
  if (input.scheduleId) {
    const sched = s.schedules.find((x) => x.id === input.scheduleId);
    if (sched) sched.status = 'in_workshop';
  }
  store.audit({
    action: 'work_order.created', entityType: 'work_order', entityLabel: wo.reference,
    summary: `${wo.reference} raised for ${vehicle.name}: ${wo.title}`,
  });
  store.timeline({
    entityType: 'work_order', entityId: wo.id, action: 'requested',
    description: `Work order raised: ${wo.title}.`,
    actorType: 'user', actorName: store.me.fullName,
  });
  store.timeline({
    entityType: 'vehicle', entityId: vehicle.id, action: 'work_order_created',
    description: `Work order ${wo.reference} raised: ${wo.title}.`,
    actorType: 'user', actorName: store.me.fullName,
    relatedType: 'work_order', relatedId: wo.id,
  });
  store.emit();
  return wo;
}

export function recalcWorkOrderCosts(wo: WorkOrder) {
  wo.partsCost = Math.round(wo.parts.reduce((a, p) => a + p.quantity * p.unitCost, 0) * 100) / 100;
  wo.labourCost = Math.round(wo.labourHours * wo.labourRate * 100) / 100;
  wo.totalCost = Math.round((wo.partsCost + wo.labourCost) * 100) / 100;
}

export function addWorkOrderPart(store: Store, woId: string, part: {
  name: string; sku: string; quantity: number; unitCost: number;
  supplier: string; warrantyMonths?: number;
}) {
  const wo = store.workOrder(woId);
  if (!wo) throw new ActionError('That work order no longer exists.');
  if (wo.status === 'completed' || wo.status === 'cancelled') {
    throw new ActionError('Parts cannot be added to a closed work order.');
  }
  wo.parts.push({ id: store.id('wp'), ...part });
  recalcWorkOrderCosts(wo);
  store.timeline({
    entityType: 'work_order', entityId: wo.id, action: 'part_added',
    description: `Part added: ${part.quantity} × ${part.name} (€${(part.quantity * part.unitCost).toFixed(2)}).`,
    actorType: 'user', actorName: store.me.fullName,
  });
  store.emit();
  return wo;
}

export function removeWorkOrderPart(store: Store, woId: string, partId: string) {
  const wo = store.workOrder(woId);
  if (!wo) throw new ActionError('That work order no longer exists.');
  const idx = wo.parts.findIndex((p) => p.id === partId);
  if (idx < 0) throw new ActionError('That part is not on this work order.');
  const [removed] = wo.parts.splice(idx, 1);
  recalcWorkOrderCosts(wo);
  store.timeline({
    entityType: 'work_order', entityId: wo.id, action: 'part_removed',
    description: `Part removed: ${removed.name}.`,
    actorType: 'user', actorName: store.me.fullName,
  });
  store.emit();
  return wo;
}

export function updateWorkOrder(store: Store, woId: string, changes: Partial<WorkOrder>) {
  const wo = store.workOrder(woId);
  if (!wo) throw new ActionError('That work order no longer exists.');
  if (wo.status === 'completed' || wo.status === 'cancelled') {
    throw new ActionError(`A ${wo.status} work order can no longer be edited.`);
  }
  Object.assign(wo, changes);
  recalcWorkOrderCosts(wo);
  store.audit({
    action: 'work_order.updated', entityType: 'work_order', entityLabel: wo.reference,
    summary: `${wo.reference} updated`,
  });
  store.emit();
  return wo;
}

export function setWorkOrderStatus(
  store: Store, woId: string, target: WorkOrderStatus, note?: string,
): WorkOrder {
  const s = store.state;
  const wo = store.workOrder(woId);
  if (!wo) throw new ActionError('That work order no longer exists.');
  if (!WO_FLOW[wo.status].includes(target)) {
    throw new ActionError(
      `A ${wo.status.replace(/_/g, ' ')} work order cannot move to ${target.replace(/_/g, ' ')}.`,
    );
  }
  const before = wo.status;
  wo.status = target;
  const vehicle = store.vehicle(wo.vehicleId);

  if (target === 'in_progress') {
    wo.actualStart = wo.actualStart ?? s.now;
    if (vehicle) vehicle.lifecycle = 'maintenance';
  } else if (target === 'completed') {
    wo.actualCompletion = s.now;
    if (wo.actualStart) {
      wo.downtimeHours = Math.round(((s.now - wo.actualStart) / HOUR) * 100) / 100;
    }
    recalcWorkOrderCosts(wo);
    if (vehicle) {
      vehicle.lifecycle = 'active';
      s.maintenanceRecords.unshift({
        id: store.id('mr'), vehicleId: vehicle.id, workOrderId: wo.id,
        scheduleId: wo.scheduleId, category: wo.category,
        serviceDate: new Date(s.now).toISOString().slice(0, 10),
        odometerKm: vehicle.odometerKm,
        workPerformed: wo.workPerformed || wo.title,
        partsCost: wo.partsCost, labourCost: wo.labourCost, totalCost: wo.totalCost,
        downtimeHours: wo.downtimeHours ?? 0,
        workshopName: store.workshop(wo.workshopId)?.name, technician: wo.technician,
      });
      if (wo.totalCost) {
        s.costs.push({
          id: store.id('co'), vehicleId: vehicle.id, category: 'maintenance',
          incurredOn: new Date(s.now).toISOString().slice(0, 10), amount: wo.totalCost,
          description: `${wo.reference}: ${wo.title}`, sourceType: 'work_order',
          sourceId: wo.id, odometerKm: vehicle.odometerKm,
        });
      }
      // reset the preventive schedule from this service point
      const sched = s.schedules.find((x) => x.id === wo.scheduleId);
      if (sched) {
        sched.lastServiceKm = vehicle.odometerKm;
        sched.lastServiceDate = new Date(s.now).toISOString().slice(0, 10);
        sched.lastAlertedStatus = undefined;
        if (sched.intervalKm) sched.dueAtKm = vehicle.odometerKm + sched.intervalKm;
        if (sched.intervalMonths) {
          sched.dueAtDate = new Date(s.now + sched.intervalMonths * 30 * DAY)
            .toISOString().slice(0, 10);
        }
        sched.status = 'healthy';
      }
      // close the maintenance alerts this work order answers
      s.alerts.forEach((a) => {
        if (a.vehicleId === vehicle.id && a.category === 'maintenance' &&
            ['triggered', 'acknowledged', 'investigating', 'escalated'].includes(a.status)) {
          a.status = 'resolved';
          a.resolvedAt = s.now;
          a.resolvedBy = store.me.id;
          a.resolutionNote = `Resolved by ${wo.reference}.`;
          store.timeline({
            entityType: 'alert', entityId: a.id, action: 'resolved',
            description: `Closed automatically by ${wo.reference}.`,
            actorType: 'user', actorName: store.me.fullName,
          });
        }
      });
      evaluateMaintenance(store, vehicle.id);
    }
  } else if (target === 'cancelled') {
    wo.cancelledReason = note;
    const sched = s.schedules.find((x) => x.id === wo.scheduleId);
    if (sched && sched.status === 'in_workshop') sched.status = 'due';
    if (vehicle && vehicle.lifecycle === 'maintenance') vehicle.lifecycle = 'active';
  }

  store.audit({
    action: 'work_order.status_changed', entityType: 'work_order',
    entityLabel: wo.reference, before: { status: before }, after: { status: target },
    summary: `${wo.reference}: ${before} → ${target}`,
  });
  store.timeline({
    entityType: 'work_order', entityId: wo.id, action: target,
    description: note ?? `Status changed to ${target.replace(/_/g, ' ')}.`,
    actorType: 'user', actorName: store.me.fullName,
  });
  if (vehicle) {
    store.timeline({
      entityType: 'vehicle', entityId: vehicle.id, action: `work_order_${target}`,
      description: `${wo.reference}: ${target.replace(/_/g, ' ')}.`,
      actorType: 'user', actorName: store.me.fullName,
      relatedType: 'work_order', relatedId: wo.id,
    });
  }
  store.emit();
  return wo;
}

export function createSchedule(store: Store, input: {
  vehicleId: string; name: string; category: string;
  intervalKm?: number; intervalMonths?: number;
  lastServiceKm?: number; lastServiceDate?: string;
  estimatedCost?: number; estimatedMinutes?: number; priority?: MaintenanceSchedule['priority'];
}): MaintenanceSchedule {
  const s = store.state;
  if (!input.intervalKm && !input.intervalMonths) {
    throw new ActionError('Set a mileage interval, a time interval, or both.');
  }
  const vehicle = store.vehicle(input.vehicleId);
  if (!vehicle) throw new ActionError('That vehicle no longer exists.');
  const lastKm = input.lastServiceKm ?? vehicle.odometerKm;
  const lastDate = input.lastServiceDate ?? new Date(s.now).toISOString().slice(0, 10);
  const sched: MaintenanceSchedule = {
    id: store.id('ms'), vehicleId: vehicle.id, name: input.name, category: input.category,
    intervalKm: input.intervalKm, intervalMonths: input.intervalMonths,
    lastServiceKm: lastKm, lastServiceDate: lastDate,
    dueAtKm: input.intervalKm ? lastKm + input.intervalKm : undefined,
    dueAtDate: input.intervalMonths
      ? new Date(Date.parse(lastDate) + input.intervalMonths * 30 * DAY).toISOString().slice(0, 10)
      : undefined,
    status: 'healthy', priority: input.priority ?? 'normal',
    estimatedCost: input.estimatedCost ?? 0,
    estimatedMinutes: input.estimatedMinutes ?? 120, active: true,
  };
  sched.status = maintenanceStatus(sched, vehicle.odometerKm, s.now, s.org.settings);
  s.schedules.push(sched);
  store.audit({
    action: 'maintenance_schedule.created', entityType: 'maintenance_schedule',
    entityLabel: sched.name, summary: `${sched.name} scheduled for ${vehicle.name}`,
  });
  store.timeline({
    entityType: 'vehicle', entityId: vehicle.id, action: 'schedule_created',
    description: `Preventive schedule added: ${sched.name}.`,
    actorType: 'user', actorName: store.me.fullName,
  });
  store.emit();
  return sched;
}

/** Re-evaluate one vehicle's schedules and raise alerts on transitions. */
export function evaluateMaintenance(store: Store, vehicleId: string) {
  const s = store.state;
  const vehicle = store.vehicle(vehicleId);
  if (!vehicle) return;
  const map: Record<string, { code: string; severity: Alert['severity'] }> = {
    due_soon: { code: 'maintenance_due_soon', severity: 'low' },
    due: { code: 'maintenance_due', severity: 'medium' },
    overdue: { code: 'maintenance_overdue', severity: 'high' },
    critical: { code: 'maintenance_critical', severity: 'critical' },
  };
  s.schedules
    .filter((sc) => sc.vehicleId === vehicle.id && sc.active && sc.status !== 'in_workshop')
    .forEach((sc) => {
      const next = maintenanceStatus(sc, vehicle.odometerKm, s.now, s.org.settings);
      if (next === sc.status) return;
      const before = sc.status;
      sc.status = next;
      store.timeline({
        entityType: 'vehicle', entityId: vehicle.id, action: 'maintenance_status_changed',
        description: `${sc.name}: ${before.replace(/_/g, ' ')} → ${next.replace(/_/g, ' ')}.`,
      });
      const spec = map[next];
      if (spec && sc.lastAlertedStatus !== next) {
        sc.lastAlertedStatus = next;
        raiseAlert(store, {
          code: spec.code, severity: spec.severity,
          title: `${vehicle.name}: ${sc.name} ${next.replace(/_/g, ' ')}`,
          detail: `${sc.name} on ${vehicle.name} (${vehicle.plate}) is ` +
                  `${next.replace(/_/g, ' ')} — ${describeDue(sc, vehicle.odometerKm, s.now)}.`,
          vehicleId: vehicle.id, driverId: vehicle.driverId,
          dedupeExtra: `schedule:${sc.id}`,
          evidence: {
            schedule: sc.name, status: next,
            odometer_km: Math.round(vehicle.odometerKm),
            due_at_km: sc.dueAtKm, due_at_date: sc.dueAtDate,
          },
        });
      }
    });
}

// --------------------------------------------------------------------------
// Geofences, places, documents, incidents
// --------------------------------------------------------------------------
export function createGeofence(store: Store, input: {
  name: string; kind: 'polygon' | 'circle'; trigger: 'enter' | 'exit' | 'both';
  colour?: string; polygon?: [number, number][]; centreLat?: number; centreLon?: number;
  radiusM?: number; restricted?: boolean; description?: string; vehicleIds?: string[];
}) {
  const s = store.state;
  if (input.kind === 'polygon' && (!input.polygon || input.polygon.length < 3)) {
    throw new ActionError('A polygon geofence needs at least three points.');
  }
  if (input.kind === 'circle' && (input.centreLat == null || !input.radiusM)) {
    throw new ActionError('A circular geofence needs a centre and a radius.');
  }
  const fence = {
    id: store.id('gf'), name: input.name, kind: input.kind, trigger: input.trigger,
    colour: input.colour ?? '#1E90FF', polygon: input.polygon,
    centreLat: input.centreLat, centreLon: input.centreLon, radiusM: input.radiusM,
    vehicleIds: input.vehicleIds ?? [], active: true,
    restricted: input.restricted ?? false, description: input.description,
  };
  s.geofences.push(fence);
  store.audit({
    action: 'geofence.created', entityType: 'geofence', entityLabel: fence.name,
    summary: `Geofence ${fence.name} created`,
  });
  store.emit();
  return fence;
}

export function deleteGeofence(store: Store, id: string) {
  const s = store.state;
  const idx = s.geofences.findIndex((g) => g.id === id);
  if (idx < 0) throw new ActionError('That geofence no longer exists.');
  const [removed] = s.geofences.splice(idx, 1);
  Object.keys(s.geofenceInside)
    .filter((k) => k.startsWith(`${id}:`))
    .forEach((k) => delete s.geofenceInside[k]);
  store.audit({
    action: 'geofence.deleted', entityType: 'geofence', entityLabel: removed.name,
    summary: `Geofence ${removed.name} deleted`,
  });
  store.emit();
  return removed;
}

export function createPlace(store: Store, input: Omit<Place, 'id' | 'active'>): Place {
  const p: Place = { ...input, id: store.id('pl'), active: true };
  store.state.places.push(p);
  store.audit({
    action: 'place.created', entityType: 'place', entityLabel: p.name,
    summary: `Place ${p.name} created`,
  });
  store.emit();
  return p;
}

export function createDocument(
  store: Store, input: Omit<FleetDocument, 'id' | 'status'>,
): FleetDocument {
  const s = store.state;
  const warn = Math.max(...s.org.settings.documentAlertDays);
  const doc: FleetDocument = {
    ...input, id: store.id('doc'),
    status: (() => {
      const days = Math.round((Date.parse(input.expiryDate) - s.now) / DAY);
      return days < 0 ? 'expired' : days <= warn ? 'expiring_soon' : 'valid';
    })(),
  };
  s.documents.push(doc);
  s.documents.sort((a, b) => a.expiryDate.localeCompare(b.expiryDate));
  store.audit({
    action: 'document.created', entityType: 'document', entityLabel: doc.name,
    summary: `Document added: ${doc.name}`,
  });
  if (doc.vehicleId) {
    store.timeline({
      entityType: 'vehicle', entityId: doc.vehicleId, action: 'document_added',
      description: `${doc.kind.replace(/_/g, ' ')} added, expires ${doc.expiryDate}.`,
      actorType: 'user', actorName: store.me.fullName,
    });
  }
  store.emit();
  return doc;
}

export function renewDocument(store: Store, docId: string, newExpiry: string, cost?: number) {
  const s = store.state;
  const doc = s.documents.find((d) => d.id === docId);
  if (!doc) throw new ActionError('That document no longer exists.');
  const before = doc.expiryDate;
  doc.expiryDate = newExpiry;
  doc.issueDate = new Date(s.now).toISOString().slice(0, 10);
  doc.lastAlertedDays = undefined;
  const days = Math.round((Date.parse(newExpiry) - s.now) / DAY);
  const warn = Math.max(...s.org.settings.documentAlertDays);
  doc.status = days < 0 ? 'expired' : days <= warn ? 'expiring_soon' : 'valid';
  if (cost) {
    doc.cost = cost;
    s.costs.push({
      id: store.id('co'), vehicleId: doc.vehicleId,
      category: doc.kind === 'insurance' ? 'insurance' : 'registration',
      incurredOn: doc.issueDate, amount: cost,
      description: `${doc.name} renewal`, sourceType: 'document', sourceId: doc.id,
    });
  }
  // close the compliance alerts this renewal answers
  s.alerts.forEach((a) => {
    if (a.documentId === doc.id &&
        ['triggered', 'acknowledged', 'investigating', 'escalated'].includes(a.status)) {
      a.status = 'resolved';
      a.resolvedAt = s.now;
      a.resolvedBy = store.me.id;
      a.resolutionNote = `Document renewed until ${newExpiry}.`;
    }
  });
  if (doc.driverId) {
    const d = store.driver(doc.driverId);
    if (d && doc.kind === 'driver_license') d.licenseExpiry = newExpiry;
  }
  store.audit({
    action: 'document.renewed', entityType: 'document', entityLabel: doc.name,
    summary: `${doc.name} renewed until ${newExpiry}`,
    before: { expiryDate: before }, after: { expiryDate: newExpiry },
  });
  store.emit();
  return doc;
}

/** Re-evaluate document expiry and raise the configured reminders. */
export function scanCompliance(store: Store): { checked: number; raised: number } {
  const s = store.state;
  const ladder = [...s.org.settings.documentAlertDays].sort((a, b) => b - a);
  let raised = 0;
  s.documents.forEach((d) => {
    const days = Math.round((Date.parse(d.expiryDate) - s.now) / DAY);
    d.status = days < 0 ? 'expired' : days <= Math.max(...ladder) ? 'expiring_soon' : 'valid';
    if (days < 0) {
      if (d.lastAlertedDays !== -1) {
        d.lastAlertedDays = -1;
        raiseAlert(store, {
          code: 'document_expired', severity: 'critical',
          title: `${d.name} has expired`,
          detail: `Expired ${Math.abs(days)} day${Math.abs(days) === 1 ? '' : 's'} ago.`,
          vehicleId: d.vehicleId, driverId: d.driverId, documentId: d.id,
          dedupeExtra: `doc:${d.id}`,
          evidence: { expiry_date: d.expiryDate, days_overdue: Math.abs(days) },
        });
        raised++;
      }
    } else {
      const step = ladder.find((x) => days <= x);
      if (step != null && d.lastAlertedDays !== step) {
        d.lastAlertedDays = step;
        raiseAlert(store, {
          code: d.kind === 'driver_license' ? 'license_expiring' : 'document_expiring',
          severity: step <= 7 ? 'high' : 'medium',
          title: `${d.name} expires in ${days} day${days === 1 ? '' : 's'}`,
          detail: `Renew before ${d.expiryDate}.`,
          vehicleId: d.vehicleId, driverId: d.driverId, documentId: d.id,
          dedupeExtra: `doc:${d.id}:${step}`,
          evidence: { expiry_date: d.expiryDate, days_remaining: days },
        });
        raised++;
      }
    }
  });
  return { checked: s.documents.length, raised };
}

export function createIncident(store: Store, input: {
  title: string; kind: string; severity: Incident['severity']; description?: string;
  occurredAt?: number; lat?: number; lon?: number; address?: string;
  vehicleId?: string; driverId?: string; tripId?: string; taskId?: string;
  estimatedCost?: number; takeVehicleOffRoad?: boolean;
  witnesses?: { name: string; contact: string }[];
}): { incident: Incident; affectedTasks: Task[] } {
  const s = store.state;
  const incident: Incident = {
    id: store.id('in'), reference: `INC-${1000 + store.seq('incident') + s.incidents.length}`,
    kind: input.kind, severity: input.severity, status: 'reported',
    title: input.title, description: input.description,
    occurredAt: input.occurredAt ?? s.now,
    lat: input.lat, lon: input.lon, address: input.address,
    vehicleId: input.vehicleId, driverId: input.driverId,
    tripId: input.tripId, taskId: input.taskId,
    photos: [], witnesses: input.witnesses ?? [],
    estimatedCost: input.estimatedCost, reportedBy: store.me.id,
  };
  s.incidents.unshift(incident);

  const affectedTasks: Task[] = [];
  const vehicle = store.vehicle(input.vehicleId);
  if (vehicle && input.takeVehicleOffRoad) {
    vehicle.lifecycle = 'suspended';
    vehicle.ignitionOn = false;
    vehicle.speedKph = 0;
    s.tasks
      .filter((t) => t.vehicleId === vehicle.id &&
              ['assigned', 'accepted', 'en_route', 'arrived', 'in_progress'].includes(t.status))
      .forEach((t) => {
        t.status = 'delayed';
        affectedTasks.push(t);
        store.timeline({
          entityType: 'task', entityId: t.id, action: 'delayed',
          description: `Marked delayed — ${incident.reference} took ${vehicle.name} off the road.`,
          actorType: 'user', actorName: store.me.fullName,
          relatedType: 'incident', relatedId: incident.id,
        });
      });
  }

  if (input.severity === 'high' || input.severity === 'critical') {
    raiseAlert(store, {
      code: 'unauthorized_movement', severity: input.severity, category: 'vehicle',
      title: `Incident ${incident.reference}: ${incident.title}`,
      detail: incident.description, vehicleId: incident.vehicleId,
      driverId: incident.driverId, lat: incident.lat, lon: incident.lon,
      dedupeExtra: `incident:${incident.id}`,
      evidence: { incident: incident.reference, type: incident.kind },
    });
  }
  if (input.estimatedCost && input.vehicleId) {
    s.costs.push({
      id: store.id('co'), vehicleId: input.vehicleId, category: 'other',
      incurredOn: new Date(incident.occurredAt).toISOString().slice(0, 10),
      amount: input.estimatedCost,
      description: `Incident ${incident.reference} — ${incident.title}`,
      sourceType: 'incident', sourceId: incident.id,
    });
  }

  store.audit({
    action: 'incident.created', entityType: 'incident', entityLabel: incident.reference,
    summary: `${incident.reference} reported: ${incident.title}`,
  });
  store.timeline({
    entityType: 'incident', entityId: incident.id, action: 'reported',
    description: `Incident reported — ${incident.title}.`,
    actorType: 'user', actorName: store.me.fullName,
  });
  if (vehicle) {
    store.timeline({
      entityType: 'vehicle', entityId: vehicle.id, action: 'incident_reported',
      description: `${incident.reference}: ${incident.title}` +
                   (input.takeVehicleOffRoad ? ' — vehicle taken off the road.' : ''),
      actorType: 'user', actorName: store.me.fullName,
      relatedType: 'incident', relatedId: incident.id,
    });
  }
  if (input.driverId) {
    store.timeline({
      entityType: 'driver', entityId: input.driverId, action: 'incident_reported',
      description: `${incident.reference}: ${incident.title}`,
      actorType: 'user', actorName: store.me.fullName,
      relatedType: 'incident', relatedId: incident.id,
    });
    recomputeDriverScore(store, input.driverId);
  }
  store.emit();
  return { incident, affectedTasks };
}

export const INCIDENT_FLOW: Record<Incident['status'], Incident['status'][]> = {
  reported: ['under_investigation', 'action_required', 'resolved'],
  under_investigation: ['action_required', 'resolved'],
  action_required: ['resolved', 'under_investigation'],
  resolved: ['closed', 'under_investigation'],
  closed: [],
};

export function setIncidentStatus(
  store: Store, id: string, target: Incident['status'],
  opts: { note?: string; restoreVehicle?: boolean } = {},
) {
  const s = store.state;
  const incident = store.incident(id);
  if (!incident) throw new ActionError('That incident no longer exists.');
  if (!INCIDENT_FLOW[incident.status].includes(target)) {
    throw new ActionError(
      `An incident that is ${incident.status.replace(/_/g, ' ')} cannot move to ` +
      `${target.replace(/_/g, ' ')}.`,
    );
  }
  const before = incident.status;
  incident.status = target;
  if (target === 'resolved' || target === 'closed') {
    incident.resolvedAt = incident.resolvedAt ?? s.now;
    incident.resolutionNote = opts.note ?? incident.resolutionNote;
  }
  if (opts.restoreVehicle && incident.vehicleId) {
    const v = store.vehicle(incident.vehicleId);
    if (v && v.lifecycle === 'suspended') {
      v.lifecycle = 'active';
      v.ignitionOn = true;
      store.timeline({
        entityType: 'vehicle', entityId: v.id, action: 'returned_to_service',
        description: `Returned to service after ${incident.reference}.`,
        actorType: 'user', actorName: store.me.fullName,
      });
    }
  }
  store.audit({
    action: 'incident.status_changed', entityType: 'incident',
    entityLabel: incident.reference, before: { status: before }, after: { status: target },
    summary: `${incident.reference}: ${before} → ${target}`,
  });
  store.timeline({
    entityType: 'incident', entityId: incident.id, action: target,
    description: opts.note ?? `Status changed to ${target.replace(/_/g, ' ')}.`,
    actorType: 'user', actorName: store.me.fullName,
  });
  store.emit();
  return incident;
}

export function workOrderFromIncident(store: Store, incidentId: string, title?: string) {
  const incident = store.incident(incidentId);
  if (!incident) throw new ActionError('That incident no longer exists.');
  if (!incident.vehicleId) {
    throw new ActionError('This incident is not linked to a vehicle.');
  }
  if (incident.workOrderId) {
    throw new ActionError('A work order already exists for this incident.');
  }
  const wo = createWorkOrder(store, {
    vehicleId: incident.vehicleId,
    title: title ?? `Repair — ${incident.title}`,
    problem: incident.description, priority: 'high', incidentId: incident.id,
    acknowledgeConflict: true,
  });
  incident.workOrderId = wo.id;
  incident.status = 'action_required';
  store.timeline({
    entityType: 'incident', entityId: incident.id, action: 'work_order_raised',
    description: `Work order ${wo.reference} raised.`,
    actorType: 'user', actorName: store.me.fullName,
    relatedType: 'work_order', relatedId: wo.id,
  });
  store.timeline({
    entityType: 'work_order', entityId: wo.id, action: 'linked',
    description: `Raised from incident ${incident.reference}.`,
    actorType: 'user', actorName: store.me.fullName,
    relatedType: 'incident', relatedId: incident.id,
  });
  store.emit();
  return wo;
}

// --------------------------------------------------------------------------
// Fuel & energy
// --------------------------------------------------------------------------
export function recordFuel(store: Store, input: {
  vehicleId: string; driverId?: string; litres: number; pricePerLitre: number;
  odometerKm: number; stationName: string; occurredAt?: number;
}) {
  const s = store.state;
  const vehicle = store.vehicle(input.vehicleId);
  if (!vehicle) throw new ActionError('That vehicle no longer exists.');
  if (input.litres <= 0) throw new ActionError('Enter the litres dispensed.');
  const previous = s.fuel
    .filter((f) => f.vehicleId === vehicle.id)
    .sort((a, b) => b.occurredAt - a.occurredAt)[0];
  const total = Math.round(input.litres * input.pricePerLitre * 100) / 100;
  const tx = {
    id: store.id('ft'), vehicleId: vehicle.id, driverId: input.driverId,
    occurredAt: input.occurredAt ?? s.now, stationName: input.stationName,
    fuelType: vehicle.fuelType, litres: input.litres,
    pricePerLitre: input.pricePerLitre, totalCost: total,
    odometerKm: input.odometerKm,
    distanceSinceLastKm: previous
      ? Math.round((input.odometerKm - previous.odometerKm) * 10) / 10 : undefined,
    fullTank: true, reference: `FC${Math.floor(100000 + Math.random() * 899999)}`,
  };
  s.fuel.unshift(tx);
  s.costs.push({
    id: store.id('co'), vehicleId: vehicle.id, category: 'fuel',
    incurredOn: new Date(tx.occurredAt).toISOString().slice(0, 10), amount: total,
    description: `Fuel — ${input.stationName}`, sourceType: 'fuel_transaction',
    sourceId: tx.id, odometerKm: input.odometerKm,
  });
  if (input.odometerKm > vehicle.odometerKm) {
    vehicle.odometerKm = input.odometerKm;
    evaluateMaintenance(store, vehicle.id);
  }
  store.audit({
    action: 'fuel.recorded', entityType: 'fuel_transaction', entityLabel: vehicle.name,
    summary: `${input.litres.toFixed(1)} L for ${vehicle.name} (€${total.toFixed(2)})`,
  });
  store.timeline({
    entityType: 'vehicle', entityId: vehicle.id, action: 'refuelled',
    description: `Refuelled ${input.litres.toFixed(1)} L at ${input.stationName} (€${total.toFixed(2)}).`,
    actorType: 'user', actorName: store.me.fullName,
  });
  store.emit();
  return tx;
}

// --------------------------------------------------------------------------
// Scoring
// --------------------------------------------------------------------------
export function recomputeDriverScore(store: Store, driverId: string) {
  const s = store.state;
  const d = store.driver(driverId);
  if (!d) return;
  const since = s.now - 30 * DAY;
  const events = s.driverEvents.filter((e) => e.driverId === d.id && e.occurredAt >= since);
  const counts: Record<string, number> = {};
  events.forEach((e) => { counts[e.kind] = (counts[e.kind] ?? 0) + 1; });
  const incidents = s.incidents.filter((i) => i.driverId === d.id && i.occurredAt >= since);
  if (incidents.length) counts.incident = incidents.length;
  const km = s.trips
    .filter((t) => t.driverId === d.id && t.startedAt >= since)
    .reduce((a, t) => a + t.distanceKm, 0);
  const score = safetyScore(counts, km, s.org.settings.safetyWeights);
  if (Math.abs(score - d.safetyScore) >= 0.05) d.previousSafetyScore = d.safetyScore;
  d.safetyScore = score;
}

export function recordDriverEvent(store: Store, input: {
  driverId: string; kind: string; vehicleId?: string; tripId?: string; alertId?: string;
  severity?: Alert['severity']; lat?: number; lon?: number; street?: string;
  value?: number; threshold?: number; durationS?: number; detail?: string; at?: number;
}) {
  const s = store.state;
  const d = store.driver(input.driverId);
  if (!d) return null;
  const at = input.at ?? s.now;
  const event = {
    id: store.id('de'), driverId: d.id, vehicleId: input.vehicleId,
    tripId: input.tripId, alertId: input.alertId,
    kind: input.kind as never, severity: (input.severity ?? 'medium') as never,
    occurredAt: at, lat: input.lat, lon: input.lon, street: input.street,
    value: input.value, threshold: input.threshold, durationS: input.durationS,
    detail: input.detail,
  };
  s.driverEvents.push(event);
  if (s.driverEvents.length > 8000) s.driverEvents.splice(0, 2000);

  const delta = s.org.settings.driverPoints[input.kind] ?? 0;
  if (delta) {
    d.points = Math.max(0, d.points + delta);
    s.pointTransactions.unshift({
      id: store.id('pt'), driverId: d.id, points: delta, balanceAfter: d.points,
      reason: input.kind, detail: input.detail, occurredAt: at,
    });
    if (s.pointTransactions.length > 2000) s.pointTransactions.length = 1500;
  }
  recomputeDriverScore(store, d.id);
  store.timeline({
    entityType: 'driver', entityId: d.id, action: input.kind,
    description: input.detail ?? `${input.kind.replace(/_/g, ' ')} recorded.`,
    at, relatedType: 'driver_event', relatedId: event.id,
  });
  return event;
}

// --------------------------------------------------------------------------
// Saved views
// --------------------------------------------------------------------------
export function saveView(store: Store, name: string, filters: Record<string, unknown>) {
  const view = {
    id: store.id('sv'), name, surface: 'live_tracking', filters, shared: false,
  };
  store.state.savedViews.push(view);
  store.audit({
    action: 'saved_view.created', entityType: 'saved_view', entityLabel: name,
    summary: `Saved view “${name}” created`,
  });
  store.emit();
  return view;
}

export function deleteView(store: Store, id: string) {
  const s = store.state;
  const idx = s.savedViews.findIndex((v) => v.id === id);
  if (idx < 0) return;
  const [removed] = s.savedViews.splice(idx, 1);
  store.audit({
    action: 'saved_view.deleted', entityType: 'saved_view', entityLabel: removed.name,
    summary: `Saved view “${removed.name}” deleted`,
  });
  store.emit();
}

// --------------------------------------------------------------------------
// Organisation settings and users
// --------------------------------------------------------------------------

/**
 * Settings are not cosmetic. Emission factors, fuel prices, safety weights and
 * freshness thresholds are read by the selectors on every render, so changing one
 * here changes Sustainability, Costs, Safety and Live Tracking immediately.
 */
export function updateSettings(
  store: Store, changes: Partial<OrgSettings>, label = 'Settings updated',
) {
  const s = store.state;
  const before: Record<string, unknown> = {};
  const after: Record<string, unknown> = {};
  (Object.keys(changes) as (keyof OrgSettings)[]).forEach((k) => {
    if (changes[k] === undefined) return;
    before[k as string] = s.org.settings[k];
    after[k as string] = changes[k];
    (s.org.settings as unknown as Record<string, unknown>)[k as string] = changes[k];
  });
  if (!Object.keys(after).length) return;

  // Safety weights feed every driver score, so re-derive rather than leave stale numbers.
  if ('safetyWeights' in changes) {
    s.drivers.forEach((d) => recomputeDriverScore(store, d.id));
  }
  store.audit({
    action: 'org.settings_updated', entityType: 'organization', entityLabel: s.org.name,
    summary: `${label}: ${Object.keys(after).join(', ')}`, before, after,
  });
  store.emit();
}

export function updateOrgProfile(store: Store, changes: { name?: string; city?: string; country?: string }) {
  const s = store.state;
  const before = { name: s.org.name, city: s.org.city, country: s.org.country };
  if (changes.name !== undefined) s.org.name = changes.name;
  if (changes.city !== undefined) s.org.city = changes.city;
  if (changes.country !== undefined) s.org.country = changes.country;
  store.audit({
    action: 'org.profile_updated', entityType: 'organization', entityLabel: s.org.name,
    summary: `Organisation profile updated`, before,
    after: { name: s.org.name, city: s.org.city, country: s.org.country },
  });
  store.emit();
}

/**
 * Role changes are the highest-leverage privilege action in the product, so the
 * rules are enforced here rather than by hiding buttons: only an admin may change
 * a role, and the last remaining admin cannot demote themselves out of existence.
 */
export function setUserRole(store: Store, userId: string, role: Role) {
  const s = store.state;
  const actor = store.me;
  if (actor.role !== 'org_admin' && actor.role !== 'super_admin') {
    throw new ActionError('Only an administrator can change roles.',
      `You are signed in as ${actor.role.replace('_', ' ')}.`);
  }
  const user = store.user(userId);
  if (!user) throw new ActionError('That user no longer exists.');
  if (user.role === role) return user;
  const admins = s.users.filter((u) => u.role === 'org_admin' || u.role === 'super_admin');
  if (admins.length === 1 && admins[0].id === user.id && role !== 'org_admin' && role !== 'super_admin') {
    throw new ActionError('This is the only administrator left.',
      'Promote another user to administrator first, or the organisation would lock itself out.');
  }
  const before = { role: user.role };
  user.role = role;
  store.audit({
    action: 'user.role_changed', entityType: 'user', entityLabel: user.fullName,
    summary: `${user.fullName} changed from ${before.role.replace('_', ' ')} to ${role.replace('_', ' ')}`,
    before, after: { role },
  });
  store.emit();
  return user;
}

/** Switch the acting user, which changes what the UI is permitted to do. */
export function switchUser(store: Store, userId: string) {
  const user = store.user(userId);
  if (!user) throw new ActionError('That user no longer exists.');
  store.state.currentUserId = userId;
  store.audit({
    action: 'auth.identity_switched', entityType: 'user', entityLabel: user.fullName,
    summary: `Acting as ${user.fullName} (${user.role.replace('_', ' ')})`,
  });
  store.emit();
  return user;
}

export function setAlertRuleActive(store: Store, ruleId: string, active: boolean) {
  const rule = store.state.alertRules.find((r) => r.id === ruleId);
  if (!rule) return;
  rule.active = active;
  store.audit({
    action: 'alert_rule.updated', entityType: 'alert_rule', entityLabel: rule.name,
    summary: `Rule “${rule.name}” ${active ? 'enabled' : 'disabled'}`,
    before: { active: !active }, after: { active },
  });
  store.emit();
}

// --------------------------------------------------------------------------
// Driver app: pre-trip inspection
// --------------------------------------------------------------------------

export const INSPECTION_ITEMS: { key: string; label: string; critical: boolean }[] = [
  { key: 'tyres', label: 'Tyres and pressure', critical: true },
  { key: 'lights', label: 'Lights and indicators', critical: true },
  { key: 'brakes', label: 'Brakes feel normal', critical: true },
  { key: 'fluids', label: 'Oil, coolant, washer fluid', critical: false },
  { key: 'mirrors', label: 'Mirrors and glass', critical: false },
  { key: 'load', label: 'Load secured', critical: true },
  { key: 'cleanliness', label: 'Cab and cargo area clean', critical: false },
];

/**
 * A pre-trip check the driver actually performs. A failed critical item is not a
 * note in a log: it raises an alert for dispatch and blocks nothing silently — the
 * vehicle stays flagged until someone in the workshop deals with it.
 */
export function recordInspection(store: Store, input: {
  driverId: string; vehicleId: string; items: Record<string, boolean>; notes?: string;
}) {
  const s = store.state;
  const driver = store.driver(input.driverId);
  const vehicle = store.vehicle(input.vehicleId);
  if (!driver || !vehicle) throw new ActionError('Driver or vehicle not found.');

  const failed = INSPECTION_ITEMS.filter((i) => input.items[i.key] === false);
  const criticalFailed = failed.filter((i) => i.critical);
  const result: 'ready' | 'issue_found' = failed.length ? 'issue_found' : 'ready';

  const inspection = {
    id: store.id('in'), driverId: driver.id, vehicleId: vehicle.id,
    performedAt: s.now, result, items: { ...input.items }, notes: input.notes,
  };
  s.inspections.unshift(inspection);
  if (s.inspections.length > 1000) s.inspections.length = 800;

  if (failed.length) {
    raiseAlert(store, {
      code: 'inspection_failed',
      severity: criticalFailed.length ? 'high' : 'medium',
      title: `${vehicle.name} failed its pre-trip check`,
      detail: `${driver.fullName} reported: ${failed.map((f) => f.label).join(', ')}.` +
              (input.notes ? ` Note: ${input.notes}` : ''),
      vehicleId: vehicle.id, driverId: driver.id,
      lat: vehicle.lat, lon: vehicle.lon, street: vehicle.street,
      dedupeExtra: `inspection:${inspection.id}`,
      evidence: { failed: failed.map((f) => f.key), notes: input.notes },
    });
  }

  store.timeline({
    entityType: 'vehicle', entityId: vehicle.id, action: 'inspection',
    description: result === 'ready'
      ? `Pre-trip check passed (${driver.fullName}).`
      : `Pre-trip check found ${failed.length} issue(s): ${failed.map((f) => f.label).join(', ')}.`,
    actorType: 'driver', actorName: driver.fullName,
    relatedType: 'inspection', relatedId: inspection.id,
  });
  store.audit({
    action: 'inspection.recorded', entityType: 'vehicle', entityLabel: vehicle.plate,
    summary: `Pre-trip inspection ${result === 'ready' ? 'passed' : 'flagged issues'} ` +
             `on ${vehicle.name} by ${driver.fullName}`,
    actorName: driver.fullName, actorRole: 'driver',
    after: { result, failed: failed.map((f) => f.key) },
  });
  store.emit();
  return inspection;
}
