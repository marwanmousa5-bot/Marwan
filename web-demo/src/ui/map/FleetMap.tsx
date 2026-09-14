// The live map. Vehicle positions are interpolated between engine ticks so
// markers glide rather than jump, and clustering keeps the picture readable
// when vehicles bunch up. Worst status wins inside a cluster.

import { useEffect, useMemo, useRef } from 'react';
import type { MlMap, MlMarker } from './maplibre';
import { OPS, VEHICLE_COLORS, buildStyle, type BaseData } from './style';
import { circlePolygon } from '../../engine/geo';
import type { FleetRow } from '../../engine/selectors';
import type {
  Disruption, Geofence, Incident, Place, Route, Severity, Task, WeatherCell,
} from '../../engine/types';

export interface MapLayers {
  vehicles: boolean; clusters: boolean; activeRoutes: boolean; plannedRoutes: boolean;
  geofences: boolean; places: boolean; tasks: boolean; incidents: boolean;
  traffic: boolean; weather: boolean; disruptions: boolean; buildings: boolean;
}

export const DEFAULT_LAYERS: MapLayers = {
  vehicles: true, clusters: true, activeRoutes: true, plannedRoutes: true,
  geofences: true, places: true, tasks: true, incidents: false,
  traffic: false, weather: false, disruptions: true, buildings: true,
};

export interface PlaybackFrame {
  lat: number; lon: number; heading: number; speedKph: number;
  path: [number, number][]; travelled: [number, number][];
  events: { lat: number; lon: number; kind: string; severity: string }[];
}

interface Props {
  base: BaseData;
  theme: 'light' | 'dark';
  rows: FleetRow[];
  routes: Route[];
  geofences: Geofence[];
  places: Place[];
  tasks: Task[];
  incidents: Incident[];
  disruptions: Disruption[];
  weather: WeatherCell[];
  layers: MapLayers;
  selectedVehicleId?: string;
  focus?: { lat: number; lon: number; zoom?: number; key: number };
  fitKey?: number;
  playback?: PlaybackFrame | null;
  draftRoute?: { geometry: [number, number][]; stops: { lat: number; lon: number; name: string }[] } | null;
  measure?: [number, number][] | null;
  onSelectVehicle: (id: string) => void;
  onMapClick?: (lon: number, lat: number) => void;
  onContextVehicle?: (id: string, x: number, y: number) => void;
  onReady?: (map: MlMap) => void;
}

const rank: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 };

