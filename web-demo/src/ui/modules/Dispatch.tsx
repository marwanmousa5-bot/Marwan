// Dispatch: resources on the left, the board in the middle, the map on the right.
// Every move previews its impact before it is committed.

import { useMemo, useState } from 'react';
import { ActionError, assignTask, assignmentPreview } from '../../engine/actions';
import { dispatchExceptions, driverWorkload, fleetRows } from '../../engine/selectors';
import type { Task, TaskStatus } from '../../engine/types';
import { useApp, useEpoch } from '../app-context';
import {
  Avatar, Button, Card, Modal, Pill, Progress, hm, titleCase, type Tone,
} from '../components/kit';
import { IconAlert, IconDrag, IconTruck } from '../icons';
import { DEFAULT_LAYERS, FleetMap } from '../map/FleetMap';
import type { BaseData } from '../map/style';

const COLUMNS: { key: TaskStatus; label: string }[] = [
  { key: 'unassigned', label: 'Unassigned' },
  { key: 'assigned', label: 'Assigned' },
  { key: 'accepted', label: 'Accepted' },
  { key: 'en_route', label: 'En route' },
  { key: 'arrived', label: 'Arrived' },
  { key: 'in_progress', label: 'In progress' },
  { key: 'completed', label: 'Completed' },
];

