// The operational command centre. Map-dominant, with the fleet panel on the
// left, a contextual drawer on the right and the live KPI strip along the foot.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  assignDriverToVehicle, addStop, applyOptimisation, avoidEdgeUnderPoint,
  createTask, moveStop, previewOptimisation, recalculateRoute, removeStop, saveView,
} from '../../engine/actions';
import { haversine } from '../../engine/geo';
import { fleetRows, liveKpis, openAlertsFor, type FleetRow } from '../../engine/selectors';
import type { Route } from '../../engine/types';
import { useApp } from '../app-context';
import {
  Avatar, Button, Confirm, Empty, Field, Modal, Pill, Progress, Timeline,
  hm, relTime, titleCase, type Tone,
} from '../components/kit';
import {
  IconAlert, IconChevron, IconClose, IconCompass, IconFit, IconLayers,
  IconMessage, IconPlus, IconRoute, IconRuler, IconSearch, IconTrash, IconTruck,
  IconWrench, IconZoomIn, IconZoomOut,
} from '../icons';
import { DEFAULT_LAYERS, FleetMap, type MapLayers } from '../map/FleetMap';
import type { MlMap } from '../map/maplibre';
import type { BaseData } from '../map/style';

type StatusFilter = 'all' | 'moving' | 'idle' | 'stopped' | 'offline';
type OpFilter = 'active_task' | 'late_task' | 'no_task' | 'on_route' | 'deviation';
type RiskFilter = 'critical_alert' | 'alert' | 'maintenance_due' | 'compliance';
type DriverFilter = 'assigned' | 'unassigned';

const STATUS_TABS: { key: StatusFilter; label: string }[] = [
  { key: 'all', label: 'All' }, { key: 'moving', label: 'Moving' },
  { key: 'idle', label: 'Idle' }, { key: 'stopped', label: 'Stopped' },
  { key: 'offline', label: 'Offline' },
];

