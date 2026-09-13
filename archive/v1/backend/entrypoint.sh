#!/usr/bin/env bash
# Wait for Postgres, apply migrations, seed the super admin, then start the API.
set -euo pipefail

echo "[fleetbeat] waiting for the database..."
until python -c "
import asyncio, sys
import asyncpg
from app.core.config import settings

async def main():
    url = settings.database_url.replace('+asyncpg', '')
    conn = await asyncpg.connect(url)
    await conn.close()

try:
    asyncio.run(main())
except Exception as exc:
    print(exc, file=sys.stderr)
    sys.exit(1)
" 2>/dev/null; do
  sleep 1
done

echo "[fleetbeat] applying migrations..."
alembic upgrade head

echo "[fleetbeat] seeding the platform super admin..."
python -m app.seed_admin

echo "[fleetbeat] starting API on :8000"
exec "$@"
