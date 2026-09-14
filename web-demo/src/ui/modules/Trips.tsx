// Trips & History, including full GPS playback with event scrubbing.

import { useEffect, useMemo, useRef, useState } from 'react';

import { useApp } from '../app-context';
import {
  Button, Card, Empty, Kpi, Modal, Pill, Sparkline, dmy, hm, titleCase, type Tone,
} from '../components/kit';
import { IconPause, IconPlay, IconRefresh } from '../icons';
import { DEFAULT_LAYERS, FleetMap, type PlaybackFrame } from '../map/FleetMap';
import type { BaseData } from '../map/style';

const DAY = 86400000;
const SPEEDS = [1, 5, 20, 60];

export function Trips({ base }: { base: BaseData }) {
  const app = useApp();
  const { store, state: s } = app;
  const [openId, setOpenId] = useState<string | undefined>(app.params.trip);
  const [vehicleId, setVehicleId] = useState('');
  const [driverId, setDriverId] = useState('');
  const [days, setDays] = useState(7);
  const [query, setQuery] = useState('');

  useEffect(() => { if (app.params.trip) setOpenId(app.params.trip); }, [app.params.trip]);

  const since = s.now - days * DAY;
  const trips = useMemo(() => s.trips
    .filter((t) => t.startedAt >= since)
    .filter((t) => !vehicleId || t.vehicleId === vehicleId)
    .filter((t) => !driverId || t.driverId === driverId)
    .filter((t) => {
      const q = query.trim().toLowerCase();
      if (!q) return true;
      return [t.reference, t.startAddress, t.endAddress]
        .some((f) => f?.toLowerCase().includes(q));
    })
    .sort((a, b) => b.startedAt - a.startedAt), [s.trips, since, vehicleId, driverId, query]);

  const totals = useMemo(() => ({
    trips: trips.length,
    km: trips.reduce((a, t) => a + t.distanceKm, 0),
    hours: trips.reduce((a, t) => a + t.durationS, 0) / 3600,
    idleHours: trips.reduce((a, t) => a + t.idleS, 0) / 3600,
    events: trips.reduce((a, t) => a + t.eventCount, 0),
    maxSpeed: Math.max(0, ...trips.map((t) => t.maxSpeedKph)),
  }), [trips]);

  const daily = useMemo(() => Array.from({ length: days }, (_, i) => {
    const day = new Date(s.now - (days - 1 - i) * DAY).toISOString().slice(0, 10);
    return trips.filter((t) => new Date(t.startedAt).toISOString().slice(0, 10) === day)
      .reduce((a, t) => a + t.distanceKm, 0);
  }), [trips, days, s.now]);

  return (
    <div className="scroll">
      <div className="page">
        <div className="page-head">
          <div className="grow">
            <h2 className="page-title">Trips & History</h2>
            <p className="page-sub">
              What actually happened. Every GPS sample is kept, so any trip can be
              replayed with its events pinned to the timeline.
            </p>
          </div>
        </div>

        <div className="kpis" style={{ marginBottom: 14 }}>
          <Kpi label="Trips" value={totals.trips} />
          <Kpi label="Distance" value={Math.round(totals.km).toLocaleString()} unit=" km" />
          <Kpi label="Driving" value={totals.hours.toFixed(1)} unit=" h" />
          <Kpi label="Idle" value={totals.idleHours.toFixed(1)} unit=" h"
               foot={totals.hours > 0
                 ? `${((totals.idleHours / totals.hours) * 100).toFixed(1)}% of engine-on`
                 : undefined}
               tone={totals.idleHours / Math.max(0.1, totals.hours) > 0.25 ? 'warn' : undefined} />
          <Kpi label="Events" value={totals.events}
               tone={totals.events ? 'warn' : 'good'} />
          <Kpi label="Max speed" value={totals.maxSpeed.toFixed(0)} unit=" km/h" />
        </div>

        <Card title={`Distance per day, last ${days} days`} >
          <Sparkline points={daily} height={54} />
        </Card>

        <div className="row wrap" style={{ gap: 8, margin: '14px 0 12px' }}>
          <input className="input" placeholder="Search reference or address" value={query}
                 onChange={(e) => setQuery(e.target.value)} style={{ maxWidth: 250 }} />
          <select className="select" style={{ width: 190 }} value={vehicleId}
                  onChange={(e) => setVehicleId(e.target.value)}>
            <option value="">All vehicles</option>
            {s.vehicles.map((v) => <option key={v.id} value={v.id}>{v.name} · {v.plate}</option>)}
          </select>
          <select className="select" style={{ width: 180 }} value={driverId}
                  onChange={(e) => setDriverId(e.target.value)}>
            <option value="">All drivers</option>
            {s.drivers.map((d) => <option key={d.id} value={d.id}>{d.fullName}</option>)}
          </select>
          <select className="select" style={{ width: 140 }} value={days}
                  onChange={(e) => setDays(Number(e.target.value))}>
            {[1, 7, 30, 90, 210].map((d) => (
              <option key={d} value={d}>Last {d} day{d === 1 ? '' : 's'}</option>
            ))}
          </select>
          <div className="grow" />
          <span className="dim" style={{ fontSize: 12 }}>{trips.length} trips</span>
        </div>

        <Card pad={false}>
          {trips.length === 0 ? (
            <Empty title="No trips in this range"
                   body="Widen the date range, or clear the vehicle and driver filters." />
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr><th>Trip</th><th>Vehicle</th><th>Driver</th><th>Started</th>
                      <th>From → To</th><th className="num">Distance</th>
                      <th className="num">Duration</th><th className="num">Avg</th>
                      <th className="num">Max</th><th className="num">Events</th>
                      <th className="num">CO₂</th><th></th></tr>
                </thead>
                <tbody>
                  {trips.slice(0, 200).map((t) => (
                    <tr key={t.id} data-clickable="true" onClick={() => setOpenId(t.id)}>
                      <td className="mono">
                        {t.reference}
                        {t.status === 'active' && <Pill tone="good">Live</Pill>}
                      </td>
                      <td className="mono">{store.vehicle(t.vehicleId)?.name}</td>
                      <td>{store.driver(t.driverId)?.fullName ?? '—'}</td>
                      <td className="num">{dmy(t.startedAt)} {hm(t.startedAt)}</td>
                      <td className="truncate" style={{ maxWidth: 240 }}>
                        {t.startAddress} → {t.endAddress ?? 'in progress'}
                      </td>
                      <td className="num">{t.distanceKm.toFixed(1)}</td>
                      <td className="num">{Math.round(t.durationS / 60)} min</td>
                      <td className="num">{t.avgSpeedKph.toFixed(0)}</td>
                      <td className="num">{t.maxSpeedKph.toFixed(0)}</td>
                      <td className="num">
                        {t.eventCount > 0 ? <Pill tone="warn">{t.eventCount}</Pill> : '0'}
                      </td>
                      <td className="num">{t.co2Kg.toFixed(1)} kg</td>
                      <td>
                        {t.positions.length > 1 && (
                          <Button size="sm" onClick={(() => setOpenId(t.id))}>Replay</Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      {openId && <TripPlayback tripId={openId} base={base} onClose={() => setOpenId(undefined)} />}
    </div>
  );
}

function TripPlayback({ tripId, base, onClose }: {
  tripId: string; base: BaseData; onClose: () => void;
}) {
  const app = useApp();
  const { store, state: s } = app;
  const trip = store.trip(tripId);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(5);
  const [cursor, setCursor] = useState(0);      // seconds from trip start
  const raf = useRef<number | null>(null);
  const last = useRef(0);

  const samples = trip?.positions ?? [];
  const base0 = samples[0]?.t ?? trip?.startedAt ?? 0;
  const duration = samples.length > 1
    ? (samples[samples.length - 1].t - base0) / 1000
    : (trip?.durationS ?? 0);

  const events = useMemo(() => (trip
    ? s.driverEvents.filter((e) => e.tripId === trip.id)
      .map((e) => ({ ...e, t: (e.occurredAt - base0) / 1000 }))
      .sort((a, b) => a.t - b.t)
    : []), [trip, s.driverEvents, base0]);

  useEffect(() => {
    if (!playing) { if (raf.current) cancelAnimationFrame(raf.current); return; }
    last.current = performance.now();
    const step = () => {
      const now = performance.now();
      const dt = (now - last.current) / 1000;
      last.current = now;
      setCursor((c) => {
        const next = c + dt * speed;
        if (next >= duration) { setPlaying(false); return duration; }
        return next;
      });
      raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => { if (raf.current) cancelAnimationFrame(raf.current); };
  }, [playing, speed, duration]);

  if (!trip) return null;
  const vehicle = store.vehicle(trip.vehicleId);
  const driver = store.driver(trip.driverId);

  const index = samples.length
    ? Math.max(0, samples.findIndex((p) => (p.t - base0) / 1000 >= cursor))
    : 0;
  const current = samples[index === -1 ? samples.length - 1 : index] ?? samples[0];

  const frame: PlaybackFrame | null = samples.length > 1 && current ? {
    lat: current.lat, lon: current.lon, heading: current.heading, speedKph: current.speedKph,
    path: samples.map((p) => [p.lon, p.lat] as [number, number]),
    travelled: samples.slice(0, index + 1).map((p) => [p.lon, p.lat] as [number, number]),
    events: events.map((e) => ({ lat: e.lat ?? 0, lon: e.lon ?? 0, kind: e.kind,
                                 severity: e.severity })),
  } : null;

  const speedProfile = samples.map((p) => p.speedKph);

  return (
    <Modal title={`${trip.reference} — trip playback`} size="xl" onClose={onClose}
           subtitle={
             <div className="row wrap" style={{ gap: 8 }}>
               <span className="mono">{vehicle?.name} · {vehicle?.plate}</span>
               <span className="dim">·</span>
               <span>{driver?.fullName ?? 'No driver'}</span>
               <span className="dim">·</span>
               <span>{dmy(trip.startedAt)} {hm(trip.startedAt)}</span>
               {trip.status === 'active' && <Pill tone="good">Live trip</Pill>}
             </div>
           }>
      <div className="stack">
        <div className="kpis">
          <Kpi label="Distance" value={trip.distanceKm.toFixed(1)} unit=" km" />
          <Kpi label="Duration" value={Math.round(trip.durationS / 60)} unit=" min" />
          <Kpi label="Avg speed" value={trip.avgSpeedKph.toFixed(0)} unit=" km/h" />
          <Kpi label="Max speed" value={trip.maxSpeedKph.toFixed(0)} unit=" km/h"
               tone={trip.maxSpeedKph > 60 ? 'warn' : undefined} />
          <Kpi label="Idle" value={Math.round(trip.idleS / 60)} unit=" min" />
          <Kpi label="Events" value={trip.eventCount}
               tone={trip.eventCount ? 'warn' : 'good'} />
          <Kpi label="CO₂" value={trip.co2Kg.toFixed(1)} unit=" kg" />
        </div>

        {samples.length > 1 ? (
          <>
            <div className="card" style={{ height: 400, position: 'relative', overflow: 'hidden' }}>
              <div className="map-area" style={{ position: 'absolute', inset: 0 }}>
                <FleetMap base={base} theme={app.theme} rows={[]} routes={[]}
                          geofences={s.geofences} places={s.places} tasks={[]}
                          incidents={[]} disruptions={[]} weather={[]}
                          layers={{ ...DEFAULT_LAYERS, vehicles: false, places: false,
                                    activeRoutes: false, plannedRoutes: false, tasks: false }}
                          playback={frame}
                          focus={current ? { lat: current.lat, lon: current.lon, zoom: 16,
                                             key: index } : undefined}
                          onSelectVehicle={() => undefined} />
                <div className="map-attrib">© OpenStreetMap contributors</div>
                {current && (
                  <div style={{
                    position: 'absolute', left: 12, top: 12, zIndex: 4,
                    background: 'var(--map-scrim)', backdropFilter: 'blur(10px)',
                    border: '1px solid var(--line)', borderRadius: 8, padding: '8px 11px',
                  }}>
                    <div className="eyebrow">At {hm(current.t)}</div>
                    <div className="num" style={{ fontSize: 21, fontWeight: 600 }}>
                      {Math.round(current.speedKph)}<span style={{ fontSize: 12 }}> km/h</span>
                    </div>
                    <div className="dim" style={{ fontSize: 11 }}>
                      {current.street ?? 'On the network'}
                    </div>
                  </div>
                )}
              </div>
            </div>

            <Card>
              <div className="row" style={{ gap: 10, marginBottom: 10 }}>
                <Button size="sm" variant="primary" onClick={() => {
                  if (cursor >= duration) setCursor(0);
                  setPlaying(!playing);
                }}>
                  {playing ? <IconPause size={13} /> : <IconPlay size={13} />}
                  {playing ? 'Pause' : 'Play'}
                </Button>
                <Button size="sm" onClick={() => { setCursor(0); setPlaying(false); }}>
                  <IconRefresh size={13} /> Restart
                </Button>
                <div className="row" style={{ gap: 3 }}>
                  {SPEEDS.map((x) => (
                    <button key={x} className="chip" data-on={speed === x}
                            onClick={() => setSpeed(x)}>{x}×</button>
                  ))}
                </div>
                <div className="grow" />
                <span className="mono" style={{ fontSize: 12 }}>
                  {fmtClock(cursor)} / {fmtClock(duration)}
                </span>
              </div>

              <div style={{ position: 'relative' }}>
                <input type="range" min={0} max={Math.max(1, duration)} step={0.5} value={cursor}
                       onChange={(e) => { setCursor(Number(e.target.value)); setPlaying(false); }}
                       style={{ width: '100%' }} aria-label="Playback position" />
                {events.map((e) => (
                  <button key={e.id} title={`${titleCase(e.kind)} — ${e.detail ?? ''}`}
                          onClick={() => { setCursor(e.t); setPlaying(false); }}
                          style={{
                            position: 'absolute', top: -3,
                            left: `${(e.t / Math.max(1, duration)) * 100}%`,
                            width: 9, height: 9, borderRadius: '50%', transform: 'translateX(-50%)',
                            background: e.severity === 'high' ? 'var(--danger)'
                              : e.severity === 'medium' ? 'var(--warning)' : 'var(--pulse)',
                            border: '2px solid var(--surface)', cursor: 'pointer',
                          }} />
                ))}
              </div>

              <div style={{ marginTop: 12 }}>
                <div className="eyebrow" style={{ marginBottom: 4 }}>Speed profile</div>
                <Sparkline points={speedProfile} height={46}
                           tone={trip.maxSpeedKph > 60 ? 'var(--warning)' : 'var(--pulse)'} />
              </div>
            </Card>
          </>
        ) : (
          <Card>
            <Empty title="No GPS samples stored for this trip"
                   body="FleetBeat keeps the full sample track for recent trips. Older trips keep
                         their summary, distance, events and cost, but not the second-by-second track." />
          </Card>
        )}

        <Card pad={false} title={`Events on this trip (${events.length})`}>
          {events.length === 0 ? (
            <Empty title="A clean trip" body="No speeding, harsh braking or cornering was recorded." />
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>At</th><th>Event</th><th>Where</th><th className="num">Value</th>
                           <th>Detail</th><th></th></tr></thead>
                <tbody>
                  {events.map((e) => (
                    <tr key={e.id}>
                      <td className="num">{hm(e.occurredAt)}</td>
                      <td><Pill tone={e.severity as Tone}>{titleCase(e.kind)}</Pill></td>
                      <td className="truncate" style={{ maxWidth: 150 }}>{e.street ?? '—'}</td>
                      <td className="num">{e.value ?? '—'}</td>
                      <td className="truncate" style={{ maxWidth: 280 }}>{e.detail}</td>
                      <td>
                        {samples.length > 1 && (
                          <Button size="sm" onClick={() => { setCursor(e.t); setPlaying(false); }}>
                            Jump to
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </Modal>
  );
}

function fmtClock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const sec = Math.floor(seconds % 60);
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}
