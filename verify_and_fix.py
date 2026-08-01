# verify_and_fix.py
import asyncio
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from adapters.secondary_impl.sqlalchemy_iam_user_repository_impl import PasswordHelper

async def main():
    DATABASE_URL = os.getenv("DATABASE_URL")
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        # Get the admin user
        result = await conn.execute(text("SELECT id, username, password_hash, legal_entity_ids FROM iam_user WHERE username = 'admin'"))
        row = result.fetchone()
        if not row:
            print("No user found.")
            return
        user_id, username, old_hash, legal_ids = row
        print(f"Found user: {username} ({user_id})")
        print(f"Old hash: {old_hash}")
        print(f"Legal entity ids: {legal_ids}")

        # Generate a valid hash
        new_hash = PasswordHelper.hash_password("Admin123!")
        print(f"New hash: {new_hash}")

        # Update explicitly
        await conn.execute(
            text("UPDATE iam_user SET password_hash = :new_hash WHERE id = :id"),
            {"new_hash": new_hash, "id": user_id}
        )
        await conn.commit()

        # Verify again
        result2 = await conn.execute(text("SELECT password_hash FROM iam_user WHERE id = :id"), {"id": user_id})
        row2 = result2.fetchone()
        print(f"Hash after update: {row2[0]}")

        # Now test if the application would accept it by creating a PasswordHashedVO
        try:
            from domain.iam.password_hashed_vo import PasswordHashedVO
            ph = PasswordHashedVO(row2[0])
            print("PasswordHashedVO validation passed!")
        except Exception as e:
            print(f"PasswordHashedVO validation failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())