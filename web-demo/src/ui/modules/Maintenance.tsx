// Maintenance Operations Centre: dashboard, schedules, work orders, calendar,
// workshops and impact analysis before anything is booked.

import { useEffect, useMemo, useState } from 'react';
import {
  ActionError, addWorkOrderPart, createSchedule, createWorkOrder, maintenanceImpact,
  removeWorkOrderPart, setWorkOrderStatus, updateWorkOrder, WO_FLOW,
} from '../../engine/actions';
import { MAINTENANCE_TEMPLATES, PARTS_CATALOG, TECHNICIANS } from '../../engine/catalog';
import { describeDue } from '../../engine/derive';
import { maintenanceSummary, OPEN_WO_STATUSES, vehicleHealth } from '../../engine/selectors';
import type { WorkOrderStatus } from '../../engine/types';
import { useApp } from '../app-context';
import {
  Button, Card, Empty, Field, HBar, Kpi, Modal, Money, Pill, Tabs, Timeline,
  dmy, hm, titleCase,
} from '../components/kit';
import { IconAlert, IconPlus, IconWrench } from '../icons';

const DAY = 86400000;
const HOUR = 3600000;

export function Maintenance() {
  const app = useApp();
  const { store, state: s } = app;
  const [tab, setTab] = useState('overview');
  const [openWo, setOpenWo] = useState<string | undefined>(app.params.workOrder);
  const [compose, setCompose] = useState(app.params.compose === '1');
  const [scheduleFilter, setScheduleFilter] = useState('');
  const [newSchedule, setNewSchedule] = useState(false);

  useEffect(() => { if (app.params.workOrder) setOpenWo(app.params.workOrder); },
            [app.params.workOrder]);
  useEffect(() => { if (app.params.compose === '1') setCompose(true); }, [app.params.compose]);

  const m = useMemo(() => maintenanceSummary(store), [store, s.schedules, s.workOrders]);
  const health = useMemo(
    () => s.vehicles.map((v) => ({ vehicle: v, ...vehicleHealth(store, v.id) }))
      .sort((a, b) => a.score - b.score),
    [store, s.vehicles, s.schedules, s.workOrders]);

  return (
    <div className="scroll">
      <div className="page">
        <div className="page-head">
          <div className="grow">
            <h2 className="page-title">Maintenance Operations</h2>
            <p className="page-sub">
              Preventive schedules run on mileage or time — whichever comes first.
              Every number below filters the list beneath it.
            </p>
          </div>
          <Button onClick={() => setNewSchedule(true)}>New schedule</Button>
          <Button variant="primary" onClick={() => setCompose(true)}>
            <IconPlus size={14} /> Work order
          </Button>
        </div>

        <div className="kpis" style={{ marginBottom: 14 }}>
          <Kpi label="Overdue" value={m.overdue} tone={m.overdue ? 'danger' : undefined}
               active={scheduleFilter === 'overdue'}
               onClick={() => { setTab('schedules'); setScheduleFilter(scheduleFilter === 'overdue' ? '' : 'overdue'); }} />
          <Kpi label="Critical" value={m.critical} tone={m.critical ? 'danger' : undefined}
               active={scheduleFilter === 'critical'}
               onClick={() => { setTab('schedules'); setScheduleFilter(scheduleFilter === 'critical' ? '' : 'critical'); }} />
          <Kpi label="Due today" value={m.dueToday} tone={m.dueToday ? 'warn' : undefined}
               onClick={() => { setTab('schedules'); setScheduleFilter('due'); }} />
          <Kpi label="Due this week" value={m.dueThisWeek}
               onClick={() => { setTab('schedules'); setScheduleFilter('due_soon'); }} />
          <Kpi label="Due this month" value={m.dueThisMonth} />
          <Kpi label="In workshop" value={m.inWorkshop} tone="pulse"
               onClick={() => setTab('workorders')} />
          <Kpi label="Open work orders" value={m.openWorkOrders}
               onClick={() => setTab('workorders')} />
          <Kpi label="Estimated cost" value={<Money value={m.estimatedCost} />} />
        </div>

        <Tabs tabs={[
          { key: 'overview', label: 'Overview' },
          { key: 'schedules', label: 'Schedules', count: s.schedules.filter((x) => x.active).length },
          { key: 'workorders', label: 'Work orders', count: s.workOrders.length },
          { key: 'calendar', label: 'Calendar' },
          { key: 'history', label: 'History' },
          { key: 'workshops', label: 'Workshops' },
          { key: 'templates', label: 'Templates' },
        ]} active={tab} onChange={setTab} />

        <div style={{ paddingTop: 14 }}>
          {tab === 'overview' && (
            <div className="stack">
              <div className="grid-2">
                <Card title="Vehicle maintenance health"
                      actions={<span className="dim" style={{ fontSize: 11 }}>Lowest first</span>}>
                  {health.slice(0, 10).map((h) => (
                    <HBar key={h.vehicle.id} label={`${h.vehicle.name} · ${h.vehicle.plate}`}
                          value={h.score} max={100}
                          format={(v) => `${Math.round(v)}/100`}
                          tone={h.score >= 80 ? 'var(--success)'
                            : h.score >= 55 ? 'var(--warning)' : 'var(--danger)'} />
                  ))}
                </Card>

                <Card title="Spend">
                  <div className="kpis" style={{ gridTemplateColumns: '1fr 1fr' }}>
                    <Kpi label="Last 30 days" value={<Money value={m.spend30d} />} />
                    <Kpi label="Committed" value={<Money value={m.estimatedCost} />} />
                  </div>
                  <div style={{ marginTop: 12 }}>
                    {(() => {
                      const byCat: Record<string, number> = {};
                      s.maintenanceRecords
                        .filter((r) => Date.parse(r.serviceDate) >= s.now - 180 * DAY)
                        .forEach((r) => { byCat[r.category] = (byCat[r.category] ?? 0) + r.totalCost; });
                      const max = Math.max(1, ...Object.values(byCat));
                      return Object.entries(byCat).sort((a, b) => b[1] - a[1]).slice(0, 7)
                        .map(([k, v]) => (
                          <HBar key={k} label={titleCase(k)} value={v} max={max}
                                format={(x) => `€${Math.round(x).toLocaleString()}`} />
                        ));
                    })()}
                  </div>
                </Card>
              </div>

              {(() => {
                const repeats = health.filter((h) => h.repeatCategories.length);
                if (!repeats.length) return null;
                return (
                  <Card title="Fleet intelligence"
                        actions={<span className="ai-tag">Rule-based</span>}>
                    <div className="stack-sm">
                      {repeats.map((h) => {
                        const top = h.repeatCategories.sort((a, b) => b.count - a.count)[0];
                        return (
                          <div key={h.vehicle.id} className="banner" data-tone="ai">
                            <IconWrench size={15} />
                            <span>
                              <strong>{h.vehicle.name}</strong> has needed{' '}
                              {top.category.replace(/_/g, ' ')} work {top.count} times in the
                              last six months. Inspect that system before the next scheduled
                              service rather than after the next failure.
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </Card>
                );
              })()}

              <Card pad={false} title="Needs attention now">
                {(() => {
                  const urgent = s.schedules
                    .filter((x) => x.active && ['overdue', 'critical', 'due'].includes(x.status))
                    .map((x) => ({ sc: x, v: store.vehicle(x.vehicleId)! }))
                    .filter((r) => r.v)
                    .sort((a, b) => (a.sc.dueAtKm ?? 0) - a.v.odometerKm -
                                    ((b.sc.dueAtKm ?? 0) - b.v.odometerKm));
                  if (!urgent.length) {
                    return <Empty title="Nothing overdue"
                                  body="Every preventive service is inside its threshold." />;
                  }
                  return (
                    <div className="table-wrap">
                      <table className="data">
                        <thead><tr><th>Vehicle</th><th>Service</th><th>Status</th><th>Due</th>
                                   <th className="num">Est. cost</th><th></th></tr></thead>
                        <tbody>
                          {urgent.slice(0, 12).map(({ sc, v }) => (
                            <tr key={sc.id}>
                              <td>
                                <button style={{ color: 'var(--pulse)', fontWeight: 550 }}
                                        onClick={() => app.open('vehicle', v.id)}>
                                  {v.name}
                                </button>
                                <div className="mono dim" style={{ fontSize: 11 }}>{v.plate}</div>
                              </td>
                              <td>{sc.name}</td>
                              <td><Pill tone={sc.status === 'critical' || sc.status === 'overdue'
                                ? 'danger' : 'warn'}>{titleCase(sc.status)}</Pill></td>
                              <td className="dim">{describeDue(sc, v.odometerKm, s.now)}</td>
                              <td className="num">€{sc.estimatedCost}</td>
                              <td>
                                <Button size="sm" onClick={() => {
                                  setCompose(true);
                                  app.navigate('maintenance',
                                               { compose: '1', vehicle: v.id, schedule: sc.id });
                                }}>Book</Button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  );
                })()}
              </Card>
            </div>
          )}

          {tab === 'schedules' && (
            <Card pad={false}
                  title={<div className="row wrap" style={{ gap: 5 }}>
                    {['', 'overdue', 'critical', 'due', 'due_soon', 'healthy', 'in_workshop']
                      .map((f) => (
                        <button key={f || 'all'} className="chip" data-on={scheduleFilter === f}
                                onClick={() => setScheduleFilter(f)}>
                          {f ? titleCase(f) : 'All'}
                        </button>
                      ))}
                  </div>}>
              {(() => {
                const list = s.schedules
                  .filter((x) => x.active && (!scheduleFilter || x.status === scheduleFilter))
                  .map((x) => ({ sc: x, v: store.vehicle(x.vehicleId)! }))
                  .filter((r) => r.v)
                  .sort((a, b) => (a.sc.dueAtDate ?? '9999').localeCompare(b.sc.dueAtDate ?? '9999'));
                if (!list.length) {
                  return <Empty title="No schedules in this state"
                                body="Pick another filter, or create a preventive schedule."
                                action={<Button onClick={() => setNewSchedule(true)}>
                                          New schedule
                                        </Button>} />;
                }
                return (
                  <div className="table-wrap">
                    <table className="data">
                      <thead><tr><th>Vehicle</th><th>Service</th><th>Interval</th>
                                 <th>Due by mileage</th><th>Due by date</th><th>Status</th>
                                 <th className="num">Est. cost</th><th>Work order</th><th></th></tr></thead>
                      <tbody>
                        {list.map(({ sc, v }) => {
                          const wo = s.workOrders.find(
                            (w) => w.scheduleId === sc.id && OPEN_WO_STATUSES.includes(w.status));
                          const kmLeft = sc.dueAtKm != null ? sc.dueAtKm - v.odometerKm : null;
                          return (
                            <tr key={sc.id}>
                              <td>
                                <button style={{ color: 'var(--pulse)', fontWeight: 550 }}
                                        onClick={() => app.open('vehicle', v.id)}>{v.name}</button>
                                <div className="mono dim" style={{ fontSize: 11 }}>
                                  {Math.round(v.odometerKm).toLocaleString()} km
                                </div>
                              </td>
                              <td>{sc.name}</td>
                              <td className="dim">
                                {[sc.intervalKm && `${sc.intervalKm.toLocaleString()} km`,
                                  sc.intervalMonths && `${sc.intervalMonths} mo`]
                                  .filter(Boolean).join(' or ')}
                              </td>
                              <td className="num" style={{
                                color: kmLeft != null && kmLeft < 0 ? 'var(--danger)' : undefined,
                              }}>
                                {kmLeft != null
                                  ? `${kmLeft < 0 ? '' : '+'}${Math.round(kmLeft).toLocaleString()} km`
                                  : '—'}
                              </td>
                              <td className="num">{sc.dueAtDate ?? '—'}</td>
                              <td><Pill tone={sc.status === 'healthy' ? 'good'
                                : sc.status === 'critical' || sc.status === 'overdue' ? 'danger'
                                : sc.status === 'in_workshop' ? 'maintenance' : 'warn'}>
                                {titleCase(sc.status)}</Pill></td>
                              <td className="num">€{sc.estimatedCost}</td>
                              <td>{wo
                                ? <button className="mono" style={{ color: 'var(--pulse)' }}
                                          onClick={() => setOpenWo(wo.id)}>{wo.reference}</button>
                                : <span className="dim">—</span>}</td>
                              <td>
                                {!wo && (
                                  <Button size="sm" onClick={() => {
                                    app.navigate('maintenance',
                                                 { compose: '1', vehicle: v.id, schedule: sc.id });
                                    setCompose(true);
                                  }}>Book</Button>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                );
              })()}
            </Card>
          )}

          {tab === 'workorders' && <WorkOrderList onOpen={setOpenWo} />}
          {tab === 'calendar' && <MaintenanceCalendar onOpen={setOpenWo} />}
          {tab === 'history' && <HistoryTab />}
          {tab === 'workshops' && <WorkshopsTab />}
          {tab === 'templates' && <TemplatesTab />}
        </div>
      </div>

      {openWo && <WorkOrderDetail woId={openWo} onClose={() => setOpenWo(undefined)} />}
      {compose && (
        <WorkOrderComposer onClose={() => setCompose(false)} onCreated={setOpenWo}
                           presetVehicle={app.params.vehicle}
                           presetSchedule={app.params.schedule} />
      )}
      {newSchedule && <ScheduleComposer onClose={() => setNewSchedule(false)} />}
    </div>
  );
}

function WorkOrderList({ onOpen }: { onOpen: (id: string) => void }) {
  const app = useApp();
  const { store, state: s } = app;
  const [filter, setFilter] = useState('');
  const list = s.workOrders
    .filter((w) => !filter || w.status === filter)
    .sort((a, b) => b.createdAt - a.createdAt);

  return (
    <Card pad={false} title={
      <div className="row wrap" style={{ gap: 5 }}>
        {['', 'requested', 'approved', 'scheduled', 'in_progress', 'waiting_for_parts',
          'completed', 'cancelled'].map((f) => (
          <button key={f || 'all'} className="chip" data-on={filter === f}
                  onClick={() => setFilter(f)}>{f ? titleCase(f) : 'All'}</button>
        ))}
      </div>
    }>
      {list.length === 0 ? (
        <Empty title="No work orders" body="Nothing is in the workshop queue right now." />
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Reference</th><th>Vehicle</th><th>Work</th><th>Status</th>
                       <th>Priority</th><th>Workshop</th><th>Scheduled</th>
                       <th className="num">Cost</th></tr></thead>
            <tbody>
              {list.map((w) => {
                const v = store.vehicle(w.vehicleId);
                const overdue = w.expectedCompletion && OPEN_WO_STATUSES.includes(w.status) &&
                  w.expectedCompletion < s.now;
                return (
                  <tr key={w.id} data-clickable="true" onClick={() => onOpen(w.id)}>
                    <td className="mono">{w.reference}</td>
                    <td>{v?.name} <span className="mono dim">{v?.plate}</span></td>
                    <td>{w.title}</td>
                    <td>
                      <Pill tone={w.status === 'completed' ? 'good'
                        : w.status === 'cancelled' ? 'neutral'
                        : w.status === 'waiting_for_parts' ? 'warn' : 'info'}>
                        {titleCase(w.status)}
                      </Pill>
                      {overdue && <Pill tone="danger">Overdue</Pill>}
                    </td>
                    <td><Pill tone={w.priority === 'urgent' ? 'danger'
                      : w.priority === 'high' ? 'warn' : 'neutral'}>{w.priority}</Pill></td>
                    <td className="truncate" style={{ maxWidth: 160 }}>
                      {store.workshop(w.workshopId)?.name ?? '—'}
                    </td>
                    <td className="num">
                      {w.scheduledStart ? `${dmy(w.scheduledStart)} ${hm(w.scheduledStart)}` : '—'}
                    </td>
                    <td className="num">€{(w.totalCost || w.estimatedCost).toFixed(0)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function MaintenanceCalendar({ onOpen }: { onOpen: (id: string) => void }) {
  const app = useApp();
  const { store, state: s } = app;
  const [offset, setOffset] = useState(0);
  const start = new Date(s.now + offset * 28 * DAY);
  start.setUTCDate(1);
  start.setUTCHours(0, 0, 0, 0);
  const firstDay = (start.getUTCDay() + 6) % 7;
  const gridStart = start.getTime() - firstDay * DAY;
  const days = Array.from({ length: 42 }, (_, i) => gridStart + i * DAY);

  return (
    <Card pad={false}
          title={start.toLocaleDateString([], { month: 'long', year: 'numeric' })}
          actions={
            <div className="row" style={{ gap: 6 }}>
              <Button size="sm" onClick={() => setOffset(offset - 1)}>Previous</Button>
              <Button size="sm" onClick={() => setOffset(0)}>Today</Button>
              <Button size="sm" onClick={() => setOffset(offset + 1)}>Next</Button>
            </div>
          }>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)' }}>
        {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d) => (
          <div key={d} className="eyebrow" style={{
            padding: '8px 10px', borderBottom: '1px solid var(--line)',
          }}>{d}</div>
        ))}
        {days.map((day) => {
          const iso = new Date(day).toISOString().slice(0, 10);
          const inMonth = new Date(day).getUTCMonth() === start.getUTCMonth();
          const schedules = s.schedules.filter((x) => x.active && x.dueAtDate === iso);
          const orders = s.workOrders.filter(
            (w) => w.scheduledStart &&
                   new Date(w.scheduledStart).toISOString().slice(0, 10) === iso);
          const isToday = iso === new Date(s.now).toISOString().slice(0, 10);
          return (
            <div key={day} style={{
              minHeight: 96, padding: 6, borderBottom: '1px solid var(--line-soft)',
              borderRight: '1px solid var(--line-soft)',
              opacity: inMonth ? 1 : 0.4,
              background: isToday ? 'var(--pulse-wash)' : undefined,
            }}>
              <div className="num" style={{ fontSize: 11, color: 'var(--ink-4)', marginBottom: 4 }}>
                {new Date(day).getUTCDate()}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                {orders.slice(0, 3).map((w) => (
                  <button key={w.id} onClick={() => onOpen(w.id)} style={{
                    textAlign: 'left', fontSize: 10, padding: '2px 5px', borderRadius: 4,
                    background: 'var(--pulse-wash)', color: 'var(--pulse)',
                    borderLeft: '2px solid var(--pulse)',
                  }}>
                    <span className="mono">{w.reference}</span> {store.vehicle(w.vehicleId)?.name}
                  </button>
                ))}
                {schedules.slice(0, 3).map((sc) => (
                  <button key={sc.id} onClick={() => app.open('vehicle', sc.vehicleId)} style={{
                    textAlign: 'left', fontSize: 10, padding: '2px 5px', borderRadius: 4,
                    background: sc.status === 'overdue' || sc.status === 'critical'
                      ? 'rgba(231,76,60,.15)' : 'var(--sunken)',
                    borderLeft: `2px solid ${sc.status === 'overdue' || sc.status === 'critical'
                      ? 'var(--danger)' : 'var(--warning)'}`,
                  }}>
                    {store.vehicle(sc.vehicleId)?.name} · {sc.name}
                  </button>
                ))}
                {orders.length + schedules.length > 6 && (
                  <span className="dim" style={{ fontSize: 10 }}>
                    +{orders.length + schedules.length - 6}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="row wrap" style={{ gap: 14, padding: '9px 14px', fontSize: 11 }}>
        <span className="row" style={{ gap: 6 }}>
          <i style={{ width: 10, height: 3, background: 'var(--pulse)' }} /> Work order
        </span>
        <span className="row" style={{ gap: 6 }}>
          <i style={{ width: 10, height: 3, background: 'var(--warning)' }} /> Service due
        </span>
        <span className="row" style={{ gap: 6 }}>
          <i style={{ width: 10, height: 3, background: 'var(--danger)' }} /> Overdue
        </span>
      </div>
    </Card>
  );
}

function HistoryTab() {
  const app = useApp();
  const { store, state: s } = app;
  const [vehicleId, setVehicleId] = useState('');
  const records = s.maintenanceRecords
    .filter((r) => !vehicleId || r.vehicleId === vehicleId)
    .sort((a, b) => b.serviceDate.localeCompare(a.serviceDate));
  const total = records.reduce((a, r) => a + r.totalCost, 0);
  const downtime = records.reduce((a, r) => a + r.downtimeHours, 0);
  const vehicle = store.vehicle(vehicleId);
  const spanKm = vehicle
    ? Math.max(1, vehicle.odometerKm - Math.min(...records.map((r) => r.odometerKm), vehicle.odometerKm))
    : null;

  return (
    <div className="stack">
      <div className="row wrap" style={{ gap: 8 }}>
        <select className="select" style={{ maxWidth: 240 }} value={vehicleId}
                onChange={(e) => setVehicleId(e.target.value)}>
          <option value="">All vehicles</option>
          {s.vehicles.map((v) => (
            <option key={v.id} value={v.id}>{v.name} · {v.plate}</option>
          ))}
        </select>
      </div>
      <div className="kpis">
        <Kpi label="Services" value={records.length} />
        <Kpi label="Total cost" value={<Money value={total} />} />
        <Kpi label="Cost per service"
             value={<Money value={records.length ? total / records.length : 0} />} />
        {spanKm && (
          <Kpi label="Cost per km" value={`€${(total / spanKm).toFixed(3)}`} />
        )}
        <Kpi label="Downtime" value={downtime.toFixed(0)} unit=" h" />
        {spanKm && (
          <Kpi label="Failures / 10,000 km"
               value={(records.length / spanKm * 10000).toFixed(2)} />
        )}
      </div>
      <Card pad={false}>
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Date</th><th>Vehicle</th><th>Work performed</th>
                       <th className="num">Odometer</th><th className="num">Parts</th>
                       <th className="num">Labour</th><th className="num">Total</th>
                       <th className="num">Downtime</th><th>Workshop</th><th>Technician</th></tr></thead>
            <tbody>
              {records.slice(0, 120).map((r) => (
                <tr key={r.id}>
                  <td>{r.serviceDate}</td>
                  <td className="mono">{store.vehicle(r.vehicleId)?.name}</td>
                  <td>{r.workPerformed}</td>
                  <td className="num">{Math.round(r.odometerKm).toLocaleString()}</td>
                  <td className="num">€{r.partsCost.toFixed(0)}</td>
                  <td className="num">€{r.labourCost.toFixed(0)}</td>
                  <td className="num">€{r.totalCost.toFixed(0)}</td>
                  <td className="num">{r.downtimeHours.toFixed(1)} h</td>
                  <td className="truncate" style={{ maxWidth: 150 }}>{r.workshopName}</td>
                  <td>{r.technician}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function WorkshopsTab() {
  const { state: s } = useApp();
  const today = new Date(s.now).toISOString().slice(0, 10);
  return (
    <div className="grid-2">
      {s.workshops.map((w) => {
        const booked = s.workOrders.filter(
          (o) => o.workshopId === w.id && o.scheduledStart &&
                 new Date(o.scheduledStart).toISOString().slice(0, 10) === today &&
                 OPEN_WO_STATUSES.includes(o.status)).length;
        return (
          <Card key={w.id} title={w.name}
                actions={<Pill tone={w.internal ? 'info' : 'neutral'}>
                  {w.internal ? 'Internal' : 'External'}</Pill>}>
            <dl className="kv">
              <dt>Address</dt><dd>{w.address}</dd>
              <dt>Contact</dt><dd>{w.contactName} · {w.contactPhone}</dd>
              <dt>Hours</dt><dd className="num">{w.openingTime} – {w.closingTime}</dd>
              <dt>Capacity today</dt>
              <dd>
                <span className="num">{booked}/{w.dailyCapacity}</span>
                {booked >= w.dailyCapacity && <Pill tone="danger">Full</Pill>}
              </dd>
              <dt>Services</dt><dd>{w.services.join(', ')}</dd>
            </dl>
          </Card>
        );
      })}
    </div>
  );
}

function TemplatesTab() {
  const app = useApp();
  const { store, state: s } = app;
  const [applying, setApplying] = useState<number | null>(null);
  const [vehicleIds, setVehicleIds] = useState<Set<string>>(new Set());

  return (
    <>
      <div className="grid-2">
        {MAINTENANCE_TEMPLATES.map((t, i) => (
          <Card key={t.name} title={t.name}
                actions={<Button size="sm" onClick={() => { setApplying(i); setVehicleIds(new Set()); }}>
                  Apply to vehicles
                </Button>}>
            <p className="muted" style={{ marginTop: 0, fontSize: 12.5 }}>{t.description}</p>
            <dl className="kv">
              <dt>Interval</dt>
              <dd>{t.intervalKm.toLocaleString()} km or {t.intervalMonths} months — whichever first</dd>
              <dt>Estimated cost</dt>
              <dd className="num">€{t.items.reduce((a, x) => a + x.cost, 0)}</dd>
              <dt>Estimated time</dt>
              <dd className="num">{t.items.reduce((a, x) => a + x.minutes, 0)} min</dd>
            </dl>
            <div className="table-wrap" style={{ marginTop: 10 }}>
              <table className="data">
                <thead><tr><th>Item</th><th className="num">Cost</th><th className="num">Time</th></tr></thead>
                <tbody>
                  {t.items.map((item) => (
                    <tr key={item.category}>
                      <td>{item.label}</td>
                      <td className="num">€{item.cost}</td>
                      <td className="num">{item.minutes} min</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        ))}
      </div>

      {applying != null && (
        <Modal title={`Apply “${MAINTENANCE_TEMPLATES[applying].name}”`}
               onClose={() => setApplying(null)}
               subtitle="Creates a preventive schedule for each item, on each selected vehicle."
               footer={<>
                 <Button onClick={() => setApplying(null)}>Cancel</Button>
                 <Button variant="primary" disabled={!vehicleIds.size} onClick={() => {
                   const tpl = MAINTENANCE_TEMPLATES[applying];
                   let n = 0;
                   vehicleIds.forEach((vid) => {
                     tpl.items.forEach((item) => {
                       try {
                         createSchedule(store, {
                           vehicleId: vid, name: item.label, category: item.category,
                           intervalKm: tpl.intervalKm, intervalMonths: tpl.intervalMonths,
                           estimatedCost: item.cost, estimatedMinutes: item.minutes,
                         });
                         n++;
                       } catch { /* skipped */ }
                     });
                   });
                   app.toast('success',
                     `${n} schedule${n === 1 ? '' : 's'} created across ${vehicleIds.size} vehicle(s)`);
                   setApplying(null);
                 }}>
                   Apply to {vehicleIds.size} vehicle{vehicleIds.size === 1 ? '' : 's'}
                 </Button>
               </>}>
          <div className="stack-sm">
            {s.vehicles.filter((v) => v.lifecycle !== 'retired').map((v) => (
              <label key={v.id} className="row" style={{
                gap: 9, padding: '7px 10px', borderRadius: 7,
                border: `1px solid ${vehicleIds.has(v.id) ? 'var(--pulse)' : 'var(--line)'}`,
              }}>
                <input type="checkbox" checked={vehicleIds.has(v.id)}
                       onChange={(e) => {
                         const next = new Set(vehicleIds);
                         if (e.target.checked) next.add(v.id); else next.delete(v.id);
                         setVehicleIds(next);
                       }} />
                <span className="grow">{v.name} · <span className="mono dim">{v.plate}</span></span>
                <span className="dim" style={{ fontSize: 11 }}>{titleCase(v.type)}</span>
              </label>
            ))}
          </div>
        </Modal>
      )}
    </>
  );
}

// --------------------------------------------------------------------------
function WorkOrderComposer({ onClose, onCreated, presetVehicle, presetSchedule }: {
  onClose: () => void; onCreated: (id: string) => void;
  presetVehicle?: string; presetSchedule?: string;
}) {
  const app = useApp();
  const { store, state: s } = app;
  const [vehicleId, setVehicleId] = useState(presetVehicle ?? s.vehicles[0]?.id ?? '');
  const [scheduleId, setScheduleId] = useState(presetSchedule ?? '');
  const [title, setTitle] = useState('');
  const [problem, setProblem] = useState('');
  const [priority, setPriority] = useState<'low' | 'normal' | 'high' | 'urgent'>('normal');
  const [workshopId, setWorkshopId] = useState(s.workshops[0]?.id ?? '');
  const [technician, setTechnician] = useState(TECHNICIANS[0]);
  const [dayOffset, setDayOffset] = useState(1);
  const [hour, setHour] = useState(9);
  const [durationMin, setDurationMin] = useState(120);
  const [acknowledge, setAcknowledge] = useState(false);

  const schedule = s.schedules.find((x) => x.id === scheduleId);
  useEffect(() => {
    if (schedule && !title) { setTitle(schedule.name); setDurationMin(schedule.estimatedMinutes); }
  }, [schedule, title]);

  const start = useMemo(() => {
    const d = new Date(s.now + dayOffset * DAY);
    d.setUTCHours(hour, 0, 0, 0);
    return d.getTime();
  }, [s.now, dayOffset, hour]);

  const impact = useMemo(() => {
    if (!vehicleId) return null;
    try { return maintenanceImpact(store, vehicleId, start, durationMin); }
    catch { return null; }
  }, [store, vehicleId, start, durationMin]);

  const schedulesForVehicle = s.schedules.filter((x) => x.vehicleId === vehicleId && x.active);

  return (
    <Modal title="Raise a work order" size="lg" onClose={onClose}
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant={impact?.hasConflict ? 'danger' : 'primary'}
                     disabled={!title.trim() || (impact?.hasConflict && !acknowledge)}
                     onClick={() => {
                       try {
                         const wo = createWorkOrder(store, {
                           vehicleId, title, problem: problem || undefined, priority,
                           workshopId, technician, scheduledStart: start,
                           expectedCompletion: start + durationMin * 60000,
                           scheduleId: scheduleId || undefined,
                           estimatedCost: schedule?.estimatedCost ?? 0,
                           category: schedule?.category,
                           acknowledgeConflict: acknowledge,
                         });
                         app.toast('success', `${wo.reference} raised`);
                         onCreated(wo.id);
                         onClose();
                       } catch (e) {
                         app.toast('error',
                           e instanceof ActionError ? e.message : 'Could not raise the work order.',
                           e instanceof ActionError ? e.hint : undefined);
                       }
                     }}>
               {impact?.hasConflict ? 'Schedule anyway' : 'Raise work order'}
             </Button>
           </>}>
      <div className="stack">
        <div className="grid-2">
          <Field label="Vehicle">
            <select className="select" value={vehicleId}
                    onChange={(e) => { setVehicleId(e.target.value); setScheduleId(''); }}>
              {s.vehicles.filter((v) => v.lifecycle !== 'retired').map((v) => (
                <option key={v.id} value={v.id}>{v.name} · {v.plate}</option>
              ))}
            </select>
          </Field>
          <Field label="Against a preventive schedule (optional)">
            <select className="select" value={scheduleId}
                    onChange={(e) => {
                      setScheduleId(e.target.value);
                      const sc = s.schedules.find((x) => x.id === e.target.value);
                      if (sc) { setTitle(sc.name); setDurationMin(sc.estimatedMinutes); }
                    }}>
              <option value="">Corrective work (no schedule)</option>
              {schedulesForVehicle.map((sc) => (
                <option key={sc.id} value={sc.id}>
                  {sc.name} — {titleCase(sc.status)}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <Field label="Title">
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)}
                 placeholder="Front brake pads and discs" />
        </Field>
        <Field label="Problem reported">
          <textarea className="textarea" value={problem}
                    onChange={(e) => setProblem(e.target.value)}
                    placeholder="Driver reports a squeal under braking from cold." />
        </Field>

        <div className="grid-2">
          <Field label="Priority">
            <select className="select" value={priority}
                    onChange={(e) => setPriority(e.target.value as typeof priority)}>
              {['low', 'normal', 'high', 'urgent'].map((p) =>
                <option key={p} value={p}>{titleCase(p)}</option>)}
            </select>
          </Field>
          <Field label="Workshop">
            <select className="select" value={workshopId}
                    onChange={(e) => setWorkshopId(e.target.value)}>
              {s.workshops.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </Field>
          <Field label="Technician">
            <select className="select" value={technician}
                    onChange={(e) => setTechnician(e.target.value)}>
              {TECHNICIANS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>
          <Field label="Duration (minutes)">
            <input className="input" type="number" min={30} max={960} value={durationMin}
                   onChange={(e) => setDurationMin(Number(e.target.value))} />
          </Field>
          <Field label="Day">
            <select className="select" value={dayOffset}
                    onChange={(e) => setDayOffset(Number(e.target.value))}>
              {[0, 1, 2, 3, 4, 5, 6, 7].map((d) => (
                <option key={d} value={d}>
                  {d === 0 ? 'Today' : d === 1 ? 'Tomorrow'
                    : new Date(s.now + d * DAY).toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'short' })}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Start hour">
            <select className="select" value={hour}
                    onChange={(e) => setHour(Number(e.target.value))}>
              {Array.from({ length: 11 }, (_, i) => i + 7).map((h) => (
                <option key={h} value={h}>{String(h).padStart(2, '0')}:00</option>
              ))}
            </select>
          </Field>
        </div>

        {impact && (
          <Card title="Operational impact">
            <dl className="kv">
              <dt>Window</dt>
              <dd className="num">
                {dmy(start)} {hm(start)} – {hm(start + durationMin * 60000)}
              </dd>
              <dt>Tasks affected</dt>
              <dd className="num" style={{
                color: impact.affectedTaskCount ? 'var(--warning)' : 'var(--success)',
              }}>{impact.affectedTaskCount}</dd>
              {impact.affectedDistanceKm > 0 && (
                <>
                  <dt>Distance affected</dt>
                  <dd className="num">{impact.affectedDistanceKm} km</dd>
                </>
              )}
              <dt>Alternative vehicle</dt>
              <dd>{impact.alternative
                ? `${impact.alternative.name} (${impact.alternative.activeTasks} active tasks)`
                : 'None of the same type available'}</dd>
            </dl>

            {impact.affectedTasks.length > 0 && (
              <div className="table-wrap" style={{ marginTop: 10 }}>
                <table className="data">
                  <thead><tr><th>Task</th><th>Scheduled</th><th>Priority</th><th>Status</th></tr></thead>
                  <tbody>
                    {impact.affectedTasks.map((t) => (
                      <tr key={t.id}>
                        <td><span className="mono">{t.reference}</span> {t.title}</td>
                        <td className="num">{hm(t.scheduledFor)}</td>
                        <td>{titleCase(t.priority)}</td>
                        <td>{titleCase(t.status)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )}

        {impact?.hasConflict && (
          <>
            <div className="banner" data-tone="warn">
              <IconAlert size={15} />
              <span>
                <strong>Maintenance conflict.</strong>{' '}
                {store.vehicle(vehicleId)?.name} has {impact.affectedTaskCount} scheduled task
                {impact.affectedTaskCount === 1 ? '' : 's'} in that window.
                {impact.alternative && ` ${impact.alternative.name} is the lightest-loaded alternative.`}
              </span>
            </div>
            <label className="row" style={{ gap: 8, fontSize: 12.5 }}>
              <input type="checkbox" checked={acknowledge}
                     onChange={(e) => setAcknowledge(e.target.checked)} />
              I have reviewed the impact and want to schedule anyway.
            </label>
          </>
        )}
      </div>
    </Modal>
  );
}

function ScheduleComposer({ onClose }: { onClose: () => void }) {
  const app = useApp();
  const { store, state: s } = app;
  const [vehicleId, setVehicleId] = useState(s.vehicles[0]?.id ?? '');
  const [name, setName] = useState('Engine oil & filter');
  const [category, setCategory] = useState('engine_oil');
  const [intervalKm, setIntervalKm] = useState(15000);
  const [intervalMonths, setIntervalMonths] = useState(12);
  const [cost, setCost] = useState(145);
  const [minutes, setMinutes] = useState(60);

  return (
    <Modal title="New preventive schedule" onClose={onClose}
           subtitle="Mileage or time — FleetBeat uses whichever threshold is reached first."
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant="primary" onClick={() => {
               const ok = app.run(() => createSchedule(store, {
                 vehicleId, name, category,
                 intervalKm: intervalKm || undefined,
                 intervalMonths: intervalMonths || undefined,
                 estimatedCost: cost, estimatedMinutes: minutes,
               }), 'Schedule created');
               if (ok) onClose();
             }}>Create schedule</Button>
           </>}>
      <div className="stack">
        <Field label="Vehicle">
          <select className="select" value={vehicleId} onChange={(e) => setVehicleId(e.target.value)}>
            {s.vehicles.filter((v) => v.lifecycle !== 'retired').map((v) => (
              <option key={v.id} value={v.id}>
                {v.name} · {v.plate} · {Math.round(v.odometerKm).toLocaleString()} km
              </option>
            ))}
          </select>
        </Field>
        <div className="grid-2">
          <Field label="Service name">
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Category">
            <select className="select" value={category} onChange={(e) => setCategory(e.target.value)}>
              {['engine_oil', 'oil_filter', 'air_filter', 'brake_inspection', 'brake_pads',
                'tires', 'battery', 'transmission', 'cooling', 'air_conditioning',
                'suspension', 'steering', 'fluids', 'general_inspection'].map((c) =>
                <option key={c} value={c}>{titleCase(c)}</option>)}
            </select>
          </Field>
          <Field label="Mileage interval (km)" hint="Leave 0 for time-only.">
            <input className="input" type="number" value={intervalKm}
                   onChange={(e) => setIntervalKm(Number(e.target.value))} />
          </Field>
          <Field label="Time interval (months)" hint="Leave 0 for mileage-only.">
            <input className="input" type="number" value={intervalMonths}
                   onChange={(e) => setIntervalMonths(Number(e.target.value))} />
          </Field>
          <Field label="Estimated cost (€)">
            <input className="input" type="number" value={cost}
                   onChange={(e) => setCost(Number(e.target.value))} />
          </Field>
          <Field label="Estimated time (minutes)">
            <input className="input" type="number" value={minutes}
                   onChange={(e) => setMinutes(Number(e.target.value))} />
          </Field>
        </div>
        {intervalKm > 0 && intervalMonths > 0 && (
          <div className="banner" data-tone="info">
            <span>
              Due every {intervalKm.toLocaleString()} km <strong>or</strong> {intervalMonths}{' '}
              months, whichever occurs first.
            </span>
          </div>
        )}
      </div>
    </Modal>
  );
}

function WorkOrderDetail({ woId, onClose }: { woId: string; onClose: () => void }) {
  const app = useApp();
  const { store, state: s } = app;
  const wo = store.workOrder(woId);
  const [addingPart, setAddingPart] = useState(false);
  const [labourHours, setLabourHours] = useState(wo?.labourHours ?? 0);
  const [diagnosis, setDiagnosis] = useState(wo?.diagnosis ?? '');
  const [workPerformed, setWorkPerformed] = useState(wo?.workPerformed ?? '');
  if (!wo) return null;
  const v = store.vehicle(wo.vehicleId);
  const workshop = store.workshop(wo.workshopId);
  const timeline = store.timelineFor('work_order', wo.id).sort((a, b) => b.occurredAt - a.occurredAt);
  const next = WO_FLOW[wo.status];
  const overdue = wo.expectedCompletion && OPEN_WO_STATUSES.includes(wo.status) &&
    wo.expectedCompletion < s.now;

  return (
    <Modal title={`${wo.reference} — ${wo.title}`} size="lg" onClose={onClose}
           subtitle={
             <div className="row wrap" style={{ gap: 7 }}>
               <Pill tone={wo.status === 'completed' ? 'good'
                 : wo.status === 'cancelled' ? 'neutral' : 'info'}>{titleCase(wo.status)}</Pill>
               <Pill tone={wo.priority === 'urgent' ? 'danger'
                 : wo.priority === 'high' ? 'warn' : 'neutral'}>{titleCase(wo.priority)}</Pill>
               {v && (
                 <button className="mono" style={{ color: 'var(--pulse)' }}
                         onClick={() => { app.open('vehicle', v.id); onClose(); }}>
                   {v.name} · {v.plate}
                 </button>
               )}
               {overdue && <Pill tone="danger">Past expected completion</Pill>}
             </div>
           }
           footer={
             <>
               {wo.status !== 'completed' && wo.status !== 'cancelled' && (
                 <Button size="sm" onClick={() => {
                   app.run(() => updateWorkOrder(store, wo.id, {
                     labourHours, diagnosis, workPerformed,
                   }), 'Work order updated');
                 }}>Save notes</Button>
               )}
               <div className="grow" />
               {next.map((target) => (
                 <Button key={target} size="sm"
                         variant={target === 'completed' ? 'primary'
                           : target === 'cancelled' ? 'danger' : undefined}
                         onClick={() => {
                           app.run(() => setWorkOrderStatus(store, wo.id, target as WorkOrderStatus),
                                   `${wo.reference} → ${titleCase(target)}`);
                         }}>
                   {target === 'completed' ? 'Complete work order' : titleCase(target)}
                 </Button>
               ))}
             </>
           }>
      <div className="stack">
        <div className="kpis">
          <Kpi label="Parts" value={<Money value={wo.partsCost} />} />
          <Kpi label="Labour" value={<Money value={wo.labourCost} />}
               foot={`${wo.labourHours} h @ €${wo.labourRate}/h`} />
          <Kpi label="Total" value={<Money value={wo.totalCost} />} tone="pulse" />
          <Kpi label="Estimated" value={<Money value={wo.estimatedCost} />} />
          <Kpi label="Downtime"
               value={wo.downtimeHours != null ? wo.downtimeHours.toFixed(1)
                 : wo.actualStart ? ((s.now - wo.actualStart) / HOUR).toFixed(1) : '—'}
               unit=" h" />
        </div>

        <div className="grid-2">
          <Card title="Job">
            <dl className="kv">
              <dt>Category</dt><dd>{titleCase(wo.category)}</dd>
              <dt>Workshop</dt><dd>{workshop?.name ?? '—'}</dd>
              <dt>Technician</dt><dd>{wo.technician ?? '—'}</dd>
              <dt>Odometer</dt>
              <dd className="num">{Math.round(wo.odometerKm).toLocaleString()} km</dd>
              <dt>Raised</dt><dd>{dmy(wo.createdAt)} {hm(wo.createdAt)}</dd>
            </dl>
          </Card>
          <Card title="Schedule">
            <dl className="kv">
              <dt>Booked for</dt>
              <dd className="num">
                {wo.scheduledStart ? `${dmy(wo.scheduledStart)} ${hm(wo.scheduledStart)}` : '—'}
              </dd>
              <dt>Expected done</dt>
              <dd className="num">{wo.expectedCompletion ? hm(wo.expectedCompletion) : '—'}</dd>
              <dt>Started</dt>
              <dd className="num">{wo.actualStart ? hm(wo.actualStart) : 'Not started'}</dd>
              <dt>Completed</dt>
              <dd className="num">{wo.actualCompletion ? hm(wo.actualCompletion) : '—'}</dd>
            </dl>
          </Card>
        </div>

        <Card title="Problem, diagnosis and work">
          <div className="stack-sm">
            <Field label="Problem reported">
              <textarea className="textarea" defaultValue={wo.problem ?? ''} readOnly
                        style={{ background: 'var(--sunken)' }} />
            </Field>
            <Field label="Diagnosis">
              <textarea className="textarea" value={diagnosis}
                        disabled={wo.status === 'completed' || wo.status === 'cancelled'}
                        onChange={(e) => setDiagnosis(e.target.value)}
                        placeholder="Front pads worn to 2 mm; discs within tolerance." />
            </Field>
            <Field label="Work performed">
              <textarea className="textarea" value={workPerformed}
                        disabled={wo.status === 'completed' || wo.status === 'cancelled'}
                        onChange={(e) => setWorkPerformed(e.target.value)}
                        placeholder="Replaced front pads, cleaned and re-greased sliders." />
            </Field>
            <Field label="Labour hours">
              <input className="input" type="number" step="0.5" value={labourHours}
                     disabled={wo.status === 'completed' || wo.status === 'cancelled'}
                     onChange={(e) => setLabourHours(Number(e.target.value))} />
            </Field>
          </div>
        </Card>

        <Card title="Parts" pad={false}
              actions={wo.status !== 'completed' && wo.status !== 'cancelled' ? (
                <Button size="sm" onClick={() => setAddingPart(true)}>
                  <IconPlus size={13} /> Add part
                </Button>
              ) : undefined}>
          {wo.parts.length === 0 ? (
            <Empty title="No parts recorded"
                   body="Add the parts used so the work order costs itself correctly."
                   action={wo.status !== 'completed' ? (
                     <Button size="sm" onClick={() => setAddingPart(true)}>Add part</Button>
                   ) : undefined} />
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>Part</th><th>SKU</th><th className="num">Qty</th>
                           <th className="num">Unit</th><th className="num">Total</th>
                           <th>Supplier</th><th>Warranty</th><th></th></tr></thead>
                <tbody>
                  {wo.parts.map((p) => (
                    <tr key={p.id}>
                      <td>{p.name}</td>
                      <td className="mono" style={{ fontSize: 11 }}>{p.sku}</td>
                      <td className="num">{p.quantity}</td>
                      <td className="num">€{p.unitCost.toFixed(2)}</td>
                      <td className="num">€{(p.quantity * p.unitCost).toFixed(2)}</td>
                      <td>{p.supplier}</td>
                      <td className="num">{p.warrantyMonths ? `${p.warrantyMonths} mo` : '—'}</td>
                      <td>
                        {wo.status !== 'completed' && wo.status !== 'cancelled' && (
                          <Button size="sm" variant="ghost" onClick={() => {
                            app.run(() => removeWorkOrderPart(store, wo.id, p.id),
                                    `${p.name} removed`);
                          }}>Remove</Button>
                        )}
                      </td>
                    </tr>
                  ))}
                  <tr>
                    <td colSpan={4} style={{ textAlign: 'right', fontWeight: 600 }}>Parts cost</td>
                    <td className="num" style={{ fontWeight: 600 }}>€{wo.partsCost.toFixed(2)}</td>
                    <td colSpan={3} />
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card title="Timeline"><Timeline entries={timeline} /></Card>
      </div>

      {addingPart && (
        <AddPart onClose={() => setAddingPart(false)} onAdd={(part) => {
          app.run(() => addWorkOrderPart(store, wo.id, part), `${part.name} added`);
          setAddingPart(false);
        }} />
      )}
    </Modal>
  );
}

function AddPart({ onClose, onAdd }: {
  onClose: () => void;
  onAdd: (p: { name: string; sku: string; quantity: number; unitCost: number;
               supplier: string; warrantyMonths?: number }) => void;
}) {
  const [idx, setIdx] = useState(0);
  const [quantity, setQuantity] = useState(1);
  const part = PARTS_CATALOG[idx];
  return (
    <Modal title="Add a part" onClose={onClose}
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant="primary" onClick={() => onAdd({
               name: part.name, sku: part.sku, quantity, unitCost: part.cost,
               supplier: part.supplier, warrantyMonths: 12,
             })}>
               Add — €{(part.cost * quantity).toFixed(2)}
             </Button>
           </>}>
      <div className="stack">
        <Field label="Part">
          <select className="select" value={idx} onChange={(e) => setIdx(Number(e.target.value))}>
            {PARTS_CATALOG.map((p, i) => (
              <option key={p.sku} value={i}>{p.name} — €{p.cost.toFixed(2)}</option>
            ))}
          </select>
        </Field>
        <Field label="Quantity">
          <input className="input" type="number" min={1} max={20} value={quantity}
                 onChange={(e) => setQuantity(Number(e.target.value))} />
        </Field>
        <dl className="kv">
          <dt>SKU</dt><dd className="mono">{part.sku}</dd>
          <dt>Supplier</dt><dd>{part.supplier}</dd>
          <dt>Line total</dt><dd className="num">€{(part.cost * quantity).toFixed(2)}</dd>
        </dl>
      </div>
    </Modal>
  );
}
