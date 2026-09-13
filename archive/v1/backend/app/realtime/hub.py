"""WebSocket fan-out hub for live tracking (Section 3 / Section 4b).

Connections are grouped by Organization so a broadcast can never cross a
tenant boundary - the same isolation rule that applies to the REST API
applies here.

Phase 1 ships the in-process hub and the tenant-keyed routing; Phase 2 wires
it to the simulation engine and adds the Redis pub/sub bridge needed once the
API runs on more than one worker process.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class ConnectionHub:
    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, organization_id: uuid.UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[organization_id].add(websocket)

    async def disconnect(self, organization_id: uuid.UUID, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections[organization_id].discard(websocket)
            if not self._connections[organization_id]:
                self._connections.pop(organization_id, None)

    async def broadcast(self, organization_id: uuid.UUID, message: dict[str, Any]) -> int:
        """Send to every socket of ONE Organization. Returns the delivery count."""
        async with self._lock:
            targets = list(self._connections.get(organization_id, ()))

        delivered = 0
        stale: list[WebSocket] = []
        for socket in targets:
            try:
                await socket.send_json(message)
                delivered += 1
            except Exception:  # noqa: BLE001 - a dead socket must not break fan-out
                stale.append(socket)

        for socket in stale:
            await self.disconnect(organization_id, socket)
        return delivered

    def connection_count(self, organization_id: uuid.UUID) -> int:
        return len(self._connections.get(organization_id, ()))


hub = ConnectionHub()
