"""Map tools: geofences and points of interest (Section 4d).

Geofences are drawn directly on the live map; this API takes the resulting
geometry. There is deliberately no coordinate-entry-only creation path in the
UI, but the API accepts geometry generically so an importer could use it later.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    Principal,
    get_tenant_scope,
    require_dashboard_user,
    require_org_admin,
)
from app.core.tenancy import TenantScope
from app.db.session import get_db
from app.models.enums import AuditAction, PoiCategory
from app.models.routing import RoadClosure
from app.models.tracking import Geofence, PointOfInterest
from app.models.vehicle import Vehicle
from app.schemas.common import Message
from app.schemas.tracking import (
    GeofenceCreate,
    GeofenceOut,
    GeofenceUpdate,
    PoiCreate,
    PoiOut,
    PoiUpdate,
    RerouteProposalOut,
    RoadClosureCreate,
    RoadClosureOut,
    RoadClosureUpdate,
)
from app.services import audit, geo, rerouting

router = APIRouter(tags=["map-tools"])


def _geofence_out(fence: Geofence) -> GeofenceOut:
    out = GeofenceOut.model_validate(fence)
    out.vehicle_ids = [uuid.UUID(str(v)) for v in (fence.vehicle_ids or [])]
    return out


async def _validate_vehicle_ids(
    db: AsyncSession, scope: TenantScope, vehicle_ids: list[uuid.UUID]
) -> list[str]:
    """A geofence may only be scoped to vehicles in the caller's own tenant."""
    if not vehicle_ids:
        return []
    result = await db.execute(
        scope.select(Vehicle).where(Vehicle.id.in_(vehicle_ids))
    )
    found = {v.id for v in result.scalars().all()}
    missing = set(vehicle_ids) - found
    if missing:
        from app.core.errors import NotFoundError

        raise NotFoundError("One or more selected vehicles were not found")
    return [str(v) for v in vehicle_ids]


# ---------------------------------------------------------------------------
# Geofences
# ---------------------------------------------------------------------------

