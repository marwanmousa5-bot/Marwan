// A* routing over the real OpenStreetMap street graph.
//
// The graph is built by scripts/build_basemap.py from the bundled Helsinki
// extract: nodes are real junctions, edges carry real street names, lengths and
// speed limits. The server build runs the same algorithm in Python.

import { haversine, projectOnSegment } from './geo';

export interface RawGraph {
  nodes: [number, number][];
  // [from, to, distance_m, speed_kph, name, class, geometry, wayId]
  edges: [number, number, number, number, string, string, [number, number][], number][];
  bounds: [number, number, number, number];
}

export interface Edge {
  a: number;
  b: number;
  d: number;
  v: number;
  name: string;
  klass: string;
  geom: [number, number][];
  t: number;
}

export interface RouteLeg {
  distanceM: number;
  durationS: number;
  geometry: [number, number][];
}

export interface RouteResult {
  ok: boolean;
  message: string;
  distanceM: number;
  durationS: number;
  geometry: [number, number][];
  legs: RouteLeg[];
  streets: string[];
}

const CELL = 0.0025; // ~250 m snapping grid

export class StreetGraph {
  nodes: [number, number][];
  edges: Edge[];
  adj: number[][];
  bounds: [number, number, number, number];
  private grid = new Map<string, number[]>();
  private maxSpeed = 50;

  constructor(raw: RawGraph) {
    this.nodes = raw.nodes;
    this.bounds = raw.bounds;
    this.edges = [];
    this.adj = raw.nodes.map(() => []);
    for (const [a, b, d, v, name, klass, geom] of raw.edges) {
      const idx = this.edges.length;
      this.edges.push({ a, b, d, v, name, klass, geom, t: d / Math.max(1, (v * 1000) / 3600) });
      this.adj[a].push(idx);
      if (v > this.maxSpeed) this.maxSpeed = v;
    }
    this.edges.forEach((e, i) => {
      for (const [lon, lat] of e.geom) {
        const key = `${Math.floor(lon / CELL)}:${Math.floor(lat / CELL)}`;
        const bucket = this.grid.get(key);
        if (bucket) bucket.push(i);
        else this.grid.set(key, [i]);
      }
    });
  }

  private nearbyEdges(lon: number, lat: number, rings: number): number[] {
    const cx = Math.floor(lon / CELL);
    const cy = Math.floor(lat / CELL);
    const out: number[] = [];
    for (let dx = -rings; dx <= rings; dx++) {
      for (let dy = -rings; dy <= rings; dy++) {
        const bucket = this.grid.get(`${cx + dx}:${cy + dy}`);
        if (bucket) out.push(...bucket);
      }
    }
    return out;
  }

  snap(lon: number, lat: number): { edge: number; distance: number; point: [number, number] } {
    let best = { edge: -1, distance: Infinity, point: [lon, lat] as [number, number] };
    for (let rings = 1; rings <= 9 && best.edge === -1; rings += 2) {
      for (const i of this.nearbyEdges(lon, lat, rings)) {
        const geom = this.edges[i].geom;
        for (let j = 0; j < geom.length - 1; j++) {
          const p = projectOnSegment(lon, lat, geom[j], geom[j + 1]);
          const d = haversine(lon, lat, p[0], p[1]);
          if (d < best.distance) best = { edge: i, distance: d, point: p };
        }
      }
    }
    return best;
  }

  streetAt(lon: number, lat: number): string {
    const s = this.snap(lon, lat);
    if (s.edge === -1 || s.distance > 120) return '';
    return this.edges[s.edge].name || '';
  }

  nearestNode(lon: number, lat: number): number {
    const s = this.snap(lon, lat);
    if (s.edge === -1) return 0;
    const e = this.edges[s.edge];
    const da = haversine(s.point[0], s.point[1], this.nodes[e.a][0], this.nodes[e.a][1]);
    const db = haversine(s.point[0], s.point[1], this.nodes[e.b][0], this.nodes[e.b][1]);
    return da <= db ? e.a : e.b;
  }

