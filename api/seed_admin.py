#!/usr/bin/env python3
"""
SIMP DATING — Seed Admin Script
===================================
Creates the first super-admin user in the database.
Run once: python seed_admin.py --telegram-id <YOUR_TG_ID> --name "Your Name"

The script connects to PostgreSQL via DATABASE_URL (from .env or env var),
creates a User with role='owner' and an empty Profile.
It also outputs the ADMIN_IDS value to set in .env.
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

# Auto-load .env from project root
_project_root = Path(__file__).resolve().parent.parent
_env_file = _project_root / ".env"

if _env_file.exists():
    with open(_env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                import os
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))



async def create_admin(telegram_id: int, name: str = "Admin", email: str | None = None) -> None:
    """Create super-admin user in dating_users + dating_profiles."""

    # Connect to DB
    from database.connection import engine, async_session_factory
    from models.models import Base, User, Profile

    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        async with session.begin():
            # Check if user already exists
            from sqlalchemy import select
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Promote existing user
                existing.role = "owner"
                existing.is_banned = False
                existing.is_verified = True
                await session.flush()
                print(f"[OK] User TG:{telegram_id} promoted to OWNER (id={existing.id})")
            else:
                # Create new admin user
                user = User(
                    telegram_id=telegram_id,
                    role="owner",
                    is_banned=False,
                    is_verified=True,
                )
                session.add(user)
                await session.flush()

                # Create profile
                profile = Profile(
                    user_id=user.id,
                    display_name=name,
                    bio="Администратор Симпа",
                    gender="other",
                    city="",
                )
                session.add(profile)
                await session.flush()

                print(f"[OK] Admin user created (id={user.id})")

            # Verify
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            admin = result.scalar_one_or_none()
            print(f"     ID:         {admin.id}")
            print(f"     Telegram:    {admin.telegram_id}")
            print(f"     Role:        {admin.role}")
            print(f"     Is banned:   {admin.is_banned}")
            print(f"     Is verified: {admin.is_verified}")

    print()
    print("=" * 50)
    print("Add this to your .env file:")
    print(f"  ADMIN_IDS={telegram_id}")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="Create super-admin for Simp Dating")
    parser.add_argument(
        "--telegram-id", "-t",
        type=int, required=True,
        help="Your Telegram user ID (from @userinfobot or @getmyid_bot)",
    )
    parser.add_argument(
        "--name", "-n",
        type=str, default="Admin",
        help="Display name for the admin profile",
    )
    parser.add_argument(
        "--email", "-e",
        type=str, default=None,
        help="Optional email address",
    )

    args = parser.parse_args()

    print(f"SIMP DATING — Seed Admin")
    print(f"Creating admin with Telegram ID: {args.telegram_id}")
    print()

    asyncio.run(create_admin(args.telegram_id, args.name, args.email))


if __name__ == "__main__":
    main()
