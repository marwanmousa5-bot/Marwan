"""Test harness.

Runs against an in-memory SQLite database so the suite needs no services.
The tenant-isolation tests exercise the real dependency chain and the real
``TenantScope``, so they prove the production isolation mechanism rather than
a test-only stand-in.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-used-in-production")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "local")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.security import hash_password  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.enums import UserRole, UserStatus  # noqa: E402
from app.models.organization import Organization, OrganizationSettings  # noqa: E402
from app.models.user import User  # noqa: E402

TEST_PASSWORD = "TestPassw0rd!2026"


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db(session_factory) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session
        await session.commit()


@pytest_asyncio.fixture
async def client(session_factory) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

async def make_organization(db: AsyncSession, name: str) -> Organization:
    org = Organization(name=name, slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}")
    db.add(org)
    await db.flush()
    db.add(OrganizationSettings(organization_id=org.id))
    await db.flush()
    return org


async def make_user(
    db: AsyncSession,
    *,
    email: str,
    role: UserRole,
    organization: Organization | None = None,
    password: str = TEST_PASSWORD,
    status: UserStatus = UserStatus.ACTIVE,
) -> User:
    user = User(
        organization_id=organization.id if organization else None,
        email=email.lower(),
        full_name=email.split("@")[0].replace(".", " ").title(),
        hashed_password=hash_password(password),
        role=role,
        status=status,
    )
    db.add(user)
    await db.flush()
    return user


async def login(client: AsyncClient, email: str, password: str = TEST_PASSWORD) -> str:
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["tokens"]["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def super_admin(db: AsyncSession) -> User:
    user = await make_user(
        db, email="platform.admin@fleetbeat.example.com", role=UserRole.SUPER_ADMIN
    )
    await db.commit()
    return user


@pytest.fixture
def password() -> str:
    return TEST_PASSWORD
