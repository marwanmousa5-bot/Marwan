"""Maintenance, fuel/energy and compliance schemas (Section 4 items 6, 7, 9)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import (
    DocumentType,
    FuelType,
    MaintenanceIntervalType,
    WorkOrderStatus,
)
from app.schemas.common import ORMModel

# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------

class MaintenanceScheduleCreate(BaseModel):
    vehicle_id: uuid.UUID
    name: str = Field(min_length=1, max_length=160)
    component: str | None = Field(default=None, max_length=120)
    interval_type: MaintenanceIntervalType = MaintenanceIntervalType.MILEAGE
    interval_km: float | None = Field(default=None, gt=0)
    interval_days: int | None = Field(default=None, gt=0)
    last_service_odometer_km: float | None = Field(default=None, ge=0)
    last_service_date: date | None = None
    is_active: bool = True


class MaintenanceScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    component: str | None = Field(default=None, max_length=120)
    interval_type: MaintenanceIntervalType | None = None
    interval_km: float | None = Field(default=None, gt=0)
    interval_days: int | None = Field(default=None, gt=0)
    last_service_odometer_km: float | None = Field(default=None, ge=0)
    last_service_date: date | None = None
    is_active: bool | None = None


class MaintenanceScheduleOut(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    vehicle_id: uuid.UUID
    name: str
    component: str | None = None
    interval_type: MaintenanceIntervalType
    interval_km: float | None = None
    interval_days: int | None = None
    last_service_odometer_km: float | None = None
    last_service_date: date | None = None
    next_due_odometer_km: float | None = None
    next_due_date: date | None = None
    is_active: bool
    created_at: datetime


class WorkOrderCreate(BaseModel):
    vehicle_id: uuid.UUID
    schedule_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    status: WorkOrderStatus = WorkOrderStatus.OPEN
    scheduled_for: datetime | None = None
    odometer_km: float | None = Field(default=None, ge=0)
    vendor: str | None = Field(default=None, max_length=200)


class WorkOrderUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: WorkOrderStatus | None = None
    scheduled_for: datetime | None = None
    odometer_km: float | None = Field(default=None, ge=0)
    labour_cost: float | None = Field(default=None, ge=0)
    parts_cost: float | None = Field(default=None, ge=0)
    vendor: str | None = Field(default=None, max_length=200)


class WorkOrderOut(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    vehicle_id: uuid.UUID
    schedule_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    status: WorkOrderStatus
    scheduled_for: datetime | None = None
    completed_at: datetime | None = None
    odometer_km: float | None = None
    labour_cost: float | None = None
    parts_cost: float | None = None
    total_cost: float | None = None
    vendor: str | None = None
    created_by_copilot: bool
    copilot_rationale: str | None = None
    created_at: datetime


class ServiceRecordOut(ORMModel):
    id: uuid.UUID
    vehicle_id: uuid.UUID
    work_order_id: uuid.UUID | None = None
    performed_on: date
    odometer_km: float | None = None
    summary: str
    total_cost: float | None = None


# ---------------------------------------------------------------------------
# Fuel & energy
# ---------------------------------------------------------------------------

class FuelLogCreate(BaseModel):
    vehicle_id: uuid.UUID
    driver_id: uuid.UUID | None = None
    fuel_type: FuelType = FuelType.DIESEL
    quantity: float = Field(gt=0)
    unit: str = Field(default="L", max_length=8)
    unit_price: float | None = Field(default=None, ge=0)
    total_cost: float = Field(ge=0)
    odometer_km: float | None = Field(default=None, ge=0)
    filled_at: datetime
    location_name: str | None = Field(default=None, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    battery_level_after: float | None = Field(default=None, ge=0, le=100)
    notes: str | None = None


class FuelLogOut(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    vehicle_id: uuid.UUID
    driver_id: uuid.UUID | None = None
    fuel_type: FuelType
    quantity: float
    unit: str
    unit_price: float | None = None
    total_cost: float
    odometer_km: float | None = None
    filled_at: datetime
    location_name: str | None = None
    battery_level_after: float | None = None
    #: Derived at write time from the organization's emission factors
    #: (Section 4 item 17), so the carbon dashboard aggregates cheaply.
    co2_kg: float | None = None
    notes: str | None = None


class FuelSummary(BaseModel):
    """Consumption rollup per vehicle, for the fuel page and TCO later."""

    vehicle_id: uuid.UUID
    vehicle_name: str
    entries: int
    total_quantity: float
    total_cost: float
    total_co2_kg: float
    litres_per_100km: float | None = None


# ---------------------------------------------------------------------------
# Compliance documents
# ---------------------------------------------------------------------------

class ComplianceDocumentCreate(BaseModel):
    document_type: DocumentType = DocumentType.OTHER
    title: str = Field(min_length=1, max_length=200)
    reference_number: str | None = Field(default=None, max_length=120)
    issuer: str | None = Field(default=None, max_length=200)
    vehicle_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    issued_on: date | None = None
    expires_on: date | None = None
    cost: float | None = Field(default=None, ge=0)
    file_url: str | None = Field(default=None, max_length=500)
    file_name: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class ComplianceDocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    reference_number: str | None = Field(default=None, max_length=120)
    issuer: str | None = Field(default=None, max_length=200)
    issued_on: date | None = None
    expires_on: date | None = None
    cost: float | None = Field(default=None, ge=0)
    file_url: str | None = Field(default=None, max_length=500)
    file_name: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class ComplianceDocumentOut(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    document_type: DocumentType
    title: str
    reference_number: str | None = None
    issuer: str | None = None
    vehicle_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    issued_on: date | None = None
    expires_on: date | None = None
    cost: float | None = None
    file_url: str | None = None
    file_name: str | None = None
    notes: str | None = None
    created_at: datetime
    #: Derived: negative once expired.
    days_until_expiry: int | None = None
