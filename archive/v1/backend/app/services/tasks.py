"""Dispatch tasks and their lifecycle (Section 4f).

The four-state lifecycle is mandatory and enforced here rather than in the UI:

    assigned -> accepted -> en_route -> completed

with ``cancelled`` reachable from any non-terminal state. A Task is the
*assignment*; accepting one links it to a Trip, which is the recorded
execution, so the driven path shows up later in Trip History Playback.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal
from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.core.tenancy import TenantScope
from app.models.driver import Driver
from app.models.enums import AuditAction, TaskStatus, TripStatus
from app.models.task import Task
from app.models.tracking import Trip
from app.models.vehicle import Vehicle
from app.services import audit, routing
from app.services.notifications import Notification, get_push_service

#: Which states each state may move to. Anything else is rejected.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    TaskStatus.ASSIGNED: frozenset({TaskStatus.ACCEPTED, TaskStatus.CANCELLED}),
    TaskStatus.ACCEPTED: frozenset({TaskStatus.EN_ROUTE, TaskStatus.CANCELLED}),
    TaskStatus.EN_ROUTE: frozenset({TaskStatus.COMPLETED, TaskStatus.CANCELLED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

AUDITED_FIELDS = [
    "title",
    "status",
    "driver_id",
    "vehicle_id",
    "priority",
    "due_at",
    "destination_label",
]


def utcnow() -> datetime:
    return datetime.now(UTC)


async def list_tasks(
    db: AsyncSession,
    scope: TenantScope,
    *,
    status: TaskStatus | None = None,
    driver_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Task], int]:
    stmt = scope.select(Task)
    if status is not None:
        stmt = stmt.where(Task.status == status)
    if driver_id is not None:
        stmt = stmt.where(Task.driver_id == driver_id)

    total = int(
        (await db.execute(sa.select(sa.func.count()).select_from(stmt.subquery())))
        .scalar_one()
    )
    result = await db.execute(
        stmt.order_by(Task.due_at.asc().nullslast(), Task.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().unique().all()), total


async def get_task(db: AsyncSession, scope: TenantScope, task_id: uuid.UUID) -> Task:
    return await scope.get_or_404(db, Task, task_id, label="Task")


async def _resolve_vehicle(
    db: AsyncSession, scope: TenantScope, *, driver_id: uuid.UUID | None
) -> uuid.UUID | None:
    """A task follows the driver's currently assigned vehicle."""
    if driver_id is None:
        return None
    driver = await scope.get(db, Driver, driver_id)
    if driver is None:
        raise NotFoundError("Driver not found")
    return driver.assigned_vehicle_id


async def create_task(
    db: AsyncSession,
    scope: TenantScope,
    *,
    data: dict,
    principal: Principal | None = None,
    request: Request | None = None,
    compute_route: bool = True,
) -> Task:
    driver_id = data.get("driver_id")
    vehicle_id = await _resolve_vehicle(db, scope, driver_id=driver_id)

    waypoints = data.get("waypoints") or []
    task = Task(
        **{k: v for k, v in data.items() if k != "waypoints"},
        waypoints=waypoints,
        vehicle_id=vehicle_id,
        status=TaskStatus.ASSIGNED,
        created_by_user_id=principal.user_id if principal else None,
    )
    scope.assign(task)
    db.add(task)
    await db.flush()

    if compute_route:
        await attach_route(db, scope, task=task)

    await audit.record(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="task",
        entity_id=task.id,
        summary=f"Task '{task.title}' assigned",
        changes={"after": audit.snapshot(task, AUDITED_FIELDS)},
        request=request,
    )
    await notify_driver(db, scope, task=task, reason="assigned")
    return task


