"""LocationProvider abstraction.

Position data enters FleetBeat through this interface only. Today a simulator
implements it; a real telematics feed replaces it later without the tracking,
trip or alert code changing (spec 36).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(slots=True)
class PositionSample:
    vehicle_id: uuid.UUID
    lat: float
    lon: float
    speed_kph: float
    heading: float
    recorded_at: datetime
    ignition: bool = True
    satellites: int = 11
    odometer_km: float | None = None
    street: str | None = None
    # motion deltas the event detectors need
    acceleration_ms2: float = 0.0
    lateral_g: float = 0.0


class LocationProvider(Protocol):
    """Any source of vehicle positions."""

    name: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def poll(self) -> list[PositionSample]: ...
