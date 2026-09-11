"""The tracking ingest loop.

Runs as a single long-lived process (``python -m app.simulation``), not as a
Celery task: dispatching a job every few seconds per vehicle would spend more
time on broker round-trips than on work, and the loop needs to carry
per-vehicle state between ticks anyway.

What it owns is only orchestration - *when* to pull from the provider, *when*
to refresh the live fleet, and where to send the results. The feed itself is
a ``LocationProvider`` and all persistence lives in ``app.services.tracking``,
so swapping in real GPS hardware changes neither this file nor the database
layer (Section 6).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.models.device import Device
from app.models.enums import DeviceStatus, OrganizationStatus
from app.models.organization import Organization, OrganizationSettings
from app.models.vehicle import Vehicle
from app.realtime.hub import hub
from app.services import tracking
from app.simulation.simulator import SimulatedLocationProvider, build_profiles

logger = logging.getLogger("fleetbeat.simulation")

#: How often the live-vehicle set is re-read, so a device assigned in the
#: Platform Admin Console goes live without a restart.
FLEET_REFRESH_SECONDS = 20.0
#: Default operating centre for vehicles with no recorded position yet.
DEFAULT_CENTER = (52.3676, 4.9041)  # Amsterdam


class TrackingRunner:
    def __init__(self, provider: SimulatedLocationProvider | None = None) -> None:
        self.provider = provider or SimulatedLocationProvider(
            tick_seconds=settings.simulation_tick_seconds,
            event_probability=settings.simulation_event_probability,
        )
        self._runtimes: dict[uuid.UUID, tracking.VehicleRuntime] = {}
        self._geofences: dict[uuid.UUID, list] = {}
        self._speed_limits: dict[uuid.UUID, float] = {}
        self._stopping = asyncio.Event()
        self._last_fleet_refresh: datetime | None = None

    # -- fleet -------------------------------------------------------------

    async def refresh_fleet(self) -> int:
        """Re-read which vehicles have a live device, and reload config.

        Only vehicles with an ACTIVE device belonging to an ACTIVE
        Organization produce data (Section 4a item 2) - everything else shows
        as "Not Tracked" to the customer.
        """
        async with SessionLocal() as db:
            rows = await db.execute(
                sa.select(
                    Vehicle.id,
                    Vehicle.organization_id,
                    Vehicle.last_latitude,
                    Vehicle.last_longitude,
                )
                .join(Device, Device.vehicle_id == Vehicle.id)
                .join(Organization, Organization.id == Vehicle.organization_id)
                .where(
                    Device.status == DeviceStatus.ACTIVE,
                    Organization.status == OrganizationStatus.ACTIVE,
                )
            )
            live = list(rows.all())

            self.provider.sync_fleet(
                build_profiles(
                    [(r[0], r[1], r[2], r[3]) for r in live],
                    default_center=DEFAULT_CENTER,
                )
            )

            vehicle_ids = [r[0] for r in live]
            self._runtimes = await tracking.load_runtimes(db, vehicle_ids)
            for vehicle_id, runtime in self._runtimes.items():
                if runtime.last_latitude is not None and runtime.last_longitude is not None:
                    self.provider.seed_position(
                        vehicle_id, runtime.last_latitude, runtime.last_longitude, 0.0
                    )

            organization_ids = {r[1] for r in live}
            self._geofences = await tracking.load_geofences(db, organization_ids)
            self._speed_limits = await self._load_speed_limits(db, organization_ids)

        self._last_fleet_refresh = datetime.now(UTC)
        return len(live)

    async def _load_speed_limits(
        self, db, organization_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, float]:
        if not organization_ids:
            return {}
        result = await db.execute(
            sa.select(OrganizationSettings).where(
                OrganizationSettings.organization_id.in_(organization_ids)
            )
        )
        return {
            row.organization_id: row.threshold("speeding_kph")
            for row in result.scalars().all()
        }

    # -- one tick ----------------------------------------------------------

    async def tick_once(self, now: datetime | None = None) -> tracking.IngestResult:
        """Advance the feed once and persist the result.

        ``now`` overrides the clock. In production it is left unset and the
        loop runs in real time; passing it lets the loop be driven at
        accelerated time to seed demo data or to verify the whole path
        end-to-end without waiting out real dwell times.
        """
        positions, events = self.provider.tick(now)
        if not positions and not events:
            return tracking.IngestResult()

        async with SessionLocal() as db:
            try:
                result = await tracking.ingest(
                    db,
                    positions=positions,
                    events=events,
                    runtimes=self._runtimes,
                    geofences=self._geofences,
                    speed_limits=self._speed_limits,
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

        for organization_id, messages in result.broadcasts.items():
            if hub.connection_count(organization_id) == 0:
                continue
            for message in messages:
                await hub.broadcast(organization_id, message)

        return result

    # -- loop --------------------------------------------------------------

    async def run(self) -> None:
        await self.provider.start()
        await self.refresh_fleet()
        logger.info(
            "Tracking loop started: %s vehicle(s) live, tick=%ss",
            self.provider.vehicle_count,
            settings.simulation_tick_seconds,
        )

        totals = {"samples": 0, "events": 0, "alerts": 0}
        ticks = 0

        while not self._stopping.is_set():
            started = asyncio.get_running_loop().time()
            try:
                if (
                    self._last_fleet_refresh is None
                    or (datetime.now(UTC) - self._last_fleet_refresh).total_seconds()
                    >= FLEET_REFRESH_SECONDS
                ):
                    await self.refresh_fleet()

                result = await self.tick_once()
                totals["samples"] += result.samples_written
                totals["events"] += result.driver_events
                totals["alerts"] += result.alerts
                ticks += 1
                if ticks % 20 == 0:
                    logger.info(
                        "%s vehicles | %s samples | %s driver events | %s alerts",
                        self.provider.vehicle_count,
                        totals["samples"],
                        totals["events"],
                        totals["alerts"],
                    )
            except Exception:
                # One bad tick must not take the feed down; the next tick
                # re-reads state from the database anyway.
                logger.exception("Tracking tick failed; continuing")

            elapsed = asyncio.get_running_loop().time() - started
            delay = max(0.0, settings.simulation_tick_seconds - elapsed)
            with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=delay)

        await self.provider.stop()
        logger.info("Tracking loop stopped")

    def request_stop(self) -> None:
        self._stopping.set()


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    if not settings.simulation_enabled:
        logger.warning("SIMULATION_ENABLED is false - nothing to do. Exiting.")
        return

    runner = TrackingRunner()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, runner.request_stop)

    try:
        await runner.run()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
