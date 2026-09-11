"""FastAPI dependencies: authentication, RBAC and tenant scoping.

RBAC is enforced HERE, at the API dependency level - the UI hiding a button
is never the control (Section 3).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import decode_token
from app.core.tenancy import TenantScope
from app.db.session import get_db
from app.models.enums import OrganizationStatus, UserRole, UserStatus
from app.models.organization import Organization
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(slots=True)
class Principal:
    """The authenticated actor for the current request."""

    user: User
    role: UserRole
    organization_id: uuid.UUID | None
    #: Set when a super_admin is acting as an Organization user (Section 4a).
    impersonator_id: uuid.UUID | None = None

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    @property
    def email(self) -> str:
        return self.user.email

    @property
    def is_super_admin(self) -> bool:
        return self.role == UserRole.SUPER_ADMIN

    @property
    def is_impersonating(self) -> bool:
        return self.impersonator_id is not None


async def get_current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Missing bearer token")

    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token has expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid access token") from exc

    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except (TypeError, ValueError) as exc:
        raise AuthenticationError("Invalid access token subject") from exc

    user = await db.get(User, user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise AuthenticationError("User is not active")

    # The token's org claim must still match the user's record. This closes
    # the door on a stale token surviving a user being moved or deleted.
    token_org = payload.get("org")
    token_org_id = uuid.UUID(token_org) if token_org else None
    if user.organization_id != token_org_id:
        raise AuthenticationError("Token organization no longer matches user")

    if token_org_id is not None:
        organization = await db.get(Organization, token_org_id)
        if organization is None or organization.status != OrganizationStatus.ACTIVE:
            raise AuthenticationError("Organization is suspended or missing")

    impersonator = payload.get("imp")
    principal = Principal(
        user=user,
        role=UserRole(user.role),
        organization_id=token_org_id,
        impersonator_id=uuid.UUID(impersonator) if impersonator else None,
    )
    # Cached on the request so the audit middleware can attribute actions
    # without re-decoding the token.
    request.state.principal = principal
    return principal


def require_roles(*roles: UserRole) -> Callable[..., object]:
    """Dependency factory enforcing that the caller holds one of ``roles``."""

    allowed = frozenset(roles)

    async def _dependency(
        principal: Principal = Depends(get_current_principal),
    ) -> Principal:
        if principal.role not in allowed:
            raise PermissionDeniedError(
                "Your role does not have access to this resource"
            )
        return principal

    return _dependency


#: Platform staff only - the Platform Admin Console (Section 4a).
require_super_admin = require_roles(UserRole.SUPER_ADMIN)
#: Customer-facing web dashboard (Section 4b).
require_dashboard_user = require_roles(UserRole.ORG_ADMIN, UserRole.DISPATCHER)
#: Organization administration (user invites, settings, point weights).
require_org_admin = require_roles(UserRole.ORG_ADMIN)
#: Driver mobile app.
require_driver = require_roles(UserRole.DRIVER)
#: Any authenticated user belonging to a customer Organization.
require_org_member = require_roles(
    UserRole.ORG_ADMIN, UserRole.DISPATCHER, UserRole.DRIVER
)


async def get_tenant_scope(
    principal: Principal = Depends(get_current_principal),
) -> TenantScope:
    """Tenant scope derived solely from the authenticated principal.

    A ``super_admin`` has no Organization of their own; to touch tenant data
    they must impersonate (Section 4a item 3), which mints a token carrying
    that Organization's id.
    """
    if principal.organization_id is None:
        raise PermissionDeniedError(
            "This endpoint requires an Organization context. Platform staff "
            "must use the Platform Admin Console or impersonate an "
            "Organization."
        )
    return TenantScope(principal.organization_id)


def roles_label(roles: Iterable[UserRole]) -> str:  # pragma: no cover - docs helper
    return ", ".join(sorted(r.value for r in roles))
