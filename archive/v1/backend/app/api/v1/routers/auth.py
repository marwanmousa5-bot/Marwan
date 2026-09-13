"""Authentication endpoints.

There is intentionally NO registration endpoint here (Section 9). Accounts
are created by platform staff (`/platform-admin/organizations`) or by an Org
Admin (`/organization/users`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import Principal, get_current_principal
from app.db.session import get_db
from app.models.enums import AuditAction
from app.models.organization import Organization
from app.schemas.auth import (
    ActivateRequest,
    ChangePasswordRequest,
    CurrentUserOut,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    SessionOut,
    TokenPair,
    UserOut,
)
from app.schemas.common import Message
from app.services import audit
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_pair(access: str, refresh: str) -> TokenPair:
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/login", response_model=SessionOut, summary="Log in with email + password")
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SessionOut:
    user, access, refresh = await auth_service.authenticate(
        db, email=payload.email, password=payload.password, request=request
    )
    organization = (
        await db.get(Organization, user.organization_id)
        if user.organization_id
        else None
    )
    return SessionOut(
        user=UserOut.model_validate(user),
        organization_name=organization.name if organization else None,
        organization_timezone=organization.timezone if organization else None,
        tokens=_token_pair(access, refresh),
    )


@router.post("/refresh", response_model=TokenPair, summary="Rotate a refresh token")
async def refresh_tokens(
    payload: RefreshRequest, db: AsyncSession = Depends(get_db)
) -> TokenPair:
    _, access, refresh = await auth_service.refresh_access_token(
        db, refresh_token=payload.refresh_token
    )
    return _token_pair(access, refresh)


@router.post("/logout", response_model=Message, summary="Revoke a refresh token")
async def logout(
    payload: LogoutRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> Message:
    await auth_service.revoke_refresh_token(db, refresh_token=payload.refresh_token)
    await audit.record(
        db,
        action=AuditAction.LOGOUT,
        principal=principal,
        entity_type="user",
        entity_id=principal.user_id,
        summary="User logged out",
        request=request,
    )
    return Message(detail="Signed out")


@router.post(
    "/activate",
    response_model=Message,
    status_code=status.HTTP_200_OK,
    summary="Set a password using a one-time activation or reset link",
)
async def activate(
    payload: ActivateRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> Message:
    await auth_service.consume_activation_token(
        db, raw_token=payload.token, new_password=payload.password, request=request
    )
    return Message(detail="Your password has been set. You can now sign in.")


@router.post("/change-password", response_model=Message, summary="Change your password")
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> Message:
    await auth_service.change_password(
        db,
        user=principal.user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        request=request,
    )
    return Message(detail="Password updated. Please sign in again.")


@router.get("/me", response_model=CurrentUserOut, summary="Current session")
async def me(
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> CurrentUserOut:
    organization = (
        await db.get(Organization, principal.organization_id)
        if principal.organization_id
        else None
    )
    return CurrentUserOut(
        user=UserOut.model_validate(principal.user),
        organization_name=organization.name if organization else None,
        organization_timezone=organization.timezone if organization else None,
        is_impersonating=principal.is_impersonating,
    )
