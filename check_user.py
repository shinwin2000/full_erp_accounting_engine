# check_user.py
import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from domain.iam.password_hashed_vo import PasswordHashedVO


async def main():
    DATABASE_URL = os.getenv("DATABASE_URL")
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id, username, password_hash, legal_entity_ids, is_active, status FROM iam_user WHERE username = 'admin'")
        )
        row = result.fetchone()
        if not row:
            print("Tidak ada user admin")
            return
        user_id, username, pw_hash, legal_ids, is_active, status = row
        print(f"ID: {user_id}")
        print(f"Username: {username}")
        print(f"Password hash: {pw_hash}")
        print(f"Legal entity ids: {legal_ids} (type: {type(legal_ids)})")
        print(f"Is active: {is_active}")
        print(f"Status: {status}")

        # Test PasswordHashedVO
        try:
            vo = PasswordHashedVO(pw_hash)
            print("PasswordHashedVO constructed successfully")
            print(f"  rounds/iterations: {vo.iterations}")
            print(f"  algorithm: {vo.algorithm}")
            match = vo.verify("Admin123!")
            print(f"Verify result: {match}")
        except Exception as e:
            print(f"Error constructing PasswordHashedVO: {e}")

        # Check roles
        role_result = await conn.execute(
            text("SELECT r.name FROM iam_user_role ur JOIN iam_role r ON ur.role_id = r.id WHERE ur.user_id = :user_id"),
            {"user_id": user_id}
        )
        roles = role_result.fetchall()
        print(f"Roles: {[r[0] for r in roles]}")

if __name__ == "__main__":
    asyncio.run(main())
