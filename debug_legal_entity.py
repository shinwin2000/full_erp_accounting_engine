import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main():
    engine = create_async_engine(os.getenv("DATABASE_URL"))
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT username, legal_entity_ids, is_active, status FROM iam_user WHERE username = 'admin'")
        )
        row = result.fetchone()
        if row:
            print(f"username         : {row[0]}")
            print(f"legal_entity_ids : {row[1]}")
            print(f"is_active        : {row[2]}")
            print(f"status           : {row[3]}")
        else:
            print("User admin tidak ditemukan")

if __name__ == "__main__":
    asyncio.run(main())