async def attach_route(
    db: AsyncSession, scope: TenantScope, *, task: Task
) -> None:
    """Compute and store the route for a task, if an origin is known.

    Routing failures never block dispatch: a task with no route is still a
    valid instruction, and the driver's app recomputes from their real
    position when they start.
    """
    origin = await routing.origin_for_driver(db, scope, vehicle_id=task.vehicle_id)
    if origin is None:
        return

    try:
        preview = await routing.preview_route(
            origin=origin,
            destination=(task.destination_latitude, task.destination_longitude),
            waypoints=routing.parse_waypoints(task.waypoints),
        )
    except Exception:  # noqa: BLE001 - routing is best-effort at create time
        return

    await routing.deactivate_routes_for_task(db, scope, task_id=task.id)
    route = await routing.persist_route(
        db,
        scope,
        preview=preview,
        task_id=task.id,
        vehicle_id=task.vehicle_id,
        driver_id=task.driver_id,
        name=task.title,
    )
    task.route_id = route.id
    task.eta = preview.eta
    await db.flush()


async def transition(
    db: AsyncSession,
    scope: TenantScope,
    *,
    task_id: uuid.UUID,
    to_status: TaskStatus,
    principal: Principal | None = None,
    request: Request | None = None,
    completion_note: str | None = None,
    completion_photo_url: str | None = None,
    cancellation_reason: str | None = None,
    acting_driver_id: uuid.UUID | None = None,
) -> Task:
    """Move a task through its lifecycle, enforcing the allowed transitions."""
    task = await get_task(db, scope, task_id)

    if acting_driver_id is not None and task.driver_id != acting_driver_id:
        # A driver may only act on their own tasks.
        raise NotFoundError("Task not found")

    allowed = ALLOWED_TRANSITIONS.get(task.status, frozenset())
    if to_status not in allowed:
        raise ValidationError(
            f"A task in '{task.status}' cannot move to '{to_status}'"
        )

    before = task.status
    task.status = to_status
    now = utcnow()

    if to_status == TaskStatus.ACCEPTED:
        task.accepted_at = now
    elif to_status == TaskStatus.EN_ROUTE:
        task.started_at = now
        await _link_trip(db, scope, task=task, now=now)
    elif to_status == TaskStatus.COMPLETED:
        task.completed_at = now
        task.completion_note = completion_note
        task.completion_photo_url = completion_photo_url
        await _close_trip(db, scope, task=task, now=now)
    elif to_status == TaskStatus.CANCELLED:
        task.cancelled_at = now
        task.cancellation_reason = cancellation_reason
        await routing.deactivate_routes_for_task(db, scope, task_id=task.id)

    await db.flush()
    await audit.record(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="task",
        entity_id=task.id,
        summary=f"Task '{task.title}': {before} -> {to_status}",
        changes={"before": {"status": before}, "after": {"status": str(to_status)}},
        request=request,
    )
    return task


async def _link_trip(
    db: AsyncSession, scope: TenantScope, *, task: Task, now: datetime
) -> None:
    """Bind the task to the vehicle's current trip, or open one for it.

    This is what makes a task's actual driven path replayable afterwards
    (Section 4f: a Task is the assignment, a Trip is its recorded execution).
    """
    if task.vehicle_id is None:
        return

    open_trip = await db.execute(
        scope.select(Trip)
        .where(Trip.vehicle_id == task.vehicle_id, Trip.status == TripStatus.IN_PROGRESS)
        .order_by(Trip.started_at.desc())
        .limit(1)
    )
    trip = open_trip.scalar_one_or_none()

    if trip is None:
        vehicle = await scope.get(db, Vehicle, task.vehicle_id)
        trip = Trip(
            organization_id=scope.organization_id,
            vehicle_id=task.vehicle_id,
            driver_id=task.driver_id,
            task_id=task.id,
            status=TripStatus.IN_PROGRESS,
            started_at=now,
            start_latitude=vehicle.last_latitude if vehicle else None,
            start_longitude=vehicle.last_longitude if vehicle else None,
            start_odometer_km=vehicle.odometer_km if vehicle else None,
        )
        db.add(trip)
        await db.flush()
    elif trip.task_id is None:
        trip.task_id = task.id

    task.trip_id = trip.id


