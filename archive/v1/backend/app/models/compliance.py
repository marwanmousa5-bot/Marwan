"""Compliance documents with expiry tracking (Section 4 item 9)."""

from __future__ import annotations

import uuid
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID
from app.models.enums import DocumentType


class ComplianceDocument(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "compliance_documents"
    __table_args__ = (
        sa.Index("ix_compliance_documents_org_expiry", "organization_id", "expires_on"),
    )

    document_type: Mapped[str] = mapped_column(
        sa.String(32), default=DocumentType.OTHER, nullable=False
    )
    title: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    reference_number: Mapped[str | None] = mapped_column(sa.String(120))
    issuer: Mapped[str | None] = mapped_column(sa.String(200))

    # Exactly one of these is normally set.
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("drivers.id", ondelete="CASCADE"), index=True
    )

    issued_on: Mapped[date | None] = mapped_column(sa.Date)
    expires_on: Mapped[date | None] = mapped_column(sa.Date, index=True)
    cost: Mapped[float | None] = mapped_column(sa.Numeric(12, 2))

    file_url: Mapped[str | None] = mapped_column(sa.String(500))
    file_name: Mapped[str | None] = mapped_column(sa.String(255))
    notes: Mapped[str | None] = mapped_column(sa.Text)
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="SET NULL")
    )
