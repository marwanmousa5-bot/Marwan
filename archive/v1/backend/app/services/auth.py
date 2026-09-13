"""Authentication, activation links and login-security rules.

There is no registration function in this module and there must never be
one (Section 9). Accounts only come into existence through
``app.services.provisioning`` (platform staff creating an Organization) or
``app.services.users`` (an Org Admin inviting a colleague).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthenticationError, NotFoundError, ValidationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    device_fingerprint,
    generate_link_token,
    hash_link_token,
    hash_password,
    verify_password,
)
from app.models.enums import (
    AlertRuleType,
    AlertSeverity,
    AuditAction,
    OrganizationStatus,
    UserStatus,
)
from app.models.organization import Organization
from app.models.user import (
    ActivationToken,
    KnownDevice,
    LoginAttempt,
    RefreshToken,
    User,
)
from app.services import audit

MIN_PASSWORD_LENGTH = 12


async def _fail(db: AsyncSession, message: str) -> AuthenticationError:
    """Persist login bookkeeping, then raise.

    Failed-attempt counters, lockouts and audit rows are security records:
    they must survive the request that produced them. Without this commit the
    caller's rollback (``get_db``) would erase the very evidence of the failed
    attempt, and account lockout would never trigger.
    """
    await db.commit()
    return AuthenticationError(message)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; normalise before comparing."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def validate_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long"
        )
    if password.lower() == password or password.upper() == password:
        raise ValidationError(
            "Password must contain both uppercase and lowercase characters"
        )
    if not any(c.isdigit() for c in password):
        raise ValidationError("Password must contain at least one digit")


# --------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------

async def authenticate(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    request: Request | None = None,
) -> tuple[User, str, str]:
    """Verify credentials and issue an access/refresh token pair."""
    normalised = email.strip().lower()
    ip = _client_ip(request)
    agent = (request.headers.get("user-agent") if request else None) or None
    fingerprint = device_fingerprint(agent, ip)

    result = await db.execute(
        sa.select(User).where(sa.func.lower(User.email) == normalised).limit(1)
    )
    user = result.scalar_one_or_none()

    if user is None:
        await _record_attempt(
            db, email=normalised, user=None, ok=False, ip=ip, agent=agent,
            fingerprint=fingerprint,
        )
        await audit.record(
            db, action=AuditAction.LOGIN_FAILURE, actor_email=normalised,
            summary="Login failed: unknown email", request=request,
        )
        raise await _fail(db, "Incorrect email or password")

    locked_until = _aware(user.locked_until)
    if locked_until and locked_until > utcnow():
        await _record_attempt(
            db, email=normalised, user=user, ok=False, ip=ip, agent=agent,
            fingerprint=fingerprint, suspicious=True,
            reason="Attempt while account locked",
        )
        raise await _fail(
            db, "Account temporarily locked after repeated failed attempts"
        )

    if not verify_password(password, user.hashed_password):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.failed_login_lockout_threshold:
            user.locked_until = utcnow() + timedelta(
                minutes=settings.failed_login_lockout_minutes
            )
        await _record_attempt(
            db, email=normalised, user=user, ok=False, ip=ip, agent=agent,
            fingerprint=fingerprint,
        )
        await audit.record(
            db,
            action=AuditAction.LOGIN_FAILURE,
            organization_id=user.organization_id,
            actor_email=normalised,
            actor_role=user.role,
            summary="Login failed: incorrect password",
            request=request,
        )
        await _flag_repeated_failures(db, user=user, ip=ip, request=request)
        raise await _fail(db, "Incorrect email or password")

    if user.status == UserStatus.PENDING_ACTIVATION:
        raise AuthenticationError(
            "This account has not been activated yet. Use the activation link "
            "provided during onboarding."
        )
    if user.status != UserStatus.ACTIVE:
        raise AuthenticationError("This account has been suspended")

    if user.organization_id is not None:
        organization = await db.get(Organization, user.organization_id)
        if organization is None or organization.status != OrganizationStatus.ACTIVE:
            raise AuthenticationError("Your organization's account is suspended")

    # Success.
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = utcnow()

    suspicious, reason = await _evaluate_new_device(
        db, user=user, fingerprint=fingerprint, ip=ip, agent=agent
    )
    await _record_attempt(
        db, email=normalised, user=user, ok=True, ip=ip, agent=agent,
        fingerprint=fingerprint, suspicious=suspicious, reason=reason,
    )
    await audit.record(
        db,
        action=AuditAction.LOGIN_SUCCESS,
        organization_id=user.organization_id,
        actor_email=user.email,
        actor_role=user.role,
        entity_type="user",
        entity_id=user.id,
        summary="Login successful",
        request=request,
    )
    if suspicious:
        await _raise_suspicious_login_alert(db, user=user, reason=reason, request=request)

    access, refresh = await issue_tokens(db, user=user)
    return user, access, refresh


async def issue_tokens(
    db: AsyncSession, *, user: User, impersonator_id: uuid.UUID | None = None
) -> tuple[str, str]:
    access = create_access_token(
        user_id=user.id,
        role=user.role,
        organization_id=user.organization_id,
        impersonator_id=impersonator_id,
    )
    refresh_raw, expires_at = create_refresh_token(user_id=user.id)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_link_token(refresh_raw),
            expires_at=expires_at,
            impersonated_by_user_id=impersonator_id,
        )
    )
    await db.flush()
    return access, refresh_raw


async def refresh_access_token(
    db: AsyncSession, *, refresh_token: str
) -> tuple[User, str, str]:
    """Rotate a refresh token, returning a fresh pair."""
    token_hash = hash_link_token(refresh_token)
    result = await db.execute(
        sa.select(RefreshToken).where(RefreshToken.token_hash == token_hash).limit(1)
    )
    stored = result.scalar_one_or_none()
    if stored is None or stored.revoked_at is not None:
        raise AuthenticationError("Refresh token is invalid or has been revoked")
    expires_at = _aware(stored.expires_at)
    if expires_at and expires_at <= utcnow():
        raise AuthenticationError("Refresh token has expired")

    user = await db.get(User, stored.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise AuthenticationError("User is no longer active")

    stored.revoked_at = utcnow()
    access, new_refresh = await issue_tokens(
        db, user=user, impersonator_id=stored.impersonated_by_user_id
    )
    return user, access, new_refresh


async def revoke_refresh_token(db: AsyncSession, *, refresh_token: str) -> None:
    result = await db.execute(
        sa.select(RefreshToken)
        .where(RefreshToken.token_hash == hash_link_token(refresh_token))
        .limit(1)
    )
    stored = result.scalar_one_or_none()
    if stored and stored.revoked_at is None:
        stored.revoked_at = utcnow()


async def revoke_all_sessions(db: AsyncSession, *, user_id: uuid.UUID) -> None:
    await db.execute(
        sa.update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


# --------------------------------------------------------------------------
# Activation / password reset links
# --------------------------------------------------------------------------

async def create_activation_link(
    db: AsyncSession,
    *,
    user: User,
    purpose: str = "activation",
    issued_by_user_id: uuid.UUID | None = None,
) -> tuple[str, ActivationToken]:
    """Mint a one-time link. Returns ``(absolute_url, token_row)``.

    For MVP the caller displays this URL in the Platform Admin Console for
    staff to deliver manually (Section 4a).
    """
    # Invalidate any outstanding link of the same purpose.
    await db.execute(
        sa.update(ActivationToken)
        .where(
            ActivationToken.user_id == user.id,
            ActivationToken.purpose == purpose,
            ActivationToken.used_at.is_(None),
        )
        .values(used_at=utcnow())
    )

    raw, token_hash = generate_link_token()
    token = ActivationToken(
        user_id=user.id,
        token_hash=token_hash,
        purpose=purpose,
        expires_at=utcnow() + timedelta(hours=settings.activation_token_expire_hours),
        issued_by_user_id=issued_by_user_id,
    )
    db.add(token)
    await db.flush()

    path = "/activate" if purpose == "activation" else "/reset-password"
    url = f"{settings.web_app_base_url.rstrip('/')}{path}?token={raw}"
    return url, token


async def consume_activation_token(
    db: AsyncSession, *, raw_token: str, new_password: str, request: Request | None = None
) -> User:
    """Set a password using a one-time link and activate the account."""
    validate_password_strength(new_password)

    result = await db.execute(
        sa.select(ActivationToken)
        .where(ActivationToken.token_hash == hash_link_token(raw_token))
        .limit(1)
    )
    token = result.scalar_one_or_none()
    if token is None or token.used_at is not None:
        raise NotFoundError("This link is invalid or has already been used")
    expires_at = _aware(token.expires_at)
    if expires_at and expires_at <= utcnow():
        raise ValidationError("This link has expired. Ask for a new one.")

    user = await db.get(User, token.user_id)
    if user is None:
        raise NotFoundError("Account not found")

    user.hashed_password = hash_password(new_password)
    user.status = UserStatus.ACTIVE
    user.must_change_password = False
    user.failed_login_count = 0
    user.locked_until = None
    token.used_at = utcnow()

    # A password change invalidates every existing session.
    await revoke_all_sessions(db, user_id=user.id)
    await audit.record(
        db,
        action=AuditAction.PASSWORD_SET,
        organization_id=user.organization_id,
        actor_email=user.email,
        actor_role=user.role,
        entity_type="user",
        entity_id=user.id,
        summary=f"Password set via {token.purpose} link",
        request=request,
    )
    return user


async def change_password(
    db: AsyncSession,
    *,
    user: User,
    current_password: str,
    new_password: str,
    request: Request | None = None,
) -> None:
    if not verify_password(current_password, user.hashed_password):
        raise AuthenticationError("Current password is incorrect")
    validate_password_strength(new_password)
    user.hashed_password = hash_password(new_password)
    user.must_change_password = False
    await revoke_all_sessions(db, user_id=user.id)
    await audit.record(
        db,
        action=AuditAction.PASSWORD_SET,
        organization_id=user.organization_id,
        actor_email=user.email,
        actor_role=user.role,
        entity_type="user",
        entity_id=user.id,
        summary="Password changed by user",
        request=request,
    )


# --------------------------------------------------------------------------
# Suspicious-login detection (rule-based, Section 4 item 18)
# --------------------------------------------------------------------------

async def _evaluate_new_device(
    db: AsyncSession,
    *,
    user: User,
    fingerprint: str,
    ip: str | None,
    agent: str | None,
) -> tuple[bool, str | None]:
    result = await db.execute(
        sa.select(KnownDevice).where(
            KnownDevice.user_id == user.id, KnownDevice.fingerprint == fingerprint
        ).limit(1)
    )
    known = result.scalar_one_or_none()
    if known is not None:
        known.last_ip = ip
        known.last_seen_at = utcnow()
        return False, None

    # First device ever seen for this user is the enrolment, not a suspicion.
    count_result = await db.execute(
        sa.select(sa.func.count()).select_from(KnownDevice).where(
            KnownDevice.user_id == user.id
        )
    )
    is_first_device = int(count_result.scalar_one()) == 0

    db.add(
        KnownDevice(
            user_id=user.id,
            fingerprint=fingerprint,
            label=(agent or "Unknown device")[:200],
            last_ip=ip,
            last_seen_at=utcnow(),
        )
    )
    if is_first_device:
        return False, None
    return True, "Login from an unrecognised device or location"


async def _flag_repeated_failures(
    db: AsyncSession, *, user: User, ip: str | None, request: Request | None
) -> None:
    if user.failed_login_count < settings.failed_login_lockout_threshold:
        return
    await audit.record(
        db,
        action=AuditAction.SUSPICIOUS_LOGIN_FLAGGED,
        organization_id=user.organization_id,
        actor_email=user.email,
        actor_role=user.role,
        entity_type="user",
        entity_id=user.id,
        summary=(
            f"{user.failed_login_count} consecutive failed login attempts"
            f" from {ip or 'unknown IP'}"
        ),
        request=request,
    )
    await _raise_suspicious_login_alert(
        db, user=user, reason="Repeated failed login attempts", request=request
    )


async def _raise_suspicious_login_alert(
    db: AsyncSession, *, user: User, reason: str | None, request: Request | None
) -> None:
    """Raise an Alert when the user belongs to an Organization.

    Platform-staff anomalies are audit-log-only: Alerts are tenant-scoped.
    """
    if user.organization_id is None:
        return
    # Imported lazily to keep the auth module free of alert-engine imports.
    from app.models.alert import Alert

    db.add(
        Alert(
            organization_id=user.organization_id,
            rule_type=AlertRuleType.SUSPICIOUS_LOGIN,
            severity=AlertSeverity.WARNING,
            title="Suspicious login activity",
            message=f"{reason or 'Unusual login'} for {user.email}.",
            subject_type="user",
            subject_id=user.id,
            dedupe_key=f"suspicious_login:{user.id}:{utcnow():%Y-%m-%d}",
            context={"reason": reason, "email": user.email},
        )
    )


async def _record_attempt(
    db: AsyncSession,
    *,
    email: str,
    user: User | None,
    ok: bool,
    ip: str | None,
    agent: str | None,
    fingerprint: str,
    suspicious: bool = False,
    reason: str | None = None,
) -> None:
    db.add(
        LoginAttempt(
            email=email,
            user_id=user.id if user else None,
            successful=ok,
            ip_address=ip,
            user_agent=(agent or "")[:500] or None,
            device_fingerprint=fingerprint,
            suspicious=suspicious,
            suspicion_reason=reason,
            attempted_at=utcnow(),
        )
    )


def _client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
