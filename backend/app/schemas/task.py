"""Dispatch task, inspection and incident schemas (Sections 4f, 4.11, 4.14)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import (
    IncidentSeverity,
    IncidentStatus,
    TaskPriority,
    TaskStatus,
    TaskType,
)
from app.schemas.common import ORMModel


class Waypoint(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    label: str | None = Field(default=None, max_length=200)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    task_type: TaskType = TaskType.DELIVERY
    priority: TaskPriority = TaskPriority.NORMAL
    driver_id: uuid.UUID | None = None
    destination_label: str | None = Field(default=None, max_length=300)
    destination_latitude: float = Field(ge=-90, le=90)
    destination_longitude: float = Field(ge=-180, le=180)
    waypoints: list[Waypoint] = Field(default_factory=list)
    due_at: datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    task_type: TaskType | None = None
    priority: TaskPriority | None = None
    destination_label: str | None = Field(default=None, max_length=300)
    due_at: datetime | None = None


class TaskReassign(BaseModel):
    driver_id: uuid.UUID


class TaskComplete(BaseModel):
    completion_note: str | None = None
    completion_photo_url: str | None = Field(default=None, max_length=500)


class TaskCancel(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class TaskOut(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    title: str
    description: str | None = None
    task_type: TaskType
    priority: TaskPriority
    status: TaskStatus
    driver_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID | None = None
    destination_label: str | None = None
    destination_latitude: float
    destination_longitude: float
    waypoints: list[dict] | None = None
    due_at: datetime | None = None
    eta: datetime | None = None
    accepted_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    completion_note: str | None = None
    completion_photo_url: str | None = None
    route_id: uuid.UUID | None = None
    trip_id: uuid.UUID | None = None
    created_at: datetime

    #: Filled in by the router so the board reads without extra lookups.
    driver_name: str | None = None
    vehicle_name: str | None = None


class RoutePreviewRequest(BaseModel):
    """Preview a route before committing to a task (Section 4f)."""

    driver_id: uuid.UUID | None = None
    origin_latitude: float | None = Field(default=None, ge=-90, le=90)
    origin_longitude: float | None = Field(default=None, ge=-180, le=180)
    destination_latitude: float = Field(ge=-90, le=90)
    destination_longitude: float = Field(ge=-180, le=180)
    waypoints: list[Waypoint] = Field(default_factory=list)


class RoutePreviewOut(BaseModel):
    distance_km: float
    duration_minutes: float
    eta: datetime
    geometry_polyline: str | None = None


# ---------------------------------------------------------------------------
# Driver app
# ---------------------------------------------------------------------------

class InspectionItem(BaseModel):
    code: str = Field(max_length=64)
    label: str = Field(max_length=160)
    ok: bool
    note: str | None = Field(default=None, max_length=300)


class PreTripInspectionCreate(BaseModel):
    vehicle_id: uuid.UUID
    task_id: uuid.UUID | None = None
    items: list[InspectionItem]
    odometer_km: float | None = Field(default=None, ge=0)
    notes: str | None = None


class PreTripInspectionOut(ORMModel):
    id: uuid.UUID
    driver_id: uuid.UUID
    vehicle_id: uuid.UUID
    task_id: uuid.UUID | None = None
    submitted_at: datetime
    items: list[dict]
    passed: bool
    odometer_km: float | None = None
    notes: str | None = None


class DriverHome(BaseModel):
    """Everything the driver app's home screen needs in one call."""

    driver_id: uuid.UUID
    driver_name: str
    vehicle_id: uuid.UUID | None = None
    vehicle_name: str | None = None
    vehicle_plate: str | None = None
    tasks: list[TaskOut]
    inspection_due: bool
    safety_score: float
    points_balance: int
    #: Only populated when the organization has opted in (Section 4g).
    leaderboard_visible: bool = False


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    severity: IncidentSeverity = IncidentSeverity.MINOR
    vehicle_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    occurred_at: datetime | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    location_label: str | None = Field(default=None, max_length=300)
    photo_urls: list[str] = Field(default_factory=list)


class IncidentOut(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    title: str
    description: str | None = None
    severity: IncidentSeverity
    status: IncidentStatus
    vehicle_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    occurred_at: datetime
    latitude: float | None = None
    longitude: float | None = None
    location_label: str | None = None
    estimated_cost: float | None = None
    created_at: datetime
    photo_urls: list[str] = []
