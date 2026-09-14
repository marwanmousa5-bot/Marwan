// Alert Operations Centre: an exception workspace, not a notification list.

import { useEffect, useMemo, useState } from 'react';
import {
  acknowledgeAlert, assignAlert, bulkAlertAction, createWorkOrder,
  escalateAlert, resolveAlert, snoozeAlert,
} from '../../engine/actions';
import { describeRule, isOpen } from '../../engine/alerts';
import { SEVERITY_RANK } from '../../engine/derive';
import { alertSummary } from '../../engine/selectors';
import type { Alert, AlertRule, Severity } from '../../engine/types';
import { useApp } from '../app-context';
import {
  Button, Card, Empty, Field, Kpi, Modal, Pill, Timeline, relTime,
  titleCase, type Tone,
} from '../components/kit';
import { IconAlert, IconWrench } from '../icons';

type View = 'all' | 'active' | 'unacknowledged' | 'mine' | 'escalated' | 'snoozed' | 'resolved';

const VIEWS: { key: View; label: string }[] = [
  { key: 'active', label: 'Active' },
  { key: 'unacknowledged', label: 'Unacknowledged' },
  { key: 'mine', label: 'Assigned to me' },
  { key: 'escalated', label: 'Escalated' },
  { key: 'snoozed', label: 'Snoozed' },
  { key: 'resolved', label: 'Resolved' },
  { key: 'all', label: 'All' },
];

const CATEGORIES = ['vehicle', 'driver', 'route', 'maintenance', 'compliance', 'geofence', 'security'];

