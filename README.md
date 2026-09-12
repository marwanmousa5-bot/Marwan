# FleetBeat

**The live pulse of your fleet.**

Multi-tenant B2B SaaS for vehicle fleet management: live GPS tracking,
dispatch, maintenance, compliance, driver safety and fleet analytics.

FleetBeat is a **managed** product, not a self-serve one. There is no public
sign-up: every customer Organization and its first administrator are created
by FleetBeat staff through the Platform Admin Console, and GPS devices are
provisioned and linked to vehicles by FleetBeat — customers only ever see the
resulting live data.

---

## Repository layout

```
backend/     FastAPI + SQLAlchemy 2.0 (async) + Alembic + Celery
  app/
    api/v1/    Versioned REST surface
    core/      Config, security, RBAC dependencies, tenant scoping
    db/        Engine, session, declarative base
    models/    All ORM entities
    schemas/   Pydantic request/response models
    services/  Business logic (auth, provisioning, vehicles, drivers, audit)
    ai/        Isolated AI service layer (Section 5)
    simulation/  LocationProvider abstraction for the GPS feed
    realtime/  WebSocket fan-out hub
  alembic/   Migrations
  tests/     Pytest suite (auth, RBAC, tenant isolation, CRUD)

web/         Next.js 14 (App Router) + TypeScript + Tailwind
  app/dashboard/       Customer console (org_admin / dispatcher)
  app/platform-admin/  Internal console (super_admin only)

mobile/      Flutter driver app

infra/osrm/  Self-hosted OSRM routing engine setup
```

---

## Quick start

```bash
cp .env.example .env
# Set JWT_SECRET_KEY to a long random value:
#   python3 -c "import secrets; print(secrets.token_urlsafe(48))"

docker compose up --build
```

That brings up Postgres, Redis, the API, the Celery worker and beat, and the
web dashboard. On first start the API container applies migrations and seeds
the platform super admin.

| Service | URL |
|---|---|
| Web dashboard | http://localhost:3000 |
| API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| OpenAPI schema | http://localhost:8000/api/v1/openapi.json |

### Demo data (evaluation and testing)

A fresh stack starts empty, which is correct for production and unhelpful for
a first look. One command builds a populated tenant:

```bash
docker compose run --rm api python -m app.seed_demo
```

That provisions **Northwind Transport** through the real provisioning flow -
7 vehicles (6 fitted with GPS, one deliberately left **Not Tracked**), 4
drivers, geofences and POIs, six weeks of fuel and service history, and 45
minutes of recorded movement, so trips, driver events, alerts and every
analytics screen have something in them before you sign in.

It prints the admin sign-in, generating a password unless you set
`DEMO_ADMIN_PASSWORD`. It refuses to run twice by default; `--force` tears the
demo tenant down and rebuilds it.

### Seeing live data

Vehicles only produce GPS data once FleetBeat fits them a device. After
creating a customer and adding a vehicle, go to **Platform Admin → Devices**,
add a device to inventory, and fit it to that vehicle. The `simulator` service
picks it up within 20 seconds and the vehicle starts moving on the customer's
Live Tracking map. Vehicles without a device show as **Not Tracked** — that
distinction is deliberate and visible to the customer.

### First login

The super-admin account (`Marwan.mousa5@gmail.com`) is seeded on first
startup. Its password comes from `SUPERADMIN_INITIAL_PASSWORD` if you set it
in `.env`; otherwise a random one is generated and printed **once** to the API
container logs:

```bash
docker compose logs api | grep -A6 "FleetBeat super admin created"
```

Sign in at http://localhost:3000 → you land in the **Platform Admin Console**.
From there, *New organization* creates a customer and returns a one-time
activation link. Copy that link, open it, set a password, and you can sign in
as that customer's Org Admin to reach the fleet dashboard.

---

## Running the backend without Docker

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

export DATABASE_URL="postgresql+asyncpg://fleetbeat:fleetbeat@localhost:5432/fleetbeat"
export JWT_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"

alembic upgrade head
python -m app.seed_admin
uvicorn app.main:app --reload
```

## Tests

```bash
cd backend && pytest            # 46 tests, no external services required
cd backend && ruff check .
cd web && npm run typecheck && npm run build
cd mobile && flutter test
```

The suite runs against in-memory SQLite so it needs no database. It includes
the mandatory tenant-isolation tests proving Organization A can never read or
write Organization B's data through any endpoint.

---

## Architecture notes

**Multi-tenancy.** Shared database, shared schema, `organization_id` on every
tenant-scoped table. Isolation is enforced by `app.core.tenancy.TenantScope`,
whose `organization_id` is derived from the authenticated principal's JWT —
never from a path, query string or request body. `scope.select(Model)` refuses
to run against a table with no tenant column.

**Roles.** `super_admin` (FleetBeat staff, belongs to no tenant),
`org_admin`, `dispatcher`, `driver`. RBAC is enforced by FastAPI dependencies
on every route, not by hiding UI.

**Audit log.** Append-only, written from day one. Logins, data changes,
organization lifecycle events and every impersonation land in `audit_logs`.
There is no update or delete path for it anywhere in the API.

**Routing.** OSRM is real, self-hosted routing over OpenStreetMap data — only
the *vehicle position feed* is simulated. See `infra/osrm/README.md`.

See `PROGRESS.md` for what is built per phase, the decisions taken, and open
questions.
