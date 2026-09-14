// Fleet Intelligence.
//
// This is a rule-based layer over the organization's own data, and it says so.
// Nothing here writes state: every recommendation is advisory until a person
// confirms it, and the confirm path runs the same actions the UI uses (spec 45).

import { assignTask, createWorkOrder, cancelTask, maintenanceImpact } from './actions';
import { isOpen } from './alerts';
import { describeDue } from './derive';
import { haversine } from './geo';
import {
  ACTIVE_TASK_STATUSES, analytics, costSummary, fleetRows, fuelSummary,
  maintenanceSummary, sustainability, vehicleHealth,
} from './selectors';
import type { Store } from './store';
import type { Recommendation } from './types';

const DAY = 86400000;
const HOUR = 3600000;
const MIN = 60000;

// --------------------------------------------------------------------------
// Copilot: proactive recommendations
// --------------------------------------------------------------------------
export function generateRecommendations(store: Store): Recommendation[] {
  const s = store.state;
  const existing = new Set(
    s.recommendations.filter((r) => r.status === 'pending')
      .map((r) => `${r.kind}:${r.entityId ?? ''}`));
  const made: Recommendation[] = [];

  const add = (r: Omit<Recommendation, 'id' | 'createdAt' | 'status' | 'source'>) => {
    const key = `${r.kind}:${r.entityId ?? ''}`;
    if (existing.has(key)) return;
    existing.add(key);
    const rec: Recommendation = {
      ...r, id: store.id('rc'), createdAt: s.now, status: 'pending', source: 'copilot',
    };
    s.recommendations.unshift(rec);
    made.push(rec);
  };

  // 1. Late tasks that a closer vehicle could still save.
  const rows = fleetRows(store);
  s.tasks
    .filter((t) => ACTIVE_TASK_STATUSES.includes(t.status) &&
                   (t.slaState === 'at_risk' || t.slaState === 'breached'))
    .forEach((t) => {
      const current = store.vehicle(t.vehicleId);
      if (!current?.lat) return;
      const currentR = store.graph.route([[current.lon!, current.lat], [t.lon, t.lat]]);
      if (!currentR.ok) return;
      const better = rows
        .filter((r) => r.vehicle.id !== current.id && r.vehicle.lat != null &&
                       r.vehicle.lifecycle === 'active' && r.taskCount <= 2)
        .map((r) => {
          const rr = store.graph.route([[r.vehicle.lon!, r.vehicle.lat!], [t.lon, t.lat]]);
          return { row: r, durationS: rr.ok ? rr.durationS : Infinity };
        })
        .filter((c) => c.durationS < currentR.durationS - 240)
        .sort((a, b) => a.durationS - b.durationS)[0];
      if (!better) return;
      const savedMin = Math.round((currentR.durationS - better.durationS) / 60);
      add({
        kind: 'reassign_task',
        title: `${t.reference} could arrive ${savedMin} min sooner`,
        situation: `${t.reference} (${t.title}) is ${t.slaState.replace('_', ' ')} with ` +
                   `${current.name} ${Math.round(currentR.durationS / 60)} minutes away.`,
        evidence: [
          `${current.name} → customer: ${Math.round(currentR.durationS / 60)} min, ` +
          `${(currentR.distanceM / 1000).toFixed(1)} km`,
          `${better.row.vehicle.name} → customer: ${Math.round(better.durationS / 60)} min`,
          `${better.row.vehicle.name} currently has ${better.row.taskCount} active task` +
          `${better.row.taskCount === 1 ? '' : 's'}`,
        ],
        recommendation: `Reassign ${t.reference} to ${better.row.vehicle.name}` +
                        (better.row.driver ? ` (${better.row.driver.fullName})` : '') + '.',
        expectedImpact: `Saves about ${savedMin} minutes and may keep the SLA.`,
        severity: t.slaState === 'breached' ? 'critical' : 'high',
        entityType: 'task', entityId: t.id,
        action: {
          type: 'reassign_task', taskId: t.id,
          vehicleId: better.row.vehicle.id, driverId: better.row.driver?.id,
        },
      });
    });

  // 2. Maintenance window that costs the least operationally.
  s.schedules
    .filter((sc) => sc.active && (sc.status === 'overdue' || sc.status === 'critical' ||
                                  sc.status === 'due'))
    .forEach((sc) => {
      const v = store.vehicle(sc.vehicleId);
      if (!v) return;
      const hasOpen = s.workOrders.some(
        (w) => w.vehicleId === v.id && w.scheduleId === sc.id &&
               !['completed', 'cancelled'].includes(w.status));
      if (hasOpen) return;
      const tomorrow = new Date(s.now + DAY);
      tomorrow.setUTCHours(9, 0, 0, 0);
      const morning = maintenanceImpact(store, v.id, tomorrow.getTime(), sc.estimatedMinutes);
      const afternoon = maintenanceImpact(
        store, v.id, tomorrow.getTime() + 5 * HOUR, sc.estimatedMinutes);
      const best = afternoon.affectedTaskCount <= morning.affectedTaskCount
        ? { slot: 'tomorrow afternoon', at: tomorrow.getTime() + 5 * HOUR, impact: afternoon }
        : { slot: 'tomorrow morning', at: tomorrow.getTime(), impact: morning };
      add({
        kind: 'schedule_maintenance',
        title: `Book ${sc.name} for ${v.name} ${best.slot}`,
        situation: `${sc.name} on ${v.name} is ${sc.status.replace('_', ' ')} — ` +
                   `${describeDue(sc, v.odometerKm, s.now)}.`,
        evidence: [
          `Morning slot would disrupt ${morning.affectedTaskCount} scheduled task` +
          `${morning.affectedTaskCount === 1 ? '' : 's'}`,
          `Afternoon slot would disrupt ${afternoon.affectedTaskCount} scheduled task` +
          `${afternoon.affectedTaskCount === 1 ? '' : 's'}`,
          `Estimated duration ${sc.estimatedMinutes} min, estimated cost €${sc.estimatedCost}`,
        ],
        recommendation: `Raise a work order for ${best.slot} at ` +
                        `${new Date(best.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}.`,
        expectedImpact: best.impact.affectedTaskCount === 0
          ? 'No scheduled work is affected in that window.'
          : `${best.impact.affectedTaskCount} task(s) would need reassigning` +
            (best.impact.alternative ? ` — ${best.impact.alternative.name} is the lightest-loaded alternative.` : '.'),
        severity: sc.status === 'critical' ? 'critical' : 'high',
        entityType: 'vehicle', entityId: v.id,
        action: {
          type: 'create_work_order', vehicleId: v.id, scheduleId: sc.id,
          title: sc.name, scheduledStart: best.at,
          expectedCompletion: best.at + sc.estimatedMinutes * MIN,
          estimatedCost: sc.estimatedCost, category: sc.category,
        },
      });
    });

  // 3. Repeat failures worth inspecting early.
  s.vehicles.forEach((v) => {
    const health = vehicleHealth(store, v.id);
    if (!health.repeatCategories.length) return;
    const top = health.repeatCategories.sort((a, b) => b.count - a.count)[0];
    add({
      kind: 'repeat_failure',
      title: `${v.name} keeps needing ${top.category.replace(/_/g, ' ')} work`,
      situation: `${v.name} has had ${top.count} ${top.category.replace(/_/g, ' ')} ` +
                 `repairs in the last six months.`,
      evidence: health.repeatCategories.map(
        (c) => `${c.category.replace(/_/g, ' ')}: ${c.count} repairs in 180 days`),
      recommendation: `Inspect the ${top.category.replace(/_/g, ' ')} system before the ` +
                      `next scheduled service rather than after the next failure.`,
      expectedImpact: 'Breaks the repeat-repair cycle and avoids another unplanned day off the road.',
      severity: 'medium', entityType: 'vehicle', entityId: v.id,
      action: {
        type: 'create_work_order', vehicleId: v.id,
        title: `Diagnostic inspection — ${top.category.replace(/_/g, ' ')}`,
        category: top.category, priority: 'high',
      },
    });
  });

  // 4. EV transition candidates, from real daily-distance patterns.
  const sus = sustainability(store, 90);
  sus.candidates.slice(0, 2).forEach((c) => {
    add({
      kind: 'ev_transition',
      title: `${c.vehicle.name} fits comfortably inside EV range`,
      situation: `${c.vehicle.name} averages ${c.avgDailyKm.toFixed(0)} km a day and has ` +
                 `never exceeded ${c.maxDailyKm.toFixed(0)} km in the last 90 days.`,
      evidence: [
        `Average daily distance: ${c.avgDailyKm.toFixed(0)} km`,
        `Maximum daily distance: ${c.maxDailyKm.toFixed(0)} km ` +
        `(practical EV range threshold: ${s.org.settings.evCandidateDailyKm} km)`,
        `Current fuel cost over 90 days: €${c.fuelCost.toFixed(0)}`,
        `Estimated electricity cost for the same distance: €${c.evCost.toFixed(0)}`,
      ],
      recommendation: `Shortlist ${c.vehicle.name} for replacement with an electric van at ` +
                      `its next renewal.`,
      expectedImpact: `About €${Math.round(c.savingPerYear)} a year in running cost and ` +
                      `${Math.round(c.co2SavingPerYear)} kg less CO₂.`,
      severity: 'low', entityType: 'vehicle', entityId: c.vehicle.id,
    });
  });

  // 5. Unassigned work that is running out of time.
  const urgent = s.tasks.filter(
    (t) => t.status === 'unassigned' && t.slaDueAt && t.slaDueAt - s.now < 2 * HOUR);
  if (urgent.length) {
    const idle = rows.filter((r) => r.taskCount === 0 && r.vehicle.lifecycle === 'active'
                                    && r.vehicle.lat != null);
    add({
      kind: 'unassigned_backlog',
      title: `${urgent.length} unassigned task${urgent.length === 1 ? '' : 's'} due within two hours`,
      situation: `${urgent.map((t) => t.reference).join(', ')} ` +
                 `${urgent.length === 1 ? 'is' : 'are'} still unassigned.`,
      evidence: [
        ...urgent.slice(0, 4).map(
          (t) => `${t.reference} — ${t.title}, due ${new Date(t.slaDueAt!).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`),
        `${idle.length} vehicle${idle.length === 1 ? '' : 's'} currently carrying no work`,
      ],
      recommendation: idle.length
        ? `Assign the backlog to ${idle.slice(0, 2).map((r) => r.vehicle.name).join(' and ')}.`
        : 'Every vehicle is already loaded — consider moving the least urgent work to tomorrow.',
      expectedImpact: 'Prevents an avoidable SLA breach on each task.',
      severity: 'high', entityType: 'dispatch', entityId: 'backlog',
    });
  }

  // 6. Fuel anomaly against the vehicle's own baseline.
  const fuel = fuelSummary(store, 30);
  const prior = fuelSummary(store, 90);
  fuel.perVehicle.forEach((row) => {
    if (row.electric || !row.efficiency) return;
    const base = prior.perVehicle.find((p) => p.vehicle.id === row.vehicle.id);
    if (!base?.efficiency) return;
    const delta = ((row.efficiency - base.efficiency) / base.efficiency) * 100;
    if (delta < 12) return;
    add({
      kind: 'fuel_anomaly',
      title: `${row.vehicle.name} is using ${delta.toFixed(0)}% more fuel than its own baseline`,
      situation: `Consumption over 30 days is ${row.efficiency.toFixed(1)} L/100km against a ` +
                 `90-day baseline of ${base.efficiency.toFixed(1)} L/100km.`,
      evidence: [
        `Last 30 days: ${row.efficiency.toFixed(1)} L/100km over ${row.distanceKm.toFixed(0)} km`,
        `90-day baseline: ${base.efficiency.toFixed(1)} L/100km`,
        `Extra cost at the current rate: about €${(((row.efficiency - base.efficiency) / 100) * row.distanceKm * s.org.settings.fuelPricePerLitre).toFixed(0)} over the period`,
      ],
      recommendation: 'Check tyre pressures, the air filter and recent driving behaviour ' +
                      'before the next service.',
      expectedImpact: 'Returning to baseline recovers the extra fuel spend.',
      severity: 'medium', entityType: 'vehicle', entityId: row.vehicle.id,
    });
  });

  if (made.length) store.emit();
  return made;
}

