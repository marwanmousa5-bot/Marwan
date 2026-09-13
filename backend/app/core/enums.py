"""Domain enumerations shared by models, schemas and services."""
from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    SUPER_ADMIN = "super_admin"
    ORG_ADMIN = "org_admin"
    DISPATCHER = "dispatcher"
    DRIVER = "driver"


class OrgStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class VehicleStatus(StrEnum):
    """Derived operational state - never stored per-module."""
    MOVING = "moving"
    IDLE = "idle"
    STOPPED = "stopped"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"
    NOT_TRACKED = "not_tracked"


class VehicleLifecycle(StrEnum):
    PLANNED = "planned"
    ACQUIRED = "acquired"
    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class VehicleType(StrEnum):
    VAN = "van"
    TRUCK = "truck"
    CAR = "car"
    REFRIGERATED_VAN = "refrigerated_van"
    CARGO_BIKE = "cargo_bike"
    EV_VAN = "ev_van"


class Ownership(StrEnum):
    OWNED = "owned"
    LEASED = "leased"


class DeviceStatus(StrEnum):
    IN_STOCK = "in_stock"
    ASSIGNED = "assigned"
    ACTIVE = "active"
    FAULTY = "faulty"
    RETIRED = "retired"


class DriverStatus(StrEnum):
    AVAILABLE = "available"
    DRIVING = "driving"
    ON_BREAK = "on_break"
    OFF_DUTY = "off_duty"
    UNAVAILABLE = "unavailable"


class TaskType(StrEnum):
    DELIVERY = "delivery"
    PICKUP = "pickup"
    SERVICE_CALL = "service_call"
    INSPECTION = "inspection"
    COLLECTION = "collection"
    CUSTOM = "custom"


class TaskStatus(StrEnum):
    UNASSIGNED = "unassigned"
    ASSIGNED = "assigned"
    ACCEPTED = "accepted"
    EN_ROUTE = "en_route"
    ARRIVED = "arrived"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DELAYED = "delayed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_TASK_STATUSES = (
    TaskStatus.ASSIGNED, TaskStatus.ACCEPTED, TaskStatus.EN_ROUTE,
    TaskStatus.ARRIVED, TaskStatus.IN_PROGRESS, TaskStatus.DELAYED,
)


class Priority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class SlaState(StrEnum):
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    BREACHED = "breached"
    MET = "met"
    NONE = "none"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertStatus(StrEnum):
    TRIGGERED = "triggered"
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    SNOOZED = "snoozed"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


OPEN_ALERT_STATUSES = (
    AlertStatus.TRIGGERED, AlertStatus.ACKNOWLEDGED,
    AlertStatus.INVESTIGATING, AlertStatus.ESCALATED,
)


class AlertCategory(StrEnum):
    VEHICLE = "vehicle"
    DRIVER = "driver"
    ROUTE = "route"
    MAINTENANCE = "maintenance"
    COMPLIANCE = "compliance"
    GEOFENCE = "geofence"
    SECURITY = "security"


class TripStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"


class DriverEventType(StrEnum):
    OVERSPEED = "overspeed"
    HARSH_BRAKING = "harsh_braking"
    HARSH_ACCELERATION = "harsh_acceleration"
    HARSH_CORNERING = "harsh_cornering"
    IDLING = "idling"
    ROUTE_DEVIATION = "route_deviation"
    GEOFENCE_BREACH = "geofence_breach"
    CLEAN_STREAK = "clean_streak"
    ECO_DRIVING = "eco_driving"
    IMPROVEMENT = "improvement"


class GeofenceType(StrEnum):
    POLYGON = "polygon"
    CIRCLE = "circle"


class GeofenceTrigger(StrEnum):
    ENTER = "enter"
    EXIT = "exit"
    BOTH = "both"


class PlaceCategory(StrEnum):
    DEPOT = "depot"
    CUSTOMER_SITE = "customer_site"
    FUEL_STATION = "fuel_station"
    WORKSHOP = "workshop"
    PARKING = "parking"
    CUSTOM = "custom"


class MaintenanceStatus(StrEnum):
    HEALTHY = "healthy"
    DUE_SOON = "due_soon"
    DUE = "due"
    OVERDUE = "overdue"
    CRITICAL = "critical"
    IN_WORKSHOP = "in_workshop"


class WorkOrderStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_PARTS = "waiting_for_parts"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


OPEN_WORK_ORDER_STATUSES = (
    WorkOrderStatus.REQUESTED, WorkOrderStatus.APPROVED, WorkOrderStatus.SCHEDULED,
    WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.WAITING_FOR_PARTS,
)


class MaintenanceCategory(StrEnum):
    ENGINE_OIL = "engine_oil"
    OIL_FILTER = "oil_filter"
    AIR_FILTER = "air_filter"
    BRAKE_INSPECTION = "brake_inspection"
    BRAKE_PADS = "brake_pads"
    TIRES = "tires"
    BATTERY = "battery"
    TRANSMISSION = "transmission"
    COOLING = "cooling"
    AIR_CONDITIONING = "air_conditioning"
    SUSPENSION = "suspension"
    STEERING = "steering"
    FLUIDS = "fluids"
    GENERAL_INSPECTION = "general_inspection"


class DocumentType(StrEnum):
    REGISTRATION = "registration"
    INSURANCE = "insurance"
    INSPECTION = "inspection"
    DRIVER_LICENSE = "driver_license"
    PERMIT = "permit"
    CERTIFICATION = "certification"
    OTHER = "other"


class DocumentStatus(StrEnum):
    VALID = "valid"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"


class IncidentStatus(StrEnum):
    REPORTED = "reported"
    UNDER_INVESTIGATION = "under_investigation"
    ACTION_REQUIRED = "action_required"
    RESOLVED = "resolved"
    CLOSED = "closed"


class IncidentType(StrEnum):
    COLLISION = "collision"
    BREAKDOWN = "breakdown"
    THEFT = "theft"
    VANDALISM = "vandalism"
    CARGO_DAMAGE = "cargo_damage"
    NEAR_MISS = "near_miss"
    INJURY = "injury"
    OTHER = "other"


class CostCategory(StrEnum):
    FUEL = "fuel"
    ENERGY = "energy"
    MAINTENANCE = "maintenance"
    INSURANCE = "insurance"
    REGISTRATION = "registration"
    DEPRECIATION = "depreciation"
    TOLLS = "tolls"
    FINES = "fines"
    OTHER = "other"


class FuelType(StrEnum):
    DIESEL = "diesel"
    PETROL = "petrol"
    ELECTRIC = "electric"
    HYBRID = "hybrid"


class RecommendationStatus(StrEnum):
    PENDING = "pending"
    APPLIED = "applied"
    DISMISSED = "dismissed"


class NotificationType(StrEnum):
    TASK_ASSIGNED = "task_assigned"
    TASK_REASSIGNED = "task_reassigned"
    TASK_CHANGED = "task_changed"
    ROUTE_CHANGED = "route_changed"
    MAINTENANCE_SCHEDULED = "maintenance_scheduled"
    DOCUMENT_EXPIRING = "document_expiring"
    AI_RECOMMENDATION = "ai_recommendation"
    REPORT_READY = "report_ready"
    ANNOUNCEMENT = "announcement"
    URGENT_ALERT = "urgent_alert"
