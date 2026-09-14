from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    size: int
    total: int
    pages: int


class Message(BaseModel):
    detail: str
    hint: str | None = None


class IdName(BaseModel):
    id: uuid.UUID
    name: str


class TimelineEntry(ORMModel):
    id: uuid.UUID
    occurred_at: datetime
    actor_type: str
    actor_name: str
    action: str
    description: str
    related_type: str | None = None
    related_id: uuid.UUID | None = None
    meta: dict = Field(default_factory=dict)
