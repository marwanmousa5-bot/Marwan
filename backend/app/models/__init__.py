"""Import every model so Alembic and SQLAlchemy see the full metadata."""
from app.db.base import Base  # noqa: F401
from app.models.org import (  # noqa: F401
    DEFAULT_ORG_SETTINGS, Invitation, LoginAttempt, Notification, Organization,
    RefreshToken, SavedView, User,
)
from app.models.fleet import (  # noqa: F401
    Device, Driver, Geofence, GeofenceState, Place, Vehicle, Workshop,
)
from app.models.ops import (  # noqa: F401
    Customer, Route, RouteStop, Task, TimelineEvent, Trip, TripPosition,
)
from app.models.safety import (  # noqa: F401
    Alert, AlertRule, Badge, DriverEvent, DriverPointTransaction,
    DriverScoreSnapshot, Incident, Inspection,
)
from app.models.assets import (  # noqa: F401
    AIRecommendation, AuditLog, ChargingSession, CostRecord, Document,
    FuelTransaction, MaintenanceRecord, MaintenanceSchedule, MaintenanceTemplate,
    RoadDisruption, WeatherObservation, WorkOrder, WorkOrderPart,
)

__all__ = [
    "Base", "Organization", "User", "Invitation", "RefreshToken", "LoginAttempt",
    "SavedView", "Notification", "Vehicle", "Driver", "Device", "Place", "Geofence",
    "GeofenceState", "Workshop", "Route", "RouteStop", "Trip", "TripPosition",
    "Task", "Customer", "TimelineEvent", "Alert", "AlertRule", "DriverEvent",
    "DriverScoreSnapshot", "DriverPointTransaction", "Badge", "Incident", "Inspection",
    "MaintenanceTemplate", "MaintenanceSchedule", "WorkOrder", "WorkOrderPart",
    "MaintenanceRecord", "FuelTransaction", "ChargingSession", "Document",
    "CostRecord", "AIRecommendation", "AuditLog", "RoadDisruption",
    "WeatherObservation", "DEFAULT_ORG_SETTINGS",
]