async def _close_trip(
    db: AsyncSession, scope: TenantScope, *, task: Task, now: datetime
) -> None:
    """Completing a task does not force its trip closed.

    The vehicle may drive straight on to the next job; the tracking loop
    closes the trip when the vehicle actually stops. Only a trip opened
    specifically for this task, with no movement recorded, is tidied away.
    """
    if task.trip_id is None:
        return
    trip = await scope.get(db, Trip, task.trip_id)
    if trip is None or trip.status != TripStatus.IN_PROGRESS:
        return
    if trip.task_id == task.id and trip.distance_km == 0:
        trip.status = TripStatus.COMPLETED
        trip.ended_at = now


async def reassign(
    db: AsyncSession,
    scope: TenantScope,
    *,
    task_id: uuid.UUID,
    driver_id: uuid.UUID,
    principal: Principal | None = None,
    request: Request | None = None,
) -> Task:
    """Hand a task to a different driver.

    A first-class action, but only before acceptance: once a driver has
    accepted, they may already be on their way, and silently moving the job
    out from under them is how dispatch mistakes happen (Section 4f).
    """
    task = await get_task(db, scope, task_id)
    if task.status != TaskStatus.ASSIGNED:
        raise ValidationError(
            "A task can only be reassigned before the driver has accepted it. "
            "Cancel it and create a new one instead."
        )

    previous_driver = task.driver_id
    task.driver_id = driver_id
    task.vehicle_id = await _resolve_vehicle(db, scope, driver_id=driver_id)
    await attach_route(db, scope, task=task)
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="task",
        entity_id=task.id,
        summary=f"Task '{task.title}' reassigned",
        changes={
            "before": {"driver_id": str(previous_driver) if previous_driver else None},
            "after": {"driver_id": str(driver_id)},
        },
        request=request,
    )
    await notify_driver(db, scope, task=task, reason="reassigned")
    return task


async def notify_driver(
    db: AsyncSession, scope: TenantScope, *, task: Task, reason: str
) -> None:
    """Push a new or reassigned task to the driver's device (Section 4f).

    Goes through the NotificationService abstraction, so wiring a real push
    provider later does not touch dispatch logic.
    """
    if task.driver_id is None:
        return
    driver = await scope.get(db, Driver, task.driver_id)
    if driver is None or driver.user_id is None:
        return

    await get_push_service().send(
        Notification(
            channel="push",
            recipient=str(driver.user_id),
            subject=f"Task {reason}: {task.title}",
            body=(
                task.description
                or task.destination_label
                or "Open FleetBeat for details."
            ),
            metadata={"task_id": str(task.id), "reason": reason},
        )
    )


async def driver_tasks(
    db: AsyncSession,
    scope: TenantScope,
    *,
    driver_id: uuid.UUID,
    include_completed: bool = False,
) -> list[Task]:
    """The driver app's home screen: today's work, open items first."""
    stmt = scope.select(Task).where(Task.driver_id == driver_id)
    if not include_completed:
        stmt = stmt.where(
            Task.status.in_(
                [TaskStatus.ASSIGNED, TaskStatus.ACCEPTED, TaskStatus.EN_ROUTE]
            )
        )
    result = await db.execute(
        stmt.order_by(Task.due_at.asc().nullslast(), Task.created_at.asc())
    )
    return list(result.scalars().unique().all())


async def driver_for_user(
    db: AsyncSession, scope: TenantScope, *, user_id: uuid.UUID
) -> Driver:
    result = await db.execute(
        scope.select(Driver).where(Driver.user_id == user_id).limit(1)
    )
    driver = result.scalar_one_or_none()
    if driver is None:
        raise PermissionDeniedError(
            "This account has no driver profile. Ask your fleet administrator "
            "to link one."
        )
    return driver
