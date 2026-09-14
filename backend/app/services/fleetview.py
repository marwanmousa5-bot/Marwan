"""Builds the Live Tracking fleet view - one query pass, everything joined.

This is the hot path: the page shows every vehicle with its driver, task, alert
and maintenance state, so it is assembled in bulk rather than per row.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (ACTIVE_TASK_STATUSES, MaintenanceStatus,
                            OPEN_ALERT_STATUSES, OPEN_WORK_ORDER_STATUSES,
                            SlaState, TaskStatus, VehicleStatus)
from app.models import (Alert, Driver, MaintenanceSchedule, Route, Task, Vehicle,
                        WorkOrder)
from app.services import routes as route_svc
from app.services.derive import gps_freshness, vehicle_status

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


async def fleet_snapshot(session: AsyncSession, org_id: uuid.UUID,
                         org_settings: dict | None = None,
                         now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    cfg = org_settings or {}
    live_s = cfg.get("gps_live_threshold_s", 45)
    stale_s = cfg.get("gps_stale_threshold_s", 300)

    vehicles = (await session.execute(
        select(Vehicle).where(Vehicle.organization_id == org_id).order_by(Vehicle.name)
    )).scalars().all()
    drivers = {d.id: d for d in (await session.execute(
        select(Driver).where(Driver.organization_id == org_id)
    )).scalars().all()}

    # open alerts per vehicle, worst severity wins
    alert_rows = (await session.execute(
        select(Alert.vehicle_id, Alert.severity, func.count()).where(
            Alert.organization_id == org_id,
            Alert.status.in_(tuple(OPEN_ALERT_STATUSES)),
            Alert.vehicle_id.isnot(None),
        ).group_by(Alert.vehicle_id, Alert.severity)
    )).all()
    alerts_by_vehicle: dict[uuid.UUID, dict] = {}
    for vid, sev, n in alert_rows:
        entry = alerts_by_vehicle.setdefault(vid, {"count": 0, "worst": None})
        entry["count"] += n
        if entry["worst"] is None or SEVERITY_RANK[sev] > SEVERITY_RANK[entry["worst"]]:
            entry["worst"] = sev

    # active tasks per vehicle
    tasks = (await session.execute(
        select(Task).where(Task.organization_id == org_id,
                           Task.status.in_(ACTIVE_TASK_STATUSES),
                           Task.vehicle_id.isnot(None))
        .order_by(Task.scheduled_for)
    )).scalars().all()
    tasks_by_vehicle: dict[uuid.UUID, list[Task]] = {}
    for t in tasks:
        tasks_by_vehicle.setdefault(t.vehicle_id, []).append(t)

    # open work orders => vehicle is in maintenance
    wo_vehicles = set((await session.execute(
        select(WorkOrder.vehicle_id).where(
            WorkOrder.organization_id == org_id,
            WorkOrder.status.in_(OPEN_WORK_ORDER_STATUSES))
    )).scalars().all())

    # worst maintenance schedule status per vehicle
    sched_rows = (await session.execute(
        select(MaintenanceSchedule.vehicle_id, MaintenanceSchedule.status,
               func.count()).where(
            MaintenanceSchedule.organization_id == org_id,
            MaintenanceSchedule.is_active.is_(True),
        ).group_by(MaintenanceSchedule.vehicle_id, MaintenanceSchedule.status)
    )).all()
    order = [MaintenanceStatus.HEALTHY, MaintenanceStatus.DUE_SOON, MaintenanceStatus.DUE,
             MaintenanceStatus.IN_WORKSHOP, MaintenanceStatus.OVERDUE,
             MaintenanceStatus.CRITICAL]
    maint_by_vehicle: dict[uuid.UUID, str] = {}
    for vid, st, _n in sched_rows:
        cur = maint_by_vehicle.get(vid)
        if cur is None or order.index(st) > order.index(cur):
            maint_by_vehicle[vid] = st

    # active routes
    routes = {r.vehicle_id: r for r in (await session.execute(
        select(Route).where(Route.organization_id == org_id, Route.is_active.is_(True))
    )).scalars().all()}

    items = []
    counters = {k: 0 for k in ("moving", "idle", "stopped", "offline", "maintenance",
                               "not_tracked", "with_alerts", "active_tasks", "late_tasks")}
    for v in vehicles:
        driver = drivers.get(v.driver_id)
        status = vehicle_status(v, has_open_work_order=v.id in wo_vehicles,
                                live_s=live_s, stale_s=stale_s, now=now)
        freshness, age = gps_freshness(v.last_position_at, live_s=live_s,
                                       stale_s=stale_s, now=now)
        alert_info = alerts_by_vehicle.get(v.id, {"count": 0, "worst": None})
        v_tasks = tasks_by_vehicle.get(v.id, [])
        current = v_tasks[0] if v_tasks else None
        late = [t for t in v_tasks if t.sla_state in (SlaState.AT_RISK, SlaState.BREACHED)]

        route = routes.get(v.id)
        route_progress = None
        if route and v.last_lat is not None:
            p = route_svc.progress(route, v.last_lat, v.last_lon)
            route_progress = {
                "route_id": str(route.id), "progress_pct": p["progress_pct"],
                "remaining_km": round(p["remaining_m"] / 1000, 2),
                "deviation_m": p["deviation_m"],
                "destination": route.dest_name,
            }

        counters[status] = counters.get(status, 0) + 1
        if alert_info["count"]:
            counters["with_alerts"] += 1
        counters["active_tasks"] += len(v_tasks)
        counters["late_tasks"] += len(late)

        items.append({
            "id": str(v.id), "name": v.name, "plate": v.plate, "type": v.type,
            "status": status, "lifecycle": v.lifecycle, "fuel_type": v.fuel_type,
            "lat": v.last_lat, "lon": v.last_lon,
            "heading": v.last_heading or 0, "speed_kph": v.last_speed_kph or 0,
            "street": v.last_street, "odometer_km": round(v.odometer_km or 0, 1),
            "last_position_at": v.last_position_at.isoformat() if v.last_position_at else None,
            "gps": {"freshness": freshness, "age_s": round(age) if age is not None else None,
                    "satellites": v.gps_satellites},
            "ignition_on": v.ignition_on,
            "state_of_charge_pct": v.state_of_charge_pct,
            "range_km": v.range_km,
            "driver": {"id": str(driver.id), "name": driver.full_name,
                       "status": driver.status, "avatar_color": driver.avatar_color,
                       "safety_score": driver.safety_score,
                       "fatigue_risk": driver.fatigue_risk} if driver else None,
            "alerts": {"count": alert_info["count"], "worst": alert_info["worst"]},
            "maintenance_status": maint_by_vehicle.get(v.id, MaintenanceStatus.HEALTHY),
            "task": {
                "id": str(current.id), "reference": current.reference,
                "title": current.title, "status": current.status,
                "priority": current.priority, "sla_state": current.sla_state,
                "address": current.address,
                "eta": current.eta.isoformat() if current.eta else None,
            } if current else None,
            "task_count": len(v_tasks),
            "late_task_count": len(late),
            "route": route_progress,
        })

    return {"vehicles": items, "counters": counters,
            "generated_at": now.isoformat()}


async def kpi_strip(session: AsyncSession, org_id: uuid.UUID, snapshot: dict,
                    now: datetime | None = None) -> dict:
    """The bottom live strip. Every number is clickable and filters the page."""
    from app.models import Trip
    now = now or datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    distance_today = (await session.execute(
        select(func.coalesce(func.sum(Trip.distance_km), 0.0)).where(
            Trip.organization_id == org_id, Trip.started_at >= day_start)
    )).scalar_one()
    c = snapshot["counters"]
    active = sum(c.get(k, 0) for k in ("moving", "idle", "stopped"))
    return {
        "active_vehicles": active,
        "moving": c.get("moving", 0),
        "idle": c.get("idle", 0),
        "stopped": c.get("stopped", 0),
        "offline": c.get("offline", 0),
        "with_alerts": c.get("with_alerts", 0),
        "in_maintenance": c.get("maintenance", 0),
        "not_tracked": c.get("not_tracked", 0),
        "distance_today_km": round(float(distance_today), 1),
        "active_tasks": c.get("active_tasks", 0),
        "late_tasks": c.get("late_tasks", 0),
    }