/** Execute a recommendation - only ever called after explicit confirmation. */
export function applyRecommendation(store: Store, id: string): string {
  const rec = store.state.recommendations.find((r) => r.id === id);
  if (!rec) throw new Error('That recommendation no longer exists.');
  if (rec.status !== 'pending') throw new Error('This recommendation has already been handled.');
  const a = rec.action as Record<string, string | number> | undefined;
  let note = 'Applied.';

  if (a?.type === 'reassign_task') {
    assignTask(store, String(a.taskId), a.driverId ? String(a.driverId) : undefined,
               String(a.vehicleId));
    note = `Task reassigned to ${store.vehicle(String(a.vehicleId))?.name}.`;
  } else if (a?.type === 'create_work_order') {
    const wo = createWorkOrder(store, {
      vehicleId: String(a.vehicleId),
      title: String(a.title),
      category: a.category ? String(a.category) : undefined,
      scheduleId: a.scheduleId ? String(a.scheduleId) : undefined,
      scheduledStart: a.scheduledStart ? Number(a.scheduledStart) : undefined,
      expectedCompletion: a.expectedCompletion ? Number(a.expectedCompletion) : undefined,
      estimatedCost: a.estimatedCost ? Number(a.estimatedCost) : undefined,
      priority: 'high',
      acknowledgeConflict: true,
    });
    note = `Work order ${wo.reference} raised.`;
  } else if (a?.type === 'cancel_tasks') {
    const ids = String(a.taskIds).split(',');
    ids.forEach((tid) => { try { cancelTask(store, tid, String(a.reason ?? 'AI action')); } catch { /* already closed */ } });
    note = `${ids.length} task(s) cancelled.`;
  } else {
    note = 'Recorded as accepted. No automatic change was applied to this advisory item.';
  }

  rec.status = 'applied';
  rec.appliedAt = store.state.now;
  rec.appliedBy = store.me.id;
  rec.resultNote = note;
  store.audit({
    action: 'ai.recommendation_applied', entityType: 'ai_recommendation',
    entityLabel: rec.title, summary: `AI recommendation applied: ${rec.title} — ${note}`,
    after: { action: rec.action },
  });
  store.emit();
  return note;
}

