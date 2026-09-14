// MapLibre GL is loaded as a same-origin script (the CSP build, which uses a
// real worker URL rather than a blob). We type only what this app touches.
declare global {
  interface Window { maplibregl: MapLibre; }
}

export interface MapLibre {
  Map: new (opts: Record<string, unknown>) => MlMap;
  Marker: new (opts?: Record<string, unknown>) => MlMarker;
  Popup: new (opts?: Record<string, unknown>) => MlPopup;
  LngLatBounds: new (sw?: [number, number], ne?: [number, number]) => MlBounds;
  addProtocol: (name: string, fn: (params: { url: string }) => Promise<{ data: ArrayBuffer }>) => void;
  setWorkerUrl: (url: string) => void;
}

export interface MlMap {
  on(ev: string, fn: (e: never) => void): void;
  on(ev: string, layer: string, fn: (e: never) => void): void;
  off(ev: string, fn: (e: never) => void): void;
  once(ev: string, fn: () => void): void;
  addSource(id: string, src: Record<string, unknown>): void;
  getSource(id: string): { setData: (d: unknown) => void } | undefined;
  addLayer(layer: Record<string, unknown>, before?: string): void;
  getLayer(id: string): unknown;
  removeLayer(id: string): void;
  removeSource(id: string): void;
  setLayoutProperty(layer: string, prop: string, value: unknown): void;
  setPaintProperty(layer: string, prop: string, value: unknown): void;
  setFilter(layer: string, filter: unknown): void;
  flyTo(opts: Record<string, unknown>): void;
  easeTo(opts: Record<string, unknown>): void;
  jumpTo(opts: Record<string, unknown>): void;
  fitBounds(b: MlBounds | number[][], opts?: Record<string, unknown>): void;
  getZoom(): number;
  setZoom(z: number): void;
  getBearing(): number;
  setBearing(b: number): void;
  setPitch(p: number): void;
  getPitch(): number;
  getCenter(): { lng: number; lat: number };
  setStyle(style: unknown): void;
  resize(): void;
  remove(): void;
  project(ll: [number, number]): { x: number; y: number };
  unproject(p: [number, number]): { lng: number; lat: number };
  queryRenderedFeatures(p?: unknown, opts?: unknown): { properties: Record<string, string>; geometry: { coordinates: number[] } }[];
  getCanvas(): HTMLCanvasElement;
  isStyleLoaded(): boolean;
}

export interface MlMarker {
  setLngLat(ll: [number, number]): MlMarker;
  setPopup(p: MlPopup): MlMarker;
  addTo(m: MlMap): MlMarker;
  remove(): void;
  getElement(): HTMLElement;
  setRotation(r: number): MlMarker;
}

export interface MlPopup {
  setHTML(h: string): MlPopup;
  setLngLat(ll: [number, number]): MlPopup;
  addTo(m: MlMap): MlPopup;
  remove(): void;
}

export interface MlBounds {
  extend(ll: [number, number]): MlBounds;
  isEmpty(): boolean;
}

export {};
