"""Seed the single platform `super_admin` account (Section 4a).

Run with::

    python -m app.seed_admin

Password resolution, in order:
1. ``SUPERADMIN_INITIAL_PASSWORD`` from the environment, if set;
2. otherwise a cryptographically random password, printed to stdout exactly
   once at creation time and never stored anywhere in plaintext.

In case (2) the account is flagged ``must_change_password`` so the password
has to be replaced on first login. No password is ever hardcoded in the
codebase.

The command is idempotent: re-running it will not overwrite an existing
account's password.
"""

from __future__ import annotations

import asyncio
import logging
import sys

import sqlalchemy as sa

from app.core.config import settings
from app.core.security import generate_password, hash_password
from app.db.session import SessionLocal
from app.models.enums import UserRole, UserStatus
from app.models.user import User

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("fleetbeat.seed")

BANNER = "=" * 72


async def seed_super_admin() -> int:
    email = settings.superadmin_email.strip().lower()

    async with SessionLocal() as db:
        result = await db.execute(
            sa.select(User).where(sa.func.lower(User.email) == email).limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            if existing.role != UserRole.SUPER_ADMIN:
                logger.error(
                    "A non-super_admin user already owns %s - refusing to change it.",
                    email,
                )
                return 1
            logger.info("Super admin %s already exists - nothing to do.", email)
            return 0

        generated = settings.superadmin_initial_password is None
        password = settings.superadmin_initial_password or generate_password()

        user = User(
            organization_id=None,  # platform staff belong to no tenant
            email=email,
            full_name=settings.superadmin_name,
            hashed_password=hash_password(password),
            role=UserRole.SUPER_ADMIN,
            status=UserStatus.ACTIVE,
            must_change_password=generated,
        )
        db.add(user)
        await db.commit()

        logger.info(BANNER)
        logger.info("FleetBeat super admin created")
        logger.info("  Email:    %s", email)
        if generated:
            logger.info("  Password: %s", password)
            logger.info("")
            logger.info("  This password is shown ONCE and is not stored anywhere")
            logger.info("  in plaintext. Copy it now - you must change it on first")
            logger.info("  login. Set SUPERADMIN_INITIAL_PASSWORD to choose your own.")
        else:
            logger.info("  Password: (taken from SUPERADMIN_INITIAL_PASSWORD)")
        logger.info(BANNER)
        return 0


def main() -> None:
    sys.exit(asyncio.run(seed_super_admin()))


if __name__ == "__main__":
    main()
