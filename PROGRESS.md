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

Phase 1 shipped 46 backend tests. They still run, alongside everything added
since - see the consolidated **Testing** section below for the current
numbers and what each suite covers.

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

---

## Phase 2 — Core Operations ✅

### What was built

**GPS device management (Section 4a item 2)**
- Devices are *platform inventory*: `super_admin` adds them to stock, fits one
  to a customer's vehicle, and retires it. No customer-side role can add,
  remove or reassign a device at any endpoint (Section 9) — there is a test
  per customer role asserting 403.
- Customers see a read-only device view on their own vehicle, so "Not Tracked"
  is a visible state with an explanation rather than a silent gap.

**Simulated GPS feed (Section 6)**
- `app/simulation/` drives vehicles along real OSRM road geometry behind the
  `LocationProvider` interface, at a configurable tick. Only vehicles with an
  *active* device produce positions.
- Every sample is persisted to `position_samples` against a `Trip`; a trip
  closes itself after 5 minutes of no movement. Trip History Playback replays
  exactly what was recorded, not an interpolation.
- Telemetry events (speeding, harsh braking/acceleration/cornering) are
  emitted probabilistically and feed both alerts and driver scoring.

**Live Tracking (Section 4b)**
- WebSocket fan-out through a tenant-keyed hub — a broadcast cannot cross an
  Organization boundary — with a 15-second poll as the fallback when the
  socket is unavailable, and a visible connection state.
- MapLibre GL JS + OSM raster tiles, vehicle clustering, geofence drawing
  (polygon and circle), POIs, the weather overlay, a layers control, and a
  vehicle roster that stays in sync with the map in both directions.

**Alerts engine, maintenance, fuel, compliance**
- Rule-driven alert evaluation per Organization with tunable thresholds;
  geofence enter/exit, speeding, harsh driving, idling, weather and
  suspicious-login rules.
- Maintenance schedules, work orders and service records; fuel and energy
  logs with odometer-derived consumption; compliance documents with expiry
  tracking.

### Decisions made that the spec left open

1. **OSM raster tiles, not a vector basemap.** A vector style needs a key from
   a tile vendor; raster OSM needs nothing and keeps `docker compose up`
   working out of the box. The style lives in one file.
2. **MapLibre's built-in GeoJSON clustering** (Supercluster internally) rather
   than a second library, with `clusterProperties` accumulators so a cluster
   takes the worst status of its members — a cluster containing one alerting
   vehicle reads as alerting.
3. **No road-snapping in the feed.** Positions come from the route geometry
   already, so snapping would be a second approximation of something we know
   exactly.
4. **Momentary vs. standing alerts.** A speeding or harsh-driving alert
   describes an instant, not a condition, so it auto-resolves: it stays on the
   map for 15 minutes and is swept after 2 hours. A geofence breach or an
   expiring document stands until someone acts on it. Without this split the
   alert feed becomes unreadable within an hour of simulation.
5. **Odometer is derived from fill-ups**, not from the GPS distance, because
   that is what a fleet's own records do.

---

## Phase 3 — Task Manager and the driver app ✅

### What was built

- Dispatch tasks with a four-state lifecycle (assigned → accepted → en route →
  completed, plus cancelled) enforced by an explicit transition table rather
  than scattered `if` statements; an illegal transition is a 422 naming both
  states.
- Real routes and ETAs from OSRM on assignment, redrawn on reassignment. When
  OSRM is unreachable the task is still assignable and the UI says why no ETA
  is shown, rather than substituting a straight line.
- A dispatcher board (list and map views) with destination picking on the map.
- The full Flutter driver app: task list and detail, accept/start/complete
  with a completion note and photo, pre-trip inspection, incident reporting
  with photos, and push-notification plumbing behind the same
  `NotificationService` abstraction.
- Incident reporting and photo storage on the API side, shared by web and
  mobile.

### Decisions made that the spec left open

1. **A task carries its own route**, rather than routes being a separate
   planning object, so reassignment cannot leave a stale ETA behind.
2. **Completion requires a note or a photo.** A one-tap "done" with no
   evidence is what makes dispute resolution impossible later.
3. **Driver endpoints are a separate router** (`/driver/...`) with a
   driver-only dependency, so a dispatcher-shaped payload can never reach a
   driver-shaped handler.

---

## Phase 4 — Scoring, points, analytics and sustainability ✅

### What was built

- **Driver safety scores normalised by distance**: weighted violations per
  100 km, not raw counts, so a driver who drives twice as far is not punished
  for it. Below 250 km in the window the score is marked *provisional* rather
  than shown as fact.