export function dismissRecommendation(store: Store, id: string, reason?: string) {
  const rec = store.state.recommendations.find((r) => r.id === id);
  if (!rec) return;
  rec.status = 'dismissed';
  rec.dismissedAt = store.state.now;
  rec.resultNote = reason;
  store.audit({
    action: 'ai.recommendation_dismissed', entityType: 'ai_recommendation',
    entityLabel: rec.title, summary: `AI recommendation dismissed: ${rec.title}`,
  });
  store.emit();
}

// --------------------------------------------------------------------------
// Assistant: natural-language questions over the org's own data
// --------------------------------------------------------------------------
export interface AssistantAnswer {
  answer: string;
  table?: { columns: string[]; rows: (string | number)[][] };
  followUps: string[];
  /** Set when the question asks for a change rather than an answer. */
  proposal?: {
    summary: string;
    affected: { label: string; detail: string }[];
    action: Record<string, unknown>;
  };
}

export const SUGGESTED_QUESTIONS = [
  'Which vehicle cost the most this month?',
  'Which vehicles are overdue for maintenance?',
  'Show me drivers with declining safety scores',
  'Which tasks are likely to be late?',
  'What is our SLA compliance this month?',
  'Which vehicles could switch to electric?',
  'Cancel tomorrow’s tasks for vehicles scheduled for maintenance',
];

