"""The mandatory tenant-scoping mechanism (Section 3).

Every read or write of a tenant-scoped table goes through a ``TenantScope``.
The scope's ``organization_id`` comes from the authenticated principal's JWT
and is never taken from a path, query string, or body. Using
``scope.select(Model)`` instead of a bare ``select(Model)`` makes the
isolation filter impossible to forget by accident, and the automated tests in
``tests/test_tenant_isolation.py`` prove it holds end-to-end.
"""

from __future__ import annotations

import uuid
from typing import Any, TypeVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, PermissionDeniedError
from app.db.base import Base, TenantScopedMixin

ModelT = TypeVar("ModelT", bound=Base)


class TenantScope:
    """Binds a request to exactly one Organization."""

    __slots__ = ("organization_id",)

    def __init__(self, organization_id: uuid.UUID) -> None:
        self.organization_id = organization_id

    def select(self, model: type[ModelT], *entities: Any) -> sa.Select:
        """A SELECT already filtered to this Organization."""
        _assert_tenant_scoped(model)
        stmt = sa.select(model, *entities) if entities else sa.select(model)
        return stmt.where(model.organization_id == self.organization_id)

    def filter(self, stmt: sa.Select, model: type[ModelT]) -> sa.Select:
        """Apply the tenant filter to an existing statement."""
        _assert_tenant_scoped(model)
        return stmt.where(model.organization_id == self.organization_id)

    def owns(self, obj: Any) -> bool:
        return getattr(obj, "organization_id", None) == self.organization_id

    def assign(self, obj: ModelT) -> ModelT:
        """Stamp a new row with this Organization before it is inserted."""
        _assert_tenant_scoped(type(obj))
        obj.organization_id = self.organization_id
        return obj

    async def get(
        self, db: AsyncSession, model: type[ModelT], entity_id: uuid.UUID
    ) -> ModelT | None:
        result = await db.execute(
            self.select(model).where(model.id == entity_id).limit(1)
        )
        return result.scalar_one_or_none()

    async def get_or_404(
        self,
        db: AsyncSession,
        model: type[ModelT],
        entity_id: uuid.UUID,
        *,
        label: str | None = None,
    ) -> ModelT:
        obj = await self.get(db, model, entity_id)
        if obj is None:
            # Deliberately indistinguishable from "exists but belongs to
            # another tenant" - cross-tenant probing must not leak existence.
            raise NotFoundError(f"{label or model.__name__} not found")
        return obj

    async def count(self, db: AsyncSession, model: type[ModelT]) -> int:
        _assert_tenant_scoped(model)
        result = await db.execute(
            sa.select(sa.func.count())
            .select_from(model)
            .where(model.organization_id == self.organization_id)
        )
        return int(result.scalar_one())

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<TenantScope org={self.organization_id}>"


def _assert_tenant_scoped(model: type) -> None:
    if not issubclass(model, TenantScopedMixin):
        raise PermissionDeniedError(
            f"{model.__name__} is not tenant-scoped and cannot be queried "
            "through a TenantScope"
        )