- **Fatigue risk** from hours driven, night driving and break gaps, with the
  reasons listed alongside the level — never a bare number.
- **An append-only points ledger** with the weights read from
  `OrganizationSettings` (nothing hardcoded, per Section 9), badges, monthly
  reset and a leaderboard whose visibility to drivers is an Organization
  setting.
- **Analytics**: fleet KPIs, cost/TCO per vehicle, six-month trends, EV
  transition candidates, asset lifecycle and replacement flags, fuel and idle
  anomaly detection, maintenance forecasting, and CO2 from per-Organization
  emission factors.

### Decisions made that the spec left open

1. **Cost per km is withheld below 100 km** in the window. A rate computed
   over 12 km is noise presented as a number.
2. **EV candidacy is judged on a vehicle's worst day, not its average.** A van
   that averages 90 km/day but hits 400 km once a fortnight cannot do that day
   on a single charge, and the average hides exactly that.
3. **Anomaly z-scores exclude the sample being judged**, or a single large
   outlier inflates the standard deviation enough to hide itself.
4. **Charts are small multiples, one measure per plot.** Distance, cost, CO2
   and violations live on different scales, and a second y-axis is the easiest
   way for a dashboard to mislead.

---

## Phase 5 — Claude-backed assistant, copilots and reporting ✅

### What was built

- **One Claude client** (`app/ai/client.py`) targeting `claude-opus-5` with
  adaptive thinking and a JSON output schema, handling a refusal as a result
  rather than an exception, and falling back to a deterministic offline path
  when no API key is configured. The product is fully usable without a key.
- **Fleet Assistant**: the model only ever classifies the question against a
  fixed capability catalogue and fills a JSON schema. The data in the answer
  is fetched by tenant-scoped queries — the model never sees a row it was not
  handed, and never writes one.
- **Fleet Copilot** (Section 4e): rule-derived signals (late tasks, weather
  delays, unassigned work beside an idle driver, alert clusters, obstructed
  routes) ranked and phrased by the model. *Our* rules decide what is
  happening; the model only words it.
- **Maintenance Copilot**: proposes the quietest day inside each service's due
  window, and books it only when the Organization has explicitly enabled
  auto-booking (off by default — an auto-created work order costs real money).
- **Narrative reports** and CSV/PDF exports (the PDF writer is hand-rolled, no
  new dependency).

### The confirmation gate (Section 9)

Every state-changing AI path is two-step by construction: the model proposes,
the API returns a pending action with an expiry, and nothing is written until
a confirm call arrives **from the same user** before that expiry. The UI shows
this rather than hiding it — an action reply renders as a pending card with an
explicit Confirm button, and a Copilot card's Apply opens a second
confirmation inside the card. Tests cover the gate directly: an unconfirmed
intent writes nothing, another user's confirmation is rejected, an expired one
is refused, and a forged payload is refused.

### Decisions made that the spec left open

1. **Detection is rule-based, phrasing is the model's.** An LLM asked to work
   out whether a van is late will occasionally invent a delay, and a panel
   that invents delays is worse than no panel.
2. **The offline keyword router can reach the action capability**, so the
   confirmation flow is not unreachable without an API key. It is safe: it
   produces a proposal, and only the confirm endpoint writes.
3. **A period with no cost records says so** rather than reporting "total cost
   0.00", which reads as a claim about spending that the data does not
   support.

---

## Phase 6 — Auto-rerouting, audit viewing and sign-in activity ✅

### What was built

**Exception Auto-Rerouting (Section 4 item 8).** The name describes the
detection, not the application. FleetBeat decodes an active route's real OSRM
geometry and asks a geometry question — does this path pass within a road
closure's radius, or a severe-weather zone's — then computes a genuine
alternative through OSRM and presents it as a Copilot card with the extra
distance and time spelled out. Applying it is a separate, audited confirm,
because a route that changes underneath a driver already on it is worse than a
delay.

- The detour is a waypoint offset perpendicular to the direction of travel by
  2.5× the closure radius, on whichever side is shorter: OSRM has no "avoid
  this area" parameter, so a waypoint on the far side is how you route around
  something.
- The alternative is recomputed at apply time rather than trusting geometry
  from a proposal made minutes ago — the vehicle has moved since.
- With the routing engine down, the obstruction is still reported and the card
  carries no action payload. A straight-line "alternative" would be a
  confidently wrong ETA.
