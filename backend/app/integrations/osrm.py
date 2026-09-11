"""OSRM routing client (Section 3).

Routing is *real*: OSRM runs against an OpenStreetMap extract and returns
genuine road geometry, distances and durations. Only the vehicle position
feed is simulated (Section 6, Section 9).

The client degrades honestly rather than silently: if OSRM is unreachable it
raises ``RoutingUnavailableError``, and callers surface that to the user
instead of quietly substituting a straight line, which would produce
confidently wrong ETAs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from app.core.config import settings
from app.core.errors import FleetBeatError

logger = logging.getLogger("fleetbeat.osrm")

DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class RoutingUnavailableError(FleetBeatError):
    status_code = 503
    code = "routing_unavailable"


@dataclass(slots=True)
class RouteLeg:
    distance_m: float
    duration_s: float


@dataclass(slots=True)
class RouteResult:
    distance_m: float
    duration_s: float
    #: Encoded polyline (precision 5) - what MapLibre and flutter_map draw.
    geometry_polyline: str | None = None
    legs: list[RouteLeg] = field(default_factory=list)

    @property
    def distance_km(self) -> float:
        return round(self.distance_m / 1000.0, 2)

    @property
    def duration_minutes(self) -> float:
        return round(self.duration_s / 60.0, 1)


class OsrmClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.osrm_base_url).rstrip("/")

    async def route(
        self,
        coordinates: list[tuple[float, float]],
        *,
        profile: str = "driving",
        overview: str = "full",
    ) -> RouteResult:
        """Route through ``(latitude, longitude)`` points, in order.

        No stop re-sequencing happens here: multi-stop *optimization* is out
        of scope for MVP (Section 9), so the waypoint order the dispatcher
        chose is the order driven.
        """
        if len(coordinates) < 2:
            raise RoutingUnavailableError("A route needs at least two points")

        # OSRM takes lng,lat - the opposite order to everything else here.
        path = ";".join(f"{lng},{lat}" for lat, lng in coordinates)
        url = f"{self.base_url}/route/v1/{profile}/{path}"
        params = {"overview": overview, "geometries": "polyline", "steps": "false"}

        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.warning("OSRM request failed: %s", exc)
            raise RoutingUnavailableError(
                "The routing engine is not reachable. Check that the OSRM "
                "container is running (docker compose --profile routing up osrm)."
            ) from exc

        if response.status_code != 200:
            raise RoutingUnavailableError(
                f"The routing engine returned {response.status_code}"
            )

        body = response.json()
        if body.get("code") != "Ok" or not body.get("routes"):
            raise RoutingUnavailableError(
                f"No route found ({body.get('code', 'unknown error')})"
            )

        route = body["routes"][0]
        return RouteResult(
            distance_m=float(route.get("distance", 0.0)),
            duration_s=float(route.get("duration", 0.0)),
            geometry_polyline=route.get("geometry"),
            legs=[
                RouteLeg(
                    distance_m=float(leg.get("distance", 0.0)),
                    duration_s=float(leg.get("duration", 0.0)),
                )
                for leg in route.get("legs", [])
            ],
        )

    async def is_available(self) -> bool:
        """Cheap health probe, so the UI can say the engine is down."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
                response = await client.get(
                    f"{self.base_url}/route/v1/driving/4.9041,52.3676;4.8952,52.3702",
                    params={"overview": "false"},
                )
            return response.status_code == 200
        except httpx.HTTPError:
            return False


_client: OsrmClient | None = None


def get_osrm_client() -> OsrmClient:
    global _client
    if _client is None:
        _client = OsrmClient()
    return _client


def set_osrm_client(client: OsrmClient) -> None:
    """Swap the client (tests, or a hosted routing provider later)."""
    global _client
    _client = client
