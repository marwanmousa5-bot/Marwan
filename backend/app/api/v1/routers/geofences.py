"""Geofences and Places."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_or_404
from app.auth.deps import Principal, require_operator, require_tenant
from app.core.enums import GeofenceTrigger, GeofenceType, PlaceCategory
from app.db.base import get_session
from app.models import Alert, Geofence, GeofenceState, Place, Vehicle
from app.schemas.common import Message
from app.services import audit, geofencing

router = APIRouter()


class GeofenceIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    type: GeofenceType = GeofenceType.POLYGON
    trigger: GeofenceTrigger = GeofenceTrigger.BOTH
    colour: str = "#1E90FF"
    polygon: list[list[float]] | None = None
    centre_lat: float | None = None
    centre_lon: float | None = None
    radius_m: float | None = None
    vehicle_ids: list[uuid.UUID] = Field(default_factory=list)
    is_restricted: bool = False
    is_active: bool = True
    description: str | None = None

    @model_validator(mode="after")
    def check_geometry(self):
        if self.type == GeofenceType.POLYGON:
            if not self.polygon or len(self.polygon) < 3:
                raise ValueError("A polygon geofence needs at least three points.")
        else:
            if self.centre_lat is None or self.centre_lon is None or not self.radius_m:
                raise ValueError("A circular geofence needs a centre and a radius.")
        return self


@router.get("")
async def list_geofences(principal: Principal = Depends(require_tenant),
                         session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    rows = (await session.execute(
        select(Geofence).where(Geofence.organization_id == org_id)
        .order_by(Geofence.name))).scalars().all()
    since = datetime.now(timezone.utc) - timedelta(days=7)
    counts = dict((await session.execute(
        select(Alert.geofence_id, func.count()).where(
            Alert.organization_id == org_id, Alert.geofence_id.isnot(None),
            Alert.triggered_at >= since).group_by(Alert.geofence_id))).all())
    inside = dict((await session.execute(
        select(GeofenceState.geofence_id, func.count()).where(
            GeofenceState.organization_id == org_id,
            GeofenceState.inside.is_(True)).group_by(GeofenceState.geofence_id))).all())
    return [{
        "id": str(g.id), "name": g.name, "type": g.type, "trigger": g.trigger,
        "colour": g.colour, "polygon": g.polygon, "centre_lat": g.centre_lat,
        "centre_lon": g.centre_lon, "radius_m": g.radius_m,
        "vehicle_ids": [str(v) for v in (g.vehicle_ids or [])],
        "scope": "All vehicles" if not g.vehicle_ids
        else f"{len(g.vehicle_ids)} vehicles",
        "is_active": g.is_active, "is_restricted": g.is_restricted,
        "description": g.description,
        "area_km2": geofencing.area_km2(g),
        "events_7d": counts.get(g.id, 0),
        "vehicles_inside": inside.get(g.id, 0),
    } for g in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_geofence(payload: GeofenceIn,
                          principal: Principal = Depends(require_operator),
                          session: AsyncSession = Depends(get_session)):
    org_id = principal.org_id
    data = payload.model_dump()
    data["vehicle_ids"] = [str(v) for v in data["vehicle_ids"]]
    fence = Geofence(organization_id=org_id, **data)
    session.add(fence)
    await session.flush()
    await audit.record(session, action="geofence.created", organization_id=org_id,
                       actor=principal.user, entity_type="geofence", entity_id=fence.id,
                       entity_label=fence.name,
                       summary=f"Geofence {fence.name} created "
                               f"({geofencing.area_km2(fence)} km²)")
    await session.commit()
    return {"id": str(fence.id), "name": fence.name,
            "area_km2": geofencing.area_km2(fence)}


class GeofenceUpdate(BaseModel):
    name: str | None = None
    trigger: GeofenceTrigger | None = None
    colour: str | None = None
    polygon: list[list[float]] | None = None
    centre_lat: float | None = None
    centre_lon: float | None = None
    radius_m: float | None = None
    vehicle_ids: list[uuid.UUID] | None = None
    is_restricted: bool | None = None
    is_active: bool | None = None
    description: str | None = None


@router.patch("/{geofence_id}")
async def update_geofence(geofence_id: uuid.UUID, payload: GeofenceUpdate,
                          principal: Principal = Depends(require_operator),
                          session: AsyncSession = Depends(get_session)):
    fence: Geofence = await get_or_404(session, Geofence, geofence_id, principal.org_id,
                                       "Geofence")
    fields = ["name", "trigger", "is_active", "is_restricted", "radius_m"]
    before = audit.snapshot(fence, fields)
    changes = payload.model_dump(exclude_unset=True)
    if "vehicle_ids" in changes and changes["vehicle_ids"] is not None:
        changes["vehicle_ids"] = [str(v) for v in changes["vehicle_ids"]]
    for k, v in changes.items():
        setattr(fence, k, v)
    await audit.record(session, action="geofence.updated",
                       organization_id=principal.org_id, actor=principal.user,
                       entity_type="geofence", entity_id=fence.id,
                       entity_label=fence.name, before=before,
                       after=audit.snapshot(fence, fields),
                       summary=f"Geofence {fence.name} updated")
    await session.commit()
    return {"id": str(fence.id), "updated": list(changes)}


@router.delete("/{geofence_id}", response_model=Message)
async def delete_geofence(geofence_id: uuid.UUID,
                          principal: Principal = Depends(require_operator),
                          session: AsyncSession = Depends(get_session)):
    fence: Geofence = await get_or_404(session, Geofence, geofence_id, principal.org_id,
                                       "Geofence")
    name = fence.name
    await session.delete(fence)
    await audit.record(session, action="geofence.deleted",
                       organization_id=principal.org_id, actor=principal.user,
                       entity_type="geofence", entity_id=geofence_id, entity_label=name,
                       summary=f"Geofence {name} deleted")
    await session.commit()
    return Message(detail=f"Geofence “{name}” deleted. Its rules no longer apply.")


# --- places ----------------------------------------------------------------
class PlaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    category: PlaceCategory = PlaceCategory.CUSTOMER_SITE
    lat: float
    lon: float
    address: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    notes: str | None = None


@router.get("/places/list")
async def list_places(category: str | None = None, q: str | None = None,
                      principal: Principal = Depends(require_tenant),
                      session: AsyncSession = Depends(get_session)):
    stmt = select(Place).where(Place.organization_id == principal.org_id)
    if category:
        stmt = stmt.where(Place.category.in_(category.split(",")))
    if q:
        stmt = stmt.where(Place.name.ilike(f"%{q.strip()}%"))
    rows = (await session.execute(stmt.order_by(Place.name))).scalars().all()
    return [{"id": str(p.id), "name": p.name, "category": p.category, "lat": p.lat,
             "lon": p.lon, "address": p.address, "contact_name": p.contact_name,
             "contact_phone": p.contact_phone, "notes": p.notes,
             "is_active": p.is_active} for p in rows]


@router.post("/places/list", status_code=status.HTTP_201_CREATED)
async def create_place(payload: PlaceIn,
                       principal: Principal = Depends(require_operator),
                       session: AsyncSession = Depends(get_session)):
    place = Place(organization_id=principal.org_id, **payload.model_dump())
    session.add(place)
    await session.flush()
    await audit.record(session, action="place.created", organization_id=principal.org_id,
                       actor=principal.user, entity_type="place", entity_id=place.id,
                       entity_label=place.name, summary=f"Place {place.name} created")
    await session.commit()
    return {"id": str(place.id), "name": place.name}


class PlaceUpdate(BaseModel):
    name: str | None = None
    category: PlaceCategory | None = None
    lat: float | None = None
    lon: float | None = None
    address: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    notes: str | None = None
    is_active: bool | None = None


@router.patch("/places/{place_id}")
async def update_place(place_id: uuid.UUID, payload: PlaceUpdate,
                       principal: Principal = Depends(require_operator),
                       session: AsyncSession = Depends(get_session)):
    place: Place = await get_or_404(session, Place, place_id, principal.org_id, "Place")
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(place, k, v)
    await audit.record(session, action="place.updated", organization_id=principal.org_id,
                       actor=principal.user, entity_type="place", entity_id=place.id,
                       entity_label=place.name, summary=f"Place {place.name} updated")
    await session.commit()
    return {"id": str(place.id), "updated": list(changes)}


@router.delete("/places/{place_id}", response_model=Message)
async def delete_place(place_id: uuid.UUID,
                       principal: Principal = Depends(require_operator),
                       session: AsyncSession = Depends(get_session)):
    place: Place = await get_or_404(session, Place, place_id, principal.org_id, "Place")
    name = place.name
    place.is_active = False  # keep history intact; hide it from pickers
    await audit.record(session, action="place.deactivated",
                       organization_id=principal.org_id, actor=principal.user,
                       entity_type="place", entity_id=place.id, entity_label=name,
                       summary=f"Place {name} deactivated")
    await session.commit()
    return Message(detail=f"“{name}” has been deactivated and hidden from new tasks.")
