"""Device inventory schemas (Platform Admin Console only)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import DeviceStatus
from app.schemas.common import ORMModel


class DeviceCreate(BaseModel):
    serial_number: str = Field(min_length=3, max_length=64)
    imei: str | None = Field(default=None, max_length=32)
    model: str | None = Field(default=None, max_length=120)
    firmware_version: str | None = Field(default=None, max_length=64)
    notes: str | None = None


class DeviceAssign(BaseModel):
    organization_id: uuid.UUID
    vehicle_id: uuid.UUID
    #: Activating immediately is the normal case - the fitter has just
    #: installed it and the customer expects the vehicle to go live.
    activate: bool = True


class DeviceStatusUpdate(BaseModel):
    status: DeviceStatus
    notes: str | None = None


class DeviceOut(ORMModel):
    id: uuid.UUID
    serial_number: str
    imei: str | None = None
    model: str | None = None
    firmware_version: str | None = None
    notes: str | None = None
    status: DeviceStatus
    organization_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID | None = None
    assigned_at: datetime | None = None
    activated_at: datetime | None = None
    last_signal_at: datetime | None = None
    created_at: datetime


class DeviceDetailOut(DeviceOut):
    """Adds the human-readable context the inventory table needs."""

    organization_name: str | None = None
    vehicle_name: str | None = None
    vehicle_plate: str | None = None
