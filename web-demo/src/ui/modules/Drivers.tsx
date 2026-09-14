// Driver management and the Driver 360 view. Safety scoring and rewards live in
// their own module (Safety.tsx), which is where the leaderboard is rendered.

import { useEffect, useMemo, useState } from 'react';
import { recomputeDriverScore, setDriverStatus } from '../../engine/actions';
import { documentStatus, fatigueRisk } from '../../engine/derive';
import { ACTIVE_TASK_STATUSES, openAlertsFor } from '../../engine/selectors';
import type { DriverStatus } from '../../engine/types';
import { useApp } from '../app-context';
import {
  Avatar, Button, Card, Empty, HBar, Kpi, Modal, Pill, Progress, Sparkline, Tabs,
  Timeline, dmy, hm, titleCase, type Tone,
} from '../components/kit';
import { IconAward, IconTrendDown, IconTrendUp } from '../icons';

const DAY = 86400000;

export function Drivers() {
  const app = useApp();
  const { store, state: s } = app;
  const [openId, setOpenId] = useState<string | undefined>(app.params.driver);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  useEffect(() => { if (app.params.driver) setOpenId(app.params.driver); }, [app.params.driver]);

  const rows = useMemo(() => s.drivers.map((d) => {
    const vehicle = s.vehicles.find((v) => v.driverId === d.id);
    const tasks = s.tasks.filter((t) => t.driverId === d.id &&
      ACTIVE_TASK_STATUSES.includes(t.status));
    const alerts = openAlertsFor(store, { driverId: d.id });
    return { driver: d, vehicle, tasks, alerts };
  }).filter((r) => {
    const q = query.trim().toLowerCase();
    if (q && ![r.driver.fullName, r.driver.employeeNo, r.driver.phone]
      .some((f) => f?.toLowerCase().includes(q))) return false;
    if (statusFilter && r.driver.status !== statusFilter) return false;
    return true;
  }), [s.drivers, s.vehicles, s.tasks, store, query, statusFilter]);

  const avgScore = s.drivers.reduce((a, d) => a + d.safetyScore, 0) / Math.max(1, s.drivers.length);
  const fatigued = s.drivers.filter((d) => fatigueRisk(d.dutyHoursToday) === 'high').length;
  const expiring = s.drivers.filter(
    (d) => documentStatus(d.licenseExpiry, s.now) !== 'valid').length;

  return (
    <div className="scroll">
      <div className="page">
        <div className="page-head">
          <div className="grow">
            <h2 className="page-title">Drivers</h2>
            <p className="page-sub">
              Who is operating the fleet, how safely, and what they are carrying right now.
            </p>
          </div>
          <Button onClick={() => app.navigate('safety')}>
            <IconAward size={14} /> Safety & rewards
          </Button>
        </div>

        <div className="kpis" style={{ marginBottom: 14 }}>
          <Kpi label="Drivers" value={s.drivers.length} />
          <Kpi label="On duty"
               value={s.drivers.filter((d) => d.status === 'driving' || d.status === 'available').length}
               tone="good" />
          <Kpi label="Avg safety score" value={avgScore.toFixed(1)}
               tone={avgScore >= 85 ? 'good' : avgScore >= 70 ? 'warn' : 'danger'} />
          <Kpi label="High fatigue risk" value={fatigued} tone={fatigued ? 'danger' : undefined} />
          <Kpi label="Licence issues" value={expiring} tone={expiring ? 'warn' : undefined}
               onClick={() => app.navigate('compliance')} />
        </div>

        <div className="row wrap" style={{ gap: 8, marginBottom: 12 }}>
          <input className="input" placeholder="Search name, employee number or phone"
                 value={query} onChange={(e) => setQuery(e.target.value)} style={{ maxWidth: 300 }} />
          <select className="select" style={{ width: 160 }} value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            {['available', 'driving', 'on_break', 'off_duty', 'unavailable'].map((x) =>
              <option key={x} value={x}>{titleCase(x)}</option>)}
          </select>
        </div>

        <Card pad={false}>
          {rows.length === 0 ? (
            <Empty title="No drivers match" body="Clear the filters to see the whole crew." />
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Driver</th><th>Status</th><th>Vehicle</th><th>Current task</th>
                    <th className="num">Safety</th><th className="num">Points</th>
                    <th>Fatigue</th><th>Licence</th><th className="num">Alerts</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(({ driver: d, vehicle, tasks, alerts }) => {
                    const lic = documentStatus(d.licenseExpiry, s.now);
                    const trend = d.safetyScore - d.previousSafetyScore;
                    return (
                      <tr key={d.id} data-clickable="true" onClick={() => setOpenId(d.id)}>
                        <td>
                          <span className="row" style={{ gap: 8 }}>
                            <Avatar name={d.fullName} color={d.avatarColor} size={26} />
                            <span>
                              <div style={{ fontWeight: 600 }}>{d.fullName}</div>
                              <div className="mono dim" style={{ fontSize: 11 }}>{d.employeeNo}</div>
                            </span>
                          </span>
                        </td>
                        <td><Pill tone={d.status === 'driving' ? 'good'
                          : d.status === 'available' ? 'info'
                          : d.status === 'unavailable' ? 'danger' : 'neutral'}>
                          {titleCase(d.status)}</Pill></td>
                        <td className="mono">{vehicle?.name ?? <span className="dim">—</span>}</td>
                        <td>
                          {tasks[0] ? (
                            <>
                              <span className="mono" style={{ fontSize: 11 }}>{tasks[0].reference}</span>
                              {tasks.length > 1 && <span className="dim"> +{tasks.length - 1}</span>}
                            </>
                          ) : <span className="dim">None</span>}
                        </td>
                        <td className="num">
                          <span className="row" style={{ gap: 5, justifyContent: 'flex-end' }}>
                            {d.safetyScore.toFixed(1)}
                            {Math.abs(trend) >= 0.5 && (
                              trend > 0
                                ? <IconTrendUp size={12} className="" />
                                : <IconTrendDown size={12} className="" />
                            )}
                          </span>
                        </td>
                        <td className="num">{d.points}</td>
                        <td>
                          <Pill tone={fatigueRisk(d.dutyHoursToday) === 'high' ? 'danger'
                            : fatigueRisk(d.dutyHoursToday) === 'elevated' ? 'warn' : 'good'}>
                            {d.dutyHoursToday.toFixed(1)} h
                          </Pill>
                        </td>
                        <td>
                          <Pill tone={lic === 'valid' ? 'good' : lic === 'expired' ? 'danger' : 'warn'}>
                            {titleCase(lic)}
                          </Pill>
                        </td>
                        <td className="num">
                          {alerts.length ? <Pill tone="warn">{alerts.length}</Pill>
                                         : <span className="dim">0</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      {openId && <Driver360 driverId={openId} onClose={() => setOpenId(undefined)} />}
    </div>
  );
}

const TABS = [
  { key: 'overview', label: 'Overview' }, { key: 'tasks', label: 'Tasks' },
  { key: 'trips', label: 'Trips' }, { key: 'safety', label: 'Safety' },
  { key: 'points', label: 'Points & badges' }, { key: 'incidents', label: 'Incidents' },
  { key: 'documents', label: 'Documents' }, { key: 'timeline', label: 'Timeline' },
];

export function Driver360({ driverId, onClose }: { driverId: string; onClose: () => void }) {
  const app = useApp();
  const { store, state: s } = app;
  const d = store.driver(driverId);
  const [tab, setTab] = useState('overview');
  const [statusOpen, setStatusOpen] = useState(false);
  if (!d) return null;

  const vehicle = s.vehicles.find((v) => v.driverId === d.id);
  const since = s.now - 30 * DAY;
  const trips = s.trips.filter((t) => t.driverId === d.id).sort((a, b) => b.startedAt - a.startedAt);
  const recentTrips = trips.filter((t) => t.startedAt >= since);
  const tasks = s.tasks.filter((t) => t.driverId === d.id)
    .sort((a, b) => (b.scheduledFor ?? 0) - (a.scheduledFor ?? 0));
  const events = s.driverEvents.filter((e) => e.driverId === d.id && e.occurredAt >= since);
  const incidents = s.incidents.filter((i) => i.driverId === d.id);
  const points = s.pointTransactions.filter((p) => p.driverId === d.id);
  const badges = s.badges.filter((b) => b.driverId === d.id);
  const documents = s.documents.filter((doc) => doc.driverId === d.id);
  const alerts = openAlertsFor(store, { driverId: d.id });

  const km = recentTrips.reduce((a, t) => a + t.distanceKm, 0);
  const fuel = recentTrips.reduce((a, t) => a + t.fuelUsedL, 0);
  const completed = tasks.filter((t) => t.status === 'completed' && (t.completedAt ?? 0) >= since);
  const eventCounts: Record<string, number> = {};
  events.forEach((e) => { eventCounts[e.kind] = (eventCounts[e.kind] ?? 0) + 1; });

  const scoreHistory = Array.from({ length: 30 }, (_, i) => {
    const dayEnd = s.now - (29 - i) * DAY;
    const upTo = s.driverEvents.filter(
      (e) => e.driverId === d.id && e.occurredAt <= dayEnd && e.occurredAt >= dayEnd - 30 * DAY);
    const c: Record<string, number> = {};
    upTo.forEach((e) => { c[e.kind] = (c[e.kind] ?? 0) + 1; });
    const dist = s.trips.filter((t) => t.driverId === d.id && t.startedAt <= dayEnd &&
      t.startedAt >= dayEnd - 30 * DAY).reduce((a, t) => a + t.distanceKm, 0);
    const w = s.org.settings.safetyWeights;
    const exposure = Math.max(dist, 25) / 100;
    const penalty = Object.entries(c).reduce((a, [k, n]) => a + (w[k] ?? 1) * n, 0) / exposure;
    return Math.max(0, Math.min(100, 100 - penalty));
  });

  return (
    <Modal title={d.fullName} size="xl" onClose={onClose}
           subtitle={
             <div className="row wrap" style={{ gap: 7 }}>
               <Pill tone={d.status === 'driving' ? 'good' : 'neutral'}>{titleCase(d.status)}</Pill>
               <span className="mono dim">{d.employeeNo}</span>
               <span className="dim">·</span>
               <span className="dim">{d.phone}</span>
               {vehicle && (
                 <>
                   <span className="dim">·</span>
                   <button style={{ color: 'var(--pulse)' }}
                           onClick={() => { app.open('vehicle', vehicle.id); onClose(); }}>
                     {vehicle.name}
                   </button>
                 </>
               )}
             </div>
           }
           footer={
             <>
               <Button size="sm" onClick={() => setStatusOpen(true)}>Change status</Button>
               {vehicle && (
                 <Button size="sm" onClick={() => { app.navigate('live', { vehicle: vehicle.id }); onClose(); }}>
                   Track on map
                 </Button>
               )}
               <Button size="sm" onClick={() => {
                 app.run(() => recomputeDriverScore(store, d.id), 'Safety score recalculated');
               }}>Recalculate score</Button>
               <div className="grow" />
               <Button size="sm" variant="primary"
                       onClick={() => { app.navigate('safety'); onClose(); }}>
                 View standings
               </Button>
             </>
           }>
      <Tabs tabs={TABS.map((t) => ({
        ...t,
        count: t.key === 'tasks' ? tasks.length : t.key === 'trips' ? trips.length
          : t.key === 'incidents' ? incidents.length : t.key === 'documents' ? documents.length
          : undefined,
      }))} active={tab} onChange={setTab} />

      <div style={{ paddingTop: 14 }}>
        {tab === 'overview' && (
          <div className="stack">
            <div className="kpis">
              <Kpi label="Safety score" value={d.safetyScore.toFixed(1)}
                   tone={d.safetyScore >= 85 ? 'good' : d.safetyScore >= 70 ? 'warn' : 'danger'}
                   foot={`${d.safetyScore - d.previousSafetyScore >= 0 ? '+' : ''}${(d.safetyScore - d.previousSafetyScore).toFixed(1)} vs previous`} />
              <Kpi label="Points" value={d.points} />
              <Kpi label="Distance 30d" value={Math.round(km).toLocaleString()} unit=" km" />
              <Kpi label="Tasks completed" value={completed.length} tone="good" />
              <Kpi label="Duty today" value={d.dutyHoursToday.toFixed(1)} unit=" h"
                   tone={fatigueRisk(d.dutyHoursToday) === 'high' ? 'danger' : undefined} />
              <Kpi label="Open alerts" value={alerts.length}
                   tone={alerts.length ? 'warn' : 'good'} />
            </div>

            <div className="grid-2">
              <Card title="Safety score, last 30 days">
                <Sparkline points={scoreHistory} height={60}
                           tone={d.safetyScore >= 85 ? 'var(--success)' : 'var(--warning)'} />
                <p className="muted" style={{ fontSize: 11.5, marginBottom: 0, marginTop: 8 }}>
                  Scored against this driver's own history, normalised per 100 km so a long
                  shift is not penalised.
                </p>
              </Card>
              <Card title="Fatigue">
                <dl className="kv">
                  <dt>Duty today</dt><dd className="num">{d.dutyHoursToday.toFixed(1)} h</dd>
                  <dt>Risk</dt>
                  <dd><Pill tone={fatigueRisk(d.dutyHoursToday) === 'high' ? 'danger'
                    : fatigueRisk(d.dutyHoursToday) === 'elevated' ? 'warn' : 'good'}>
                    {titleCase(fatigueRisk(d.dutyHoursToday))}</Pill></dd>
                  <dt>Shift</dt><dd className="num">{d.shiftStart} – {d.shiftEnd}</dd>
                  <dt>Hired</dt><dd>{d.hiredOn}</dd>
                </dl>
                <div style={{ marginTop: 10 }}>
                  <Progress pct={(d.dutyHoursToday / 11) * 100}
                            tone={d.dutyHoursToday > 9 ? 'danger'
                              : d.dutyHoursToday > 7 ? 'warn' : 'good'} />
                  <div className="dim" style={{ fontSize: 11, marginTop: 4 }}>
                    Against an 11-hour daily limit.
                  </div>
                </div>
              </Card>
            </div>

            <Card title="Fuel efficiency (30 days)">
              <dl className="kv">
                <dt>Distance</dt><dd className="num">{km.toFixed(0)} km</dd>
                <dt>Fuel used</dt><dd className="num">{fuel.toFixed(1)} L</dd>
                <dt>Consumption</dt>
                <dd className="num">
                  {km > 5 ? `${((fuel / km) * 100).toFixed(1)} L/100km` : '—'}
                </dd>
                <dt>Trips</dt><dd className="num">{recentTrips.length}</dd>
                <dt>Driving hours</dt>
                <dd className="num">{(recentTrips.reduce((a, t) => a + t.durationS, 0) / 3600).toFixed(1)} h</dd>
              </dl>
            </Card>
          </div>
        )}

        {tab === 'safety' && (
          <div className="stack">
            <Card title="Event breakdown (30 days)">
              {Object.keys(eventCounts).length === 0 ? (
                <p className="muted" style={{ margin: 0 }}>
                  No safety events in the last 30 days — a clean record.
                </p>
              ) : (
                Object.entries(eventCounts).sort((a, b) => b[1] - a[1]).map(([k, n]) => (
                  <HBar key={k} label={titleCase(k)} value={n}
                        max={Math.max(...Object.values(eventCounts))}
                        tone={k === 'overspeed' ? 'var(--danger)' : 'var(--warning)'} />
                ))
              )}
            </Card>
            <Card title="How this driver compares with their own history">
              <dl className="kv">
                <dt>Current score</dt><dd className="num">{d.safetyScore.toFixed(1)}</dd>
                <dt>Previous</dt><dd className="num">{d.previousSafetyScore.toFixed(1)}</dd>
                <dt>Change</dt>
                <dd className="num" style={{
                  color: d.safetyScore >= d.previousSafetyScore ? 'var(--success)' : 'var(--danger)',
                }}>
                  {d.safetyScore - d.previousSafetyScore >= 0 ? '+' : ''}
                  {(d.safetyScore - d.previousSafetyScore).toFixed(1)}
                </dd>
              </dl>
              <div className="banner" data-tone="info" style={{ marginTop: 10 }}>
                <span>
                  {d.safetyScore >= 90
                    ? 'Consistently strong. Nothing to coach right now.'
                    : Object.entries(eventCounts).sort((a, b) => b[1] - a[1])[0]
                      ? `Most frequent issue: ${titleCase(Object.entries(eventCounts).sort((a, b) => b[1] - a[1])[0][0])}. Focus coaching there first.`
                      : 'No events recorded to coach on.'}
                </span>
              </div>
            </Card>
            <Card pad={false} title="Recent events">
              <div className="table-wrap">
                <table className="data">
                  <thead><tr><th>When</th><th>Event</th><th>Vehicle</th><th>Where</th>
                             <th className="num">Value</th><th>Detail</th></tr></thead>
                  <tbody>
                    {events.slice(-40).reverse().map((e) => (
                      <tr key={e.id}>
                        <td>{dmy(e.occurredAt)} {hm(e.occurredAt)}</td>
                        <td><Pill tone={e.severity as Tone}>{titleCase(e.kind)}</Pill></td>
                        <td className="mono">{store.vehicle(e.vehicleId)?.name ?? '—'}</td>
                        <td className="truncate" style={{ maxWidth: 140 }}>{e.street ?? '—'}</td>
                        <td className="num">{e.value ?? '—'}</td>
                        <td className="truncate" style={{ maxWidth: 250 }}>{e.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        )}

        {tab === 'points' && (
          <div className="stack">
            <div className="kpis">
              <Kpi label="Points balance" value={d.points}
                   foot={`Starts at ${s.org.settings.driverPointsStart}`} />
              <Kpi label="Badges earned" value={badges.length} tone="good" />
              <Kpi label="Deductions (30d)"
                   value={points.filter((p) => p.points < 0 && p.occurredAt >= since)
                     .reduce((a, p) => a + p.points, 0)} tone="danger" />
              <Kpi label="Rewards (30d)"
                   value={`+${points.filter((p) => p.points > 0 && p.occurredAt >= since)
                     .reduce((a, p) => a + p.points, 0)}`} tone="good" />
            </div>
            {badges.length > 0 && (
              <Card title="Badges">
                <div className="row wrap" style={{ gap: 10 }}>
                  {badges.map((b) => (
                    <div key={b.id} className="card card-pad" style={{ minWidth: 190 }}>
                      <div className="row" style={{ gap: 8 }}>
                        <IconAward size={18} />
                        <strong style={{ fontSize: 12.5 }}>{b.name}</strong>
                      </div>
                      <div className="muted" style={{ fontSize: 11.5, marginTop: 5 }}>
                        {b.description}
                      </div>
                      <div className="dim mono" style={{ fontSize: 10, marginTop: 6 }}>
                        {dmy(b.awardedAt)} · {b.period}
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            )}
            <Card pad={false} title="Points ledger">
              {points.length === 0 ? (
                <Empty title="No transactions yet"
                       body="Points move when safety events are recorded or rewards are earned." />
              ) : (
                <div className="table-wrap">
                  <table className="data">
                    <thead><tr><th>When</th><th>Reason</th><th className="num">Change</th>
                               <th className="num">Balance</th><th>Detail</th></tr></thead>
                    <tbody>
                      {points.slice(0, 40).map((p) => (
                        <tr key={p.id}>
                          <td>{dmy(p.occurredAt)} {hm(p.occurredAt)}</td>
                          <td>{titleCase(p.reason)}</td>
                          <td className="num" style={{
                            color: p.points < 0 ? 'var(--danger)' : 'var(--success)',
                          }}>{p.points > 0 ? '+' : ''}{p.points}</td>
                          <td className="num">{p.balanceAfter}</td>
                          <td className="truncate" style={{ maxWidth: 260 }}>{p.detail ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </div>
        )}

        {tab === 'tasks' && (
          <Card pad={false}>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>Task</th><th>Status</th><th>Scheduled</th><th>SLA</th><th>Vehicle</th></tr></thead>
                <tbody>
                  {tasks.slice(0, 50).map((t) => (
                    <tr key={t.id} data-clickable="true"
                        onClick={() => { app.open('task', t.id); onClose(); }}>
                      <td>
                        <div className="mono dim" style={{ fontSize: 11 }}>{t.reference}</div>
                        {t.title}
                      </td>
                      <td><Pill tone={t.status === 'completed' ? 'good'
                        : t.status === 'failed' ? 'danger' : 'info'}>{titleCase(t.status)}</Pill></td>
                      <td className="num">{dmy(t.scheduledFor)} {hm(t.scheduledFor)}</td>
                      <td><Pill tone={t.slaState === 'breached' ? 'danger'
                        : t.slaState === 'met' ? 'good' : 'neutral'}>{titleCase(t.slaState)}</Pill></td>
                      <td className="mono">{store.vehicle(t.vehicleId)?.name ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {tab === 'trips' && (
          <Card pad={false}>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>Trip</th><th>Started</th><th>Route</th>
                           <th className="num">Distance</th><th className="num">Duration</th>
                           <th className="num">Events</th></tr></thead>
                <tbody>
                  {trips.slice(0, 60).map((t) => (
                    <tr key={t.id} data-clickable="true"
                        onClick={() => { app.navigate('trips', { trip: t.id }); onClose(); }}>
                      <td className="mono">{t.reference}</td>
                      <td>{dmy(t.startedAt)} {hm(t.startedAt)}</td>
                      <td className="truncate" style={{ maxWidth: 240 }}>
                        {t.startAddress} → {t.endAddress ?? 'in progress'}
                      </td>
                      <td className="num">{t.distanceKm.toFixed(1)} km</td>
                      <td className="num">{Math.round(t.durationS / 60)} min</td>
                      <td className="num">{t.eventCount}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {tab === 'incidents' && (
          <Card pad={false}>
            {incidents.length === 0 ? (
              <Empty title="No incidents" body={`${d.fullName} has a clean incident record.`} />
            ) : (
              <div className="table-wrap">
                <table className="data">
                  <thead><tr><th>Reference</th><th>Incident</th><th>Severity</th>
                             <th>Status</th><th>When</th></tr></thead>
                  <tbody>
                    {incidents.map((i) => (
                      <tr key={i.id} data-clickable="true"
                          onClick={() => { app.open('incident', i.id); onClose(); }}>
                        <td className="mono">{i.reference}</td>
                        <td>{i.title}</td>
                        <td><Pill tone={i.severity as Tone}>{i.severity}</Pill></td>
                        <td><Pill tone={i.status === 'closed' ? 'good' : 'info'}>
                          {titleCase(i.status)}</Pill></td>
                        <td>{dmy(i.occurredAt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )}

        {tab === 'documents' && (
          <Card pad={false}>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>Document</th><th>Issuer</th><th>Reference</th>
                           <th>Expires</th><th>Status</th></tr></thead>
                <tbody>
                  <tr>
                    <td>Driving licence (class {d.licenseClass})</td>
                    <td>Traficom</td>
                    <td className="mono" style={{ fontSize: 11 }}>{d.licenseNumber}</td>
                    <td className="num">{d.licenseExpiry}</td>
                    <td>
                      <Pill tone={documentStatus(d.licenseExpiry, s.now) === 'valid' ? 'good'
                        : documentStatus(d.licenseExpiry, s.now) === 'expired' ? 'danger' : 'warn'}>
                        {titleCase(documentStatus(d.licenseExpiry, s.now))}
                      </Pill>
                    </td>
                  </tr>
                  {documents.filter((doc) => doc.kind !== 'driver_license').map((doc) => (
                    <tr key={doc.id} data-clickable="true"
                        onClick={() => { app.open('document', doc.id); onClose(); }}>
                      <td>{doc.name}</td>
                      <td>{doc.issuer}</td>
                      <td className="mono" style={{ fontSize: 11 }}>{doc.reference}</td>
                      <td className="num">{doc.expiryDate}</td>
                      <td><Pill tone={doc.status === 'valid' ? 'good'
                        : doc.status === 'expired' ? 'danger' : 'warn'}>
                        {titleCase(doc.status)}</Pill></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {tab === 'timeline' && (
          <Card><Timeline entries={store.timelineFor('driver', d.id).slice(0, 80)} /></Card>
        )}
      </div>

      {statusOpen && (
        <Modal title={`Change ${d.fullName}'s status`} onClose={() => setStatusOpen(false)}>
          <div className="stack-sm">
            {(['available', 'driving', 'on_break', 'off_duty', 'unavailable'] as DriverStatus[])
              .map((st) => (
                <button key={st} className="row" style={{
                  gap: 9, width: '100%', padding: '9px 11px', borderRadius: 7,
                  border: `1px solid ${st === d.status ? 'var(--pulse)' : 'var(--line)'}`,
                  textAlign: 'left',
                }} onClick={() => {
                  app.run(() => setDriverStatus(store, d.id, st),
                          `${d.fullName} set to ${titleCase(st)}`);
                  setStatusOpen(false);
                }}>
                  <Pill tone={st === 'driving' ? 'good' : st === 'unavailable' ? 'danger' : 'neutral'}>
                    {titleCase(st)}
                  </Pill>
                  <span className="grow dim" style={{ fontSize: 11.5 }}>
                    {st === 'available' ? 'Ready to take work'
                      : st === 'driving' ? 'Currently on a trip'
                      : st === 'on_break' ? 'Mandatory rest'
                      : st === 'off_duty' ? 'Shift finished'
                      : 'Cannot be assigned work'}
                  </span>
                </button>
              ))}
          </div>
        </Modal>
      )}
    </Modal>
  );
}