export function ask(store: Store, question: string): AssistantAnswer {
  const s = store.state;
  const q = question.toLowerCase();
  const money = (n: number) => `€${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

  // --- agentic: cancel tomorrow's tasks for vehicles in maintenance ---
  if (q.includes('cancel') && q.includes('task')) {
    const tomorrowStart = new Date(s.now + DAY);
    tomorrowStart.setUTCHours(0, 0, 0, 0);
    const tomorrowEnd = tomorrowStart.getTime() + DAY;
    const maintenanceVehicles = new Set([
      ...s.vehicles.filter((v) => v.lifecycle === 'maintenance').map((v) => v.id),
      ...s.workOrders
        .filter((w) => ['scheduled', 'in_progress', 'waiting_for_parts', 'approved']
          .includes(w.status) && w.scheduledStart &&
          w.scheduledStart >= tomorrowStart.getTime() && w.scheduledStart < tomorrowEnd)
        .map((w) => w.vehicleId),
    ]);
    const affected = s.tasks.filter(
      (t) => t.vehicleId && maintenanceVehicles.has(t.vehicleId) &&
             t.scheduledFor && t.scheduledFor >= tomorrowStart.getTime() &&
             t.scheduledFor < tomorrowEnd &&
             !['completed', 'cancelled', 'failed'].includes(t.status));
    if (!affected.length) {
      return {
        answer: 'No tasks are scheduled tomorrow for vehicles that are in, or booked into, ' +
                'the workshop. Nothing needs cancelling.',
        followUps: ['Which vehicles are overdue for maintenance?',
                    'Which tasks are likely to be late?'],
      };
    }
    return {
      answer: `I found ${affected.length} task${affected.length === 1 ? '' : 's'} scheduled ` +
              `tomorrow on ${maintenanceVehicles.size} vehicle(s) that will be in the ` +
              `workshop. Nothing has changed yet — review the list and confirm.`,
      proposal: {
        summary: `Cancel ${affected.length} task${affected.length === 1 ? '' : 's'} ` +
                 `on vehicles booked for maintenance tomorrow`,
        affected: affected.map((t) => ({
          label: `${t.reference} — ${t.title}`,
          detail: `${store.vehicle(t.vehicleId)?.name ?? 'Vehicle'} · ` +
                  `${new Date(t.scheduledFor!).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · ` +
                  `currently ${t.status.replace('_', ' ')}`,
        })),
        action: {
          type: 'cancel_tasks', taskIds: affected.map((t) => t.id).join(','),
          reason: 'Vehicle scheduled for maintenance',
        },
      },
      followUps: ['Which vehicles are overdue for maintenance?'],
    };
  }

  // --- cost ---
  if ((q.includes('cost') || q.includes('expensive') || q.includes('spend')) &&
      (q.includes('vehicle') || q.includes('most') || q.includes('which'))) {
    const rows = s.vehicles.map((v) => {
      const c = costSummary(store, 1, v.id);
      return { v, total: c.operating, perKm: c.costPerKm ?? 0, km: c.distanceKm };
    }).filter((r) => r.total > 0).sort((a, b) => b.total - a.total);
    if (!rows.length) return { answer: 'No costs are recorded for this period yet.', followUps: [] };
    const top = rows[0];
    return {
      answer: `${top.v.name} (${top.v.plate}) cost the most over the last 30 days at ` +
              `${money(top.total)} — ${top.km.toFixed(0)} km driven, ` +
              `€${top.perKm.toFixed(2)} per km.`,
      table: {
        columns: ['Vehicle', 'Plate', 'Total', 'Distance', '€/km'],
        rows: rows.slice(0, 8).map((r) => [
          r.v.name, r.v.plate, money(r.total), `${r.km.toFixed(0)} km`,
          `€${r.perKm.toFixed(2)}`]),
      },
      followUps: ['Which vehicles are overdue for maintenance?',
                  'Which vehicles could switch to electric?'],
    };
  }

  // --- maintenance ---
  if (q.includes('maintenance') || q.includes('service') || q.includes('overdue')) {
    const rows = s.schedules
      .filter((sc) => sc.active && ['overdue', 'critical', 'due'].includes(sc.status))
      .map((sc) => {
        const v = store.vehicle(sc.vehicleId)!;
        return { sc, v };
      })
      .sort((a, b) => (a.sc.dueAtKm ?? 0) - (a.v.odometerKm) -
                      ((b.sc.dueAtKm ?? 0) - b.v.odometerKm));
    const m = maintenanceSummary(store);
    if (!rows.length) {
      return {
        answer: 'Nothing is overdue. ' +
                `${m.dueSoon} service${m.dueSoon === 1 ? '' : 's'} ` +
                `${m.dueSoon === 1 ? 'is' : 'are'} approaching their threshold.`,
        followUps: ['Which vehicle cost the most this month?'],
      };
    }
    return {
      answer: `${rows.length} service${rows.length === 1 ? '' : 's'} ` +
              `${rows.length === 1 ? 'is' : 'are'} due or overdue across ` +
              `${new Set(rows.map((r) => r.v.id)).size} vehicle(s). ` +
              `${m.overdue} overdue, ${m.critical} critical, ${m.due} due now.`,
      table: {
        columns: ['Vehicle', 'Service', 'Status', 'Due'],
        rows: rows.slice(0, 10).map((r) => [
          `${r.v.name} (${r.v.plate})`, r.sc.name,
          r.sc.status.replace('_', ' '), describeDue(r.sc, r.v.odometerKm, s.now)]),
      },
      followUps: ['Which tasks are likely to be late?',
                  'Cancel tomorrow’s tasks for vehicles scheduled for maintenance'],
    };
  }

  // --- driver safety ---
  if (q.includes('safety') || q.includes('driver') || q.includes('declining') ||
      q.includes('score')) {
    const rows = s.drivers
      .map((d) => ({ d, trend: d.safetyScore - d.previousSafetyScore }))
      .sort((a, b) => a.trend - b.trend);
    const declining = rows.filter((r) => r.trend < 0);
    return {
      answer: declining.length
        ? `${declining.length} driver${declining.length === 1 ? '' : 's'} ` +
          `${declining.length === 1 ? 'has' : 'have'} a falling safety score. ` +
          `${declining[0].d.fullName} has dropped the most, ` +
          `${Math.abs(declining[0].trend).toFixed(1)} points to ` +
          `${declining[0].d.safetyScore.toFixed(1)}.`
        : 'No driver is trending downward right now.',
      table: {
        columns: ['Driver', 'Score', 'Trend', 'Points', 'Events (30d)'],
        rows: rows.slice(0, 8).map((r) => [
          r.d.fullName, r.d.safetyScore.toFixed(1),
          `${r.trend >= 0 ? '+' : ''}${r.trend.toFixed(1)}`,
          r.d.points,
          s.driverEvents.filter((e) => e.driverId === r.d.id &&
            e.occurredAt >= s.now - 30 * DAY).length]),
      },
      followUps: ['Which tasks are likely to be late?'],
    };
  }

  // --- late tasks ---
  if (q.includes('late') || q.includes('sla') || q.includes('delay')) {
    const at = s.tasks.filter(
      (t) => ACTIVE_TASK_STATUSES.includes(t.status) &&
             (t.slaState === 'at_risk' || t.slaState === 'breached'));
    const a = analytics(store, 30);
    if (q.includes('compliance') || q.includes('sla compliance')) {
      return {
        answer: `SLA compliance over the last 30 days is ${a.slaCompliance.toFixed(1)}% ` +
                `across ${a.tasksCompleted} completed tasks. ${at.length} live task` +
                `${at.length === 1 ? ' is' : 's are'} currently at risk or breached.`,
        followUps: ['Which tasks are likely to be late?'],
      };
    }
    return {
      answer: at.length
        ? `${at.length} task${at.length === 1 ? '' : 's'} ` +
          `${at.length === 1 ? 'is' : 'are'} at risk or already past the deadline.`
        : 'No live task is at risk right now.',
      table: at.length ? {
        columns: ['Task', 'Customer', 'Vehicle', 'ETA', 'Deadline', 'State'],
        rows: at.slice(0, 10).map((t) => [
          t.reference, t.title.split(' — ')[1] ?? '—',
          store.vehicle(t.vehicleId)?.name ?? 'Unassigned',
          t.eta ? new Date(t.eta).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—',
          t.slaDueAt ? new Date(t.slaDueAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—',
          t.slaState.replace('_', ' ')]),
      } : undefined,
      followUps: ['What is our SLA compliance this month?',
                  'Which vehicles are overdue for maintenance?'],
    };
  }

  // --- EV ---
  if (q.includes('electric') || q.includes(' ev') || q.startsWith('ev')) {
    const sus = sustainability(store, 90);
    return {
      answer: sus.candidates.length
        ? `${sus.candidates.length} vehicle${sus.candidates.length === 1 ? '' : 's'} ` +
          `never exceeded ${s.org.settings.evCandidateDailyKm} km in a day over the last ` +
          `90 days, so they fit comfortably inside practical EV range.`
        : 'No combustion vehicle currently fits the EV range test.',
      table: sus.candidates.length ? {
        columns: ['Vehicle', 'Avg/day', 'Max/day', 'Fuel (90d)', 'Est. EV cost', 'Saving/yr'],
        rows: sus.candidates.map((c) => [
          `${c.vehicle.name} (${c.vehicle.plate})`,
          `${c.avgDailyKm.toFixed(0)} km`, `${c.maxDailyKm.toFixed(0)} km`,
          money(c.fuelCost), money(c.evCost), money(c.savingPerYear)]),
      } : undefined,
      followUps: ['Which vehicle cost the most this month?'],
    };
  }

  // --- utilisation / general ---
  if (q.includes('utilis') || q.includes('utiliz') || q.includes('busiest') ||
      q.includes('idle')) {
    const a = analytics(store, 30);
    return {
      answer: `Fleet utilisation averages ` +
              `${(a.utilisation.reduce((x, u) => x + u.utilisationPct, 0) / Math.max(1, a.utilisation.length)).toFixed(0)}% ` +
              `over 30 days. Idle time is ${a.idleSharePct.toFixed(1)}% of engine-on time.`,
      table: {
        columns: ['Vehicle', 'Utilisation', 'Distance', 'Trips'],
        rows: a.utilisation.slice(0, 8).map((u) => [
          u.vehicle.name, `${u.utilisationPct}%`,
          `${u.distanceKm.toFixed(0)} km`, u.trips]),
      },
      followUps: ['Which vehicle cost the most this month?'],
    };
  }

  // --- fallback: an honest one ---
  const openAlerts = s.alerts.filter(isOpen).length;
  return {
    answer: `I can answer questions about cost, maintenance, driver safety, SLA and ` +
            `delays, utilisation and EV suitability, using this organization's own data. ` +
            `Right now there ${openAlerts === 1 ? 'is' : 'are'} ${openAlerts} open alert` +
            `${openAlerts === 1 ? '' : 's'} and ` +
            `${s.tasks.filter((t) => ACTIVE_TASK_STATUSES.includes(t.status)).length} active tasks. ` +
            `I could not match “${question.trim()}” to one of those, so try one of these:`,
    followUps: SUGGESTED_QUESTIONS.slice(0, 5),
  };
}

