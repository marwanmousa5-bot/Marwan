"""Build FleetBeat's offline basemap assets from a real OpenStreetMap extract.

Outputs (into backend/data/):
  basemap.mbtiles  - Mapbox Vector Tiles (z10-z18) with land/water/landuse/
                     buildings/roads/rail/places layers, rendered by MapLibre GL.
  graph.json.gz    - routable street graph (nodes + directed edges) used by the
                     in-process routing engine.
  places.json      - named real-world places (shops, offices, hotels, stations)
                     used for geocoding, search and demo-data seeding.

Nothing here is synthesised: every geometry comes from the OSM extract.
"""
from __future__ import annotations

import gzip
import json
import math
import os
import sqlite3
import sys
from collections import defaultdict

import osmium
import mapbox_vector_tile
from shapely.geometry import LineString, Polygon, Point, box, mapping
from shapely.ops import transform as shp_transform

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "backend", "data")
PBF = os.path.join(DATA, "helsinki.osm.pbf")

MIN_ZOOM, MAX_ZOOM = 10, 18
EXTENT = 4096

# --- which OSM highway classes are routable, and their default speeds (km/h) ---
ROAD_SPEEDS = {
    "motorway": 100, "motorway_link": 60,
    "trunk": 80, "trunk_link": 50,
    "primary": 50, "primary_link": 40,
    "secondary": 50, "secondary_link": 40,
    "tertiary": 40, "tertiary_link": 35,
    "unclassified": 30, "residential": 30,
    "living_street": 15, "service": 20, "pedestrian": 10,
}
# Rendered but not routable by vehicles
PATH_CLASSES = {"footway", "path", "cycleway", "steps", "track", "corridor", "trail"}

ROAD_RANK = {
    "motorway": 0, "trunk": 1, "primary": 2, "secondary": 3,
    "tertiary": 4, "unclassified": 5, "residential": 6,
    "living_street": 7, "service": 8, "pedestrian": 8,
}

POI_KEYS = ("amenity", "shop", "office", "tourism", "healthcare", "leisure")


