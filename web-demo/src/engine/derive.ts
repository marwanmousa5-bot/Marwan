// Derived state. A vehicle has ONE status; Live Tracking, Dispatch and
// Maintenance all read it from here so the product can never contradict itself.

import type {
  Driver, MaintenanceSchedule, MaintenanceStatus, OrgSettings, SlaState, Task,
  Vehicle, VehicleStatus, DocStatus,
} from './types';

export type Freshness = 'LIVE' | 'STALE' | 'OFFLINE' | 'NEVER';

export function gpsFreshness(
  lastAt: number | undefined, now: number, liveS = 45, staleS = 300,
): { state: Freshness; ageS: number | null } {
  if (!lastAt) return { state: 'NEVER', ageS: null };
  const age = (now - lastAt) / 1000;
  if (age <= liveS) return { state: 'LIVE', ageS: age };
  if (age <= staleS) return { state: 'STALE', ageS: age };
  return { state: 'OFFLINE', ageS: age };
}

export function vehicleStatus(
  v: Vehicle, opts: { openWorkOrder?: boolean; now: number; settings: OrgSettings },
): VehicleStatus {
  const { openWorkOrder, now, settings } = opts;
  if (v.lifecycle === 'retired' || v.lifecycle === 'suspended' || v.lifecycle === 'planned') {
    return 'offline';
  }
  if (v.lifecycle === 'maintenance' || openWorkOrder) return 'maintenance';
  if (!v.lastPositionAt) return 'not_tracked';
  const { state } = gpsFreshness(v.lastPositionAt, now, settings.gpsLiveThresholdS,
                                settings.gpsStaleThresholdS);
  if (state === 'OFFLINE') return 'offline';
  if ((v.speedKph ?? 0) > 3) return 'moving';
  if (v.ignitionOn) return 'idle';
  return 'stopped';
}

const MAINT_ORDER: MaintenanceStatus[] =
  ['healthy', 'due_soon', 'due', 'in_workshop', 'overdue', 'critical'];

export function worstMaintenance(a: MaintenanceStatus, b: MaintenanceStatus): MaintenanceStatus {
  return MAINT_ORDER.indexOf(a) >= MAINT_ORDER.indexOf(b) ? a : b;
}

export function daysBetween(isoDate: string, now: number): number {
  const then = Date.parse(isoDate + 'T00:00:00Z');
  return Math.round((then - now) / 86400000);
}

export function maintenanceStatus(
  s: MaintenanceSchedule, odometerKm: number, now: number, settings: OrgSettings,
): MaintenanceStatus {
  let worst: MaintenanceStatus = 'healthy';
  const bump = (c: MaintenanceStatus) => {
    if (['healthy', 'due_soon', 'due', 'overdue', 'critical'].indexOf(c) >
        ['healthy', 'due_soon', 'due', 'overdue', 'critical'].indexOf(worst)) worst = c;
  };
  if (s.dueAtKm != null) {
    const left = s.dueAtKm - odometerKm;
    if (left <= -1000) bump('critical');
    else if (left < 0) bump('overdue');
    else if (left <= 50) bump('due');
    else if (left <= settings.maintenanceDueSoonKm) bump('due_soon');
  }
  if (s.dueAtDate) {
    const left = daysBetween(s.dueAtDate, now);
    if (left <= -30) bump('critical');
    else if (left < 0) bump('overdue');
    else if (left <= 1) bump('due');
    else if (left <= settings.maintenanceDueSoonDays) bump('due_soon');
  }
  return worst;
}

export function describeDue(
  s: MaintenanceSchedule, odometerKm: number, now: number,
): string {
  const bits: string[] = [];
  if (s.dueAtKm != null) {
    const left = s.dueAtKm - odometerKm;
    bits.push(`${Math.abs(Math.round(left)).toLocaleString()} km ${left < 0 ? 'overdue' : 'remaining'}`);
  }
  if (s.dueAtDate) {
    const left = daysBetween(s.dueAtDate, now);
    bits.push(`${Math.abs(left)} days ${left < 0 ? 'overdue' : 'remaining'}`);
  }
  return bits.join(' · ') || 'No threshold set';
}

