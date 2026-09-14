// Geometry helpers shared by routing, simulation and the map layer.

export const EARTH_R = 6371000;

export function haversine(lon1: number, lat1: number, lon2: number, lat2: number): number {
  const p1 = (lat1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const dp = p2 - p1;
  const dl = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * EARTH_R * Math.asin(Math.sqrt(a));
}

export function bearing(lon1: number, lat1: number, lon2: number, lat2: number): number {
  const r = Math.PI / 180;
  const y = Math.sin((lon2 - lon1) * r) * Math.cos(lat2 * r);
  const x =
    Math.cos(lat1 * r) * Math.sin(lat2 * r) -
    Math.sin(lat1 * r) * Math.cos(lat2 * r) * Math.cos((lon2 - lon1) * r);
  return (Math.atan2(y, x) * (180 / Math.PI) + 360) % 360;
}

/** Shortest signed difference between two bearings, in degrees. */
export function angleDelta(a: number, b: number): number {
  return ((b - a + 540) % 360) - 180;
}

export function pathLength(path: [number, number][]): number {
  let total = 0;
  for (let i = 0; i < path.length - 1; i++) {
    total += haversine(path[i][0], path[i][1], path[i + 1][0], path[i + 1][1]);
  }
  return total;
}

/** Project a point onto a segment using a local equirectangular frame. */
export function projectOnSegment(
  lon: number, lat: number,
  a: [number, number], b: [number, number],
): [number, number] {
  const k = Math.cos((lat * Math.PI) / 180);
  const ax = a[0] * k, ay = a[1];
  const bx = b[0] * k, by = b[1];
  const px = lon * k, py = lat;
  const dx = bx - ax, dy = by - ay;
  if (dx === 0 && dy === 0) return [a[0], a[1]];
  let t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy);
  t = Math.max(0, Math.min(1, t));
  return [(ax + t * dx) / k, ay + t * dy];
}

export function pointInPolygon(lon: number, lat: number, poly: [number, number][]): boolean {
  let inside = false;
  const n = poly.length;
  if (n < 3) return false;
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > lat !== yj > lat) {
      const x = ((xj - xi) * (lat - yi)) / (yj - yi || 1e-12) + xi;
      if (lon < x) inside = !inside;
    }
  }
  return inside;
}

export function polygonAreaKm2(poly: [number, number][]): number {
  if (poly.length < 3) return 0;
  const lat0 = poly.reduce((s, p) => s + p[1], 0) / poly.length;
  const k = Math.cos((lat0 * Math.PI) / 180) * 111320;
  let s = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i];
    const [x2, y2] = poly[(i + 1) % poly.length];
    s += x1 * k * (y2 * 110540) - x2 * k * (y1 * 110540);
  }
  return Math.abs(s) / 2 / 1e6;
}

/** A circle approximated as a polygon, for drawing circular geofences. */
export function circlePolygon(
  lon: number, lat: number, radiusM: number, steps = 64,
): [number, number][] {
  const out: [number, number][] = [];
  const latR = radiusM / 110540;
  const lonR = radiusM / (111320 * Math.cos((lat * Math.PI) / 180));
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * Math.PI * 2;
    out.push([lon + lonR * Math.cos(a), lat + latR * Math.sin(a)]);
  }
  return out;
}

/** Walk `metres` along a polyline, returning the position and the index reached. */
export function advanceAlong(
  path: [number, number][], segIndex: number, segProgressM: number, metres: number,
): { seg: number; progress: number; point: [number, number]; done: boolean; heading: number } {
  let seg = segIndex;
  let progress = segProgressM;
  let left = metres;
  let heading = 0;
  while (left > 0 && seg < path.length - 1) {
    const a = path[seg];
    const b = path[seg + 1];
    const segLen = haversine(a[0], a[1], b[0], b[1]);
    heading = bearing(a[0], a[1], b[0], b[1]);
    const remaining = segLen - progress;
    if (left < remaining) {
      progress += left;
      left = 0;
      const t = progress / (segLen || 1e-9);
      return {
        seg, progress, heading, done: false,
        point: [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t],
      };
    }
    left -= remaining;
    seg += 1;
    progress = 0;
  }
  const last = path[Math.min(seg, path.length - 1)];
  return { seg, progress, heading, done: seg >= path.length - 1, point: [last[0], last[1]] };
}

export function pointAt(
  path: [number, number][], seg: number, progressM: number,
): [number, number] {
  if (!path.length) return [0, 0];
  if (seg >= path.length - 1) return path[path.length - 1];
  const a = path[seg];
  const b = path[seg + 1];
  const segLen = haversine(a[0], a[1], b[0], b[1]) || 1e-9;
  const t = Math.min(1, progressM / segLen);
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}
