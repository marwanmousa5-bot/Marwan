"""Routing over the real OpenStreetMap street graph.

`RoutingProvider` is the seam: `BuiltinRouter` runs an A* search over the graph
built from the bundled OSM extract, `OSRMRouter` talks to a real OSRM server when
ROUTING_PROVIDER=osrm. Nothing above this module knows which is in use.
"""
from __future__ import annotations

import gzip
import heapq
import json
import math
import os
import threading
from dataclasses import dataclass, field
from typing import Iterable, Protocol

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "data")
GRAPH_PATH = os.path.join(DATA_DIR, "graph.json.gz")

EARTH_R = 6371000.0


def haversine(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def bearing(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    y = math.sin(math.radians(lon2 - lon1)) * math.cos(math.radians(lat2))
    x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
         - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.cos(math.radians(lon2 - lon1)))
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


@dataclass
class RouteLeg:
    distance_m: float
    duration_s: float
    geometry: list[list[float]]
    from_name: str = ""
    to_name: str = ""


@dataclass
class RouteResult:
    distance_m: float
    duration_s: float
    geometry: list[list[float]] = field(default_factory=list)
    legs: list[RouteLeg] = field(default_factory=list)
    street_names: list[str] = field(default_factory=list)
    ok: bool = True
    message: str = ""

    def as_dict(self) -> dict:
        return {
            "distance_m": round(self.distance_m, 1),
            "duration_s": round(self.duration_s, 1),
            "geometry": self.geometry,
            "legs": [
                {"distance_m": round(l.distance_m, 1), "duration_s": round(l.duration_s, 1),
                 "geometry": l.geometry, "from": l.from_name, "to": l.to_name}
                for l in self.legs
            ],
            "streets": self.street_names,
            "ok": self.ok,
            "message": self.message,
        }


class RoutingProvider(Protocol):
    def route(self, waypoints: list[tuple[float, float]],
              avoid_edges: Iterable[int] = ()) -> RouteResult: ...

    def snap(self, lon: float, lat: float) -> tuple[float, float, str]: ...


# --------------------------------------------------------------------------- #
class StreetGraph:
    """Immutable, process-wide graph loaded once from the OSM-derived file."""

    _instance: "StreetGraph | None" = None
    _lock = threading.Lock()

    def __init__(self, path: str = GRAPH_PATH):
        with gzip.open(path, "rt") as f:
            raw = json.load(f)
        self.nodes: list[tuple[float, float]] = [tuple(n) for n in raw["nodes"]]
        self.bounds = raw.get("bounds")
        self.adj: list[list[int]] = [[] for _ in self.nodes]
        self.edges: list[dict] = []
        for a, b, dist, speed, name, cls, geom, wid in raw["edges"]:
            idx = len(self.edges)
            self.edges.append({
                "a": a, "b": b, "d": dist, "v": speed, "name": name,
                "class": cls, "geom": geom, "way": wid,
                "t": dist / max(1.0, speed * 1000.0 / 3600.0),
            })
            self.adj[a].append(idx)

        # Uniform grid index for nearest-edge snapping.
        self._cell = 0.0025  # ~250 m
        self._grid: dict[tuple[int, int], list[int]] = {}
        for i, e in enumerate(self.edges):
            for lon, lat in e["geom"]:
                key = (int(lon / self._cell), int(lat / self._cell))
                self._grid.setdefault(key, []).append(i)
        self.max_speed = max((e["v"] for e in self.edges), default=50)

    @classmethod
    def instance(cls) -> "StreetGraph":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = StreetGraph()
        return cls._instance

    # --- snapping ---------------------------------------------------------
    def nearby_edges(self, lon: float, lat: float, rings: int = 1) -> list[int]:
        cx, cy = int(lon / self._cell), int(lat / self._cell)
        out: list[int] = []
        for dx in range(-rings, rings + 1):
            for dy in range(-rings, rings + 1):
                out.extend(self._grid.get((cx + dx, cy + dy), ()))
        return out

    def snap_to_edge(self, lon: float, lat: float) -> tuple[int, float, tuple[float, float]]:
        """Nearest edge, the distance to it, and the projected point on it."""
        best = (None, float("inf"), (lon, lat))
        rings = 1
        while best[0] is None and rings <= 8:
            for i in self.nearby_edges(lon, lat, rings):
                geom = self.edges[i]["geom"]
                for j in range(len(geom) - 1):
                    p = _project(lon, lat, geom[j], geom[j + 1])
                    d = haversine(lon, lat, p[0], p[1])
                    if d < best[1]:
                        best = (i, d, p)
            rings += 2
        if best[0] is None:  # degenerate: fall back to nearest node
            k = min(range(len(self.nodes)),
                    key=lambda n: haversine(lon, lat, *self.nodes[n]))
            return 0, haversine(lon, lat, *self.nodes[k]), self.nodes[k]
        return best

    def nearest_node(self, lon: float, lat: float) -> int:
        eid, _dist, point = self.snap_to_edge(lon, lat)
        e = self.edges[eid]
        # pick whichever end of the snapped edge is closer to the projection
        da = haversine(point[0], point[1], *self.nodes[e["a"]])
        db = haversine(point[0], point[1], *self.nodes[e["b"]])
        return e["a"] if da <= db else e["b"]

    def street_at(self, lon: float, lat: float) -> str:
        eid, dist, _ = self.snap_to_edge(lon, lat)
        if dist > 120:
            return ""
        return self.edges[eid]["name"] or ""

    # --- search -----------------------------------------------------------
    def shortest_path(self, start: int, goal: int,
                      avoid_edges: set[int] | None = None) -> tuple[list[int], float, float]:
        """A* on travel time. Returns (edge ids, distance_m, duration_s)."""
        if start == goal:
            return [], 0.0, 0.0
        avoid = avoid_edges or set()
        gx, gy = self.nodes[goal]
        best_speed_ms = max(1.0, self.max_speed * 1000.0 / 3600.0)

        def h(n: int) -> float:
            nx, ny = self.nodes[n]
            return haversine(nx, ny, gx, gy) / best_speed_ms

        open_heap = [(h(start), 0.0, start, -1)]
        came: dict[int, int] = {}
        gscore = {start: 0.0}
        closed: set[int] = set()

        while open_heap:
            _f, g, node, via = heapq.heappop(open_heap)
            if node in closed:
                continue
            closed.add(node)
            if via >= 0:
                came[node] = via
            if node == goal:
                break
            for eid in self.adj[node]:
                if eid in avoid:
                    continue
                e = self.edges[eid]
                nxt = e["b"]
                if nxt in closed:
                    continue
                ng = g + e["t"]
                if ng < gscore.get(nxt, float("inf")):
                    gscore[nxt] = ng
                    heapq.heappush(open_heap, (ng + h(nxt), ng, nxt, eid))

        if goal not in came and goal != start:
            return [], 0.0, 0.0

        path: list[int] = []
        cur = goal
        while cur != start:
            eid = came.get(cur)
            if eid is None:
                return [], 0.0, 0.0
            path.append(eid)
            cur = self.edges[eid]["a"]
        path.reverse()
        dist = sum(self.edges[i]["d"] for i in path)
        dur = sum(self.edges[i]["t"] for i in path)
        return path, dist, dur


def _project(lon, lat, a, b):
    """Project (lon,lat) onto segment a-b using a local equirectangular frame."""
    k = math.cos(math.radians(lat))
    ax, ay = a[0] * k, a[1]
    bx, by = b[0] * k, b[1]
    px, py = lon * k, lat
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return (a[0], a[1])
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return (round((ax + t * dx) / k, 7), round(ay + t * dy, 7))


# --------------------------------------------------------------------------- #
class BuiltinRouter:
    """Routes on the bundled OSM graph - no network access required."""

    name = "builtin"

    def __init__(self) -> None:
        self.graph = StreetGraph.instance()

    def snap(self, lon: float, lat: float) -> tuple[float, float, str]:
        eid, dist, point = self.graph.snap_to_edge(lon, lat)
        name = self.graph.edges[eid]["name"] if dist <= 150 else ""
        return point[0], point[1], name

    def route(self, waypoints: list[tuple[float, float]],
              avoid_edges: Iterable[int] = ()) -> RouteResult:
        if len(waypoints) < 2:
            return RouteResult(0, 0, ok=False, message="A route needs at least two points.")
        avoid = set(avoid_edges or ())
        g = self.graph
        legs: list[RouteLeg] = []
        full: list[list[float]] = []
        names: list[str] = []
        total_d = total_t = 0.0

        for i in range(len(waypoints) - 1):
            a_lon, a_lat = waypoints[i]
            b_lon, b_lat = waypoints[i + 1]
            n1 = g.nearest_node(a_lon, a_lat)
            n2 = g.nearest_node(b_lon, b_lat)
            path, dist, dur = g.shortest_path(n1, n2, avoid)
            if not path and n1 != n2:
                return RouteResult(
                    0, 0, ok=False,
                    message="No drivable route exists between these points on the "
                            "mapped street network.",
                )
            geom: list[list[float]] = [[round(a_lon, 6), round(a_lat, 6)]]
            for eid in path:
                e = g.edges[eid]
                for pt in e["geom"]:
                    if not geom or geom[-1] != pt:
                        geom.append(pt)
                if e["name"] and (not names or names[-1] != e["name"]):
                    names.append(e["name"])
            geom.append([round(b_lon, 6), round(b_lat, 6)])

            # connector distance from the real point to the snapped network
            lead = haversine(a_lon, a_lat, *geom[1]) if len(geom) > 1 else 0.0
            tail = haversine(b_lon, b_lat, *geom[-2]) if len(geom) > 1 else 0.0
            dist += lead + tail
            dur += (lead + tail) / 5.5  # walking-pace approach speed

            legs.append(RouteLeg(dist, dur, geom))
            total_d += dist
            total_t += dur
            full.extend(geom if not full else geom[1:])

        return RouteResult(total_d, total_t, full, legs, names)


class OSRMRouter:
    """Talks to an OSRM server. Selected with ROUTING_PROVIDER=osrm."""

    name = "osrm"

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._fallback = BuiltinRouter()

    def snap(self, lon: float, lat: float):
        return self._fallback.snap(lon, lat)

    def route(self, waypoints, avoid_edges=()) -> RouteResult:
        import httpx

        coords = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in waypoints)
        url = f"{self.base_url}/route/v1/driving/{coords}"
        try:
            r = httpx.get(url, params={"overview": "full", "geometries": "geojson",
                                       "steps": "false"}, timeout=6.0)
            r.raise_for_status()
            data = r.json()
            route = data["routes"][0]
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller honestly
            return RouteResult(0, 0, ok=False,
                               message=f"The routing service did not respond ({exc}).")
        geom = [[round(c[0], 6), round(c[1], 6)] for c in route["geometry"]["coordinates"]]
        legs = [RouteLeg(l["distance"], l["duration"], []) for l in route.get("legs", [])]
        return RouteResult(route["distance"], route["duration"], geom, legs)


_provider: RoutingProvider | None = None


def get_router() -> RoutingProvider:
    global _provider
    if _provider is None:
        from app.core.config import settings
        if settings.routing_provider == "osrm" and settings.osrm_url:
            _provider = OSRMRouter(settings.osrm_url)
        else:
            _provider = BuiltinRouter()
    return _provider
