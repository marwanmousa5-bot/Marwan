"""Open-Meteo weather client and adverse-condition zones (Section 4e).

Open-Meteo was chosen because it needs no API key and no billing account,
which keeps `docker compose up` genuinely one command for a new developer.
The client is thin and the mapping from weather code to "adverse zone" lives
here, so swapping providers means rewriting one file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger("fleetbeat.weather")

DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

#: WMO weather codes that matter operationally, mapped to
#: (condition label, severity, typical delay in minutes).
#: Anything not listed is treated as fine weather and produces no zone - a
#: map covered in "light cloud" markers would train people to ignore it.
ADVERSE_CODES: dict[int, tuple[str, str, int]] = {
    45: ("fog", "warning", 10),
    48: ("freezing_fog", "critical", 20),
    55: ("heavy_drizzle", "info", 5),
    63: ("rain", "warning", 10),
    65: ("heavy_rain", "critical", 20),
    66: ("freezing_rain", "critical", 30),
    67: ("heavy_freezing_rain", "critical", 35),
    73: ("snow", "warning", 20),
    75: ("heavy_snow", "critical", 35),
    77: ("snow_grains", "warning", 15),
    81: ("rain_showers", "warning", 10),
    82: ("violent_rain_showers", "critical", 25),
    85: ("snow_showers", "warning", 20),
    86: ("heavy_snow_showers", "critical", 35),
    95: ("thunderstorm", "critical", 25),
    96: ("thunderstorm_hail", "critical", 40),
    99: ("severe_thunderstorm_hail", "critical", 45),
}


@dataclass(slots=True)
class WeatherObservation:
    latitude: float
    longitude: float
    weather_code: int
    temperature_c: float | None
    wind_kph: float | None
    precipitation_mm: float | None
    observed_at: str

    @property
    def is_adverse(self) -> bool:
        return self.weather_code in ADVERSE_CODES

    @property
    def condition(self) -> str:
        return ADVERSE_CODES.get(self.weather_code, ("clear", "info", 0))[0]

    @property
    def severity(self) -> str:
        return ADVERSE_CODES.get(self.weather_code, ("clear", "info", 0))[1]

    @property
    def expected_delay_minutes(self) -> int:
        return ADVERSE_CODES.get(self.weather_code, ("clear", "info", 0))[2]


class OpenMeteoClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.open_meteo_base_url).rstrip("/")

    async def current(
        self, points: list[tuple[float, float]]
    ) -> list[WeatherObservation]:
        """Fetch current conditions for up to a handful of points.

        Open-Meteo accepts comma-separated coordinate lists, so one request
        covers a whole fleet's operating area rather than one per vehicle.
        """
        if not points:
            return []

        params = {
            "latitude": ",".join(f"{lat:.4f}" for lat, _ in points),
            "longitude": ",".join(f"{lng:.4f}" for _, lng in points),
            "current": "temperature_2m,precipitation,weather_code,wind_speed_10m",
            "wind_speed_unit": "kmh",
        }

        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                response = await client.get(f"{self.base_url}/forecast", params=params)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            # Weather is an enhancement, not a dependency: a failed fetch
            # leaves the map without an overlay, it does not break tracking.
            logger.warning("Open-Meteo request failed: %s", exc)
            return []

        body = response.json()
        # A single point returns an object; several return a list.
        entries = body if isinstance(body, list) else [body]

        observations: list[WeatherObservation] = []
        for entry in entries:
            current = entry.get("current") or {}
            observations.append(
                WeatherObservation(
                    latitude=float(entry.get("latitude", 0.0)),
                    longitude=float(entry.get("longitude", 0.0)),
                    weather_code=int(current.get("weather_code", 0)),
                    temperature_c=current.get("temperature_2m"),
                    wind_kph=current.get("wind_speed_10m"),
                    precipitation_mm=current.get("precipitation"),
                    observed_at=str(current.get("time", "")),
                )
            )
        return observations


_client: OpenMeteoClient | None = None


def get_weather_client() -> OpenMeteoClient:
    global _client
    if _client is None:
        _client = OpenMeteoClient()
    return _client


def set_weather_client(client: OpenMeteoClient) -> None:
    global _client
    _client = client