/**
 * Execute an assistant proposal, but only after a person has confirmed it.
 *
 * The assistant never calls this itself: `ask()` returns the proposal, the UI shows
 * exactly what would change, and this runs only from the confirm button (spec 45).
 */
export function applyProposal(
  store: Store, proposal: NonNullable<AssistantAnswer['proposal']>,
): string {
  const a = proposal.action as Record<string, string | number>;
  let note: string;

  if (a.type === 'cancel_tasks') {
    const ids = String(a.taskIds).split(',').filter(Boolean);
    let done = 0;
    ids.forEach((id) => {
      try { cancelTask(store, id, String(a.reason ?? 'Confirmed AI action')); done++; }
      catch { /* the task closed between proposal and confirmation */ }
    });
    note = `${done} of ${ids.length} task(s) cancelled.` +
      (done < ids.length ? ' The rest had already closed.' : '');
  } else {
    throw new Error('This proposal has no executable action.');
  }

  store.audit({
    action: 'ai.proposal_applied', entityType: 'ai_assistant',
    entityLabel: proposal.summary,
    summary: `AI proposal confirmed by ${store.me.fullName}: ${proposal.summary} — ${note}`,
    after: { action: proposal.action },
  });
  store.emit();
  return note;
}

// --------------------------------------------------------------------------
// Anomaly detection against baselines
// --------------------------------------------------------------------------
export function anomalies(store: Store) {
  const s = store.state;
  const out: {
    kind: string; subject: string; detail: string; severity: 'low' | 'medium' | 'high';
    baseline: string; observed: string; entityType: string; entityId: string;
  }[] = [];

  const recent = fuelSummary(store, 30);
  const base = fuelSummary(store, 90);
  recent.perVehicle.forEach((r) => {
    if (!r.efficiency) return;
    const b = base.perVehicle.find((x) => x.vehicle.id === r.vehicle.id);
    if (!b?.efficiency) return;
    const delta = ((r.efficiency - b.efficiency) / b.efficiency) * 100;
    if (Math.abs(delta) < 10) return;
    out.push({
      kind: 'fuel_consumption', subject: `${r.vehicle.name} (${r.vehicle.plate})`,
      detail: `Consumption is ${Math.abs(delta).toFixed(0)}% ${delta > 0 ? 'higher' : 'lower'} ` +
              `than this vehicle's own 90-day baseline.`,
      severity: Math.abs(delta) > 20 ? 'high' : 'medium',
      baseline: `${b.efficiency.toFixed(1)} ${r.unit}`,
      observed: `${r.efficiency.toFixed(1)} ${r.unit}`,
      entityType: 'vehicle', entityId: r.vehicle.id,
    });
  });

  // idle time against the fleet baseline
  const since30 = s.now - 30 * DAY;
  const fleetIdle = (() => {
    const trips = s.trips.filter((t) => t.startedAt >= since30);
    const drive = trips.reduce((a, t) => a + t.durationS, 0);
    const idle = trips.reduce((a, t) => a + t.idleS, 0);
    return drive ? (idle / drive) * 100 : 0;
  })();
  s.vehicles.forEach((v) => {
    const trips = s.trips.filter((t) => t.vehicleId === v.id && t.startedAt >= since30);
    if (trips.length < 5) return;
    const drive = trips.reduce((a, t) => a + t.durationS, 0);
    const idle = trips.reduce((a, t) => a + t.idleS, 0);
    const pct = drive ? (idle / drive) * 100 : 0;
    if (pct > fleetIdle * 1.4 && pct > 18) {
      out.push({
        kind: 'idle_time', subject: `${v.name} (${v.plate})`,
        detail: 'Idle time is well above the fleet norm for the same period.',
        severity: pct > fleetIdle * 1.8 ? 'high' : 'medium',
        baseline: `${fleetIdle.toFixed(1)}% fleet average`,
        observed: `${pct.toFixed(1)}% of engine-on time`,
        entityType: 'vehicle', entityId: v.id,
      });
    }
  });

  // driver event rate against their own history
  s.drivers.forEach((d) => {
    const recentN = s.driverEvents.filter(
      (e) => e.driverId === d.id && e.occurredAt >= s.now - 7 * DAY).length;
    const priorN = s.driverEvents.filter(
      (e) => e.driverId === d.id && e.occurredAt >= s.now - 35 * DAY &&
             e.occurredAt < s.now - 7 * DAY).length / 4;
    if (recentN >= 3 && recentN > priorN * 1.6) {
      out.push({
        kind: 'driving_pattern', subject: d.fullName,
        detail: 'Safety events this week are well above this driver’s recent weekly rate.',
        severity: recentN > priorN * 2.2 ? 'high' : 'medium',
        baseline: `${priorN.toFixed(1)} events/week`,
        observed: `${recentN} events this week`,
        entityType: 'driver', entityId: d.id,
      });
    }
  });

  // live route deviation
  s.vehicles.forEach((v) => {
    if (v.lat == null) return;
    const route = s.routes.find((r) => r.vehicleId === v.id && r.active);
    if (!route?.geometry.length) return;
    let best = Infinity;
    route.geometry.forEach((p) => {
      const dd = haversine(v.lon!, v.lat!, p[0], p[1]);
      if (dd < best) best = dd;
    });
    if (best > 250) {
      out.push({
        kind: 'route_deviation', subject: `${v.name} (${v.plate})`,
        detail: `Currently off the planned corridor toward ${route.destName}.`,
        severity: best > 500 ? 'high' : 'medium',
        baseline: 'within 250 m of the planned route',
        observed: `${Math.round(best)} m away`,
        entityType: 'vehicle', entityId: v.id,
      });
    }
  });

  const rank = { high: 0, medium: 1, low: 2 };
  return out.sort((a, b) => rank[a.severity] - rank[b.severity]);
}

