"""Fuel & Energy, including EV charging."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_or_404, paginate
from app.auth.deps import Principal, require_operator, require_tenant
from app.core.enums import CostCategory, FuelType
from app.db.base import get_session
from app.models import (ChargingSession, CostRecord, Driver, FuelTransaction, Place,
                        Trip, Vehicle)
from app.services import audit

router = APIRouter()


class FuelIn(BaseModel):
    vehicle_id: uuid.UUID
    driver_id: uuid.UUID | None = None
    place_id: uuid.UUID | None = None
    occurred_at: datetime
    station_name: str | None = None
    fuel_type: FuelType = FuelType.DIESEL
    litres: float = Field(gt=0)
    price_per_litre: float = Field(gt=0)
    odometer_km: float = Field(ge=0)
    is_full_tank: bool = True
    reference: str | None = None


@router.get("/summary")
async def summary(days: int = Query(30, ge=1, le=365),
                  principal: Principal = Depends(require_tenant),
                  session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    since = datetime.now(timezone.utc) - timedelta(days=days)
    fuel = (await session.execute(
        select(func.coalesce(func.sum(FuelTransaction.litres), 0.0),
               func.coalesce(func.sum(FuelTransaction.total_cost), 0.0),
               func.count()).where(FuelTransaction.organization_id == org_id,
                                   FuelTransaction.occurred_at >= since))).one()
    energy = (await session.execute(
        select(func.coalesce(func.sum(ChargingSession.energy_kwh), 0.0),
               func.coalesce(func.sum(ChargingSession.total_cost), 0.0),
               func.count()).where(ChargingSession.organization_id == org_id,
                                   ChargingSession.started_at >= since))).one()
    km = (await session.execute(
        select(func.coalesce(func.sum(Trip.distance_km), 0.0)).where(
            Trip.organization_id == org_id, Trip.started_at >= since))).scalar_one()

    litres, fuel_cost, fills = fuel
    kwh, energy_cost, charges = energy
    km = float(km)
    total_cost = float(fuel_cost) + float(energy_cost)

    # per-vehicle consumption, computed from distance between full fills
    per_vehicle = []
    vehicles = (await session.execute(
        select(Vehicle).where(Vehicle.organization_id == org_id))).scalars().all()
    for v in vehicles:
        vl = (await session.execute(
            select(func.coalesce(func.sum(FuelTransaction.litres), 0.0),
                   func.coalesce(func.sum(FuelTransaction.total_cost), 0.0)).where(
                FuelTransaction.vehicle_id == v.id,
                FuelTransaction.occurred_at >= since))).one()
        vk = (await session.execute(
            select(func.coalesce(func.sum(Trip.distance_km), 0.0)).where(
                Trip.vehicle_id == v.id, Trip.started_at >= since))).scalar_one()
        vkwh = (await session.execute(
            select(func.coalesce(func.sum(ChargingSession.energy_kwh), 0.0),
                   func.coalesce(func.sum(ChargingSession.total_cost), 0.0)).where(
                ChargingSession.vehicle_id == v.id,
                ChargingSession.started_at >= since))).one()
        vk = float(vk)
        if vk < 5:
            continue
        entry = {
            "id": str(v.id), "name": v.name, "plate": v.plate, "type": v.type,
            "fuel_type": v.fuel_type, "distance_km": round(vk, 1),
            "litres": round(float(vl[0]), 1), "fuel_cost": round(float(vl[1]), 2),
            "kwh": round(float(vkwh[0]), 1), "energy_cost": round(float(vkwh[1]), 2),
        }
        cost = float(vl[1]) + float(vkwh[1])
        entry["cost_per_km"] = round(cost / vk, 3)
        if v.fuel_type == FuelType.ELECTRIC:
            entry["kwh_per_100km"] = round(float(vkwh[0]) / vk * 100, 2) \
                if float(vkwh[0]) else None
            entry["efficiency"] = entry["kwh_per_100km"]
            entry["efficiency_unit"] = "kWh/100km"
        else:
            entry["l_per_100km"] = round(float(vl[0]) / vk * 100, 2) if float(vl[0]) else None
            entry["efficiency"] = entry["l_per_100km"]
            entry["efficiency_unit"] = "L/100km"
        per_vehicle.append(entry)

    rated = [v for v in per_vehicle if v["efficiency"]]
    combustion = sorted([v for v in rated if v["fuel_type"] != FuelType.ELECTRIC],
                        key=lambda v: v["efficiency"])
    return {
        "period_days": days,
        "total_litres": round(float(litres), 1),
        "fuel_cost": round(float(fuel_cost), 2),
        "fill_count": fills,
        "total_kwh": round(float(kwh), 1),
        "energy_cost": round(float(energy_cost), 2),
        "charge_count": charges,
        "total_cost": round(total_cost, 2),
        "distance_km": round(km, 1),
        "avg_l_per_100km": round(float(litres) / km * 100, 2) if km > 5 else None,
        "cost_per_km": round(total_cost / km, 3) if km > 5 else None,
        "most_efficient": combustion[:5],
        "least_efficient": list(reversed(combustion))[:5],
        "per_vehicle": per_vehicle,
    }


@router.get("/transactions")
async def transactions(vehicle_id: uuid.UUID | None = None,
                       driver_id: uuid.UUID | None = None,
                       page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
                       principal: Principal = Depends(require_tenant),
                       session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    stmt = select(FuelTransaction).where(FuelTransaction.organization_id == org_id)
    if vehicle_id:
        stmt = stmt.where(FuelTransaction.vehicle_id == vehicle_id)
    if driver_id:
        stmt = stmt.where(FuelTransaction.driver_id == driver_id)
    result = await paginate(session, stmt.order_by(FuelTransaction.occurred_at.desc()),
                            page, size)
    vehicles = {v.id: v for v in (await session.execute(
        select(Vehicle).where(Vehicle.organization_id == org_id))).scalars().all()}
    drivers = {d.id: d for d in (await session.execute(
        select(Driver).where(Driver.organization_id == org_id))).scalars().all()}
    result["items"] = [{
        "id": str(f.id), "occurred_at": f.occurred_at.isoformat(),
        "station_name": f.station_name, "fuel_type": f.fuel_type,
        "litres": f.litres, "price_per_litre": f.price_per_litre,
        "total_cost": f.total_cost, "odometer_km": f.odometer_km,
        "distance_since_last_km": f.distance_since_last_km,
        "l_per_100km": round(f.litres / f.distance_since_last_km * 100, 2)
        if f.distance_since_last_km and f.distance_since_last_km > 5 else None,
        "is_full_tank": f.is_full_tank, "reference": f.reference,
        "vehicle": {"id": str(vehicles[f.vehicle_id].id),
                    "name": vehicles[f.vehicle_id].name,
                    "plate": vehicles[f.vehicle_id].plate}
        if f.vehicle_id in vehicles else None,
        "driver": {"id": str(drivers[f.driver_id].id),
                   "name": drivers[f.driver_id].full_name}
        if f.driver_id in drivers else None,
    } for f in result["items"]]
    return result


@router.post("/transactions", status_code=status.HTTP_201_CREATED)
async def create_transaction(payload: FuelIn,
                             principal: Principal = Depends(require_operator),
                             session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    vehicle: Vehicle = await get_or_404(session, Vehicle, payload.vehicle_id, org_id,
                                        "Vehicle")
    previous = (await session.execute(
        select(FuelTransaction).where(FuelTransaction.vehicle_id == vehicle.id,
                                      FuelTransaction.occurred_at < payload.occurred_at)
        .order_by(FuelTransaction.occurred_at.desc()).limit(1))).scalars().first()
    total = round(payload.litres * payload.price_per_litre, 2)
    tx = FuelTransaction(organization_id=org_id, total_cost=total,
                         distance_since_last_km=round(
                             payload.odometer_km - previous.odometer_km, 1)
                         if previous else None,
                         **payload.model_dump())
    session.add(tx)
    session.add(CostRecord(organization_id=org_id, vehicle_id=vehicle.id,
                           category=CostCategory.FUEL,
                           incurred_on=payload.occurred_at.date(), amount=total,
                           description=f"Fuel — {payload.station_name or 'station'}",
                           source_type="fuel_transaction",
                           odometer_km=payload.odometer_km))
    if payload.odometer_km > vehicle.odometer_km:
        vehicle.odometer_km = payload.odometer_km
    await session.flush()
    await audit.record(session, action="fuel.recorded", organization_id=org_id,
                       actor=principal.user, entity_type="fuel_transaction",
                       entity_id=tx.id, entity_label=vehicle.name,
                       summary=f"{payload.litres:.1f} L for {vehicle.name} (€{total:.2f})")
    await audit.timeline(session, organization_id=org_id, entity_type="vehicle",
                         entity_id=vehicle.id, action="refuelled", actor=principal.user,
                         occurred_at=payload.occurred_at,
                         description=f"Refuelled {payload.litres:.1f} L at "
                                     f"{payload.station_name or 'a station'} "
                                     f"(€{total:.2f}).")
    await session.commit()
    return {"id": str(tx.id), "total_cost": total,
            "l_per_100km": round(tx.litres / tx.distance_since_last_km * 100, 2)
            if tx.distance_since_last_km and tx.distance_since_last_km > 5 else None}


class ChargeIn(BaseModel):
    vehicle_id: uuid.UUID
    driver_id: uuid.UUID | None = None
    started_at: datetime
    ended_at: datetime | None = None
    location_name: str | None = None
    energy_kwh: float = Field(gt=0)
    price_per_kwh: float = Field(gt=0)
    start_soc_pct: float | None = None
    end_soc_pct: float | None = None
    odometer_km: float | None = None


@router.get("/charging")
async def charging(page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
                   principal: Principal = Depends(require_tenant),
                   session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    result = await paginate(session, select(ChargingSession).where(
        ChargingSession.organization_id == org_id).order_by(
        ChargingSession.started_at.desc()), page, size)
    vehicles = {v.id: v for v in (await session.execute(
        select(Vehicle).where(Vehicle.organization_id == org_id))).scalars().all()}
    result["items"] = [{
        "id": str(c.id), "started_at": c.started_at.isoformat(),
        "ended_at": c.ended_at.isoformat() if c.ended_at else None,
        "location_name": c.location_name, "energy_kwh": c.energy_kwh,
        "price_per_kwh": c.price_per_kwh, "total_cost": c.total_cost,
        "start_soc_pct": c.start_soc_pct, "end_soc_pct": c.end_soc_pct,
        "duration_min": round((c.ended_at - c.started_at).total_seconds() / 60)
        if c.ended_at else None,
        "vehicle": {"id": str(vehicles[c.vehicle_id].id),
                    "name": vehicles[c.vehicle_id].name}
        if c.vehicle_id in vehicles else None,
    } for c in result["items"]]
    return result


@router.post("/charging", status_code=status.HTTP_201_CREATED)
async def create_charge(payload: ChargeIn,
                        principal: Principal = Depends(require_operator),
                        session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    vehicle: Vehicle = await get_or_404(session, Vehicle, payload.vehicle_id, org_id,
                                        "Vehicle")
    if not vehicle.is_ev:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"{vehicle.name} is not an electric vehicle.")
    total = round(payload.energy_kwh * payload.price_per_kwh, 2)
    cs = ChargingSession(organization_id=org_id, total_cost=total, **payload.model_dump())
    session.add(cs)
    session.add(CostRecord(organization_id=org_id, vehicle_id=vehicle.id,
                           category=CostCategory.ENERGY,
                           incurred_on=payload.started_at.date(), amount=total,
                           description=f"Charging — {payload.location_name or 'charger'}",
                           source_type="charging_session"))
    if payload.end_soc_pct is not None:
        vehicle.state_of_charge_pct = payload.end_soc_pct
        if vehicle.battery_capacity_kwh:
            vehicle.range_km = round(payload.end_soc_pct / 100
                                     * vehicle.battery_capacity_kwh / 0.21, 0)
    await session.flush()
    await audit.timeline(session, organization_id=org_id, entity_type="vehicle",
                         entity_id=vehicle.id, action="charged", actor=principal.user,
                         occurred_at=payload.started_at,
                         description=f"Charged {payload.energy_kwh:.1f} kWh at "
                                     f"{payload.location_name or 'a charger'} "
                                     f"(€{total:.2f}).")
    await session.commit()
    return {"id": str(cs.id), "total_cost": total}


@router.get("/ev-overview")
async def ev_overview(days: int = Query(30, ge=1, le=365),
                      principal: Principal = Depends(require_tenant),
                      session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    since = datetime.now(timezone.utc) - timedelta(days=days)
    evs = (await session.execute(
        select(Vehicle).where(Vehicle.organization_id == org_id,
                              Vehicle.fuel_type == FuelType.ELECTRIC))).scalars().all()
    total_vehicles = (await session.execute(
        select(func.count()).select_from(Vehicle).where(
            Vehicle.organization_id == org_id))).scalar_one()
    rows = []
    for v in evs:
        km = float((await session.execute(
            select(func.coalesce(func.sum(Trip.distance_km), 0.0)).where(
                Trip.vehicle_id == v.id, Trip.started_at >= since))).scalar_one())
        kwh, cost = (await session.execute(
            select(func.coalesce(func.sum(ChargingSession.energy_kwh), 0.0),
                   func.coalesce(func.sum(ChargingSession.total_cost), 0.0)).where(
                ChargingSession.vehicle_id == v.id,
                ChargingSession.started_at >= since))).one()
        rows.append({
            "id": str(v.id), "name": v.name, "plate": v.plate,
            "battery_capacity_kwh": v.battery_capacity_kwh,
            "state_of_charge_pct": v.state_of_charge_pct,
            "range_km": v.range_km, "charging_status": v.charging_status,
            "distance_km": round(km, 1), "energy_kwh": round(float(kwh), 1),
            "energy_cost": round(float(cost), 2),
            "kwh_per_100km": round(float(kwh) / km * 100, 2) if km > 5 else None,
            "cost_per_km": round(float(cost) / km, 3) if km > 5 else None,
        })
    return {
        "ev_count": len(evs), "fleet_size": total_vehicles,
        "ev_share_pct": round(len(evs) / total_vehicles * 100, 1) if total_vehicles else 0,
        "total_energy_kwh": round(sum(r["energy_kwh"] for r in rows), 1),
        "total_energy_cost": round(sum(r["energy_cost"] for r in rows), 2),
        "total_distance_km": round(sum(r["distance_km"] for r in rows), 1),
        "vehicles": rows,
    }