- Road closures are flagged on the Live Tracking map and drawn in coral with a
  dashed outline — a closure is a live disruption, and it is the one thing on
  that map that feeds rerouting.

**Audit log viewing (Section 4 item 18).** One store, two audiences: an
`org_admin` reads their own tenant's trail (filterable by action and actor,
with each entry's before/after diff expandable in place), a `super_admin`
reads the platform-wide one including the rows that belong to no tenant, and
can narrow it to an Organization. A dispatcher can read neither. No endpoint
writes, edits or deletes an entry — a test walks the route table to keep it
that way.

**Sign-in activity (Section 7).** Suspicious sign-ins, failed attempts, locked
accounts and known devices, with a suspicious-only filter. Detection already
ran on every login from Phase 2; this is the half that lets an admin read it
back.

### Decisions made that the spec left open

1. **`login_attempts` carries no `organization_id`** — an attempt can arrive
   for an address belonging to no user at all — so the tenant scoping is a
   join through the user table, and there is a test that one admin cannot see
   another tenant's sign-ins or the attempts matching no user.
2. **A weather zone justifies a reroute proposal only above 15 minutes of
   expected delay.** Below that the detour usually costs more than the weather
   does.
3. **One proposal per route at a time**, and at most three OSRM round trips
   per Copilot pass, because the pass runs on a two-minute timer.

---

## Settings and team management ✅

Added after the phases, to close a gap the UI itself was pointing at: two
screens told the user to change something "in Settings" and there was no
Settings screen. The API had always exposed these; nothing could reach them.

`/dashboard/settings` now carries the organisation profile, units and
currency, **the driver point weights and monthly baseline** (the Section 9
constraint against hardcoded weights is only real if an admin can actually
reach them), the alert thresholds, the CO2 emission factors, the leaderboard
visibility switch, the maintenance auto-booking switch, and team management -
invite a dispatcher or driver, surface the one-time activation link for manual
delivery, suspend and reactivate.

Two notes on it:

- **Maintenance auto-booking is the one place FleetBeat acts without asking
  each time**, so the screen says exactly that. Turning it on is a standing
  instruction to book; leaving it off (the default) means the Copilot proposes
  and a person applies. The card states which mode is in force.
- **A dispatcher sees the screen read-only.** That is cosmetic - the real gate
  is the API, which answers a dispatcher's PATCH with 403. Verified both ways.

Unlabelled keys are still rendered: a weight or threshold added server-side
appears on this screen with a humanised name rather than silently vanishing
from it.

---

## Driver standings in the mobile app ✅

The same dangling-promise problem as Settings, one layer down. The Safety
screen told an admin "drivers can see this leaderboard in the mobile app", the
API already served a driver-facing leaderboard, the driver app already parsed
`leaderboard_visible` from its home payload — and then never used it. There
was no standings screen.

`lib/features/standings/` adds one, reached by tapping the score/points block
on the driver's home screen. It shows the driver's own row always, the full
leaderboard when their fleet has opted in, their badges, and the badge
catalogue so the scoring is legible rather than mysterious.

**The gate stays server-side.** When peer visibility is off the API returns
only that driver's row; the app renders whatever it is handed and explains why
the list is short. A client-side filter would be a privacy control that a
proxy steps around. The model parser falls closed too — a missing
`visible_to_drivers` flag reads as private, with a test for exactly that.

---

## Three gaps closed after a sweep ✅

After the Settings and standings screens both turned out to be promises the
product had made and not kept, the same question was put to the whole API:
which endpoints does no client ever call? Most answers were noise, three were
real.

**A forced password change was not enforced anywhere.** The super-admin seed
sets `must_change_password`, Section 4a requires the password be changed on
first login, `POST /auth/change-password` existed — and nothing read the flag.
The web app parsed it into a type and ignored it. A seeded account could use
its temporary password against every endpoint, indefinitely.

The fix is server-first, because a UI-only gate would leave the temporary
password working against the API: `get_current_principal` now refuses every
path except the four needed to complete the change (`change-password`, `me`,
`logout`, `refresh`) with a distinct `password_change_required` code. An
impersonating `super_admin` is exempt — the flag is the customer's to clear,
and staff cannot choose their password. The web app adds `/change-password`,
routes there from login and from the role guard, and redirects any tab that
meets the refusal code mid-session.

**A road closure could be created but never lifted.** Roadworks end; a closure
nobody can remove keeps proposing reroutes forever. The live map now lists
active closures with a Lift action beside each.