export function Dispatch({ base }: { base: BaseData }) {
  const app = useApp();
  const epoch = useEpoch();
  const { store, state: s } = app;
  const [drag, setDrag] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [pending, setPending] = useState<{ taskId: string; driverId?: string; vehicleId?: string } | null>(null);
  const [showMap, setShowMap] = useState(true);

  const rows = useMemo(() => fleetRows(store), [store, s.ticks]);
  const workload = useMemo(() => driverWorkload(store), [store, epoch]);
  const exceptions = useMemo(() => dispatchExceptions(store), [store, s.tasks, s.alerts]);

  const dayStart = new Date(s.now).setUTCHours(0, 0, 0, 0);
  const board = useMemo(() => {
    const map = new Map<TaskStatus, Task[]>();
    COLUMNS.forEach((c) => map.set(c.key, []));
    const exceptionsCol: Task[] = [];
    s.tasks
      .filter((t) => t.createdAt >= dayStart - 86400000 && t.status !== 'cancelled')
      .sort((a, b) => (a.scheduledFor ?? 0) - (b.scheduledFor ?? 0))
      .forEach((t) => {
        if (t.status === 'delayed' || t.status === 'failed') exceptionsCol.push(t);
        else map.get(t.status)?.push(t);
      });
    return { map, exceptionsCol };
  }, [s.tasks, dayStart]);

  const driversAvailable = workload.filter((w) => w.available).length;
  const vehiclesAvailable = rows.filter(
    (r) => r.vehicle.lifecycle === 'active' && r.status !== 'maintenance').length;

  const onDropDriver = (driverId: string) => {
    if (!drag) return;
    const vehicle = s.vehicles.find((v) => v.driverId === driverId);
    setPending({ taskId: drag, driverId, vehicleId: vehicle?.id });
    setDrag(null);
    setOver(null);
  };

  return (
    <div style={{ display: 'flex', height: '100%', minHeight: 0 }}>
      <aside style={{
        width: 268, flex: '0 0 auto', borderRight: '1px solid var(--line)',
        background: 'var(--surface)', display: 'flex', flexDirection: 'column',
      }}>
        <div style={{ padding: '11px 12px', borderBottom: '1px solid var(--line-soft)' }}>
          <div className="eyebrow">Resources</div>
          <div className="row" style={{ gap: 10, marginTop: 6, fontSize: 12 }}>
            <span><strong className="num">{driversAvailable}</strong>
              <span className="dim">/{workload.length} drivers</span></span>
            <span><strong className="num">{vehiclesAvailable}</strong>
              <span className="dim">/{s.vehicles.length} vehicles</span></span>
          </div>
        </div>
        <div style={{ overflowY: 'auto', flex: 1 }}>
          {workload.map((w) => (
            <div key={w.driver.id}
                 onDragOver={(e) => { e.preventDefault(); setOver(w.driver.id); }}
                 onDragLeave={() => setOver((o) => (o === w.driver.id ? null : o))}
                 onDrop={() => onDropDriver(w.driver.id)}
                 style={{
                   padding: '10px 12px', borderBottom: '1px solid var(--line-soft)',
                   background: over === w.driver.id ? 'var(--pulse-wash)' : undefined,
                   outline: over === w.driver.id ? '2px solid var(--pulse)' : undefined,
                   outlineOffset: -2,
                 }}>
              <div className="row" style={{ gap: 8 }}>
                <Avatar name={w.driver.fullName} color={w.driver.avatarColor} size={24} />
                <button className="grow truncate" style={{ textAlign: 'left', fontWeight: 550 }}
                        onClick={() => app.open('driver', w.driver.id)}>
                  {w.driver.fullName}
                </button>
                <Pill tone={w.available ? 'good' : 'neutral'}>{titleCase(w.driver.status)}</Pill>
              </div>
              <div className="row" style={{ gap: 8, marginTop: 5, fontSize: 11 }}>
                <span className="dim truncate grow">
                  {w.vehicle ? `${w.vehicle.name} · ${w.vehicle.plate}` : 'No vehicle'}
                </span>
                <span className="mono">{w.activeTasks} task{w.activeTasks === 1 ? '' : 's'}</span>
                {w.lateTasks > 0 && <Pill tone="danger">{w.lateTasks} late</Pill>}
              </div>
              <div style={{ marginTop: 6 }}>
                <Progress pct={w.loadPct}
                          tone={w.loadPct > 85 ? 'danger' : w.loadPct > 60 ? 'warn' : undefined} />
                <div className="row" style={{ fontSize: 10, marginTop: 3 }}>
                  <span className="dim grow">{w.loadPct}% workload</span>
                  <span className="dim">{w.driver.dutyHoursToday.toFixed(1)} h duty</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </aside>

      <div className="scroll" style={{ flex: 1, minWidth: 0 }}>
        <div style={{ padding: '16px 18px 30px' }}>
          <div className="page-head">
            <div className="grow">
              <h2 className="page-title">Dispatch</h2>
              <p className="page-sub">
                Drag a task onto a driver to move it. FleetBeat shows the routing and
                workload impact before anything changes.
              </p>
            </div>
            <Button onClick={() => setShowMap((v) => !v)}>
              {showMap ? 'Hide map' : 'Show map'}
            </Button>
            <Button variant="primary" onClick={() => app.navigate('tasks', { compose: '1' })}>
              New task
            </Button>
          </div>

          {exceptions.length > 0 && (
            <Card title={`Exception centre — ${exceptions.length} item${exceptions.length === 1 ? '' : 's'}`}
                  pad={false}
                  actions={<span className="dim" style={{ fontSize: 11.5 }}>Highest severity first</span>}>
              <div style={{ maxHeight: 190, overflowY: 'auto' }}>
                {exceptions.slice(0, 12).map((e, i) => (
                  <button key={i} className="row" style={{
                    gap: 9, width: '100%', textAlign: 'left', padding: '8px 14px',
                    borderBottom: '1px solid var(--line-soft)',
                  }} onClick={() => {
                    if (e.entityType === 'task') app.open('task', e.entityId);
                    else if (e.entityType === 'alert') app.open('alert', e.entityId);
                    else if (e.entityType === 'vehicle') app.navigate('live', { vehicle: e.entityId });
                  }}>
                    <Pill tone={e.severity as Tone}>{e.severity}</Pill>
                    <span className="grow">
                      <span style={{ fontWeight: 550, fontSize: 12.5 }}>{e.title}</span>
                      <div className="dim" style={{ fontSize: 11 }}>{e.detail}</div>
                    </span>
                    <span className="dim" style={{ fontSize: 11 }}>{titleCase(e.type)}</span>
                  </button>
                ))}
              </div>
            </Card>
          )}

          <div style={{ marginTop: 14 }}>
            <div className="board">
              {COLUMNS.map((col) => {
                const tasks = board.map.get(col.key) ?? [];
                return (
                  <div key={col.key} className="column">
                    <div className="column-head">
                      <span className="title">{col.label}</span>
                      <span className="count">{tasks.length}</span>
                    </div>
                    <div className="column-body">
                      {tasks.length === 0 && (
                        <div className="dim" style={{ fontSize: 11.5, padding: '10px 4px' }}>
                          {col.key === 'unassigned'
                            ? 'Nothing waiting — every task has an owner.'
                            : 'Empty'}
                        </div>
                      )}
                      {tasks.map((t) => (
                        <TaskCard key={t.id} task={t}
                                  draggable={t.status !== 'completed'}
                                  dragging={drag === t.id}
                                  onDragStart={() => setDrag(t.id)}
                                  onDragEnd={() => { setDrag(null); setOver(null); }}
                                  onOpen={() => app.open('task', t.id)} />
                      ))}
                    </div>
                  </div>
                );
              })}

              {board.exceptionsCol.length > 0 && (
                <div className="column" style={{ borderColor: 'var(--danger)' }}>
                  <div className="column-head">
                    <IconAlert size={13} />
                    <span className="title">Exception</span>
                    <span className="count">{board.exceptionsCol.length}</span>
                  </div>
                  <div className="column-body">
                    {board.exceptionsCol.map((t) => (
                      <TaskCard key={t.id} task={t} draggable dragging={drag === t.id}
                                onDragStart={() => setDrag(t.id)}
                                onDragEnd={() => setDrag(null)}
                                onOpen={() => app.open('task', t.id)} />
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {showMap && (
        <aside style={{
          width: 380, flex: '0 0 auto', borderLeft: '1px solid var(--line)',
          position: 'relative',
        }}>
          <div className="map-area" style={{ position: 'absolute', inset: 0 }}>
            <FleetMap
              base={base} theme={app.theme} rows={rows} routes={s.routes}
              geofences={s.geofences} places={s.places}
              tasks={s.tasks.filter((t) => !['completed', 'cancelled'].includes(t.status))}
              incidents={s.incidents} disruptions={s.disruptions} weather={s.weather}
              layers={{ ...DEFAULT_LAYERS, places: false, plannedRoutes: false }}
              onSelectVehicle={(id) => app.navigate('live', { vehicle: id })}
            />
            <div className="map-attrib">© OpenStreetMap contributors</div>
          </div>
        </aside>
      )}

      {pending && (
        <MovePreview move={pending} onClose={() => setPending(null)} />
      )}
    </div>
  );
}

function TaskCard({ task, draggable, dragging, onDragStart, onDragEnd, onOpen }: {
  task: Task; draggable: boolean; dragging: boolean;
  onDragStart: () => void; onDragEnd: () => void; onOpen: () => void;
}) {
  const app = useApp();
  const driver = app.store.driver(task.driverId);
  const vehicle = app.store.vehicle(task.vehicleId);
  return (
    <div className="tcard" data-priority={task.priority} data-dragging={dragging}
         draggable={draggable} onDragStart={onDragStart} onDragEnd={onDragEnd}
         onClick={onOpen} role="button" tabIndex={0}
         onKeyDown={(e) => { if (e.key === 'Enter') onOpen(); }}>
      <div className="row" style={{ gap: 6 }}>
        <span className="ref">{task.reference}</span>
        <div className="grow" />
        {draggable && <IconDrag size={12} />}
      </div>
      <div className="title">{task.title}</div>
      <div className="meta">
        <span className="mono">{hm(task.scheduledFor)}</span>
        {task.slaState !== 'none' && task.slaState !== 'on_track' && (
          <Pill tone={task.slaState === 'breached' ? 'danger' : 'warn'}>
            {titleCase(task.slaState)}
          </Pill>
        )}
        {task.priority !== 'normal' && (
          <Pill tone={task.priority === 'urgent' ? 'danger'
            : task.priority === 'high' ? 'warn' : 'neutral'}>{task.priority}</Pill>
        )}
      </div>
      <div className="meta">
        {driver ? (
          <>
            <Avatar name={driver.fullName} color={driver.avatarColor} size={17} />
            <span className="truncate">{driver.fullName}</span>
          </>
        ) : <span className="dim">Unassigned</span>}
        {vehicle && <><IconTruck size={12} /><span className="mono">{vehicle.name}</span></>}
      </div>
    </div>
  );
}

function MovePreview({ move, onClose }: {
  move: { taskId: string; driverId?: string; vehicleId?: string }; onClose: () => void;
}) {
  const app = useApp();
  const { store } = app;
  const task = store.task(move.taskId)!;
  const driver = store.driver(move.driverId);
  const vehicle = store.vehicle(move.vehicleId);
  const currentDriver = store.driver(task.driverId);
  const currentVehicle = store.vehicle(task.vehicleId);

  const preview = useMemo(() => {
    try { return assignmentPreview(store, task, driver, vehicle); }
    catch { return null; }
  }, [store, task, driver, vehicle]);

  const delta = useMemo(() => {
    if (!currentVehicle?.lat || !vehicle?.lat) return null;
    const before = store.graph.route([[currentVehicle.lon!, currentVehicle.lat], [task.lon, task.lat]]);
    const after = store.graph.route([[vehicle.lon!, vehicle.lat], [task.lon, task.lat]]);
    if (!before.ok || !after.ok) return null;
    return {
      km: (after.distanceM - before.distanceM) / 1000,
      min: (after.durationS - before.durationS) / 60,
    };
  }, [store, currentVehicle, vehicle, task]);

  const confirm = () => {
    try {
      assignTask(store, task.id, move.driverId, move.vehicleId);
      app.toast('success', `${task.reference} moved to ${driver?.fullName ?? 'the queue'}`);
      onClose();
    } catch (e) {
      app.toast('error', e instanceof ActionError ? e.message : 'Could not move the task.');
    }
  };

  return (
    <Modal title={`Move ${task.reference}`} onClose={onClose}
           subtitle={task.title}
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant={preview?.hasConflict ? 'danger' : 'primary'} onClick={confirm}>
               {preview?.hasConflict ? 'Assign anyway' : 'Confirm move'}
             </Button>
           </>}>
      <div className="stack">
        <div className="grid-2">
          <Card title="From">
            <dl className="kv">
              <dt>Driver</dt><dd>{currentDriver?.fullName ?? '—'}</dd>
              <dt>Vehicle</dt><dd>{currentVehicle?.name ?? '—'}</dd>
            </dl>
          </Card>
          <Card title="To">
            <dl className="kv">
              <dt>Driver</dt><dd>{driver?.fullName ?? '—'}</dd>
              <dt>Vehicle</dt><dd>{vehicle?.name ?? 'None assigned'}</dd>
            </dl>
          </Card>
        </div>

        {delta && (
          <div className="banner" data-tone={delta.min > 0 ? 'warn' : 'info'}>
            <span>
              <strong>Route impact.</strong>{' '}
              {delta.km >= 0 ? '+' : ''}{delta.km.toFixed(1)} km,{' '}
              {delta.min >= 0 ? '+' : ''}{Math.round(delta.min)} min to reach the customer.
            </span>
          </div>
        )}

        {preview?.workload && (
          <Card title="New driver's workload">
            <dl className="kv">
              <dt>Status</dt><dd>{titleCase(preview.workload.status)}</dd>
              <dt>Active tasks</dt><dd className="num">{preview.workload.activeTasks}</dd>
              <dt>Late tasks</dt><dd className="num">{preview.workload.lateTasks}</dd>
              <dt>Duty today</dt><dd className="num">{preview.workload.dutyHoursToday} h</dd>
              <dt>Load</dt>
              <dd><Progress pct={preview.workload.loadPct}
                            tone={preview.workload.loadPct > 85 ? 'danger' : undefined} /></dd>
            </dl>
          </Card>
        )}

        {preview?.eta && (
          <div className="banner" data-tone="info">
            <span>
              <strong>Projected arrival {hm(preview.eta)}.</strong>{' '}
              {preview.routeImpact && (
                <>{preview.routeImpact.distanceKm} km via {preview.routeImpact.via.join(', ')}.</>
              )}
              {preview.sla && (
                <> SLA margin {preview.sla.marginMin} min.</>
              )}
            </span>
          </div>
        )}

        {preview?.conflicts.map((c, i) => (
          <div key={i} className="banner" data-tone="danger">
            <IconAlert size={15} />
            <span><strong>Potential conflict.</strong> {c.message}</span>
          </div>
        ))}
        {preview?.warnings.map((w, i) => (
          <div key={i} className="banner" data-tone="warn">
            <IconAlert size={15} /><span>{w}</span>
          </div>
        ))}
        {!preview?.hasConflict && !preview?.warnings.length && (
          <div className="banner" data-tone="info">
            <span>No conflicts found. The move is clear.</span>
          </div>
        )}
      </div>
    </Modal>
  );
}
