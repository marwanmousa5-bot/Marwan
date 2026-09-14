// The MapLibre style. Colours come from the FleetBeat palette so the map is
// part of the product rather than a third-party rectangle inside it.

export interface BaseData {
  roads: unknown; paths: unknown; rail: unknown;
  buildings: unknown; water: unknown; landuse: unknown;
}

const LIGHT = {
  bg: '#E4EAF1', water: '#B7D3EC', park: '#D7E7D2', land: '#DCE3EB',
  building: '#CDD6E1', buildingLine: '#BAC5D3',
  road: '#FFFFFF', roadCase: '#B9C5D3', rail: '#B4BCC7', path: '#D3D9E1',
  label: '#333E4D', halo: '#FFFFFF', poi: '#5F6B78',
};

const DARK = {
  bg: '#0A0D12', water: '#0F1E2B', park: '#132018', land: '#11151A',
  building: '#171C23', buildingLine: '#212832',
  road: '#2B323B', roadCase: '#14181E', rail: '#242932', path: '#1C2129',
  label: '#93A0B1', halo: '#080A0E', poi: '#6B7889',
};

export function buildStyle(theme: 'light' | 'dark', data: BaseData) {
  const c = theme === 'dark' ? DARK : LIGHT;
  const width = (m = 1) => [
    'interpolate', ['exponential', 1.5], ['zoom'],
    12, 0.5 * m, 14, 1.6 * m, 16, 5.5 * m, 18, 17 * m,
  ];
  return {
    version: 8,
    glyphs: 'fbfont://{fontstack}/{range}',
    sources: {
      landuse: { type: 'geojson', data: data.landuse },
      water: { type: 'geojson', data: data.water },
      buildings: { type: 'geojson', data: data.buildings },
      paths: { type: 'geojson', data: data.paths },
      rail: { type: 'geojson', data: data.rail },
      roads: { type: 'geojson', data: data.roads },
    },
    layers: [
      { id: 'bg', type: 'background', paint: { 'background-color': c.bg } },
      { id: 'landuse', type: 'fill', source: 'landuse',
        paint: { 'fill-color': ['match', ['get', 'c'],
                                'park', c.park, 'grass', c.park, 'forest', c.park,
                                'cemetery', c.park, c.land],
                 'fill-opacity': 0.85 } },
      { id: 'water', type: 'fill', source: 'water', paint: { 'fill-color': c.water } },
      { id: 'buildings', type: 'fill', source: 'buildings', minzoom: 14.5,
        paint: { 'fill-color': c.building, 'fill-outline-color': c.buildingLine,
                 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 14.5, 0.35, 17, 0.92] } },
      { id: 'paths', type: 'line', source: 'paths', minzoom: 15.5,
        paint: { 'line-color': c.path, 'line-width': width(0.24),
                 'line-dasharray': [2, 2] } },
      { id: 'rail', type: 'line', source: 'rail', minzoom: 13,
        paint: { 'line-color': c.rail, 'line-width': width(0.32) } },
      { id: 'roads-case', type: 'line', source: 'roads', minzoom: 13,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': c.roadCase, 'line-width': width(1.4) } },
      { id: 'roads-minor', type: 'line', source: 'roads',
        filter: ['>=', ['get', 'r'], 5],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': c.road, 'line-width': width(0.85) } },
      { id: 'roads-major', type: 'line', source: 'roads',
        filter: ['<', ['get', 'r'], 5],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': c.road, 'line-width': width(1.18) } },
      { id: 'road-labels', type: 'symbol', source: 'roads', minzoom: 14.5,
        filter: ['!=', ['get', 'n'], ''],
        layout: { 'symbol-placement': 'line', 'text-field': ['get', 'n'],
                  'text-font': ['NotoSans-Regular'],
                  'text-size': ['interpolate', ['linear'], ['zoom'], 14.5, 9.5, 18, 12.5],
                  'text-letter-spacing': 0.02, 'symbol-spacing': 260 },
        paint: { 'text-color': c.label, 'text-halo-color': c.halo,
                 'text-halo-width': 1.4 } },
    ],
  };
}

/** Operational overlay colours, shared by the map and the legend. */
export const OPS = {
  planned: '#8A94A6',
  travelled: '#1E90FF',
  remaining: '#1E90FF',
  geofence: '#1E90FF',
  restricted: '#E74C3C',
  disruption: '#FF6B35',
  weather: '#5EA9E8',
  task: '#F5A623',
  taskUrgent: '#FF6B35',
  incident: '#E74C3C',
  place: '#7E8C9E',
  depot: '#1E90FF',
  workshop: '#9B6BFF',
  fuel: '#2ECC71',
  playback: '#FF6B35',
};

export const VEHICLE_COLORS: Record<string, string> = {
  moving: '#2ECC71',
  idle: '#F5A623',
  stopped: '#8A94A6',
  offline: '#5C6877',
  maintenance: '#9B6BFF',
  not_tracked: '#5C6877',
};
