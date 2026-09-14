"""Self-hosted map surface: style, vector tiles, glyphs, geocoding, routing."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from app.auth.deps import Principal, get_principal, require_tenant
from app.geo.basemap import DATA_DIR, build_style, gazetteer, provider_descriptor, tiles
from app.routing.engine import get_router
from app.services import routes as route_svc

router = APIRouter()


def _base(request: Request) -> str:
    return str(request.url_for("get_style")).rsplit("/style.json", 1)[0]


@router.get("/config")
async def map_config(request: Request):
    """Which map provider the client should use. Public so the login page can theme."""
    return provider_descriptor(_base(request))


@router.get("/style.json", name="get_style")
async def get_style(request: Request, theme: str = Query("light", pattern="^(light|dark)$")):
    if not tiles().available:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Basemap tiles are not built. Run scripts/build_basemap.py.")
    return build_style(_base(request), theme)


@router.get("/tiles/{z}/{x}/{y}.pbf")
async def get_tile(z: int, x: int, y: int):
    if not (0 <= z <= 22):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Zoom level out of range.")
    blob = tiles().tile(z, x, y)
    if blob is None:
        # An empty 204 is the correct answer for "no data here", not an error.
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return Response(content=blob, media_type="application/x-protobuf",
                    headers={"Cache-Control": "public, max-age=86400",
                             "Content-Encoding": "identity"})


@router.get("/fonts/{fontstack}/{rng}.pbf")
async def get_glyphs(fontstack: str, rng: str):
    """SDF glyph ranges. Falls back to the regular weight for unknown stacks."""
    stack = fontstack.split(",")[0].strip()
    base = os.path.join(DATA_DIR, "fonts", "glyphs")
    path = os.path.join(base, stack, f"{rng}.pbf")
    if not os.path.exists(path):
        path = os.path.join(base, "Noto Sans Regular", f"{rng}.pbf")
    if not os.path.exists(path):
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    with open(path, "rb") as f:
        return Response(content=f.read(), media_type="application/x-protobuf",
                        headers={"Cache-Control": "public, max-age=604800"})


@router.get("/geocode")
async def geocode(q: str = Query(min_length=2, max_length=80), limit: int = Query(8, le=25),
                  principal: Principal = Depends(get_principal)):
    return {"query": q, "results": gazetteer().search(q, limit)}


@router.get("/reverse")
async def reverse(lat: float, lon: float, principal: Principal = Depends(get_principal)):
    return {"lat": lat, "lon": lon, "address": gazetteer().reverse(lon, lat),
            "street": get_router().snap(lon, lat)[2]}


class RouteRequest(BaseModel):
    waypoints: list[list[float]] = Field(min_length=2,
                                         description="[[lon,lat], ...] in order")
    avoid_edges: list[int] = Field(default_factory=list)


@router.post("/route")
async def compute_route(payload: RouteRequest, principal: Principal = Depends(require_tenant)):
    """Point-to-point or multi-stop routing on the real street network."""
    pts = [(float(p[0]), float(p[1])) for p in payload.waypoints]
    result = route_svc.calculate(pts, payload.avoid_edges)
    if not result.ok:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, result.message)
    return result.as_dict()


class OptimiseRequest(BaseModel):
    origin: list[float]
    destination: list[float]
    stops: list[dict]


@router.post("/optimize")
async def optimise_route(payload: OptimiseRequest,
                         principal: Principal = Depends(require_tenant)):
    """Preview a better stop order. Never applied without explicit confirmation."""
    if len(payload.stops) < 2:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Add at least two stops before optimising.")
    result = route_svc.optimise(
        (payload.origin[0], payload.origin[1]), payload.stops,
        (payload.destination[0], payload.destination[1]),
    )
    result["stops"] = [payload.stops[i] for i in result["order"]]
    return result
