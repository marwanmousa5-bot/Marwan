"""Persistence for the AI layer (Section 5).

Every AI-produced *action* lands here as a proposal first: nothing in this
system changes real data without an explicit user confirmation step
(Section 9).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID, JSONB
from app.models.enums import RecommendationStatus


class Recommendation(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """A proposed action from the Copilot / Maintenance Copilot / rerouting."""

    __tablename__ = "recommendations"
    __table_args__ = (
        sa.Index("ix_recommendations_org_status", "organization_id", "status"),
        sa.Index("ix_recommendations_dedupe", "organization_id", "dedupe_key"),
    )

    kind: Mapped[str] = mapped_column(sa.String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        sa.String(24), default=RecommendationStatus.PENDING, nullable=False
    )
    rank: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)

    title: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    summary: Mapped[str] = mapped_column(sa.Text, nullable=False)
    suggested_action: Mapped[str | None] = mapped_column(sa.Text)
    estimated_benefit: Mapped[str | None] = mapped_column(sa.String(200))

    #: The structured, machine-executable form of ``suggested_action``.
    #: e.g. {"op": "reassign_stop", "from_task": "...", "to_task": "..."}
    action_payload: Mapped[dict | None] = mapped_column(JSONB)
    #: The rule-derived facts handed to the LLM - the LLM phrases, never invents.
    signals: Mapped[dict | None] = mapped_column(JSONB)

    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("drivers.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("tasks.id", ondelete="CASCADE")
    )

    dedupe_key: Mapped[str | None] = mapped_column(sa.String(200))
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="SET NULL")
    )


class AssistantConversation(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """A chat thread with the Agentic NL Fleet Assistant (Section 5 item 3)."""

    __tablename__ = "assistant_conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(sa.String(200))


class AssistantMessage(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "assistant_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        sa.ForeignKey("assistant_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(sa.String(16), nullable=False)  # user|assistant
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    #: Parsed intent when the message requested an action.
    intent: Mapped[dict | None] = mapped_column(JSONB)
    #: Pending action awaiting the user's explicit confirmation.
    pending_action: Mapped[dict | None] = mapped_column(JSONB)
    confirmed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class ReportSummary(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Auto-generated weekly/monthly narrative summary (Section 5 item 5)."""

    __tablename__ = "report_summaries"

    period_type: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    period_start: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    summary_text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    metrics: Mapped[dict | None] = mapped_column(JSONB)
    generated_by: Mapped[str] = mapped_column(
        sa.String(32), default="rule_based", nullable=False
    )
