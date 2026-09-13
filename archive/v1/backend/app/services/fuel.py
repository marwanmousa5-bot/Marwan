"""Fuel and energy logging, with CO2 derived at write time (Sections 4.7, 4.17)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal
from app.core.errors import NotFoundError
from app.core.tenancy import TenantScope
from app.models.enums import AuditAction, FuelType
from app.models.fuel import FuelLog
from app.models.organization import OrganizationSettings
from app.models.vehicle import Vehicle
from app.services import audit

#: Fallbacks when an Organization has not overridden its factors. kg CO2 per
#: litre burned; electricity is counted at zero here because grid intensity
#: varies far too much by region to guess, and over-claiming a saving would be
#: worse than reporting none.
DEFAULT_EMISSION_FACTORS: dict[str, float] = {
    "petrol": 2.31,
    "diesel": 2.68,
    "lpg": 1.51,
    "hybrid": 2.10,
    "electric": 0.0,
}


def co2_for(quantity: float, fuel_type: str, factors: dict[str, float] | None) -> float:
    """kg of CO2 for a fuel or charging entry."""
    table = {**DEFAULT_EMISSION_FACTORS, **(factors or {})}
    return round(quantity * float(table.get(fuel_type, 0.0)), 3)


async def _factors(db: AsyncSession, scope: TenantScope) -> dict[str, float]:
    result = await db.execute(
        sa.select(OrganizationSettings)
        .where(OrganizationSettings.organization_id == scope.organization_id)
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return dict(row.co2_emission_factors or {}) if row else {}


async def list_logs(
    db: AsyncSession,
    scope: TenantScope,
    *,
    vehicle_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[FuelLog], int]:
    stmt = scope.select(FuelLog)
    if vehicle_id is not None:
        stmt = stmt.where(FuelLog.vehicle_id == vehicle_id)

    total = int(
        (await db.execute(sa.select(sa.func.count()).select_from(stmt.subquery())))
        .scalar_one()
    )
    result = await db.execute(
        stmt.order_by(FuelLog.filled_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all()), total


async def create_log(
    db: AsyncSession,
    scope: TenantScope,
    *,
    data: dict,
    principal: Principal | None = None,
    request: Request | None = None,
) -> FuelLog:
    vehicle = await scope.get(db, Vehicle, data["vehicle_id"])
    if vehicle is None:
        raise NotFoundError("Vehicle not found")

    entry = FuelLog(
        **data, created_by_user_id=principal.user_id if principal else None
    )
    scope.assign(entry)
    entry.co2_kg = co2_for(entry.quantity, entry.fuel_type, await _factors(db, scope))

    # A fill-up is also the most reliable odometer reading a fleet gets;
    # never let it move the odometer backwards.
    if entry.odometer_km and entry.odometer_km > (vehicle.odometer_km or 0):
        vehicle.odometer_km = entry.odometer_km
    if entry.fuel_type == FuelType.ELECTRIC and entry.battery_level_after is not None:
        vehicle.battery_level_percent = entry.battery_level_after

    db.add(entry)
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="fuel_log",
        entity_id=entry.id,
        summary=(
            f"{entry.quantity}{entry.unit} logged for {vehicle.name} "
            f"({entry.total_cost})"
        ),
        request=request,
    )
    return entry


async def summarise(
    db: AsyncSession, scope: TenantScope
) -> list[tuple[uuid.UUID, str, int, float, float, float, float | None]]:
    """Per-vehicle consumption rollup.

    Consumption is derived from the *span between the first and last logged
    odometer readings*, not from the vehicle's lifetime odometer: only the
    distance actually covered by these entries is attributable to them.
    """
    rows = await db.execute(
        sa.select(
            FuelLog.vehicle_id,
            Vehicle.name,
            sa.func.count(FuelLog.id),
            sa.func.coalesce(sa.func.sum(FuelLog.quantity), 0.0),
            sa.func.coalesce(sa.func.sum(FuelLog.total_cost), 0.0),
            sa.func.coalesce(sa.func.sum(FuelLog.co2_kg), 0.0),
            sa.func.min(FuelLog.odometer_km),
            sa.func.max(FuelLog.odometer_km),
        )
        .join(Vehicle, Vehicle.id == FuelLog.vehicle_id)
        .where(FuelLog.organization_id == scope.organization_id)
        .group_by(FuelLog.vehicle_id, Vehicle.name)
        .order_by(Vehicle.name)
    )

    out = []
    for vehicle_id, name, count, quantity, cost, co2, min_odo, max_odo in rows.all():
        consumption: float | None = None
        if min_odo is not None and max_odo is not None and max_odo > min_odo:
            distance = float(max_odo) - float(min_odo)
            consumption = round(float(quantity) / distance * 100.0, 2)
        out.append(
            (
                vehicle_id,
                name,
                int(count),
                round(float(quantity), 2),
                round(float(cost), 2),
                round(float(co2), 2),
                consumption,
            )
        )
    return out


async def carbon_totals(db: AsyncSession, scope: TenantScope) -> dict[str, float]:
    """Organization-level CO2 rollup for the sustainability dashboard."""
    row = await db.execute(
        sa.select(
            sa.func.coalesce(sa.func.sum(FuelLog.co2_kg), 0.0),
            sa.func.coalesce(sa.func.sum(FuelLog.quantity), 0.0),
            sa.func.coalesce(sa.func.sum(FuelLog.total_cost), 0.0),
        ).where(FuelLog.organization_id == scope.organization_id)
    )
    co2, quantity, cost = row.one()
    return {
        "total_co2_kg": round(float(co2), 2),
        "total_quantity": round(float(quantity), 2),
        "total_cost": round(float(cost), 2),
    }