export function FleetMap(props: Props) {
  const holder = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const ready = useRef(false);
  const markers = useRef(new Map<string, { marker: MlMarker; el: HTMLElement }>());
  const anim = useRef(new Map<string, {
    from: [number, number]; to: [number, number]; fromH: number; toH: number;
    start: number; dur: number;
  }>());
  const raf = useRef<number | null>(null);
  const propsRef = useRef(props);
  propsRef.current = props;

  // --- create the map once -------------------------------------------------
  useEffect(() => {
    const ml = window.maplibregl;
    if (!ml || !holder.current) return;
    const map = new ml.Map({
      container: holder.current,
      style: buildStyle(props.theme, props.base),
      center: [24.9443, 60.1716],
      zoom: 15.2,
      minZoom: 12,
      maxZoom: 18,
      attributionControl: false,
      dragRotate: true,
      pitchWithRotate: true,
    });
    mapRef.current = map;
    map.on('load', () => {
      ready.current = true;
      installOverlays(map);
      syncOverlays(map, propsRef.current);
      // open on the whole operating area rather than a guessed centre
      const pts = propsRef.current.rows.filter((r) => r.vehicle.lat != null);
      if (pts.length) {
        const b = new ml.LngLatBounds();
        pts.forEach((r) => b.extend([r.vehicle.lon!, r.vehicle.lat!]));
        map.fitBounds(b, { padding: { top: 80, bottom: 120, left: 70, right: 70 },
                           duration: 0, maxZoom: 16 });
      }
      props.onReady?.(map);
    });
    map.on('click', (e: never) => {
      const ev = e as unknown as { lngLat: { lng: number; lat: number } };
      propsRef.current.onMapClick?.(ev.lngLat.lng, ev.lngLat.lat);
    });
    return () => {
      ready.current = false;
      markers.current.forEach((m) => m.marker.remove());
      markers.current.clear();
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- theme changes rebuild the style, then overlays are reinstalled ------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready.current) return;
    map.setStyle(buildStyle(props.theme, props.base));
    map.once('styledata', () => {
      installOverlays(map);
      syncOverlays(map, propsRef.current);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.theme]);

  // --- overlay data --------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (map && ready.current) syncOverlays(map, props);
  });

  // --- vehicle markers with smooth interpolation ---------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready.current) return;
    const now = performance.now();
    const seen = new Set<string>();

    props.rows.forEach((row) => {
      const v = row.vehicle;
      if (v.lat == null || v.lon == null) return;
      if (!props.layers.vehicles) return;
      seen.add(v.id);
      let entry = markers.current.get(v.id);
      if (!entry) {
        const el = document.createElement('button');
        el.className = 'veh-marker';
        el.type = 'button';
        el.setAttribute('aria-label', `${v.name} ${v.plate}`);
        el.addEventListener('click', (e) => {
          e.stopPropagation();
          propsRef.current.onSelectVehicle(v.id);
        });
        el.addEventListener('contextmenu', (e) => {
          e.preventDefault();
          e.stopPropagation();
          propsRef.current.onContextVehicle?.(v.id, e.clientX, e.clientY);
        });
        const marker = new window.maplibregl.Marker({ element: el, rotationAlignment: 'map' })
          .setLngLat([v.lon, v.lat]).addTo(map);
        entry = { marker, el };
        markers.current.set(v.id, entry);
        anim.current.set(v.id, {
          from: [v.lon, v.lat], to: [v.lon, v.lat],
          fromH: v.heading, toH: v.heading, start: now, dur: 1,
        });
      }
      const a = anim.current.get(v.id)!;
      if (a.to[0] !== v.lon || a.to[1] !== v.lat) {
        const current = interpolate(a, now);
        a.from = current.pos;
        a.fromH = current.heading;
        a.to = [v.lon, v.lat];
        a.toH = v.heading;
        a.start = now;
        a.dur = 900;
      }
      paintMarker(entry.el, row, props.selectedVehicleId === v.id);
    });

    markers.current.forEach((entry, id) => {
      if (!seen.has(id)) {
        entry.marker.remove();
        markers.current.delete(id);
        anim.current.delete(id);
      }
    });
  }, [props.rows, props.selectedVehicleId, props.layers.vehicles]);

  // --- animation loop ------------------------------------------------------
  useEffect(() => {
    const step = () => {
      const now = performance.now();
      markers.current.forEach((entry, id) => {
        const a = anim.current.get(id);
        if (!a) return;
        const { pos, heading } = interpolate(a, now);
        entry.marker.setLngLat(pos);
        const arrow = entry.el.firstElementChild as HTMLElement | null;
        if (arrow) arrow.style.transform = `rotate(${heading}deg)`;
      });
      raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => { if (raf.current) cancelAnimationFrame(raf.current); };
  }, []);

  // --- imperative camera ---------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !props.focus) return;
    map.flyTo({
      center: [props.focus.lon, props.focus.lat],
      zoom: props.focus.zoom ?? Math.max(map.getZoom(), 16),
      duration: 900, essential: true,
    });
  }, [props.focus?.key]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !props.fitKey) return;
    const pts = props.rows.filter((r) => r.vehicle.lat != null);
    if (!pts.length) return;
    const b = new window.maplibregl.LngLatBounds();
    pts.forEach((r) => b.extend([r.vehicle.lon!, r.vehicle.lat!]));
    map.fitBounds(b, { padding: { top: 70, bottom: 110, left: 70, right: 70 }, duration: 800 });
  }, [props.fitKey]);

  const legend = useMemo(() => props.layers, [props.layers]);
  void legend;

  return <div ref={holder} className="map-canvas" />;
}

function interpolate(
  a: { from: [number, number]; to: [number, number]; fromH: number; toH: number; start: number; dur: number },
  now: number,
): { pos: [number, number]; heading: number } {
  const t = Math.min(1, (now - a.start) / a.dur);
  const e = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;   // ease-in-out
  let dh = ((a.toH - a.fromH + 540) % 360) - 180;
  return {
    pos: [a.from[0] + (a.to[0] - a.from[0]) * e, a.from[1] + (a.to[1] - a.from[1]) * e],
    heading: a.fromH + dh * e,
  };
}

