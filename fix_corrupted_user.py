# fix_corrupted_user.py
import asyncio
import os
import json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from adapters.secondary_impl.sqlalchemy_iam_user_repository_impl import PasswordHelper

async def main():
    DATABASE_URL = os.getenv("DATABASE_URL")
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        # Find the admin user (there's only one)
        result = await conn.execute(text("SELECT id FROM iam_user WHERE username = 'admin'"))
        row = result.fetchone()
        if not row:
            print("No admin user found.")
            return
        user_id = row[0]

        # Generate correct hash
        hash_val = PasswordHelper.hash_password("Admin123!")
        legal_id = "d4785e85-a647-46dc-8fe2-fc64b5188f37"
        legal_ids_json = json.dumps([legal_id])

        # Update the columns correctly
        await conn.execute(
            text("""
                UPDATE iam_user
                SET password_hash = :hash,
                    legal_entity_ids = CAST(:legal_ids AS jsonb)
                WHERE id = :id
            """),
            {"hash": hash_val, "legal_ids": legal_ids_json, "id": user_id}
        )
        await conn.commit()
        print(f"Updated user {user_id} with proper hash and legal_entity_ids.")

if __name__ == "__main__":
    asyncio.run(main())