# fix_legal_entity.py
import asyncio
import os
import json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    DATABASE_URL = os.getenv("DATABASE_URL")
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        # Update legal_entity_ids to exactly match the expected JSON array
        await conn.execute(
            text("UPDATE iam_user SET legal_entity_ids = CAST(:ids AS jsonb) WHERE username = 'admin'"),
            {"ids": json.dumps(["d4785e85-a647-46dc-8fe2-fc64b5188f37"])}
        )
        await conn.commit()
        print("Updated legal_entity_ids for admin.")

if __name__ == "__main__":
    asyncio.run(main())