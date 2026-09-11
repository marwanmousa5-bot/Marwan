"""Live tracking, trips, geofences, POIs and alerts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import (
    AlertRuleType,
    AlertSeverity,
    AlertStatus,
    GeofenceShape,
    GeofenceTrigger,
    PoiCategory,
    TripStatus,
    VehicleLiveStatus,
)
from app.schemas.common import ORMModel

# ---------------------------------------------------------------------------
# Live map
# ---------------------------------------------------------------------------

class LiveVehicle(BaseModel):
    """One row of the sidebar and one marker on the map (Section 4b)."""

    id: uuid.UUID
    name: str
    license_plate: str
    live_status: VehicleLiveStatus
    latitude: float | None = None
    longitude: float | None = None
    heading: float | None = None
    speed_kph: float | None = None
    last_position_at: datetime | None = None
    stopped_since: datetime | None = None
    is_tracked: bool
    device_serial: str | None = None
    device_last_signal_at: datetime | None = None
    driver_id: uuid.UUID | None = None
    driver_name: str | None = None
    active_alert_count: int = 0


class LiveKpis(BaseModel):
    """The bottom KPI strip of the Live Tracking page."""

    total_vehicles: int
    active_now: int
    idle: int
    not_tracked: int
    active_alerts: int
    distance_today_km: float


class LiveSnapshot(BaseModel):
    """Everything the live page needs to render before the socket opens."""

    vehicles: list[LiveVehicle]
    kpis: LiveKpis
    server_time: datetime


# ---------------------------------------------------------------------------
# Trips and playback
# ---------------------------------------------------------------------------

class TripOut(ORMModel):
    id: uuid.UUID
    vehicle_id: uuid.UUID
    driver_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    status: TripStatus
    started_at: datetime
    ended_at: datetime | None = None
    start_latitude: float | None = None
    start_longitude: float | None = None
    end_latitude: float | None = None
    end_longitude: float | None = None
    distance_km: float
    duration_seconds: int
    average_speed_kph: float
    max_speed_kph: float
    idle_seconds: int


class TripPoint(BaseModel):
    """One vertex of the replayed route."""

    lat: float
    lng: float
    speed_kph: float
    heading: float
    at: datetime


class TripEventMarker(BaseModel):
    """A notable moment, marked on both the route line and the scrubber."""

    id: uuid.UUID
    event_type: str
    severity: str
    at: datetime
    lat: float | None = None
    lng: float | None = None
    speed_kph: float | None = None


class TripPlayback(BaseModel):
    trip: TripOut
    vehicle_name: str
    driver_name: str | None = None
    points: list[TripPoint]
    events: list[TripEventMarker]


# ---------------------------------------------------------------------------
# Geofences (Section 4d)
# ---------------------------------------------------------------------------

class GeofenceBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    shape: GeofenceShape = GeofenceShape.POLYGON
    #: polygon -> {"coordinates": [[lng, lat], ...]}
    #: circle  -> {"center": [lng, lat], "radius_m": 250}
    geometry: dict
    color: str = Field(default="#1E90FF", max_length=9)
    trigger: GeofenceTrigger = GeofenceTrigger.BOTH
    is_active: bool = True
    #: Empty means every vehicle in the organization.
    vehicle_ids: list[uuid.UUID] = Field(default_factory=list)

    @field_validator("color")
    @classmethod
    def _hex_colour(cls, value: str) -> str:
        if not value.startswith("#") or len(value) not in (4, 7, 9):
            raise ValueError("Colour must be a hex value like #1E90FF")
        return value


class GeofenceCreate(GeofenceBase):
    pass


class GeofenceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    shape: GeofenceShape | None = None
    geometry: dict | None = None
    color: str | None = Field(default=None, max_length=9)
    trigger: GeofenceTrigger | None = None
    is_active: bool | None = None
    vehicle_ids: list[uuid.UUID] | None = None


class GeofenceOut(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    shape: GeofenceShape
    geometry: dict
    color: str
    trigger: GeofenceTrigger
    is_active: bool
    vehicle_ids: list[uuid.UUID] = Field(default_factory=list)
    created_at: datetime


# ---------------------------------------------------------------------------
# Points of interest (Section 4d)
# ---------------------------------------------------------------------------

class PoiBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    category: PoiCategory = PoiCategory.CUSTOM
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    address: str | None = Field(default=None, max_length=400)
    notes: str | None = None


class PoiCreate(PoiBase):
    pass


class PoiUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    category: PoiCategory | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    address: str | None = Field(default=None, max_length=400)
    notes: str | None = None


class PoiOut(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    category: PoiCategory
    latitude: float
    longitude: float
    address: str | None = None
    notes: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Alerts (Section 4 item 12)
# ---------------------------------------------------------------------------

class AlertOut(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    rule_type: AlertRuleType
    severity: AlertSeverity
    status: AlertStatus
    title: str
    message: str
    vehicle_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    subject_type: str | None = None
    subject_id: uuid.UUID | None = None
    context: dict | None = None
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    created_at: datetime


class AlertRuleOut(ORMModel):
    id: uuid.UUID
    rule_type: AlertRuleType
    is_enabled: bool
    severity: AlertSeverity
    parameters: dict | None = None
    notify_roles: list[str] | None = None


class AlertRuleUpdate(BaseModel):
    is_enabled: bool | None = None
    severity: AlertSeverity | None = None
    parameters: dict | None = None


# ---------------------------------------------------------------------------
# Weather overlay (Section 4e)
# ---------------------------------------------------------------------------

class WeatherZoneOut(ORMModel):
    id: uuid.UUID
    latitude: float
    longitude: float
    radius_m: float
    condition: str
    severity: str
    expected_delay_minutes: int
    observed_at: datetime
    expires_at: datetime | None = None


# ---------------------------------------------------------------------------
# Road closures - the manual input to Exception Auto-Rerouting (Section 4.8)
# ---------------------------------------------------------------------------

class RoadClosureCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_m: float = Field(default=500.0, gt=0, le=50_000)
    active_from: datetime | None = None
    active_until: datetime | None = None


class RoadClosureUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    radius_m: float | None = Field(default=None, gt=0, le=50_000)
    active_from: datetime | None = None
    active_until: datetime | None = None
    is_active: bool | None = None


class RoadClosureOut(ORMModel):
    id: uuid.UUID
    label: str
    latitude: float
    longitude: float
    radius_m: float
    active_from: datetime | None = None
    active_until: datetime | None = None
    is_active: bool
    created_at: datetime


class RerouteProposalOut(BaseModel):
    """A computed alternative. Returned by a read-only endpoint."""

    task_id: uuid.UUID
    task_title: str
    route_id: uuid.UUID
    obstruction_kind: str
    obstruction_id: uuid.UUID
    obstruction_label: str
    added_km: float | None = None
    added_minutes: float | None = None
    new_distance_km: float | None = None
    new_eta: datetime | None = None
    routing_available: bool