export function maintenanceHealth(counts: {
  overdue: number; critical: number; due: number; dueSoon: number;
  openWorkOrders: number; repeatFailures: number;
}, weights: Record<string, number>): number {
  const w = {
    overdue: 25, critical: 30, due: 10, due_soon: 4,
    open_work_order: 6, repeat_failure: 15, ...weights,
  };
  const penalty =
    counts.overdue * w.overdue + counts.critical * w.critical + counts.due * w.due +
    counts.dueSoon * w.due_soon + counts.openWorkOrders * w.open_work_order +
    counts.repeatFailures * w.repeat_failure;
  return Math.max(0, Math.min(100, Math.round(100 - penalty)));
}

export function documentStatus(expiryIso: string, now: number, warnDays = 30): DocStatus {
  const days = daysBetween(expiryIso, now);
  if (days < 0) return 'expired';
  if (days <= warnDays) return 'expiring_soon';
  return 'valid';
}

export function slaState(t: Task, now: number, atRiskMinutes = 15): SlaState {
  if (!t.slaDueAt) return 'none';
  if (t.status === 'completed') return (t.completedAt ?? now) <= t.slaDueAt ? 'met' : 'breached';
  if (t.status === 'cancelled' || t.status === 'failed') return 'none';
  const reference = t.eta ?? now;
  if (reference > t.slaDueAt || now > t.slaDueAt) return 'breached';
  if (t.slaDueAt - reference <= atRiskMinutes * 60000) return 'at_risk';
  return 'on_track';
}

export function slaMinutesRemaining(t: Task, now: number): number | null {
  if (!t.slaDueAt) return null;
  return Math.round((t.slaDueAt - now) / 60000);
}

export function safetyScore(
  counts: Record<string, number>, distanceKm: number, weights: Record<string, number>,
): number {
  const w = {
    overspeed: 6, harsh_braking: 4, harsh_acceleration: 3.5, harsh_cornering: 3,
    route_deviation: 2, incident: 12, ...weights,
  } as Record<string, number>;
  const exposure = Math.max(distanceKm, 25) / 100;
  const penalty = Object.entries(counts)
    .reduce((s, [k, n]) => s + (w[k] ?? 1) * n, 0) / exposure;
  return Math.round(Math.max(0, Math.min(100, 100 - penalty)) * 10) / 10;
}

export function fatigueRisk(hours: number): 'low' | 'moderate' | 'elevated' | 'high' {
  if (hours >= 9) return 'high';
  if (hours >= 7) return 'elevated';
  if (hours >= 5) return 'moderate';
  return 'low';
}

export function bookValue(v: Vehicle, now: number): number {
  if (!v.purchaseValue || !v.purchaseDate) return 0;
  const years = Math.max(0, (now - Date.parse(v.purchaseDate + 'T00:00:00Z')) / (365.25 * 86400000));
  const life = Math.max(1, v.depreciationYears);
  const annual = (v.purchaseValue - v.residualValue) / life;
  return Math.round(Math.max(v.residualValue, v.purchaseValue - annual * years) * 100) / 100;
}

export function annualDepreciation(v: Vehicle): number {
  if (!v.purchaseValue) return 0;
  return Math.round(((v.purchaseValue - v.residualValue) / Math.max(1, v.depreciationYears)) * 100) / 100;
}

export function co2ForTrip(
  litres: number, kwh: number, fuel: string, s: OrgSettings,
): number {
  if (fuel === 'electric') return Math.round(kwh * s.co2PerKwh * 1000) / 1000;
  const f = fuel === 'petrol' ? s.co2PerLitrePetrol : s.co2PerLitreDiesel;
  return Math.round(litres * f * 1000) / 1000;
}

export const SEVERITY_RANK: Record<string, number> = {
  critical: 0, high: 1, medium: 2, low: 3,
};

export function driverFatigue(d: Driver) {
  return fatigueRisk(d.dutyHoursToday);
}
