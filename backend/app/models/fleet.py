"""Vehicles, drivers, devices, places and geofences."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON,
                        String, Text, UniqueConstraint)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (DeviceStatus, DriverStatus, FuelType, GeofenceTrigger,
                            GeofenceType, Ownership, PlaceCategory, VehicleLifecycle,
                            VehicleType)
from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDMixin


class Device(Base, UUIDMixin, TimestampMixin):
    """GPS hardware. Owned by the platform; only super_admin may (re)assign it."""
    __tablename__ = "devices"

    serial: Mapped[str] = mapped_column(String(60), nullable=False, unique=True, index=True)
    imei: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    model: Mapped[str] = mapped_column(String(60), nullable=False)
    firmware: Mapped[str] = mapped_column(String(30), default="1.0.0")
    status: Mapped[str] = mapped_column(String(20), default=DeviceStatus.IN_STOCK, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"), index=True
    )
    last_signal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    vehicle: Mapped["Vehicle | None"] = relationship(
        back_populates="device", foreign_keys=[vehicle_id]
    )


class Vehicle(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "vehicles"
    __table_args__ = (UniqueConstraint("organization_id", "plate", name="uq_vehicles_org_plate"),)

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    plate: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    vin: Mapped[str | None] = mapped_column(String(40))
    type: Mapped[str] = mapped_column(String(30), default=VehicleType.VAN, nullable=False)
    make: Mapped[str] = mapped_column(String(50), default="")
    model: Mapped[str] = mapped_column(String(50), default="")
    year: Mapped[int | None] = mapped_column(Integer)
    colour: Mapped[str] = mapped_column(String(30), default="White")
    fuel_type: Mapped[str] = mapped_column(String(20), default=FuelType.DIESEL, nullable=False)
    lifecycle: Mapped[str] = mapped_column(
        String(20), default=VehicleLifecycle.ACTIVE, nullable=False, index=True
    )

    odometer_km: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tank_capacity_l: Mapped[float | None] = mapped_column(Float)
    avg_consumption_l_100km: Mapped[float | None] = mapped_column(Float)

    # EV
    battery_capacity_kwh: Mapped[float | None] = mapped_column(Float)
    state_of_charge_pct: Mapped[float | None] = mapped_column(Float)
    range_km: Mapped[float | None] = mapped_column(Float)
    charging_status: Mapped[str | None] = mapped_column(String(20))

    # Lifecycle / finance
    ownership: Mapped[str] = mapped_column(String(20), default=Ownership.OWNED, nullable=False)
    purchase_date: Mapped[date | None] = mapped_column(Date)
    purchase_value: Mapped[float | None] = mapped_column(Float)
    residual_value: Mapped[float | None] = mapped_column(Float)
    depreciation_years: Mapped[int] = mapped_column(Integer, default=7)
    annual_insurance_cost: Mapped[float | None] = mapped_column(Float)
    annual_registration_cost: Mapped[float | None] = mapped_column(Float)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("drivers.id", ondelete="SET NULL"), index=True
    )
    home_place_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("places.id", ondelete="SET NULL")
    )

    # Denormalised live telemetry - single source of truth for "where is it now".
    last_lat: Mapped[float | None] = mapped_column(Float)
    last_lon: Mapped[float | None] = mapped_column(Float)
    last_heading: Mapped[float | None] = mapped_column(Float)
    last_speed_kph: Mapped[float | None] = mapped_column(Float)
    last_position_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_street: Mapped[str | None] = mapped_column(String(120))
    gps_satellites: Mapped[int | None] = mapped_column(Integer)
    ignition_on: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    idle_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    notes: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    driver: Mapped["Driver | None"] = relationship(
        back_populates="vehicle", foreign_keys=[driver_id]
    )
    device: Mapped["Device | None"] = relationship(
        back_populates="vehicle", foreign_keys="Device.vehicle_id", uselist=False
    )

    @property
    def is_ev(self) -> bool:
        return self.fuel_type == FuelType.ELECTRIC


class Driver(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "drivers"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    employee_no: Mapped[str] = mapped_column(String(30), nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(
        String(20), default=DriverStatus.OFF_DUTY, nullable=False, index=True
    )
    license_number: Mapped[str | None] = mapped_column(String(40))
    license_class: Mapped[str | None] = mapped_column(String(20))
    license_expiry: Mapped[date | None] = mapped_column(Date)
    hired_on: Mapped[date | None] = mapped_column(Date)

    safety_score: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    previous_safety_score: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    points_balance: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    # Hours in the current duty window - drives the fatigue indicator.
    duty_hours_today: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    duty_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shift_start: Mapped[str] = mapped_column(String(5), default="07:00")
    shift_end: Mapped[str] = mapped_column(String(5), default="16:00")
    avatar_color: Mapped[str] = mapped_column(String(16), default="#1E90FF")
    notes: Mapped[str | None] = mapped_column(Text)

    vehicle: Mapped["Vehicle | None"] = relationship(
        back_populates="driver", foreign_keys="Vehicle.driver_id", uselist=False
    )

    @property
    def fatigue_risk(self) -> str:
        h = self.duty_hours_today or 0
        if h >= 9:
            return "high"
        if h >= 7:
            return "elevated"
        if h >= 5:
            return "moderate"
        return "low"


class Place(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    """Depots, customer sites, fuel stations, workshops - real OSM coordinates."""
    __tablename__ = "places"

    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    category: Mapped[str] = mapped_column(
        String(30), default=PlaceCategory.CUSTOMER_SITE, nullable=False, index=True
    )
    address: Mapped[str | None] = mapped_column(String(255))
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(120))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)
    osm_ref: Mapped[str | None] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Geofence(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "geofences"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    type: Mapped[str] = mapped_column(String(20), default=GeofenceType.POLYGON, nullable=False)
    trigger: Mapped[str] = mapped_column(String(10), default=GeofenceTrigger.BOTH, nullable=False)
    colour: Mapped[str] = mapped_column(String(16), default="#1E90FF")
    # polygon: [[lon,lat], ...]; circle: centre + radius_m
    polygon: Mapped[list | None] = mapped_column(JSON)
    centre_lat: Mapped[float | None] = mapped_column(Float)
    centre_lon: Mapped[float | None] = mapped_column(Float)
    radius_m: Mapped[float | None] = mapped_column(Float)
    # empty scope means "all vehicles"
    vehicle_ids: Mapped[list | None] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_restricted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class GeofenceState(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    """Tracks whether a vehicle is currently inside a fence, so we emit edges only."""
    __tablename__ = "geofence_states"
    __table_args__ = (
        UniqueConstraint("geofence_id", "vehicle_id", name="uq_geofence_state"),
    )

    geofence_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("geofences.id", ondelete="CASCADE"), index=True
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    inside: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Workshop(Base, UUIDMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "workshops"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    address: Mapped[str | None] = mapped_column(String(255))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    contact_name: Mapped[str | None] = mapped_column(String(120))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    daily_capacity: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    opening_time: Mapped[str] = mapped_column(String(5), default="08:00")
    closing_time: Mapped[str] = mapped_column(String(5), default="18:00")
    services: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
