#!/usr/bin/env python3
"""Seed/fix admin user - UPDATE in place (aman terhadap FK, tidak delete)."""
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

        # legal_entity_id yang BENAR-BENAR ada di tabel legal_entity & sudah dipakai user admin
        legal_entity_id = UUID("81171f76-9045-4eb5-9132-76a5d842bb78")
        password_hash = "$2b$12$B.I.O0UIbTPGS7uJho5rTuGI12CKSS/PdvRclP/Z.3B.0VhDXfu6i"
        now = datetime.now(UTC)

        if existing:
            print(f"Admin user sudah ada (id={existing.id}). UPDATE in place...")
            update_stmt = text("""
                UPDATE iam_user
                SET password_hash = :password_hash,
                    must_change_password = false,
                    status = 'active',
                    is_active = true,
                    is_superuser = true,
                    failed_login_count = 0,
                    locked_until = NULL,
                    legal_entity_ids = CAST(:legal_entity_ids AS jsonb),
                    updated_at = :updated_at
                WHERE username = 'admin'
            """)
            await session.execute(update_stmt, {
                "password_hash": password_hash,
                "legal_entity_ids": json.dumps([str(legal_entity_id)]),
                "updated_at": now,
            })
            await session.commit()
            print("Admin user updated. Password: Admin123!")
            print(f"   User ID: {existing.id}")
            print(f"   Legal Entity ID: {legal_entity_id}")
        else:
            admin_id = uuid4()
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