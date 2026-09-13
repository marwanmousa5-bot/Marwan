"""In-process event bus + WebSocket fan-out.

Backend services publish domain events (spec 18); the API layer relays them to
subscribed browsers, scoped strictly per organization.
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import orjson

# --- canonical event names (spec 18) ---------------------------------------
VEHICLE_LOCATION_UPDATED = "vehicle.location.updated"
VEHICLE_STATUS_CHANGED = "vehicle.status.changed"
TASK_CREATED = "task.created"
TASK_ASSIGNED = "task.assigned"
TASK_ACCEPTED = "task.accepted"
TASK_STARTED = "task.started"
TASK_UPDATED = "task.updated"
TASK_COMPLETED = "task.completed"
TASK_FAILED = "task.failed"
ALERT_TRIGGERED = "alert.triggered"
ALERT_ACKNOWLEDGED = "alert.acknowledged"
ALERT_RESOLVED = "alert.resolved"
ALERT_UPDATED = "alert.updated"
MAINTENANCE_DUE = "maintenance.due"
WORK_ORDER_CREATED = "maintenance.work_order.created"
WORK_ORDER_UPDATED = "maintenance.work_order.updated"
WORK_ORDER_COMPLETED = "maintenance.work_order.completed"
DRIVER_EVENT_CREATED = "driver.event.created"
INCIDENT_CREATED = "incident.created"
TRIP_STARTED = "trip.started"
TRIP_COMPLETED = "trip.completed"
ROUTE_CHANGED = "route.changed"
NOTIFICATION_CREATED = "notification.created"
RECOMMENDATION_CREATED = "ai.recommendation.created"


def _default(obj: Any):
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError


class EventBus:
    """Fan-out hub. One queue per connected socket keeps slow clients isolated."""

    def __init__(self) -> None:
        # org_id -> set of queues
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._seq = 0

    async def subscribe(self, org_id: uuid.UUID | str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        async with self._lock:
            self._subscribers[str(org_id)].add(q)
        return q

    async def unsubscribe(self, org_id: uuid.UUID | str, q: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers[str(org_id)].discard(q)

    def subscriber_count(self, org_id: uuid.UUID | str) -> int:
        return len(self._subscribers.get(str(org_id), ()))

    async def publish(self, org_id: uuid.UUID | str | None, event: str,
                      payload: dict | None = None) -> None:
        if org_id is None:
            return
        self._seq += 1
        message = orjson.dumps(
            {
                "seq": self._seq,
                "event": event,
                "at": datetime.now(timezone.utc).isoformat(),
                "data": payload or {},
            },
            default=_default,
        ).decode()
        dead = []
        for q in tuple(self._subscribers.get(str(org_id), ())):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            # A client that cannot keep up is dropped; it reconciles on reconnect.
            await self.unsubscribe(org_id, q)

    async def publish_many(self, org_id, events: list[tuple[str, dict]]) -> None:
        for name, payload in events:
            await self.publish(org_id, name, payload)


bus = EventBus()


@contextlib.asynccontextmanager
async def subscription(org_id):
    q = await bus.subscribe(org_id)
    try:
        yield q
    finally:
        await bus.unsubscribe(org_id, q)
