"""The ``LocationProvider`` abstraction (Section 6).

Swapping the simulated feed for real GPS hardware or a telematics API must
mean implementing ONE new class here - never rewriting the tracking module.
Everything downstream (trip assembly, position persistence, WebSocket
fan-out, geofence evaluation) consumes ``PositionUpdate`` and
``TelemetryEvent`` and knows nothing about where they came from.

The simulated implementation lands in Phase 2 (``app.simulation.simulator``).
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.enums import DriverEventType


@dataclass(slots=True)
class PositionUpdate:
    """One GPS fix for one vehicle, from any source."""

    vehicle_id: uuid.UUID
    organization_id: uuid.UUID
    latitude: float
    longitude: float
    speed_kph: float
    heading: float
    recorded_at: datetime
    ignition_on: bool = True
    altitude_m: float | None = None
    accuracy_m: float | None = None
    source: str = "simulated"


@dataclass(slots=True)
class TelemetryEvent:
    """A behavioural event (harsh braking, speeding, ...) from the feed."""

    vehicle_id: uuid.UUID
    organization_id: uuid.UUID
    event_type: DriverEventType
    occurred_at: datetime
    latitude: float | None = None
    longitude: float | None = None
    speed_kph: float | None = None
    magnitude: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


class LocationProvider(ABC):
    """Source of vehicle position and telemetry data."""

    #: Human-readable name recorded on every persisted sample.
    name: str = "abstract"

    @abstractmethod
    async def start(self) -> None:
        """Prepare the provider (open connections, seed state)."""

    @abstractmethod
    async def stop(self) -> None:
        """Release any resources."""

    @abstractmethod
    def stream(self) -> AsyncIterator[PositionUpdate | TelemetryEvent]:
        """Yield position updates and telemetry events as they occur."""


class NullLocationProvider(LocationProvider):
    """No-op provider used when simulation is disabled."""

    name = "null"

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def stream(self) -> AsyncIterator[PositionUpdate | TelemetryEvent]:
        # An empty async generator.
        return
        yield  # pragma: no cover
