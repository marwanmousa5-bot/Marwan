"""Shared request helpers."""
from __future__ import annotations

import uuid
from typing import Any, Sequence

from fastapi import HTTPException, Request, status
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


async def paginate(session: AsyncSession, stmt: Select, page: int, size: int) -> dict:
    total = (await session.execute(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    )).scalar_one()
    rows = (await session.execute(stmt.limit(size).offset((page - 1) * size))).scalars().all()
    return {
        "items": rows,
        "page": page,
        "size": size,
        "total": total,
        "pages": max(1, (total + size - 1) // size),
    }


async def get_or_404(session: AsyncSession, model, entity_id: uuid.UUID,
                     org_id: uuid.UUID | None, label: str) -> Any:
    """Fetch inside the caller's tenant. A cross-tenant id is simply not found."""
    obj = await session.get(model, entity_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not found.")
    if org_id is not None and getattr(obj, "organization_id", None) != org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not found.")
    return obj
