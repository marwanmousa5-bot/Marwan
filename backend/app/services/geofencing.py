"""Geofence evaluation - emits enter/exit edges, never repeated 'inside' events."""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import GeofenceTrigger, Severity
from app.models import Geofence, GeofenceState
from app.services import alerts as alert_svc


def point_in_polygon(lon: float, lat: float, poly: list) -> bool:
    """Ray casting. `poly` is [[lon,lat], ...]."""
    inside = False
    n = len(poly)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def contains(fence: Geofence, lon: float, lat: float) -> bool:
    if fence.type == "circle":
        if fence.centre_lat is None or fence.radius_m is None:
            return False
        from app.routing.engine import haversine
        return haversine(lon, lat, fence.centre_lon, fence.centre_lat) <= fence.radius_m
    return point_in_polygon(lon, lat, fence.polygon or [])


def centroid(fence: Geofence) -> tuple[float, float]:
    if fence.type == "circle":
        return fence.centre_lon, fence.centre_lat
    pts = fence.polygon or []
    if not pts:
        return 0.0, 0.0
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def area_km2(fence: Geofence) -> float:
    if fence.type == "circle":
        return round(math.pi * (fence.radius_m or 0) ** 2 / 1e6, 3)
    pts = fence.polygon or []
    if len(pts) < 3:
        return 0.0
    # equirectangular projection about the centroid is plenty at city scale
    lat0 = sum(p[1] for p in pts) / len(pts)
    k = math.cos(math.radians(lat0)) * 111_320
    xy = [(p[0] * k, p[1] * 110_540) for p in pts]
    s = 0.0
    for i in range(len(xy)):
        x1, y1 = xy[i]
        x2, y2 = xy[(i + 1) % len(xy)]
        s += x1 * y2 - x2 * y1
    return round(abs(s) / 2 / 1e6, 3)


async def evaluate(session: AsyncSession, *, org_id: uuid.UUID, vehicle,
                   lon: float, lat: float, fences: list[Geofence] | None = None,
                   states: dict | None = None,
                   now: datetime | None = None) -> list[tuple[Geofence, str]]:
    """Compare current position against every applicable fence.

    Returns the (fence, 'enter'|'exit') transitions that actually happened.
    Callers may pass pre-loaded fences/states to avoid per-tick queries.
    """
    now = now or datetime.now(timezone.utc)
    if fences is None:
        fences = (await session.execute(
            select(Geofence).where(Geofence.organization_id == org_id,
                                   Geofence.is_active.is_(True))
        )).scalars().all()

    transitions: list[tuple[Geofence, str]] = []
    for fence in fences:
        scope = {str(v) for v in (fence.vehicle_ids or [])}
        if scope and str(vehicle.id) not in scope:
            continue
        now_inside = contains(fence, lon, lat)
        key = (fence.id, vehicle.id)
        state = (states or {}).get(key)
        if state is None:
            state = (await session.execute(
                select(GeofenceState).where(GeofenceState.geofence_id == fence.id,
                                            GeofenceState.vehicle_id == vehicle.id)
            )).scalars().first()
            if state is None:
                state = GeofenceState(organization_id=org_id, geofence_id=fence.id,
                                      vehicle_id=vehicle.id, inside=now_inside,
                                      changed_at=now)
                session.add(state)
                if states is not None:
                    states[key] = state
                continue  # first observation establishes a baseline, not an event
            if states is not None:
                states[key] = state

        if state.inside == now_inside:
            continue
        state.inside = now_inside
        state.changed_at = now
        direction = "enter" if now_inside else "exit"
        wanted = fence.trigger
        if wanted != GeofenceTrigger.BOTH and wanted != direction:
            continue
        transitions.append((fence, direction))

        if fence.is_restricted and direction == "enter":
            code, title, severity = ("geofence_unauthorized",
                                     f"{vehicle.name} entered restricted zone {fence.name}",
                                     Severity.CRITICAL)
        else:
            code = f"geofence_{direction}"
            verb = "entered" if direction == "enter" else "left"
            title, severity = f"{vehicle.name} {verb} {fence.name}", None
        await alert_svc.raise_alert(
            session, org_id=org_id, code=code, title=title, severity=severity,
            vehicle_id=vehicle.id, driver_id=vehicle.driver_id, geofence_id=fence.id,
            lat=lat, lon=lon, dedupe_extra=f"{fence.id}:{direction}",
            evidence={"geofence": fence.name, "direction": direction},
            now=now,
        )
    return transitions
