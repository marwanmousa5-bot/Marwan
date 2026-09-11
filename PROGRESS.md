# FleetBeat — build progress

Section references point at the master product spec.

---

## Phase 1 — Foundation ✅

### What was built

**Docker & environment**
- `docker-compose.yml` brings up Postgres 16, Redis 7, the API (migrated and
  seeded on start), the Celery worker, Celery beat and the Next.js dashboard
  with a single `docker compose up --build`.
- OSRM sits behind a `routing` Compose profile because it needs a
  pre-processed OpenStreetMap extract; including it in the default stack would
  make a first `up` block on a multi-gigabyte download. Setup is documented in
  `infra/osrm/README.md`.
- All configuration via `.env` (`.env.example` committed). No secrets in code.

**Database schema (Sections 4 and 4a — all entities, not just Phase 1's)**
- 39 tables in one baseline Alembic migration (`0001_initial`), covering
  organizations and per-org settings, users/auth/audit, vehicles, drivers plus
  the shared driver-event stream, GPS device inventory, trips and persisted
  position history, geofences/POIs, maintenance, fuel, routing, dispatch
  tasks, compliance, incidents, alerts, weather zones and the AI layer.
- Three FK cycles (vehicle↔driver, route↔task, trip↔task) are broken with
  `use_alter` and created as post-table `ALTER TABLE` statements.

**Multi-tenancy (Section 3)**
- Shared database / shared schema, `organization_id` on every tenant-scoped
  table via `TenantScopedMixin`.
- `app/core/tenancy.py::TenantScope` is the single scoping mechanism.
  `scope.select(Model)` pre-filters by Organization and *refuses* to run
  against a model without a tenant column. `scope.assign(obj)` stamps new rows.
- Scope is derived only from the authenticated principal's JWT. A client-sent
  `organization_id` is ignored — there is a test for exactly that.
- Cross-tenant reads return **404, not 403**, so probing cannot confirm that a
  row exists in another tenant.

**Auth & RBAC (Section 3, Section 9)**
- JWT access + refresh, argon2id hashing, server-side refresh-token registry
  with rotation and replay rejection. Password change revokes all sessions.
- Roles `super_admin` / `org_admin` / `dispatcher` / `driver`, enforced by
  FastAPI dependencies on every route.
- **No public registration endpoint exists at any path.** A test asserts this
  against the generated OpenAPI schema, not just against known routes.
- Account lockout after 5 consecutive failures; login bookkeeping is committed
  before the failure is raised so the evidence survives the request.

**Platform Admin Console API (Section 4a)**
- Organization provisioning: creates the Organization, its settings, its
  default alert rules and its first `org_admin` in one call, returning a
  one-time activation link.
- View / edit / suspend / reactivate an Organization. Suspension immediately
  blocks that tenant's logins.
- Audited impersonation: mints a token for the Organization's admin carrying
  an `imp` claim; every event is written to the audit log.
- Platform-wide counts and an organization list with health indicators
  (vehicles, active devices, users, last login).
- Activation-link re-issue for a customer user.

**Super-admin seed (Section 4a)**
- `python -m app.seed_admin` creates exactly one `super_admin`
  (`Marwan.mousa5@gmail.com`). Password comes from
  `SUPERADMIN_INITIAL_PASSWORD` if set, else a random one is generated and
  printed once, with `must_change_password` set. Nothing hardcoded. Idempotent.

**Audit log (Section 4 item 18) — stood up from day one**
- Append-only `audit_logs` with actor, impersonator, IP, user agent, request
  id and a compact `{before, after}` diff of changed fields only.
- Already wired into logins (success and failure), password set/change,
  organization lifecycle, user invites, vehicle and driver changes, and
  impersonation.
- No update or delete surface anywhere in the API — a test enforces that.

**Vehicle & driver CRUD**
- Full registry with search, filtering and pagination. Vehicles are *retired*,
  never hard-deleted, so history survives.
- Vehicles expose `is_tracked`, `live_status` and a **read-only** device view,
  so "Not Tracked" is visible to customers from the start.
- Drivers can optionally be created with a mobile-app login, returning an
  activation link.
- Org settings endpoint exposes Org-Admin-tunable point weights, alert
  thresholds, CO2 factors, the leaderboard visibility flag and the
  maintenance auto-book flag (default OFF). Dict-valued settings merge on
  PATCH rather than being replaced wholesale.

**Web dashboard (Next.js 14, App Router, TypeScript, Tailwind)**
- Login (with an explicit "accounts are created by our team" note instead of a
  dead-end sign-up link) and the one-time activation flow.
- Customer console at `/dashboard`: Live Tracking landing page with the KPI
  strip and vehicle roster already wired to the API, plus vehicle and driver
  management screens.
- **Platform Admin Console at `/platform-admin`**, role-gated and given a
  deliberately different visual identity — light "internal tool" chrome with a
  standing FLEETBEAT INTERNAL banner — so the two consoles can never be
  confused. Organization list, provisioning flow with copyable activation
  link, suspend/reactivate and one-click impersonation.
- All copy lives in `lib/strings.ts`; no i18n machinery (Section 9), but
  extraction later is mechanical.
- Heartbeat/pulse motif used for loaders and the alert status dot only, so the
  motion stays meaningful.

**Flutter driver app**
- Login with a driver-only role check, session restore with transparent token
  refresh, and the "My Tasks" home shell.
- Two widget tests, including one asserting no sign-up affordance exists.

**Skeletons for later phases**
- `app/simulation/provider.py` — the `LocationProvider` abstraction with
  `PositionUpdate` / `TelemetryEvent`, so swapping simulation for real GPS
  hardware means one new class (Section 6).
- `app/realtime/hub.py` — tenant-keyed WebSocket fan-out; a broadcast cannot
  cross an Organization boundary.
- `app/ai/client.py` — Claude API wrapper with an offline fallback so the
  system builds and tests without an API key.
- `app/ai/stubs.py` — explicit `NotImplementedError` stubs for dashcam,
  fleet-sizing and fraud detection, carrying the privacy-by-design design note
  from Section 5 item 7.
- `app/worker.py` + `app/tasks.py` — Celery app with the full beat schedule
  declared up front and task bodies filled in by their owning phase.

### Tested

- **46 backend tests, all passing**, no external services needed (in-memory
  SQLite).
  - `test_tenant_isolation.py` (13) — the mandatory Section 7 proof: list,
    read-by-id, update, delete, foreign-FK injection, client-supplied
    `organization_id`, cross-tenant user administration, audit attribution.
  - `test_auth.py` (11) — login, lockout, refresh rotation and replay, RBAC
    per role, and the no-public-registration assertion.
  - `test_platform_admin.py` (12) — provisioning, activation single-use, weak
    password rejection, duplicate email, suspension blocking logins,
    impersonation + its audit record, health indicators, invite restrictions.
  - `test_fleet_crud.py` (10) — vehicle/driver lifecycles, search, duplicate
    plates, configurable point weights, audit diffs, append-only audit surface.
- `ruff check .` clean.
- `npm run typecheck` and `npm run build` clean (9 routes).
- The baseline migration was validated by rendering its full Postgres DDL
  offline (`alembic upgrade head --sql`) — 40 `CREATE TABLE` statements in
  dependency order plus the 3 deferred FKs.

### Decisions made that the spec left open

1. **Celery + Redis over APScheduler.** Several later phases are genuinely
   job-shaped and need retries, a result backend and horizontal workers (AI
   Copilot passes, weekly reports, maintenance scans, weather refresh).
   APScheduler would have to be replaced the moment any of those needs to
   survive a restart. Redis is in the stack anyway for WebSocket fan-out.
   **However**, the high-frequency GPS tick is deliberately *not* a Celery
   task — dispatching a job every few seconds per vehicle costs more in broker
   round-trips than the work itself. It runs as one long-lived asyncio loop
   behind the same `LocationProvider` interface.
2. **No PostGIS.** Geofence geometry is stored as JSON (`{coordinates}` for
   polygons, `{center, radius_m}` for circles) and evaluated in Python with
   Shapely. This keeps docker-compose on a stock `postgres` image. Only that
   one column changes if PostGIS is adopted later.
3. **argon2id directly, not via passlib.** passlib is unmaintained and its
   bcrypt backend breaks against bcrypt ≥ 4.
4. **Enums stored as strings, not native PG enums**, so adding a value is a
   code change rather than a migration.
5. **Cross-tenant misses return 404.** Chosen over 403 so existence is not
   leaked.
6. **Vehicles are retired, not deleted.** Trips, costs and incidents reference
   them; a hard delete would orphan history.
7. **Tokens in `localStorage` on web.** The API is a separate origin and the
   Flutter app consumes identical endpoints, so a bearer header was the
   straightforward choice. Hardening path: move the refresh token to an
   httpOnly cookie behind a same-site Next.js proxy route — no API contract
   changes.
8. **A `points_ledger_entries` table**, not just a balance column, so a
   driver's score is explainable line by line when they dispute it.
9. **`Device` is deliberately not tenant-scoped** in the `TenantScopeMixin`
   sense: it is platform inventory that is *assigned* to an Organization.
   Customers reach it only through the read-only view on their own vehicle.
10. **Super admins have no tenant scope at all.** Hitting a customer endpoint
    as `super_admin` returns 403 with an explanation; they must impersonate,
    which is audited. This makes "platform staff read customer data" an event
    on the record rather than an invisible capability.
11. **Only the alert status pulses.** The heartbeat motif is brand-correct but
    ambient motion on every row would make the one state that needs attention
    invisible.

### Open questions for the product owner

1. **Operating region for OSRM.** The routing container needs a specific
   OpenStreetMap extract. Which country/region should ship as the default?
2. **Distance and currency defaults.** Currently km and USD per Organization.
   Should these follow from the chosen timezone/region at provisioning time?
3. **Driver profile vs. driver login.** A driver profile can exist without a
   login (for a driver who does not use the app). Is that right, or should
   every driver always get mobile access?
4. **Suspending an Organization currently blocks logins immediately** but does
   not stop the simulation/tracking of their vehicles. Should a suspension
   freeze data collection too, or keep it running for a grace period?
5. **Activation link lifetime** is 72 hours. Confirm that suits the onboarding
   pace, since links are delivered manually.

### Not built in this phase (by design)

Device management UI, the live map, WebSocket feed, trip playback, map tools,
weather overlay, maintenance, fuel, compliance and alert *evaluation* are
Phase 2. The Task Manager and the full driver app are Phase 3. Scoring,
points, analytics and sustainability are Phase 4. The Claude-backed assistant,
copilots and reporting are Phase 5. Auto-rerouting, the audit-log UI and
suspicious-login alerting UI are Phase 6.

### Known gaps in verification

The Flutter app could not be compiled or its tests run in this environment —
no Flutter SDK is installed here. The Dart code is written against Flutter
3.27+ (`Color.withValues` requires it, and the constraint is pinned in
`pubspec.yaml`), but it has not been executed. `android/` and `ios/` platform
folders are not committed; run `flutter create .` in `mobile/` once before the
first build.

---

## Phase 2 — Core Operations ⏳ Not started

Device Management (platform + read-only customer view), OSRM wiring, the GPS
simulation engine persisting full position history per Trip, the Live Tracking
home page with WebSocket updates, Trip History Playback, map tools (geofence
drawing, POIs, clustering), the weather overlay, maintenance, fuel, compliance
and the alerts engine.
