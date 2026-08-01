# fix_password_with_app_helper.py
import asyncio
import os
import json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from adapters.secondary_impl.sqlalchemy_iam_user_repository_impl import PasswordHelper

async def main():
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:palapapls88@localhost/erp_db")
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        # Find admin user
        result = await conn.execute(text("SELECT id FROM iam_user WHERE username = 'admin'"))
        row = result.fetchone()
        if not row:
            print("User not found")
            return
        user_id = row[0]
        # Hash using the application's PasswordHelper
        new_hash = PasswordHelper.hash_password("Admin123!")
        # Update
        await conn.execute(
            text("UPDATE iam_user SET password_hash = :hash WHERE id = :id"),
            {"hash": new_hash, "id": user_id}
        )
        await conn.commit()
        print(f"Password updated for user {user_id} with hash: {new_hash}")

if __name__ == "__main__":
    asyncio.run(main())