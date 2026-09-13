"""Driver mobile app API (Sections 4f and 4 item 14).

Every route here is driver-only and implicitly scoped to the caller's own
driver profile: a driver can never see or act on another driver's work, and
nothing accepts a `driver_id` from the client.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal, get_tenant_scope, require_driver
from app.core.errors import NotFoundError, ValidationError
from app.core.tenancy import TenantScope
from app.db.session import get_db
from app.models.enums import TaskStatus
from app.models.organization import OrganizationSettings
from app.models.task import PreTripInspection
from app.models.vehicle import Vehicle
from app.schemas.task import (
    DriverHome,
    IncidentCreate,
    IncidentOut,
    PreTripInspectionCreate,
    PreTripInspectionOut,
    RoutePreviewOut,
    TaskComplete,
    TaskOut,
)
from app.services import incidents as incident_service
from app.services import routing
from app.services import tasks as task_service

router = APIRouter(prefix="/driver", tags=["driver-app"])

#: A pre-trip inspection is valid for the working day.
INSPECTION_VALID_FOR = timedelta(hours=14)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@router.get(
    "/home",
    response_model=DriverHome,
    summary="My Tasks - the driver app home screen",
)
async def driver_home(
    principal: Principal = Depends(require_driver),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> DriverHome:
    driver = await task_service.driver_for_user(db, scope, user_id=principal.user_id)
    tasks = await task_service.driver_tasks(db, scope, driver_id=driver.id)

    vehicle: Vehicle | None = None
    if driver.assigned_vehicle_id:
        vehicle = await scope.get(db, Vehicle, driver.assigned_vehicle_id)

    # An inspection submitted today covers the day's driving.
    latest = await db.execute(
        scope.select(PreTripInspection)
        .where(PreTripInspection.driver_id == driver.id)
        .order_by(PreTripInspection.submitted_at.desc())
        .limit(1)
    )
    last_inspection = latest.scalar_one_or_none()
    submitted_at = _aware(last_inspection.submitted_at) if last_inspection else None
    inspection_due = (
        submitted_at is None or (utcnow() - submitted_at) > INSPECTION_VALID_FOR
    )

    settings_row = (
        await db.execute(
            sa.select(OrganizationSettings)
            .where(OrganizationSettings.organization_id == scope.organization_id)
            .limit(1)
        )
    ).scalar_one_or_none()

    return DriverHome(
        driver_id=driver.id,
        driver_name=driver.full_name,
        vehicle_id=vehicle.id if vehicle else None,
        vehicle_name=vehicle.name if vehicle else None,
        vehicle_plate=vehicle.license_plate if vehicle else None,
        tasks=[TaskOut.model_validate(t) for t in tasks],
        inspection_due=inspection_due,
        safety_score=driver.safety_score,
        points_balance=driver.points_balance,
        leaderboard_visible=bool(
            settings_row and settings_row.show_leaderboard_to_drivers
        ),
    )


@router.get(
    "/tasks", response_model=list[TaskOut], summary="My tasks"
)
async def my_tasks(
    include_completed: bool = False,
    principal: Principal = Depends(require_driver),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[TaskOut]:
    driver = await task_service.driver_for_user(db, scope, user_id=principal.user_id)
    tasks = await task_service.driver_tasks(
        db, scope, driver_id=driver.id, include_completed=include_completed
    )
    return [TaskOut.model_validate(t) for t in tasks]


@router.get(
    "/tasks/{task_id}/route",
    response_model=RoutePreviewOut,
    summary="Route from my current position to the destination",
)
async def task_route(
    task_id: uuid.UUID,
    latitude: float | None = None,
    longitude: float | None = None,
    principal: Principal = Depends(require_driver),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> RoutePreviewOut:
    driver = await task_service.driver_for_user(db, scope, user_id=principal.user_id)
    task = await task_service.get_task(db, scope, task_id)
    if task.driver_id != driver.id:
        raise NotFoundError("Task not found")

    # Prefer the handset's own position; fall back to the vehicle's last fix.
    origin: tuple[float, float] | None = None
    if latitude is not None and longitude is not None:
        origin = (latitude, longitude)
    else:
        origin = await routing.origin_for_driver(
            db, scope, vehicle_id=task.vehicle_id
        )
    if origin is None:
        raise ValidationError("No starting position is available yet")

    preview = await routing.preview_route(
        origin=origin,
        destination=(task.destination_latitude, task.destination_longitude),
        waypoints=routing.parse_waypoints(task.waypoints),
    )
    return RoutePreviewOut(
        distance_km=preview.distance_km,
        duration_minutes=preview.duration_minutes,
        eta=preview.eta,
        geometry_polyline=preview.geometry_polyline,
    )


async def _transition(
    db: AsyncSession,
    scope: TenantScope,
    principal: Principal,
    request: Request,
    task_id: uuid.UUID,
    to_status: TaskStatus,
    **kwargs: object,
) -> TaskOut:
    driver = await task_service.driver_for_user(db, scope, user_id=principal.user_id)
    task = await task_service.transition(
        db,
        scope,
        task_id=task_id,
        to_status=to_status,
        principal=principal,
        request=request,
        acting_driver_id=driver.id,
        **kwargs,
    )
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/accept", response_model=TaskOut, summary="Accept a task")
async def accept_task(
    task_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_driver),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    return await _transition(
        db, scope, principal, request, task_id, TaskStatus.ACCEPTED
    )


@router.post(
    "/tasks/{task_id}/start",
    response_model=TaskOut,
    summary="Start driving - links the task to a recorded trip",
)
async def start_task(
    task_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_driver),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    return await _transition(
        db, scope, principal, request, task_id, TaskStatus.EN_ROUTE
    )


@router.post(
    "/tasks/{task_id}/complete", response_model=TaskOut, summary="Complete a task"
)
async def complete_task(
    task_id: uuid.UUID,
    payload: TaskComplete,
    request: Request,
    principal: Principal = Depends(require_driver),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    return await _transition(
        db,
        scope,
        principal,
        request,
        task_id,
        TaskStatus.COMPLETED,
        completion_note=payload.completion_note,
        completion_photo_url=payload.completion_photo_url,
    )


@router.post(
    "/inspections",
    response_model=PreTripInspectionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a pre-trip inspection checklist",
)
async def submit_inspection(
    payload: PreTripInspectionCreate,
    principal: Principal = Depends(require_driver),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> PreTripInspectionOut:
    driver = await task_service.driver_for_user(db, scope, user_id=principal.user_id)
    if await scope.get(db, Vehicle, payload.vehicle_id) is None:
        raise NotFoundError("Vehicle not found")
    if not payload.items:
        raise ValidationError("An inspection needs at least one checklist item")

    inspection = PreTripInspection(
        driver_id=driver.id,
        vehicle_id=payload.vehicle_id,
        task_id=payload.task_id,
        submitted_at=utcnow(),
        items=[item.model_dump() for item in payload.items],
        passed=all(item.ok for item in payload.items),
        odometer_km=payload.odometer_km,
        notes=payload.notes,
    )
    scope.assign(inspection)
    db.add(inspection)
    await db.flush()

    # A failed check is an operational problem someone must see, so it is
    # raised as an incident rather than sitting in a form nobody opens.
    if not inspection.passed:
        failed = [item.label for item in payload.items if not item.ok]
        await incident_service.create_incident(
            db,
            scope,
            data={
                "title": f"Pre-trip inspection failed: {', '.join(failed)[:120]}",
                "description": payload.notes,
                "severity": "moderate",
                "vehicle_id": payload.vehicle_id,
                "driver_id": driver.id,
                "task_id": payload.task_id,
                "occurred_at": inspection.submitted_at,
                "latitude": None,
                "longitude": None,
                "location_label": None,
            },
            principal=principal,
        )

    return PreTripInspectionOut.model_validate(inspection)


@router.post(
    "/incidents",
    response_model=IncidentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Report an issue from the roadside",
)
async def report_incident(
    payload: IncidentCreate,
    request: Request,
    principal: Principal = Depends(require_driver),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> IncidentOut:
    driver = await task_service.driver_for_user(db, scope, user_id=principal.user_id)
    data = payload.model_dump(exclude={"photo_urls"})
    # The reporter is always the caller - never taken from the request body.
    data["driver_id"] = driver.id
    if data.get("vehicle_id") is None:
        data["vehicle_id"] = driver.assigned_vehicle_id

    incident = await incident_service.create_incident(
        db,
        scope,
        data=data,
        photo_urls=payload.photo_urls,
        principal=principal,
        request=request,
    )
    out = IncidentOut.model_validate(incident)
    out.photo_urls = list(payload.photo_urls)
    return out
