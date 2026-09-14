from fastapi import APIRouter

from app.api.v1.routers import (ai, alerts, analytics, auth, compliance, costs,
                                dispatch, drivers, driver_app, fuel, geofences,
                                incidents, maintenance, map_data, notifications,
                                org, platform_admin, search, tasks, tracking,
                                trips, vehicles, ws)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(map_data.router, prefix="/map", tags=["map"])
api_router.include_router(tracking.router, prefix="/tracking", tags=["live tracking"])
api_router.include_router(vehicles.router, prefix="/vehicles", tags=["vehicles"])
api_router.include_router(drivers.router, prefix="/drivers", tags=["drivers"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(dispatch.router, prefix="/dispatch", tags=["dispatch"])
api_router.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
api_router.include_router(maintenance.router, prefix="/maintenance", tags=["maintenance"])
api_router.include_router(trips.router, prefix="/trips", tags=["trips"])
api_router.include_router(geofences.router, prefix="/geofences", tags=["geofences"])
api_router.include_router(fuel.router, prefix="/fuel", tags=["fuel & energy"])
api_router.include_router(compliance.router, prefix="/compliance", tags=["compliance"])
api_router.include_router(incidents.router, prefix="/incidents", tags=["incidents"])
api_router.include_router(costs.router, prefix="/costs", tags=["costs & tco"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(org.router, prefix="/org", tags=["organization"])
api_router.include_router(driver_app.router, prefix="/driver", tags=["driver app"])
api_router.include_router(platform_admin.router, prefix="/platform", tags=["platform admin"])
api_router.include_router(ws.router, tags=["realtime"])
