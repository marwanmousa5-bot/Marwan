// Task Manager: board, list, calendar and map views over the same tasks, plus
// the guided creation workflow and the full task record.

import { useEffect, useMemo, useState } from 'react';
import {
  assignTask, assignmentPreview, cancelTask, completeTaskWithPod, createTask,
  failTask, transitionTask, TASK_FLOW,
} from '../../engine/actions';
import { FAILURE_REASONS } from '../../engine/catalog';
import { slaMinutesRemaining } from '../../engine/derive';
import { ACTIVE_TASK_STATUSES, fleetRows } from '../../engine/selectors';
import type { Priority, Task, TaskKind, TaskStatus } from '../../engine/types';
import { useApp } from '../app-context';
import {
  Avatar, Button, Card, Empty, Field, Kpi, Modal, Pill, Progress, Timeline,
  dmy, hm, titleCase, type Tone,
} from '../components/kit';
import {
  IconAlert, IconCalendar, IconCheck, IconGrid, IconList, IconMap, IconPlus, IconRoute,
} from '../icons';
import { DEFAULT_LAYERS, FleetMap } from '../map/FleetMap';
import type { BaseData } from '../map/style';

const BOARD_COLUMNS: TaskStatus[] = [
  'unassigned', 'assigned', 'accepted', 'en_route', 'arrived', 'in_progress', 'completed',
];

export function Tasks({ base }: { base: BaseData }) {
  const app = useApp();
  const { store, state: s } = app;
  const [view, setView] = useState<'board' | 'list' | 'calendar' | 'map'>('board');
  const [compose, setCompose] = useState(app.params.compose === '1');
  const [openId, setOpenId] = useState<string | undefined>(app.params.task);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('');

  useEffect(() => { if (app.params.task) setOpenId(app.params.task); }, [app.params.task]);
  useEffect(() => { if (app.params.compose === '1') setCompose(true); }, [app.params.compose]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return s.tasks.filter((t) => {
      if (statusFilter && t.status !== statusFilter) return false;
      if (priorityFilter && t.priority !== priorityFilter) return false;
      if (q && ![t.reference, t.title, t.address].some((f) => f?.toLowerCase().includes(q))) return false;
      return true;
    }).sort((a, b) => (b.scheduledFor ?? b.createdAt) - (a.scheduledFor ?? a.createdAt));
  }, [s.tasks, query, statusFilter, priorityFilter]);

  const counts = useMemo(() => ({
    unassigned: s.tasks.filter((t) => t.status === 'unassigned').length,
    active: s.tasks.filter((t) => ACTIVE_TASK_STATUSES.includes(t.status)).length,
    atRisk: s.tasks.filter((t) => t.slaState === 'at_risk').length,
    breached: s.tasks.filter((t) => t.slaState === 'breached').length,
    completedToday: s.tasks.filter(
      (t) => t.completedAt && t.completedAt >= new Date(s.now).setUTCHours(0, 0, 0, 0)).length,
    failed: s.tasks.filter((t) => t.status === 'failed').length,
  }), [s.tasks, s.now]);

  const openTask = openId ? store.task(openId) : undefined;

  return (
    <div className="scroll">
      <div className="page">
        <div className="page-head">
          <div className="grow">
            <h2 className="page-title">Task Manager</h2>
            <p className="page-sub">
              Every job the fleet is asked to do, from creation through proof of delivery.
              The same tasks appear on the board, the list, the calendar and the map.
            </p>
          </div>
          <div className="row" style={{ gap: 2, background: 'var(--raised)', padding: 2,
                                        borderRadius: 8, border: '1px solid var(--line)' }}>
            {([['board', IconGrid], ['list', IconList], ['calendar', IconCalendar],
               ['map', IconMap]] as const).map(([key, Icon]) => (
              <button key={key} className="btn" data-size="sm"
                      data-variant={view === key ? 'primary' : 'ghost'}
                      onClick={() => setView(key)} title={titleCase(key)}>
                <Icon size={13} /> {titleCase(key)}
              </button>
            ))}
          </div>
          <Button variant="primary" onClick={() => setCompose(true)}>
            <IconPlus size={14} /> New task
          </Button>
        </div>

        <div className="kpis" style={{ marginBottom: 14 }}>
          <Kpi label="Unassigned" value={counts.unassigned}
               tone={counts.unassigned ? 'warn' : undefined}
               active={statusFilter === 'unassigned'}
               onClick={() => setStatusFilter(statusFilter === 'unassigned' ? '' : 'unassigned')} />
          <Kpi label="Active" value={counts.active} tone="pulse" />
          <Kpi label="SLA at risk" value={counts.atRisk} tone={counts.atRisk ? 'warn' : undefined} />
          <Kpi label="SLA breached" value={counts.breached}
               tone={counts.breached ? 'danger' : undefined} />
          <Kpi label="Completed today" value={counts.completedToday} tone="good" />
          <Kpi label="Failed" value={counts.failed} tone={counts.failed ? 'danger' : undefined}
               active={statusFilter === 'failed'}
               onClick={() => setStatusFilter(statusFilter === 'failed' ? '' : 'failed')} />
        </div>

        <div className="row wrap" style={{ gap: 8, marginBottom: 12 }}>
          <input className="input" placeholder="Search reference, title or address"
                 value={query} onChange={(e) => setQuery(e.target.value)}
                 style={{ maxWidth: 280 }} />
          <select className="select" style={{ width: 160 }} value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            {[...BOARD_COLUMNS, 'delayed', 'failed', 'cancelled'].map((x) =>
              <option key={x} value={x}>{titleCase(x)}</option>)}
          </select>
          <select className="select" style={{ width: 140 }} value={priorityFilter}
                  onChange={(e) => setPriorityFilter(e.target.value)}>
            <option value="">All priorities</option>
            {['low', 'normal', 'high', 'urgent'].map((x) =>
              <option key={x} value={x}>{titleCase(x)}</option>)}
          </select>
          <div className="grow" />
          <span className="dim" style={{ fontSize: 12 }}>{filtered.length} tasks</span>
        </div>

        {view === 'board' && <BoardView tasks={filtered} onOpen={setOpenId} />}
        {view === 'list' && <ListView tasks={filtered} onOpen={setOpenId} />}
        {view === 'calendar' && <CalendarView tasks={filtered} onOpen={setOpenId} />}
        {view === 'map' && <MapView base={base} tasks={filtered} onOpen={setOpenId} />}
      </div>

      {compose && <TaskComposer onClose={() => setCompose(false)} onCreated={setOpenId} />}
      {openTask && <TaskDetail task={openTask} onClose={() => setOpenId(undefined)} />}
    </div>
  );
}