@router.get("/geofences", response_model=list[GeofenceOut], summary="List geofences")
async def list_geofences(
    active_only: bool = Query(default=False),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[GeofenceOut]:
    stmt = scope.select(Geofence)
    if active_only:
        stmt = stmt.where(Geofence.is_active.is_(True))
    result = await db.execute(stmt.order_by(Geofence.name))
    return [_geofence_out(f) for f in result.scalars().all()]


@router.post(
    "/geofences",
    response_model=GeofenceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a geofence drawn on the map",
)
async def create_geofence(
    payload: GeofenceCreate,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> GeofenceOut:
    geometry = geo.validate_geometry(payload.shape, payload.geometry)
    vehicle_ids = await _validate_vehicle_ids(db, scope, payload.vehicle_ids)

    fence = Geofence(
        name=payload.name,
        shape=payload.shape,
        geometry=geometry,
        color=payload.color,
        trigger=payload.trigger,
        is_active=payload.is_active,
        vehicle_ids=vehicle_ids,
        created_by_user_id=principal.user_id,
    )
    scope.assign(fence)
    db.add(fence)
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="geofence",
        entity_id=fence.id,
        summary=f"Geofence '{fence.name}' created ({fence.shape})",
        request=request,
    )
    return _geofence_out(fence)


@router.patch(
    "/geofences/{geofence_id}", response_model=GeofenceOut, summary="Update a geofence"
)
async def update_geofence(
    geofence_id: uuid.UUID,
    payload: GeofenceUpdate,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> GeofenceOut:
    fence = await scope.get_or_404(db, Geofence, geofence_id, label="Geofence")
    fields = ["name", "shape", "color", "trigger", "is_active"]
    before = audit.snapshot(fence, fields)

    data = payload.model_dump(exclude_unset=True)
    if "vehicle_ids" in data and data["vehicle_ids"] is not None:
        data["vehicle_ids"] = await _validate_vehicle_ids(
            db, scope, data["vehicle_ids"]
        )
    if "geometry" in data and data["geometry"] is not None:
        shape = data.get("shape") or fence.shape
        data["geometry"] = geo.validate_geometry(shape, data["geometry"])

    for key, value in data.items():
        setattr(fence, key, value)
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="geofence",
        entity_id=fence.id,
        summary=f"Geofence '{fence.name}' updated",
        changes=audit.diff(before, audit.snapshot(fence, fields)),
        request=request,
    )
    return _geofence_out(fence)


@router.delete(
    "/geofences/{geofence_id}", response_model=Message, summary="Delete a geofence"
)
async def delete_geofence(
    geofence_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_org_admin),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> Message:
    fence = await scope.get_or_404(db, Geofence, geofence_id, label="Geofence")
    name = fence.name
    await db.delete(fence)
    await audit.record(
        db,
        action=AuditAction.DELETE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="geofence",
        entity_id=geofence_id,
        summary=f"Geofence '{name}' deleted",
        request=request,
    )
    return Message(detail=f"Geofence '{name}' deleted")


# ---------------------------------------------------------------------------
# Points of interest
# ---------------------------------------------------------------------------

@router.get("/pois", response_model=list[PoiOut], summary="List points of interest")
async def list_pois(
    category: PoiCategory | None = Query(default=None),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[PoiOut]:
    stmt = scope.select(PointOfInterest)
    if category is not None:
        stmt = stmt.where(PointOfInterest.category == category)
    result = await db.execute(stmt.order_by(PointOfInterest.name))
    return [PoiOut.model_validate(p) for p in result.scalars().all()]


@router.post(
    "/pois",
    response_model=PoiOut,
    status_code=status.HTTP_201_CREATED,
    summary="Drop a point of interest",
)
async def create_poi(
    payload: PoiCreate,
    request: Request,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> PoiOut:
    poi = PointOfInterest(
        **payload.model_dump(), created_by_user_id=principal.user_id
    )
    scope.assign(poi)
    db.add(poi)
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="point_of_interest",
        entity_id=poi.id,
        summary=f"POI '{poi.name}' created ({poi.category})",
        request=request,
    )
    return PoiOut.model_validate(poi)


@router.patch("/pois/{poi_id}", response_model=PoiOut, summary="Update a POI")
async def update_poi(
    poi_id: uuid.UUID,
    payload: PoiUpdate,
    request: Request,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> PoiOut:
    poi = await scope.get_or_404(db, PointOfInterest, poi_id, label="Point of interest")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(poi, key, value)
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="point_of_interest",
        entity_id=poi.id,
        summary=f"POI '{poi.name}' updated",
        request=request,
    )
    return PoiOut.model_validate(poi)


@router.delete("/pois/{poi_id}", response_model=Message, summary="Delete a POI")
async def delete_poi(
    poi_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> Message:
    poi = await scope.get_or_404(db, PointOfInterest, poi_id, label="Point of interest")
    name = poi.name
    await db.delete(poi)
    await audit.record(
        db,
        action=AuditAction.DELETE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="point_of_interest",
        entity_id=poi_id,
        summary=f"POI '{name}' deleted",
        request=request,
    )
    return Message(detail=f"Point of interest '{name}' deleted")


# ---------------------------------------------------------------------------
# Road closures and Exception Auto-Rerouting (Section 4 item 8)
# ---------------------------------------------------------------------------

@router.get(
    "/road-closures",
    response_model=list[RoadClosureOut],
    summary="List road closures",
)
async def list_road_closures(
    include_inactive: bool = Query(default=False),
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[RoadClosureOut]:
    stmt = scope.select(RoadClosure)
    if not include_inactive:
        stmt = stmt.where(RoadClosure.is_active.is_(True))
    result = await db.execute(stmt.order_by(RoadClosure.created_at.desc()))
    return [RoadClosureOut.model_validate(c) for c in result.scalars().all()]


@router.post(
    "/road-closures",
    response_model=RoadClosureOut,
    status_code=status.HTTP_201_CREATED,
    summary="Flag a road closure",
)
async def create_road_closure(
    payload: RoadClosureCreate,
    request: Request,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> RoadClosureOut:
    closure = RoadClosure(
        **payload.model_dump(), created_by_user_id=principal.user_id
    )
    scope.assign(closure)
    db.add(closure)
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="road_closure",
        entity_id=closure.id,
        summary=f"Road closure '{closure.label}' flagged",
        request=request,
    )
    return RoadClosureOut.model_validate(closure)


@router.patch(
    "/road-closures/{closure_id}",
    response_model=RoadClosureOut,
    summary="Update or lift a road closure",
)
async def update_road_closure(
    closure_id: uuid.UUID,
    payload: RoadClosureUpdate,
    request: Request,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> RoadClosureOut:
    closure = await scope.get_or_404(db, RoadClosure, closure_id, label="Road closure")
    fields = ("label", "radius_m", "active_from", "active_until", "is_active")
    before = audit.snapshot(closure, fields)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(closure, key, value)
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="road_closure",
        entity_id=closure.id,
        summary=f"Road closure '{closure.label}' updated",
        changes=audit.diff(before, audit.snapshot(closure, fields)),
        request=request,
    )
    return RoadClosureOut.model_validate(closure)


@router.delete(
    "/road-closures/{closure_id}",
    response_model=Message,
    summary="Delete a road closure",
)
async def delete_road_closure(
    closure_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> Message:
    closure = await scope.get_or_404(db, RoadClosure, closure_id, label="Road closure")
    label = closure.label
    await db.delete(closure)
    await audit.record(
        db,
        action=AuditAction.DELETE,
        principal=principal,
        organization_id=scope.organization_id,
        entity_type="road_closure",
        entity_id=closure_id,
        summary=f"Road closure '{label}' deleted",
        request=request,
    )
    return Message(detail=f"Road closure '{label}' deleted")


@router.get(
    "/reroutes/proposals",
    response_model=list[RerouteProposalOut],
    summary="Active routes obstructed right now, with the alternative costed",
)
async def reroute_proposals(
    _: Principal = Depends(require_dashboard_user),
    scope: TenantScope = Depends(get_tenant_scope),
    db: AsyncSession = Depends(get_db),
) -> list[RerouteProposalOut]:
    """Read-only. Applying one goes through the Copilot's Apply step, which
    is the single confirmed, audited path that can move a running task onto a
    different route (Section 9)."""
    hits = await rerouting.detect(db, scope.organization_id)
    proposals = []
    for task, route, obstruction in hits[:10]:
        proposal = await rerouting.propose(
            db, scope, task=task, route=route, obstruction=obstruction
        )
        proposals.append(
            RerouteProposalOut(
                task_id=proposal.task_id,
                task_title=proposal.task_title,
                route_id=proposal.route_id,
                obstruction_kind=obstruction.kind,
                obstruction_id=obstruction.obstruction_id,
                obstruction_label=obstruction.label,
                added_km=proposal.added_km,
                added_minutes=proposal.added_minutes,
                new_distance_km=proposal.new_distance_km,
                new_eta=proposal.new_eta,
                routing_available=proposal.routing_available,
            )
        )
    return proposals
