"""WebSocket relay. Every socket is pinned to the authenticated user's tenant."""
from __future__ import annotations

import asyncio
import contextlib
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import decode_token
from app.db.base import SessionLocal
from app.models import Organization, User
from app.websocket.events import bus

router = APIRouter()


@router.websocket("/stream")
async def stream(websocket: WebSocket, token: str | None = Query(default=None)):
    raw = token or websocket.cookies.get("fb_access")
    claims = decode_token(raw, "access") if raw else None
    if not claims:
        await websocket.close(code=4401, reason="Not authenticated")
        return

    async with SessionLocal() as session:  # type: AsyncSession
        user = await session.get(User, uuid.UUID(claims["sub"]))
        if user is None or not user.is_active or user.organization_id is None:
            await websocket.close(code=4403, reason="No organization scope")
            return
        org = await session.get(Organization, user.organization_id)
        if org is None or org.status != "active":
            await websocket.close(code=4403, reason="Organization unavailable")
            return
        org_id = org.id

    await websocket.accept()
    queue = await bus.subscribe(org_id)
    await websocket.send_json({"event": "connected", "data": {
        "organization_id": str(org_id), "subscribers": bus.subscriber_count(org_id)}})

    async def heartbeat() -> None:
        """Keeps the socket warm and lets the client show connection health."""
        while True:
            await asyncio.sleep(20)
            await websocket.send_json({"event": "ping", "data": {}})

    hb = asyncio.create_task(heartbeat())
    try:
        while True:
            message = await queue.get()
            await websocket.send_text(message)
    except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
        pass
    finally:
        hb.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await hb
        await bus.unsubscribe(org_id, queue)
