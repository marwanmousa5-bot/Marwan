// Geofences & Places — drawn on the real map, evaluated on every GPS sample.

import { useMemo, useState } from 'react';
import { createGeofence, createPlace, deleteGeofence } from '../../engine/actions';
import { circlePolygon, polygonAreaKm2 } from '../../engine/geo';
import { fleetRows } from '../../engine/selectors';
import { containsPoint } from '../../engine/sim';
import type { Geofence, Place } from '../../engine/types';
import { useApp } from '../app-context';
import {
  Button, Card, Confirm, Empty, Field, Kpi, Modal, Pill, Tabs, titleCase,
} from '../components/kit';
import { IconAlert, IconPlus, IconZone } from '../icons';
import { DEFAULT_LAYERS, FleetMap } from '../map/FleetMap';
import type { BaseData } from '../map/style';

const DAY = 86400000;

export function Geofences({ base }: { base: BaseData }) {
  const app = useApp();
  const { store, state: s } = app;
  const [tab, setTab] = useState('geofences');
  const [drawing, setDrawing] = useState(false);
  const [draft, setDraft] = useState<{ lat: number; lon: number } | null>(null);
  const [deleting, setDeleting] = useState<Geofence | null>(null);
  const [addingPlace, setAddingPlace] = useState(false);
  const [selected, setSelected] = useState<string | undefined>(app.params.geofence);
  const [placeDraft, setPlaceDraft] = useState<{ lat: number; lon: number } | null>(null);

  const rows = useMemo(() => fleetRows(store), [store, s.ticks]);

  const stats = (g: Geofence) => {
    const since = s.now - 7 * DAY;
    const events = s.alerts.filter((a) => a.geofenceId === g.id && a.triggeredAt >= since).length;
    const inside = s.vehicles.filter(
      (v) => v.lat != null && containsPoint(g, v.lon!, v.lat)).length;
    return { events, inside };
  };

  return (
    <div className="scroll">
      <div className="page">
        <div className="page-head">
          <div className="grow">
            <h2 className="page-title">Geofences & Places</h2>
            <p className="page-sub">
              Zones are evaluated against every GPS sample, and only the edges — entering
              and leaving — raise an alert.
            </p>
          </div>
          {tab === 'geofences' ? (
            <Button variant="primary" onClick={() => { setDrawing(true); setDraft(null); }}>
              <IconPlus size={14} /> New geofence
            </Button>
          ) : (
            <Button variant="primary" onClick={() => { setAddingPlace(true); setPlaceDraft(null); }}>
              <IconPlus size={14} /> New place
            </Button>
          )}
        </div>

        <div className="kpis" style={{ marginBottom: 14 }}>
          <Kpi label="Geofences" value={s.geofences.length} />
          <Kpi label="Restricted zones"
               value={s.geofences.filter((g) => g.restricted).length}
               tone={s.geofences.some((g) => g.restricted) ? 'warn' : undefined} />
          <Kpi label="Places" value={s.places.filter((p) => p.active).length} />
          <Kpi label="Depots" value={s.places.filter((p) => p.category === 'depot').length} />
          <Kpi label="Zone events (7d)"
               value={s.alerts.filter((a) => a.geofenceId && a.triggeredAt >= s.now - 7 * DAY).length} />
        </div>

        <Tabs tabs={[
          { key: 'geofences', label: 'Geofences', count: s.geofences.length },
          { key: 'places', label: 'Places', count: s.places.filter((p) => p.active).length },
          { key: 'map', label: 'Map' },
        ]} active={tab} onChange={setTab} />

        <div style={{ paddingTop: 14 }}>
          {tab === 'geofences' && (
            <Card pad={false}>
              {s.geofences.length === 0 ? (
                <Empty title="No geofences yet"
                       body="Draw a zone to be told when vehicles arrive at a depot, enter the
                             city centre, or cross into an area they should not."
                       action={<Button variant="primary" onClick={() => setDrawing(true)}>
                                 Create geofence
                               </Button>} />
              ) : (
                <div className="table-wrap">
                  <table className="data">
                    <thead><tr><th>Zone</th><th>Shape</th><th>Trigger</th><th>Scope</th>
                               <th className="num">Area</th><th className="num">Inside now</th>
                               <th className="num">Events (7d)</th><th>Active</th><th></th></tr></thead>
                    <tbody>
                      {s.geofences.map((g) => {
                        const st = stats(g);
                        return (
                          <tr key={g.id} data-selected={selected === g.id}>
                            <td>
                              <span className="row" style={{ gap: 7 }}>
                                <i style={{
                                  width: 10, height: 10, borderRadius: 3,
                                  background: g.restricted ? 'var(--danger)' : g.colour,
                                }} />
                                <span>
                                  <div style={{ fontWeight: 550 }}>{g.name}</div>
                                  {g.description && (
                                    <div className="dim" style={{ fontSize: 11 }}>{g.description}</div>
                                  )}
                                </span>
                                {g.restricted && <Pill tone="danger">Restricted</Pill>}
                              </span>
                            </td>
                            <td>{titleCase(g.kind)}
                              {g.kind === 'circle' && (
                                <span className="dim"> · {Math.round(g.radiusM ?? 0)} m</span>
                              )}
                            </td>
                            <td><Pill tone="info">{titleCase(g.trigger)}</Pill></td>
                            <td className="dim">
                              {g.vehicleIds.length ? `${g.vehicleIds.length} vehicles` : 'All vehicles'}
                            </td>
                            <td className="num">
                              {(g.kind === 'circle'
                                ? polygonAreaKm2(circlePolygon(g.centreLon!, g.centreLat!, g.radiusM!))
                                : polygonAreaKm2(g.polygon ?? [])).toFixed(2)} km²
                            </td>
                            <td className="num">
                              {st.inside > 0 ? <Pill tone="info">{st.inside}</Pill> : '0'}
                            </td>
                            <td className="num">{st.events}</td>
                            <td>
                              <button className="switch" data-on={g.active} role="switch"
                                      aria-checked={g.active} aria-label={`Toggle ${g.name}`}
                                      onClick={() => {
                                        g.active = !g.active;
                                        store.audit({
                                          action: 'geofence.updated', entityType: 'geofence',
                                          entityLabel: g.name,
                                          summary: `${g.name} ${g.active ? 'activated' : 'deactivated'}`,
                                        });
                                        store.emitNow();
                                        app.toast('success',
                                          `${g.name} ${g.active ? 'activated' : 'deactivated'}`);
                                      }} />
                            </td>
                            <td>
                              <div className="row" style={{ gap: 5 }}>
                                <Button size="sm" onClick={() => {
                                  setSelected(g.id);
                                  setTab('map');
                                  const c = g.kind === 'circle'
                                    ? [g.centreLat!, g.centreLon!]
                                    : [(g.polygon ?? [[0, 0]])[0][1], (g.polygon ?? [[0, 0]])[0][0]];
                                  app.focusMap(c[0], c[1], 15);
                                }}>Show</Button>
                                <Button size="sm" variant="ghost"
                                        onClick={() => setDeleting(g)}>Delete</Button>
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
          )}

          {tab === 'places' && (
            <Card pad={false}>
              <div className="table-wrap">
                <table className="data">
                  <thead><tr><th>Place</th><th>Category</th><th>Address</th>
                             <th>Contact</th><th className="num">Coordinates</th><th></th></tr></thead>
                  <tbody>
                    {s.places.filter((p) => p.active).map((p) => (
                      <tr key={p.id}>
                        <td style={{ fontWeight: 550 }}>{p.name}</td>
                        <td><Pill tone={p.category === 'depot' ? 'info'
                          : p.category === 'workshop' ? 'maintenance' : 'neutral'}>
                          {titleCase(p.category)}</Pill></td>
                        <td className="truncate" style={{ maxWidth: 230 }}>{p.address}</td>
                        <td className="dim">{p.contactPhone ?? '—'}</td>
                        <td className="num" style={{ fontSize: 11 }}>
                          {p.lat.toFixed(5)}, {p.lon.toFixed(5)}
                        </td>
                        <td>
                          <Button size="sm" onClick={() => {
                            setTab('map');
                            app.focusMap(p.lat, p.lon, 17);
                          }}>Show</Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {tab === 'map' && (
            <div className="card" style={{ height: 560, position: 'relative', overflow: 'hidden' }}>
              <div className="map-area" style={{ position: 'absolute', inset: 0 }}>
                <FleetMap base={base} theme={app.theme} rows={rows} routes={s.routes}
                          geofences={s.geofences} places={s.places} tasks={[]}
                          incidents={[]} disruptions={s.disruptions} weather={[]}
                          layers={{ ...DEFAULT_LAYERS, tasks: false, clusters: false }}
                          onSelectVehicle={(id) => app.navigate('live', { vehicle: id })}
                          onMapClick={(lon, lat) => {
                            if (drawing) setDraft({ lat, lon });
                            if (addingPlace) setPlaceDraft({ lat, lon });
                          }} />
                <div className="map-attrib">© OpenStreetMap contributors</div>
                {(drawing || addingPlace) && (
                  <div className="conn-banner" style={{ borderColor: 'var(--pulse)' }}>
                    <IconZone size={14} />
                    <span>
                      {drawing
                        ? draft ? 'Centre picked — set the radius in the panel.'
                                : 'Click the map to place the centre of the zone.'
                        : placeDraft ? 'Point picked — name it in the panel.'
                                     : 'Click the map to place the new location.'}
                    </span>
                    <Button size="sm" variant="ghost"
                            onClick={() => { setDrawing(false); setAddingPlace(false); }}>
                      Cancel
                    </Button>
                  </div>
                )}
                <div className="map-legend">
                  <span className="eyebrow">Zones</span>
                  <span className="row"><i style={{ background: '#1E90FF' }} /> Monitored</span>
                  <span className="row"><i style={{ background: '#2ECC71' }} /> Low-emission</span>
                  <span className="row"><i style={{ background: '#E74C3C' }} /> Restricted</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {drawing && (
        <GeofenceComposer draft={draft} onPickOnMap={() => setTab('map')}
                          onClose={() => { setDrawing(false); setDraft(null); }} />
      )}
      {addingPlace && (
        <PlaceComposer draft={placeDraft} onPickOnMap={() => setTab('map')}
                       onClose={() => { setAddingPlace(false); setPlaceDraft(null); }} />
      )}
      {deleting && (
        <Confirm title={`Delete “${deleting.name}”?`}
                 body="The zone stops being evaluated immediately and disappears from the map."
                 consequences={
                   <div className="banner" data-tone="warn">
                     <IconAlert size={15} />
                     <span>
                       Alerts already raised by this zone are kept for the record, but no new
                       entry or exit events will fire.
                     </span>
                   </div>
                 }
                 confirmLabel="Delete geofence" tone="danger"
                 onCancel={() => setDeleting(null)}
                 onConfirm={() => {
                   app.run(() => deleteGeofence(store, deleting.id), `“${deleting.name}” deleted`);
                   setDeleting(null);
                 }} />
      )}
    </div>
  );
}

function GeofenceComposer({ draft, onClose, onPickOnMap }: {
  draft: { lat: number; lon: number } | null; onClose: () => void; onPickOnMap: () => void;
}) {
  const app = useApp();
  const { store, state: s } = app;
  const [name, setName] = useState('');
  const [radius, setRadius] = useState(150);
  const [trigger, setTrigger] = useState<'enter' | 'exit' | 'both'>('both');
  const [restricted, setRestricted] = useState(false);
  const [colour, setColour] = useState('#1E90FF');
  const [description, setDescription] = useState('');
  const [placeId, setPlaceId] = useState('');

  const centre = draft ?? (placeId
    ? (() => { const p = store.place(placeId); return p ? { lat: p.lat, lon: p.lon } : null; })()
    : null);

  return (
    <Modal title="New geofence" onClose={onClose}
           subtitle="A circular zone around a real point. Entering or leaving raises an alert."
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant="primary" disabled={!name.trim() || !centre} onClick={() => {
               const ok = app.run(() => createGeofence(store, {
                 name, kind: 'circle', trigger,
                 centreLat: centre!.lat, centreLon: centre!.lon, radiusM: radius,
                 restricted, colour: restricted ? '#E74C3C' : colour,
                 description: description || undefined,
               }), `“${name}” created`);
               if (ok) onClose();
             }}>Create geofence</Button>
           </>}>
      <div className="stack">
        <Field label="Name">
          <input className="input" value={name} autoFocus
                 onChange={(e) => setName(e.target.value)}
                 placeholder="Customer loading bay" />
        </Field>

        <Field label="Centre" hint="Pick a saved place, or click a point on the map.">
          <div className="row" style={{ gap: 8 }}>
            <select className="select" value={placeId} onChange={(e) => setPlaceId(e.target.value)}>
              <option value="">Choose a place…</option>
              {s.places.filter((p) => p.active).map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            <Button onClick={onPickOnMap}>Pick on map</Button>
          </div>
        </Field>

        {centre ? (
          <div className="banner" data-tone="info">
            <span className="mono">
              Centre {centre.lat.toFixed(5)}, {centre.lon.toFixed(5)} · radius {radius} m ·
              area {(Math.PI * radius * radius / 1e6).toFixed(3)} km²
            </span>
          </div>
        ) : (
          <div className="banner" data-tone="warn">
            <IconAlert size={15} />
            <span>Choose a centre before creating the zone.</span>
          </div>
        )}

        <div className="grid-2">
          <Field label={`Radius: ${radius} m`}>
            <input type="range" min={40} max={900} step={10} value={radius}
                   onChange={(e) => setRadius(Number(e.target.value))} style={{ width: '100%' }} />
          </Field>
          <Field label="Trigger on">
            <select className="select" value={trigger}
                    onChange={(e) => setTrigger(e.target.value as typeof trigger)}>
              <option value="both">Entry and exit</option>
              <option value="enter">Entry only</option>
              <option value="exit">Exit only</option>
            </select>
          </Field>
        </div>

        <Field label="Colour">
          <div className="row wrap" style={{ gap: 6 }}>
            {['#1E90FF', '#2ECC71', '#F5A623', '#9B6BFF', '#FF6B35'].map((c) => (
              <button key={c} onClick={() => setColour(c)} aria-label={`Colour ${c}`}
                      style={{
                        width: 26, height: 26, borderRadius: 6, background: c,
                        border: colour === c ? '2px solid var(--ink)' : '2px solid transparent',
                      }} />
            ))}
          </div>
        </Field>

        <label className="row" style={{ gap: 8, fontSize: 12.5 }}>
          <input type="checkbox" checked={restricted}
                 onChange={(e) => setRestricted(e.target.checked)} />
          Restricted zone — entering raises a <strong>critical</strong> alert and deducts driver points.
        </label>

        <Field label="Description">
          <textarea className="textarea" value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Vehicles are not permitted here during trading hours." />
        </Field>
      </div>
    </Modal>
  );
}

function PlaceComposer({ draft, onClose, onPickOnMap }: {
  draft: { lat: number; lon: number } | null; onClose: () => void; onPickOnMap: () => void;
}) {
  const app = useApp();
  const [name, setName] = useState('');
  const [category, setCategory] = useState<Place['category']>('customer_site');
  const [address, setAddress] = useState('');
  const [contactName, setContactName] = useState('');
  const [contactPhone, setContactPhone] = useState('');

  const reverse = draft ? app.store.graph.streetAt(draft.lon, draft.lat) : '';

  return (
    <Modal title="New place" onClose={onClose}
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant="primary" disabled={!name.trim() || !draft} onClick={() => {
               const ok = app.run(() => createPlace(app.store, {
                 name, category, lat: draft!.lat, lon: draft!.lon,
                 address: address || (reverse ? `${reverse}, Helsinki` : 'Helsinki'),
                 contactName: contactName || undefined,
                 contactPhone: contactPhone || undefined,
               }), `“${name}” added`);
               if (ok) onClose();
             }}>Add place</Button>
           </>}>
      <div className="stack">
        <Field label="Name">
          <input className="input" value={name} autoFocus
                 onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Category">
          <select className="select" value={category}
                  onChange={(e) => setCategory(e.target.value as Place['category'])}>
            {['depot', 'customer_site', 'fuel_station', 'workshop', 'parking', 'custom'].map((c) =>
              <option key={c} value={c}>{titleCase(c)}</option>)}
          </select>
        </Field>
        <Field label="Position">
          {draft ? (
            <div className="banner" data-tone="info">
              <span className="mono">
                {draft.lat.toFixed(5)}, {draft.lon.toFixed(5)}
                {reverse && ` · ${reverse}`}
              </span>
            </div>
          ) : (
            <Button onClick={onPickOnMap}>Pick a point on the map</Button>
          )}
        </Field>
        <Field label="Address" hint="Leave blank to use the nearest street name.">
          <input className="input" value={address} onChange={(e) => setAddress(e.target.value)}
                 placeholder={reverse ? `${reverse}, Helsinki` : 'Helsinki'} />
        </Field>
        <div className="grid-2">
          <Field label="Contact name">
            <input className="input" value={contactName}
                   onChange={(e) => setContactName(e.target.value)} />
          </Field>
          <Field label="Contact phone">
            <input className="input" value={contactPhone}
                   onChange={(e) => setContactPhone(e.target.value)} />
          </Field>
        </div>
      </div>
    </Modal>
  );
}
