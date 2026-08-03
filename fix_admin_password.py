# fix_admin_password.py
import asyncio
import json
import os

import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main():
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:palapapls88@localhost/erp_db")
    if not DATABASE_URL:
        print("DATABASE_URL not set")
        return

    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        # Find admin user
        result = await conn.execute(text("SELECT id, legal_entity_ids FROM iam_user WHERE username = 'admin'"))
        row = result.fetchone()
        if not row:
            print("User 'admin' not found. Creating...")
            # We'll create a new one with minimal fields.
            # But better to use a combined script.
            # Let's create a simple one.
            await conn.execute(text("""
                INSERT INTO iam_user (id, username, email, full_name, password_hash,
                    is_superuser, is_active, status, legal_entity_ids,
                    must_change_password, failed_login_count,
                    created_at, updated_at, version)
                VALUES (
                    gen_random_uuid(), 'admin', 'admin@example.com', 'Administrator', :hash,
                    true, true, 'active', CAST(:legal_ids AS jsonb),
                    false, 0, NOW(), NOW(), 1
                )
            """), {"hash": bcrypt.hashpw(b"Admin123!", bcrypt.gensalt()).decode(),
                   "legal_ids": json.dumps(["d4785e85-a647-46dc-8fe2-fc64b5188f37"])})
            print("Admin created.")
        else:
            user_id = row[0]
            # Update password
            new_hash = bcrypt.hashpw(b"Admin123!", bcrypt.gensalt()).decode()
            await conn.execute(
                text("UPDATE iam_user SET password_hash = :hash WHERE id = :id"),
                {"hash": new_hash, "id": user_id}
            )
            print(f"Password updated for user {user_id}.")
        await conn.commit()

if __name__ == "__main__":
    asyncio.run(main())
