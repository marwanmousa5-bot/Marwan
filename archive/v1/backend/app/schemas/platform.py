"""Platform Admin Console schemas (Section 4a)."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.auth import TokenPair, UserOut
from app.schemas.organization import OrganizationOut


class PlatformOverview(BaseModel):
    total_organizations: int
    active_organizations: int
    total_vehicles: int
    total_drivers: int
    total_users: int
    total_devices: int
    active_devices: int
    devices_in_stock: int


class ResendActivationResponse(BaseModel):
    user: UserOut
    activation_url: str


class ImpersonationResponse(BaseModel):
    organization: OrganizationOut
    impersonated_user: UserOut
    tokens: TokenPair