function BoardView({ tasks, onOpen }: { tasks: Task[]; onOpen: (id: string) => void }) {
  const app = useApp();
  const grouped = new Map<string, Task[]>();
  BOARD_COLUMNS.forEach((c) => grouped.set(c, []));
  const exceptions: Task[] = [];
  tasks.forEach((t) => {
    if (t.status === 'delayed' || t.status === 'failed') exceptions.push(t);
    else if (t.status !== 'cancelled') grouped.get(t.status)?.push(t);
  });

  return (
    <div className="board">
      {BOARD_COLUMNS.map((col) => {
        const list = grouped.get(col) ?? [];
        return (
          <div key={col} className="column">
            <div className="column-head">
              <span className="title">{titleCase(col)}</span>
              <span className="count">{list.length}</span>
            </div>
            <div className="column-body" style={{ maxHeight: 520 }}>
              {list.length === 0 && (
                <div className="dim" style={{ fontSize: 11.5, padding: '8px 4px' }}>Empty</div>
              )}
              {list.map((t) => <MiniCard key={t.id} task={t} onOpen={() => onOpen(t.id)} />)}
            </div>
          </div>
        );
      })}
      {exceptions.length > 0 && (
        <div className="column" style={{ borderColor: 'var(--danger)' }}>
          <div className="column-head">
            <IconAlert size={13} />
            <span className="title">Exception</span>
            <span className="count">{exceptions.length}</span>
          </div>
          <div className="column-body" style={{ maxHeight: 520 }}>
            {exceptions.map((t) => <MiniCard key={t.id} task={t} onOpen={() => onOpen(t.id)} />)}
          </div>
        </div>
      )}
      {tasks.length === 0 && (
        <Empty title="No tasks match"
               body="Clear the filters, or create the first task of the day."
               action={<Button variant="primary"
                               onClick={() => app.navigate('tasks', { compose: '1' })}>
                         Create task
                       </Button>} />
      )}
    </div>
  );
}

function MiniCard({ task, onOpen }: { task: Task; onOpen: () => void }) {
  const app = useApp();
  const driver = app.store.driver(task.driverId);
  return (
    <button className="tcard" data-priority={task.priority} onClick={onOpen}>
      <div className="row"><span className="ref">{task.reference}</span></div>
      <div className="title">{task.title}</div>
      <div className="meta">
        <span className="mono">{hm(task.scheduledFor)}</span>
        {task.slaState === 'breached' && <Pill tone="danger">Breached</Pill>}
        {task.slaState === 'at_risk' && <Pill tone="warn">At risk</Pill>}
        {task.status === 'failed' && <Pill tone="danger">Failed</Pill>}
      </div>
      {driver && (
        <div className="meta">
          <Avatar name={driver.fullName} color={driver.avatarColor} size={17} />
          <span className="truncate">{driver.fullName}</span>
        </div>
      )}
    </button>
  );
}

