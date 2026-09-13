"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import FleetBeatError

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("fleetbeat")

DESCRIPTION = """
FleetBeat - the live pulse of your fleet.

Multi-tenant fleet management API consumed by the Next.js web dashboard and
the Flutter driver app.

**There is no public registration.** Organizations and their first
administrator are created exclusively through the Platform Admin Console
(`/api/v1/platform-admin/*`, `super_admin` role only). An Org Admin may then
invite dispatchers and drivers within their own organization.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s (%s)", settings.app_name, settings.environment)
    yield
    from app.db.session import engine

    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION,
    version="0.1.0",
    openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Tag every request so audit entries and logs can be correlated."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response


@app.exception_handler(FleetBeatError)
async def fleetbeat_error_handler(request: Request, exc: FleetBeatError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "detail": exc.message},
        headers=(
            {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        ),
    )


app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", tags=["health"], summary="Service banner")
async def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "tagline": "The live pulse of your fleet.",
        "docs": "/docs",
        "api": settings.api_v1_prefix,
    }
