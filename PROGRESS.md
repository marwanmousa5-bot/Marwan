# FleetBeat — build progress

A commercial fleet management and operations platform. This file records what is
built, what it does, and what is still outstanding.

## What you can use right now

`web-demo/` is a complete, browsable FleetBeat. It runs the whole product in the
browser against real data so the system can be explored without deploying
anything:

- **Real geography.** An OpenStreetMap extract of central Helsinki supplies the
  basemap, every street name, the buildings, the water, and 1,400 real named
  places. Routing is A* over the extracted street graph (1,046 junctions,
  1,880 directed edges). Nothing is drawn by hand — see `backend/data/SOURCE.md`.
- **Real state.** A seeded tenant (Kaiku Logistics Oy) with 14 vehicles,
  14 drivers, four months of operating history, and a live telemetry simulation
  that drives vehicles along routed paths, opens and closes trips, evaluates
  geofences and raises alerts.
- **Real actions.** Every control changes state, and the change ripples. Completing
  a job writes the proof of delivery, closes the SLA and moves the dispatcher's
  board. Finishing a work order writes a maintenance record and a cost record and
  resets the schedule. Changing a safety weight in Settings re-scores every driver.

Build and serve it:

```
node web-demo/build.mjs
python3 -m http.server 8099 --directory web-demo/public
```

### Modules

| Surface | State | Notes |
| --- | --- | --- |
| Live Tracking | done | Map-dominant command centre, fleet panel, route editing, playback |
| Alerts | done | Lifecycle, dedupe, cooldown, escalation ladders, bulk actions |
| Dispatch | done | Exception queue, assignment preview with conflicts |
| Tasks | done | Full state machine, POD, failure reasons, SLA |
| Vehicles | done | Vehicle 360, assignment, retirement, lifecycle |
| Drivers | done | Driver 360, status, duty hours, documents |
| Maintenance | done | Schedules, work orders, parts, workshop impact |
| Trips & History | done | Replay against the recorded track |
| Geofences & Places | done | Draw, edit, dwell rules |
| Fuel & Energy | done | Consumption between full fills, EV charging |
| Compliance | done | Documents, expiry ladders, renewal |
| Incidents | done | Report, investigate, convert to work order |
| Costs & TCO | done | Operating cost, cost per km, book value |
| Analytics | done | Five workspaces, CSV export, period reports |
| Safety & Rewards | done | Transparent scoring, coaching, points, badges |
| Sustainability | done | Emissions from measured fuel, electrification cases |
| Fleet Intelligence | done | Recommendations, assistant, anomalies, reports |
| Settings | done | Every figure the rest of the product calculates from |
| Driver app | done | The phone view, driving the same state machine |
| Platform admin | done | Tenants, device health, background jobs, isolation |

## Backend

`backend/` holds the production shape of the same system: FastAPI, SQLAlchemy 2.0
async, PostgreSQL, Alembic, JWT access/refresh with argon2 hashing, RBAC, an
append-only audit log, and `organization_id` on every tenant-scoped table.

- **Done:** 42 tables and migrations; auth with refresh rotation and device
  fingerprinting; tenancy and RBAC dependencies; the offline basemap, tile store,
  gazetteer and routing engine; the alert, task, maintenance, geofence, scoring and
  simulation services; routers for auth, tracking, tasks, dispatch, alerts,
  vehicles, drivers, maintenance, trips, geofences, fuel, compliance, incidents,
  map data and the WebSocket feed.
- **Outstanding:** routers for AI, analytics, costs, notifications, org, search,
  the driver app and platform admin; Celery workers and beat schedule; the Next.js
  client; the Flutter driver app; the pytest suite; `docker-compose`.

## Decisions worth knowing

- **Why an in-browser engine.** The environment this was built in blocks outbound
  network access, including map tiles and OSRM. Rather than fake a map, the OSM
  extract was parsed locally into vector tiles, a routing graph and SDF glyphs
  generated from Noto Sans, so the product keeps a real map with no external
  dependency. `RoutingProvider` still has an OSRM implementation behind it.
- **Why the fleet is a courier operation.** The bundled extract covers about
  1.6 km by 1 km of central Helsinki. A long-haul fleet in that footprint would be
  a lie, so the seeded tenant is a last-mile courier doing many short drops a day,
  which is what actually operates there.
- **Why utilisation is on-duty time.** A last-mile vehicle spends most of its shift
  parked at a drop. Counting only driving minutes reports 3% for a van that was out
  for eight hours, so the metric measures the time the vehicle was out working and
  says so on the page.
