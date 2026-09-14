"""Route building, optimisation, ETA projection and progress tracking."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from itertools import permutations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Route, RouteStop
from app.routing.engine import RouteResult, get_router, haversine


def waypoints_of(route: Route) -> list[tuple[float, float]]:
    pts = [(route.origin_lon, route.origin_lat)]
    pts.extend((s.lon, s.lat) for s in sorted(route.stops, key=lambda s: s.sequence))
    pts.append((route.dest_lon, route.dest_lat))
    return pts


def calculate(waypoints: list[tuple[float, float]],
              avoid_edges: list[int] | None = None) -> RouteResult:
    return get_router().route(waypoints, avoid_edges or [])


async def recalculate(session: AsyncSession, route: Route) -> RouteResult:
    """Recompute geometry/distance/duration after any stop edit."""
    result = calculate(waypoints_of(route), route.avoid_edges)
    if not result.ok:
        return result
    route.geometry = result.geometry
    route.distance_m = result.distance_m
    route.duration_s = result.duration_s
    route.legs = [
        {"distance_m": round(l.distance_m, 1), "duration_s": round(l.duration_s, 1)}
        for l in result.legs
    ]
    _project_stop_times(route)
    await session.flush()
    return result


def _project_stop_times(route: Route, depart: datetime | None = None) -> None:
    """Planned arrival per stop = cumulative leg time + service time."""
    depart = depart or route.started_at or datetime.now(timezone.utc)
    clock = depart
    stops = sorted(route.stops, key=lambda s: s.sequence)
    for i, stop in enumerate(stops):
        leg = route.legs[i] if i < len(route.legs) else {"duration_s": 0}
        clock = clock + timedelta(seconds=leg.get("duration_s", 0))
        stop.planned_arrival = clock
        clock = clock + timedelta(minutes=stop.service_minutes or 0)


def optimise(origin: tuple[float, float], stops: list[dict],
             destination: tuple[float, float]) -> dict:
    """Reorder stops to cut travel time.

    Exact for small stop counts (the common dispatch case); nearest-neighbour
    plus 2-opt beyond that, so the call always returns quickly.
    """
    if len(stops) < 2:
        return {"order": list(range(len(stops))), "improved": False}

    router = get_router()

    def cost(order: tuple[int, ...]) -> float:
        pts = [origin] + [(stops[i]["lon"], stops[i]["lat"]) for i in order] + [destination]
        r = router.route(list(pts))
        return r.duration_s if r.ok else float("inf")

    base_order = tuple(range(len(stops)))
    base = cost(base_order)

    if len(stops) <= 6:
        best_order, best = base_order, base
        for perm in permutations(base_order):
            if perm == base_order:
                continue
            c = cost(perm)
            if c < best:
                best_order, best = perm, c
    else:
        # nearest neighbour seed
        remaining = set(base_order)
        cur = origin
        seed: list[int] = []
        while remaining:
            nxt = min(remaining, key=lambda i: haversine(cur[0], cur[1],
                                                         stops[i]["lon"], stops[i]["lat"]))
            seed.append(nxt)
            cur = (stops[nxt]["lon"], stops[nxt]["lat"])
            remaining.discard(nxt)
        best_order, best = tuple(seed), cost(tuple(seed))
        improved = True
        while improved:
            improved = False
            for i in range(len(best_order) - 1):
                for j in range(i + 2, len(best_order)):
                    cand = best_order[:i + 1] + best_order[i + 1:j + 1][::-1] + best_order[j + 1:]
                    c = cost(cand)
                    if c < best - 1:
                        best_order, best, improved = cand, c, True
    saved = base - best
    return {
        "order": list(best_order),
        "improved": saved > 1,
        "before_duration_s": round(base, 1),
        "after_duration_s": round(best, 1),
        "saved_duration_s": round(max(0.0, saved), 1),
    }


def progress(route: Route, lat: float, lon: float) -> dict:
    """How far along its planned geometry a vehicle is, and what remains."""
    geom = route.geometry or []
    if len(geom) < 2:
        return {"progress_pct": 0.0, "remaining_m": route.distance_m,
                "travelled_m": 0.0, "nearest_index": 0, "deviation_m": 0.0}

    best_i, best_d = 0, float("inf")
    for i, (glon, glat) in enumerate(geom):
        d = haversine(lon, lat, glon, glat)
        if d < best_d:
            best_i, best_d = i, d

    travelled = 0.0
    for i in range(best_i):
        travelled += haversine(geom[i][0], geom[i][1], geom[i + 1][0], geom[i + 1][1])
    total = 0.0
    for i in range(len(geom) - 1):
        total += haversine(geom[i][0], geom[i][1], geom[i + 1][0], geom[i + 1][1])
    total = total or route.distance_m or 1.0
    return {
        "progress_pct": round(min(100.0, travelled / total * 100), 1),
        "travelled_m": round(travelled, 1),
        "remaining_m": round(max(0.0, total - travelled), 1),
        "nearest_index": best_i,
        "deviation_m": round(best_d, 1),
    }


def eta_from(route: Route, lat: float, lon: float, speed_kph: float | None = None,
             now: datetime | None = None) -> datetime | None:
    """Projected arrival at the route's destination from the current position."""
    now = now or datetime.now(timezone.utc)
    p = progress(route, lat, lon)
    remaining_m = p["remaining_m"]
    if remaining_m <= 0:
        return now
    if route.distance_m > 0 and route.duration_s > 0:
        planned_speed_ms = route.distance_m / route.duration_s
    else:
        planned_speed_ms = 8.0
    live = (speed_kph or 0) / 3.6
    # blend planned pace with observed pace so the ETA reacts but does not jitter
    effective = max(2.0, 0.7 * planned_speed_ms + 0.3 * live) if live > 1 else planned_speed_ms
    return now + timedelta(seconds=remaining_m / max(effective, 1.0))


def remaining_geometry(route: Route, lat: float, lon: float) -> list[list[float]]:
    geom = route.geometry or []
    if not geom:
        return []
    idx = progress(route, lat, lon)["nearest_index"]
    return [[round(lon, 6), round(lat, 6)]] + geom[idx + 1:]


def travelled_geometry(route: Route, lat: float, lon: float) -> list[list[float]]:
    geom = route.geometry or []
    if not geom:
        return []
    idx = progress(route, lat, lon)["nearest_index"]
    return geom[:idx + 1]
