// Alert raising with cooldown, deduplication and escalation (spec 6.7/6.8).

import type { Store } from './store';
import type { Alert, AlertCategory, Severity } from './types';

export interface RaiseOptions {
  code: string;
  title: string;
  detail?: string;
  severity?: Severity;
  category?: AlertCategory;
  vehicleId?: string;
  driverId?: string;
  tripId?: string;
  taskId?: string;
  geofenceId?: string;
  workOrderId?: string;
  documentId?: string;
  lat?: number;
  lon?: number;
  street?: string;
  evidence?: Record<string, unknown>;
  dedupeExtra?: string;
  at?: number;
  notify?: boolean;
}

const OPEN: Alert['status'][] = ['triggered', 'acknowledged', 'investigating', 'escalated'];

export function isOpen(a: Alert): boolean {
  return OPEN.includes(a.status);
}

export function raiseAlert(store: Store, o: RaiseOptions): Alert | null {
  const s = store.state;
  const now = o.at ?? s.now;
  const rule = s.alertRules.find((r) => r.code === o.code && r.active);
  if (!rule) return null;
  if (rule.vehicleIds.length && o.vehicleId && !rule.vehicleIds.includes(o.vehicleId)) return null;
  if (rule.driverIds.length && o.driverId && !rule.driverIds.includes(o.driverId)) return null;

  const key = [o.code, o.vehicleId ?? '-', o.driverId ?? '-', o.dedupeExtra ?? '-'].join(':');
  const existing = s.alerts.find((a) => a.dedupeKey === key && isOpen(a));

  if (existing) {
    const windowMs = Math.max(rule.dedupeWindowS, rule.cooldownS) * 1000;
    if (now - existing.lastOccurrenceAt <= windowMs) {
      existing.occurrences += 1;
      existing.lastOccurrenceAt = now;
      if (o.lat != null) { existing.lat = o.lat; existing.lon = o.lon; existing.street = o.street; }
      existing.evidence = {
        ...existing.evidence, ...(o.evidence ?? {}),
        occurrences: existing.occurrences,
        window_s: Math.round((now - existing.firstOccurrenceAt) / 1000),
      };
      return existing;
    }
    if (now - existing.lastOccurrenceAt <= rule.cooldownS * 1000) return null;
  }

  const alert: Alert = {
    id: store.id('al'),
    ruleId: rule.id,
    code: o.code,
    category: o.category ?? rule.category,
    severity: o.severity ?? rule.severity,
    status: 'triggered',
    title: o.title,
    detail: o.detail ?? rule.description,
    recommendedAction: rule.recommendedAction,
    vehicleId: o.vehicleId, driverId: o.driverId, tripId: o.tripId, taskId: o.taskId,
    geofenceId: o.geofenceId, workOrderId: o.workOrderId, documentId: o.documentId,
    lat: o.lat, lon: o.lon, street: o.street,
    evidence: { ...(o.evidence ?? {}), rule: describeRule(rule) },
    triggeredAt: now,
    escalationLevel: 0,
    occurrences: 1,
    firstOccurrenceAt: now,
    lastOccurrenceAt: now,
    dedupeKey: key,
  };
  s.alerts.unshift(alert);
  if (s.alerts.length > 1200) s.alerts.length = 900;

  store.timeline({
    entityType: 'alert', entityId: alert.id, action: 'triggered',
    description: `${alert.title} triggered.`, at: now,
  });
  if (o.vehicleId) {
    store.timeline({
      entityType: 'vehicle', entityId: o.vehicleId, action: 'alert_triggered',
      description: `Alert: ${alert.title}`, relatedType: 'alert', relatedId: alert.id, at: now,
    });
  }
  if ((o.notify ?? true) && (alert.severity === 'high' || alert.severity === 'critical')) {
    s.users
      .filter((u) => rule.notifyRoles.includes(u.role))
      .forEach((u) => store.notify(u.id, {
        kind: 'urgent_alert', title: alert.title, body: alert.detail,
        link: `alerts:${alert.id}`, entityType: 'alert', entityId: alert.id,
      }));
  }
  s.lastEventAt = now;
  return alert;
}

export function describeRule(rule: {
  metric: string; operator: string; threshold?: number;
  thresholdUnit?: string; durationS: number;
}): string {
  const parts = [`WHEN ${rule.metric.replace(/_/g, ' ')}`];
  if (rule.threshold != null) {
    parts.push(`${rule.operator} ${rule.threshold}${rule.thresholdUnit ? ' ' + rule.thresholdUnit : ''}`);
  }
  if (rule.durationS) parts.push(`FOR ${rule.durationS}s`);
  return parts.join(' ');
}

/** Escalate unacknowledged high/critical alerts along the rule's ladder. */
export function escalateDue(store: Store): number {
  const s = store.state;
  let n = 0;
  s.alerts.forEach((a) => {
    if (a.status !== 'triggered' || a.acknowledgedAt) return;
    if (a.severity !== 'high' && a.severity !== 'critical') return;
    const rule = s.alertRules.find((r) => r.id === a.ruleId);
    const ladder = rule?.escalationMinutes ?? [];
    if (!ladder.length) return;
    const ageMin = (s.now - a.triggeredAt) / 60000;
    const level = ladder.filter((step) => ageMin >= step).length;
    if (level > a.escalationLevel) {
      a.escalationLevel = level;
      a.escalatedAt = s.now;
      a.status = 'escalated';
      n++;
      store.timeline({
        entityType: 'alert', entityId: a.id, action: 'escalated',
        description: `Unacknowledged for ${Math.round(ageMin)} minutes — escalated to level ${level}.`,
      });
    }
  });
  return n;
}

/** Snoozed alerts wake themselves up when their timer expires. */
export function wakeSnoozed(store: Store): number {
  const s = store.state;
  let n = 0;
  s.alerts.forEach((a) => {
    if (a.status === 'snoozed' && a.snoozedUntil && a.snoozedUntil <= s.now) {
      a.status = 'triggered';
      a.snoozedUntil = undefined;
      n++;
      store.timeline({
        entityType: 'alert', entityId: a.id, action: 'unsnoozed',
        description: 'Snooze expired — the alert is active again.',
      });
    }
  });
  return n;
}
