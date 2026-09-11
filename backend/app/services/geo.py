"""Geospatial helpers.

Deliberately pure-Python: the geometry FleetBeat needs (distance, bearing,
dead-reckoning a point, and point-in-polygon/circle containment) is a few
dozen lines, and keeping it dependency-free means no PostGIS in the compose
stack and no binary wheels in the image. If geofence evaluation ever has to
run over millions of rows in the database rather than per-sample in Python,
that is the moment to reach for PostGIS - and only ``Geofence.geometry``
changes.
"""

from __future__ import annotations

import math
from typing import Any

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    return haversine_m(lat1, lng1, lat2, lng2) / 1000.0


def bearing_deg(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Initial bearing from point 1 to point 2, in degrees clockwise from north."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lambda = math.radians(lng2 - lng1)
    y = math.sin(d_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(
        d_lambda
    )
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def destination_point(
    lat: float, lng: float, bearing: float, distance_m: float
) -> tuple[float, float]:
    """Project a point along a bearing - used to advance a simulated vehicle."""
    angular = distance_m / EARTH_RADIUS_M
    theta = math.radians(bearing)
    phi1, lambda1 = math.radians(lat), math.radians(lng)

    phi2 = math.asin(
        math.sin(phi1) * math.cos(angular)
        + math.cos(phi1) * math.sin(angular) * math.cos(theta)
    )
    lambda2 = lambda1 + math.atan2(
        math.sin(theta) * math.sin(angular) * math.cos(phi1),
        math.cos(angular) - math.sin(phi1) * math.sin(phi2),
    )
    # Normalise longitude back into [-180, 180).
    return math.degrees(phi2), (math.degrees(lambda2) + 540.0) % 360.0 - 180.0


def point_in_polygon(lat: float, lng: float, coordinates: list[list[float]]) -> bool:
    """Ray-casting containment test.

    ``coordinates`` is GeoJSON-ordered ``[[lng, lat], ...]``. The ring may be
    open or closed; both are handled.
    """
    if len(coordinates) < 3:
        return False

    inside = False
    count = len(coordinates)
    j = count - 1
    for i in range(count):
        xi, yi = coordinates[i][0], coordinates[i][1]
        xj, yj = coordinates[j][0], coordinates[j][1]
        # Does the edge straddle the test point's latitude, and is the
        # crossing to the right of it?
        if (yi > lat) != (yj > lat):
            x_at_lat = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lng < x_at_lat:
                inside = not inside
        j = i
    return inside


def point_in_circle(
    lat: float, lng: float, center: list[float], radius_m: float
) -> bool:
    """``center`` is GeoJSON-ordered ``[lng, lat]``."""
    return haversine_m(lat, lng, center[1], center[0]) <= radius_m


def contains(geometry: dict[str, Any] | None, lat: float, lng: float) -> bool:
    """Containment against a stored geofence geometry of either shape."""
    if not geometry:
        return False
    if "coordinates" in geometry:
        return point_in_polygon(lat, lng, geometry["coordinates"])
    if "center" in geometry:
        return point_in_circle(
            lat, lng, geometry["center"], float(geometry.get("radius_m", 0))
        )
    return False


def bounding_box(
    points: list[tuple[float, float]],
) -> tuple[float, float, float, float] | None:
    """``(min_lat, min_lng, max_lat, max_lng)`` over ``(lat, lng)`` pairs."""
    if not points:
        return None
    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    return min(lats), min(lngs), max(lats), max(lngs)


def centroid(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    if not points:
        return None
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )


def validate_geometry(shape: str, geometry: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise a geofence geometry drawn on the map."""
    from app.core.errors import ValidationError

    if shape == "polygon":
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 3:
            raise ValidationError("A polygon geofence needs at least three points")
        cleaned: list[list[float]] = []
        for point in coordinates:
            if not isinstance(point, list | tuple) or len(point) < 2:
                raise ValidationError("Each polygon point must be [longitude, latitude]")
            lng, lat = float(point[0]), float(point[1])
            _assert_coordinate(lat, lng)
            cleaned.append([lng, lat])
        # Store the ring open; the renderer closes it.
        if len(cleaned) > 3 and cleaned[0] == cleaned[-1]:
            cleaned.pop()
        return {"coordinates": cleaned}

    if shape == "circle":
        center = geometry.get("center")
        radius = geometry.get("radius_m")
        if not isinstance(center, list | tuple) or len(center) < 2:
            raise ValidationError("A circle geofence needs a [longitude, latitude] center")
        lng, lat = float(center[0]), float(center[1])
        _assert_coordinate(lat, lng)
        if radius is None or float(radius) <= 0:
            raise ValidationError("A circle geofence needs a positive radius")
        return {"center": [lng, lat], "radius_m": float(radius)}

    raise ValidationError(f"Unsupported geofence shape: {shape}")


def _assert_coordinate(lat: float, lng: float) -> None:
    from app.core.errors import ValidationError

    if not -90.0 <= lat <= 90.0 or not -180.0 <= lng <= 180.0:
        raise ValidationError(f"Coordinate out of range: {lat}, {lng}")
