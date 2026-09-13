"""AI assistant, copilot and reporting schemas (Sections 4e and 5)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import RecommendationKind, RecommendationStatus
from app.schemas.common import ORMModel


class AssistantAsk(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class AssistantReplyOut(BaseModel):
    answer: str
    capability: str
    kind: str
    data: dict[str, Any] = Field(default_factory=dict)
    #: Present only for actions. Nothing has changed until this is sent back
    #: to the confirm endpoint (Section 9).
    pending_action: dict[str, Any] | None = None
    offline: bool = False


class AssistantConfirm(BaseModel):
    pending_action: dict[str, Any]


class AssistantActionResult(BaseModel):
    capability: str
    applied_count: int
    tasks: list[str] = Field(default_factory=list)
    message: str


class RecommendationOut(ORMModel):
    id: uuid.UUID
    kind: RecommendationKind
    status: RecommendationStatus
    rank: int
    title: str
    summary: str
    suggested_action: str | None = None
    estimated_benefit: str | None = None
    action_payload: dict | None = None
    signals: dict | None = None
    vehicle_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    created_at: datetime


class MaintenanceProposalOut(BaseModel):
    vehicle_id: uuid.UUID
    vehicle_name: str
    schedule_id: uuid.UUID
    schedule_name: str
    proposed_date: date
    rationale: str
    tasks_that_day: int
    auto_booked: bool
    work_order_id: uuid.UUID | None = None


class ReportSummaryOut(ORMModel):
    id: uuid.UUID
    period_type: str
    period_start: datetime
    period_end: datetime
    summary_text: str
    metrics: dict | None = None
    generated_by: str
    created_at: datetime
