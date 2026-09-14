"""Live Tracking - the command centre's data surface."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_or_404
from app.auth.deps import Principal, require_operator, require_tenant
from app.core.enums import (ACTIVE_TASK_STATUSES, OPEN_ALERT_STATUSES, Role,
                            VehicleLifecycle)
from app.db.base import get_session
from app.models import (Alert, Driver, Geofence, Place, RoadDisruption, Route,
                        SavedView, Task, Trip, Vehicle, WeatherObservation)
from app.schemas.common import Message
from app.services import audit
from app.services import fleetview, routes as route_svc
from app.services.derive import gps_freshness, vehicle_status
from app.simulation.engine import engine as simulation

router = APIRouter()


@router.get("/fleet")
async def fleet(principal: Principal = Depends(require_tenant),
                session: AsyncSession = Depends(get_session)):
    """Every vehicle with driver, task, alert, maintenance and route context."""
    snapshot = await fleetview.fleet_snapshot(session, principal.org_id,
                                              principal.organization.settings)
    snapshot["kpis"] = await fleetview.kpi_strip(session, principal.org_id, snapshot)
    snapshot["simulation"] = {"running": simulation.running, "ticks": simulation.tick_count}
    return snapshot


@router.get("/vehicles/{vehicle_id}/panel")
async def vehicle_panel(vehicle_id: uuid.UUID,
                        principal: Principal = Depends(require_tenant),
                        session: AsyncSession = Depends(get_session)):
    """The quick panel shown when a vehicle is selected (spec 2.9)."""
    org_id = principal.org_id
    vehicle: Vehicle = await get_or_404(session, Vehicle, vehicle_id, org_id, "Vehicle")
    cfg = principal.organization.settings or {}
    now = datetime.now(timezone.utc)

    driver = await session.get(Driver, vehicle.driver_id) if vehicle.driver_id else None
    task = (await session.execute(
        select(Task).where(Task.vehicle_id == vehicle.id,
                           Task.status.in_(ACTIVE_TASK_STATUSES))
        .order_by(Task.scheduled_for).limit(1)
    )).scalars().first()
    alerts = (await session.execute(
        select(Alert).where(Alert.vehicle_id == vehicle.id,
                            Alert.status.in_(tuple(OPEN_ALERT_STATUSES)))
        .order_by(Alert.triggered_at.desc()).limit(10)
    )).scalars().all()
    trip = (await session.execute(
        select(Trip).where(Trip.vehicle_id == vehicle.id, Trip.status == "active")
        .order_by(Trip.started_at.desc()).limit(1)
    )).scalars().first()

    route = None
    route_detail = None
    if task and task.route_id:
        route = await session.get(Route, task.route_id)
    if route is None:
        route = (await session.execute(
            select(Route).where(Route.vehicle_id == vehicle.id, Route.is_active.is_(True))
            .limit(1)
        )).scalars().first()
    if route and vehicle.last_lat is not None:
        p = route_svc.progress(route, vehicle.last_lat, vehicle.last_lon)
        eta = route_svc.eta_from(route, vehicle.last_lat, vehicle.last_lon,
                                 vehicle.last_speed_kph, now)
        route_detail = {
            "id": str(route.id), "name": route.name,
            "destination": route.dest_name,
            "planned": route.geometry,
            "travelled": route_svc.travelled_geometry(route, vehicle.last_lat, vehicle.last_lon),
            "remaining": route_svc.remaining_geometry(route, vehicle.last_lat, vehicle.last_lon),
            "progress_pct": p["progress_pct"],
            "remaining_km": round(p["remaining_m"] / 1000, 2),
            "deviation_m": p["deviation_m"],
            "eta": eta.isoformat() if eta else None,
            "planned_distance_km": round(route.distance_m / 1000, 2),
            "planned_duration_min": round(route.duration_s / 60),
            "stops": [{"id": str(s.id), "sequence": s.sequence, "name": s.name,
                       "lat": s.lat, "lon": s.lon, "type": s.stop_type,
                       "planned_arrival": s.planned_arrival.isoformat()
                       if s.planned_arrival else None,
                       "arrived_at": s.arrived_at.isoformat() if s.arrived_at else None}
                      for s in route.stops],
        }

    freshness, age = gps_freshness(
        vehicle.last_position_at, live_s=cfg.get("gps_live_threshold_s", 45),
        stale_s=cfg.get("gps_stale_threshold_s", 300), now=now)

    return {
        "vehicle": {
            "id": str(vehicle.id), "name": vehicle.name, "plate": vehicle.plate,
            "type": vehicle.type, "make": vehicle.make, "model": vehicle.model,
            "fuel_type": vehicle.fuel_type, "lifecycle": vehicle.lifecycle,
            "status": vehicle_status(vehicle, now=now),
            "lat": vehicle.last_lat, "lon": vehicle.last_lon,
            "speed_kph": vehicle.last_speed_kph or 0,
            "heading": vehicle.last_heading or 0,
            "street": vehicle.last_street,
            "odometer_km": round(vehicle.odometer_km or 0, 1),
            "state_of_charge_pct": vehicle.state_of_charge_pct,
            "range_km": vehicle.range_km,
            "gps": {"freshness": freshness, "age_s": round(age) if age is not None else None,
                    "satellites": vehicle.gps_satellites},
            "last_position_at": vehicle.last_position_at.isoformat()
            if vehicle.last_position_at else None,
        },
        "driver": {"id": str(driver.id), "name": driver.full_name, "phone": driver.phone,
                   "status": driver.status, "safety_score": driver.safety_score,
                   "fatigue_risk": driver.fatigue_risk,
                   "avatar_color": driver.avatar_color} if driver else None,
        "task": {"id": str(task.id), "reference": task.reference, "title": task.title,
                 "status": task.status, "priority": task.priority,
                 "sla_state": task.sla_state, "address": task.address,
                 "eta": task.eta.isoformat() if task.eta else None,
                 "sla_due_at": task.sla_due_at.isoformat() if task.sla_due_at else None,
                 } if task else None,
        "trip": {"id": str(trip.id), "reference": trip.reference,
                 "started_at": trip.started_at.isoformat(),
                 "distance_km": trip.distance_km} if trip else None,
        "route": route_detail,
        "alerts": [{"id": str(a.id), "code": a.code, "title": a.title,
                    "severity": a.severity, "status": a.status,
                    "triggered_at": a.triggered_at.isoformat(),
                    "occurrence_count": a.occurrence_count} for a in alerts],
        "permissions": {
            "can_assign": principal.role in (Role.ORG_ADMIN, Role.DISPATCHER),
            "can_create_task": principal.role in (Role.ORG_ADMIN, Role.DISPATCHER),
            "can_edit_vehicle": principal.role == Role.ORG_ADMIN,
            "can_assign_device": False,
        },
    }


@router.get("/layers")
async def layers(principal: Principal = Depends(require_tenant),
                 session: AsyncSession = Depends(get_session)):
    """Everything the map can overlay: places, geofences, disruptions, weather."""
    org_id = principal.org_id
    now = datetime.now(timezone.utc)
    places = (await session.execute(
        select(Place).where(Place.organization_id == org_id, Place.is_active.is_(True))
    )).scalars().all()
    fences = (await session.execute(
        select(Geofence).where(Geofence.organization_id == org_id)
    )).scalars().all()
    disruptions = (await session.execute(
        select(RoadDisruption).where(RoadDisruption.organization_id == org_id,
                                     RoadDisruption.is_active.is_(True))
    )).scalars().all()
    weather = (await session.execute(
        select(WeatherObservation).where(
            WeatherObservation.organization_id == org_id,
            WeatherObservation.observed_at >= now - timedelta(hours=3),
        ).order_by(WeatherObservation.observed_at.desc()).limit(40)
    )).scalars().all()
    open_tasks = (await session.execute(
        select(Task).where(Task.organization_id == org_id,
                           Task.status.in_(ACTIVE_TASK_STATUSES + ("unassigned",)),
                           Task.lat.isnot(None))
    )).scalars().all()

    return {
        "places": [{"id": str(p.id), "name": p.name, "category": p.category,
                    "lat": p.lat, "lon": p.lon, "address": p.address} for p in places],
        "geofences": [{"id": str(g.id), "name": g.name, "type": g.type,
                       "trigger": g.trigger, "colour": g.colour,
                       "polygon": g.polygon, "centre_lat": g.centre_lat,
                       "centre_lon": g.centre_lon, "radius_m": g.radius_m,
                       "is_active": g.is_active, "is_restricted": g.is_restricted}
                      for g in fences],
        "disruptions": [{"id": str(d.id), "kind": d.kind, "title": d.title,
                         "severity": d.severity, "lat": d.lat, "lon": d.lon,
                         "radius_m": d.radius_m, "street": d.street,
                         "delay_minutes": d.delay_minutes,
                         "description": d.description} for d in disruptions],
        "weather": [{"id": str(w.id), "condition": w.condition, "lat": w.lat, "lon": w.lon,
                     "temperature_c": w.temperature_c, "wind_kph": w.wind_kph,
                     "precipitation_mm": w.precipitation_mm, "severity": w.severity,
                     "radius_m": w.radius_m,
                     "observed_at": w.observed_at.isoformat()} for w in weather],
        "tasks": [{"id": str(t.id), "reference": t.reference, "title": t.title,
                   "status": t.status, "priority": t.priority, "sla_state": t.sla_state,
                   "lat": t.lat, "lon": t.lon, "address": t.address} for t in open_tasks],
        "traffic_available": False,
        "traffic_message": "Live traffic is not available from the configured map "
                           "provider. Known closures and weather cells are shown instead.",
    }


# --- saved views ------------------------------------------------------------
class SavedViewIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    filters: dict = Field(default_factory=dict)
    surface: str = "live_tracking"
    is_shared: bool = False


@router.get("/views")
async def list_views(surface: str = "live_tracking",
                     principal: Principal = Depends(require_tenant),
                     session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(SavedView).where(
            SavedView.organization_id == principal.org_id,
            SavedView.surface == surface,
        ).order_by(SavedView.name)
    )).scalars().all()
    visible = [v for v in rows if v.is_shared or v.owner_id == principal.user.id]
    return [{"id": str(v.id), "name": v.name, "filters": v.filters,
             "is_shared": v.is_shared, "is_mine": v.owner_id == principal.user.id}
            for v in visible]


@router.post("/views", status_code=status.HTTP_201_CREATED)
async def create_view(payload: SavedViewIn,
                      principal: Principal = Depends(require_tenant),
                      session: AsyncSession = Depends(get_session)):
    view = SavedView(organization_id=principal.org_id, name=payload.name.strip(),
                     surface=payload.surface, filters=payload.filters,
                     owner_id=principal.user.id, is_shared=payload.is_shared)
    session.add(view)
    await session.commit()
    return {"id": str(view.id), "name": view.name, "filters": view.filters,
            "is_shared": view.is_shared, "is_mine": True}


@router.delete("/views/{view_id}", response_model=Message)
async def delete_view(view_id: uuid.UUID,
                      principal: Principal = Depends(require_tenant),
                      session: AsyncSession = Depends(get_session)):
    view: SavedView = await get_or_404(session, SavedView, view_id, principal.org_id,
                                       "Saved view")
    if view.owner_id != principal.user.id and principal.role != Role.ORG_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only the owner or a fleet administrator can delete this view.")
    name = view.name
    await session.delete(view)
    await session.commit()
    return Message(detail=f"Saved view “{name}” deleted.")


@router.get("/simulation")
async def simulation_status(principal: Principal = Depends(require_tenant)):
    return {"running": simulation.running, "ticks": simulation.tick_count,
            "tracked_vehicles": len(simulation.state)}