// --------------------------------------------------------------------------
// Automated reports
// --------------------------------------------------------------------------
export function periodReport(store: Store, days: 7 | 30) {
  const s = store.state;
  const now = analytics(store, days);
  const prior = analytics(store, days * 2);
  // the earlier half, derived by subtracting the recent half from the double window
  const priorHalf = {
    distanceKm: prior.distanceKm - now.distanceKm,
    tasksCompleted: prior.tasksCompleted - now.tasksCompleted,
    events: prior.events - now.events,
    co2Kg: prior.co2Kg - now.co2Kg,
  };
  const pct = (a: number, b: number) => (b > 0 ? ((a - b) / b) * 100 : 0);

  const improved: string[] = [];
  const worse: string[] = [];
  const record = (label: string, delta: number, goodWhenUp: boolean) => {
    if (Math.abs(delta) < 3) return;
    const line = `${label} ${delta > 0 ? 'up' : 'down'} ${Math.abs(delta).toFixed(0)}%`;
    ((delta > 0) === goodWhenUp ? improved : worse).push(line);
  };
  record('Distance covered', pct(now.distanceKm, priorHalf.distanceKm), true);
  record('Tasks completed', pct(now.tasksCompleted, priorHalf.tasksCompleted), true);
  record('Safety events', pct(now.events, priorHalf.events), false);
  record('CO₂ emitted', pct(now.co2Kg, priorHalf.co2Kg), false);

  const m = maintenanceSummary(store);
  const risks: string[] = [];
  if (m.overdue + m.critical > 0) {
    risks.push(`${m.overdue + m.critical} service${m.overdue + m.critical === 1 ? '' : 's'} overdue or critical`);
  }
  const expiring = s.documents.filter((d) => {
    const days2 = (Date.parse(d.expiryDate) - s.now) / DAY;
    return days2 >= 0 && days2 <= 30;
  }).length;
  if (expiring) risks.push(`${expiring} document(s) expiring within 30 days`);
  const breached = s.tasks.filter((t) => t.slaState === 'breached').length;
  if (breached) risks.push(`${breached} task(s) currently past their SLA deadline`);
  const openCritical = s.alerts.filter((a) => isOpen(a) && a.severity === 'critical').length;
  if (openCritical) risks.push(`${openCritical} unresolved critical alert(s)`);

  const actions: string[] = [];
  if (m.overdue + m.critical) actions.push('Book the overdue services into the workshop queue.');
  if (breached) actions.push('Review the breached deliveries with dispatch and the customers.');
  if (expiring) actions.push('Renew the documents expiring inside the next 30 days.');
  const worstDriver = [...s.drivers].sort((a, b) => a.safetyScore - b.safetyScore)[0];
  if (worstDriver && worstDriver.safetyScore < 80) {
    actions.push(`Arrange a coaching session with ${worstDriver.fullName} (score ${worstDriver.safetyScore.toFixed(1)}).`);
  }
  if (!actions.length) actions.push('No corrective action outstanding — keep the current pattern.');

  return {
    period: days === 7 ? 'Last 7 days' : 'Last 30 days',
    generatedAt: s.now,
    happened: [
      `${now.trips} trips covering ${now.distanceKm.toFixed(0)} km`,
      `${now.tasksCompleted} tasks completed, ${now.tasksFailed} failed`,
      `SLA compliance ${now.slaCompliance.toFixed(1)}%`,
      `${now.events} safety events across ${s.drivers.length} drivers`,
      `${now.co2Kg.toFixed(0)} kg CO₂ emitted`,
    ],
    improved: improved.length ? improved : ['No metric moved materially in the right direction.'],
    deteriorated: worse.length ? worse : ['Nothing deteriorated materially.'],
    risks: risks.length ? risks : ['No material risk outstanding.'],
    actions,
    metrics: now,
  };
}

export function csvFor(columns: string[], rows: (string | number)[][]): string {
  const esc = (v: string | number) => {
    const str = String(v ?? '');
    return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
  };
  return [columns.map(esc).join(','), ...rows.map((r) => r.map(esc).join(','))].join('\n');
}
