// Incident management — reporting, investigation and the link into repair work.

import { useEffect, useState } from 'react';
import {
  createIncident, INCIDENT_FLOW, setIncidentStatus, workOrderFromIncident,
} from '../../engine/actions';
import type { Incident, Severity } from '../../engine/types';
import { useApp } from '../app-context';
import {
  Button, Card, Empty, Field, Kpi, Modal, Money, Pill, Timeline, dmy, hm, titleCase,
  type Tone,
} from '../components/kit';
import { IconAlert, IconPlus, IconWrench } from '../icons';

const TYPES = ['collision', 'breakdown', 'theft', 'vandalism', 'cargo_damage',
               'near_miss', 'injury', 'other'];

export function Incidents() {
  const app = useApp();
  const { store, state: s } = app;
  const [openId, setOpenId] = useState<string | undefined>(app.params.incident);
  const [compose, setCompose] = useState(app.params.compose === '1');
  const [statusFilter, setStatusFilter] = useState('');
  const [severityFilter, setSeverityFilter] = useState('');
  const [query, setQuery] = useState('');

  useEffect(() => { if (app.params.incident) setOpenId(app.params.incident); },
            [app.params.incident]);
  useEffect(() => { if (app.params.compose === '1') setCompose(true); }, [app.params.compose]);

  const list = s.incidents.filter((i) => {
    if (statusFilter && i.status !== statusFilter) return false;
    if (severityFilter && i.severity !== severityFilter) return false;
    const q = query.trim().toLowerCase();
    if (q && ![i.reference, i.title, i.description].some((f) => f?.toLowerCase().includes(q))) {
      return false;
    }
    return true;
  });

  const open = s.incidents.filter((i) => i.status !== 'resolved' && i.status !== 'closed');
  const cost = s.incidents.reduce((a, i) => a + (i.estimatedCost ?? 0), 0);
  const openIncident = openId ? store.incident(openId) : undefined;

  return (
    <div className="scroll">
      <div className="page">
        <div className="page-head">
          <div className="grow">
            <h2 className="page-title">Incidents</h2>
            <p className="page-sub">
              What went wrong, what it cost, and what was done about it. Every incident
              keeps its links to the vehicle, the driver and the repair.
            </p>
          </div>
          <Button variant="primary" onClick={() => setCompose(true)}>
            <IconPlus size={14} /> Report incident
          </Button>
        </div>

        <div className="kpis" style={{ marginBottom: 14 }}>
          <Kpi label="Total" value={s.incidents.length} />
          <Kpi label="Open" value={open.length} tone={open.length ? 'warn' : 'good'} />
          <Kpi label="Critical"
               value={s.incidents.filter((i) => i.severity === 'critical').length}
               tone={s.incidents.some((i) => i.severity === 'critical') ? 'danger' : undefined}
               active={severityFilter === 'critical'}
               onClick={() => setSeverityFilter(severityFilter === 'critical' ? '' : 'critical')} />
          <Kpi label="Action required"
               value={s.incidents.filter((i) => i.status === 'action_required').length}
               active={statusFilter === 'action_required'}
               onClick={() => setStatusFilter(statusFilter === 'action_required' ? '' : 'action_required')} />
          <Kpi label="Estimated cost" value={<Money value={cost} />} />
        </div>

        <div className="row wrap" style={{ gap: 8, marginBottom: 12 }}>
          <input className="input" placeholder="Search reference or description"
                 value={query} onChange={(e) => setQuery(e.target.value)}
                 style={{ maxWidth: 280 }} />
          <select className="select" style={{ width: 180 }} value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            {['reported', 'under_investigation', 'action_required', 'resolved', 'closed']
              .map((x) => <option key={x} value={x}>{titleCase(x)}</option>)}
          </select>
          <select className="select" style={{ width: 150 }} value={severityFilter}
                  onChange={(e) => setSeverityFilter(e.target.value)}>
            <option value="">All severities</option>
            {['low', 'medium', 'high', 'critical'].map((x) =>
              <option key={x} value={x}>{titleCase(x)}</option>)}
          </select>
        </div>

        <Card pad={false}>
          {list.length === 0 ? (
            <Empty title="No incidents recorded"
                   body="A clean record — or widen the filters to see closed items."
                   action={<Button onClick={() => setCompose(true)}>Report an incident</Button>} />
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>Reference</th><th>Incident</th><th>Type</th><th>Severity</th>
                           <th>Status</th><th>Vehicle</th><th>Driver</th><th>When</th>
                           <th className="num">Cost</th></tr></thead>
                <tbody>
                  {list.map((i) => (
                    <tr key={i.id} data-clickable="true" onClick={() => setOpenId(i.id)}>
                      <td className="mono">{i.reference}</td>
                      <td>
                        <div style={{ fontWeight: 550 }}>{i.title}</div>
                        {i.address && (
                          <div className="dim truncate" style={{ fontSize: 11, maxWidth: 240 }}>
                            {i.address}
                          </div>
                        )}
                      </td>
                      <td>{titleCase(i.kind)}</td>
                      <td><Pill tone={i.severity as Tone}>{i.severity}</Pill></td>
                      <td><Pill tone={i.status === 'closed' || i.status === 'resolved' ? 'good'
                        : i.status === 'action_required' ? 'warn' : 'info'}>
                        {titleCase(i.status)}</Pill></td>
                      <td className="mono">{store.vehicle(i.vehicleId)?.name ?? '—'}</td>
                      <td>{store.driver(i.driverId)?.fullName ?? '—'}</td>
                      <td className="num">{dmy(i.occurredAt)}</td>
                      <td className="num">{i.estimatedCost ? `€${i.estimatedCost}` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      {openIncident && (
        <IncidentDetail incident={openIncident} onClose={() => setOpenId(undefined)} />
      )}
      {compose && (
        <IncidentComposer presetVehicle={app.params.vehicle}
                          onClose={() => setCompose(false)} onCreated={setOpenId} />
      )}
    </div>
  );
}

function IncidentDetail({ incident, onClose }: { incident: Incident; onClose: () => void }) {
  const app = useApp();
  const { store } = app;
  const vehicle = store.vehicle(incident.vehicleId);
  const driver = store.driver(incident.driverId);
  const wo = store.workOrder(incident.workOrderId);
  const timeline = store.timelineFor('incident', incident.id);
  const next = INCIDENT_FLOW[incident.status];
  const [note, setNote] = useState('');
  const [restoring, setRestoring] = useState(false);

  return (
    <Modal title={`${incident.reference} — ${incident.title}`} size="lg" onClose={onClose}
           subtitle={
             <div className="row wrap" style={{ gap: 7 }}>
               <Pill tone={incident.severity as Tone}>{incident.severity}</Pill>
               <Pill tone={incident.status === 'closed' || incident.status === 'resolved'
                 ? 'good' : 'info'}>{titleCase(incident.status)}</Pill>
               <span className="dim">{titleCase(incident.kind)}</span>
               <span className="dim">·</span>
               <span className="dim">{dmy(incident.occurredAt)} {hm(incident.occurredAt)}</span>
             </div>
           }
           footer={
             <>
               {vehicle && !wo && (
                 <Button size="sm" onClick={() => {
                   const created = app.run(() => workOrderFromIncident(store, incident.id),
                                           'Work order raised from this incident');
                   if (created) { app.open('work_order', created.id); onClose(); }
                 }}><IconWrench size={13} /> Raise work order</Button>
               )}
               {wo && (
                 <Button size="sm" onClick={() => { app.open('work_order', wo.id); onClose(); }}>
                   Open {wo.reference}
                 </Button>
               )}
               {vehicle && vehicle.lifecycle === 'suspended' && (
                 <Button size="sm" onClick={() => setRestoring(true)}>
                   Return vehicle to service
                 </Button>
               )}
               <div className="grow" />
               {next.map((target) => (
                 <Button key={target} size="sm"
                         variant={target === 'closed' ? 'primary' : undefined}
                         onClick={() => {
                           app.run(() => setIncidentStatus(store, incident.id, target,
                                                           { note: note || undefined }),
                                   `${incident.reference} → ${titleCase(target)}`);
                         }}>
                   {titleCase(target)}
                 </Button>
               ))}
             </>
           }>
      <div className="stack">
        <div className="grid-2">
          <Card title="What happened">
            <p style={{ marginTop: 0, fontSize: 12.5 }}>{incident.description}</p>
            <dl className="kv">
              <dt>Occurred</dt>
              <dd>{dmy(incident.occurredAt)} {hm(incident.occurredAt)}</dd>
              <dt>Location</dt><dd>{incident.address ?? 'Not recorded'}</dd>
              {incident.lat != null && (
                <>
                  <dt>Coordinates</dt>
                  <dd className="mono">
                    {incident.lat.toFixed(5)}, {incident.lon!.toFixed(5)}
                  </dd>
                </>
              )}
              <dt>Estimated cost</dt>
              <dd>{incident.estimatedCost ? <Money value={incident.estimatedCost} /> : '—'}</dd>
            </dl>
          </Card>
          <Card title="Linked records">
            <dl className="kv">
              <dt>Vehicle</dt>
              <dd>{vehicle
                ? <button style={{ color: 'var(--pulse)' }}
                          onClick={() => { app.open('vehicle', vehicle.id); onClose(); }}>
                    {vehicle.name} · {vehicle.plate}
                  </button>
                : '—'}</dd>
              <dt>Vehicle state</dt>
              <dd>{vehicle
                ? <Pill tone={vehicle.lifecycle === 'suspended' ? 'danger' : 'good'}>
                    {titleCase(vehicle.lifecycle)}
                  </Pill>
                : '—'}</dd>
              <dt>Driver</dt>
              <dd>{driver
                ? <button style={{ color: 'var(--pulse)' }}
                          onClick={() => { app.open('driver', driver.id); onClose(); }}>
                    {driver.fullName}
                  </button>
                : '—'}</dd>
              <dt>Work order</dt>
              <dd>{wo
                ? <button className="mono" style={{ color: 'var(--pulse)' }}
                          onClick={() => { app.open('work_order', wo.id); onClose(); }}>
                    {wo.reference} — {titleCase(wo.status)}
                  </button>
                : <span className="dim">None raised</span>}</dd>
              <dt>Reported by</dt>
              <dd>{store.user(incident.reportedBy)?.fullName ?? 'System'}</dd>
            </dl>
          </Card>
        </div>

        {incident.witnesses.length > 0 && (
          <Card title="Witnesses">
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5 }}>
              {incident.witnesses.map((w, i) => (
                <li key={i}>{w.name} — {w.contact}</li>
              ))}
            </ul>
          </Card>
        )}

        {incident.resolutionNote && (
          <div className="banner" data-tone="info">
            <span><strong>Resolution.</strong> {incident.resolutionNote}</span>
          </div>
        )}

        {next.length > 0 && (
          <Field label="Note for the next status change (optional)">
            <textarea className="textarea" value={note} onChange={(e) => setNote(e.target.value)}
                      placeholder="Panel repaired; driver debriefed on reversing procedure." />
          </Field>
        )}

        <Card title="Timeline"><Timeline entries={timeline} /></Card>
      </div>

      {restoring && vehicle && (
        <Modal title={`Return ${vehicle.name} to service?`} onClose={() => setRestoring(false)}
               footer={<>
                 <Button onClick={() => setRestoring(false)}>Cancel</Button>
                 <Button variant="primary" onClick={() => {
                   app.run(() => setIncidentStatus(store, incident.id,
                     incident.status === 'closed' ? 'closed' : incident.status,
                     { restoreVehicle: true }), `${vehicle.name} returned to service`);
                   setRestoring(false);
                 }}>Return to service</Button>
               </>}>
          <p style={{ margin: 0, fontSize: 12.5 }}>
            {vehicle.name} is currently suspended because of this incident. Returning it to
            service makes it available for dispatch again and lets the simulator drive it.
          </p>
        </Modal>
      )}
    </Modal>
  );
}

function IncidentComposer({ onClose, onCreated, presetVehicle }: {
  onClose: () => void; onCreated: (id: string) => void; presetVehicle?: string;
}) {
  const app = useApp();
  const { store, state: s } = app;
  const [kind, setKind] = useState('collision');
  const [severity, setSeverity] = useState<Severity>('medium');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [vehicleId, setVehicleId] = useState(presetVehicle ?? s.vehicles[0]?.id ?? '');
  const [cost, setCost] = useState(0);
  const [offRoad, setOffRoad] = useState(false);

  const vehicle = store.vehicle(vehicleId);
  const driver = store.driver(vehicle?.driverId);
  const affected = s.tasks.filter(
    (t) => t.vehicleId === vehicleId &&
           ['assigned', 'accepted', 'en_route', 'arrived', 'in_progress'].includes(t.status));

  return (
    <Modal title="Report an incident" size="lg" onClose={onClose}
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant="primary" disabled={!title.trim()} onClick={() => {
               const res = app.run(() => createIncident(store, {
                 title, kind, severity, description: description || undefined,
                 vehicleId: vehicleId || undefined, driverId: driver?.id,
                 lat: vehicle?.lat, lon: vehicle?.lon, address: vehicle?.street,
                 estimatedCost: cost || undefined, takeVehicleOffRoad: offRoad,
               }), 'Incident reported');
               if (res) {
                 if (res.affectedTasks.length) {
                   app.toast('info',
                     `${res.affectedTasks.length} task(s) marked delayed`,
                     'Reassign them from Dispatch.');
                 }
                 onCreated(res.incident.id);
                 onClose();
               }
             }}>Report incident</Button>
           </>}>
      <div className="stack">
        <div className="grid-2">
          <Field label="Type">
            <select className="select" value={kind} onChange={(e) => setKind(e.target.value)}>
              {TYPES.map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}
            </select>
          </Field>
          <Field label="Severity">
            <select className="select" value={severity}
                    onChange={(e) => setSeverity(e.target.value as Severity)}>
              {['low', 'medium', 'high', 'critical'].map((x) =>
                <option key={x} value={x}>{titleCase(x)}</option>)}
            </select>
          </Field>
        </div>
        <Field label="Title">
          <input className="input" value={title} autoFocus
                 onChange={(e) => setTitle(e.target.value)}
                 placeholder="Low-speed contact with a bollard while reversing" />
        </Field>
        <Field label="Description">
          <textarea className="textarea" value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="What happened, who was involved, and what condition the vehicle is in." />
        </Field>
        <div className="grid-2">
          <Field label="Vehicle">
            <select className="select" value={vehicleId}
                    onChange={(e) => setVehicleId(e.target.value)}>
              <option value="">No vehicle involved</option>
              {s.vehicles.map((v) => (
                <option key={v.id} value={v.id}>{v.name} · {v.plate}</option>
              ))}
            </select>
          </Field>
          <Field label="Estimated cost (€)">
            <input className="input" type="number" value={cost}
                   onChange={(e) => setCost(Number(e.target.value))} />
          </Field>
        </div>

        {vehicle && (
          <Card title="Context captured automatically">
            <dl className="kv">
              <dt>Driver</dt><dd>{driver?.fullName ?? 'None assigned'}</dd>
              <dt>Position</dt>
              <dd>{vehicle.street ?? 'Off the named network'}
                {vehicle.lat != null && (
                  <span className="mono dim">
                    {' '}({vehicle.lat.toFixed(5)}, {vehicle.lon!.toFixed(5)})
                  </span>
                )}
              </dd>
              <dt>Odometer</dt>
              <dd className="num">{Math.round(vehicle.odometerKm).toLocaleString()} km</dd>
              <dt>Active tasks</dt><dd className="num">{affected.length}</dd>
            </dl>
          </Card>
        )}

        {vehicle && (
          <label className="row" style={{ gap: 8, fontSize: 12.5 }}>
            <input type="checkbox" checked={offRoad}
                   onChange={(e) => setOffRoad(e.target.checked)} />
            Take {vehicle.name} off the road immediately
          </label>
        )}

        {offRoad && affected.length > 0 && (
          <div className="banner" data-tone="warn">
            <IconAlert size={15} />
            <span>
              <strong>{affected.length} active task{affected.length === 1 ? '' : 's'}</strong>{' '}
              ({affected.map((t) => t.reference).join(', ')}) will be marked delayed and
              will need reassigning from Dispatch.
            </span>
          </div>
        )}

        {(severity === 'high' || severity === 'critical') && (
          <div className="banner" data-tone="danger">
            <IconAlert size={15} />
            <span>
              A {severity} incident also raises an alert so dispatch sees it immediately.
            </span>
          </div>
        )}
      </div>
    </Modal>
  );
}
