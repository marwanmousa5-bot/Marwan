"""Export the OSM extract as compact GeoJSON for the in-browser FleetBeat demo.

MapLibre renders these as native `geojson` sources, so the browsable build needs
no tile server - but the geometry is still the real OpenStreetMap extract.
"""
from __future__ import annotations

import json
import os
import sys

import osmium
from shapely.geometry import LineString, Polygon

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PBF = os.path.join(ROOT, "backend", "data", "helsinki.osm.pbf")
OUT = os.path.join(ROOT, "web-demo", "public", "data")

ROAD_SPEEDS = {
    "motorway": 100, "motorway_link": 60, "trunk": 80, "trunk_link": 50,
    "primary": 50, "primary_link": 40, "secondary": 50, "secondary_link": 40,
    "tertiary": 40, "tertiary_link": 35, "unclassified": 30, "residential": 30,
    "living_street": 15, "service": 20, "pedestrian": 10,
}
RANK = {"motorway": 0, "trunk": 1, "primary": 2, "secondary": 3, "tertiary": 4,
        "unclassified": 5, "residential": 6, "living_street": 7, "service": 8,
        "pedestrian": 8}
PATHS = {"footway", "path", "cycleway", "steps", "track", "corridor", "trail"}
POI_KEYS = ("amenity", "shop", "office", "tourism", "healthcare", "leisure")


def r(v, p=5):
    return round(v, p)


class C(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.roads, self.paths, self.rail = [], [], []
        self.buildings, self.water, self.landuse = [], [], []
        self.pois = []

    def node(self, n):
        if not n.location.valid():
            return
        t = dict(n.tags)
        cat = next((k for k in POI_KEYS if k in t), None)
        if cat and t.get("name"):
            self.pois.append({"name": t["name"], "cat": cat, "kind": t[cat],
                              "lon": r(n.location.lon, 6), "lat": r(n.location.lat, 6),
                              "street": t.get("addr:street"),
                              "hn": t.get("addr:housenumber")})

    def way(self, w):
        try:
            co = [(r(n.location.lon, 6), r(n.location.lat, 6))
                  for n in w.nodes if n.location.valid()]
        except osmium.InvalidLocationError:
            return
        if len(co) < 2:
            return
        t = dict(w.tags)
        hw = t.get("highway")
        closed = co[0] == co[-1] and len(co) >= 4
        if hw in ROAD_SPEEDS:
            self.roads.append((co, t))
        elif hw in PATHS:
            self.paths.append((co, t))
        if t.get("railway") in ("rail", "light_rail", "subway", "tram"):
            self.rail.append((co, t))
        if "building" in t and closed:
            self.buildings.append((co, t))
        if closed and (t.get("natural") == "water"
                       or t.get("waterway") in ("riverbank", "dock")
                       or t.get("landuse") == "basin"):
            self.water.append((co, t))
        elif closed and t.get("landuse") in ("grass", "forest", "meadow", "cemetery",
                                             "recreation_ground"):
            self.landuse.append((co, t))
        elif closed and t.get("leisure") in ("park", "garden", "pitch", "playground",
                                             "sports_centre"):
            self.landuse.append((co, dict(t, landuse="park")))
        cat = next((k for k in POI_KEYS if k in t), None)
        if cat and t.get("name"):
            g = Polygon(co).centroid if closed else LineString(co).centroid
            self.pois.append({"name": t["name"], "cat": cat, "kind": t[cat],
                              "lon": r(g.x, 6), "lat": r(g.y, 6),
                              "street": t.get("addr:street"),
                              "hn": t.get("addr:housenumber")})


def fc(features):
    return {"type": "FeatureCollection", "features": features}


def line(co, props):
    return {"type": "Feature", "geometry": {"type": "LineString",
                                            "coordinates": [list(p) for p in co]},
            "properties": props}


def poly(co, props):
    return {"type": "Feature", "geometry": {"type": "Polygon",
                                            "coordinates": [[list(p) for p in co]]},
            "properties": props}


def main():
    os.makedirs(OUT, exist_ok=True)
    c = C()
    c.apply_file(PBF, locations=True)

    roads = [line(co, {"c": t["highway"], "n": t.get("name", ""),
                       "r": RANK.get(t["highway"], 8)}) for co, t in c.roads]
    paths = [line(co, {"c": t["highway"]}) for co, t in c.paths]
    rail = [line(co, {"c": t.get("railway", "rail")}) for co, t in c.rail]
    buildings = [poly(co, {}) for co, t in c.buildings]
    water = [poly(co, {}) for co, t in c.water]
    landuse = [poly(co, {"c": t.get("landuse", "grass")}) for co, t in c.landuse]

    seen, pois = set(), []
    for p in c.pois:
        k = (p["name"], p["lon"], p["lat"])
        if k in seen:
            continue
        seen.add(k)
        pois.append(p)

    layers = {
        "roads": fc(roads), "paths": fc(paths), "rail": fc(rail),
        "buildings": fc(buildings), "water": fc(water), "landuse": fc(landuse),
    }
    for name, data in layers.items():
        path = os.path.join(OUT, f"{name}.geojson")
        with open(path, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        print(f"  {name}: {len(data['features'])} features, "
              f"{os.path.getsize(path) / 1024:.0f} KB")

    with open(os.path.join(OUT, "places.json"), "w") as f:
        json.dump(pois, f, separators=(",", ":"))
    print(f"  places: {len(pois)} ({os.path.getsize(os.path.join(OUT, 'places.json')) / 1024:.0f} KB)")

    # the routing graph, uncompressed for the browser
    import gzip
    g = json.load(gzip.open(os.path.join(ROOT, "backend", "data", "graph.json.gz"), "rt"))
    with open(os.path.join(OUT, "graph.json"), "w") as f:
        json.dump(g, f, separators=(",", ":"))
    print(f"  graph: {len(g['nodes'])} nodes / {len(g['edges'])} edges "
          f"({os.path.getsize(os.path.join(OUT, 'graph.json')) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
