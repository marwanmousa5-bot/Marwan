"""Route planning on top of the real routing engine (Section 4 item 8).

Everything here calls OSRM. Stop *sequencing* is never changed: multi-stop
optimization is out of scope for MVP (Section 9), so the order a dispatcher
chose is the order driven.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.core.tenancy import TenantScope
from app.integrations.osrm import RouteResult, get_osrm_client
from app.models.routing import Route, RouteStop
from app.models.vehicle import Vehicle


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class RoutePreview:
    """What the dispatcher sees before committing to a task."""

    distance_km: float
    duration_minutes: float
    eta: datetime
    geometry_polyline: str | None
    origin: tuple[float, float]
    destination: tuple[float, float]
    waypoints: list[tuple[float, float]]


async def origin_for_driver(
    db: AsyncSession, scope: TenantScope, *, vehicle_id: uuid.UUID | None
) -> tuple[float, float] | None:
    """Where a route should start: the vehicle's last known position."""
    if vehicle_id is None:
        return None
    vehicle = await scope.get(db, Vehicle, vehicle_id)
    if vehicle is None or vehicle.last_latitude is None or vehicle.last_longitude is None:
        return None
    return vehicle.last_latitude, vehicle.last_longitude


async def preview_route(
    *,
    origin: tuple[float, float],
    destination: tuple[float, float],
    waypoints: list[tuple[float, float]] | None = None,
    depart_at: datetime | None = None,
) -> RoutePreview:
    """Ask OSRM for the real road route and derive an ETA."""
    points = [origin, *(waypoints or []), destination]
    result: RouteResult = await get_osrm_client().route(points)

    departure = depart_at or utcnow()
    return RoutePreview(
        distance_km=result.distance_km,
        duration_minutes=result.duration_minutes,
        eta=departure + timedelta(seconds=result.duration_s),
        geometry_polyline=result.geometry_polyline,
        origin=origin,
        destination=destination,
        waypoints=list(waypoints or []),
    )


async def persist_route(
    db: AsyncSession,
    scope: TenantScope,
    *,
    preview: RoutePreview,
    task_id: uuid.UUID | None = None,
    vehicle_id: uuid.UUID | None = None,
    driver_id: uuid.UUID | None = None,
    name: str | None = None,
    replaced_route_id: uuid.UUID | None = None,
    reroute_reason: str | None = None,
) -> Route:
    """Store a computed route and its stops."""
    route = Route(
        name=name,
        vehicle_id=vehicle_id,
        driver_id=driver_id,
        task_id=task_id,
        origin_latitude=preview.origin[0],
        origin_longitude=preview.origin[1],
        destination_latitude=preview.destination[0],
        destination_longitude=preview.destination[1],
        distance_km=preview.distance_km,
        duration_seconds=int(preview.duration_minutes * 60),
        geometry_polyline=preview.geometry_polyline,
        eta=preview.eta,
        replaced_route_id=replaced_route_id,
        reroute_reason=reroute_reason,
    )
    scope.assign(route)
    db.add(route)
    await db.flush()

    for index, (lat, lng) in enumerate([*preview.waypoints, preview.destination]):
        stop = RouteStop(
            route_id=route.id,
            sequence=index,
            latitude=lat,
            longitude=lng,
            label="Destination" if index == len(preview.waypoints) else f"Stop {index + 1}",
        )
        scope.assign(stop)
        db.add(stop)

    await db.flush()
    return route


async def deactivate_routes_for_task(
    db: AsyncSession, scope: TenantScope, *, task_id: uuid.UUID
) -> None:
    await db.execute(
        sa.update(Route)
        .where(Route.organization_id == scope.organization_id, Route.task_id == task_id)
        .values(is_active=False)
    )


def parse_waypoints(raw: list[dict] | None) -> list[tuple[float, float]]:
    """Validate ``[{"lat": .., "lng": ..}]`` into coordinate pairs."""
    points: list[tuple[float, float]] = []
    for entry in raw or []:
        try:
            lat = float(entry["lat"])
            lng = float(entry["lng"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(
                "Each waypoint must have numeric 'lat' and 'lng' values"
            ) from exc
        if not -90 <= lat <= 90 or not -180 <= lng <= 180:
            raise ValidationError(f"Waypoint out of range: {lat}, {lng}")
        points.append((lat, lng))
    return points
