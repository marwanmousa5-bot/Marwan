"""Task Manager - the dispatcher side (Section 4f)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal, get_tenant_scope, require_dashboard_user
from app.core.errors import ValidationError
from app.core.tenancy import TenantScope
from app.db.session import get_db
from app.models.driver import Driver
from app.models.enums import IncidentStatus, TaskStatus
from app.models.incident import Incident
from app.models.task import Task
from app.models.vehicle import Vehicle
from app.schemas.common import Page
from app.schemas.task import (
    IncidentCreate,
    IncidentOut,
    RoutePreviewOut,
    RoutePreviewRequest,
    TaskCancel,
    TaskComplete,
    TaskCreate,
    TaskOut,
    TaskReassign,
    TaskUpdate,
)
from app.services import incidents as incident_service
from app.services import routing
from app.services import tasks as task_service

router = APIRouter(tags=["tasks"])


async def _decorate(
    db: AsyncSession, scope: TenantScope, tasks: list[Task]
) -> list[TaskOut]:
    """Attach driver and vehicle names so the board renders in one pass."""
    driver_ids = {t.driver_id for t in tasks if t.driver_id}
    vehicle_ids = {t.vehicle_id for t in tasks if t.vehicle_id}

    drivers: dict[uuid.UUID, str] = {}
    if driver_ids:
        rows = await db.execute(
            scope.select(Driver).where(Driver.id.in_(driver_ids))
        )
        drivers = {d.id: d.full_name for d in rows.scalars().all()}

    vehicles: dict[uuid.UUID, str] = {}
    if vehicle_ids:
        rows = await db.execute(
            scope.select(Vehicle).where(Vehicle.id.in_(vehicle_ids))
        )
        vehicles = {v.id: v.name for v in rows.scalars().all()}

    out: list[TaskOut] = []
    for task in tasks:
        item = TaskOut.model_validate(task)
        item.driver_name = drivers.get(task.driver_id) if task.driver_id else None
        item.vehicle_name = vehicles.get(task.vehicle_id) if task.vehicle_id else None
        out.append(item)
    return out


@router.get("/tasks", response_model=Page[TaskOut], summary="Task board")
async def list_tasks(
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    driver_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> Page[TaskOut]:
    items, total = await task_service.list_tasks(
        db, scope, status=status_filter, driver_id=driver_id, limit=limit, offset=offset
    )
    return Page[TaskOut](
        items=await _decorate(db, scope, items), total=total, limit=limit, offset=offset
    )


@router.post(
    "/tasks/route-preview",
    response_model=RoutePreviewOut,
    summary="Preview the route and ETA before assigning a task",
)
async def route_preview(
    payload: RoutePreviewRequest,
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> RoutePreviewOut:
    origin: tuple[float, float] | None = None
    if payload.origin_latitude is not None and payload.origin_longitude is not None:
        origin = (payload.origin_latitude, payload.origin_longitude)
    elif payload.driver_id is not None:
        driver = await scope.get(db, Driver, payload.driver_id)
        if driver is not None:
            origin = await routing.origin_for_driver(
                db, scope, vehicle_id=driver.assigned_vehicle_id
            )

    if origin is None:
        raise ValidationError(
            "No starting point is known for that driver yet. Their vehicle has "
            "no recorded position - pick an origin on the map instead."
        )

    preview = await routing.preview_route(
        origin=origin,
        destination=(payload.destination_latitude, payload.destination_longitude),
        waypoints=[(w.lat, w.lng) for w in payload.waypoints],
    )
    return RoutePreviewOut(
        distance_km=preview.distance_km,
        duration_minutes=preview.duration_minutes,
        eta=preview.eta,
        geometry_polyline=preview.geometry_polyline,
    )


@router.post(
    "/tasks",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a task to a driver",
)
async def create_task(
    payload: TaskCreate,
    request: Request,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    data = payload.model_dump()
    data["waypoints"] = [w.model_dump() for w in payload.waypoints]
    task = await task_service.create_task(
        db, scope, data=data, principal=principal, request=request
    )
    return (await _decorate(db, scope, [task]))[0]


@router.get("/tasks/{task_id}", response_model=TaskOut, summary="Get one task")
async def get_task(
    task_id: uuid.UUID,
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    task = await task_service.get_task(db, scope, task_id)
    return (await _decorate(db, scope, [task]))[0]


@router.patch("/tasks/{task_id}", response_model=TaskOut, summary="Edit a task")
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    task = await task_service.get_task(db, scope, task_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, key, value)
    await db.flush()
    return (await _decorate(db, scope, [task]))[0]


@router.post(
    "/tasks/{task_id}/reassign",
    response_model=TaskOut,
    summary="Hand a task to a different driver (before acceptance)",
)
async def reassign_task(
    task_id: uuid.UUID,
    payload: TaskReassign,
    request: Request,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    task = await task_service.reassign(
        db,
        scope,
        task_id=task_id,
        driver_id=payload.driver_id,
        principal=principal,
        request=request,
    )
    return (await _decorate(db, scope, [task]))[0]


@router.post(
    "/tasks/{task_id}/cancel", response_model=TaskOut, summary="Cancel a task"
)
async def cancel_task(
    task_id: uuid.UUID,
    payload: TaskCancel,
    request: Request,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    task = await task_service.transition(
        db,
        scope,
        task_id=task_id,
        to_status=TaskStatus.CANCELLED,
        cancellation_reason=payload.reason,
        principal=principal,
        request=request,
    )
    return (await _decorate(db, scope, [task]))[0]


@router.post(
    "/tasks/{task_id}/complete",
    response_model=TaskOut,
    summary="Mark a task complete from the dispatcher side",
)
async def complete_task(
    task_id: uuid.UUID,
    payload: TaskComplete,
    request: Request,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    task = await task_service.transition(
        db,
        scope,
        task_id=task_id,
        to_status=TaskStatus.COMPLETED,
        completion_note=payload.completion_note,
        completion_photo_url=payload.completion_photo_url,
        principal=principal,
        request=request,
    )
    return (await _decorate(db, scope, [task]))[0]


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

async def _incident_out(
    db: AsyncSession, incidents: list[Incident]
) -> list[IncidentOut]:
    photos = await incident_service.photo_urls_for(db, [i.id for i in incidents])
    out = []
    for incident in incidents:
        item = IncidentOut.model_validate(incident)
        item.photo_urls = photos.get(incident.id, [])
        out.append(item)
    return out


@router.get(
    "/incidents", response_model=Page[IncidentOut], summary="Reported incidents"
)
async def list_incidents(
    status_filter: IncidentStatus | None = Query(default=None, alias="status"),
    vehicle_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> Page[IncidentOut]:
    items, total = await incident_service.list_incidents(
        db, scope, status=status_filter, vehicle_id=vehicle_id, limit=limit, offset=offset
    )
    return Page[IncidentOut](
        items=await _incident_out(db, items), total=total, limit=limit, offset=offset
    )


@router.post(
    "/incidents",
    response_model=IncidentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Report an incident",
)
async def create_incident(
    payload: IncidentCreate,
    request: Request,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> IncidentOut:
    data = payload.model_dump(exclude={"photo_urls"})
    incident = await incident_service.create_incident(
        db,
        scope,
        data=data,
        photo_urls=payload.photo_urls,
        principal=principal,
        request=request,
    )
    return (await _incident_out(db, [incident]))[0]
