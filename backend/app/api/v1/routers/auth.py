"""Authentication: sign in, refresh, sign out, password change, session identity.

There is no public registration - the platform admin creates organizations and
org admins invite users into their own organization (spec 32).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, user_agent
from app.auth.deps import Principal, get_principal
from app.auth.security import (create_access_token, create_refresh_token, decode_token,
                               device_fingerprint, hash_password, hash_token,
                               validate_password_strength, verify_password)
from app.core.config import settings
from app.core.enums import AlertCategory, Role, Severity
from app.db.base import get_session
from app.models import LoginAttempt, Organization, RefreshToken, User
from app.schemas.common import Message
from app.services import alerts as alert_svc
from app.services import audit

router = APIRouter()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    must_change_password: bool = False


class SessionUser(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    phone: str | None = None
    avatar_color: str
    must_change_password: bool
    organization: dict | None = None
    preferences: dict = {}


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


def _set_cookies(response: Response, access: str, refresh: str) -> None:
    secure = settings.environment != "development"
    response.set_cookie("fb_access", access, httponly=True, samesite="lax",
                        secure=secure, max_age=settings.access_token_minutes * 60, path="/")
    response.set_cookie("fb_refresh", refresh, httponly=True, samesite="lax",
                        secure=secure, max_age=settings.refresh_token_days * 86400, path="/")


async def _record_attempt(session: AsyncSession, *, email: str, ok: bool,
                          user: User | None, request: Request,
                          reason: str | None = None) -> LoginAttempt:
    ip = client_ip(request)
    ua = user_agent(request)
    fp = device_fingerprint(ua, ip)

    is_new_device = is_new_location = False
    if user is not None:
        seen = (await session.execute(
            select(func.count()).select_from(LoginAttempt).where(
                LoginAttempt.user_id == user.id, LoginAttempt.successful.is_(True),
                LoginAttempt.device_fingerprint == fp)
        )).scalar_one()
        any_success = (await session.execute(
            select(func.count()).select_from(LoginAttempt).where(
                LoginAttempt.user_id == user.id, LoginAttempt.successful.is_(True))
        )).scalar_one()
        is_new_device = seen == 0 and any_success > 0
        known_ips = (await session.execute(
            select(LoginAttempt.ip_address).where(
                LoginAttempt.user_id == user.id, LoginAttempt.successful.is_(True)
            ).distinct()
        )).scalars().all()
        is_new_location = bool(known_ips) and ip not in known_ips

    attempt = LoginAttempt(
        email=email, user_id=user.id if user else None,
        organization_id=user.organization_id if user else None,
        successful=ok, reason=reason, ip_address=ip, user_agent=(ua or "")[:255] or None,
        device_fingerprint=fp, is_new_device=is_new_device, is_new_location=is_new_location,
    )
    session.add(attempt)
    return attempt


async def _check_suspicious(session: AsyncSession, user: User | None, email: str,
                            attempt: LoginAttempt) -> None:
    """Raise a security alert on repeated failures or an unfamiliar device."""
    if user is None or user.organization_id is None:
        return
    window = datetime.now(timezone.utc) - timedelta(minutes=settings.failed_login_window_minutes)
    failures = (await session.execute(
        select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.email == email, LoginAttempt.successful.is_(False),
            LoginAttempt.created_at >= window)
    )).scalar_one()

    if failures >= settings.failed_login_lock_threshold:
        await alert_svc.raise_alert(
            session, org_id=user.organization_id, code="suspicious_login",
            severity=Severity.HIGH, category=AlertCategory.SECURITY,
            title=f"Repeated failed sign-ins for {user.full_name}",
            detail=f"{failures} failed attempts in the last "
                   f"{settings.failed_login_window_minutes} minutes.",
            dedupe_extra=f"failed:{user.id}",
            evidence={"attempts": failures, "ip": attempt.ip_address},
        )
    elif attempt.successful and (attempt.is_new_device or attempt.is_new_location):
        what = "a new device" if attempt.is_new_device else "a new location"
        await alert_svc.raise_alert(
            session, org_id=user.organization_id, code="suspicious_login",
            severity=Severity.MEDIUM, category=AlertCategory.SECURITY,
            title=f"{user.full_name} signed in from {what}",
            detail="Confirm with the user that this sign-in was expected.",
            dedupe_extra=f"device:{user.id}:{attempt.device_fingerprint}",
            evidence={"new_device": attempt.is_new_device,
                      "new_location": attempt.is_new_location},
        )


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, request: Request, response: Response,
                session: AsyncSession = Depends(get_session)):
    email = payload.email.lower().strip()
    user = (await session.execute(select(User).where(User.email == email))).scalars().first()

    generic = HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "That email and password combination is not recognised.")

    if user is None:
        await _record_attempt(session, email=email, ok=False, user=None, request=request,
                              reason="unknown_email")
        await session.commit()
        raise generic

    now = datetime.now(timezone.utc)
    if user.locked_until and user.locked_until > now:
        await _record_attempt(session, email=email, ok=False, user=user, request=request,
                              reason="locked")
        await session.commit()
        minutes = max(1, round((user.locked_until - now).total_seconds() / 60))
        raise HTTPException(
            status.HTTP_423_LOCKED,
            f"This account is temporarily locked after repeated failed sign-ins. "
            f"Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
        )

    if not user.is_active:
        await _record_attempt(session, email=email, ok=False, user=user, request=request,
                              reason="inactive")
        await session.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "This account has been deactivated. Contact your administrator.")

    if not verify_password(payload.password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.failed_login_lock_threshold:
            user.locked_until = now + timedelta(minutes=settings.failed_login_window_minutes)
            user.failed_login_count = 0
        attempt = await _record_attempt(session, email=email, ok=False, user=user,
                                        request=request, reason="bad_password")
        await _check_suspicious(session, user, email, attempt)
        await audit.record(session, action=audit.LOGIN_FAILED,
                           organization_id=user.organization_id, actor=user,
                           entity_type="user", entity_id=user.id, entity_label=user.email,
                           summary="Failed sign-in attempt",
                           ip_address=client_ip(request), user_agent=user_agent(request))
        await session.commit()
        raise generic

    org = await session.get(Organization, user.organization_id) if user.organization_id else None
    if org is not None and org.status == "suspended" and user.role != Role.SUPER_ADMIN:
        await _record_attempt(session, email=email, ok=False, user=user, request=request,
                              reason="org_suspended")
        await session.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Your organization's access is currently suspended.")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now

    access = create_access_token(user.id, user.role, user.organization_id)
    raw_refresh, refresh_hash, expires = create_refresh_token(user.id)
    session.add(RefreshToken(user_id=user.id, token_hash=refresh_hash, expires_at=expires,
                             user_agent=(user_agent(request) or "")[:255] or None,
                             ip_address=client_ip(request)))
    attempt = await _record_attempt(session, email=email, ok=True, user=user, request=request)
    await _check_suspicious(session, user, email, attempt)
    await audit.record(session, action=audit.LOGIN, organization_id=user.organization_id,
                       actor=user, entity_type="user", entity_id=user.id,
                       entity_label=user.email, summary="Signed in",
                       ip_address=client_ip(request), user_agent=user_agent(request))
    await session.commit()

    _set_cookies(response, access, raw_refresh)
    return TokenPair(access_token=access, refresh_token=raw_refresh,
                     expires_in=settings.access_token_minutes * 60,
                     must_change_password=user.must_change_password)


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, request: Request, response: Response,
                  session: AsyncSession = Depends(get_session)):
    raw = payload.refresh_token or request.cookies.get("fb_refresh")
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token supplied.")
    claims = decode_token(raw, "refresh")
    if not claims:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Your session has expired. Please sign in again.")
    stored = (await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw))
    )).scalars().first()
    now = datetime.now(timezone.utc)
    if stored is None or stored.revoked_at or stored.expires_at <= now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Your session has expired. Please sign in again.")
    user = await session.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is inactive.")

    # rotate
    stored.revoked_at = now
    access = create_access_token(user.id, user.role, user.organization_id)
    new_raw, new_hash, expires = create_refresh_token(user.id)
    session.add(RefreshToken(user_id=user.id, token_hash=new_hash, expires_at=expires,
                             user_agent=(user_agent(request) or "")[:255] or None,
                             ip_address=client_ip(request)))
    await session.commit()
    _set_cookies(response, access, new_raw)
    return TokenPair(access_token=access, refresh_token=new_raw,
                     expires_in=settings.access_token_minutes * 60,
                     must_change_password=user.must_change_password)


@router.post("/logout", response_model=Message)
async def logout(request: Request, response: Response,
                 principal: Principal = Depends(get_principal),
                 session: AsyncSession = Depends(get_session)):
    raw = request.cookies.get("fb_refresh")
    if raw:
        stored = (await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw))
        )).scalars().first()
        if stored:
            stored.revoked_at = datetime.now(timezone.utc)
    await audit.record(session, action=audit.LOGOUT,
                       organization_id=principal.org_id, actor=principal.user,
                       entity_type="user", entity_id=principal.user.id,
                       summary="Signed out", ip_address=client_ip(request))
    await session.commit()
    response.delete_cookie("fb_access", path="/")
    response.delete_cookie("fb_refresh", path="/")
    return Message(detail="Signed out.")


@router.get("/me", response_model=SessionUser)
async def me(principal: Principal = Depends(get_principal)):
    org = principal.organization
    return SessionUser(
        id=principal.user.id, email=principal.user.email,
        full_name=principal.user.full_name, role=principal.user.role,
        phone=principal.user.phone, avatar_color=principal.user.avatar_color,
        must_change_password=principal.user.must_change_password,
        preferences=principal.user.preferences or {},
        organization={"id": str(org.id), "name": org.name, "slug": org.slug,
                      "status": org.status, "city": org.city, "country": org.country,
                      "settings": org.settings} if org else None,
    )


@router.post("/change-password", response_model=Message)
async def change_password(payload: PasswordChange, request: Request,
                          principal: Principal = Depends(get_principal),
                          session: AsyncSession = Depends(get_session)):
    user = principal.user
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Your current password is not correct.")
    problem = validate_password_strength(payload.new_password)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Choose a password you have not used before.")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    await session.execute(
        RefreshToken.__table__.update()
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await audit.record(session, action=audit.PASSWORD_CHANGED,
                       organization_id=principal.org_id, actor=user,
                       entity_type="user", entity_id=user.id, summary="Password changed",
                       ip_address=client_ip(request))
    await session.commit()
    return Message(detail="Password updated. Other sessions have been signed out.")
