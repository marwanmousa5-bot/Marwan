from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import OrganizationStatus, SubscriptionStatus
from app.schemas.auth import UserOut
from app.schemas.common import ORMModel


class OrganizationCreate(BaseModel):
    """Platform Admin Console: provision a new customer (Section 4a)."""

    name: str = Field(min_length=2, max_length=200)
    industry: str | None = Field(default=None, max_length=120)
    timezone: str = Field(default="UTC", max_length=64)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=50)
    plan: str = Field(default="standard", max_length=50)

    admin_full_name: str = Field(min_length=2, max_length=200)
    admin_email: EmailStr


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    industry: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=50)
    logo_url: str | None = Field(default=None, max_length=500)
    plan: str | None = Field(default=None, max_length=50)


class OrganizationOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    industry: str | None = None
    timezone: str
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    logo_url: str | None = None
    status: OrganizationStatus
    plan: str
    subscription_status: SubscriptionStatus
    created_at: datetime


class OrganizationHealth(BaseModel):
    """Row in the Platform Admin Console organization list (Section 4a item 3)."""

    organization: OrganizationOut
    vehicle_count: int
    active_device_count: int
    user_count: int
    last_login_at: datetime | None = None


class OrganizationProvisionResponse(BaseModel):
    organization: OrganizationOut
    admin_user: UserOut
    #: Shown once for staff to copy and send manually (email/WhatsApp).
    activation_url: str


class OrganizationSettingsOut(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    distance_unit: str
    currency: str
    show_leaderboard_to_drivers: bool
    driver_points_baseline: int
    point_weights: dict
    maintenance_auto_book_enabled: bool
    alert_thresholds: dict
    co2_emission_factors: dict


class OrganizationSettingsUpdate(BaseModel):
    distance_unit: str | None = Field(default=None, pattern="^(km|mi)$")
    currency: str | None = Field(default=None, max_length=8)
    show_leaderboard_to_drivers: bool | None = None
    driver_points_baseline: int | None = Field(default=None, ge=0, le=10_000)
    #: Org-Admin-configurable penalty/reward weights (Section 4g, Section 9).
    point_weights: dict[str, int] | None = None
    maintenance_auto_book_enabled: bool | None = None
    alert_thresholds: dict[str, float] | None = None
    co2_emission_factors: dict[str, float] | None = None