function paintMarker(el: HTMLElement, row: FleetRow, selected: boolean) {
  const colour = VEHICLE_COLORS[row.status] ?? VEHICLE_COLORS.stopped;
  const alertTone = row.worstAlert;
  const critical = alertTone === 'critical';
  el.dataset.selected = String(selected);
  el.dataset.status = row.status;
  el.innerHTML = `
    <span class="veh-arrow" style="transform:rotate(${row.vehicle.heading}deg)">
      <svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true">
        <circle cx="15" cy="15" r="12.5" fill="${colour}" fill-opacity="${row.status === 'offline' ? 0.45 : 1}"
                stroke="${selected ? '#1E90FF' : 'rgba(255,255,255,.9)'}" stroke-width="${selected ? 3 : 1.8}"/>
        <path d="M15 6.5 L20 19.5 L15 16.5 L10 19.5 Z" fill="#fff" fill-opacity=".97"/>
      </svg>
    </span>
    ${alertTone ? `<span class="veh-alert" data-crit="${critical}">${row.alertCount}</span>` : ''}
    ${row.status === 'maintenance' ? '<span class="veh-badge veh-wrench">&#9881;</span>' : ''}
    ${row.freshness.state === 'LIVE' && row.status === 'moving' ? '<span class="veh-pulse"></span>' : ''}
    <span class="veh-name">${escapeHtml(row.vehicle.name)}</span>
  `;
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!
  ));
}

// --------------------------------------------------------------------------
// Overlay sources and layers
// --------------------------------------------------------------------------
const EMPTY = { type: 'FeatureCollection', features: [] };