function ListView({ tasks, onOpen }: { tasks: Task[]; onOpen: (id: string) => void }) {
  const app = useApp();
  const { store, state: s } = app;
  if (!tasks.length) {
    return <Empty title="No tasks match" body="Widen the filters to see more work." />;
  }
  return (
    <Card pad={false}>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Task</th><th>Customer</th><th>Status</th><th>Priority</th>
              <th>Driver</th><th>Vehicle</th><th>Scheduled</th><th>ETA</th><th>SLA</th>
            </tr>
          </thead>
          <tbody>
            {tasks.slice(0, 250).map((t) => {
              const driver = store.driver(t.driverId);
              const vehicle = store.vehicle(t.vehicleId);
              const mins = slaMinutesRemaining(t, s.now);
              return (
                <tr key={t.id} data-clickable="true" onClick={() => onOpen(t.id)}>
                  <td>
                    <div className="mono" style={{ fontSize: 11, color: 'var(--ink-4)' }}>
                      {t.reference}
                    </div>
                    <div style={{ fontWeight: 550 }}>{t.title}</div>
                  </td>
                  <td className="truncate" style={{ maxWidth: 170 }}>{t.address}</td>
                  <td><Pill tone={taskTone(t.status)}>{titleCase(t.status)}</Pill></td>
                  <td><Pill tone={t.priority === 'urgent' ? 'danger'
                    : t.priority === 'high' ? 'warn' : 'neutral'}>{t.priority}</Pill></td>
                  <td>{driver?.fullName ?? <span className="dim">—</span>}</td>
                  <td className="mono">{vehicle?.name ?? '—'}</td>
                  <td className="num">{hm(t.scheduledFor)}</td>
                  <td className="num">{hm(t.eta)}</td>
                  <td>
                    {t.slaState === 'none' ? <span className="dim">—</span> : (
                      <Pill tone={t.slaState === 'breached' ? 'danger'
                        : t.slaState === 'at_risk' ? 'warn'
                        : t.slaState === 'met' ? 'good' : 'info'}>
                        {t.status === 'completed' ? titleCase(t.slaState)
                          : mins == null ? '—'
                          : mins < 0 ? `${Math.abs(mins)} min over` : `${mins} min left`}
                      </Pill>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function taskTone(status: TaskStatus): Tone {
  if (status === 'completed') return 'good';
  if (status === 'failed' || status === 'delayed') return 'danger';
  if (status === 'cancelled') return 'neutral';
  if (status === 'unassigned') return 'warn';
  return 'info';
}

function CalendarView({ tasks, onOpen }: { tasks: Task[]; onOpen: (id: string) => void }) {
  const app = useApp();
  const now = app.state.now;
  const start = new Date(now);
  start.setUTCHours(0, 0, 0, 0);
  start.setUTCDate(start.getUTCDate() - start.getUTCDay() + 1);   // Monday
  const days = Array.from({ length: 7 }, (_, i) => start.getTime() + i * 86400000);

  return (
    <div className="grid-3" style={{ gridTemplateColumns: 'repeat(7, minmax(140px, 1fr))' }}>
      {days.map((day) => {
        const dayTasks = tasks.filter(
          (t) => (t.scheduledFor ?? 0) >= day && (t.scheduledFor ?? 0) < day + 86400000)
          .sort((a, b) => (a.scheduledFor ?? 0) - (b.scheduledFor ?? 0));
        const isToday = day === new Date(now).setUTCHours(0, 0, 0, 0);
        return (
          <div key={day} className="card" style={{
            borderColor: isToday ? 'var(--pulse)' : undefined, minHeight: 190,
          }}>
            <div className="card-head" style={{ padding: '8px 11px' }}>
              <div>
                <div className="eyebrow">
                  {new Date(day).toLocaleDateString([], { weekday: 'short' })}
                </div>
                <div className="num" style={{ fontSize: 15, fontWeight: 600 }}>
                  {new Date(day).getUTCDate()}
                </div>
              </div>
              <div className="grow" />
              <span className="mono dim">{dayTasks.length}</span>
            </div>
            <div style={{ padding: 7, display: 'flex', flexDirection: 'column', gap: 5 }}>
              {dayTasks.slice(0, 8).map((t) => (
                <button key={t.id} onClick={() => onOpen(t.id)} style={{
                  textAlign: 'left', padding: '5px 7px', borderRadius: 5,
                  background: 'var(--raised)', border: '1px solid var(--line-soft)',
                  borderLeft: `3px solid ${t.priority === 'urgent' ? 'var(--coral)'
                    : t.slaState === 'breached' ? 'var(--danger)' : 'var(--pulse)'}`,
                }}>
                  <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>
                    {hm(t.scheduledFor)} · {t.reference}
                  </div>
                  <div className="truncate" style={{ fontSize: 11.5 }}>{t.title}</div>
                </button>
              ))}
              {dayTasks.length > 8 && (
                <div className="dim" style={{ fontSize: 11 }}>+{dayTasks.length - 8} more</div>
              )}
              {!dayTasks.length && (
                <div className="dim" style={{ fontSize: 11, padding: 4 }}>No work scheduled</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function MapView({ base, tasks, onOpen }: {
  base: BaseData; tasks: Task[]; onOpen: (id: string) => void;
}) {
  const app = useApp();
  const { store, state: s } = app;
  const rows = useMemo(() => fleetRows(store), [store, s.ticks]);
  return (
    <div className="card" style={{ height: 560, position: 'relative', overflow: 'hidden' }}>
      <div className="map-area" style={{ position: 'absolute', inset: 0 }}>
        <FleetMap base={base} theme={app.theme}
                  rows={rows} routes={s.routes} geofences={s.geofences} places={s.places}
                  tasks={tasks} incidents={[]} disruptions={s.disruptions} weather={[]}
                  layers={{ ...DEFAULT_LAYERS, places: false }}
                  onSelectVehicle={(id) => app.navigate('live', { vehicle: id })}
                  onMapClick={(lon, lat) => {
                    // pick the nearest task pin within roughly 80 m of the click
                    const near = tasks
                      .map((t) => ({ t, d: Math.hypot(t.lon - lon, t.lat - lat) }))
                      .sort((a, b) => a.d - b.d)[0];
                    if (near && near.d < 0.0012) onOpen(near.t.id);
                  }} />
        <div className="map-attrib">© OpenStreetMap contributors</div>
        <div className="map-legend">
          <span className="eyebrow">Task pins</span>
          <span className="row"><i style={{ background: '#F5A623' }} /> Scheduled</span>
          <span className="row"><i style={{ background: '#FF6B35' }} /> Urgent</span>
          <span className="row"><i style={{ background: '#E74C3C' }} /> SLA breached</span>
          <span className="dim" style={{ fontSize: 10 }}>Click a pin to open the task</span>
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
// Guided creation
// --------------------------------------------------------------------------
const STEPS = ['Type', 'Customer', 'Timing', 'Crew', 'Detail', 'Review'];

function TaskComposer({ onClose, onCreated }: {
  onClose: () => void; onCreated: (id: string) => void;
}) {
  const app = useApp();
  const { store, state: s } = app;
  const [step, setStep] = useState(0);
  const [kind, setKind] = useState<TaskKind>('delivery');
  const [customerId, setCustomerId] = useState(s.customers[0]?.id ?? '');
  const [title, setTitle] = useState('Parcel delivery');
  const [priority, setPriority] = useState<Priority>('normal');
  const [scheduledOffset, setScheduledOffset] = useState(60);
  const [slaMinutes, setSlaMinutes] = useState(120);
  const [serviceMinutes, setServiceMinutes] = useState(10);
  const [driverId, setDriverId] = useState('');
  const [vehicleId, setVehicleId] = useState('');
  const [instructions, setInstructions] = useState('');

  const customer = store.customer(customerId);
  const place = store.place(customer?.placeId);
  const vehicle = store.vehicle(vehicleId);
  const driver = store.driver(driverId);

  const routePreview = useMemo(() => {
    if (!place || !vehicle?.lat) return null;
    const r = store.graph.route([[vehicle.lon!, vehicle.lat], [place.lon, place.lat]]);
    return r.ok ? r : null;
  }, [place, vehicle, store]);

  const conflictPreview = useMemo(() => {
    if (!place) return null;
    const draft: Task = {
      id: 'draft', reference: 'draft', title, kind, status: 'unassigned', priority,
      address: place.address ?? place.name, lat: place.lat, lon: place.lon,
      slaState: 'none', serviceMinutes, createdAt: s.now,
      scheduledFor: s.now + scheduledOffset * 60000,
      slaDueAt: s.now + (scheduledOffset + slaMinutes) * 60000,
    };
    try { return assignmentPreview(store, draft, driver, vehicle); } catch { return null; }
  }, [store, place, driver, vehicle, title, kind, priority, serviceMinutes,
      scheduledOffset, slaMinutes, s.now]);

  const next = () => setStep((x) => Math.min(x + 1, STEPS.length - 1));
  const back = () => setStep((x) => Math.max(x - 1, 0));

  const submit = () => {
    const created = app.run(() => createTask(store, {
      title: `${title}${customer ? ` — ${customer.name}` : ''}`,
      kind, priority, customerId, slaMinutes, serviceMinutes,
      scheduledFor: s.now + scheduledOffset * 60000,
      instructions: instructions || undefined,
      driverId: driverId || undefined, vehicleId: vehicleId || undefined,
    }), 'Task created');
    if (created) { onCreated(created.id); onClose(); }
  };

  return (
    <Modal title="Create a task" size="lg" onClose={onClose}
           subtitle={
             <div className="row" style={{ gap: 6, marginTop: 4 }}>
               {STEPS.map((label, i) => (
                 <span key={label} className="row" style={{ gap: 5 }}>
                   <span style={{
                     width: 18, height: 18, borderRadius: '50%', display: 'grid',
                     placeItems: 'center', fontSize: 10, fontFamily: 'var(--font-mono)',
                     background: i <= step ? 'var(--pulse)' : 'var(--sunken)',
                     color: i <= step ? '#fff' : 'var(--ink-4)',
                   }}>{i + 1}</span>
                   <span style={{ fontSize: 11.5, color: i === step ? 'var(--ink)' : 'var(--ink-4)' }}>
                     {label}
                   </span>
                 </span>
               ))}
             </div>
           }
           footer={
             <>
               {step > 0 && <Button onClick={back}>Back</Button>}
               <div className="grow" />
               <Button onClick={onClose}>Cancel</Button>
               {step < STEPS.length - 1
                 ? <Button variant="primary" onClick={next}
                           disabled={step === 1 && !customerId}>Continue</Button>
                 : <Button variant="primary" onClick={submit}>Create task</Button>}
             </>
           }>
      <div className="stack">
        {step === 0 && (
          <>
            <Field label="Task type">
              <div className="row wrap" style={{ gap: 6 }}>
                {(['delivery', 'pickup', 'service_call', 'inspection', 'collection', 'custom'] as TaskKind[])
                  .map((k) => (
                    <button key={k} className="chip" data-on={kind === k}
                            onClick={() => setKind(k)}>{titleCase(k)}</button>
                  ))}
              </div>
            </Field>
            <Field label="Title">
              <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
            </Field>
            <Field label="Priority">
              <div className="row wrap" style={{ gap: 6 }}>
                {(['low', 'normal', 'high', 'urgent'] as Priority[]).map((p) => (
                  <button key={p} className="chip" data-on={priority === p}
                          onClick={() => setPriority(p)}>{titleCase(p)}</button>
                ))}
              </div>
            </Field>
          </>
        )}

        {step === 1 && (
          <>
            <Field label="Customer" hint="Customer sites come from real Helsinki addresses.">
              <select className="select" value={customerId}
                      onChange={(e) => setCustomerId(e.target.value)}>
                {s.customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>
            {place && (
              <Card title="Destination">
                <dl className="kv">
                  <dt>Address</dt><dd>{place.address}</dd>
                  <dt>Contact</dt><dd>{customer?.contactName} · {customer?.contactPhone}</dd>
                  <dt>Coordinates</dt>
                  <dd className="mono">{place.lat.toFixed(5)}, {place.lon.toFixed(5)}</dd>
                </dl>
              </Card>
            )}
          </>
        )}

        {step === 2 && (
          <>
            <Field label="Scheduled in (minutes from now)">
              <input className="input" type="number" min={0} max={1440} value={scheduledOffset}
                     onChange={(e) => setScheduledOffset(Number(e.target.value))} />
            </Field>
            <div className="grid-2">
              <Field label="SLA window (minutes)"
                     hint="Measured from the scheduled time.">
                <input className="input" type="number" min={15} max={720} value={slaMinutes}
                       onChange={(e) => setSlaMinutes(Number(e.target.value))} />
              </Field>
              <Field label="On-site service time (minutes)">
                <input className="input" type="number" min={1} max={180} value={serviceMinutes}
                       onChange={(e) => setServiceMinutes(Number(e.target.value))} />
              </Field>
            </div>
            <div className="banner" data-tone="info">
              <span>
                Scheduled {hm(s.now + scheduledOffset * 60000)}, deadline{' '}
                {hm(s.now + (scheduledOffset + slaMinutes) * 60000)}.
              </span>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <Field label="Driver">
              <select className="select" value={driverId}
                      onChange={(e) => {
                        setDriverId(e.target.value);
                        const v = s.vehicles.find((x) => x.driverId === e.target.value);
                        if (v) setVehicleId(v.id);
                      }}>
                <option value="">Leave unassigned</option>
                {s.drivers.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.fullName} — {titleCase(d.status)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Vehicle">
              <select className="select" value={vehicleId}
                      onChange={(e) => setVehicleId(e.target.value)}>
                <option value="">Leave unassigned</option>
                {s.vehicles.filter((v) => v.lifecycle === 'active').map((v) => (
                  <option key={v.id} value={v.id}>{v.name} · {v.plate}</option>
                ))}
              </select>
            </Field>
            {routePreview && (
              <div className="banner" data-tone="info">
                <IconRoute size={15} />
                <span>
                  {(routePreview.distanceM / 1000).toFixed(1)} km, about{' '}
                  {Math.round(routePreview.durationS / 60)} min
                  {routePreview.streets.length > 0 &&
                    <> via {routePreview.streets.slice(0, 3).join(', ')}</>}
                </span>
              </div>
            )}
            {conflictPreview?.conflicts.map((c, i) => (
              <div key={i} className="banner" data-tone="danger">
                <IconAlert size={15} /><span>{c.message}</span>
              </div>
            ))}
            {conflictPreview?.warnings.map((w, i) => (
              <div key={i} className="banner" data-tone="warn">
                <IconAlert size={15} /><span>{w}</span>
              </div>
            ))}
          </>
        )}

        {step === 4 && (
          <Field label="Instructions for the driver"
                 hint="Shown on the task card in the driver app.">
            <textarea className="textarea" value={instructions}
                      onChange={(e) => setInstructions(e.target.value)}
                      placeholder="Use the rear loading bay; buzz for the goods lift." />
          </Field>
        )}

        {step === 5 && (
          <Card title="Review">
            <dl className="kv">
              <dt>Type</dt><dd>{titleCase(kind)}</dd>
              <dt>Title</dt><dd>{title}{customer ? ` — ${customer.name}` : ''}</dd>
              <dt>Destination</dt><dd>{place?.address ?? '—'}</dd>
              <dt>Priority</dt><dd>{titleCase(priority)}</dd>
              <dt>Scheduled</dt><dd>{hm(s.now + scheduledOffset * 60000)}</dd>
              <dt>SLA deadline</dt><dd>{hm(s.now + (scheduledOffset + slaMinutes) * 60000)}</dd>
              <dt>Driver</dt><dd>{driver?.fullName ?? 'Unassigned'}</dd>
              <dt>Vehicle</dt><dd>{vehicle ? `${vehicle.name} · ${vehicle.plate}` : 'Unassigned'}</dd>
              {routePreview && (
                <>
                  <dt>Projected ETA</dt>
                  <dd className="num">{hm(s.now + routePreview.durationS * 1000)}</dd>
                </>
              )}
              {instructions && <><dt>Instructions</dt><dd>{instructions}</dd></>}
            </dl>
          </Card>
        )}
      </div>
    </Modal>
  );
}

// --------------------------------------------------------------------------
// Task record
// --------------------------------------------------------------------------
export function TaskDetail({ task, onClose }: { task: Task; onClose: () => void }) {
  const app = useApp();
  const { store, state: s } = app;
  const driver = store.driver(task.driverId);
  const vehicle = store.vehicle(task.vehicleId);
  const route = store.route(task.routeId);
  const trip = s.trips.find((t) => t.taskId === task.id);
  const timeline = store.timelineFor('task', task.id)
    .sort((a, b) => a.occurredAt - b.occurredAt);
  const [reassign, setReassign] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [failing, setFailing] = useState(false);
  const [pod, setPod] = useState(false);
  const mins = slaMinutesRemaining(task, s.now);
  const allowed = TASK_FLOW[task.status];

  return (
    <Modal title={`${task.reference} — ${task.title}`} size="lg" onClose={onClose}
           subtitle={
             <div className="row wrap" style={{ gap: 7 }}>
               <Pill tone={taskTone(task.status)}>{titleCase(task.status)}</Pill>
               <Pill tone={task.priority === 'urgent' ? 'danger'
                 : task.priority === 'high' ? 'warn' : 'neutral'}>{titleCase(task.priority)}</Pill>
               {task.slaState !== 'none' && (
                 <Pill tone={task.slaState === 'breached' ? 'danger'
                   : task.slaState === 'at_risk' ? 'warn'
                   : task.slaState === 'met' ? 'good' : 'info'}>
                   SLA {titleCase(task.slaState)}
                   {task.status !== 'completed' && mins != null &&
                     ` · ${mins < 0 ? `${Math.abs(mins)} min over` : `${mins} min left`}`}
                 </Pill>
               )}
             </div>
           }
           footer={
             <>
               <Button size="sm" onClick={() => setReassign(true)}
                       disabled={task.status === 'completed' || task.status === 'cancelled'}>
                 Reassign
               </Button>
               {vehicle && (
                 <Button size="sm" onClick={() => { app.navigate('live', { vehicle: vehicle.id }); onClose(); }}>
                   Track on map
                 </Button>
               )}
               {trip && (
                 <Button size="sm" onClick={() => { app.navigate('trips', { trip: trip.id }); onClose(); }}>
                   View trip
                 </Button>
               )}
               <div className="grow" />
               {allowed.includes('failed') && (
                 <Button size="sm" onClick={() => setFailing(true)}>Mark failed</Button>
               )}
               {allowed.includes('cancelled') && (
                 <Button size="sm" variant="danger" onClick={() => setCancelling(true)}>Cancel</Button>
               )}
               {allowed.filter((x) => !['failed', 'cancelled', 'unassigned'].includes(x))
                 .slice(0, 1).map((target) => (
                   <Button key={target} size="sm" variant="primary" onClick={() => {
                     if (target === 'completed') setPod(true);
                     else app.run(() => transitionTask(store, task, target),
                                  `${task.reference} moved to ${titleCase(target)}`);
                   }}>
                     {target === 'completed' ? 'Complete with POD' : `Move to ${titleCase(target)}`}
                   </Button>
                 ))}
             </>
           }>
      <div className="stack">
        <div className="grid-2">
          <Card title="Assignment">
            <dl className="kv">
              <dt>Driver</dt>
              <dd>{driver
                ? <button className="row" style={{ gap: 6 }}
                          onClick={() => { app.open('driver', driver.id); onClose(); }}>
                    <Avatar name={driver.fullName} color={driver.avatarColor} size={18} />
                    <span style={{ color: 'var(--pulse)' }}>{driver.fullName}</span>
                  </button>
                : <span className="dim">Unassigned</span>}</dd>
              <dt>Vehicle</dt>
              <dd>{vehicle
                ? <button style={{ color: 'var(--pulse)' }}
                          onClick={() => { app.open('vehicle', vehicle.id); onClose(); }}>
                    {vehicle.name} · {vehicle.plate}
                  </button>
                : <span className="dim">Unassigned</span>}</dd>
              <dt>Created</dt><dd>{dmy(task.createdAt)} {hm(task.createdAt)}</dd>
            </dl>
          </Card>

          <Card title="Customer">
            <dl className="kv">
              <dt>Site</dt><dd>{store.customer(task.customerId)?.name ?? task.address}</dd>
              <dt>Contact</dt><dd>{task.contactName ?? '—'}</dd>
              <dt>Phone</dt><dd className="mono">{task.contactPhone ?? '—'}</dd>
              <dt>Address</dt><dd>{task.address}</dd>
            </dl>
          </Card>
        </div>

        <div className="grid-2">
          <Card title="Timing">
            <dl className="kv">
              <dt>Scheduled</dt><dd className="num">{hm(task.scheduledFor)}</dd>
              <dt>Window</dt>
              <dd className="num">{hm(task.windowStart)} – {hm(task.windowEnd)}</dd>
              <dt>SLA deadline</dt><dd className="num">{hm(task.slaDueAt)}</dd>
              <dt>ETA</dt><dd className="num">{hm(task.eta)}</dd>
              {task.completedAt && (
                <><dt>Completed</dt><dd className="num">{hm(task.completedAt)}</dd></>
              )}
              <dt>Service time</dt><dd className="num">{task.serviceMinutes} min</dd>
            </dl>
            {task.slaDueAt && task.status !== 'completed' && (
              <div style={{ marginTop: 10 }}>
                <Progress
                  pct={Math.max(0, Math.min(100,
                    100 - ((task.slaDueAt - s.now) / ((task.slaMinutes ?? 120) * 60000)) * 100))}
                  tone={task.slaState === 'breached' ? 'danger'
                    : task.slaState === 'at_risk' ? 'warn' : 'good'} />
              </div>
            )}
          </Card>

          <Card title="Route">
            {route ? (
              <dl className="kv">
                <dt>Distance</dt><dd className="num">{(route.distanceM / 1000).toFixed(2)} km</dd>
                <dt>Duration</dt><dd className="num">{Math.round(route.durationS / 60)} min</dd>
                <dt>From</dt><dd className="truncate">{route.originName}</dd>
                <dt>To</dt><dd className="truncate">{route.destName}</dd>
                <dt>Stops</dt><dd className="num">{route.stops.length}</dd>
              </dl>
            ) : (
              <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
                No route yet. A route is built automatically when a vehicle is assigned.
              </p>
            )}
          </Card>
        </div>

        {task.instructions && (
          <Card title="Instructions">
            <p style={{ margin: 0, fontSize: 12.5 }}>{task.instructions}</p>
          </Card>
        )}

        {task.failureReason && (
          <div className="banner" data-tone="danger">
            <IconAlert size={15} />
            <span>
              <strong>Failed — {titleCase(task.failureReason)}.</strong>{' '}
              {task.failureNote}
            </span>
          </div>
        )}

        {task.pod && (
          <Card title="Proof of delivery">
            <dl className="kv">
              <dt>Recipient</dt><dd>{task.pod.recipient}</dd>
              <dt>Captured</dt><dd>{dmy(task.pod.at)} {hm(task.pod.at)}</dd>
              <dt>Location</dt>
              <dd className="mono">{task.pod.lat.toFixed(5)}, {task.pod.lon.toFixed(5)}</dd>
              {task.pod.notes && <><dt>Notes</dt><dd>{task.pod.notes}</dd></>}
            </dl>
          </Card>
        )}

        <Card title="Timeline">
          <Timeline entries={[...timeline].reverse()} />
        </Card>
      </div>

      {reassign && <ReassignModal task={task} onClose={() => setReassign(false)} />}

      {cancelling && (
        <CancelModal task={task} onClose={() => setCancelling(false)} onDone={onClose} />
      )}

      {failing && (
        <FailModal task={task} onClose={() => setFailing(false)} onDone={onClose} />
      )}

      {pod && (
        <PodModal task={task} onClose={() => setPod(false)} onDone={onClose} />
      )}
    </Modal>
  );
}

function ReassignModal({ task, onClose }: { task: Task; onClose: () => void }) {
  const app = useApp();
  const { store, state: s } = app;
  const [driverId, setDriverId] = useState(task.driverId ?? '');
  const [vehicleId, setVehicleId] = useState(task.vehicleId ?? '');
  const driver = store.driver(driverId);
  const vehicle = store.vehicle(vehicleId);
  const preview = useMemo(() => {
    try { return assignmentPreview(store, task, driver, vehicle); } catch { return null; }
  }, [store, task, driver, vehicle]);

  return (
    <Modal title={`Reassign ${task.reference}`} onClose={onClose}
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant={preview?.hasConflict ? 'danger' : 'primary'} onClick={() => {
               const ok = app.run(
                 () => assignTask(store, task.id, driverId || undefined, vehicleId || undefined),
                 'Assignment updated');
               if (ok) onClose();
             }}>
               {preview?.hasConflict ? 'Assign anyway' : 'Confirm'}
             </Button>
           </>}>
      <div className="stack">
        <Field label="Driver">
          <select className="select" value={driverId} onChange={(e) => {
            setDriverId(e.target.value);
            const v = s.vehicles.find((x) => x.driverId === e.target.value);
            if (v) setVehicleId(v.id);
          }}>
            <option value="">Unassigned</option>
            {s.drivers.map((d) => (
              <option key={d.id} value={d.id}>{d.fullName} — {titleCase(d.status)}</option>
            ))}
          </select>
        </Field>
        <Field label="Vehicle">
          <select className="select" value={vehicleId} onChange={(e) => setVehicleId(e.target.value)}>
            <option value="">Unassigned</option>
            {s.vehicles.filter((v) => v.lifecycle === 'active').map((v) => (
              <option key={v.id} value={v.id}>{v.name} · {v.plate}</option>
            ))}
          </select>
        </Field>
        {preview?.eta && (
          <div className="banner" data-tone="info">
            <span>
              Projected arrival {hm(preview.eta)}
              {preview.routeImpact && ` · ${preview.routeImpact.distanceKm} km, ${preview.routeImpact.durationMin} min`}
              {preview.sla && ` · SLA margin ${preview.sla.marginMin} min`}
            </span>
          </div>
        )}
        {preview?.conflicts.map((c, i) => (
          <div key={i} className="banner" data-tone="danger">
            <IconAlert size={15} /><span>{c.message}</span>
          </div>
        ))}
        {preview?.warnings.map((w, i) => (
          <div key={i} className="banner" data-tone="warn">
            <IconAlert size={15} /><span>{w}</span>
          </div>
        ))}
      </div>
    </Modal>
  );
}

function CancelModal({ task, onClose, onDone }: {
  task: Task; onClose: () => void; onDone: () => void;
}) {
  const app = useApp();
  const [reason, setReason] = useState('');
  return (
    <Modal title={`Cancel ${task.reference}?`} onClose={onClose}
           footer={<>
             <Button onClick={onClose}>Keep task</Button>
             <Button variant="danger" disabled={!reason.trim()} onClick={() => {
               const ok = app.run(() => cancelTask(app.store, task.id, reason),
                                  `${task.reference} cancelled`);
               if (ok) { onClose(); onDone(); }
             }}>Cancel task</Button>
           </>}>
      <div className="stack">
        <div className="banner" data-tone="warn">
          <IconAlert size={15} />
          <span>
            Cancelling removes the task from the driver's list and closes its route.
            This cannot be undone.
          </span>
        </div>
        <Field label="Reason (required)">
          <textarea className="textarea" value={reason} autoFocus
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Customer rescheduled to next week." />
        </Field>
      </div>
    </Modal>
  );
}

function FailModal({ task, onClose, onDone }: {
  task: Task; onClose: () => void; onDone: () => void;
}) {
  const app = useApp();
  const [reason, setReason] = useState(FAILURE_REASONS[0].code);
  const [note, setNote] = useState('');
  return (
    <Modal title={`Mark ${task.reference} failed`} onClose={onClose}
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant="danger" onClick={() => {
               const ok = app.run(() => failTask(app.store, task.id, reason, note || undefined),
                                  `${task.reference} marked failed`);
               if (ok) { onClose(); onDone(); }
             }}>Mark failed</Button>
           </>}>
      <div className="stack">
        <Field label="Reason" hint="A failed task raises an alert and appears in the dispatch exception centre.">
          <select className="select" value={reason} onChange={(e) => setReason(e.target.value)}>
            {FAILURE_REASONS.map((r) => (
              <option key={r.code} value={r.code}>{r.label}</option>
            ))}
          </select>
        </Field>
        <Field label="Note (optional)">
          <textarea className="textarea" value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}

function PodModal({ task, onClose, onDone }: {
  task: Task; onClose: () => void; onDone: () => void;
}) {
  const app = useApp();
  const [recipient, setRecipient] = useState(task.contactName ?? '');
  const [notes, setNotes] = useState('');
  const [signed, setSigned] = useState(false);
  return (
    <Modal title={`Complete ${task.reference}`} onClose={onClose}
           subtitle="Proof of delivery is stored with the task and stamped with time and position."
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant="primary" disabled={!recipient.trim()} onClick={() => {
               const ok = app.run(() => completeTaskWithPod(app.store, task.id, {
                 recipient, notes: notes || undefined,
                 signature: signed ? 'captured' : undefined,
               }), `${task.reference} completed`);
               if (ok) { onClose(); onDone(); }
             }}>
               <IconCheck size={14} /> Complete task
             </Button>
           </>}>
      <div className="stack">
        <Field label="Received by">
          <input className="input" value={recipient} autoFocus
                 onChange={(e) => setRecipient(e.target.value)} />
        </Field>
        <Field label="Notes">
          <textarea className="textarea" value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Left with reception on the ground floor." />
        </Field>
        <label className="row" style={{ gap: 8, fontSize: 12.5 }}>
          <input type="checkbox" checked={signed} onChange={(e) => setSigned(e.target.checked)} />
          Signature captured on the handheld
        </label>
      </div>
    </Modal>
  );
}
