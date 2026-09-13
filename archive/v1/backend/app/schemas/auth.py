"""Auth request/response schemas.

Note the absence of any registration schema - by design (Section 9).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import UserRole, UserStatus
from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ActivateRequest(BaseModel):
    token: str
    password: str = Field(min_length=12, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=256)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class UserOut(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    email: str
    full_name: str
    phone: str | None = None
    role: UserRole
    status: UserStatus
    must_change_password: bool


class CurrentUserOut(BaseModel):
    """The authenticated user plus their Organization context."""

    user: UserOut
    organization_name: str | None = None
    organization_timezone: str | None = None
    is_impersonating: bool = False


class SessionOut(CurrentUserOut):
    """What the client needs immediately after login."""

    tokens: TokenPair


class InviteUserRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: UserRole
    phone: str | None = Field(default=None, max_length=50)


class InviteUserResponse(BaseModel):
    user: UserOut
    #: Displayed in the UI for manual delivery - no email provider in MVP.
    activation_url: str