function installOverlays(map: MlMap) {
  const add = (id: string, src: Record<string, unknown> = {}) => {
    if (!map.getSource(id)) {
      map.addSource(id, { type: 'geojson', data: EMPTY, ...src });
    }
  };
  add('ops-geofence');
  add('ops-weather');
  add('ops-disruption');
  add('ops-route-planned');
  add('ops-route-travelled');
  add('ops-route-remaining');
  add('ops-draft');
  add('ops-measure');
  add('ops-places', { cluster: true, clusterRadius: 46, clusterMaxZoom: 15 });
  add('ops-tasks');
  add('ops-incidents');
  add('ops-stops');
  add('ops-playback');
  add('ops-playback-events');

  const L = (layer: Record<string, unknown>) => {
    if (!map.getLayer(layer.id as string)) map.addLayer(layer);
  };

  // geofences
  L({ id: 'gf-fill', type: 'fill', source: 'ops-geofence',
      paint: { 'fill-color': ['get', 'colour'], 'fill-opacity': 0.055 } });
  L({ id: 'gf-line', type: 'line', source: 'ops-geofence',
      paint: { 'line-color': ['get', 'colour'], 'line-width': 1.8,
               'line-dasharray': [3, 2] } });
  L({ id: 'gf-label', type: 'symbol', source: 'ops-geofence', minzoom: 13.5,
      layout: { 'text-field': ['get', 'name'], 'text-font': ['NotoSans-Regular'],
                'text-size': 10, 'symbol-placement': 'point',
                'text-max-width': 10, 'text-allow-overlap': false,
                'text-ignore-placement': false, 'symbol-avoid-edges': true },
      paint: { 'text-color': ['get', 'colour'], 'text-halo-color': 'rgba(0,0,0,.6)',
               'text-halo-width': 1.2 } });

  // weather + disruptions
  L({ id: 'wx-fill', type: 'fill', source: 'ops-weather',
      paint: { 'fill-color': ['get', 'colour'], 'fill-opacity': 0.16 } });
  L({ id: 'dsr-road', type: 'line', source: 'ops-disruption',
      filter: ['==', ['geometry-type'], 'LineString'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': ['get', 'colour'], 'line-width':
                 ['interpolate', ['exponential', 1.5], ['zoom'], 13, 3, 16, 9, 18, 20],
               'line-opacity': 0.8 } });
  L({ id: 'dsr-point', type: 'circle', source: 'ops-disruption',
      filter: ['==', ['geometry-type'], 'Point'],
      paint: { 'circle-radius': 7, 'circle-color': ['get', 'colour'],
               'circle-stroke-width': 2, 'circle-stroke-color': 'rgba(255,255,255,.9)' } });
  L({ id: 'dsr-label', type: 'symbol', source: 'ops-disruption', minzoom: 14,
      filter: ['==', ['geometry-type'], 'Point'],
      layout: { 'text-field': ['get', 'label'], 'text-font': ['NotoSans-Bold'],
                'text-size': 9.5, 'text-anchor': 'top', 'text-offset': [0, 0.9],
                'text-max-width': 12 },
      paint: { 'text-color': ['get', 'colour'], 'text-halo-color': 'rgba(0,0,0,.55)',
               'text-halo-width': 1.3 } });

  // routes
  L({ id: 'rt-planned', type: 'line', source: 'ops-route-planned',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': OPS.planned, 'line-width': 3, 'line-opacity': 0.55,
               'line-dasharray': [2, 2] } });
  L({ id: 'rt-remaining', type: 'line', source: 'ops-route-remaining',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': OPS.remaining, 'line-width': 4, 'line-opacity': 0.9 } });
  L({ id: 'rt-travelled', type: 'line', source: 'ops-route-travelled',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': OPS.travelled, 'line-width': 4, 'line-opacity': 0.32 } });
  L({ id: 'rt-draft', type: 'line', source: 'ops-draft',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#FF6B35', 'line-width': 4, 'line-opacity': 0.95 } });
  L({ id: 'measure-line', type: 'line', source: 'ops-measure',
      paint: { 'line-color': '#FF6B35', 'line-width': 2, 'line-dasharray': [2, 1.5] } });
  L({ id: 'measure-pt', type: 'circle', source: 'ops-measure',
      filter: ['==', ['geometry-type'], 'Point'],
      paint: { 'circle-radius': 4, 'circle-color': '#FF6B35',
               'circle-stroke-width': 2, 'circle-stroke-color': '#fff' } });

  // playback
  L({ id: 'pb-line', type: 'line', source: 'ops-playback',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': OPS.playback, 'line-width': 3.5, 'line-opacity': 0.9 } });
  L({ id: 'pb-events', type: 'circle', source: 'ops-playback-events',
      paint: { 'circle-radius': 6, 'circle-color': ['get', 'colour'],
               'circle-stroke-width': 2, 'circle-stroke-color': '#fff' } });

  // places (clustered)
  L({ id: 'pl-cluster', type: 'circle', source: 'ops-places',
      filter: ['has', 'point_count'],
      paint: { 'circle-color': 'rgba(126,140,158,.55)',
               'circle-radius': ['step', ['get', 'point_count'], 9, 5, 12, 12, 16],
               'circle-stroke-width': 1.2, 'circle-stroke-color': 'rgba(255,255,255,.5)' } });
  L({ id: 'pl-cluster-count', type: 'symbol', source: 'ops-places',
      filter: ['has', 'point_count'],
      layout: { 'text-field': ['get', 'point_count_abbreviated'],
                'text-font': ['NotoSans-Bold'], 'text-size': 9.5 },
      paint: { 'text-color': '#fff' } });
  L({ id: 'pl-point', type: 'circle', source: 'ops-places',
      filter: ['!', ['has', 'point_count']],
      paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 13, 2.5, 16, 4.5],
               'circle-color': ['get', 'colour'], 'circle-opacity': 0.75,
               'circle-stroke-width': 1, 'circle-stroke-color': 'rgba(255,255,255,.55)' } });
  L({ id: 'pl-label', type: 'symbol', source: 'ops-places', minzoom: 15.8,
      filter: ['!', ['has', 'point_count']],
      layout: { 'text-field': ['get', 'name'], 'text-font': ['NotoSans-Regular'],
                'text-size': 10.5, 'text-anchor': 'top', 'text-offset': [0, 0.7],
                'text-max-width': 9 },
      paint: { 'text-color': '#8A94A6', 'text-halo-color': 'rgba(0,0,0,.55)',
               'text-halo-width': 1.2 } });

  // tasks, stops, incidents
  L({ id: 'task-point', type: 'circle', source: 'ops-tasks',
      paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 13, 4, 16, 6.5],
               'circle-color': ['get', 'colour'],
               'circle-stroke-width': 1.6, 'circle-stroke-color': 'rgba(255,255,255,.85)' } });
  L({ id: 'task-label', type: 'symbol', source: 'ops-tasks', minzoom: 15.4,
      layout: { 'text-field': ['get', 'ref'], 'text-font': ['NotoSans-Bold'],
                'text-size': 9.5, 'text-anchor': 'top', 'text-offset': [0, 0.9] },
      paint: { 'text-color': '#F5A623', 'text-halo-color': 'rgba(0,0,0,.6)',
               'text-halo-width': 1.2 } });
  L({ id: 'stop-point', type: 'circle', source: 'ops-stops',
      paint: { 'circle-radius': 8, 'circle-color': '#fff',
               'circle-stroke-width': 3, 'circle-stroke-color': OPS.remaining } });
  L({ id: 'stop-label', type: 'symbol', source: 'ops-stops',
      layout: { 'text-field': ['get', 'seq'], 'text-font': ['NotoSans-Bold'],
                'text-size': 10 },
      paint: { 'text-color': '#0B63C4' } });
  L({ id: 'inc-point', type: 'circle', source: 'ops-incidents',
      paint: { 'circle-radius': 7, 'circle-color': OPS.incident,
               'circle-stroke-width': 2, 'circle-stroke-color': 'rgba(255,255,255,.85)' } });
}

function syncOverlays(map: MlMap, p: Props) {
  const set = (id: string, data: unknown) => {
    const src = map.getSource(id);
    if (src) src.setData(data);
  };
  const vis = (layer: string, on: boolean) => {
    if (map.getLayer(layer)) {
      map.setLayoutProperty(layer, 'visibility', on ? 'visible' : 'none');
    }
  };

  // geofences
  set('ops-geofence', {
    type: 'FeatureCollection',
    features: p.geofences.filter((g) => g.active).map((g) => ({
      type: 'Feature',
      properties: { name: g.name, colour: g.restricted ? OPS.restricted : g.colour },
      geometry: {
        type: 'Polygon',
        coordinates: [g.kind === 'circle'
          ? circlePolygon(g.centreLon!, g.centreLat!, g.radiusM ?? 100)
          : (g.polygon ?? [])],
      },
    })),
  });
  ['gf-fill', 'gf-line', 'gf-label'].forEach((l) => vis(l, p.layers.geofences));

  // weather
  set('ops-weather', {
    type: 'FeatureCollection',
    features: p.weather.filter((w) => w.condition !== 'clear').map((w) => ({
      type: 'Feature',
      properties: {
        colour: w.condition === 'fog' ? '#8A94A6'
          : w.condition === 'snow' || w.condition === 'sleet' ? '#A8C8E8' : OPS.weather,
      },
      geometry: { type: 'Polygon', coordinates: [circlePolygon(w.lon, w.lat, w.radiusM, 40)] },
    })),
  });
  vis('wx-fill', p.layers.weather);

  // disruptions
  set('ops-disruption', {
    type: 'FeatureCollection',
    features: p.disruptions.filter((d) => d.active).flatMap((d) => {
      const colour = d.kind === 'closure' ? OPS.incident
        : d.kind === 'congestion' ? OPS.disruption : OPS.weather;
      const label = d.kind === 'closure' ? 'CLOSED'
        : d.kind === 'congestion' ? `+${Math.round(d.delayMinutes)} MIN` : 'WEATHER';
      const feats: unknown[] = [{
        type: 'Feature', properties: { title: d.title, colour, label },
        geometry: { type: 'Point', coordinates: [d.lon, d.lat] },
      }];
      if (d.geometry?.length) {
        feats.unshift({
          type: 'Feature', properties: { title: d.title, colour, label },
          geometry: { type: 'LineString', coordinates: d.geometry },
        });
      }
      return feats;
    }),
  });
  ['dsr-road', 'dsr-point', 'dsr-label'].forEach((l) => vis(l, p.layers.disruptions));

  // routes: planned vs travelled vs remaining
  const selected = p.rows.find((r) => r.vehicle.id === p.selectedVehicleId);
  const activeRoutes = p.routes.filter((r) => r.active && r.geometry.length > 1);
  const planned: unknown[] = [];
  const travelled: unknown[] = [];
  const remaining: unknown[] = [];
  const stops: unknown[] = [];

  activeRoutes.forEach((r) => {
    const isSelected = selected?.vehicle.id === r.vehicleId;
    if (!isSelected && !p.layers.plannedRoutes) return;
    planned.push({
      type: 'Feature', properties: {},
      geometry: { type: 'LineString', coordinates: r.geometry },
    });
    if (isSelected) {
      const v = selected!.vehicle;
      if (v.lat != null) {
        const idx = nearestIndex(r.geometry, v.lon!, v.lat);
        travelled.push({
          type: 'Feature', properties: {},
          geometry: { type: 'LineString', coordinates: r.geometry.slice(0, idx + 1) },
        });
        remaining.push({
          type: 'Feature', properties: {},
          geometry: {
            type: 'LineString',
            coordinates: [[v.lon!, v.lat], ...r.geometry.slice(idx + 1)],
          },
        });
      }
      r.stops.forEach((s) => stops.push({
        type: 'Feature', properties: { seq: String(s.sequence) },
        geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
      }));
    }
  });

  set('ops-route-planned', { type: 'FeatureCollection', features: planned });
  set('ops-route-travelled', { type: 'FeatureCollection', features: travelled });
  set('ops-route-remaining', { type: 'FeatureCollection', features: remaining });
  set('ops-stops', { type: 'FeatureCollection', features: stops });
  vis('rt-planned', p.layers.plannedRoutes || p.layers.activeRoutes);
  vis('rt-travelled', p.layers.activeRoutes);
  vis('rt-remaining', p.layers.activeRoutes);

  // places
  const placeColour = (c: string) =>
    c === 'depot' ? OPS.depot : c === 'workshop' ? OPS.workshop
      : c === 'fuel_station' ? OPS.fuel : OPS.place;
  set('ops-places', {
    type: 'FeatureCollection',
    features: p.places.filter((pl) => pl.active).map((pl) => ({
      type: 'Feature',
      properties: { name: pl.name, colour: placeColour(pl.category), category: pl.category },
      geometry: { type: 'Point', coordinates: [pl.lon, pl.lat] },
    })),
  });
  ['pl-point', 'pl-label'].forEach((l) => vis(l, p.layers.places));
  ['pl-cluster', 'pl-cluster-count'].forEach(
    (l) => vis(l, p.layers.places && p.layers.clusters));

  // tasks
  set('ops-tasks', {
    type: 'FeatureCollection',
    features: p.tasks.map((t) => ({
      type: 'Feature',
      properties: {
        ref: t.reference,
        colour: t.slaState === 'breached' ? OPS.incident
          : t.priority === 'urgent' ? OPS.taskUrgent : OPS.task,
      },
      geometry: { type: 'Point', coordinates: [t.lon, t.lat] },
    })),
  });
  ['task-point', 'task-label'].forEach((l) => vis(l, p.layers.tasks));

  set('ops-incidents', {
    type: 'FeatureCollection',
    features: p.incidents.filter((i) => i.lat != null).map((i) => ({
      type: 'Feature', properties: { ref: i.reference },
      geometry: { type: 'Point', coordinates: [i.lon!, i.lat!] },
    })),
  });
  vis('inc-point', p.layers.incidents);

  // draft route being edited
  set('ops-draft', p.draftRoute?.geometry.length
    ? { type: 'FeatureCollection', features: [{
        type: 'Feature', properties: {},
        geometry: { type: 'LineString', coordinates: p.draftRoute.geometry } }] }
    : EMPTY);

  // measurement
  set('ops-measure', p.measure?.length
    ? { type: 'FeatureCollection', features: [
        ...(p.measure.length > 1 ? [{
          type: 'Feature', properties: {},
          geometry: { type: 'LineString', coordinates: p.measure },
        }] : []),
        ...p.measure.map((c) => ({
          type: 'Feature', properties: {},
          geometry: { type: 'Point', coordinates: c },
        })),
      ] }
    : EMPTY);

  // playback
  set('ops-playback', p.playback
    ? { type: 'FeatureCollection', features: [
        { type: 'Feature', properties: {},
          geometry: { type: 'LineString', coordinates: p.playback.path } }] }
    : EMPTY);
  set('ops-playback-events', p.playback
    ? { type: 'FeatureCollection', features: p.playback.events.map((e) => ({
        type: 'Feature',
        properties: {
          colour: e.severity === 'high' ? OPS.incident
            : e.severity === 'medium' ? OPS.task : OPS.travelled,
        },
        geometry: { type: 'Point', coordinates: [e.lon, e.lat] },
      })) }
    : EMPTY);

  vis('buildings', p.layers.buildings);
}

function nearestIndex(geom: [number, number][], lon: number, lat: number): number {
  let best = 0;
  let bd = Infinity;
  for (let i = 0; i < geom.length; i++) {
    const dx = geom[i][0] - lon;
    const dy = geom[i][1] - lat;
    const d = dx * dx + dy * dy;
    if (d < bd) { bd = d; best = i; }
  }
  return best;
}

export function worstSeverity(list: (Severity | undefined)[]): Severity | undefined {
  let worst: Severity | undefined;
  list.forEach((s) => {
    if (!s) return;
    if (!worst || rank[s] > rank[worst]) worst = s;
  });
  return worst;
}
