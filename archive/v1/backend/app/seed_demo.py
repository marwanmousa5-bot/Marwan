"""Populate a demo tenant so a fresh stack is worth looking at.

A first `docker compose up` leaves an empty platform: before anything moves on
the map you must provision an Organization, add vehicles and drivers, add GPS
devices to inventory and fit them. That is the correct production flow and it
stays the correct production flow - this module just performs it for you, with
realistic data, when you are evaluating or testing.

Never runs by itself. It is a command:

    docker compose run --rm api python -m app.seed_demo

Idempotent: if the demo Organization already exists it stops and says so,
rather than doubling the fleet. Pass --force to tear it down and rebuild.

The demo admin password comes from DEMO_ADMIN_PASSWORD, or is generated and
printed once - the same rule the real super-admin seed follows (Section 7: no
password is ever hardcoded).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import secrets
import sys
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa

from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.models.compliance import ComplianceDocument
from app.models.device import Device
from app.models.driver import Driver
from app.models.enums import (
    DocumentType,
    FuelType,
    MaintenanceIntervalType,
    PoiCategory,
    VehicleType,
    WorkOrderStatus,
)
from app.models.fuel import FuelLog
from app.models.maintenance import MaintenanceSchedule, WorkOrder
from app.models.organization import Organization
from app.models.tracking import Geofence, PointOfInterest
from app.models.vehicle import Vehicle
from app.services.fuel import co2_for

logger = logging.getLogger("fleetbeat.seed_demo")

BANNER = "=" * 68

ORG_NAME = "Northwind Transport"
#: Serial prefix for the demo's GPS hardware, so a rebuild can reclaim it.
DEVICE_PREFIX = "FB-"
ADMIN_EMAIL = "nora@northwind.example.com"

#: Amsterdam, because the default OSRM extract in infra/osrm is Netherlands.
DEPOT = (52.3676, 4.9041)

FLEET = [
    ("Van 01", VehicleType.VAN, FuelType.DIESEL, 42_800),
    ("Van 02", VehicleType.VAN, FuelType.DIESEL, 51_200),
    ("Truck 03", VehicleType.TRUCK, FuelType.DIESEL, 118_400),
    ("Van 04", VehicleType.VAN, FuelType.PETROL, 33_900),
    ("Truck 05", VehicleType.TRUCK, FuelType.DIESEL, 96_100),
    ("Van 06", VehicleType.VAN, FuelType.DIESEL, 27_500),
    #: Deliberately left without a device, so "Not Tracked" is visible.
    ("EV 07", VehicleType.EV, FuelType.ELECTRIC, 12_300),
]

DRIVERS = ["Dee Driver", "Sam Roads", "Priya Patel", "Tom Vance"]

#: How much recent history to generate. Analytics and the safety scores need a
#: few weeks of it, or every chart reads "not enough data yet".
HISTORY_DAYS = 45
SIMULATED_MINUTES = 45


def _password() -> tuple[str, bool]:
    chosen = (settings.demo_admin_password or "").strip()
    if chosen:
        return chosen, False
    return secrets.token_urlsafe(18), True


async def _purge_organization(db, org: Organization) -> None:
    """Delete a demo tenant and everything under it.

    Explicit rather than relying on ``ON DELETE CASCADE``: SQLite does not
    enforce foreign keys unless asked, so trusting the cascade would quietly
    leave the old fleet in place on some backends and produce a demo with
    fourteen vehicles instead of seven. Walking the metadata in reverse
    dependency order deletes the same rows on every backend, and picks up any
    tenant-scoped table added later without this needing an edit.
    """
    from app.models import Base

    for table in reversed(Base.metadata.sorted_tables):
        column = table.c.get("organization_id")
        if column is not None:
            await db.execute(sa.delete(table).where(column == org.id))

    # Devices are platform inventory, not tenant data - they survive a
    # customer on purpose, and their serial numbers stay taken. A rebuild has
    # to reclaim the demo's own hardware explicitly.
    await db.execute(
        sa.delete(Device).where(Device.serial_number.startswith(DEVICE_PREFIX))
    )
    await db.delete(org)


async def _existing_org(db) -> Organization | None:
    return (
        await db.execute(
            sa.select(Organization).where(Organization.name == ORG_NAME).limit(1)
        )
    ).scalar_one_or_none()


async def seed_demo(force: bool = False) -> int:
    from app.seed_admin import seed_super_admin
    from app.services.auth import consume_activation_token
    from app.services.devices import add_device, assign_device
    from app.services.provisioning import create_organization

    await seed_super_admin()

    async with SessionLocal() as db:
        existing = await _existing_org(db)
        if existing is not None:
            if not force:
                logger.info(
                    "Demo organization '%s' already exists - nothing to do. "
                    "Re-run with --force to rebuild it.",
                    ORG_NAME,
                )
                return 0
            logger.info("Removing the existing demo organization...")
            await _purge_organization(db, existing)
            await db.commit()

        password, generated = _password()

        org, _admin, activation_link = await create_organization(
            db,
            name=ORG_NAME,
            admin_email=ADMIN_EMAIL,
            admin_full_name="Nora Admin",
            industry="Logistics",
            timezone_name="Europe/Amsterdam",
            contact_name="Nora Admin",
            contact_email=ADMIN_EMAIL,
        )
        await db.commit()

        # Consume the activation link exactly as a real admin would, so the
        # account ends up in the same state a real one does.
        await consume_activation_token(
            db, raw_token=activation_link.split("token=")[1], new_password=password
        )
        await db.commit()

        today = date.today()
        now = datetime.now(UTC)

        vehicles: list[Vehicle] = []
        for index, (name, vehicle_type, fuel_type, odometer) in enumerate(FLEET):
            vehicle = Vehicle(
                organization_id=org.id,
                name=name,
                license_plate=f"NW-{index + 1:03d}",
                vehicle_type=vehicle_type,
                fuel_type=fuel_type,
                odometer_km=odometer,
                make="Mercedes" if vehicle_type == VehicleType.TRUCK else "Ford",
                model="Actros" if vehicle_type == VehicleType.TRUCK else "Transit",
                year=2021 + (index % 4),
            )
            db.add(vehicle)
            vehicles.append(vehicle)
        await db.flush()

        for index, full_name in enumerate(DRIVERS):
            db.add(
                Driver(
                    organization_id=org.id,
                    full_name=full_name,
                    assigned_vehicle_id=vehicles[index].id,
                    license_number=f"DL-{1000 + index}",
                )
            )

        db.add_all(
            [
                Geofence(
                    organization_id=org.id,
                    name="Amsterdam depot",
                    shape="circle",
                    geometry={"center": [DEPOT[1], DEPOT[0]], "radius_m": 3500},
                    color="#1E90FF",
                    trigger="both",
                ),
                Geofence(
                    organization_id=org.id,
                    name="City centre - restricted",
                    shape="polygon",
                    geometry={
                        "coordinates": [
                            [4.86, 52.35],
                            [4.95, 52.35],
                            [4.95, 52.40],
                            [4.86, 52.40],
                        ]
                    },
                    color="#FF6B35",
                    trigger="on_enter",
                ),
            ]
        )

        for name, category, lat, lng in (
            ("Main depot", PoiCategory.DEPOT, 52.3676, 4.9041),
            ("Schiphol hub", PoiCategory.CUSTOMER_SITE, 52.3105, 4.7683),
            ("Shell A10", PoiCategory.FUEL_STATION, 52.3420, 4.8600),
        ):
            db.add(
                PointOfInterest(
                    organization_id=org.id,
                    name=name,
                    category=category,
                    latitude=lat,
                    longitude=lng,
                )
            )

        # A document about to expire, so the compliance screen has something
        # to say on day one.
        db.add(
            ComplianceDocument(
                organization_id=org.id,
                document_type=DocumentType.INSURANCE,
                title="Fleet insurance 2026",
                vehicle_id=vehicles[0].id,
                expires_on=today + timedelta(days=12),
            )
        )

        # --- costs -----------------------------------------------------------
        # Without these the cost report correctly says "no costs recorded",
        # which is accurate and useless for a demo.
        for index, vehicle in enumerate(vehicles):
            if vehicle.fuel_type == FuelType.ELECTRIC:
                continue
            for week in range(6):
                litres = 48.0 + (index * 3) + (week * 1.5)
                price = 1.82 + (week * 0.01)
                quantity = round(litres, 1)
                db.add(
                    FuelLog(
                        organization_id=org.id,
                        vehicle_id=vehicle.id,
                        fuel_type=vehicle.fuel_type,
                        quantity=quantity,
                        unit="L",
                        unit_price=round(price, 4),
                        total_cost=round(litres * price, 2),
                        odometer_km=vehicle.odometer_km - (week * 620),
                        filled_at=now - timedelta(days=week * 7 + index),
                        location_name="Shell A10",
                        # Derived the same way the fuel service derives it, or
                        # the sustainability dashboard reads a flat zero.
                        co2_kg=co2_for(quantity, vehicle.fuel_type, None),
                    )
                )

        for index, vehicle in enumerate(vehicles[:4]):
            schedule = MaintenanceSchedule(
                organization_id=org.id,
                vehicle_id=vehicle.id,
                name="Oil and filter change",
                component="engine",
                interval_type=MaintenanceIntervalType.MILEAGE,
                interval_km=15_000,
                last_service_odometer_km=vehicle.odometer_km - 13_200,
                next_due_odometer_km=vehicle.odometer_km + 1_800,
            )
            db.add(schedule)
            await db.flush()
            db.add(
                WorkOrder(
                    organization_id=org.id,
                    vehicle_id=vehicle.id,
                    schedule_id=schedule.id,
                    title="Oil and filter change",
                    status=WorkOrderStatus.COMPLETED,
                    completed_at=now - timedelta(days=30 + index * 5),
                    odometer_km=vehicle.odometer_km - 13_200,
                    labour_cost=120.00,
                    parts_cost=85.50,
                    total_cost=205.50,
                    vendor="Amsterdam Fleet Services",
                )
            )

        # --- devices ---------------------------------------------------------
        # Six of seven get one. EV 07 stays Not Tracked on purpose, because
        # that state is part of the product and should be visible.
        for index, vehicle in enumerate(vehicles[:6]):
            device = await add_device(
                db, serial_number=f"{DEVICE_PREFIX}{index + 1:04d}", model="FB-Tracker 2"
            )
            await assign_device(
                db, device_id=device.id, organization_id=org.id, vehicle_id=vehicle.id
            )

        await db.commit()

    # --- movement ------------------------------------------------------------
    # Run the simulator forward over recent history so trips, positions and
    # driver events exist before anyone opens the dashboard.
    from app.simulation.runner import TrackingRunner
    from app.simulation.simulator import SimulatedLocationProvider

    runner = TrackingRunner(
        SimulatedLocationProvider(
            tick_seconds=5.0,
            event_probability=settings.simulation_event_probability,
            seed=7,
        )
    )
    start = datetime.now(UTC) - timedelta(minutes=SIMULATED_MINUTES)
    # The fleet must stagger its departures against the clock the replay is
    # driven on, not the wall clock, or every vehicle stays parked until real
    # time catches up - which for a backfill is never.
    await runner.refresh_fleet(now=start)
    for step in range(SIMULATED_MINUTES * 12):
        await runner.tick_once(start + timedelta(seconds=5 * step))

    logger.info(BANNER)
    logger.info("FleetBeat demo data ready")
    logger.info("")
    logger.info("  Organization: %s", ORG_NAME)
    logger.info("  Sign in at:   %s", settings.web_app_base_url)
    logger.info("  Email:        %s", ADMIN_EMAIL)
    if generated:
        logger.info("  Password:     %s", password)
        logger.info("")
        logger.info("  Shown once. Set DEMO_ADMIN_PASSWORD to choose your own.")
    else:
        logger.info("  Password:     (taken from DEMO_ADMIN_PASSWORD)")
    logger.info("")
    logger.info("  %d vehicles (6 tracked, EV 07 deliberately Not Tracked)", len(FLEET))
    logger.info(
        "  %d drivers, 2 geofences, 3 POIs, 6 weeks of fuel and service", len(DRIVERS)
    )
    logger.info(
        "  %d minutes of recorded movement, trips and driver events",
        SIMULATED_MINUTES,
    )
    logger.info(BANNER)

    await engine.dispose()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the FleetBeat demo tenant.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete and rebuild the demo organization if it already exists.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(asyncio.run(seed_demo(force=args.force)))


if __name__ == "__main__":
    main()