def haversine(lon1, lat1, lon2, lat2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class Collector(osmium.SimpleHandler):
    """Single pass over the extract, collecting everything we need."""

    def __init__(self):
        super().__init__()
        self.roads = []       # (coords, tags)
        self.paths = []
        self.rail = []
        self.buildings = []
        self.water = []
        self.landuse = []
        self.pois = []        # dicts
        self.bounds = [180.0, 90.0, -180.0, -90.0]

    def _track(self, lon, lat):
        b = self.bounds
        b[0] = min(b[0], lon); b[1] = min(b[1], lat)
        b[2] = max(b[2], lon); b[3] = max(b[3], lat)

    def node(self, n):
        if not n.location.valid():
            return
        self._track(n.location.lon, n.location.lat)
        t = dict(n.tags)
        cat = next((k for k in POI_KEYS if k in t), None)
        if cat and t.get("name"):
            self.pois.append({
                "osm_id": f"n{n.id}", "name": t["name"], "category": cat,
                "kind": t[cat], "lon": round(n.location.lon, 7),
                "lat": round(n.location.lat, 7),
                "street": t.get("addr:street"), "housenumber": t.get("addr:housenumber"),
            })

    def way(self, w):
        try:
            coords = [(nd.location.lon, nd.location.lat) for nd in w.nodes if nd.location.valid()]
        except osmium.InvalidLocationError:
            return
        if len(coords) < 2:
            return
        for lon, lat in coords:
            self._track(lon, lat)
        t = dict(w.tags)
        hw = t.get("highway")
        closed = coords[0] == coords[-1] and len(coords) >= 4

        if hw in ROAD_SPEEDS:
            self.roads.append((coords, t, w.id))
        elif hw in PATH_CLASSES:
            self.paths.append((coords, t))
        if t.get("railway") in ("rail", "light_rail", "subway", "tram"):
            self.rail.append((coords, t))
        if "building" in t and closed:
            self.buildings.append((coords, t))
        if closed and (t.get("natural") == "water" or t.get("waterway") in ("riverbank", "dock")
                       or t.get("landuse") == "basin"):
            self.water.append((coords, t))
        elif closed and t.get("landuse") in ("grass", "forest", "meadow", "residential",
                                             "commercial", "industrial", "retail", "railway",
                                             "cemetery", "recreation_ground"):
            self.landuse.append((coords, t))
        elif closed and t.get("leisure") in ("park", "garden", "pitch", "playground", "sports_centre"):
            self.landuse.append((coords, dict(t, landuse="park")))

        cat = next((k for k in POI_KEYS if k in t), None)
        if cat and t.get("name"):
            c = LineString(coords).centroid if not closed else Polygon(coords).centroid
            self.pois.append({
                "osm_id": f"w{w.id}", "name": t["name"], "category": cat, "kind": t[cat],
                "lon": round(c.x, 7), "lat": round(c.y, 7),
                "street": t.get("addr:street"), "housenumber": t.get("addr:housenumber"),
            })


# --------------------------------------------------------------------------- #
# Routing graph
# --------------------------------------------------------------------------- #
def build_graph(roads):
    """Turn OSM ways into a directed, node-indexed routing graph.

    Junctions are detected by counting how many ways use each coordinate; a way
    is then split into edges between consecutive junctions so the router works on
    real intersections rather than raw way geometry.
    """
    usage = defaultdict(int)
    for coords, _tags, _wid in roads:
        for c in coords:
            usage[c] += 1

    node_ids: dict[tuple, int] = {}
    nodes: list[tuple[float, float]] = []

    def nid(c):
        if c not in node_ids:
            node_ids[c] = len(nodes)
            nodes.append((round(c[0], 7), round(c[1], 7)))
        return node_ids[c]

    edges = []  # (from, to, dist_m, speed_kph, name, road_class, geometry)
    for coords, tags, wid in roads:
        hw = tags["highway"]
        speed = ROAD_SPEEDS[hw]
        try:
            speed = min(130, int(str(tags.get("maxspeed", speed)).split()[0]))
        except (ValueError, IndexError):
            pass
        name = tags.get("name") or tags.get("ref") or ""
        oneway = tags.get("oneway") in ("yes", "true", "1") or tags.get("junction") == "roundabout"
        reverse_only = tags.get("oneway") == "-1"

        # split at junctions / endpoints
        segment = [coords[0]]
        for c in coords[1:]:
            segment.append(c)
            is_junction = usage[c] > 1 or c == coords[-1]
            if is_junction and len(segment) >= 2:
                a, b = nid(segment[0]), nid(segment[-1])
                if a != b:
                    dist = sum(haversine(*segment[i], *segment[i + 1])
                               for i in range(len(segment) - 1))
                    geom = [[round(x, 6), round(y, 6)] for x, y in segment]
                    if not reverse_only:
                        edges.append([a, b, round(dist, 1), speed, name, hw, geom, wid])
                    if not oneway:
                        edges.append([b, a, round(dist, 1), speed, name, hw,
                                      list(reversed(geom)), wid])
                segment = [c]

    # keep only the largest connected component so routing never dead-ends
    adj = defaultdict(list)
    und = defaultdict(set)
    for i, e in enumerate(edges):
        adj[e[0]].append(i)
        und[e[0]].add(e[1]); und[e[1]].add(e[0])

    seen = set()
    best: set[int] = set()
    for start in range(len(nodes)):
        if start in seen:
            continue
        stack, comp = [start], set()
        seen.add(start)
        while stack:
            n = stack.pop()
            comp.add(n)
            for m in und[n]:
                if m not in seen:
                    seen.add(m); stack.append(m)
        if len(comp) > len(best):
            best = comp

    keep_edges = [e for e in edges if e[0] in best and e[1] in best]
    remap = {old: new for new, old in enumerate(sorted(best))}
    new_nodes = [nodes[o] for o in sorted(best)]
    for e in keep_edges:
        e[0] = remap[e[0]]; e[1] = remap[e[1]]

    return {"nodes": new_nodes, "edges": keep_edges}


# --------------------------------------------------------------------------- #
# Vector tiles
# --------------------------------------------------------------------------- #
def lonlat_to_tile(lon, lat, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n
    return x, y


def tile_bounds(x, y, z):
    n = 2 ** z

    def lon(xx):
        return xx / n * 360.0 - 180.0

    def lat(yy):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / n))))

    return lon(x), lat(y + 1), lon(x + 1), lat(y)


