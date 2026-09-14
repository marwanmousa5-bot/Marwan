// Vehicle registry and the Vehicle 360 workspace — the contextual view that
// connects the whole platform around one asset.

import { useEffect, useMemo, useState } from 'react';
import {
  assignDriverToVehicle, createVehicle, createWorkOrder, retireVehicle, updateVehicle,
} from '../../engine/actions';
import { annualDepreciation, bookValue, gpsFreshness, vehicleStatus } from '../../engine/derive';
import {
  ACTIVE_TASK_STATUSES, fleetRows, openAlertsFor, vehicleCosts, vehicleHealth,
} from '../../engine/selectors';
import type { Vehicle, VehicleType } from '../../engine/types';
import { useApp, useEpoch } from '../app-context';
import {
  Avatar, Button, Card, Confirm, Empty, Field, HBar, Kpi, Modal, Money, Pill,
  Progress, Sparkline, Tabs, Timeline, dmy, hm, relTime, titleCase, type Tone,
} from '../components/kit';
import { IconAlert, IconPlus, IconWrench } from '../icons';

export function Vehicles() {
  const app = useApp();
  const { store, state: s } = app;
  const [openId, setOpenId] = useState<string | undefined>(app.params.vehicle);
  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [maintFilter, setMaintFilter] = useState('');
  const [adding, setAdding] = useState(false);

  useEffect(() => { if (app.params.vehicle) setOpenId(app.params.vehicle); }, [app.params.vehicle]);

  const rows = useMemo(() => fleetRows(store), [store, s.ticks, s.vehicles]);
  const since = s.now - 30 * 86400000;

  const filtered = rows.filter((r) => {
    const q = query.trim().toLowerCase();
    if (q && ![r.vehicle.name, r.vehicle.plate, r.vehicle.make, r.vehicle.model,
               r.driver?.fullName].some((f) => f?.toLowerCase().includes(q))) return false;
    if (typeFilter && r.vehicle.type !== typeFilter) return false;
    if (statusFilter && r.status !== statusFilter) return false;
    if (maintFilter && r.maintenance !== maintFilter) return false;
    return true;
  });

  const utilisation = (id: string) => {
    const seconds = s.trips.filter((t) => t.vehicleId === id && t.startedAt >= since)
      .reduce((a, t) => a + t.durationS, 0);
    return Math.min(100, Math.round((seconds / (30 * 10 * 3600)) * 100));
  };

  const counts = {
    active: s.vehicles.filter((v) => v.lifecycle === 'active').length,
    maintenance: s.vehicles.filter((v) => v.lifecycle === 'maintenance').length,
    suspended: s.vehicles.filter((v) => v.lifecycle === 'suspended').length,
    retired: s.vehicles.filter((v) => v.lifecycle === 'retired').length,
    ev: s.vehicles.filter((v) => v.fuelType === 'electric').length,
  };

  return (
    <div className="scroll">
      <div className="page">
        <div className="page-head">
          <div className="grow">
            <h2 className="page-title">Vehicles</h2>
            <p className="page-sub">
              The asset register. Every row links to the vehicle's full operating
              picture — telemetry, work, maintenance, cost and compliance.
            </p>
          </div>
          <Button variant="primary" onClick={() => setAdding(true)}>
            <IconPlus size={14} /> Add vehicle
          </Button>
        </div>

        <div className="kpis" style={{ marginBottom: 14 }}>
          <Kpi label="Fleet size" value={s.vehicles.length} />
          <Kpi label="Active" value={counts.active} tone="good" />
          <Kpi label="In maintenance" value={counts.maintenance}
               tone={counts.maintenance ? 'warn' : undefined} />
          <Kpi label="Suspended" value={counts.suspended}
               tone={counts.suspended ? 'danger' : undefined} />
          <Kpi label="Electric" value={counts.ev} foot={`${Math.round(counts.ev / s.vehicles.length * 100)}% of fleet`} />
          <Kpi label="Avg utilisation"
               value={`${Math.round(rows.reduce((a, r) => a + utilisation(r.vehicle.id), 0) / Math.max(1, rows.length))}`}
               unit="%" />
        </div>

        <div className="row wrap" style={{ gap: 8, marginBottom: 12 }}>
          <input className="input" placeholder="Search name, plate, make or driver"
                 value={query} onChange={(e) => setQuery(e.target.value)} style={{ maxWidth: 280 }} />
          <select className="select" style={{ width: 150 }} value={typeFilter}
                  onChange={(e) => setTypeFilter(e.target.value)}>
            <option value="">All types</option>
            {['van', 'truck', 'car', 'refrigerated_van', 'cargo_bike', 'ev_van'].map((t) =>
              <option key={t} value={t}>{titleCase(t)}</option>)}
          </select>
          <select className="select" style={{ width: 150 }} value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            {['moving', 'idle', 'stopped', 'offline', 'maintenance', 'not_tracked'].map((t) =>
              <option key={t} value={t}>{titleCase(t)}</option>)}
          </select>
          <select className="select" style={{ width: 170 }} value={maintFilter}
                  onChange={(e) => setMaintFilter(e.target.value)}>
            <option value="">All maintenance states</option>
            {['healthy', 'due_soon', 'due', 'overdue', 'critical', 'in_workshop'].map((t) =>
              <option key={t} value={t}>{titleCase(t)}</option>)}
          </select>
          <div className="grow" />
          <span className="dim" style={{ fontSize: 12 }}>{filtered.length} vehicles</span>
        </div>

        <Card pad={false}>
          {filtered.length === 0 ? (
            <Empty title="No vehicles match" body="Clear a filter to see the rest of the fleet." />
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Vehicle</th><th>Type</th><th>Driver</th><th>Status</th>
                    <th>Location</th><th className="num">Speed</th><th className="num">Odometer</th>
                    <th>Device</th><th>Maintenance</th><th className="num">Alerts</th>
                    <th className="num">Utilisation</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((r) => {
                    const v = r.vehicle;
                    const device = s.devices.find((d) => d.vehicleId === v.id);
                    const util = utilisation(v.id);
                    return (
                      <tr key={v.id} data-clickable="true" onClick={() => setOpenId(v.id)}>
                        <td>
                          <div style={{ fontWeight: 600 }}>{v.name}</div>
                          <div className="mono dim" style={{ fontSize: 11 }}>
                            {v.plate} · {v.make} {v.model}
                          </div>
                        </td>
                        <td>{titleCase(v.type)}</td>
                        <td>
                          {r.driver ? (
                            <span className="row" style={{ gap: 6 }}>
                              <Avatar name={r.driver.fullName} color={r.driver.avatarColor} size={19} />
                              <span className="truncate">{r.driver.fullName}</span>
                            </span>
                          ) : <span className="dim">Unassigned</span>}
                        </td>
                        <td><Pill tone={r.status as Tone}>{titleCase(r.status)}</Pill></td>
                        <td className="truncate" style={{ maxWidth: 150 }}>
                          {v.street ?? <span className="dim">—</span>}
                        </td>
                        <td className="num">{Math.round(v.speedKph)}</td>
                        <td className="num">{Math.round(v.odometerKm).toLocaleString()}</td>
                        <td className="mono" style={{ fontSize: 11 }}>
                          {device?.serial ?? <span className="dim">None</span>}
                        </td>
                        <td>
                          <Pill tone={r.maintenance === 'healthy' ? 'good'
                            : r.maintenance === 'critical' || r.maintenance === 'overdue' ? 'danger'
                            : r.maintenance === 'in_workshop' ? 'maintenance' : 'warn'}>
                            {titleCase(r.maintenance)}
                          </Pill>
                        </td>
                        <td className="num">
                          {r.alertCount > 0
                            ? <Pill tone={(r.worstAlert ?? 'medium') as Tone}>{r.alertCount}</Pill>
                            : <span className="dim">0</span>}
                        </td>
                        <td className="num" style={{ minWidth: 96 }}>
                          <div className="row" style={{ gap: 7 }}>
                            <span style={{ flex: 1 }}><Progress pct={util} /></span>
                            <span style={{ width: 30 }}>{util}%</span>
                          </div>
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

      {openId && <Vehicle360 vehicleId={openId} onClose={() => setOpenId(undefined)} />}
      {adding && <AddVehicle onClose={() => setAdding(false)} onCreated={setOpenId} />}
    </div>
  );
}

const TABS = [
  { key: 'overview', label: 'Overview' }, { key: 'live', label: 'Live' },
  { key: 'trips', label: 'Trips' }, { key: 'tasks', label: 'Tasks' },
  { key: 'maintenance', label: 'Maintenance' }, { key: 'fuel', label: 'Fuel' },
  { key: 'documents', label: 'Documents' }, { key: 'costs', label: 'Costs' },
  { key: 'safety', label: 'Safety' }, { key: 'alerts', label: 'Alerts' },
  { key: 'timeline', label: 'Timeline' },
];

export function Vehicle360({ vehicleId, onClose }: { vehicleId: string; onClose: () => void }) {
  const app = useApp();
  const { store, state: s } = app;
  const v = store.vehicle(vehicleId);
  const [tab, setTab] = useState('overview');
  const [retiring, setRetiring] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [editing, setEditing] = useState(false);

  const epoch = useEpoch();
  const health = useMemo(() => v ? vehicleHealth(store, v.id) : null, [store, v, epoch]);
  const costs = useMemo(() => v ? vehicleCosts(store, v.id, 12) : null, [store, v, epoch]);

  if (!v) return null;
  const driver = store.driver(v.driverId);
  const device = s.devices.find((d) => d.vehicleId === v.id);
  const freshness = gpsFreshness(v.lastPositionAt, s.now);
  const status = vehicleStatus(v, { now: s.now, settings: s.org.settings,
                                    openWorkOrder: (health?.counts.openWorkOrders ?? 0) > 0 });
  const trips = s.trips.filter((t) => t.vehicleId === v.id)
    .sort((a, b) => b.startedAt - a.startedAt);
  const tasks = s.tasks.filter((t) => t.vehicleId === v.id)
    .sort((a, b) => (b.scheduledFor ?? 0) - (a.scheduledFor ?? 0));
  const alerts = openAlertsFor(store, { vehicleId: v.id });
  const documents = s.documents.filter((d) => d.vehicleId === v.id);
  const schedules = s.schedules.filter((x) => x.vehicleId === v.id && x.active);
  const workOrders = s.workOrders.filter((w) => w.vehicleId === v.id);
  const records = s.maintenanceRecords.filter((r) => r.vehicleId === v.id);
  const fuel = s.fuel.filter((f) => f.vehicleId === v.id);
  const charging = s.charging.filter((c) => c.vehicleId === v.id);
  const events = s.driverEvents.filter((e) => e.vehicleId === v.id);

  const last30 = s.now - 30 * 86400000;
  const km30 = trips.filter((t) => t.startedAt >= last30).reduce((a, t) => a + t.distanceKm, 0);
  const dailyKm = Array.from({ length: 30 }, (_, i) => {
    const day = new Date(s.now - (29 - i) * 86400000).toISOString().slice(0, 10);
    return trips.filter((t) => new Date(t.startedAt).toISOString().slice(0, 10) === day)
      .reduce((a, t) => a + t.distanceKm, 0);
  });

  return (
    <Modal title={`${v.name} · ${v.plate}`} size="xl" onClose={onClose}
           subtitle={
             <div className="row wrap" style={{ gap: 7 }}>
               <Pill tone={status as Tone}>{titleCase(status)}</Pill>
               <span className="dim">{v.year} {v.make} {v.model}</span>
               <span className="dim">·</span>
               <span className="dim">{titleCase(v.fuelType)}</span>
               <span className="dim">·</span>
               <span className="mono dim">{Math.round(v.odometerKm).toLocaleString()} km</span>
               {health && (
                 <Pill tone={health.score >= 80 ? 'good' : health.score >= 55 ? 'warn' : 'danger'}>
                   Health {health.score}/100
                 </Pill>
               )}
             </div>
           }
           footer={
             <>
               <Button size="sm" onClick={() => { app.navigate('live', { vehicle: v.id }); onClose(); }}>
                 Track on map
               </Button>
               <Button size="sm" onClick={() => setAssigning(true)}>Assign driver</Button>
               <Button size="sm" onClick={() => setEditing(true)}>Edit details</Button>
               <Button size="sm" onClick={() => {
                 app.run(() => createWorkOrder(store, {
                   vehicleId: v.id, title: 'Workshop inspection',
                   problem: 'Raised from Vehicle 360.', acknowledgeConflict: true,
                 }), 'Work order raised');
               }}><IconWrench size={13} /> Raise work order</Button>
               <div className="grow" />
               <Button size="sm" variant="danger" onClick={() => setRetiring(true)}
                       disabled={v.lifecycle === 'retired'}>
                 {v.lifecycle === 'retired' ? 'Retired' : 'Retire vehicle'}
               </Button>
             </>
           }>
      <Tabs tabs={TABS.map((t) => ({
        ...t,
        count: t.key === 'alerts' ? alerts.length
          : t.key === 'trips' ? trips.length
          : t.key === 'tasks' ? tasks.length
          : t.key === 'documents' ? documents.length : undefined,
      }))} active={tab} onChange={setTab} />

      <div style={{ paddingTop: 14 }}>
        {tab === 'overview' && (
          <div className="stack">
            <div className="kpis">
              <Kpi label="Distance 30d" value={Math.round(km30).toLocaleString()} unit=" km" />
              <Kpi label="Trips 30d" value={trips.filter((t) => t.startedAt >= last30).length} />
              <Kpi label="Open alerts" value={alerts.length}
                   tone={alerts.length ? 'danger' : 'good'} />
              <Kpi label="Health" value={health?.score ?? 0} unit="/100"
                   tone={(health?.score ?? 0) >= 80 ? 'good' : 'warn'} />
              <Kpi label="Cost / km" value={costs?.costPerKm ? `€${costs.costPerKm.toFixed(2)}` : '—'} />
              <Kpi label="Book value" value={<Money value={bookValue(v, s.now)} />} />
            </div>

            <div className="grid-2">
              <Card title="Identity">
                <dl className="kv">
                  <dt>Name</dt><dd>{v.name}</dd>
                  <dt>Plate</dt><dd className="mono">{v.plate}</dd>
                  <dt>VIN</dt><dd className="mono" style={{ fontSize: 11 }}>{v.vin || '—'}</dd>
                  <dt>Type</dt><dd>{titleCase(v.type)}</dd>
                  <dt>Colour</dt><dd>{v.colour}</dd>
                  <dt>Lifecycle</dt><dd>{titleCase(v.lifecycle)}</dd>
                  <dt>Ownership</dt><dd>{titleCase(v.ownership)}</dd>
                </dl>
              </Card>
              <Card title="Assignment">
                <dl className="kv">
                  <dt>Driver</dt>
                  <dd>{driver ? (
                    <button className="row" style={{ gap: 6 }}
                            onClick={() => { app.open('driver', driver.id); onClose(); }}>
                      <Avatar name={driver.fullName} color={driver.avatarColor} size={18} />
                      <span style={{ color: 'var(--pulse)' }}>{driver.fullName}</span>
                    </button>
                  ) : <span className="dim">Unassigned</span>}</dd>
                  <dt>Device</dt>
                  <dd className="mono">{device ? `${device.serial} (${device.model})` : 'None'}</dd>
                  <dt>Firmware</dt><dd className="mono">{device?.firmware ?? '—'}</dd>
                  <dt>Home depot</dt>
                  <dd>{store.place(v.homePlaceId)?.name ?? '—'}</dd>
                </dl>
              </Card>
            </div>

            <Card title="Distance, last 30 days">
              <Sparkline points={dailyKm} height={56} />
              <div className="row" style={{ marginTop: 6, fontSize: 11 }}>
                <span className="dim grow">30 days ago</span>
                <span className="mono">Peak {Math.max(...dailyKm).toFixed(0)} km/day</span>
                <span className="dim" style={{ marginLeft: 12 }}>Today</span>
              </div>
            </Card>

            {health && health.repeatCategories.length > 0 && (
              <div className="banner" data-tone="ai">
                <span className="ai-tag">Fleet intelligence</span>
                <span>
                  {v.name} has needed{' '}
                  {health.repeatCategories.map((c) => `${c.category.replace(/_/g, ' ')} (${c.count}×)`).join(', ')}{' '}
                  work in the last six months. Inspect that system before the next
                  scheduled service rather than after the next failure.
                </span>
              </div>
            )}
          </div>
        )}

        {tab === 'live' && (
          <div className="stack">
            <Card title="Telemetry">
              <dl className="kv">
                <dt>GPS</dt>
                <dd>
                  <span className="freshness" data-state={freshness.state}>
                    <i className="dot" /> {freshness.state}
                  </span>
                  {v.lastPositionAt && ` · ${relTime(v.lastPositionAt, s.now)}`}
                </dd>
                <dt>Position</dt>
                <dd className="mono">
                  {v.lat != null ? `${v.lat.toFixed(5)}, ${v.lon!.toFixed(5)}` : 'No fix'}
                </dd>
                <dt>Street</dt><dd>{v.street ?? '—'}</dd>
                <dt>Speed</dt><dd className="num">{Math.round(v.speedKph)} km/h</dd>
                <dt>Heading</dt><dd className="num">{Math.round(v.heading)}°</dd>
                <dt>Satellites</dt><dd className="num">{v.satellites}</dd>
                <dt>Ignition</dt><dd>{v.ignitionOn ? 'On' : 'Off'}</dd>
                <dt>Odometer</dt>
                <dd className="num">{Math.round(v.odometerKm).toLocaleString()} km</dd>
              </dl>
            </Card>
            {v.fuelType === 'electric' && (
              <Card title="Battery">
                <dl className="kv">
                  <dt>Capacity</dt><dd className="num">{v.batteryCapacityKwh} kWh</dd>
                  <dt>State of charge</dt>
                  <dd>
                    <div className="row" style={{ gap: 8 }}>
                      <span style={{ flex: 1, maxWidth: 160 }}>
                        <Progress pct={v.stateOfChargePct ?? 0}
                                  tone={(v.stateOfChargePct ?? 0) < 20 ? 'danger' : 'good'} />
                      </span>
                      <span className="num">{Math.round(v.stateOfChargePct ?? 0)}%</span>
                    </div>
                  </dd>
                  <dt>Range</dt><dd className="num">{Math.round(v.rangeKm ?? 0)} km</dd>
                  <dt>Charging</dt><dd>{titleCase(v.chargingStatus ?? 'idle')}</dd>
                </dl>
              </Card>
            )}
          </div>
        )}

        {tab === 'trips' && (
          <Card pad={false}>
            {trips.length === 0 ? (
              <Empty title="No trips yet"
                     body="Trips are recorded automatically once the vehicle starts moving." />
            ) : (
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr><th>Trip</th><th>Started</th><th>From → To</th>
                        <th className="num">Distance</th><th className="num">Duration</th>
                        <th className="num">Max speed</th><th className="num">Events</th></tr>
                  </thead>
                  <tbody>
                    {trips.slice(0, 60).map((t) => (
                      <tr key={t.id} data-clickable="true"
                          onClick={() => { app.navigate('trips', { trip: t.id }); onClose(); }}>
                        <td className="mono">{t.reference}</td>
                        <td>{dmy(t.startedAt)} {hm(t.startedAt)}</td>
                        <td className="truncate" style={{ maxWidth: 230 }}>
                          {t.startAddress} → {t.endAddress ?? 'in progress'}
                        </td>
                        <td className="num">{t.distanceKm.toFixed(1)} km</td>
                        <td className="num">{Math.round(t.durationS / 60)} min</td>
                        <td className="num">{t.maxSpeedKph.toFixed(0)}</td>
                        <td className="num">{t.eventCount}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )}

        {tab === 'tasks' && (
          <Card pad={false}>
            {tasks.length === 0 ? (
              <Empty title="No tasks assigned"
                     body="Assign work from Dispatch or the Task Manager." />
            ) : (
              <div className="table-wrap">
                <table className="data">
                  <thead><tr><th>Task</th><th>Status</th><th>Scheduled</th><th>SLA</th><th>Driver</th></tr></thead>
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
                        <td>{store.driver(t.driverId)?.fullName ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )}

        {tab === 'maintenance' && (
          <div className="stack">
            {health && (
              <Card title="Maintenance health">
                <div className="row" style={{ gap: 16, alignItems: 'flex-start' }}>
                  <div>
                    <div className="num" style={{ fontSize: 34, fontWeight: 600,
                      color: health.score >= 80 ? 'var(--success)'
                        : health.score >= 55 ? 'var(--warning)' : 'var(--danger)' }}>
                      {health.score}
                    </div>
                    <div className="dim" style={{ fontSize: 11 }}>out of 100</div>
                  </div>
                  <dl className="kv grow">
                    <dt>Overdue</dt><dd className="num">{health.counts.overdue}</dd>
                    <dt>Critical</dt><dd className="num">{health.counts.critical}</dd>
                    <dt>Due</dt><dd className="num">{health.counts.due}</dd>
                    <dt>Due soon</dt><dd className="num">{health.counts.dueSoon}</dd>
                    <dt>Open work orders</dt><dd className="num">{health.counts.openWorkOrders}</dd>
                    <dt>Repeat failures</dt><dd className="num">{health.counts.repeatFailures}</dd>
                  </dl>
                </div>
              </Card>
            )}
            <Card title="Preventive schedules" pad={false}>
              <div className="table-wrap">
                <table className="data">
                  <thead><tr><th>Service</th><th>Interval</th><th>Due at</th><th>Status</th>
                             <th className="num">Est. cost</th></tr></thead>
                  <tbody>
                    {schedules.map((sc) => (
                      <tr key={sc.id}>
                        <td>{sc.name}</td>
                        <td className="dim">
                          {[sc.intervalKm && `${sc.intervalKm.toLocaleString()} km`,
                            sc.intervalMonths && `${sc.intervalMonths} months`]
                            .filter(Boolean).join(' or ')}
                        </td>
                        <td className="num">
                          {sc.dueAtKm ? `${Math.round(sc.dueAtKm).toLocaleString()} km` : ''}
                          {sc.dueAtDate ? ` · ${sc.dueAtDate}` : ''}
                        </td>
                        <td><Pill tone={sc.status === 'healthy' ? 'good'
                          : sc.status === 'overdue' || sc.status === 'critical' ? 'danger'
                          : sc.status === 'in_workshop' ? 'maintenance' : 'warn'}>
                          {titleCase(sc.status)}</Pill></td>
                        <td className="num">€{sc.estimatedCost}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
            <Card title="Work orders" pad={false}>
              {workOrders.length === 0 ? (
                <Empty title="No work orders" body="Nothing has been sent to the workshop yet." />
              ) : (
                <div className="table-wrap">
                  <table className="data">
                    <thead><tr><th>Reference</th><th>Title</th><th>Status</th>
                               <th className="num">Cost</th><th className="num">Downtime</th></tr></thead>
                    <tbody>
                      {workOrders.map((w) => (
                        <tr key={w.id} data-clickable="true"
                            onClick={() => { app.open('work_order', w.id); onClose(); }}>
                          <td className="mono">{w.reference}</td>
                          <td>{w.title}</td>
                          <td><Pill tone={w.status === 'completed' ? 'good'
                            : w.status === 'cancelled' ? 'neutral' : 'info'}>
                            {titleCase(w.status)}</Pill></td>
                          <td className="num">€{w.totalCost.toFixed(0)}</td>
                          <td className="num">{w.downtimeHours?.toFixed(1) ?? '—'} h</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
            <Card title="Service history" pad={false}>
              <div className="table-wrap">
                <table className="data">
                  <thead><tr><th>Date</th><th>Work</th><th className="num">Odometer</th>
                             <th className="num">Cost</th><th>Workshop</th></tr></thead>
                  <tbody>
                    {records.slice(0, 30).map((r) => (
                      <tr key={r.id}>
                        <td>{r.serviceDate}</td>
                        <td>{r.workPerformed}</td>
                        <td className="num">{Math.round(r.odometerKm).toLocaleString()}</td>
                        <td className="num">€{r.totalCost.toFixed(0)}</td>
                        <td className="truncate" style={{ maxWidth: 170 }}>{r.workshopName}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        )}

        {tab === 'fuel' && (
          <Card pad={false} title={v.fuelType === 'electric' ? 'Charging sessions' : 'Fuel transactions'}>
            <div className="table-wrap">
              {v.fuelType === 'electric' ? (
                <table className="data">
                  <thead><tr><th>Started</th><th>Location</th><th className="num">Energy</th>
                             <th className="num">Cost</th><th className="num">SoC</th></tr></thead>
                  <tbody>
                    {charging.slice(0, 40).map((c) => (
                      <tr key={c.id}>
                        <td>{dmy(c.startedAt)} {hm(c.startedAt)}</td>
                        <td>{c.locationName}</td>
                        <td className="num">{c.energyKwh.toFixed(1)} kWh</td>
                        <td className="num">€{c.totalCost.toFixed(2)}</td>
                        <td className="num">{c.startSocPct}% → {c.endSocPct}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <table className="data">
                  <thead><tr><th>Date</th><th>Station</th><th className="num">Litres</th>
                             <th className="num">€/L</th><th className="num">Cost</th>
                             <th className="num">L/100km</th></tr></thead>
                  <tbody>
                    {fuel.slice(0, 40).map((f) => (
                      <tr key={f.id}>
                        <td>{dmy(f.occurredAt)}</td>
                        <td>{f.stationName}</td>
                        <td className="num">{f.litres.toFixed(1)}</td>
                        <td className="num">{f.pricePerLitre.toFixed(3)}</td>
                        <td className="num">€{f.totalCost.toFixed(2)}</td>
                        <td className="num">
                          {f.distanceSinceLastKm && f.distanceSinceLastKm > 5
                            ? ((f.litres / f.distanceSinceLastKm) * 100).toFixed(1) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </Card>
        )}

        {tab === 'documents' && (
          <Card pad={false}>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>Document</th><th>Issuer</th><th>Reference</th>
                           <th>Expires</th><th>Status</th></tr></thead>
                <tbody>
                  {documents.map((d) => (
                    <tr key={d.id} data-clickable="true"
                        onClick={() => { app.open('document', d.id); onClose(); }}>
                      <td>{d.name}</td>
                      <td>{d.issuer}</td>
                      <td className="mono" style={{ fontSize: 11 }}>{d.reference}</td>
                      <td className="num">{d.expiryDate}</td>
                      <td><Pill tone={d.status === 'valid' ? 'good'
                        : d.status === 'expired' ? 'danger' : 'warn'}>
                        {titleCase(d.status)}</Pill></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {tab === 'costs' && costs && (
          <div className="stack">
            <div className="kpis">
              <Kpi label="Acquisition" value={<Money value={v.purchaseValue} />} />
              <Kpi label="Operating (12m)" value={<Money value={costs.operating} />} />
              <Kpi label="Book value" value={<Money value={bookValue(v, s.now)} />} />
              <Kpi label="TCO" value={<Money value={costs.tco} />} tone="pulse" />
              <Kpi label="Cost / km"
                   value={costs.costPerKm ? `€${costs.costPerKm.toFixed(2)}` : '—'} />
              <Kpi label="Depreciation / yr" value={<Money value={annualDepreciation(v)} />} />
            </div>
            <Card title="Operating cost by category (12 months)">
              {Object.entries(costs.byCategory)
                .sort((a, b) => b[1] - a[1])
                .map(([cat, amount]) => (
                  <HBar key={cat} label={titleCase(cat)} value={amount}
                        max={Math.max(...Object.values(costs.byCategory))}
                        format={(x) => `€${Math.round(x).toLocaleString()}`} />
                ))}
            </Card>
            <div className="banner" data-tone="info">
              <span>
                TCO = acquisition {`€${v.purchaseValue.toLocaleString()}`} + operating{' '}
                €{Math.round(costs.operating).toLocaleString()} − book value{' '}
                €{Math.round(bookValue(v, s.now)).toLocaleString()}, using straight-line
                depreciation over {v.depreciationYears} years.
              </span>
            </div>
          </div>
        )}

        {tab === 'safety' && (
          <div className="stack">
            <Card title="Driving events recorded on this vehicle (30 days)">
              {(() => {
                const recent = events.filter((e) => e.occurredAt >= last30);
                const counts: Record<string, number> = {};
                recent.forEach((e) => { counts[e.kind] = (counts[e.kind] ?? 0) + 1; });
                const max = Math.max(1, ...Object.values(counts));
                return Object.keys(counts).length ? (
                  Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, n]) => (
                    <HBar key={k} label={titleCase(k)} value={n} max={max}
                          tone={k === 'overspeed' ? 'var(--danger)' : 'var(--warning)'} />
                  ))
                ) : <p className="muted" style={{ margin: 0 }}>No safety events in the last 30 days.</p>;
              })()}
            </Card>
            <Card pad={false} title="Recent events">
              <div className="table-wrap">
                <table className="data">
                  <thead><tr><th>When</th><th>Event</th><th>Driver</th><th>Where</th>
                             <th className="num">Value</th></tr></thead>
                  <tbody>
                    {events.slice(-30).reverse().map((e) => (
                      <tr key={e.id}>
                        <td>{dmy(e.occurredAt)} {hm(e.occurredAt)}</td>
                        <td><Pill tone={e.severity as Tone}>{titleCase(e.kind)}</Pill></td>
                        <td>{store.driver(e.driverId)?.fullName ?? '—'}</td>
                        <td className="truncate" style={{ maxWidth: 160 }}>{e.street ?? '—'}</td>
                        <td className="num">{e.value ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        )}

        {tab === 'alerts' && (
          <Card pad={false}>
            {alerts.length === 0 ? (
              <Empty title="No open alerts" body={`${v.name} has nothing outstanding.`} />
            ) : (
              <div className="table-wrap">
                <table className="data">
                  <thead><tr><th>Severity</th><th>Alert</th><th>Triggered</th><th>Status</th></tr></thead>
                  <tbody>
                    {alerts.map((a) => (
                      <tr key={a.id} data-clickable="true"
                          onClick={() => { app.open('alert', a.id); onClose(); }}>
                        <td><Pill tone={a.severity as Tone}>{a.severity}</Pill></td>
                        <td>{a.title}</td>
                        <td className="num">{relTime(a.triggeredAt, s.now)}</td>
                        <td><Pill tone="info">{titleCase(a.status)}</Pill></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )}

        {tab === 'timeline' && (
          <Card>
            <Timeline entries={store.timelineFor('vehicle', v.id).slice(0, 80)} />
          </Card>
        )}
      </div>

      {retiring && (
        <Confirm title={`Retire ${v.name}?`}
                 body={`${v.name} (${v.plate}) will be removed from operations. Its history, costs and documents are kept.`}
                 consequences={
                   <div className="banner" data-tone="warn">
                     <IconAlert size={15} />
                     <span>
                       {s.tasks.filter((t) => t.vehicleId === v.id &&
                         ACTIVE_TASK_STATUSES.includes(t.status)).length} active task(s) must be
                       reassigned first, and the driver will be unassigned.
                     </span>
                   </div>
                 }
                 confirmLabel="Retire vehicle" tone="danger"
                 onCancel={() => setRetiring(false)}
                 onConfirm={() => {
                   const ok = app.run(() => retireVehicle(store, v.id, 'End of service life'),
                                      `${v.name} retired`);
                   setRetiring(false);
                   if (ok) onClose();
                 }} />
      )}

      {assigning && (
        <Modal title={`Assign a driver to ${v.name}`} onClose={() => setAssigning(false)}>
          <div className="stack-sm">
            <button className="row" style={{ gap: 9, width: '100%', padding: '8px 10px',
                                             borderRadius: 7, border: '1px solid var(--line)' }}
                    onClick={() => {
                      app.run(() => assignDriverToVehicle(store, v.id, undefined),
                              'Driver unassigned');
                      setAssigning(false);
                    }}>
              <span className="grow" style={{ textAlign: 'left' }}>No driver</span>
            </button>
            {s.drivers.map((d) => {
              const other = s.vehicles.find((x) => x.driverId === d.id && x.id !== v.id);
              return (
                <button key={d.id} className="row" style={{
                  gap: 9, width: '100%', padding: '8px 10px', borderRadius: 7,
                  border: `1px solid ${d.id === v.driverId ? 'var(--pulse)' : 'var(--line)'}`,
                }} onClick={() => {
                  app.run(() => assignDriverToVehicle(store, v.id, d.id),
                          `${d.fullName} assigned to ${v.name}`);
                  setAssigning(false);
                }}>
                  <Avatar name={d.fullName} color={d.avatarColor} size={22} />
                  <span className="grow" style={{ textAlign: 'left' }}>
                    {d.fullName}
                    <div className="dim" style={{ fontSize: 11 }}>
                      {titleCase(d.status)}{other ? ` · currently on ${other.name}` : ''}
                    </div>
                  </span>
                  <Pill tone={d.safetyScore >= 85 ? 'good' : 'warn'}>
                    {d.safetyScore.toFixed(0)}
                  </Pill>
                </button>
              );
            })}
          </div>
        </Modal>
      )}

      {editing && <EditVehicle vehicle={v} onClose={() => setEditing(false)} />}
    </Modal>
  );
}

function EditVehicle({ vehicle, onClose }: { vehicle: Vehicle; onClose: () => void }) {
  const app = useApp();
  const [name, setName] = useState(vehicle.name);
  const [plate, setPlate] = useState(vehicle.plate);
  const [colour, setColour] = useState(vehicle.colour);
  const [consumption, setConsumption] = useState(vehicle.avgConsumption ?? 0);
  const [notes, setNotes] = useState(vehicle.notes ?? '');
  return (
    <Modal title={`Edit ${vehicle.name}`} onClose={onClose}
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant="primary" onClick={() => {
               app.run(() => updateVehicle(app.store, vehicle.id, {
                 name, plate, colour,
                 avgConsumption: consumption || undefined,
                 notes: notes || undefined,
               }), 'Vehicle updated');
               onClose();
             }}>Save changes</Button>
           </>}>
      <div className="stack">
        <div className="grid-2">
          <Field label="Name"><input className="input" value={name}
                                     onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Plate"><input className="input" value={plate}
                                      onChange={(e) => setPlate(e.target.value)} /></Field>
          <Field label="Colour"><input className="input" value={colour}
                                       onChange={(e) => setColour(e.target.value)} /></Field>
          <Field label="Average consumption (L/100km)">
            <input className="input" type="number" step="0.1" value={consumption}
                   onChange={(e) => setConsumption(Number(e.target.value))} />
          </Field>
        </div>
        <Field label="Notes">
          <textarea className="textarea" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}

function AddVehicle({ onClose, onCreated }: {
  onClose: () => void; onCreated: (id: string) => void;
}) {
  const app = useApp();
  const [name, setName] = useState('');
  const [plate, setPlate] = useState('');
  const [type, setType] = useState<VehicleType>('van');
  const [make, setMake] = useState('');
  const [model, setModel] = useState('');
  const [odometer, setOdometer] = useState(0);
  const [value, setValue] = useState(38000);
  return (
    <Modal title="Add a vehicle" onClose={onClose}
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant="primary" disabled={!name.trim() || !plate.trim()} onClick={() => {
               const v = app.run(() => createVehicle(app.store, {
                 name, plate, type, make, model, odometerKm: odometer,
                 purchaseValue: value, residualValue: Math.round(value * 0.3),
                 fuelType: type === 'ev_van' ? 'electric' : 'diesel',
                 avgConsumption: type === 'ev_van' ? undefined : 9,
                 batteryCapacityKwh: type === 'ev_van' ? 60 : undefined,
               }), `${name} added to the fleet`);
               if (v) { onCreated(v.id); onClose(); }
             }}>Add vehicle</Button>
           </>}>
      <div className="stack">
        <div className="grid-2">
          <Field label="Name" hint="How the fleet refers to it, e.g. KL-15.">
            <input className="input" value={name} autoFocus
                   onChange={(e) => setName(e.target.value)} placeholder="KL-15" />
          </Field>
          <Field label="Plate">
            <input className="input" value={plate}
                   onChange={(e) => setPlate(e.target.value.toUpperCase())} placeholder="ABC-123" />
          </Field>
          <Field label="Type">
            <select className="select" value={type}
                    onChange={(e) => setType(e.target.value as VehicleType)}>
              {['van', 'truck', 'car', 'refrigerated_van', 'cargo_bike', 'ev_van'].map((t) =>
                <option key={t} value={t}>{titleCase(t)}</option>)}
            </select>
          </Field>
          <Field label="Odometer (km)">
            <input className="input" type="number" value={odometer}
                   onChange={(e) => setOdometer(Number(e.target.value))} />
          </Field>
          <Field label="Make"><input className="input" value={make}
                                     onChange={(e) => setMake(e.target.value)} /></Field>
          <Field label="Model"><input className="input" value={model}
                                      onChange={(e) => setModel(e.target.value)} /></Field>
          <Field label="Purchase value (€)">
            <input className="input" type="number" value={value}
                   onChange={(e) => setValue(Number(e.target.value))} />
          </Field>
        </div>
      </div>
    </Modal>
  );
}
