"""Derived state.

Spec 17: a vehicle has ONE source of truth. Live Tracking, Dispatch and
Maintenance must never store their own copy of "status" - they all call these
helpers, so the system can never contradict itself.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.core.enums import (DocumentStatus, MaintenanceStatus, SlaState,
                            VehicleLifecycle, VehicleStatus)


def gps_freshness(last_position_at: datetime | None, *, live_s: int = 45,
                  stale_s: int = 300, now: datetime | None = None) -> tuple[str, float | None]:
    """Returns (LIVE|STALE|OFFLINE|NEVER, age_seconds). Never show old as live."""
    if last_position_at is None:
        return "NEVER", None
    now = now or datetime.now(timezone.utc)
    age = (now - last_position_at).total_seconds()
    if age <= live_s:
        return "LIVE", age
    if age <= stale_s:
        return "STALE", age
    return "OFFLINE", age


def vehicle_status(vehicle, *, has_open_work_order: bool = False,
                   live_s: int = 45, stale_s: int = 300,
                   idle_minutes: float = 3.0, now: datetime | None = None) -> str:
    """The single derived operational state of a vehicle."""
    if vehicle.lifecycle in (VehicleLifecycle.RETIRED, VehicleLifecycle.SUSPENDED,
                             VehicleLifecycle.PLANNED):
        return VehicleStatus.OFFLINE
    if vehicle.lifecycle == VehicleLifecycle.MAINTENANCE or has_open_work_order:
        return VehicleStatus.MAINTENANCE
    if vehicle.last_position_at is None:
        return VehicleStatus.NOT_TRACKED
    freshness, _age = gps_freshness(vehicle.last_position_at, live_s=live_s,
                                    stale_s=stale_s, now=now)
    if freshness == "OFFLINE":
        return VehicleStatus.OFFLINE
    speed = vehicle.last_speed_kph or 0.0
    if speed > 3.0:
        return VehicleStatus.MOVING
    if vehicle.ignition_on:
        now = now or datetime.now(timezone.utc)
        if vehicle.idle_since and (now - vehicle.idle_since).total_seconds() >= idle_minutes * 60:
            return VehicleStatus.IDLE
        return VehicleStatus.IDLE if speed <= 3.0 else VehicleStatus.MOVING
    return VehicleStatus.STOPPED


def maintenance_status(schedule, odometer_km: float, *, today: date | None = None,
                       due_soon_km: float = 500, due_soon_days: int = 14) -> str:
    """Mileage OR time rule - whichever triggers first (spec 7.5)."""
    today = today or date.today()
    km_left = schedule.km_remaining(odometer_km)
    days_left = schedule.days_remaining(today)

    worst = MaintenanceStatus.HEALTHY
    order = [MaintenanceStatus.HEALTHY, MaintenanceStatus.DUE_SOON,
             MaintenanceStatus.DUE, MaintenanceStatus.OVERDUE, MaintenanceStatus.CRITICAL]

    def bump(candidate):
        nonlocal worst
        if order.index(candidate) > order.index(worst):
            worst = candidate

    if km_left is not None:
        if km_left <= -1000:
            bump(MaintenanceStatus.CRITICAL)
        elif km_left < 0:
            bump(MaintenanceStatus.OVERDUE)
        elif km_left <= 50:
            bump(MaintenanceStatus.DUE)
        elif km_left <= due_soon_km:
            bump(MaintenanceStatus.DUE_SOON)
    if days_left is not None:
        if days_left <= -30:
            bump(MaintenanceStatus.CRITICAL)
        elif days_left < 0:
            bump(MaintenanceStatus.OVERDUE)
        elif days_left <= 1:
            bump(MaintenanceStatus.DUE)
        elif days_left <= due_soon_days:
            bump(MaintenanceStatus.DUE_SOON)
    return worst


def maintenance_health(*, overdue: int, critical: int, due: int, due_soon: int,
                       open_work_orders: int, repeat_failures: int,
                       weights: dict | None = None) -> int:
    """0-100 vehicle maintenance health. Weights are org-configurable (spec 7.2)."""
    w = {"overdue": 25, "critical": 30, "due": 10, "due_soon": 4,
         "open_work_order": 6, "repeat_failure": 15, **(weights or {})}
    penalty = (overdue * w["overdue"] + critical * w["critical"] + due * w["due"]
               + due_soon * w["due_soon"] + open_work_orders * w["open_work_order"]
               + repeat_failures * w["repeat_failure"])
    return max(0, min(100, round(100 - penalty)))


def document_status(expiry: date | None, *, today: date | None = None,
                    warn_days: int = 30) -> str:
    if expiry is None:
        return DocumentStatus.VALID
    today = today or date.today()
    days = (expiry - today).days
    if days < 0:
        return DocumentStatus.EXPIRED
    if days <= warn_days:
        return DocumentStatus.EXPIRING_SOON
    return DocumentStatus.VALID


def sla_state(task, *, now: datetime | None = None, at_risk_minutes: int = 15) -> str:
    """On track / at risk / breached, judged against ETA where one exists."""
    from app.core.enums import TaskStatus

    if task.sla_due_at is None:
        return SlaState.NONE
    now = now or datetime.now(timezone.utc)
    if task.status == TaskStatus.COMPLETED:
        return SlaState.MET if (task.completed_at or now) <= task.sla_due_at else SlaState.BREACHED
    if task.status in (TaskStatus.CANCELLED, TaskStatus.FAILED):
        return SlaState.NONE
    reference = task.eta or now
    if reference > task.sla_due_at or now > task.sla_due_at:
        return SlaState.BREACHED
    if (task.sla_due_at - reference) <= timedelta(minutes=at_risk_minutes):
        return SlaState.AT_RISK
    return SlaState.ON_TRACK


def sla_minutes_remaining(task, now: datetime | None = None) -> int | None:
    if task.sla_due_at is None:
        return None
    now = now or datetime.now(timezone.utc)
    return round((task.sla_due_at - now).total_seconds() / 60)


def safety_score(event_counts: dict[str, int], distance_km: float,
                 weights: dict | None = None) -> float:
    """0-100, normalised per 100 km so long shifts are not punished (spec 13.1)."""
    w = {"overspeed": 6.0, "harsh_braking": 4.0, "harsh_acceleration": 3.5,
         "harsh_cornering": 3.0, "route_deviation": 2.0, "incident": 12.0,
         **(weights or {})}
    exposure = max(distance_km, 25.0) / 100.0
    penalty = sum(w.get(k, 1.0) * v for k, v in event_counts.items()) / exposure
    return round(max(0.0, min(100.0, 100.0 - penalty)), 1)


def straight_line_depreciation(vehicle, *, today: date | None = None) -> float:
    """Current book value under straight-line depreciation (spec 20)."""
    if not vehicle.purchase_value or not vehicle.purchase_date:
        return 0.0
    today = today or date.today()
    years = max(0.0, (today - vehicle.purchase_date).days / 365.25)
    residual = vehicle.residual_value or 0.0
    life = max(1, vehicle.depreciation_years or 7)
    annual = (vehicle.purchase_value - residual) / life
    return round(max(residual, vehicle.purchase_value - annual * years), 2)


def annual_depreciation(vehicle) -> float:
    if not vehicle.purchase_value:
        return 0.0
    residual = vehicle.residual_value or 0.0
    life = max(1, vehicle.depreciation_years or 7)
    return round((vehicle.purchase_value - residual) / life, 2)


def co2_kg(*, litres: float = 0.0, kwh: float = 0.0, fuel_type: str = "diesel",
           settings_map: dict | None = None) -> float:
    s = settings_map or {}
    if fuel_type == "electric":
        return round(kwh * s.get("co2_kg_per_kwh", 0.061), 3)
    factor = (s.get("co2_kg_per_litre_petrol", 2.31) if fuel_type == "petrol"
              else s.get("co2_kg_per_litre_diesel", 2.68))
    return round(litres * factor, 3)
