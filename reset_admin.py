# reset_admin.py
import asyncio
import json
import os
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from adapters.secondary_impl.sqlalchemy_iam_user_repository_impl import PasswordHelper


async def main():
    DATABASE_URL = os.getenv("DATABASE_URL")
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        # Delete all admin users
        await conn.execute(text("DELETE FROM iam_user_role WHERE user_id IN (SELECT id FROM iam_user WHERE username = 'admin')"))
        await conn.execute(text("DELETE FROM iam_user WHERE username = 'admin'"))
        print("Deleted all existing admin users.")

        # Create a fresh admin
        legal_entity_id = "d4785e85-a647-46dc-8fe2-fc64b5188f37"
        admin_id = uuid.uuid4()
        password_hash = PasswordHelper.hash_password("Admin123!")

        await conn.execute(
            text("""
                INSERT INTO iam_user (
                    id, username, email, full_name, password_hash,
                    is_superuser, is_active, status, legal_entity_ids,
                    must_change_password, failed_login_count,
                    created_at, updated_at, version
                ) VALUES (
                    :id, 'admin', 'admin@example.com', 'Administrator', :hash,
                    true, true, 'active', CAST(:legal_ids AS jsonb),
                    false, 0, NOW(), NOW(), 1
                )
            """),
            {
                "id": admin_id,
                "hash": password_hash,
                "legal_ids": json.dumps([legal_entity_id])
            }
        )
        print(f"Fresh admin created with ID: {admin_id}")

        # Ensure the 'Administrator' role is assigned
        # First get the role id
        role_result = await conn.execute(text("SELECT id FROM iam_role WHERE name = 'Administrator'"))
        role_row = role_result.fetchone()
        if role_row:
            role_id = role_row[0]
            await conn.execute(
                text("INSERT INTO iam_user_role (user_id, role_id) VALUES (:user_id, :role_id) ON CONFLICT DO NOTHING"),
                {"user_id": admin_id, "role_id": role_id}
            )
            print("Role 'Administrator' assigned.")
        else:
            print("Warning: Role 'Administrator' not found. Please create it first.")

        await conn.commit()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