export function LiveTracking({ base }: { base: BaseData }) {
  const app = useApp();
  const { store, state: s } = app;
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<StatusFilter>('all');
  const [ops, setOps] = useState<Set<OpFilter>>(new Set());
  const [risk, setRisk] = useState<Set<RiskFilter>>(new Set());
  const [driverFilter, setDriverFilter] = useState<Set<DriverFilter>>(new Set());
  const [selected, setSelected] = useState<string | undefined>();
  const [layers, setLayers] = useState<MapLayers>(DEFAULT_LAYERS);
  const [layerPanel, setLayerPanel] = useState(false);
  const [mapSearch, setMapSearch] = useState('');
  const [measure, setMeasure] = useState<[number, number][] | null>(null);
  const [ctx, setCtx] = useState<{ id: string; x: number; y: number } | null>(null);
  const [routeEditor, setRouteEditor] = useState<string | null>(null);
  const [fitKey, setFitKey] = useState(0);
  const [focus, setFocus] = useState<{ lat: number; lon: number; zoom?: number; key: number }>();
  const [saveViewOpen, setSaveViewOpen] = useState(false);
  const [composeFor, setComposeFor] = useState<string | null>(null);
  const [assignDriverFor, setAssignDriverFor] = useState<string | null>(null);
  const [messageFor, setMessageFor] = useState<string | null>(null);
  const mapRef = useRef<MlMap | null>(null);

  const rows = useMemo(() => fleetRows(store), [store, s.ticks, s.vehicles, s.tasks, s.alerts]);
  const kpis = useMemo(() => liveKpis(store, rows), [store, rows]);

  const filtered = useMemo(() => rows.filter((r) => {
    if (status !== 'all' && r.status !== status) return false;
    const q = query.trim().toLowerCase();
    if (q && ![r.vehicle.name, r.vehicle.plate, r.driver?.fullName, r.vehicle.street]
      .some((f) => f?.toLowerCase().includes(q))) return false;
    if (ops.size) {
      const pass =
        (ops.has('active_task') && r.taskCount > 0) ||
        (ops.has('late_task') && r.lateTaskCount > 0) ||
        (ops.has('no_task') && r.taskCount === 0) ||
        (ops.has('on_route') && r.routeProgressPct != null) ||
        (ops.has('deviation') && (r.deviationM ?? 0) > 250);
      if (!pass) return false;
    }
    if (risk.size) {
      const pass =
        (risk.has('critical_alert') && r.worstAlert === 'critical') ||
        (risk.has('alert') && r.alertCount > 0) ||
        (risk.has('maintenance_due') &&
          ['due', 'due_soon', 'overdue', 'critical'].includes(r.maintenance)) ||
        (risk.has('compliance') && s.documents.some(
          (d) => d.vehicleId === r.vehicle.id && d.status !== 'valid'));
      if (!pass) return false;
    }
    if (driverFilter.size) {
      const pass = (driverFilter.has('assigned') && r.driver) ||
                   (driverFilter.has('unassigned') && !r.driver);
      if (!pass) return false;
    }
    return true;
  }), [rows, status, query, ops, risk, driverFilter, s.documents]);

  const selectedRow = rows.find((r) => r.vehicle.id === selected);

  const select = useCallback((id: string) => {
    setSelected(id);
    const row = rows.find((r) => r.vehicle.id === id);
    if (row?.vehicle.lat != null) {
      setFocus((f) => ({ lat: row.vehicle.lat!, lon: row.vehicle.lon!, zoom: 16.4,
                         key: (f?.key ?? 0) + 1 }));
    }
  }, [rows]);

  // deep link from elsewhere in the app
  useEffect(() => {
    if (app.params.vehicle) select(app.params.vehicle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [app.params.vehicle]);

  const geoResults = useMemo(() => {
    const q = mapSearch.trim().toLowerCase();
    if (q.length < 2) return [];
    const out: { title: string; sub: string; lat: number; lon: number }[] = [];
    s.vehicles.filter((v) => v.name.toLowerCase().includes(q) || v.plate.toLowerCase().includes(q))
      .slice(0, 3).forEach((v) => out.push({
        title: `${v.name} · ${v.plate}`, sub: 'Vehicle', lat: v.lat ?? 0, lon: v.lon ?? 0 }));
    s.drivers.filter((d) => d.fullName.toLowerCase().includes(q)).slice(0, 3).forEach((d) => {
      const v = s.vehicles.find((x) => x.driverId === d.id);
      if (v?.lat != null) out.push({ title: d.fullName, sub: `Driving ${v.name}`, lat: v.lat, lon: v.lon! });
    });
    s.places.filter((p) => p.name.toLowerCase().includes(q)).slice(0, 5).forEach((p) => out.push({
      title: p.name, sub: `${titleCase(p.category)} · ${p.address ?? ''}`, lat: p.lat, lon: p.lon }));
    const streets = new Map<string, [number, number]>();
    store.graph.edges.forEach((e) => {
      if (e.name && e.name.toLowerCase().includes(q) && !streets.has(e.name)) {
        streets.set(e.name, e.geom[Math.floor(e.geom.length / 2)]);
      }
    });
    [...streets.entries()].slice(0, 5).forEach(([name, pt]) => out.push({
      title: name, sub: 'Street · Helsinki', lat: pt[1], lon: pt[0] }));
    return out.slice(0, 9);
  }, [mapSearch, s.vehicles, s.drivers, s.places, store.graph]);

  const toggle = <T,>(set: Set<T>, apply: (s: Set<T>) => void, value: T) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value); else next.add(value);
    apply(next);
  };

  const measureTotal = measure && measure.length > 1
    ? measure.slice(1).reduce((a, p, i) => a + haversine(measure[i][0], measure[i][1], p[0], p[1]), 0)
    : 0;

  const activeRoute = routeEditor ? store.route(routeEditor) : null;

  return (
    <div className="lt">
      <aside className="fleet-panel">
        <div className="fleet-head">
          <div className="row" style={{ gap: 7, marginBottom: 8 }}>
            <div style={{ position: 'relative', flex: 1 }}>
              <input className="input" placeholder="Vehicle, plate or driver"
                     value={query} onChange={(e) => setQuery(e.target.value)}
                     style={{ paddingLeft: 30 }} aria-label="Search the fleet panel" />
              <span style={{ position: 'absolute', left: 9, top: 8, color: 'var(--ink-4)',
                             pointerEvents: 'none' }}>
                <IconSearch size={14} />
              </span>
            </div>
            <Button size="sm" onClick={() => setSaveViewOpen(true)} title="Save this filter set">
              Save view
            </Button>
          </div>
          <div className="row wrap" style={{ gap: 4 }}>
            {STATUS_TABS.map((t) => (
              <button key={t.key} className="chip" data-on={status === t.key}
                      onClick={() => setStatus(t.key)}>
                {t.label}
                <span className="count">
                  {t.key === 'all' ? rows.length : rows.filter((r) => r.status === t.key).length}
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="fleet-filters">
          <span className="eyebrow" style={{ width: '100%' }}>Operational</span>
          {([['active_task', 'Active task'], ['late_task', 'Late'], ['no_task', 'No task'],
             ['on_route', 'On route'], ['deviation', 'Deviation']] as [OpFilter, string][])
            .map(([key, label]) => (
              <button key={key} className="chip" data-on={ops.has(key)}
                      onClick={() => toggle(ops, setOps, key)}>{label}</button>
            ))}
          <span className="eyebrow" style={{ width: '100%', marginTop: 4 }}>Risk</span>
          {([['critical_alert', 'Critical'], ['alert', 'Any alert'],
             ['maintenance_due', 'Maintenance'], ['compliance', 'Compliance']] as [RiskFilter, string][])
            .map(([key, label]) => (
              <button key={key} className="chip" data-on={risk.has(key)}
                      onClick={() => toggle(risk, setRisk, key)}>{label}</button>
            ))}
          <span className="eyebrow" style={{ width: '100%', marginTop: 4 }}>Driver</span>
          {([['assigned', 'Assigned'], ['unassigned', 'Unassigned']] as [DriverFilter, string][])
            .map(([key, label]) => (
              <button key={key} className="chip" data-on={driverFilter.has(key)}
                      onClick={() => toggle(driverFilter, setDriverFilter, key)}>{label}</button>
            ))}
        </div>

        {s.savedViews.length > 0 && (
          <div className="fleet-filters" style={{ paddingTop: 7, paddingBottom: 7 }}>
            <span className="eyebrow" style={{ width: '100%' }}>Saved views</span>
            {s.savedViews.map((v) => (
              <button key={v.id} className="chip" onClick={() => {
                const f = v.filters as Record<string, string[]>;
                setStatus((f.status?.[0] as StatusFilter) ?? 'all');
                setOps(new Set((f.operational ?? []) as OpFilter[]));
                setRisk(new Set((f.risk ?? []) as RiskFilter[]));
                app.toast('info', `View “${v.name}” applied`);
              }}>{v.name}</button>
            ))}
          </div>
        )}

        <div className="fleet-list">
          {filtered.length === 0 && (
            <Empty title="No vehicles match"
                   body="Clear a filter, or widen the search. The fleet panel shows every tracked vehicle by default."
                   action={<Button size="sm" onClick={() => {
                     setStatus('all'); setOps(new Set()); setRisk(new Set());
                     setDriverFilter(new Set()); setQuery('');
                   }}>Reset filters</Button>} />
          )}
          {filtered.map((row) => (
            <VehicleRow key={row.vehicle.id} row={row} selected={selected === row.vehicle.id}
                        now={s.now} onSelect={() => select(row.vehicle.id)} />
          ))}
        </div>
      </aside>

      <div className="map-area">
        <FleetMap
          base={base} theme={app.theme} rows={rows}
          routes={s.routes} geofences={s.geofences} places={s.places}
          tasks={s.tasks.filter((t) => !['completed', 'cancelled'].includes(t.status))}
          incidents={s.incidents} disruptions={s.disruptions} weather={s.weather}
          layers={layers} selectedVehicleId={selected} focus={focus} fitKey={fitKey}
          draftRoute={activeRoute ? { geometry: activeRoute.geometry, stops: activeRoute.stops } : null}
          measure={measure}
          onSelectVehicle={select}
          onMapClick={(lon, lat) => {
            if (measure) setMeasure([...measure, [lon, lat]]);
            else setCtx(null);
          }}
          onContextVehicle={(id, x, y) => setCtx({ id, x, y })}
          onReady={(m) => { mapRef.current = m; }}
        />

        <div className="map-search">
          <span className="icon"><IconSearch size={15} /></span>
          <input className="input" placeholder="Find an address, place, vehicle or driver"
                 value={mapSearch} onChange={(e) => setMapSearch(e.target.value)}
                 aria-label="Search the map" />
          {geoResults.length > 0 && (
            <div className="search-results">
              {geoResults.map((r, i) => (
                <button key={i} className="search-result" onClick={() => {
                  setFocus((f) => ({ lat: r.lat, lon: r.lon, zoom: 17, key: (f?.key ?? 0) + 1 }));
                  setMapSearch('');
                }}>
                  <span className="grow">
                    <span className="title">{r.title}</span>
                    <div className="sub">{r.sub}</div>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="map-tools">
          <div className="tool-group">
            <button className="tool" title="Zoom in"
                    onClick={() => mapRef.current?.setZoom(mapRef.current.getZoom() + 1)}>
              <IconZoomIn size={15} />
            </button>
            <button className="tool" title="Zoom out"
                    onClick={() => mapRef.current?.setZoom(mapRef.current.getZoom() - 1)}>
              <IconZoomOut size={15} />
            </button>
            <button className="tool" title="Reset bearing to north"
                    onClick={() => { mapRef.current?.setBearing(0); mapRef.current?.setPitch(0); }}>
              <IconCompass size={15} />
            </button>
            <button className="tool" title="Fit every vehicle"
                    onClick={() => setFitKey((k) => k + 1)}>
              <IconFit size={15} />
            </button>
          </div>
          <div className="tool-group">
            <button className="tool" title="Map layers" data-on={layerPanel}
                    onClick={() => setLayerPanel((v) => !v)}>
              <IconLayers size={15} />
            </button>
            <button className="tool" title="Measure distance" data-on={!!measure}
                    onClick={() => setMeasure(measure ? null : [])}>
              <IconRuler size={15} />
            </button>
            <button className="tool" title="3D buildings"
                    data-on={(mapRef.current?.getPitch() ?? 0) > 10}
                    onClick={() => {
                      const m = mapRef.current;
                      if (!m) return;
                      m.easeTo({ pitch: m.getPitch() > 10 ? 0 : 52, duration: 600 });
                    }}>
              <IconTruck size={15} />
            </button>
          </div>
        </div>

        {layerPanel && (
          <div className="layer-panel">
            <div className="row" style={{ marginBottom: 6 }}>
              <span className="eyebrow grow">Map layers</span>
              <button className="iconbtn" onClick={() => setLayerPanel(false)} aria-label="Close">
                <IconClose size={13} />
              </button>
            </div>
            {([
              ['vehicles', 'Vehicles'], ['clusters', 'Cluster places'],
              ['activeRoutes', 'Active route'], ['plannedRoutes', 'All planned routes'],
              ['geofences', 'Geofences'], ['places', 'Places & depots'],
              ['tasks', 'Task destinations'], ['incidents', 'Incidents'],
              ['disruptions', 'Road disruptions'], ['weather', 'Weather'],
              ['buildings', 'Buildings'], ['traffic', 'Live traffic'],
            ] as [keyof MapLayers, string][]).map(([key, label]) => (
              <button key={key} className="layer-row" role="switch"
                      aria-checked={layers[key]}
                      disabled={key === 'traffic'}
                      title={key === 'traffic'
                        ? 'Live traffic is not available from the configured map provider'
                        : undefined}
                      onClick={() => setLayers({ ...layers, [key]: !layers[key] })}
                      style={key === 'traffic' ? { opacity: .5, cursor: 'not-allowed' } : undefined}>
                <span className="switch" data-on={layers[key]} />
                <span>{label}</span>
              </button>
            ))}
            <div className="muted" style={{ fontSize: 10.5, padding: '6px 6px 0', lineHeight: 1.45 }}>
              Live traffic is unavailable from the configured map provider. Known closures
              and weather cells are shown instead.
            </div>
          </div>
        )}

        {measure && (
          <div className="conn-banner" style={{ borderColor: 'var(--coral)' }}>
            <IconRuler size={14} />
            <span>
              {measure.length < 2
                ? 'Click points on the map to measure.'
                : `${(measureTotal / 1000).toFixed(2)} km across ${measure.length} points`}
            </span>
            <Button size="sm" variant="ghost" onClick={() => setMeasure([])}>Clear</Button>
            <Button size="sm" variant="ghost" onClick={() => setMeasure(null)}>Done</Button>
          </div>
        )}

        {s.connection !== 'live' && (
          <div className="conn-banner">
            <span className="freshness" data-state="STALE"><i className="dot" /></span>
            <span>Live connection interrupted — last update {relTime(s.lastEventAt, Date.now())}. Reconnecting…</span>
          </div>
        )}

        <div className="map-legend">
          <span className="eyebrow">Route</span>
          <span className="row"><i className="line" style={{ background: '#8A94A6' }} /> Planned</span>
          <span className="row"><i className="line" style={{ background: '#1E90FF', opacity: .4 }} /> Travelled</span>
          <span className="row"><i className="line" style={{ background: '#1E90FF' }} /> Remaining</span>
        </div>

        <div className="map-attrib">© OpenStreetMap contributors</div>

        <div className="kpi-strip">
          <KpiCell label="Active" value={kpis.activeVehicles} onClick={() => setStatus('all')} />
          <KpiCell label="Moving" value={kpis.moving} tone="good"
                   active={status === 'moving'} onClick={() => setStatus('moving')} />
          <KpiCell label="Idle" value={kpis.idle} tone="warn"
                   active={status === 'idle'} onClick={() => setStatus('idle')} />
          <KpiCell label="Stopped" value={kpis.stopped}
                   active={status === 'stopped'} onClick={() => setStatus('stopped')} />
          <KpiCell label="Offline" value={kpis.offline}
                   active={status === 'offline'} onClick={() => setStatus('offline')} />
          <KpiCell label="With alerts" value={kpis.withAlerts} tone={kpis.withAlerts ? 'danger' : undefined}
                   active={risk.has('alert')}
                   onClick={() => toggle(risk, setRisk, 'alert')} />
          <KpiCell label="Maintenance" value={kpis.inMaintenance}
                   active={risk.has('maintenance_due')}
                   onClick={() => toggle(risk, setRisk, 'maintenance_due')} />
          <KpiCell label="Today" value={kpis.distanceTodayKm.toFixed(0)} suffix=" km"
                   onClick={() => app.navigate('trips')} />
          <KpiCell label="Active tasks" value={kpis.activeTasks}
                   active={ops.has('active_task')}
                   onClick={() => toggle(ops, setOps, 'active_task')} />
          <KpiCell label="Late tasks" value={kpis.lateTasks} tone={kpis.lateTasks ? 'danger' : undefined}
                   active={ops.has('late_task')}
                   onClick={() => toggle(ops, setOps, 'late_task')} />
        </div>

        {selectedRow && !routeEditor && (
          <VehicleDrawer
            row={selectedRow}
            onClose={() => setSelected(undefined)}
            onEditRoute={(id) => setRouteEditor(id)}
            onCreateTask={() => setComposeFor(selectedRow.vehicle.id)}
            onAssignDriver={() => setAssignDriverFor(selectedRow.vehicle.id)}
            onMessage={() => setMessageFor(selectedRow.vehicle.id)}
          />
        )}

        {activeRoute && (
          <RouteEditor route={activeRoute} onClose={() => setRouteEditor(null)}
                       onPick={(fn) => { void fn; }} />
        )}

        {ctx && (
          <VehicleContextMenu row={rows.find((r) => r.vehicle.id === ctx.id)!}
                              x={ctx.x} y={ctx.y} onClose={() => setCtx(null)}
                              onSelect={() => select(ctx.id)}
                              onCreateTask={() => setComposeFor(ctx.id)}
                              onAssignDriver={() => setAssignDriverFor(ctx.id)}
                              onMessage={() => setMessageFor(ctx.id)} />
        )}
      </div>

      {saveViewOpen && (
        <SaveViewModal onClose={() => setSaveViewOpen(false)} onSave={(name) => {
          app.run(() => saveView(store, name, {
            status: status === 'all' ? [] : [status],
            operational: [...ops], risk: [...risk],
          }), `View “${name}” saved`);
          setSaveViewOpen(false);
        }} />
      )}

      {composeFor && (
        <QuickTaskModal vehicleId={composeFor} onClose={() => setComposeFor(null)} />
      )}
      {assignDriverFor && (
        <AssignDriverModal vehicleId={assignDriverFor} onClose={() => setAssignDriverFor(null)} />
      )}
      {messageFor && (
        <MessageModal vehicleId={messageFor} onClose={() => setMessageFor(null)} />
      )}
    </div>
  );
}

function KpiCell({ label, value, suffix, tone, onClick, active }: {
  label: string; value: number | string; suffix?: string;
  tone?: 'danger' | 'warn' | 'good'; onClick?: () => void; active?: boolean;
}) {
  return (
    <button className="kpi-cell" data-tone={tone} data-on={active} onClick={onClick}>
      <div className="label">{label}</div>
      <div className="value">{value}{suffix}</div>
    </button>
  );
}

function VehicleRow({ row, selected, now, onSelect }: {
  row: FleetRow; selected: boolean; now: number; onSelect: () => void;
}) {
  const v = row.vehicle;
  return (
    <button className="vrow" data-selected={selected} data-status={row.status}
            data-alert={row.worstAlert} onClick={onSelect}>
      <span className="stripe" />
      <span>
        <span className="line1">
          <span className="name">{v.name}</span>
          <span className="plate">{v.plate}</span>
        </span>
        <span className="line2">
          <Pill tone={row.status as Tone}>{titleCase(row.status)}</Pill>
          {row.driver
            ? <span className="truncate">{row.driver.fullName}</span>
            : <span className="dim">Unassigned</span>}
        </span>
        <span className="line3">
          <span className="freshness" data-state={row.freshness.state}>
            <i className="dot" />
            {row.freshness.state === 'NEVER' ? 'No fix'
              : `${row.freshness.state} · ${relTime(v.lastPositionAt ?? now, now)}`}
          </span>
          {row.task && (
            <>
              <span className="dim">·</span>
              <span className="mono truncate" title={row.task.title}>{row.task.reference}</span>
            </>
          )}
        </span>
      </span>
      <span className="right">
        <span className="speed">
          {Math.round(v.speedKph)}<small> km/h</small>
        </span>
        <span className="badges">
          {row.alertCount > 0 && (
            <Pill tone={(row.worstAlert ?? 'medium') as Tone}>
              {row.alertCount}
            </Pill>
          )}
          {['overdue', 'critical', 'due'].includes(row.maintenance) && (
            <Pill tone="maintenance">svc</Pill>
          )}
          {row.lateTaskCount > 0 && <Pill tone="danger">late</Pill>}
        </span>
      </span>
    </button>
  );
}

function VehicleDrawer({ row, onClose, onEditRoute, onCreateTask, onAssignDriver, onMessage }: {
  row: FleetRow; onClose: () => void; onEditRoute: (routeId: string) => void;
  onCreateTask: () => void; onAssignDriver: () => void; onMessage: () => void;
}) {
  const app = useApp();
  const { store, state: s } = app;
  const v = row.vehicle;
  const alerts = openAlertsFor(store, { vehicleId: v.id });
  const route = store.route(row.task?.routeId);
  const trip = s.trips.find((t) => t.vehicleId === v.id && t.status === 'active');
  const timeline = store.timelineFor('vehicle', v.id).slice(0, 8);
  const [confirmMaint, setConfirmMaint] = useState(false);

  return (
    <aside className="drawer" aria-label={`${v.name} details`}>
      <header className="drawer-head">
        <div className="grow">
          <div className="row" style={{ gap: 8 }}>
            <h2 style={{ fontSize: 16 }}>{v.name}</h2>
            <span className="mono muted">{v.plate}</span>
          </div>
          <div className="row" style={{ gap: 6, marginTop: 5 }}>
            <Pill tone={row.status as Tone}>{titleCase(row.status)}</Pill>
            <span className="freshness" data-state={row.freshness.state}>
              <i className="dot" />
              {row.freshness.state}
              {row.freshness.ageS != null && ` · ${relTime(v.lastPositionAt!, s.now)}`}
            </span>
          </div>
        </div>
        <button className="iconbtn" onClick={onClose} aria-label="Close panel">
          <IconClose size={15} />
        </button>
      </header>

      <div className="drawer-body">
        <section className="section">
          <h4>Telemetry</h4>
          <dl className="kv">
            <dt>Speed</dt><dd className="num">{Math.round(v.speedKph)} km/h</dd>
            <dt>Heading</dt><dd className="num">{Math.round(v.heading)}°</dd>
            <dt>Odometer</dt><dd className="num">{Math.round(v.odometerKm).toLocaleString()} km</dd>
            <dt>Location</dt><dd>{v.street || 'Off the named network'}</dd>
            <dt>GPS</dt><dd className="num">{v.satellites} satellites</dd>
            {v.fuelType === 'electric' && (
              <>
                <dt>Charge</dt><dd className="num">{Math.round(v.stateOfChargePct ?? 0)}%</dd>
                <dt>Range</dt><dd className="num">{Math.round(v.rangeKm ?? 0)} km</dd>
              </>
            )}
            <dt>Driver</dt>
            <dd>
              {row.driver
                ? <button className="row" style={{ gap: 6 }}
                          onClick={() => app.open('driver', row.driver!.id)}>
                    <Avatar name={row.driver.fullName} color={row.driver.avatarColor} size={20} />
                    <span style={{ color: 'var(--pulse)' }}>{row.driver.fullName}</span>
                  </button>
                : <span className="dim">No driver assigned</span>}
            </dd>
          </dl>
        </section>

        {row.task && (
          <section className="section">
            <h4>Current operation</h4>
            <button className="row" style={{ gap: 7, marginBottom: 7, width: '100%' }}
                    onClick={() => app.open('task', row.task!.id)}>
              <span className="mono" style={{ color: 'var(--pulse)' }}>{row.task.reference}</span>
              <Pill tone={row.task.status === 'delayed' ? 'danger' : 'info'}>
                {titleCase(row.task.status)}
              </Pill>
              <span className="grow truncate" style={{ textAlign: 'left' }}>{row.task.title}</span>
            </button>
            <dl className="kv">
              <dt>Destination</dt><dd className="truncate">{row.task.address}</dd>
              <dt>ETA</dt><dd className="num">{hm(row.task.eta)}</dd>
              <dt>SLA</dt>
              <dd>
                <Pill tone={row.task.slaState === 'breached' ? 'danger'
                  : row.task.slaState === 'at_risk' ? 'warn' : 'good'}>
                  {titleCase(row.task.slaState)}
                </Pill>
              </dd>
              {row.remainingKm != null && (
                <>
                  <dt>Remaining</dt><dd className="num">{row.remainingKm.toFixed(1)} km</dd>
                </>
              )}
            </dl>
            {row.routeProgressPct != null && (
              <div style={{ marginTop: 9 }}>
                <div className="row" style={{ fontSize: 11, marginBottom: 4 }}>
                  <span className="muted grow">Route progress</span>
                  <span className="mono">{row.routeProgressPct}%</span>
                </div>
                <Progress pct={row.routeProgressPct} />
                {(row.deviationM ?? 0) > 250 && (
                  <div className="muted" style={{ fontSize: 11, marginTop: 5 }}>
                    {Math.round(row.deviationM!)} m off the planned corridor.
                  </div>
                )}
              </div>
            )}
            {route && (
              <Button size="sm" onClick={() => onEditRoute(route.id)} style={{ marginTop: 9 }}>
                <IconRoute size={13} /> Edit route
              </Button>
            )}
          </section>
        )}

        {alerts.length > 0 && (
          <section className="section">
            <h4>Active alerts ({alerts.length})</h4>
            <div className="stack-sm">
              {alerts.slice(0, 5).map((a) => (
                <button key={a.id} className="row" style={{ gap: 7, width: '100%', textAlign: 'left' }}
                        onClick={() => app.open('alert', a.id)}>
                  <Pill tone={a.severity as Tone}>{a.severity}</Pill>
                  <span className="grow truncate">{a.title}</span>
                  {a.occurrences > 1 && <span className="mono dim">×{a.occurrences}</span>}
                </button>
              ))}
            </div>
          </section>
        )}

        {trip && (
          <section className="section">
            <h4>Active trip</h4>
            <dl className="kv">
              <dt>Reference</dt><dd className="mono">{trip.reference}</dd>
              <dt>Started</dt><dd>{hm(trip.startedAt)} from {trip.startAddress}</dd>
              <dt>Samples</dt><dd className="num">{trip.positions.length} GPS points</dd>
            </dl>
          </section>
        )}

        <section className="section">
          <h4>Recent activity</h4>
          <Timeline entries={timeline} />
        </section>
      </div>

      <footer className="drawer-foot">
        <Button variant="primary" size="sm" onClick={() => app.open('vehicle', v.id)}>
          Vehicle 360
        </Button>
        <Button size="sm" onClick={onCreateTask}><IconPlus size={13} /> Task</Button>
        <Button size="sm" onClick={onAssignDriver}>Assign driver</Button>
        <Button size="sm" onClick={onMessage}><IconMessage size={13} /> Message</Button>
        <Button size="sm" onClick={() => setConfirmMaint(true)}>
          <IconWrench size={13} /> Maintenance
        </Button>
        <Button size="sm" onClick={() => app.navigate('incidents', { compose: '1', vehicle: v.id })}>
          <IconAlert size={13} /> Incident
        </Button>
        {trip && (
          <Button size="sm" onClick={() => app.navigate('trips', { trip: trip.id })}>
            Replay trip
          </Button>
        )}
      </footer>

      {confirmMaint && (
        <Confirm
          title={`Raise a maintenance request for ${v.name}?`}
          body={`This creates a work order in the Requested state for ${v.name} (${v.plate}) at ${Math.round(v.odometerKm).toLocaleString()} km. The workshop queue and the vehicle's timeline both update.`}
          confirmLabel="Raise work order"
          onCancel={() => setConfirmMaint(false)}
          onConfirm={() => {
            app.navigate('maintenance', { compose: '1', vehicle: v.id });
            setConfirmMaint(false);
          }}
        />
      )}
    </aside>
  );
}

function VehicleContextMenu({ row, x, y, onClose, onSelect, onCreateTask, onAssignDriver, onMessage }: {
  row: FleetRow; x: number; y: number; onClose: () => void; onSelect: () => void;
  onCreateTask: () => void; onAssignDriver: () => void; onMessage: () => void;
}) {
  const app = useApp();
  const canDispatch = app.store.me.role === 'org_admin' || app.store.me.role === 'dispatcher';
  useEffect(() => {
    const close = () => onClose();
    window.addEventListener('click', close);
    return () => window.removeEventListener('click', close);
  }, [onClose]);
  const trip = app.state.trips.find((t) => t.vehicleId === row.vehicle.id);
  const item = (label: string, fn: () => void, enabled = true) => (
    <button className="ctx-item" disabled={!enabled}
            onClick={(e) => { e.stopPropagation(); fn(); onClose(); }}>
      {label}
    </button>
  );
  return (
    <div className="ctx-menu" style={{ left: Math.min(x, window.innerWidth - 220), top: y }}
         onClick={(e) => e.stopPropagation()}>
      {item('Centre on map', onSelect)}
      {item('Open Vehicle 360', () => app.open('vehicle', row.vehicle.id))}
      <div className="ctx-sep" />
      {item('Create task', onCreateTask, canDispatch)}
      {item('Assign driver', onAssignDriver, canDispatch)}
      {item('Send message', onMessage, canDispatch)}
      <div className="ctx-sep" />
      {item('Replay last trip', () => trip && app.navigate('trips', { trip: trip.id }), !!trip)}
      {item('Create maintenance request',
            () => app.navigate('maintenance', { compose: '1', vehicle: row.vehicle.id }),
            canDispatch)}
      {item('Report incident',
            () => app.navigate('incidents', { compose: '1', vehicle: row.vehicle.id }))}
    </div>
  );
}

function RouteEditor({ route, onClose }: {
  route: Route; onClose: () => void; onPick: (fn: (lon: number, lat: number) => void) => void;
}) {
  const app = useApp();
  const { store } = app;
  const [delta, setDelta] = useState<{ deltaM: number; deltaS: number } | null>(null);
  const [optimisation, setOptimisation] = useState<ReturnType<typeof previewOptimisation> | null>(null);
  const [adding, setAdding] = useState(false);

  const places = store.state.places.filter((p) => p.active);

  return (
    <aside className="drawer" aria-label="Route builder">
      <header className="drawer-head">
        <div className="grow">
          <h2 style={{ fontSize: 15 }}>Route builder</h2>
          <div className="muted" style={{ fontSize: 12 }}>{route.name}</div>
        </div>
        <button className="iconbtn" onClick={onClose} aria-label="Close"><IconClose size={15} /></button>
      </header>

      <div className="drawer-body">
        <section className="section">
          <h4>Summary</h4>
          <dl className="kv">
            <dt>Distance</dt><dd className="num">{(route.distanceM / 1000).toFixed(2)} km</dd>
            <dt>Duration</dt><dd className="num">{Math.round(route.durationS / 60)} min</dd>
            <dt>Stops</dt><dd className="num">{route.stops.length}</dd>
            <dt>Destination</dt><dd className="truncate">{route.destName}</dd>
          </dl>
          {delta && (
            <div className="banner" data-tone="info" style={{ marginTop: 10 }}>
              Route changed — {(delta.deltaM / 1000 >= 0 ? '+' : '')}
              {(delta.deltaM / 1000).toFixed(1)} km,{' '}
              {(delta.deltaS / 60 >= 0 ? '+' : '')}{Math.round(delta.deltaS / 60)} min
            </div>
          )}
        </section>

        <section className="section">
          <h4>Stops</h4>
          <div className="stack-sm">
            <div className="row" style={{ gap: 8, fontSize: 12 }}>
              <span className="mono dim">0</span>
              <span className="grow truncate">{route.originName}</span>
              <span className="dim">Origin</span>
            </div>
            {route.stops.sort((a, b) => a.sequence - b.sequence).map((stop, i) => (
              <div key={stop.id} className="row" style={{ gap: 8, fontSize: 12 }}>
                <span className="mono dim">{stop.sequence}</span>
                <span className="grow truncate" title={stop.name}>{stop.name}</span>
                <span className="dim mono">{hm(stop.plannedArrival)}</span>
                <button className="iconbtn" title="Move up" disabled={i === 0}
                        onClick={() => setDelta(app.run(() => moveStop(store, route.id, i, i - 1)) ?? null)}
                        style={{ width: 22, height: 22 }}>
                  <IconChevron size={11} className="" />
                </button>
                <button className="iconbtn" title="Remove stop"
                        onClick={() => setDelta(app.run(() => removeStop(store, route.id, stop.id),
                                                        `Stop removed`) ?? null)}
                        style={{ width: 22, height: 22 }}>
                  <IconTrash size={12} />
                </button>
              </div>
            ))}
            <div className="row" style={{ gap: 8, fontSize: 12 }}>
              <span className="mono dim">→</span>
              <span className="grow truncate">{route.destName}</span>
              <span className="dim">Destination</span>
            </div>
          </div>

          {adding ? (
            <div className="stack-sm" style={{ marginTop: 10 }}>
              <Field label="Add a stop">
                <select className="select" defaultValue=""
                        onChange={(e) => {
                          const p = places.find((x) => x.id === e.target.value);
                          if (!p) return;
                          setDelta(app.run(() => addStop(store, route.id, {
                            name: p.name, lat: p.lat, lon: p.lon, serviceMinutes: 5,
                          }), `${p.name} added to the route`) ?? null);
                          setAdding(false);
                        }}>
                  <option value="" disabled>Choose a place…</option>
                  {places.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </Field>
              <Button size="sm" variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
            </div>
          ) : (
            <Button size="sm" onClick={() => setAdding(true)} style={{ marginTop: 10 }}>
              <IconPlus size={13} /> Add stop
            </Button>
          )}
        </section>

        <section className="section">
          <h4>Optimisation</h4>
          {route.stops.length < 2 ? (
            <p className="muted" style={{ fontSize: 12, margin: 0 }}>
              Add at least two stops before optimising the order.
            </p>
          ) : optimisation ? (
            <div className="stack-sm">
              <dl className="kv">
                <dt>Current</dt><dd className="num">{Math.round(optimisation.beforeS / 60)} min</dd>
                <dt>Optimised</dt><dd className="num">{Math.round(optimisation.afterS / 60)} min</dd>
                <dt>Saving</dt>
                <dd className="num" style={{ color: 'var(--success)' }}>
                  {Math.round(optimisation.savedS / 60)} min
                </dd>
              </dl>
              <div className="row" style={{ gap: 7 }}>
                <Button size="sm" variant="primary" disabled={!optimisation.improved}
                        onClick={() => {
                          setDelta(app.run(() => applyOptimisation(store, route.id, optimisation.order),
                                           'Optimised order applied') ?? null);
                          setOptimisation(null);
                        }}>
                  Apply new order
                </Button>
                <Button size="sm" onClick={() => setOptimisation(null)}>Discard</Button>
              </div>
              {!optimisation.improved && (
                <p className="muted" style={{ fontSize: 11.5, margin: 0 }}>
                  The current order is already the quickest.
                </p>
              )}
            </div>
          ) : (
            <Button size="sm" onClick={() => setOptimisation(app.run(() =>
              previewOptimisation(store, route.id)) ?? null)}>
              Preview optimisation
            </Button>
          )}
        </section>

        <section className="section">
          <h4>Avoid a road</h4>
          <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>
            Exclude a road and the route recalculates around it. If no drivable
            alternative exists, the original route is kept.
          </p>
          <select className="select" defaultValue=""
                  onChange={(e) => {
                    const edge = store.graph.edges[Number(e.target.value)];
                    if (!edge) return;
                    const mid = edge.geom[Math.floor(edge.geom.length / 2)];
                    const result = app.run(() => avoidEdgeUnderPoint(store, route.id, mid[0], mid[1]),
                                           `Avoiding ${edge.name}`);
                    if (result) setDelta(result);
                    e.currentTarget.value = '';
                  }}>
            <option value="" disabled>Choose a road on this route…</option>
            {[...new Set(route.geometry.map((p) => store.graph.snap(p[0], p[1]).edge))]
              .filter((i) => i >= 0 && store.graph.edges[i]?.name)
              .slice(0, 12)
              .map((i) => (
                <option key={i} value={i}>{store.graph.edges[i].name}</option>
              ))}
          </select>
          {route.avoidEdges.length > 0 && (
            <Button size="sm" style={{ marginTop: 8 }} onClick={() => {
              route.avoidEdges = [];
              setDelta(app.run(() => recalculateRoute(store, route), 'Avoided roads cleared') ?? null);
            }}>
              Clear avoided roads ({route.avoidEdges.length})
            </Button>
          )}
        </section>
      </div>

      <footer className="drawer-foot">
        <Button variant="primary" size="sm" onClick={() => {
          app.toast('success', 'Route saved and sent to the driver');
          store.timeline({
            entityType: 'route', entityId: route.id, action: 'sent_to_driver',
            description: 'Route saved and sent to the driver app.',
            actorType: 'user', actorName: store.me.fullName,
          });
          const driver = store.driver(route.driverId);
          if (driver?.userId) {
            store.notify(driver.userId, {
              kind: 'route_changed', title: 'Route updated',
              body: `${route.name} — ${(route.distanceM / 1000).toFixed(1)} km, ${Math.round(route.durationS / 60)} min`,
            });
          }
          store.emitNow();
          onClose();
        }}>
          Save & send to driver
        </Button>
        <Button size="sm" onClick={onClose}>Close</Button>
      </footer>
    </aside>
  );
}

function SaveViewModal({ onClose, onSave }: { onClose: () => void; onSave: (n: string) => void }) {
  const [name, setName] = useState('');
  return (
    <Modal title="Save this view" onClose={onClose}
           subtitle="Saved views keep a filter combination one click away."
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant="primary" disabled={!name.trim()} onClick={() => onSave(name.trim())}>
               Save view
             </Button>
           </>}>
      <Field label="View name" hint="For example: Late deliveries, or Maintenance due today.">
        <input className="input" value={name} autoFocus
               onChange={(e) => setName(e.target.value)} placeholder="My critical vehicles" />
      </Field>
    </Modal>
  );
}

function QuickTaskModal({ vehicleId, onClose }: { vehicleId: string; onClose: () => void }) {
  const app = useApp();
  const { store, state: s } = app;
  const vehicle = store.vehicle(vehicleId)!;
  const [customerId, setCustomerId] = useState(s.customers[0]?.id ?? '');
  const [title, setTitle] = useState('Parcel delivery');
  const [priority, setPriority] = useState<'low' | 'normal' | 'high' | 'urgent'>('normal');
  const [slaMinutes, setSla] = useState(120);

  const customer = store.customer(customerId);
  const place = store.place(customer?.placeId);
  const preview = useMemo(() => {
    if (!place || vehicle.lat == null) return null;
    const r = store.graph.route([[vehicle.lon!, vehicle.lat], [place.lon, place.lat]]);
    return r.ok ? r : null;
  }, [place, vehicle, store]);

  return (
    <Modal title={`New task for ${vehicle.name}`} onClose={onClose}
           subtitle={`${vehicle.plate} · currently ${vehicle.street ?? 'on the network'}`}
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant="primary" disabled={!customer} onClick={() => {
               const t = app.run(() => createTask(store, {
                 title: `${title} — ${customer!.name}`, kind: 'delivery', priority,
                 customerId, slaMinutes, driverId: vehicle.driverId, vehicleId: vehicle.id,
                 scheduledFor: s.now + 15 * 60000,
               }), 'Task created and assigned');
               if (t) onClose();
             }}>
               Create & assign
             </Button>
           </>}>
      <div className="stack">
        <Field label="Customer">
          <select className="select" value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
            {s.customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Task">
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <div className="grid-2">
          <Field label="Priority">
            <select className="select" value={priority}
                    onChange={(e) => setPriority(e.target.value as typeof priority)}>
              <option value="low">Low</option><option value="normal">Normal</option>
              <option value="high">High</option><option value="urgent">Urgent</option>
            </select>
          </Field>
          <Field label="SLA (minutes)">
            <input className="input" type="number" min={15} max={480} value={slaMinutes}
                   onChange={(e) => setSla(Number(e.target.value))} />
          </Field>
        </div>
        {preview && (
          <div className="banner" data-tone="info">
            <IconRoute size={15} />
            <span>
              {(preview.distanceM / 1000).toFixed(1)} km · about {Math.round(preview.durationS / 60)} min
              {preview.streets.length > 0 && <> via {preview.streets.slice(0, 3).join(', ')}</>}
            </span>
          </div>
        )}
        {place && (
          <div className="muted" style={{ fontSize: 12 }}>
            Destination: {place.address}
          </div>
        )}
      </div>
    </Modal>
  );
}

function AssignDriverModal({ vehicleId, onClose }: { vehicleId: string; onClose: () => void }) {
  const app = useApp();
  const { store, state: s } = app;
  const vehicle = store.vehicle(vehicleId)!;
  const [driverId, setDriverId] = useState(vehicle.driverId ?? '');
  const activeTasks = s.tasks.filter(
    (t) => t.vehicleId === vehicle.id &&
           ['assigned', 'accepted', 'en_route', 'arrived', 'in_progress'].includes(t.status));

  return (
    <Modal title={`Assign a driver to ${vehicle.name}`} onClose={onClose}
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant="primary" onClick={() => {
               const res = app.run(
                 () => assignDriverToVehicle(store, vehicle.id, driverId || undefined),
                 'Driver assignment updated');
               if (res) onClose();
             }}>
               Confirm assignment
             </Button>
           </>}>
      <div className="stack">
        <Field label="Driver" hint="Assigning a driver who already has a vehicle moves them across.">
          <select className="select" value={driverId} onChange={(e) => setDriverId(e.target.value)}>
            <option value="">No driver</option>
            {s.drivers.map((d) => {
              const other = s.vehicles.find((v) => v.driverId === d.id && v.id !== vehicle.id);
              return (
                <option key={d.id} value={d.id}>
                  {d.fullName} — {titleCase(d.status)}
                  {other ? ` (currently on ${other.name})` : ''}
                </option>
              );
            })}
          </select>
        </Field>
        {activeTasks.length > 0 && (
          <div className="banner" data-tone="warn">
            <IconAlert size={15} />
            <span>
              {activeTasks.length} active task{activeTasks.length === 1 ? '' : 's'} on this vehicle
              will move to the new driver.
            </span>
          </div>
        )}
      </div>
    </Modal>
  );
}

function MessageModal({ vehicleId, onClose }: { vehicleId: string; onClose: () => void }) {
  const app = useApp();
  const { store } = app;
  const vehicle = store.vehicle(vehicleId)!;
  const driver = store.driver(vehicle.driverId);
  const [text, setText] = useState('');
  return (
    <Modal title={driver ? `Message ${driver.fullName}` : 'No driver assigned'}
           onClose={onClose}
           subtitle={driver ? `Delivered to the driver app on ${vehicle.name}` : undefined}
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant="primary" disabled={!driver || !text.trim()} onClick={() => {
               store.notify(driver!.userId!, {
                 kind: 'announcement', title: `Message from ${store.me.fullName}`, body: text,
               });
               store.timeline({
                 entityType: 'driver', entityId: driver!.id, action: 'message_sent',
                 description: `Message sent: “${text}”`,
                 actorType: 'user', actorName: store.me.fullName,
               });
               store.emitNow();
               app.toast('success', `Message sent to ${driver!.fullName}`);
               onClose();
             }}>
               Send message
             </Button>
           </>}>
      {driver ? (
        <Field label="Message">
          <textarea className="textarea" value={text} autoFocus
                    onChange={(e) => setText(e.target.value)}
                    placeholder="Customer has moved the delivery window to 15:00." />
        </Field>
      ) : (
        <p className="muted" style={{ margin: 0 }}>
          {vehicle.name} has no driver assigned, so there is nobody to message.
          Assign a driver first.
        </p>
      )}
    </Modal>
  );
}
