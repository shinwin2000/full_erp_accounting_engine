#!/usr/bin/env python3
"""
Script diagnostik: cek langsung ke database erp_db (via DATABASE_URL env var,
sama dengan yang dipakai aplikasi FastAPI) untuk:
1. Isi alembic_version
2. Daftar semua tabel yang benar-benar ada di schema public
3. Apakah tabel 'budget', 'budget_line', 'budget_actual' ada
"""

import asyncio
import os

import asyncpg


async def main() -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL tidak di-set di environment ini!")
        return

    # asyncpg tidak paham prefix 'postgresql+asyncpg://', harus 'postgresql://'
    dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")

    print(f"Menyambung ke: {dsn.split('@')[-1]}")  # jangan print password
    conn = await asyncpg.connect(dsn)

    try:
        print("\n=== alembic_version ===")
        try:
            rows = await conn.fetch("SELECT * FROM alembic_version")
            for r in rows:
                print(dict(r))
        except Exception as e:
            print(f"Gagal baca alembic_version: {e}")

        print("\n=== Semua tabel di schema public ===")
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        tables = [r["tablename"] for r in rows]
        for t in tables:
            print(f"  - {t}")
        print(f"\nTotal: {len(tables)} tabel")

        print("\n=== Cek spesifik tabel budget ===")
        for name in ("budget", "budget_line", "budget_actual"):
            exists = name in tables
            mark = "✅ ADA" if exists else "❌ TIDAK ADA"
            print(f"  {name}: {mark}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
