"""Model registry.

Importing this package registers every table on ``Base.metadata`` - Alembic's
autogenerate and the test-suite both rely on that.
"""

from app.db.base import Base
from app.models.ai import (
    AssistantConversation,
    AssistantMessage,
    Recommendation,
    ReportSummary,
)
from app.models.alert import Alert, AlertRule
from app.models.audit import AuditLog
from app.models.compliance import ComplianceDocument
from app.models.device import Device
from app.models.driver import (
    Driver,
    DriverBadge,
    DriverEvent,
    PointsLedgerEntry,
)
from app.models.fuel import FuelLog
from app.models.incident import Incident, IncidentPhoto
from app.models.maintenance import (
    MaintenanceSchedule,
    ServiceRecord,
    WorkOrder,
    WorkOrderPart,
)
from app.models.organization import Organization, OrganizationSettings
from app.models.routing import RoadClosure, Route, RouteStop
from app.models.task import PreTripInspection, Task
from app.models.tracking import (
    Geofence,
    GeofenceEvent,
    PointOfInterest,
    PositionSample,
    Trip,
)
from app.models.user import (
    ActivationToken,
    KnownDevice,
    LoginAttempt,
    RefreshToken,
    User,
)
from app.models.vehicle import Vehicle
from app.models.weather import WeatherZone

__all__ = [
    "ActivationToken",
    "Alert",
    "AlertRule",
    "AssistantConversation",
    "AssistantMessage",
    "AuditLog",
    "Base",
    "ComplianceDocument",
    "Device",
    "Driver",
    "DriverBadge",
    "DriverEvent",
    "FuelLog",
    "Geofence",
    "GeofenceEvent",
    "Incident",
    "IncidentPhoto",
    "KnownDevice",
    "LoginAttempt",
    "MaintenanceSchedule",
    "Organization",
    "OrganizationSettings",
    "PointOfInterest",
    "PointsLedgerEntry",
    "PositionSample",
    "PreTripInspection",
    "Recommendation",
    "RefreshToken",
    "ReportSummary",
    "RoadClosure",
    "Route",
    "RouteStop",
    "ServiceRecord",
    "Task",
    "Trip",
    "User",
    "Vehicle",
    "WeatherZone",
    "WorkOrder",
    "WorkOrderPart",
]