**Acknowledging an alert looked exactly like resolving it.** The action
existed, the string existed, and `GET /alerts` filtered to active only — so an
acknowledged alert vanished from the feed on the next refresh. The filter now
takes several statuses (`?status=active&status=acknowledged`), the live feed
asks for both, and an acknowledged alert stays on screen wearing a badge. The
default is unchanged, so nothing else shifts meaning.

---

## Testing

**181 backend tests, all passing**, with no external services (in-memory
SQLite, a fake OSRM client, and the offline Claude path).

| Suite | Tests | Covers |
|---|---|---|
| `test_tenant_isolation.py` | 13 | the mandatory Section 7 proof |
| `test_auth.py` | 14 | login, lockout, refresh rotation, RBAC, no registration, forced password change |
| `test_platform_admin.py` | 13 | provisioning, activation, suspension, impersonation |
| `test_fleet_crud.py` | 10 | vehicle/driver lifecycles, audit diffs |
| `test_devices.py` | 10 | device inventory, and that no customer role can touch it |
| `test_simulation.py` | 12 | the feed, trips, persisted history |
| `test_operations.py` | 22 | alerts, maintenance, fuel, compliance |
| `test_tasks.py` | 16 | the task lifecycle and the driver API |
| `test_analytics.py` | 25 | scoring, points, analytics, sustainability |
| `test_ai.py` | 24 | the assistant, copilots, reports, and the confirmation gate |
| `test_phase6.py` | 22 | rerouting, audit views, sign-in activity |

`ruff check .` is clean; the web app typechecks, lints and builds clean across
24 routes.

**Browser verification.** Phases 2, 3, 4, 5 and 6 were each exercised in
Chromium against a live API with the simulator running — not just unit-tested.
That is how several of the fixes recorded in the commit messages were found:
a route-ordering bug that made `/drivers/scores` unreachable, a simulation
event rate twenty times too high that floored every safety score, a Copilot
rank collision that showed two "#1" cards, an audit diff renderer that showed
"— → —" for every entry, and a reroute audit entry that recorded no change at
all because it read the ETA after overwriting it.

**Two guard tests were rewritten after being checked against the bug they
guard.** The first route-shadowing test still passed with the bug
reintroduced, and so did the first rank-collision test. Both were rewritten
until they failed against the bug and passed against the fix.

---

## Known gaps in verification

1. **The Flutter app has not been compiled.** No Flutter SDK is installed in
   this environment. The Dart code is written against Flutter 3.27+ but has
   not been executed, and its four widget/model tests have not been run.
   `android/` and `ios/` folders are not committed — run `flutter create .` in
   `mobile/` once before the first build.

   Two checks in `mobile/tool/` stand in for what a compiler would catch
   first, and both were validated against a deliberately broken copy of the
   code rather than trusted because they printed OK:
   - `static_check.py` — unbalanced delimiters, imports resolving to nothing,
     `Strings.*` with no constant, a type used without its import.
   - `route_check.py` — every API path the app calls, matched against the
     OpenAPI schema the API actually serves, expanding an interpolated path to
     the concrete routes it can produce. This found a real bug: the standings
     screen called `/analytics/leaderboard` when the served route is
     `/leaderboard`.
2. **No Docker daemon here**, so `docker compose up` has not been run
   end-to-end. The stack was exercised by running the API, worker and web app
   directly. The baseline migration was validated by rendering its full
   Postgres DDL offline (`alembic upgrade head --sql`).
3. **OSRM is not running in this environment**, so rerouting was verified
   against a fake OSRM client in tests rather than against real road geometry
   in a browser. Every other Phase 6 screen was verified in a browser.
4. **Map tiles are blocked by this environment's network policy**, so the map
   was verified by its layers, sources, markers and controls rather than by
   the imagery underneath them.

---

## Open questions for the product owner

1. **Operating region for OSRM.** The routing container needs a specific
   OpenStreetMap extract. Which country/region should ship as the default?
2. **Distance and currency defaults.** Currently km and USD per Organization.
   Should these follow from the chosen timezone/region at provisioning time?
3. **Driver profile vs. driver login.** A driver profile can exist without a
   login. Is that right, or should every driver always get mobile access?
4. **Suspending an Organization** blocks logins immediately but does not stop
   tracking their vehicles. Should a suspension freeze data collection too?
5. **Activation link lifetime** is 72 hours. Does that suit the onboarding
   pace, given links are delivered manually?
6. **Who should be able to flag a road closure?** It is currently any
   dashboard user (`org_admin` or `dispatcher`), on the grounds that a
   dispatcher is the person who hears about a closure first. Applying the
   resulting reroute is `org_admin` only.
