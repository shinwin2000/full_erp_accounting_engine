# check_admin_users.py
import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main():
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        print("DATABASE_URL not set")
        return

    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id, username, legal_entity_ids, password_hash FROM iam_user WHERE username = 'admin'")
        )
        rows = result.fetchall()
        if not rows:
            print("Tidak ada user dengan username 'admin'.")
        else:
            print(f"Ditemukan {len(rows)} user admin:")
            for i, row in enumerate(rows, 1):
                print(f"\n--- User {i} ---")
                print(f"ID               : {row[0]}")
                print(f"legal_entity_ids : {row[1]}")
                print(f"password_hash    : {row[2][:50]}...")  # tampilkan sebagian

if __name__ == "__main__":
    asyncio.run(main())
