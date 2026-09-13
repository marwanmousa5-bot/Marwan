"""Authentication and authorisation dependencies.

Tenant scope is *always* derived from the authenticated user - a client-supplied
organization id is never trusted (spec 31 / 44).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import decode_token
from app.core.enums import OrgStatus, Role
from app.db.base import get_session
from app.models import Organization, User


@dataclass
class Principal:
    """The authenticated caller plus the tenant scope it may act in."""
    user: User
    organization: Organization | None

    @property
    def role(self) -> str:
        return self.user.role

    @property
    def org_id(self) -> uuid.UUID | None:
        return self.organization.id if self.organization else None

    @property
    def is_super_admin(self) -> bool:
        return self.user.role == Role.SUPER_ADMIN

    def label(self) -> str:
        return self.user.full_name or self.user.email


def _unauthorised(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail,
                         headers={"WWW-Authenticate": "Bearer"})


async def _load_principal(token: str, session: AsyncSession) -> Principal:
    payload = decode_token(token, "access")
    if not payload:
        raise _unauthorised("Session expired or invalid. Please sign in again.")
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise _unauthorised("Malformed token.")

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorised("Account is inactive.")

    org = None
    if user.organization_id:
        org = await session.get(Organization, user.organization_id)
        if org is None:
            raise _unauthorised("Organization not found.")
        if org.status == OrgStatus.SUSPENDED and user.role != Role.SUPER_ADMIN:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "This organization is suspended. Contact your platform administrator.",
            )
    return Principal(user=user, organization=org)


async def get_principal(
    request: Request,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Principal:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        token = request.cookies.get("fb_access")
    if not token:
        raise _unauthorised()
    return await _load_principal(token, session)


async def get_principal_optional(
    request: Request,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Principal | None:
    try:
        return await get_principal(request, authorization, session)
    except HTTPException:
        return None


def require_roles(*roles: str):
    """RBAC enforced at the API layer, never only in the UI (spec 32)."""
    allowed = {str(r) for r in roles}

    async def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Your role ({principal.role.replace('_', ' ')}) cannot perform this action.",
            )
        return principal

    return _dep


async def require_tenant(principal: Principal = Depends(get_principal)) -> Principal:
    """Any caller that must act inside exactly one organization."""
    if principal.organization is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This endpoint operates inside an organization; the platform "
            "administrator account is not scoped to one.",
        )
    if principal.user.must_change_password:
        raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED,
                            "Password change required before continuing.")
    return principal


# --- convenience role gates -------------------------------------------------
require_super_admin = require_roles(Role.SUPER_ADMIN)
require_org_admin = require_roles(Role.ORG_ADMIN)


async def require_operator(principal: Principal = Depends(require_tenant)) -> Principal:
    """org_admin or dispatcher - the two operational console roles."""
    if principal.role not in (Role.ORG_ADMIN, Role.DISPATCHER):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only fleet administrators and dispatchers can do this.")
    return principal


async def require_admin_of_org(principal: Principal = Depends(require_tenant)) -> Principal:
    if principal.role != Role.ORG_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only a fleet administrator can do this.")
    return principal


async def require_driver(principal: Principal = Depends(require_tenant)) -> Principal:
    if principal.role != Role.DRIVER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Driver account required.")
    return principal


async def require_any_member(principal: Principal = Depends(require_tenant)) -> Principal:
    return principal