  /** A* on travel time. Returns the edge ids of the path. */
  shortestPath(start: number, goal: number, avoid?: Set<number>): number[] {
    if (start === goal) return [];
    const [gx, gy] = this.nodes[goal];
    const bestSpeed = Math.max(1, (this.maxSpeed * 1000) / 3600);
    const h = (n: number) => {
      const [nx, ny] = this.nodes[n];
      return haversine(nx, ny, gx, gy) / bestSpeed;
    };

    const open = new BinaryHeap();
    open.push(start, h(start));
    const gScore = new Map<number, number>([[start, 0]]);
    const cameFrom = new Map<number, number>();
    const closed = new Set<number>();

    while (open.size) {
      const node = open.pop()!;
      if (closed.has(node)) continue;
      closed.add(node);
      if (node === goal) break;
      const g = gScore.get(node)!;
      for (const eid of this.adj[node]) {
        if (avoid?.has(eid)) continue;
        const e = this.edges[eid];
        if (closed.has(e.b)) continue;
        const ng = g + e.t;
        if (ng < (gScore.get(e.b) ?? Infinity)) {
          gScore.set(e.b, ng);
          cameFrom.set(e.b, eid);
          open.push(e.b, ng + h(e.b));
        }
      }
    }

    if (!cameFrom.has(goal)) return [];
    const path: number[] = [];
    let cur = goal;
    let guard = 0;
    while (cur !== start && guard++ < 20000) {
      const eid = cameFrom.get(cur);
      if (eid === undefined) return [];
      path.push(eid);
      cur = this.edges[eid].a;
    }
    return path.reverse();
  }

  route(waypoints: [number, number][], avoidEdges: number[] = []): RouteResult {
    if (waypoints.length < 2) {
      return { ok: false, message: 'A route needs at least two points.',
               distanceM: 0, durationS: 0, geometry: [], legs: [], streets: [] };
    }
    const avoid = new Set(avoidEdges);
    const legs: RouteLeg[] = [];
    const full: [number, number][] = [];
    const streets: string[] = [];
    let totalD = 0;
    let totalT = 0;

    for (let i = 0; i < waypoints.length - 1; i++) {
      const [aLon, aLat] = waypoints[i];
      const [bLon, bLat] = waypoints[i + 1];
      const n1 = this.nearestNode(aLon, aLat);
      const n2 = this.nearestNode(bLon, bLat);
      const path = this.shortestPath(n1, n2, avoid);
      if (!path.length && n1 !== n2) {
        return {
          ok: false,
          message: 'No drivable route exists between these points on the mapped street network.',
          distanceM: 0, durationS: 0, geometry: [], legs: [], streets: [],
        };
      }
      const geom: [number, number][] = [[aLon, aLat]];
      let d = 0;
      let t = 0;
      for (const eid of path) {
        const e = this.edges[eid];
        for (const pt of e.geom) {
          const last = geom[geom.length - 1];
          if (!last || last[0] !== pt[0] || last[1] !== pt[1]) geom.push(pt);
        }
        d += e.d;
        t += e.t;
        if (e.name && streets[streets.length - 1] !== e.name) streets.push(e.name);
      }
      geom.push([bLon, bLat]);
      // approach legs from the real point to the snapped network
      const lead = haversine(aLon, aLat, geom[1][0], geom[1][1]);
      const tail = haversine(bLon, bLat, geom[geom.length - 2][0], geom[geom.length - 2][1]);
      d += lead + tail;
      t += (lead + tail) / 5.5;

      legs.push({ distanceM: d, durationS: t, geometry: geom });
      totalD += d;
      totalT += t;
      full.push(...(full.length ? geom.slice(1) : geom));
    }

    return { ok: true, message: '', distanceM: totalD, durationS: totalT,
             geometry: full, legs, streets };
  }
}

/** Minimal binary heap - the graph is small but routing runs on every tick. */
class BinaryHeap {
  private items: number[] = [];
  private prios: number[] = [];

  get size() { return this.items.length; }

  push(item: number, prio: number) {
    this.items.push(item);
    this.prios.push(prio);
    let i = this.items.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (this.prios[p] <= this.prios[i]) break;
      this.swap(i, p);
      i = p;
    }
  }

  pop(): number | undefined {
    if (!this.items.length) return undefined;
    const top = this.items[0];
    const lastItem = this.items.pop()!;
    const lastPrio = this.prios.pop()!;
    if (this.items.length) {
      this.items[0] = lastItem;
      this.prios[0] = lastPrio;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let s = i;
        if (l < this.items.length && this.prios[l] < this.prios[s]) s = l;
        if (r < this.items.length && this.prios[r] < this.prios[s]) s = r;
        if (s === i) break;
        this.swap(i, s);
        i = s;
      }
    }
    return top;
  }

  private swap(a: number, b: number) {
    [this.items[a], this.items[b]] = [this.items[b], this.items[a]];
    [this.prios[a], this.prios[b]] = [this.prios[b], this.prios[a]];
  }
}

