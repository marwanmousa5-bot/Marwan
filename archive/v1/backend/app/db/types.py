"""Portable column types.

The production database is PostgreSQL, but the test-suite runs on SQLite so
that tenant-isolation/RBAC tests stay fast and dependency-free. These
variants keep a single model definition working on both.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# JSONB on Postgres, plain JSON on SQLite.
JSONB = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")

# Native uuid on Postgres, CHAR(32) on SQLite.
GUID = sa.Uuid(as_uuid=True)