def to_tile_coords(geom, x, y, z):
    """Project WGS84 geometry into 0..EXTENT tile space (y up, MVT convention)."""
    n = 2 ** z

    def fn(lon, lat):
        px = (lon + 180.0) / 360.0 * n - x
        lat_r = math.radians(max(-85.05, min(85.05, lat)))
        py = (1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n - y
        return px * EXTENT, (1 - py) * EXTENT

    if geom.geom_type == "Point":
        return Point(*fn(geom.x, geom.y))
    return shp_transform(lambda xs, ys: tuple(zip(*[fn(a, b) for a, b in zip(xs, ys)])), geom)


def build_tiles(c: Collector, out_path: str):
    # Pre-build shapely geometries once, tagged with the minimum zoom they appear at.
    feats: dict[str, list] = defaultdict(list)

    for coords, tags, _wid in c.roads:
        hw = tags["highway"]
        rank = ROAD_RANK.get(hw, 8)
        minz = {0: 10, 1: 10, 2: 11, 3: 12, 4: 13, 5: 14, 6: 14, 7: 15, 8: 15}[rank]
        feats["roads"].append((LineString(coords), {
            "class": hw, "name": tags.get("name", ""), "rank": rank,
            "oneway": 1 if tags.get("oneway") in ("yes", "true", "1") else 0,
        }, minz))
    for coords, tags in c.paths:
        feats["paths"].append((LineString(coords),
                               {"class": tags["highway"], "name": tags.get("name", "")}, 16))
    for coords, tags in c.rail:
        feats["rail"].append((LineString(coords), {"class": tags.get("railway", "rail")}, 13))
    for coords, tags in c.buildings:
        try:
            p = Polygon(coords)
            if p.is_valid and p.area > 0:
                feats["buildings"].append((p, {"name": tags.get("name", "")}, 15))
        except Exception:
            pass
    for coords, tags in c.water:
        try:
            p = Polygon(coords)
            if p.is_valid:
                feats["water"].append((p, {"class": "water"}, 10))
        except Exception:
            pass
    for coords, tags in c.landuse:
        try:
            p = Polygon(coords)
            if p.is_valid:
                feats["landuse"].append((p, {"class": tags.get("landuse", "grass")}, 12))
        except Exception:
            pass
    for p in c.pois:
        minz = 15 if p["category"] in ("office", "shop") else 14
        feats["places"].append((Point(p["lon"], p["lat"]),
                                {"name": p["name"], "class": p["category"], "kind": p["kind"]},
                                minz))

    if os.path.exists(out_path):
        os.remove(out_path)
    db = sqlite3.connect(out_path)
    db.executescript("""
        CREATE TABLE metadata (name TEXT, value TEXT);
        CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER,
                            tile_row INTEGER, tile_data BLOB);
        CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row);
    """)

    minlon, minlat, maxlon, maxlat = c.bounds
    total = 0
    for z in range(MIN_ZOOM, MAX_ZOOM + 1):
        x0, y1 = lonlat_to_tile(minlon, minlat, z)
        x1, y0 = lonlat_to_tile(maxlon, maxlat, z)
        for tx in range(int(x0), int(x1) + 1):
            for ty in range(int(y0), int(y1) + 1):
                w, s, e, n = tile_bounds(tx, ty, z)
                pad = (e - w) * 0.05
                clip = box(w - pad, s - pad, e + pad, n + pad)
                layers = []
                for layer, items in feats.items():
                    out = []
                    for geom, props, minz in items:
                        if z < minz or not geom.intersects(clip):
                            continue
                        g = geom if geom.geom_type == "Point" else geom.intersection(clip)
                        if g.is_empty:
                            continue
                        try:
                            tg = to_tile_coords(g, tx, ty, z)
                        except Exception:
                            continue
                        if tg.is_empty:
                            continue
                        out.append({"geometry": mapping(tg), "properties": props})
                    if out:
                        layers.append({"name": layer, "features": out})
                if not layers:
                    continue
                blob = mapbox_vector_tile.encode(layers, default_options={"extents": EXTENT})
                if not blob:
                    continue
                db.execute("INSERT OR REPLACE INTO tiles VALUES (?,?,?,?)",
                           (z, tx, (2 ** z - 1) - ty, blob))
                total += 1
        db.commit()
        print(f"  z{z}: {total} tiles cumulative", flush=True)

    meta = {
        "name": "FleetBeat Helsinki", "format": "pbf", "type": "baselayer", "version": "1",
        "minzoom": str(MIN_ZOOM), "maxzoom": str(MAX_ZOOM),
        "bounds": f"{minlon},{minlat},{maxlon},{maxlat}",
        "center": f"{(minlon + maxlon) / 2},{(minlat + maxlat) / 2},15",
        "attribution": "© OpenStreetMap contributors",
        "json": json.dumps({"vector_layers": [
            {"id": k, "minzoom": MIN_ZOOM, "maxzoom": MAX_ZOOM, "fields": {}} for k in feats
        ]}),
    }
    db.executemany("INSERT INTO metadata VALUES (?,?)", list(meta.items()))
    db.commit()
    db.close()
    return total


def main():
    print(f"Reading {PBF} ...", flush=True)
    c = Collector()
    c.apply_file(PBF, locations=True)
    print(f"  roads={len(c.roads)} paths={len(c.paths)} buildings={len(c.buildings)} "
          f"water={len(c.water)} landuse={len(c.landuse)} pois={len(c.pois)}", flush=True)
    print(f"  bounds={c.bounds}", flush=True)

    print("Building routing graph ...", flush=True)
    g = build_graph(c.roads)
    g["bounds"] = [round(v, 6) for v in c.bounds]
    print(f"  nodes={len(g['nodes'])} edges={len(g['edges'])}", flush=True)
    with gzip.open(os.path.join(DATA, "graph.json.gz"), "wt") as f:
        json.dump(g, f, separators=(",", ":"))

    # de-duplicate places by (name, rounded position)
    seen, places = set(), []
    for p in c.pois:
        k = (p["name"], round(p["lon"], 5), round(p["lat"], 5))
        if k in seen:
            continue
        seen.add(k)
        places.append(p)
    with open(os.path.join(DATA, "places.json"), "w") as f:
        json.dump({"bounds": g["bounds"], "places": places}, f, separators=(",", ":"))
    print(f"  places={len(places)}", flush=True)

    print("Building vector tiles ...", flush=True)
    n = build_tiles(c, os.path.join(DATA, "basemap.mbtiles"))
    print(f"Done. {n} tiles.", flush=True)


if __name__ == "__main__":
    sys.exit(main())
