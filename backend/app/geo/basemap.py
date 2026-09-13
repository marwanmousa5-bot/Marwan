"""Serves the self-hosted basemap: MVT tiles, the style document and geocoding.

The tiles come from `basemap.mbtiles`, produced from the bundled OSM extract.
MAP_PROVIDER lets a deployment point MapLibre at MapTiler/Mapbox/any OSM raster
source instead - the frontend only ever asks this module for a style URL.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import unicodedata

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "data")
MBTILES = os.path.join(DATA_DIR, "basemap.mbtiles")
PLACES = os.path.join(DATA_DIR, "places.json")


class TileStore:
    """Thread-local sqlite handles; MBTiles is read-only here."""

    def __init__(self, path: str = MBTILES):
        self.path = path
        self._local = threading.local()
        self.meta: dict[str, str] = {}
        self.available = os.path.exists(path)
        if self.available:
            with sqlite3.connect(path) as db:
                self.meta = dict(db.execute("SELECT name, value FROM metadata").fetchall())

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True,
                                   check_same_thread=False)
            self._local.conn = conn
        return conn

    def tile(self, z: int, x: int, y: int) -> bytes | None:
        if not self.available:
            return None
        row = self._conn().execute(
            "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
            (z, x, (2 ** z - 1) - y),
        ).fetchone()
        return row[0] if row else None

    @property
    def bounds(self) -> list[float]:
        raw = self.meta.get("bounds", "24.93,60.16,24.96,60.18")
        return [float(v) for v in raw.split(",")]

    @property
    def center(self) -> list[float]:
        raw = self.meta.get("center", "24.945,60.171,15")
        parts = [float(v) for v in raw.split(",")]
        return parts[:3]


_tiles: TileStore | None = None


def tiles() -> TileStore:
    global _tiles
    if _tiles is None:
        _tiles = TileStore()
    return _tiles


# --------------------------------------------------------------------------- #
# Map style. Colours mirror the FleetBeat palette so the map belongs to the UI.
# --------------------------------------------------------------------------- #
LIGHT = {
    "bg": "#EEF1F5", "water": "#BBD7EE", "park": "#D7E8D2", "land": "#E4E9EF",
    "building": "#D8DEE7", "building_line": "#C8D0DB",
    "road": "#FFFFFF", "road_major": "#FFFFFF", "road_case": "#D2D9E3",
    "rail": "#C2C8D2", "path": "#E2E5EA",
    "label": "#3C4656", "label_halo": "#FFFFFF", "poi": "#6B7686",
}
DARK = {
    "bg": "#0D0F13", "water": "#12212F", "park": "#152218", "land": "#14171C",
    "building": "#1A1E25", "building_line": "#222731",
    "road": "#2A3038", "road_major": "#39424E", "road_case": "#161A20",
    "rail": "#262B33", "path": "#1E232A",
    "label": "#96A1B2", "label_halo": "#0A0C0F", "poi": "#6D7A8C",
}


def build_style(base_url: str, theme: str = "light") -> dict:
    """A complete MapLibre style backed by our own vector tiles."""
    c = DARK if theme == "dark" else LIGHT
    t = tiles()
    minz, maxz = int(t.meta.get("minzoom", 10)), int(t.meta.get("maxzoom", 18))

    def road_width(mult=1.0):
        return ["interpolate", ["exponential", 1.5], ["zoom"],
                11, 0.6 * mult, 14, 1.8 * mult, 16, 6 * mult, 18, 18 * mult]

    return {
        "version": 8,
        "name": f"FleetBeat {theme.title()}",
        "glyphs": f"{base_url}/fonts/{{fontstack}}/{{range}}.pbf",
        "sources": {
            "fleetbeat": {
                "type": "vector",
                "tiles": [f"{base_url}/tiles/{{z}}/{{x}}/{{y}}.pbf"],
                "minzoom": minz, "maxzoom": maxz,
                "bounds": t.bounds,
                "attribution": "© OpenStreetMap contributors",
            }
        },
        "layers": [
            {"id": "background", "type": "background", "paint": {"background-color": c["bg"]}},
            {"id": "landuse", "type": "fill", "source": "fleetbeat", "source-layer": "landuse",
             "paint": {"fill-color": ["match", ["get", "class"],
                                      "park", c["park"], "grass", c["park"],
                                      "forest", c["park"], "cemetery", c["park"],
                                      c["land"]],
                       "fill-opacity": 0.85}},
            {"id": "water", "type": "fill", "source": "fleetbeat", "source-layer": "water",
             "paint": {"fill-color": c["water"]}},
            {"id": "buildings", "type": "fill", "source": "fleetbeat",
             "source-layer": "buildings", "minzoom": 15,
             "paint": {"fill-color": c["building"], "fill-outline-color": c["building_line"],
                       "fill-opacity": ["interpolate", ["linear"], ["zoom"], 15, 0.4, 17, 0.9]}},
            {"id": "paths", "type": "line", "source": "fleetbeat", "source-layer": "paths",
             "minzoom": 16,
             "paint": {"line-color": c["path"], "line-width": road_width(0.25),
                       "line-dasharray": [2, 2]}},
            {"id": "rail", "type": "line", "source": "fleetbeat", "source-layer": "rail",
             "paint": {"line-color": c["rail"], "line-width": road_width(0.35)}},
            {"id": "roads-case", "type": "line", "source": "fleetbeat",
             "source-layer": "roads", "minzoom": 13,
             "layout": {"line-cap": "round", "line-join": "round"},
             "paint": {"line-color": c["road_case"], "line-width": road_width(1.35)}},
            {"id": "roads-minor", "type": "line", "source": "fleetbeat",
             "source-layer": "roads", "filter": [">=", ["get", "rank"], 5],
             "layout": {"line-cap": "round", "line-join": "round"},
             "paint": {"line-color": c["road"], "line-width": road_width(0.85)}},
            {"id": "roads-major", "type": "line", "source": "fleetbeat",
             "source-layer": "roads", "filter": ["<", ["get", "rank"], 5],
             "layout": {"line-cap": "round", "line-join": "round"},
             "paint": {"line-color": c["road_major"], "line-width": road_width(1.15)}},
            {"id": "road-labels", "type": "symbol", "source": "fleetbeat",
             "source-layer": "roads", "minzoom": 15,
             "filter": ["!=", ["get", "name"], ""],
             "layout": {"symbol-placement": "line", "text-field": ["get", "name"],
                        "text-font": ["Noto Sans Regular"],
                        "text-size": ["interpolate", ["linear"], ["zoom"], 15, 10, 18, 13],
                        "text-letter-spacing": 0.02},
             "paint": {"text-color": c["label"], "text-halo-color": c["label_halo"],
                       "text-halo-width": 1.4}},
            {"id": "place-labels", "type": "symbol", "source": "fleetbeat",
             "source-layer": "places", "minzoom": 16,
             "layout": {"text-field": ["get", "name"], "text-font": ["Noto Sans Regular"],
                        "text-size": 11, "text-anchor": "top", "text-offset": [0, 0.4],
                        "text-max-width": 8},
             "paint": {"text-color": c["poi"], "text-halo-color": c["label_halo"],
                       "text-halo-width": 1.2}},
        ],
    }


def provider_descriptor(base_url: str) -> dict:
    """Tells the frontend which style to load - vendor-neutral by design."""
    from app.core.config import settings

    p = settings.map_provider
    t = tiles()
    common = {
        "provider": p,
        "attribution": settings.map_attribution,
        "center": t.center,
        "bounds": t.bounds,
        "operating_area": "Helsinki city centre, Finland",
    }
    if settings.map_style_url:
        return {**common, "provider": "custom", "style_url": settings.map_style_url}
    if p == "maptiler" and settings.maptiler_key:
        return {**common,
                "style_url": f"https://api.maptiler.com/maps/streets-v2/style.json?key={settings.maptiler_key}",
                "satellite_url": f"https://api.maptiler.com/maps/satellite/style.json?key={settings.maptiler_key}",
                "terrain_url": f"https://api.maptiler.com/maps/outdoor-v2/style.json?key={settings.maptiler_key}"}
    if p == "mapbox" and settings.mapbox_token:
        return {**common, "style_url": "mapbox://styles/mapbox/streets-v12",
                "token": settings.mapbox_token}
    if p == "osm_raster" and settings.map_raster_url_template:
        return {**common, "raster_url": settings.map_raster_url_template}
    # default: our own tiles
    return {**common,
            "style_url": f"{base_url}/style.json",
            "style_url_dark": f"{base_url}/style.json?theme=dark",
            "self_hosted": True}


# --------------------------------------------------------------------------- #
# Geocoding over the real OSM place list
# --------------------------------------------------------------------------- #
class Gazetteer:
    def __init__(self, path: str = PLACES):
        with open(path) as f:
            raw = json.load(f)
        self.bounds = raw["bounds"]
        self.places: list[dict] = raw["places"]
        for p in self.places:
            p["_k"] = _fold(p["name"])
            p["_s"] = _fold(p.get("street") or "")
        # street-name index built from the same extract
        from app.routing.engine import StreetGraph
        g = StreetGraph.instance()
        streets: dict[str, list] = {}
        for e in g.edges:
            if e["name"]:
                streets.setdefault(e["name"], []).append(e["geom"][len(e["geom"]) // 2])
        self.streets = [
            {"name": n, "lon": sum(p[0] for p in pts) / len(pts),
             "lat": sum(p[1] for p in pts) / len(pts), "_k": _fold(n)}
            for n, pts in streets.items()
        ]

    def search(self, query: str, limit: int = 8) -> list[dict]:
        q = _fold(query)
        if len(q) < 2:
            return []
        out: list[tuple[int, dict]] = []
        for s in self.streets:
            if q in s["_k"]:
                rank = 0 if s["_k"].startswith(q) else 1
                out.append((rank, {"type": "street", "name": s["name"],
                                   "lat": s["lat"], "lon": s["lon"],
                                   "subtitle": "Street · Helsinki"}))
        for p in self.places:
            if q in p["_k"] or (p["_s"] and q in p["_s"]):
                rank = 2 if p["_k"].startswith(q) else 3
                sub = (p.get("kind") or p["category"]).replace("_", " ").title()
                if p.get("street"):
                    sub += f" · {p['street']}"
                    if p.get("housenumber"):
                        sub += f" {p['housenumber']}"
                out.append((rank, {"type": "place", "name": p["name"], "lat": p["lat"],
                                   "lon": p["lon"], "subtitle": sub,
                                   "category": p["category"], "kind": p.get("kind")}))
        out.sort(key=lambda r: (r[0], len(r[1]["name"])))
        return [r[1] for r in out[:limit]]

    def by_category(self, kinds: set[str]) -> list[dict]:
        return [p for p in self.places if p.get("kind") in kinds]

    def reverse(self, lon: float, lat: float) -> str:
        from app.routing.engine import get_router, haversine
        street = get_router().snap(lon, lat)[2]
        near = min(self.places, key=lambda p: haversine(lon, lat, p["lon"], p["lat"]),
                   default=None)
        if near and haversine(lon, lat, near["lon"], near["lat"]) < 60:
            return f"{near['name']}, {street}" if street else near["name"]
        return street or "Helsinki"


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower())
                   if not unicodedata.combining(c))


_gaz: Gazetteer | None = None


def gazetteer() -> Gazetteer:
    global _gaz
    if _gaz is None:
        _gaz = Gazetteer()
    return _gaz
