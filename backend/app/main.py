"""FleetBeat API."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse

from app.api.v1 import api_router
from app.core.config import settings
from app.simulation.engine import engine as simulation

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-5s %(name)s %(message)s")
log = logging.getLogger("fleetbeat")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the map assets so the first request is not the one that pays for it.
    from app.geo.basemap import gazetteer, tiles
    from app.routing.engine import StreetGraph
    t0 = time.perf_counter()
    StreetGraph.instance()
    tiles()
    gazetteer()
    log.info("map assets loaded in %.0f ms", (time.perf_counter() - t0) * 1000)

    if settings.simulation_enabled:
        await simulation.start()
        log.info("GPS simulation started (tick=%.1fs, speed x%.0f)",
                 settings.simulation_tick_seconds, settings.simulation_speed_factor)
    yield
    await simulation.stop()


app = FastAPI(
    title="FleetBeat API",
    description="Fleet operations platform - the live pulse of your fleet.",
    version="1.0.0",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def timing(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Response-Time"] = f"{(time.perf_counter() - started) * 1000:.1f}ms"
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    """Never leak a stack trace; never say 'something went wrong' either."""
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "FleetBeat could not complete that request.",
            "hint": "The operation was not applied. Retry, and contact support if it persists.",
            "path": request.url.path,
        },
    )


app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/health", tags=["system"])
async def health():
    from app.geo.basemap import tiles
    return {
        "status": "ok",
        "environment": settings.environment,
        "simulation": simulation.running,
        "simulation_ticks": simulation.tick_count,
        "map_provider": settings.map_provider,
        "basemap": tiles().available,
        "routing_provider": settings.routing_provider,
    }
