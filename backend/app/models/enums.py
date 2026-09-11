"""Enumerations shared across the data model.

Stored as native strings (not native PG enums) so that adding a value is a
code change rather than a migration - deliberate trade-off for MVP velocity.
"""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    SUPER_ADMIN = "super_admin"
    ORG_ADMIN = "org_admin"
    DISPATCHER = "dispatcher"
    DRIVER = "driver"


#: Roles that belong to a customer Organization (everything except platform staff).
CUSTOMER_ROLES = frozenset(
    {UserRole.ORG_ADMIN, UserRole.DISPATCHER, UserRole.DRIVER}
)
#: Roles allowed into the customer-facing web dashboard (Section 4b).
WEB_DASHBOARD_ROLES = frozenset({UserRole.ORG_ADMIN, UserRole.DISPATCHER})


class UserStatus(StrEnum):
    PENDING_ACTIVATION = "pending_activation"
    ACTIVE = "active"
    SUSPENDED = "suspended"


class OrganizationStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class SubscriptionStatus(StrEnum):
    """Reserved for a future billing phase - not enforced anywhere (Section 2)."""

    TRIAL = "trial"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"


class VehicleType(StrEnum):
    CAR = "car"
    VAN = "van"
    TRUCK = "truck"
    EV = "ev"
    OTHER = "other"


class VehicleStatus(StrEnum):
    ACTIVE = "active"
    IN_MAINTENANCE = "in_maintenance"
    RETIRED = "retired"


class VehicleOwnership(StrEnum):
    OWNED = "owned"
    LEASED = "leased"


class VehicleLiveStatus(StrEnum):
    """Derived, not stored: how a vehicle renders on the live map (Section 4b)."""

    MOVING = "moving"
    IDLE = "idle"
    ALERT = "alert"
    NOT_TRACKED = "not_tracked"


class DeviceStatus(StrEnum):
    IN_STOCK = "in_stock"
    ASSIGNED = "assigned"
    ACTIVE = "active"
    FAULTY = "faulty"
    RETIRED = "retired"


class EmploymentStatus(StrEnum):
    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    TERMINATED = "terminated"


class TripStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DriverEventType(StrEnum):
    """The single shared driver-event stream (Section 4g / Section 5 item 1)."""

    HARSH_BRAKING = "harsh_braking"
    HARSH_ACCELERATION = "harsh_acceleration"
    SPEEDING = "speeding"
    GEOFENCE_BREACH = "geofence_breach"
    IDLE_TOO_LONG = "idle_too_long"
    CLEAN_STREAK = "clean_streak"
    FUEL_EFFICIENT = "fuel_efficient"


#: Event types that deduct points by default (weights are Org-configurable).
VIOLATION_EVENT_TYPES = frozenset(
    {
        DriverEventType.HARSH_BRAKING,
        DriverEventType.HARSH_ACCELERATION,
        DriverEventType.SPEEDING,
        DriverEventType.GEOFENCE_BREACH,
    }
)


class GeofenceShape(StrEnum):
    POLYGON = "polygon"
    CIRCLE = "circle"


class GeofenceTrigger(StrEnum):
    ON_ENTER = "on_enter"
    ON_EXIT = "on_exit"
    BOTH = "both"


class PoiCategory(StrEnum):
    DEPOT = "depot"
    CUSTOMER_SITE = "customer_site"
    FUEL_STATION = "fuel_station"
    CUSTOM = "custom"


class MaintenanceIntervalType(StrEnum):
    MILEAGE = "mileage"
    TIME = "time"


class WorkOrderStatus(StrEnum):
    PROPOSED = "proposed"
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class FuelType(StrEnum):
    PETROL = "petrol"
    DIESEL = "diesel"
    ELECTRIC = "electric"
    HYBRID = "hybrid"
    LPG = "lpg"


class DocumentType(StrEnum):
    INSURANCE = "insurance"
    REGISTRATION = "registration"
    INSPECTION = "inspection"
    LICENSE = "license"
    OTHER = "other"


class TaskStatus(StrEnum):
    """Mandatory four-state lifecycle + cancellation (Section 4f)."""

    ASSIGNED = "assigned"
    ACCEPTED = "accepted"
    EN_ROUTE = "en_route"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(StrEnum):
    NORMAL = "normal"
    URGENT = "urgent"


class TaskType(StrEnum):
    DELIVERY = "delivery"
    PICKUP = "pickup"
    SERVICE_CALL = "service_call"
    CUSTOM = "custom"


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(StrEnum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class AlertRuleType(StrEnum):
    MAINTENANCE_DUE = "maintenance_due"
    DOCUMENT_EXPIRING = "document_expiring"
    GEOFENCE_BREACH = "geofence_breach"
    HARSH_DRIVING = "harsh_driving"
    SPEEDING = "speeding"
    IDLE_TOO_LONG = "idle_too_long"
    WEATHER_DELAY = "weather_delay"
    ANOMALY = "anomaly"
    SUSPICIOUS_LOGIN = "suspicious_login"
    FATIGUE_RISK = "fatigue_risk"


class IncidentSeverity(StrEnum):
    MINOR = "minor"
    MODERATE = "moderate"
    SEVERE = "severe"


class IncidentStatus(StrEnum):
    REPORTED = "reported"
    UNDER_REVIEW = "under_review"
    CLOSED = "closed"


class AuditAction(StrEnum):
    """Append-only audit log verbs (Section 4 item 18)."""

    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    LOGOUT = "logout"
    PASSWORD_SET = "password_set"
    PASSWORD_RESET_REQUESTED = "password_reset_requested"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    ORGANIZATION_CREATED = "organization_created"
    ORGANIZATION_SUSPENDED = "organization_suspended"
    ORGANIZATION_REACTIVATED = "organization_reactivated"
    DEVICE_ASSIGNED = "device_assigned"
    DEVICE_UNASSIGNED = "device_unassigned"
    IMPERSONATION_STARTED = "impersonation_started"
    AI_ACTION_CONFIRMED = "ai_action_confirmed"
    SUSPICIOUS_LOGIN_FLAGGED = "suspicious_login_flagged"


class RecommendationKind(StrEnum):
    """AI-produced proposals that always require explicit confirmation."""

    COPILOT = "copilot"
    MAINTENANCE_WINDOW = "maintenance_window"
    REROUTE = "reroute"
    EV_TRANSITION = "ev_transition"
    ANOMALY = "anomaly"


class RecommendationStatus(StrEnum):
    PENDING = "pending"
    DISMISSED = "dismissed"
    APPLIED = "applied"
    EXPIRED = "expired"
