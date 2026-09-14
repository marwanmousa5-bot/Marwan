"""Vehicle registry and the Vehicle 360 workspace."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_or_404, paginate
from app.auth.deps import Principal, require_admin_of_org, require_operator, require_tenant
from app.core.enums import (ACTIVE_TASK_STATUSES, CostCategory, FuelType,
                            MaintenanceStatus, OPEN_ALERT_STATUSES,
                            OPEN_WORK_ORDER_STATUSES, Ownership, VehicleLifecycle,
                            VehicleType)
from app.db.base import get_session
from app.models import (Alert, ChargingSession, CostRecord, Device, Document, Driver,
                        FuelTransaction, Incident, MaintenanceRecord,
                        MaintenanceSchedule, Task, TimelineEvent, Trip, Vehicle,
                        WorkOrder)
from app.schemas.common import Message
from app.services import audit, maintenance as maint_svc
from app.services.derive import (annual_depreciation, gps_freshness,
                                 straight_line_depreciation, vehicle_status)

router = APIRouter()

EDITABLE = ["name", "plate", "vin", "type", "make", "model", "year", "colour",
            "fuel_type", "lifecycle", "ownership", "purchase_date", "purchase_value",
            "residual_value", "depreciation_years", "annual_insurance_cost",
            "annual_registration_cost", "tank_capacity_l", "avg_consumption_l_100km",
            "battery_capacity_kwh", "notes", "odometer_km"]


class VehicleIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    plate: str = Field(min_length=1, max_length=30)
    type: VehicleType = VehicleType.VAN
    fuel_type: FuelType = FuelType.DIESEL
    vin: str | None = None
    make: str = ""
    model: str = ""
    year: int | None = None
    colour: str = "White"
    ownership: Ownership = Ownership.OWNED
    odometer_km: float = 0
    purchase_date: date | None = None
    purchase_value: float | None = None
    residual_value: float | None = None
    depreciation_years: int = 7
    annual_insurance_cost: float | None = None
    annual_registration_cost: float | None = None
    tank_capacity_l: float | None = None
    avg_consumption_l_100km: float | None = None
    battery_capacity_kwh: float | None = None
    driver_id: uuid.UUID | None = None
    notes: str | None = None


class VehicleUpdate(BaseModel):
    name: str | None = None
    plate: str | None = None
    type: VehicleType | None = None
    fuel_type: FuelType | None = None
    vin: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    colour: str | None = None
    ownership: Ownership | None = None
    lifecycle: VehicleLifecycle | None = None
    odometer_km: float | None = None
    purchase_date: date | None = None
    purchase_value: float | None = None
    residual_value: float | None = None
    depreciation_years: int | None = None
    annual_insurance_cost: float | None = None
    annual_registration_cost: float | None = None
    tank_capacity_l: float | None = None
    avg_consumption_l_100km: float | None = None
    battery_capacity_kwh: float | None = None
    notes: str | None = None


@router.get("")
async def list_vehicles(
    q: str | None = None,
    type: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    lifecycle: str | None = None,
    driver_id: uuid.UUID | None = None,
    maintenance: str | None = None,
    has_device: bool | None = None,
    page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
):
    org_id = principal.org_id
    stmt = select(Vehicle).where(Vehicle.organization_id == org_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Vehicle.name.ilike(like), Vehicle.plate.ilike(like),
                              Vehicle.make.ilike(like), Vehicle.model.ilike(like)))
    if type:
        stmt = stmt.where(Vehicle.type == type)
    if lifecycle:
        stmt = stmt.where(Vehicle.lifecycle == lifecycle)
    if driver_id:
        stmt = stmt.where(Vehicle.driver_id == driver_id)
    stmt = stmt.order_by(Vehicle.name)

    result = await paginate(session, stmt, page, size)
    vehicles = result["items"]

    drivers = {d.id: d for d in (await session.execute(
        select(Driver).where(Driver.organization_id == org_id))).scalars().all()}
    devices = {d.vehicle_id: d for d in (await session.execute(
        select(Device).where(Device.organization_id == org_id,
                             Device.vehicle_id.isnot(None)))).scalars().all()}
    wo_vehicles = set((await session.execute(
        select(WorkOrder.vehicle_id).where(
            WorkOrder.organization_id == org_id,
            WorkOrder.status.in_(OPEN_WORK_ORDER_STATUSES)))).scalars().all())
    alert_counts = dict((await session.execute(
        select(Alert.vehicle_id, func.count()).where(
            Alert.organization_id == org_id,
            Alert.status.in_(tuple(OPEN_ALERT_STATUSES)),
            Alert.vehicle_id.isnot(None)).group_by(Alert.vehicle_id))).all())
    maint_rows = (await session.execute(
        select(MaintenanceSchedule.vehicle_id, MaintenanceSchedule.status).where(
            MaintenanceSchedule.organization_id == org_id,
            MaintenanceSchedule.is_active.is_(True)))).all()
    order = [MaintenanceStatus.HEALTHY, MaintenanceStatus.DUE_SOON, MaintenanceStatus.DUE,
             MaintenanceStatus.IN_WORKSHOP, MaintenanceStatus.OVERDUE,
             MaintenanceStatus.CRITICAL]
    maint_by = {}
    for vid, st in maint_rows:
        cur = maint_by.get(vid)
        if cur is None or order.index(st) > order.index(cur):
            maint_by[vid] = st

    # utilisation: share of the last 30 days with recorded trips
    since = datetime.now(timezone.utc) - timedelta(days=30)
    util_rows = dict((await session.execute(
        select(Trip.vehicle_id, func.coalesce(func.sum(Trip.duration_s), 0.0)).where(
            Trip.organization_id == org_id, Trip.started_at >= since
        ).group_by(Trip.vehicle_id))).all())

    now = datetime.now(timezone.utc)
    items = []
    for v in vehicles:
        driver = drivers.get(v.driver_id)
        device = devices.get(v.id)
        st = vehicle_status(v, has_open_work_order=v.id in wo_vehicles, now=now)
        if status_filter and st != status_filter:
            continue
        m = maint_by.get(v.id, MaintenanceStatus.HEALTHY)
        if maintenance and m != maintenance:
            continue
        if has_device is not None and bool(device) != has_device:
            continue
        # assume a 10 h operating day
        util = min(100, round(float(util_rows.get(v.id, 0)) / (30 * 10 * 3600) * 100))
        items.append({
            "id": str(v.id), "name": v.name, "plate": v.plate, "type": v.type,
            "make": v.make, "model": v.model, "year": v.year, "fuel_type": v.fuel_type,
            "lifecycle": v.lifecycle, "status": st,
            "driver": {"id": str(driver.id), "name": driver.full_name,
                       "avatar_color": driver.avatar_color} if driver else None,
            "location": v.last_street, "lat": v.last_lat, "lon": v.last_lon,
            "speed_kph": v.last_speed_kph or 0,
            "odometer_km": round(v.odometer_km or 0, 1),
            "device": {"serial": device.serial, "status": device.status} if device else None,
            "maintenance_status": m,
            "alert_count": alert_counts.get(v.id, 0),
            "utilisation_pct": util,
            "state_of_charge_pct": v.state_of_charge_pct,
            "last_position_at": v.last_position_at.isoformat() if v.last_position_at else None,
        })
    result["items"] = items
    result["total"] = len(items) if (status_filter or maintenance or has_device is not None) \
        else result["total"]
    return result


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_vehicle(payload: VehicleIn,
                         principal: Principal = Depends(require_admin_of_org),
                         session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    clash = (await session.execute(
        select(Vehicle).where(Vehicle.organization_id == org_id,
                              func.lower(Vehicle.plate) == payload.plate.lower())
    )).scalars().first()
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"A vehicle with plate {payload.plate} already exists "
                            f"({clash.name}).")
    data = payload.model_dump()
    driver_id = data.pop("driver_id", None)
    vehicle = Vehicle(organization_id=org_id, **data)
    if driver_id:
        driver = await get_or_404(session, Driver, driver_id, org_id, "Driver")
        vehicle.driver_id = driver.id
    session.add(vehicle)
    await session.flush()
    await audit.record(session, action="vehicle.created", organization_id=org_id,
                       actor=principal.user, entity_type="vehicle", entity_id=vehicle.id,
                       entity_label=vehicle.name,
                       summary=f"Vehicle {vehicle.name} ({vehicle.plate}) added",
                       after=audit.snapshot(vehicle, EDITABLE))
    await audit.timeline(session, organization_id=org_id, entity_type="vehicle",
                         entity_id=vehicle.id, action="created", actor=principal.user,
                         description=f"{vehicle.name} added to the fleet.")
    await session.commit()
    return {"id": str(vehicle.id), "name": vehicle.name, "plate": vehicle.plate}


@router.patch("/{vehicle_id}")
async def update_vehicle(vehicle_id: uuid.UUID, payload: VehicleUpdate,
                         principal: Principal = Depends(require_admin_of_org),
                         session: AsyncSession = Depends(get_session)):
    vehicle: Vehicle = await get_or_404(session, Vehicle, vehicle_id, principal.org_id,
                                        "Vehicle")
    before = audit.snapshot(vehicle, EDITABLE)
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(vehicle, k, v)
    await session.flush()
    await audit.record(session, action="vehicle.updated", organization_id=principal.org_id,
                       actor=principal.user, entity_type="vehicle", entity_id=vehicle.id,
                       entity_label=vehicle.name,
                       summary=f"{vehicle.name} updated: " + ", ".join(changes),
                       before=before, after=audit.snapshot(vehicle, EDITABLE))
    await audit.timeline(session, organization_id=principal.org_id, entity_type="vehicle",
                         entity_id=vehicle.id, action="updated", actor=principal.user,
                         description="Vehicle details updated: " + ", ".join(
                             k.replace('_', ' ') for k in changes))
    await session.commit()
    return {"id": str(vehicle.id), "updated": list(changes)}


class AssignDriver(BaseModel):
    driver_id: uuid.UUID | None = None


@router.post("/{vehicle_id}/driver")
async def assign_driver(vehicle_id: uuid.UUID, payload: AssignDriver,
                        principal: Principal = Depends(require_operator),
                        session: AsyncSession = Depends(get_session)):
    """Reassignment ripples to the driver, live map, dispatch and both timelines."""
    org_id = principal.org_id
    vehicle: Vehicle = await get_or_404(session, Vehicle, vehicle_id, org_id, "Vehicle")
    previous = await session.get(Driver, vehicle.driver_id) if vehicle.driver_id else None
    driver = None
    if payload.driver_id:
        driver = await get_or_404(session, Driver, payload.driver_id, org_id, "Driver")
        other = (await session.execute(
            select(Vehicle).where(Vehicle.driver_id == driver.id,
                                  Vehicle.id != vehicle.id)
        )).scalars().first()
        if other:
            other.driver_id = None
            await audit.timeline(session, organization_id=org_id, entity_type="vehicle",
                                 entity_id=other.id, action="driver_unassigned",
                                 actor=principal.user,
                                 description=f"{driver.full_name} moved to {vehicle.name}.")

    vehicle.driver_id = driver.id if driver else None

    # active tasks follow the vehicle's driver
    tasks = (await session.execute(
        select(Task).where(Task.vehicle_id == vehicle.id,
                           Task.status.in_(ACTIVE_TASK_STATUSES))
    )).scalars().all()
    for t in tasks:
        t.driver_id = vehicle.driver_id
        await audit.timeline(session, organization_id=org_id, entity_type="task",
                             entity_id=t.id, action="driver_changed", actor=principal.user,
                             description=f"Driver changed to "
                                         f"{driver.full_name if driver else 'unassigned'} "
                                         f"with the vehicle.")

    who = driver.full_name if driver else "nobody"
    await audit.record(session, action="vehicle.driver_assigned", organization_id=org_id,
                       actor=principal.user, entity_type="vehicle", entity_id=vehicle.id,
                       entity_label=vehicle.name,
                       summary=f"{vehicle.name} assigned to {who}",
                       before={"driver": previous.full_name if previous else None},
                       after={"driver": who})
    await audit.timeline(session, organization_id=org_id, entity_type="vehicle",
                         entity_id=vehicle.id, action="driver_assigned",
                         actor=principal.user,
                         description=f"Driver set to {who}.",
                         related_type="driver", related_id=driver.id if driver else None)
    if driver:
        await audit.timeline(session, organization_id=org_id, entity_type="driver",
                             entity_id=driver.id, action="vehicle_assigned",
                             actor=principal.user,
                             description=f"Assigned to {vehicle.name} ({vehicle.plate}).",
                             related_type="vehicle", related_id=vehicle.id)
    if previous and (not driver or previous.id != driver.id):
        await audit.timeline(session, organization_id=org_id, entity_type="driver",
                             entity_id=previous.id, action="vehicle_unassigned",
                             actor=principal.user,
                             description=f"No longer assigned to {vehicle.name}.")
    await session.commit()
    return {"vehicle_id": str(vehicle.id),
            "driver": {"id": str(driver.id), "name": driver.full_name} if driver else None,
            "tasks_updated": len(tasks)}


class RetireRequest(BaseModel):
    reason: str | None = None


@router.post("/{vehicle_id}/retire", response_model=Message)
async def retire(vehicle_id: uuid.UUID, payload: RetireRequest,
                 principal: Principal = Depends(require_admin_of_org),
                 session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    vehicle: Vehicle = await get_or_404(session, Vehicle, vehicle_id, org_id, "Vehicle")
    active = (await session.execute(
        select(func.count()).select_from(Task).where(
            Task.vehicle_id == vehicle.id, Task.status.in_(ACTIVE_TASK_STATUSES))
    )).scalar_one()
    if active:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{vehicle.name} still has {active} active task"
            f"{'s' if active != 1 else ''}. Reassign them before retiring the vehicle.",
        )
    vehicle.lifecycle = VehicleLifecycle.RETIRED
    vehicle.retired_at = datetime.now(timezone.utc)
    vehicle.driver_id = None
    await audit.record(session, action="vehicle.retired", organization_id=org_id,
                       actor=principal.user, entity_type="vehicle", entity_id=vehicle.id,
                       entity_label=vehicle.name, summary=f"{vehicle.name} retired",
                       after={"reason": payload.reason})
    await audit.timeline(session, organization_id=org_id, entity_type="vehicle",
                         entity_id=vehicle.id, action="retired", actor=principal.user,
                         description=f"Vehicle retired."
                                     + (f" Reason: {payload.reason}" if payload.reason else ""))
    await session.commit()
    return Message(detail=f"{vehicle.name} has been retired and removed from operations.")


# --------------------------------------------------------------------------- #
# Vehicle 360
# --------------------------------------------------------------------------- #
@router.get("/{vehicle_id}")
async def vehicle_overview(vehicle_id: uuid.UUID,
                           principal: Principal = Depends(require_tenant),
                           session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    cfg = principal.organization.settings or {}
    v: Vehicle = await get_or_404(session, Vehicle, vehicle_id, org_id, "Vehicle")
    now = datetime.now(timezone.utc)
    driver = await session.get(Driver, v.driver_id) if v.driver_id else None
    device = (await session.execute(
        select(Device).where(Device.vehicle_id == v.id))).scalars().first()
    health = await maint_svc.vehicle_health(session, v, cfg)
    open_alerts = (await session.execute(
        select(func.count()).select_from(Alert).where(
            Alert.vehicle_id == v.id, Alert.status.in_(tuple(OPEN_ALERT_STATUSES)))
    )).scalar_one()
    task = (await session.execute(
        select(Task).where(Task.vehicle_id == v.id,
                           Task.status.in_(ACTIVE_TASK_STATUSES))
        .order_by(Task.scheduled_for).limit(1))).scalars().first()

    since = now - timedelta(days=30)
    km30 = (await session.execute(
        select(func.coalesce(func.sum(Trip.distance_km), 0.0)).where(
            Trip.vehicle_id == v.id, Trip.started_at >= since))).scalar_one()
    trips30 = (await session.execute(
        select(func.count()).select_from(Trip).where(
            Trip.vehicle_id == v.id, Trip.started_at >= since))).scalar_one()
    freshness, age = gps_freshness(v.last_position_at, now=now)

    return {
        "id": str(v.id), "name": v.name, "plate": v.plate, "vin": v.vin, "type": v.type,
        "make": v.make, "model": v.model, "year": v.year, "colour": v.colour,
        "fuel_type": v.fuel_type, "lifecycle": v.lifecycle, "ownership": v.ownership,
        "status": vehicle_status(v, has_open_work_order=health["open_work_orders"] > 0,
                                 now=now),
        "odometer_km": round(v.odometer_km or 0, 1),
        "lat": v.last_lat, "lon": v.last_lon, "street": v.last_street,
        "speed_kph": v.last_speed_kph or 0, "heading": v.last_heading or 0,
        "gps": {"freshness": freshness, "age_s": round(age) if age is not None else None,
                "satellites": v.gps_satellites},
        "last_position_at": v.last_position_at.isoformat() if v.last_position_at else None,
        "driver": {"id": str(driver.id), "name": driver.full_name,
                   "phone": driver.phone, "safety_score": driver.safety_score,
                   "avatar_color": driver.avatar_color} if driver else None,
        "device": {"id": str(device.id), "serial": device.serial, "imei": device.imei,
                   "model": device.model, "firmware": device.firmware,
                   "status": device.status} if device else None,
        "maintenance_health": health,
        "open_alerts": open_alerts,
        "current_task": {"id": str(task.id), "reference": task.reference,
                         "title": task.title, "status": task.status,
                         "sla_state": task.sla_state} if task else None,
        "battery": {"capacity_kwh": v.battery_capacity_kwh,
                    "state_of_charge_pct": v.state_of_charge_pct,
                    "range_km": v.range_km,
                    "charging_status": v.charging_status} if v.is_ev else None,
        "finance": {
            "purchase_date": v.purchase_date.isoformat() if v.purchase_date else None,
            "purchase_value": v.purchase_value,
            "residual_value": v.residual_value,
            "current_book_value": straight_line_depreciation(v),
            "annual_depreciation": annual_depreciation(v),
            "annual_insurance_cost": v.annual_insurance_cost,
            "annual_registration_cost": v.annual_registration_cost,
        },
        "usage_30d": {"distance_km": round(float(km30), 1), "trips": trips30},
        "notes": v.notes,
    }


@router.get("/{vehicle_id}/timeline")
async def vehicle_timeline(vehicle_id: uuid.UUID, limit: int = Query(60, le=300),
                           principal: Principal = Depends(require_tenant),
                           session: AsyncSession = Depends(get_session)):
    await get_or_404(session, Vehicle, vehicle_id, principal.org_id, "Vehicle")
    rows = (await session.execute(
        select(TimelineEvent).where(
            TimelineEvent.organization_id == principal.org_id,
            TimelineEvent.entity_type == "vehicle",
            TimelineEvent.entity_id == vehicle_id,
        ).order_by(TimelineEvent.occurred_at.desc()).limit(limit)
    )).scalars().all()
    return [{"id": str(r.id), "occurred_at": r.occurred_at.isoformat(),
             "actor_type": r.actor_type, "actor_name": r.actor_name, "action": r.action,
             "description": r.description, "related_type": r.related_type,
             "related_id": str(r.related_id) if r.related_id else None,
             "meta": r.meta} for r in rows]


@router.get("/{vehicle_id}/costs")
async def vehicle_costs(vehicle_id: uuid.UUID, months: int = Query(12, ge=1, le=36),
                        principal: Principal = Depends(require_tenant),
                        session: AsyncSession = Depends(get_session)):
    """Vehicle TCO: acquisition + operating - residual (spec 20)."""
    v: Vehicle = await get_or_404(session, Vehicle, vehicle_id, principal.org_id, "Vehicle")
    since = date.today() - timedelta(days=30 * months)
    rows = (await session.execute(
        select(CostRecord.category, func.coalesce(func.sum(CostRecord.amount), 0.0)).where(
            CostRecord.vehicle_id == v.id, CostRecord.incurred_on >= since
        ).group_by(CostRecord.category)
    )).all()
    by_category = {c: round(float(a), 2) for c, a in rows}

    depreciation = round(annual_depreciation(v) * months / 12, 2)
    if depreciation:
        by_category[CostCategory.DEPRECIATION] = depreciation
    operating = round(sum(by_category.values()), 2)

    km = (await session.execute(
        select(func.coalesce(func.sum(Trip.distance_km), 0.0)).where(
            Trip.vehicle_id == v.id,
            Trip.started_at >= datetime.combine(since, datetime.min.time(), timezone.utc))
    )).scalar_one()
    km = float(km)

    monthly = (await session.execute(
        select(func.date_trunc("month", CostRecord.incurred_on).label("m"),
               CostRecord.category,
               func.coalesce(func.sum(CostRecord.amount), 0.0)).where(
            CostRecord.vehicle_id == v.id, CostRecord.incurred_on >= since
        ).group_by("m", CostRecord.category).order_by("m")
    )).all()
    trend: dict[str, dict] = {}
    for m, cat, amount in monthly:
        key = m.strftime("%Y-%m")
        trend.setdefault(key, {"month": key, "total": 0.0})
        trend[key][cat] = round(float(amount), 2)
        trend[key]["total"] = round(trend[key]["total"] + float(amount), 2)

    book = straight_line_depreciation(v)
    return {
        "vehicle": {"id": str(v.id), "name": v.name, "plate": v.plate},
        "period_months": months,
        "by_category": by_category,
        "operating_cost": operating,
        "distance_km": round(km, 1),
        "cost_per_km": round(operating / km, 3) if km > 1 else None,
        "cost_per_day": round(operating / (months * 30), 2),
        "acquisition_cost": v.purchase_value or 0.0,
        "current_book_value": book,
        "residual_value": v.residual_value or 0.0,
        "tco": round((v.purchase_value or 0.0) + operating - book, 2),
        "trend": list(trend.values()),
    }
