from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import (
    DeviceStatus,
    FuelType,
    VehicleLiveStatus,
    VehicleOwnership,
    VehicleStatus,
    VehicleType,
)
from app.schemas.common import ORMModel


class VehicleDeviceOut(BaseModel):
    """Read-only device view for customers (Section 4a item 2)."""

    id: uuid.UUID
    serial_number: str
    model: str | None = None
    status: DeviceStatus
    last_signal_at: datetime | None = None


class VehicleBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    make: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    year: int | None = Field(default=None, ge=1900, le=2100)
    vin: str | None = Field(default=None, max_length=32)
    license_plate: str = Field(min_length=1, max_length=32)
    vehicle_type: VehicleType = VehicleType.CAR
    fuel_type: FuelType = FuelType.PETROL
    ownership: VehicleOwnership = VehicleOwnership.OWNED
    status: VehicleStatus = VehicleStatus.ACTIVE
    odometer_km: float = Field(default=0.0, ge=0)

    battery_capacity_kwh: float | None = Field(default=None, ge=0)
    ev_range_km: float | None = Field(default=None, ge=0)

    purchase_date: date | None = None
    purchase_value: float | None = Field(default=None, ge=0)
    residual_value: float | None = Field(default=None, ge=0)
    useful_life_years: int | None = Field(default=None, ge=1, le=50)


class VehicleCreate(VehicleBase):
    primary_driver_id: uuid.UUID | None = None


class VehicleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    make: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    year: int | None = Field(default=None, ge=1900, le=2100)
    vin: str | None = Field(default=None, max_length=32)
    license_plate: str | None = Field(default=None, min_length=1, max_length=32)
    vehicle_type: VehicleType | None = None
    fuel_type: FuelType | None = None
    ownership: VehicleOwnership | None = None
    status: VehicleStatus | None = None
    odometer_km: float | None = Field(default=None, ge=0)
    battery_capacity_kwh: float | None = Field(default=None, ge=0)
    battery_level_percent: float | None = Field(default=None, ge=0, le=100)
    ev_range_km: float | None = Field(default=None, ge=0)
    purchase_date: date | None = None
    purchase_value: float | None = Field(default=None, ge=0)
    residual_value: float | None = Field(default=None, ge=0)
    useful_life_years: int | None = Field(default=None, ge=1, le=50)
    primary_driver_id: uuid.UUID | None = None


class VehicleOut(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    make: str | None = None
    model: str | None = None
    year: int | None = None
    vin: str | None = None
    license_plate: str
    vehicle_type: VehicleType
    fuel_type: FuelType
    ownership: VehicleOwnership
    status: VehicleStatus
    odometer_km: float

    battery_capacity_kwh: float | None = None
    battery_level_percent: float | None = None
    ev_range_km: float | None = None

    purchase_date: date | None = None
    purchase_value: float | None = None
    residual_value: float | None = None
    useful_life_years: int | None = None
    replacement_recommended: bool = False
    ev_transition_candidate: bool = False

    primary_driver_id: uuid.UUID | None = None

    last_latitude: float | None = None
    last_longitude: float | None = None
    last_heading: float | None = None
    last_speed_kph: float | None = None
    last_position_at: datetime | None = None
    stopped_since: datetime | None = None

    #: False when no active GPS device is linked - surfaced to the customer
    #: as "Not Tracked" (Section 4a item 2 / Section 4b).
    is_tracked: bool = False
    device: VehicleDeviceOut | None = None
    live_status: VehicleLiveStatus = VehicleLiveStatus.NOT_TRACKED

    created_at: datetime
    updated_at: datetime
