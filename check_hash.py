# check_hash.py
import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main():
    DATABASE_URL = os.getenv("DATABASE_URL")
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT id, username, password_hash FROM iam_user WHERE username = 'admin'"))
        row = result.fetchone()
        if row:
            print(f"User ID: {row[0]}, Username: {row[1]}, Hash: {row[2]}")
            # Attempt to decode rounds from hash
            if row[2]:
                try:
                    # bcrypt hash format: $2b$<rounds>$<salt><hash>
                    parts = row[2].split('$')
                    if len(parts) >= 3:
                        rounds_str = parts[1]
                        if rounds_str.startswith('2b$'):
                            rounds_str = rounds_str[3:]
                        rounds = int(rounds_str)
                        print(f"Rounds: {rounds}")
                except:
                    pass
        else:
            print("User not found")

if __name__ == "__main__":
    asyncio.run(main())
