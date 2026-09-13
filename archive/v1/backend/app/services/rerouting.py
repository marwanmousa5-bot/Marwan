"""Exception Auto-Rerouting (Section 4 item 8, Section 4e).

The name is the one part of this feature that has to be read carefully. It is
*automatic detection*, not automatic application: FleetBeat notices when an
active route runs through a road closure or a severe-weather zone, works out
a genuine alternative through OSRM, and puts it in front of a dispatcher as a
proposal with the extra distance and time spelled out. Nothing is switched
until a person confirms it (Section 9) - a route that changes underneath a
driver who is already on it is worse than a delay.

Detection is ours, not the model's. A road closure either lies on the decoded
route geometry or it does not, and that is a geometry question.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal
from app.core.errors import ValidationError
from app.core.tenancy import TenantScope
from app.integrations.osrm import RoutingUnavailableError
from app.models.enums import AuditAction, TaskStatus
from app.models.routing import RoadClosure, Route
from app.models.task import Task
from app.models.vehicle import Vehicle
from app.models.weather import WeatherZone
from app.services import audit, geo, routing
from app.services.notifications import Notification, get_push_service

logger = logging.getLogger("fleetbeat.rerouting")

#: How far off the closure the detour waypoint is pushed, as a multiple of the
#: closure radius. Too small and OSRM routes straight back through it; too
#: large and the detour stops resembling the shortest way round.
DETOUR_OFFSET_FACTOR = 2.5

#: A weather zone only justifies proposing a reroute above this much delay.
WEATHER_DELAY_THRESHOLD_MINUTES = 15

OPEN_TASK_STATUSES = (TaskStatus.ASSIGNED, TaskStatus.ACCEPTED, TaskStatus.EN_ROUTE)


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class Obstruction:
    """Something sitting on an active route."""

    kind: str  # "closure" | "weather"
    obstruction_id: uuid.UUID
    label: str
    latitude: float
    longitude: float
    radius_m: float
    expected_delay_minutes: int = 0


@dataclass(slots=True)
class RerouteProposal:
    """A computed alternative. Nothing has been applied."""

    task_id: uuid.UUID
    task_title: str
    route_id: uuid.UUID
    vehicle_id: uuid.UUID | None
    driver_id: uuid.UUID | None
    obstruction: Obstruction
    #: None when the routing engine could not be reached - the obstruction is
    #: still reported, without a fabricated alternative.
    added_km: float | None = None
    added_minutes: float | None = None
    new_distance_km: float | None = None
    new_eta: datetime | None = None
    detour_latitude: float | None = None
    detour_longitude: float | None = None
    routing_available: bool = True

    @property
    def dedupe_key(self) -> str:
        return f"reroute:{self.task_id}:{self.obstruction.obstruction_id}"


async def active_obstructions(
    db: AsyncSession, organization_id: uuid.UUID, *, now: datetime | None = None
) -> list[Obstruction]:
    """Closures in force right now, plus weather bad enough to route around."""
    moment = now or utcnow()
    obstructions: list[Obstruction] = []

    closures = (
        await db.execute(
            sa.select(RoadClosure).where(
                RoadClosure.organization_id == organization_id,
                RoadClosure.is_active.is_(True),
            )
        )
    ).scalars().all()
    for closure in closures:
        start = _aware(closure.active_from)
        end = _aware(closure.active_until)
        if start and start > moment:
            continue
        if end and end < moment:
            continue
        obstructions.append(
            Obstruction(
                kind="closure",
                obstruction_id=closure.id,
                label=closure.label,
                latitude=closure.latitude,
                longitude=closure.longitude,
                radius_m=closure.radius_m,
            )
        )

    zones = (
        await db.execute(
            sa.select(WeatherZone).where(
                WeatherZone.organization_id == organization_id,
                WeatherZone.expected_delay_minutes
                >= WEATHER_DELAY_THRESHOLD_MINUTES,
            )
        )
    ).scalars().all()
    for zone in zones:
        obstructions.append(
            Obstruction(
                kind="weather",
                obstruction_id=zone.id,
                label=zone.condition.replace("_", " "),
                latitude=zone.latitude,
                longitude=zone.longitude,
                radius_m=zone.radius_m,
                expected_delay_minutes=zone.expected_delay_minutes,
            )
        )

    return obstructions


async def detect(
    db: AsyncSession, organization_id: uuid.UUID, *, now: datetime | None = None
) -> list[tuple[Task, Route, Obstruction]]:
    """Active routes whose real geometry runs into an obstruction."""
    obstructions = await active_obstructions(db, organization_id, now=now)
    if not obstructions:
        return []

    rows = (
        await db.execute(
            sa.select(Task, Route)
            .join(Route, Route.task_id == Task.id)
            .where(
                Task.organization_id == organization_id,
                Task.status.in_(OPEN_TASK_STATUSES),
                Route.is_active.is_(True),
            )
        )
    ).all()

    hits: list[tuple[Task, Route, Obstruction]] = []
    for task, route in rows:
        path = geo.decode_polyline(route.geometry_polyline or "")
        if not path:
            # No stored geometry to judge - fall back to the straight line
            # between the endpoints rather than claiming the route is clear.
            path = [
                (route.origin_latitude, route.origin_longitude),
                (route.destination_latitude, route.destination_longitude),
            ]
        for obstruction in obstructions:
            if geo.path_enters_circle(
                path, obstruction.latitude, obstruction.longitude, obstruction.radius_m
            ):
                hits.append((task, route, obstruction))
                break  # One proposal per route at a time.

    return hits


async def propose(
    db: AsyncSession,
    scope: TenantScope,
    *,
    task: Task,
    route: Route,
    obstruction: Obstruction,
) -> RerouteProposal:
    """Compute the alternative. This writes nothing."""
    proposal = RerouteProposal(
        task_id=task.id,
        task_title=task.title,
        route_id=route.id,
        vehicle_id=task.vehicle_id,
        driver_id=task.driver_id,
        obstruction=obstruction,
    )

    origin = await _origin_for(db, scope, route=route, task=task)
    destination = (route.destination_latitude, route.destination_longitude)
    detour = _detour_waypoint(origin, destination, obstruction)
    proposal.detour_latitude, proposal.detour_longitude = detour

    try:
        preview = await routing.preview_route(
            origin=origin, destination=destination, waypoints=[detour]
        )
    except RoutingUnavailableError:
        # Report the obstruction honestly instead of inventing a detour.
        logger.warning(
            "Routing engine unavailable while proposing a reroute for task %s", task.id
        )
        proposal.routing_available = False
        return proposal

    proposal.new_distance_km = preview.distance_km
    proposal.new_eta = preview.eta
    if route.distance_km is not None:
        proposal.added_km = round(preview.distance_km - route.distance_km, 2)
    if route.duration_seconds is not None:
        proposal.added_minutes = round(
            preview.duration_minutes - route.duration_seconds / 60.0, 1
        )
    return proposal


async def apply_reroute(
    db: AsyncSession,
    scope: TenantScope,
    *,
    task_id: uuid.UUID,
    obstruction_id: uuid.UUID,
    principal: Principal,
    request: Request | None = None,
) -> Route:
    """Switch a task onto the alternative. Only ever called from a confirm.

    Recomputed here rather than trusting a geometry carried in the payload:
    the proposal may be minutes old, and the vehicle has moved since.
    """
    task = await scope.get_or_404(db, Task, task_id, label="Task")
    if task.status not in OPEN_TASK_STATUSES:
        raise ValidationError("That task is no longer running, so it cannot be rerouted")

    current = (
        await db.execute(
            scope.select(Route)
            .where(Route.task_id == task.id, Route.is_active.is_(True))
            .order_by(Route.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if current is None:
        raise ValidationError("That task has no active route to replace")

    obstructions = await active_obstructions(db, scope.organization_id)
    obstruction = next(
        (o for o in obstructions if o.obstruction_id == obstruction_id), None
    )
    if obstruction is None:
        raise ValidationError(
            "That closure is no longer in force - the original route is fine"
        )

    proposal = await propose(
        db, scope, task=task, route=current, obstruction=obstruction
    )
    if not proposal.routing_available:
        raise RoutingUnavailableError(
            "The routing engine is not reachable, so no alternative can be "
            "computed. The route has been left exactly as it was."
        )

    origin = await _origin_for(db, scope, route=current, task=task)
    preview = await routing.preview_route(
        origin=origin,
        destination=(current.destination_latitude, current.destination_longitude),
        waypoints=[(proposal.detour_latitude, proposal.detour_longitude)],
    )

    new_route = await routing.persist_route(
        db,
        scope,
        preview=preview,
        task_id=task.id,
        vehicle_id=task.vehicle_id,
        driver_id=task.driver_id,
        name=current.name,
        replaced_route_id=current.id,
        reroute_reason=f"{obstruction.kind}: {obstruction.label}",
    )
    # Snapshot before mutating, or the audit diff records the new ETA as the
    # old one and shows no change at all.
    before = {
        "route_id": current.id,
        "eta": task.eta,
        "distance_km": current.distance_km,
    }
    current.is_active = False
    task.route_id = new_route.id
    task.eta = preview.eta

    await audit.record(
        db,
        action=AuditAction.ROUTE_REROUTED,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="task",
        entity_id=task.id,
        summary=(
            f"Rerouted '{task.title}' around {obstruction.label} "
            f"({proposal.added_km:+} km, {proposal.added_minutes:+} min)"
            if proposal.added_km is not None and proposal.added_minutes is not None
            else f"Rerouted '{task.title}' around {obstruction.label}"
        ),
        changes=audit.diff(
            before,
            {
                "route_id": new_route.id,
                "eta": preview.eta,
                "distance_km": preview.distance_km,
            },
        ),
        request=request,
    )

    # The driver is mid-task: they need to be told, not left to notice.
    if task.driver_id:
        await get_push_service().send(
            Notification(
                channel="push",
                recipient=str(task.driver_id),
                subject="Your route has changed",
                body=(
                    f"'{task.title}' now avoids {obstruction.label}. "
                    "Open the task for the new route."
                ),
                metadata={"task_id": str(task.id), "route_id": str(new_route.id)},
            )
        )

    await db.flush()
    return new_route


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def _origin_for(
    db: AsyncSession, scope: TenantScope, *, route: Route, task: Task
) -> tuple[float, float]:
    """Reroute from where the vehicle is now, not from where it set off."""
    if task.vehicle_id:
        vehicle = await scope.get(db, Vehicle, task.vehicle_id)
        if vehicle and vehicle.last_latitude is not None:
            return vehicle.last_latitude, vehicle.last_longitude
    return route.origin_latitude, route.origin_longitude


def _detour_waypoint(
    origin: tuple[float, float],
    destination: tuple[float, float],
    obstruction: Obstruction,
) -> tuple[float, float]:
    """A point beside the obstruction, offset across the direction of travel.

    OSRM has no "avoid this area" parameter, so the way to route around
    something is to give it a waypoint on the far side of it. Offsetting
    perpendicular to the origin->destination bearing keeps the detour on the
    line the vehicle was already travelling rather than sending it backwards.
    """
    heading = geo.bearing_deg(origin[0], origin[1], destination[0], destination[1])
    offset_m = obstruction.radius_m * DETOUR_OFFSET_FACTOR

    left = geo.destination_point(
        obstruction.latitude, obstruction.longitude, (heading - 90) % 360, offset_m
    )
    right = geo.destination_point(
        obstruction.latitude, obstruction.longitude, (heading + 90) % 360, offset_m
    )

    # Take whichever side keeps the detour shorter overall.
    def detour_length(point: tuple[float, float]) -> float:
        return geo.haversine_m(
            origin[0], origin[1], point[0], point[1]
        ) + geo.haversine_m(point[0], point[1], destination[0], destination[1])

    return left if detour_length(left) <= detour_length(right) else right
