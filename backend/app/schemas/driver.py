from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import EmploymentStatus
from app.schemas.common import ORMModel


class DriverBase(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    employee_number: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=50)
    license_number: str | None = Field(default=None, max_length=64)
    license_class: str | None = Field(default=None, max_length=32)
    license_expiry: date | None = None
    employment_status: EmploymentStatus = EmploymentStatus.ACTIVE
    hired_on: date | None = None
    assigned_vehicle_id: uuid.UUID | None = None


class DriverCreate(DriverBase):
    #: When set, a pending driver login is created alongside the profile and
    #: an activation link is returned. Omit for a profile-only record.
    login_email: EmailStr | None = None


class DriverUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    employee_number: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=50)
    license_number: str | None = Field(default=None, max_length=64)
    license_class: str | None = Field(default=None, max_length=32)
    license_expiry: date | None = None
    employment_status: EmploymentStatus | None = None
    hired_on: date | None = None
    assigned_vehicle_id: uuid.UUID | None = None


class DriverOut(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID | None = None
    full_name: str
    employee_number: str | None = None
    phone: str | None = None
    license_number: str | None = None
    license_class: str | None = None
    license_expiry: date | None = None
    employment_status: EmploymentStatus
    hired_on: date | None = None
    assigned_vehicle_id: uuid.UUID | None = None
    safety_score: float
    fatigue_risk_level: str
    points_balance: int
    created_at: datetime
    updated_at: datetime


class DriverCreateResponse(BaseModel):
    driver: DriverOut
    #: Present only when ``login_email`` was supplied.
    activation_url: str | None = None
