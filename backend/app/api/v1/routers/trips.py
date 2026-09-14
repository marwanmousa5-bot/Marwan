"""Trips & History, including full GPS playback."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_or_404, paginate
from app.auth.deps import Principal, require_tenant
from app.db.base import get_session
from app.models import (Alert, Driver, DriverEvent, Route, Task, Trip, TripPosition,
                        Vehicle)

router = APIRouter()


@router.get("")
async def list_trips(
    vehicle_id: uuid.UUID | None = None,
    driver_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    status_filter: str | None = Query(None, alias="status"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
):
    org_id = principal.org_id
    stmt = select(Trip).where(Trip.organization_id == org_id)
    if vehicle_id:
        stmt = stmt.where(Trip.vehicle_id == vehicle_id)
    if driver_id:
        stmt = stmt.where(Trip.driver_id == driver_id)
    if task_id:
        stmt = stmt.where(Trip.task_id == task_id)
    if status_filter:
        stmt = stmt.where(Trip.status == status_filter)
    if date_from:
        stmt = stmt.where(Trip.started_at >= date_from)
    if date_to:
        stmt = stmt.where(Trip.started_at <= date_to)
    result = await paginate(session, stmt.order_by(Trip.started_at.desc()), page, size)

    vehicles = {v.id: v for v in (await session.execute(
        select(Vehicle).where(Vehicle.organization_id == org_id))).scalars().all()}
    drivers = {d.id: d for d in (await session.execute(
        select(Driver).where(Driver.organization_id == org_id))).scalars().all()}
    result["items"] = [{
        "id": str(t.id), "reference": t.reference, "status": t.status,
        "started_at": t.started_at.isoformat(),
        "ended_at": t.ended_at.isoformat() if t.ended_at else None,
        "start_address": t.start_address, "end_address": t.end_address,
        "distance_km": round(t.distance_km, 2),
        "duration_s": round(t.duration_s),
        "idle_s": round(t.idle_s),
        "avg_speed_kph": t.avg_speed_kph, "max_speed_kph": t.max_speed_kph,
        "stop_count": t.stop_count, "event_count": t.event_count,
        "fuel_used_l": t.fuel_used_l, "energy_used_kwh": t.energy_used_kwh,
        "co2_kg": t.co2_kg,
        "vehicle": {"id": str(vehicles[t.vehicle_id].id),
                    "name": vehicles[t.vehicle_id].name,
                    "plate": vehicles[t.vehicle_id].plate}
        if t.vehicle_id in vehicles else None,
        "driver": {"id": str(drivers[t.driver_id].id),
                   "name": drivers[t.driver_id].full_name}
        if t.driver_id in drivers else None,
        "task_id": str(t.task_id) if t.task_id else None,
    } for t in result["items"]]
    return result


@router.get("/summary")
async def summary(days: int = Query(7, ge=1, le=90),
                  principal: Principal = Depends(require_tenant),
                  session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    since = datetime.now(timezone.utc) - timedelta(days=days)
    row = (await session.execute(
        select(func.count(), func.coalesce(func.sum(Trip.distance_km), 0.0),
               func.coalesce(func.sum(Trip.duration_s), 0.0),
               func.coalesce(func.sum(Trip.idle_s), 0.0),
               func.coalesce(func.avg(Trip.avg_speed_kph), 0.0),
               func.coalesce(func.max(Trip.max_speed_kph), 0.0),
               func.coalesce(func.sum(Trip.event_count), 0)).where(
            Trip.organization_id == org_id, Trip.started_at >= since))).one()
    trips, km, dur, idle, avg, mx, events = row
    return {
        "period_days": days, "trips": trips, "distance_km": round(float(km), 1),
        "driving_hours": round(float(dur) / 3600, 1),
        "idle_hours": round(float(idle) / 3600, 1),
        "avg_speed_kph": round(float(avg), 1), "max_speed_kph": round(float(mx), 1),
        "events": int(events),
        "idle_share_pct": round(float(idle) / float(dur) * 100, 1) if dur else 0,
    }


@router.get("/{trip_id}")
async def trip_detail(trip_id: uuid.UUID,
                      principal: Principal = Depends(require_tenant),
                      session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    t: Trip = await get_or_404(session, Trip, trip_id, org_id, "Trip")
    vehicle = await session.get(Vehicle, t.vehicle_id)
    driver = await session.get(Driver, t.driver_id) if t.driver_id else None
    task = await session.get(Task, t.task_id) if t.task_id else None
    route = await session.get(Route, t.route_id) if t.route_id else None
    events = (await session.execute(
        select(DriverEvent).where(DriverEvent.trip_id == t.id)
        .order_by(DriverEvent.occurred_at))).scalars().all()
    alerts = (await session.execute(
        select(Alert).where(Alert.trip_id == t.id)
        .order_by(Alert.triggered_at))).scalars().all()
    return {
        "id": str(t.id), "reference": t.reference, "status": t.status,
        "started_at": t.started_at.isoformat(),
        "ended_at": t.ended_at.isoformat() if t.ended_at else None,
        "start_address": t.start_address, "end_address": t.end_address,
        "start": {"lat": t.start_lat, "lon": t.start_lon},
        "end": {"lat": t.end_lat, "lon": t.end_lon},
        "distance_km": round(t.distance_km, 2), "duration_s": round(t.duration_s),
        "idle_s": round(t.idle_s), "avg_speed_kph": t.avg_speed_kph,
        "max_speed_kph": t.max_speed_kph, "stop_count": t.stop_count,
        "fuel_used_l": t.fuel_used_l, "energy_used_kwh": t.energy_used_kwh,
        "co2_kg": t.co2_kg,
        "start_odometer_km": t.start_odometer_km, "end_odometer_km": t.end_odometer_km,
        "vehicle": {"id": str(vehicle.id), "name": vehicle.name,
                    "plate": vehicle.plate} if vehicle else None,
        "driver": {"id": str(driver.id), "name": driver.full_name} if driver else None,
        "task": {"id": str(task.id), "reference": task.reference,
                 "title": task.title} if task else None,
        "planned_route": route.geometry if route else None,
        "events": [{"id": str(e.id), "type": e.type, "severity": e.severity,
                    "occurred_at": e.occurred_at.isoformat(), "lat": e.lat, "lon": e.lon,
                    "street": e.street, "value": e.value, "detail": e.detail}
                   for e in events],
        "alerts": [{"id": str(a.id), "code": a.code, "title": a.title,
                    "severity": a.severity,
                    "triggered_at": a.triggered_at.isoformat()} for a in alerts],
    }


@router.get("/{trip_id}/playback")
async def playback(trip_id: uuid.UUID,
                   principal: Principal = Depends(require_tenant),
                   session: AsyncSession = Depends(get_session)):
    """Every persisted GPS sample, plus the events pinned to the timeline."""
    org_id = principal.org_id
    t: Trip = await get_or_404(session, Trip, trip_id, org_id, "Trip")
    rows = (await session.execute(
        select(TripPosition).where(TripPosition.trip_id == t.id)
        .order_by(TripPosition.recorded_at))).scalars().all()
    events = (await session.execute(
        select(DriverEvent).where(DriverEvent.trip_id == t.id)
        .order_by(DriverEvent.occurred_at))).scalars().all()
    base = rows[0].recorded_at if rows else t.started_at
    return {
        "trip_id": str(t.id), "reference": t.reference,
        "started_at": t.started_at.isoformat(),
        "ended_at": t.ended_at.isoformat() if t.ended_at else None,
        "sample_count": len(rows),
        "samples": [{
            "t": round((p.recorded_at - base).total_seconds(), 1),
            "at": p.recorded_at.isoformat(),
            "lat": p.lat, "lon": p.lon, "speed_kph": p.speed_kph,
            "heading": p.heading, "street": p.street,
            "odometer_km": p.odometer_km, "ignition": p.ignition,
        } for p in rows],
        "events": [{
            "id": str(e.id), "type": e.type, "severity": e.severity,
            "t": round((e.occurred_at - base).total_seconds(), 1),
            "at": e.occurred_at.isoformat(), "lat": e.lat, "lon": e.lon,
            "street": e.street, "detail": e.detail, "value": e.value,
        } for e in events],
    }
