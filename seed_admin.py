#!/usr/bin/env python3
"""Seed admin user jika belum ada di database - menggunakan raw SQL."""
import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text

from infrastructure.persistence_orm.database import async_session_maker


async def seed_admin():
    async with async_session_maker() as session:
        check_stmt = text("SELECT id FROM iam_user WHERE username = 'admin'")
        result = await session.execute(check_stmt)
        existing = result.fetchone()
        if existing:
            print("Admin user already exists.")
            return

        admin_id = uuid4()
        legal_entity_id = UUID("00000000-0000-0000-0000-000000000001")
        password_hash = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKx0f7WcUmHx5cW"  # "Admin123!"
        now = datetime.now(UTC)

        insert_stmt = text("""
            INSERT INTO iam_user (
                id, username, email, full_name, password_hash,
                must_change_password, status, is_active, is_superuser,
                failed_login_count, legal_entity_ids,
                created_at, updated_at, version
            )
            VALUES (
                :id, :username, :email, :full_name, :password_hash,
                :must_change_password, :status, :is_active, :is_superuser,
                :failed_login_count, CAST(:legal_entity_ids AS jsonb),
                :created_at, :updated_at, :version
            )
        """)
        await session.execute(insert_stmt, {
            "id": admin_id,
            "username": "admin",
            "email": "admin@erp.com",
            "full_name": "Administrator",
            "password_hash": password_hash,
            "must_change_password": False,
            "status": "active",
            "is_active": True,
            "is_superuser": True,
            "failed_login_count": 0,
            "legal_entity_ids": json.dumps([str(legal_entity_id)]),
            "created_at": now,
            "updated_at": now,
            "version": 1,
        })
        await session.commit()
        print("Admin user created with password: Admin123!")
        print(f"   User ID: {admin_id}")
        print(f"   Legal Entity ID: {legal_entity_id}")

if __name__ == "__main__":
    asyncio.run(seed_admin())
