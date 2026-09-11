"""NotificationService abstraction (Section 4a item 1).

MVP ships a console/no-op implementation: activation links are surfaced in
the Platform Admin Console UI for staff to send manually, and no
transactional email provider is integrated in this phase. Plugging in a real
provider later means adding one subclass and swapping the factory - the
provisioning flow itself does not change.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("fleetbeat.notifications")


@dataclass(slots=True)
class Notification:
    channel: str  # "email" | "push" | "sms"
    recipient: str
    subject: str
    body: str
    metadata: dict[str, Any] = field(default_factory=dict)


class NotificationService(ABC):
    @abstractmethod
    async def send(self, notification: Notification) -> bool:
        """Deliver a notification. Returns True when handed off successfully."""


class ConsoleNotificationService(NotificationService):
    """Logs instead of sending. The only implementation wired up for MVP."""

    async def send(self, notification: Notification) -> bool:
        logger.info(
            "[notification:%s] to=%s subject=%s",
            notification.channel,
            notification.recipient,
            notification.subject,
        )
        logger.debug("body: %s", notification.body)
        return True


class NullPushService(NotificationService):
    """Placeholder for driver push notifications (wired up in Phase 3)."""

    async def send(self, notification: Notification) -> bool:  # pragma: no cover
        logger.info(
            "[push:pending-implementation] to=%s subject=%s",
            notification.recipient,
            notification.subject,
        )
        return False


_service: NotificationService = ConsoleNotificationService()


def get_notification_service() -> NotificationService:
    return _service


def set_notification_service(service: NotificationService) -> None:
    """Swap the implementation (used by tests and by a future email provider)."""
    global _service
    _service = service
