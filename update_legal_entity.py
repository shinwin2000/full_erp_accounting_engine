# update_legal_entity.py
import asyncio
import json
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main():
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:palapapls88@localhost/erp_db")
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        legal_id = "d4785e85-a647-46dc-8fe2-fc64b5188f37"
        await conn.execute(
            text("UPDATE iam_user SET legal_entity_ids = CAST(:ids AS jsonb) WHERE username = 'admin'"),
            {"ids": json.dumps([legal_id])}
        )
        await conn.commit()
        print("Updated legal_entity_ids for admin.")
        result = await conn.execute(text("SELECT id, legal_entity_ids FROM iam_user WHERE username = 'admin'"))
        row = result.fetchone()
        print(row)

if __name__ == "__main__":
    asyncio.run(main())
