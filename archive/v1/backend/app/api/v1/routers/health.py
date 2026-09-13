from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
    }


@router.get("/health/ready", summary="Readiness probe (checks the database)")
async def readiness(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    await db.execute(sa.text("SELECT 1"))
    return {"status": "ready"}