/** Progress of a vehicle along a planned geometry. */
export function routeProgress(
  geometry: [number, number][], lat: number, lon: number,
): { pct: number; travelledM: number; remainingM: number; index: number; deviationM: number } {
  if (geometry.length < 2) {
    return { pct: 0, travelledM: 0, remainingM: 0, index: 0, deviationM: 0 };
  }
  let bestI = 0;
  let bestD = Infinity;
  for (let i = 0; i < geometry.length; i++) {
    const d = haversine(lon, lat, geometry[i][0], geometry[i][1]);
    if (d < bestD) { bestD = d; bestI = i; }
  }
  let travelled = 0;
  for (let i = 0; i < bestI; i++) {
    travelled += haversine(geometry[i][0], geometry[i][1], geometry[i + 1][0], geometry[i + 1][1]);
  }
  let total = 0;
  for (let i = 0; i < geometry.length - 1; i++) {
    total += haversine(geometry[i][0], geometry[i][1], geometry[i + 1][0], geometry[i + 1][1]);
  }
  total = total || 1;
  return {
    pct: Math.min(100, (travelled / total) * 100),
    travelledM: travelled,
    remainingM: Math.max(0, total - travelled),
    index: bestI,
    deviationM: bestD,
  };
}

/** Exact for small stop counts, nearest-neighbour + 2-opt beyond that. */
export function optimiseStops(
  graph: StreetGraph,
  origin: [number, number],
  stops: { lon: number; lat: number }[],
  destination: [number, number],
): { order: number[]; improved: boolean; beforeS: number; afterS: number; savedS: number } {
  const base = stops.map((_, i) => i);
  if (stops.length < 2) return { order: base, improved: false, beforeS: 0, afterS: 0, savedS: 0 };

  const cost = (order: number[]) => {
    const pts: [number, number][] = [origin, ...order.map((i) => [stops[i].lon, stops[i].lat] as [number, number]), destination];
    const r = graph.route(pts);
    return r.ok ? r.durationS : Infinity;
  };

  const beforeS = cost(base);
  let bestOrder = base;
  let best = beforeS;

  if (stops.length <= 6) {
    const permute = (arr: number[], k = 0) => {
      if (k === arr.length) {
        const c = cost(arr);
        if (c < best) { best = c; bestOrder = [...arr]; }
        return;
      }
      for (let i = k; i < arr.length; i++) {
        [arr[k], arr[i]] = [arr[i], arr[k]];
        permute(arr, k + 1);
        [arr[k], arr[i]] = [arr[i], arr[k]];
      }
    };
    permute([...base]);
  } else {
    const remaining = new Set(base);
    let cur = origin;
    const seed: number[] = [];
    while (remaining.size) {
      let pick = -1;
      let pd = Infinity;
      for (const i of remaining) {
        const d = haversine(cur[0], cur[1], stops[i].lon, stops[i].lat);
        if (d < pd) { pd = d; pick = i; }
      }
      seed.push(pick);
      remaining.delete(pick);
      cur = [stops[pick].lon, stops[pick].lat];
    }
    bestOrder = seed;
    best = cost(seed);
    let improved = true;
    while (improved) {
      improved = false;
      for (let i = 0; i < bestOrder.length - 1; i++) {
        for (let j = i + 2; j < bestOrder.length; j++) {
          const cand = [
            ...bestOrder.slice(0, i + 1),
            ...bestOrder.slice(i + 1, j + 1).reverse(),
            ...bestOrder.slice(j + 1),
          ];
          const c = cost(cand);
          if (c < best - 1) { best = c; bestOrder = cand; improved = true; }
        }
      }
    }
  }

  return {
    order: bestOrder,
    improved: beforeS - best > 1,
    beforeS,
    afterS: best,
    savedS: Math.max(0, beforeS - best),
  };
}
