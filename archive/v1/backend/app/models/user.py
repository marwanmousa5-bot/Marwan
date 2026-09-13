"""Users, activation/reset tokens and login-security records.

There is no public registration anywhere in this system (Section 9):
* a ``super_admin`` is seeded once (``app.seed_admin``);
* a ``super_admin`` creates an Organization and its first ``org_admin``;
* an ``org_admin`` invites ``dispatcher``/``driver`` users inside their own
  Organization only.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID
from app.models.enums import UserRole, UserStatus

if TYPE_CHECKING:
    from app.models.driver import Driver
    from app.models.organization import Organization


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.Index("ix_users_org_role", "organization_id", "role"),
    )

    # NULL only for super_admin: platform staff belong to no tenant.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )

    email: Mapped[str] = mapped_column(sa.String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(sa.String(50))

    hashed_password: Mapped[str | None] = mapped_column(sa.String(255))
    role: Mapped[str] = mapped_column(sa.String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        sa.String(32), default=UserStatus.PENDING_ACTIVATION, nullable=False
    )

    must_change_password: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    # Set when the user is created by another user (provisioning / invitation).
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="SET NULL")
    )

    organization: Mapped[Organization | None] = relationship(back_populates="users")
    driver_profile: Mapped[Driver | None] = relationship(
        back_populates="user", uselist=False
    )

    @property
    def is_super_admin(self) -> bool:
        return self.role == UserRole.SUPER_ADMIN

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.email} role={self.role}>"


class ActivationToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One-time "set your password" / password-reset token.

    Section 4a: for MVP the resulting link is *displayed in the Platform Admin
    Console* for staff to send manually. Only the SHA-256 hash of the token is
    stored, so a database read cannot mint a working link.
    """

    __tablename__ = "activation_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(
        sa.String(64), nullable=False, unique=True, index=True
    )
    purpose: Mapped[str] = mapped_column(
        sa.String(32), default="activation", nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    issued_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="SET NULL")
    )


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Server-side refresh-token registry so sessions can be revoked."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(
        sa.String(64), nullable=False, unique=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Set when a super_admin impersonates an Organization (Section 4a item 3).
    impersonated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="SET NULL")
    )


class LoginAttempt(UUIDPrimaryKeyMixin, Base):
    """Raw login attempts, used by rule-based suspicious-login detection."""

    __tablename__ = "login_attempts"
    __table_args__ = (sa.Index("ix_login_attempts_email_time", "email", "attempted_at"),)

    email: Mapped[str] = mapped_column(sa.String(320), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    successful: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(sa.String(64))
    user_agent: Mapped[str | None] = mapped_column(sa.String(500))
    device_fingerprint: Mapped[str | None] = mapped_column(sa.String(128), index=True)
    suspicious: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    suspicion_reason: Mapped[str | None] = mapped_column(sa.String(200))
    attempted_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


class KnownDevice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Devices/browsers a user has previously logged in from."""

    __tablename__ = "known_devices"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "fingerprint", name="uq_known_device"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fingerprint: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    label: Mapped[str | None] = mapped_column(sa.String(200))
    last_ip: Mapped[str | None] = mapped_column(sa.String(64))
    last_seen_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