export function Alerts() {
  const app = useApp();
  const { store, state: s } = app;
  const [view, setView] = useState<View>((app.params.view as View) ?? 'active');
  const [severity, setSeverity] = useState<Set<Severity>>(
    app.params.severity ? new Set([app.params.severity as Severity]) : new Set());
  const [category, setCategory] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openId, setOpenId] = useState<string | undefined>(app.params.alert);
  const [showRules, setShowRules] = useState(false);
  const [bulk, setBulk] = useState<null | 'acknowledge' | 'snooze' | 'resolve'>(null);

  useEffect(() => { if (app.params.alert) setOpenId(app.params.alert); }, [app.params.alert]);

  const summary = useMemo(() => alertSummary(store), [store, s.alerts]);

  const rows = useMemo(() => {
    let list = s.alerts.filter((a) => {
      if (view === 'active') return isOpen(a);
      if (view === 'unacknowledged') return a.status === 'triggered';
      if (view === 'mine') return a.assignedTo === s.currentUserId && isOpen(a);
      if (view === 'escalated') return a.status === 'escalated';
      if (view === 'snoozed') return a.status === 'snoozed';
      if (view === 'resolved') return a.status === 'resolved';
      return true;
    });
    if (severity.size) list = list.filter((a) => severity.has(a.severity));
    if (category.size) list = list.filter((a) => category.has(a.category));
    const q = query.trim().toLowerCase();
    if (q) {
      list = list.filter((a) => [a.title, a.detail, a.street, a.code]
        .some((f) => f?.toLowerCase().includes(q)));
    }
    return [...list].sort((a, b) =>
      SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] || b.triggeredAt - a.triggeredAt);
  }, [s.alerts, view, severity, category, query, s.currentUserId]);

  const openAlert = openId ? store.alert(openId) : undefined;

  const toggleSeverity = (sev: Severity) => {
    const next = new Set(severity);
    if (next.has(sev)) next.delete(sev); else next.add(sev);
    setSeverity(next);
  };

  return (
    <div className="scroll">
      <div className="page">
        <div className="page-head">
          <div className="grow">
            <h2 className="page-title">Alert Operations</h2>
            <p className="page-sub">
              Every exception the fleet raises, from trigger to resolution. Repeated
              firings roll up into one alert so the queue stays readable.
            </p>
          </div>
          <Button onClick={() => setShowRules(true)}>Alert rules</Button>
        </div>

        <div className="kpis" style={{ marginBottom: 14 }}>
          <Kpi label="Critical" value={summary.critical} tone={summary.critical ? 'danger' : undefined}
               active={severity.has('critical')} onClick={() => toggleSeverity('critical')} />
          <Kpi label="High" value={summary.high} tone={summary.high ? 'warn' : undefined}
               active={severity.has('high')} onClick={() => toggleSeverity('high')} />
          <Kpi label="Medium" value={summary.medium}
               active={severity.has('medium')} onClick={() => toggleSeverity('medium')} />
          <Kpi label="Low" value={summary.low}
               active={severity.has('low')} onClick={() => toggleSeverity('low')} />
          <Kpi label="Active" value={summary.active} tone="pulse"
               active={view === 'active'} onClick={() => setView('active')} />
          <Kpi label="Unacknowledged" value={summary.unacknowledged}
               active={view === 'unacknowledged'} onClick={() => setView('unacknowledged')} />
          <Kpi label="Escalated" value={summary.escalated}
               active={view === 'escalated'} onClick={() => setView('escalated')} />
          <Kpi label="Resolved today" value={summary.resolvedToday} tone="good"
               active={view === 'resolved'} onClick={() => setView('resolved')} />
        </div>

        <Card pad={false}
              title={
                <div className="row wrap" style={{ gap: 5 }}>
                  {VIEWS.map((v) => (
                    <button key={v.key} className="chip" data-on={view === v.key}
                            onClick={() => setView(v.key)}>{v.label}</button>
                  ))}
                </div>
              }
              actions={
                <div className="row" style={{ gap: 7 }}>
                  <input className="input" placeholder="Search alerts" value={query}
                         onChange={(e) => setQuery(e.target.value)} style={{ width: 190 }} />
                  <select className="select" style={{ width: 150 }}
                          value={[...category][0] ?? ''}
                          onChange={(e) => setCategory(e.target.value ? new Set([e.target.value]) : new Set())}>
                    <option value="">All categories</option>
                    {CATEGORIES.map((c) => <option key={c} value={c}>{titleCase(c)}</option>)}
                  </select>
                </div>
              }>
          {selected.size > 0 && (
            <div className="row wrap" style={{
              gap: 8, padding: '9px 14px', borderBottom: '1px solid var(--line-soft)',
              background: 'var(--pulse-wash)',
            }}>
              <strong style={{ fontSize: 12.5 }}>{selected.size} selected</strong>
              <div className="grow" />
              <Button size="sm" onClick={() => setBulk('acknowledge')}>Acknowledge</Button>
              <Button size="sm" onClick={() => setBulk('snooze')}>Snooze</Button>
              <Button size="sm" variant="danger" onClick={() => setBulk('resolve')}>Resolve</Button>
              <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>Clear</Button>
            </div>
          )}

          {rows.length === 0 ? (
            <Empty title="No alerts in this view"
                   body={view === 'active'
                     ? 'Nothing needs attention right now. Alerts appear here the moment a rule fires.'
                     : 'Try another view, or clear the filters.'} />
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th style={{ width: 30 }}>
                      <input type="checkbox" aria-label="Select all"
                             checked={selected.size === rows.length && rows.length > 0}
                             onChange={(e) => setSelected(e.target.checked
                               ? new Set(rows.map((r) => r.id)) : new Set())} />
                    </th>
                    <th>Severity</th><th>Alert</th><th>Vehicle</th><th>Driver</th>
                    <th>Location</th><th>Triggered</th><th>Status</th><th>Assigned</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 200).map((a) => {
                    const v = store.vehicle(a.vehicleId);
                    const d = store.driver(a.driverId);
                    const assignee = store.user(a.assignedTo);
                    return (
                      <tr key={a.id} data-clickable="true" onClick={() => setOpenId(a.id)}>
                        <td onClick={(e) => e.stopPropagation()}>
                          <input type="checkbox" aria-label={`Select ${a.title}`}
                                 checked={selected.has(a.id)}
                                 onChange={(e) => {
                                   const next = new Set(selected);
                                   if (e.target.checked) next.add(a.id); else next.delete(a.id);
                                   setSelected(next);
                                 }} />
                        </td>
                        <td><Pill tone={a.severity as Tone}>{a.severity}</Pill></td>
                        <td>
                          <div style={{ fontWeight: 550 }}>{a.title}</div>
                          <div className="dim" style={{ fontSize: 11 }}>
                            {titleCase(a.category)}
                            {a.occurrences > 1 && ` · ${a.occurrences} occurrences in ${
                              Math.max(1, Math.round((a.lastOccurrenceAt - a.firstOccurrenceAt) / 60000))} min`}
                          </div>
                        </td>
                        <td className="mono">{v?.name ?? '—'}</td>
                        <td>{d?.fullName ?? '—'}</td>
                        <td className="truncate" style={{ maxWidth: 160 }}>{a.street ?? '—'}</td>
                        <td className="num" title={new Date(a.triggeredAt).toLocaleString()}>
                          {relTime(a.triggeredAt, s.now)}
                        </td>
                        <td><Pill tone={statusTone(a)}>{titleCase(a.status)}</Pill></td>
                        <td>{assignee?.fullName ?? <span className="dim">—</span>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      {openAlert && <AlertDetail alert={openAlert} onClose={() => setOpenId(undefined)} />}
      {showRules && <RuleBuilder onClose={() => setShowRules(false)} />}
      {bulk && (
        <BulkModal kind={bulk} count={selected.size}
                   criticalCount={rows.filter((r) => selected.has(r.id) && r.severity === 'critical').length}
                   onClose={() => setBulk(null)}
                   onConfirm={(opts) => {
                     const res = app.run(() => bulkAlertAction(store, [...selected], {
                       kind: bulk, ...opts,
                     }));
                     if (res) {
                       app.toast('success',
                         `${res.updated} alert${res.updated === 1 ? '' : 's'} ${bulk}d` +
                         (res.skipped ? `, ${res.skipped} skipped` : ''));
                       setSelected(new Set());
                       setBulk(null);
                     }
                   }} />
      )}
    </div>
  );
}

function statusTone(a: Alert): Tone {
  if (a.status === 'resolved') return 'good';
  if (a.status === 'escalated') return 'danger';
  if (a.status === 'snoozed') return 'neutral';
  if (a.status === 'triggered') return 'warn';
  return 'info';
}

function AlertDetail({ alert, onClose }: { alert: Alert; onClose: () => void }) {
  const app = useApp();
  const { store, state: s } = app;
  const v = store.vehicle(alert.vehicleId);
  const d = store.driver(alert.driverId);
  const rule = s.alertRules.find((r) => r.id === alert.ruleId);
  const task = store.task(alert.taskId);
  const trip = store.trip(alert.tripId);
  const timeline = store.timelineFor('alert', alert.id);
  const [resolving, setResolving] = useState(false);
  const [note, setNote] = useState('');
  const [assigning, setAssigning] = useState(false);

  const act = (fn: () => unknown, msg: string) => { app.run(fn, msg); };

  return (
    <Modal title={alert.title} size="lg" onClose={onClose}
           subtitle={
             <div className="row wrap" style={{ gap: 7 }}>
               <Pill tone={alert.severity as Tone}>{alert.severity}</Pill>
               <Pill tone={statusTone(alert)}>{titleCase(alert.status)}</Pill>
               <span className="mono dim">{alert.code}</span>
               {alert.occurrences > 1 && (
                 <span className="dim">
                   {alert.occurrences} occurrences over{' '}
                   {Math.max(1, Math.round((alert.lastOccurrenceAt - alert.firstOccurrenceAt) / 60000))} min
                 </span>
               )}
             </div>
           }
           footer={
             <>
               {v && (
                 <Button size="sm" onClick={() => { app.navigate('live', { vehicle: v.id }); onClose(); }}>
                   View vehicle on map
                 </Button>
               )}
               {trip && (
                 <Button size="sm" onClick={() => { app.navigate('trips', { trip: trip.id }); onClose(); }}>
                   View trip
                 </Button>
               )}
               {v && (
                 <Button size="sm" onClick={() => {
                   act(() => createWorkOrder(store, {
                     vehicleId: v.id, title: `Investigate — ${alert.title}`,
                     problem: alert.detail, priority: 'high', acknowledgeConflict: true,
                   }), 'Work order raised');
                 }}>
                   <IconWrench size={13} /> Raise work order
                 </Button>
               )}
               <div className="grow" />
               {alert.status !== 'resolved' && (
                 <>
                   {!alert.acknowledgedAt && (
                     <Button size="sm" onClick={() => act(() => acknowledgeAlert(store, alert.id),
                                                          'Alert acknowledged')}>
                       Acknowledge
                     </Button>
                   )}
                   <Button size="sm" onClick={() => setAssigning(true)}>Assign</Button>
                   {alert.severity !== 'critical' && (
                     <Button size="sm" onClick={() => act(() => snoozeAlert(store, alert.id, 30),
                                                          'Snoozed for 30 minutes')}>
                       Snooze 30m
                     </Button>
                   )}
                   <Button size="sm" onClick={() => act(() => escalateAlert(store, alert.id),
                                                        'Alert escalated')}>
                     Escalate
                   </Button>
                   <Button size="sm" variant="primary" onClick={() => setResolving(true)}>
                     Resolve
                   </Button>
                 </>
               )}
             </>
           }>
      <div className="stack">
        <div className="grid-2">
          <Card title="What happened">
            <p style={{ marginTop: 0, fontSize: 12.5 }}>{alert.detail}</p>
            <dl className="kv">
              <dt>Triggered</dt>
              <dd>{new Date(alert.triggeredAt).toLocaleString()} ({relTime(alert.triggeredAt, s.now)})</dd>
              <dt>Where</dt><dd>{alert.street ?? 'Unknown location'}</dd>
              <dt>Vehicle</dt>
              <dd>{v ? <button style={{ color: 'var(--pulse)' }}
                               onClick={() => { app.open('vehicle', v.id); onClose(); }}>
                        {v.name} · {v.plate}</button> : '—'}</dd>
              <dt>Driver</dt>
              <dd>{d ? <button style={{ color: 'var(--pulse)' }}
                               onClick={() => { app.open('driver', d.id); onClose(); }}>
                        {d.fullName}</button> : '—'}</dd>
              {task && (
                <>
                  <dt>Task</dt>
                  <dd><button style={{ color: 'var(--pulse)' }}
                              onClick={() => { app.open('task', task.id); onClose(); }}>
                        {task.reference}</button></dd>
                </>
              )}
            </dl>
          </Card>

          <Card title="Why it fired">
            {rule ? (
              <>
                <div className="mono" style={{
                  fontSize: 12, padding: 9, background: 'var(--sunken)',
                  borderRadius: 6, marginBottom: 10,
                }}>
                  {describeRule(rule)}
                </div>
                <dl className="kv">
                  <dt>Rule</dt><dd>{rule.name}</dd>
                  <dt>Category</dt><dd>{titleCase(rule.category)}</dd>
                  <dt>Cooldown</dt><dd className="num">{rule.cooldownS}s</dd>
                  <dt>Escalation</dt>
                  <dd>{rule.escalationMinutes.length
                    ? `${rule.escalationMinutes.join(' min, ')} min`
                    : 'None'}</dd>
                </dl>
              </>
            ) : <p className="muted">The rule behind this alert has been removed.</p>}
          </Card>
        </div>

        <Card title="Evidence">
          <dl className="kv">
            {Object.entries(alert.evidence)
              .filter(([, val]) => val !== undefined && val !== null)
              .map(([key, val]) => (
                <div key={key} style={{ display: 'contents' }}>
                  <dt>{titleCase(key)}</dt>
                  <dd className="mono">{String(val)}</dd>
                </div>
              ))}
          </dl>
        </Card>

        {alert.recommendedAction && (
          <div className="banner" data-tone="info">
            <IconAlert size={15} />
            <span><strong>Recommended action.</strong> {alert.recommendedAction}</span>
          </div>
        )}

        {alert.resolutionNote && (
          <div className="banner" data-tone="info">
            <span><strong>Resolution.</strong> {alert.resolutionNote}</span>
          </div>
        )}

        <Card title="Activity">
          <Timeline entries={timeline} />
        </Card>
      </div>

      {resolving && (
        <Modal title="Resolve this alert" onClose={() => setResolving(false)}
               footer={<>
                 <Button onClick={() => setResolving(false)}>Cancel</Button>
                 <Button variant="primary" disabled={!note.trim()} onClick={() => {
                   act(() => resolveAlert(store, alert.id, note), 'Alert resolved');
                   setResolving(false);
                   onClose();
                 }}>Resolve</Button>
               </>}>
          <Field label="Resolution note"
                 hint="Recorded on the alert timeline and in the audit log.">
            <textarea className="textarea" value={note} autoFocus
                      onChange={(e) => setNote(e.target.value)}
                      placeholder="Spoke to the driver; speed was a misread on a changed limit." />
          </Field>
        </Modal>
      )}

      {assigning && (
        <Modal title="Assign this alert" onClose={() => setAssigning(false)}>
          <div className="stack-sm">
            {s.users.filter((u) => u.role !== 'driver').map((u) => (
              <button key={u.id} className="row" style={{
                gap: 9, width: '100%', padding: '8px 10px', borderRadius: 7,
                border: '1px solid var(--line)', textAlign: 'left',
              }} onClick={() => {
                act(() => assignAlert(store, alert.id, u.id), `Assigned to ${u.fullName}`);
                setAssigning(false);
              }}>
                <span className="grow">{u.fullName}</span>
                <span className="dim" style={{ textTransform: 'capitalize' }}>
                  {u.role.replace('_', ' ')}
                </span>
              </button>
            ))}
          </div>
        </Modal>
      )}
    </Modal>
  );
}

function BulkModal({ kind, count, criticalCount, onClose, onConfirm }: {
  kind: 'acknowledge' | 'snooze' | 'resolve'; count: number; criticalCount: number;
  onClose: () => void;
  onConfirm: (opts: { note?: string; minutes?: number; confirmCritical?: boolean }) => void;
}) {
  const [note, setNote] = useState('');
  const [minutes, setMinutes] = useState(60);
  const [confirmCritical, setConfirmCritical] = useState(false);
  const blocked = kind === 'resolve' && criticalCount > 0 && !confirmCritical;

  return (
    <Modal title={`${titleCase(kind)} ${count} alert${count === 1 ? '' : 's'}`} onClose={onClose}
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant={kind === 'resolve' ? 'danger' : 'primary'}
                     disabled={blocked || (kind === 'resolve' && !note.trim())}
                     onClick={() => onConfirm({ note, minutes, confirmCritical })}>
               {titleCase(kind)} {count}
             </Button>
           </>}>
      <div className="stack">
        {kind === 'resolve' && criticalCount > 0 && (
          <div className="banner" data-tone="danger">
            <IconAlert size={15} />
            <span>
              {criticalCount} of these are <strong>critical</strong>. Resolving a critical
              alert in bulk needs explicit confirmation.
            </span>
          </div>
        )}
        {kind === 'resolve' && criticalCount > 0 && (
          <label className="row" style={{ gap: 8, fontSize: 12.5 }}>
            <input type="checkbox" checked={confirmCritical}
                   onChange={(e) => setConfirmCritical(e.target.checked)} />
            I have reviewed the critical alerts and want to resolve them.
          </label>
        )}
        {kind === 'snooze' && (
          <Field label="Snooze for (minutes)"
                 hint="Critical alerts are never snoozed and will be skipped.">
            <input className="input" type="number" min={5} max={720} value={minutes}
                   onChange={(e) => setMinutes(Number(e.target.value))} />
          </Field>
        )}
        {kind === 'resolve' && (
          <Field label="Resolution note (required)">
            <textarea className="textarea" value={note}
                      onChange={(e) => setNote(e.target.value)} />
          </Field>
        )}
        {kind === 'acknowledge' && (
          <p className="muted" style={{ margin: 0 }}>
            Acknowledging records that a person has seen each alert and stops the
            escalation clock. Alerts stay open until they are resolved.
          </p>
        )}
      </div>
    </Modal>
  );
}

function RuleBuilder({ onClose }: { onClose: () => void }) {
  const app = useApp();
  const { store, state: s } = app;
  const [editing, setEditing] = useState<AlertRule | null>(null);
  const since = s.now - 30 * 86400000;
  const fired = (id: string) => s.alerts.filter(
    (a) => a.ruleId === id && a.triggeredAt >= since).length;

  return (
    <Modal title="Alert rules" size="xl" onClose={onClose}
           subtitle="Rules read WHEN a metric crosses a threshold FOR a duration, THEN raise an alert and notify.">
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr><th>Rule</th><th>Category</th><th>Severity</th><th>Condition</th>
                <th className="num">Cooldown</th><th className="num">Fired (30d)</th>
                <th>Active</th></tr>
          </thead>
          <tbody>
            {s.alertRules.map((r) => (
              <tr key={r.id} data-clickable="true" onClick={() => setEditing(r)}>
                <td>
                  <div style={{ fontWeight: 550 }}>{r.name}</div>
                  <div className="dim" style={{ fontSize: 11 }}>{r.description}</div>
                </td>
                <td>{titleCase(r.category)}</td>
                <td><Pill tone={r.severity as Tone}>{r.severity}</Pill></td>
                <td className="mono" style={{ fontSize: 11.5 }}>{describeRule(r)}</td>
                <td className="num">{r.cooldownS}s</td>
                <td className="num">{fired(r.id)}</td>
                <td onClick={(e) => e.stopPropagation()}>
                  <button className="switch" data-on={r.active} role="switch"
                          aria-checked={r.active} aria-label={`Toggle ${r.name}`}
                          onClick={() => {
                            r.active = !r.active;
                            store.audit({
                              action: 'alert_rule.updated', entityType: 'alert_rule',
                              entityLabel: r.name,
                              summary: `${r.name} ${r.active ? 'activated' : 'deactivated'}`,
                            });
                            store.emitNow();
                            app.toast('success', `${r.name} ${r.active ? 'activated' : 'deactivated'}`);
                          }} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editing && (
        <Modal title={`Edit ${editing.name}`} onClose={() => setEditing(null)}
               footer={<Button variant="primary" onClick={() => setEditing(null)}>Done</Button>}>
          <div className="stack">
            <div className="mono" style={{
              fontSize: 12.5, padding: 11, background: 'var(--sunken)', borderRadius: 7,
              lineHeight: 1.7,
            }}>
              <div style={{ color: 'var(--ink-4)' }}>WHEN</div>
              <div>{editing.metric.replace(/_/g, ' ')} {editing.operator}{' '}
                <strong>{editing.threshold}</strong> {editing.thresholdUnit}</div>
              {editing.durationS > 0 && (
                <>
                  <div style={{ color: 'var(--ink-4)' }}>FOR</div>
                  <div>{editing.durationS} seconds</div>
                </>
              )}
              <div style={{ color: 'var(--ink-4)' }}>THEN</div>
              <div>create a <strong>{editing.severity}</strong> alert</div>
              <div style={{ color: 'var(--ink-4)' }}>AND NOTIFY</div>
              <div>{editing.notifyRoles.map((r) => titleCase(r)).join(', ')}</div>
              {editing.escalationMinutes.length > 0 && (
                <>
                  <div style={{ color: 'var(--ink-4)' }}>ESCALATE AFTER</div>
                  <div>{editing.escalationMinutes.join(' min, then ')} min unanswered</div>
                </>
              )}
            </div>
            <div className="grid-2">
              <Field label="Threshold">
                <input className="input" type="number" defaultValue={editing.threshold}
                       onChange={(e) => {
                         editing.threshold = Number(e.target.value);
                         store.emitNow();
                       }} />
              </Field>
              <Field label="Duration (seconds)">
                <input className="input" type="number" defaultValue={editing.durationS}
                       onChange={(e) => { editing.durationS = Number(e.target.value); store.emitNow(); }} />
              </Field>
              <Field label="Cooldown (seconds)" hint="Suppresses repeats of the same alert.">
                <input className="input" type="number" defaultValue={editing.cooldownS}
                       onChange={(e) => { editing.cooldownS = Number(e.target.value); store.emitNow(); }} />
              </Field>
              <Field label="Deduplication window (seconds)"
                     hint="Repeats inside this window roll into one alert.">
                <input className="input" type="number" defaultValue={editing.dedupeWindowS}
                       onChange={(e) => { editing.dedupeWindowS = Number(e.target.value); store.emitNow(); }} />
              </Field>
            </div>
            <Field label="Severity">
              <select className="select" defaultValue={editing.severity}
                      onChange={(e) => {
                        editing.severity = e.target.value as Severity;
                        store.audit({
                          action: 'alert_rule.updated', entityType: 'alert_rule',
                          entityLabel: editing.name,
                          summary: `${editing.name} severity set to ${e.target.value}`,
                        });
                        store.emitNow();
                      }}>
                {['low', 'medium', 'high', 'critical'].map((x) =>
                  <option key={x} value={x}>{titleCase(x)}</option>)}
              </select>
            </Field>
          </div>
        </Modal>
      )}
    </Modal>
  );
}
