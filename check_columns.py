#!/usr/bin/env python3
"""
Script diagnostik: cek kolom-kolom yang benar-benar ada di suatu tabel
di database (via DATABASE_URL env var, sama dengan yang dipakai aplikasi).

Usage:
    python check_columns.py <nama_tabel> [<nama_tabel_2> ...]

Contoh:
    python check_columns.py approval_request approval_matrix approval_delegation
"""

import asyncio
import os
import sys

import asyncpg


async def main() -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL tidak di-set di environment ini!")
        return

    table_names = sys.argv[1:]
    if not table_names:
        table_names = ["approval_request"]

    dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)

    try:
        for table_name in table_names:
            print(f"\n=== Kolom di tabel '{table_name}' ===")
            rows = await conn.fetch(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = $1
                ORDER BY ordinal_position
                """,
                table_name,
            )
            if not rows:
                print(f"  (tabel '{table_name}' tidak ditemukan)")
                continue
            for r in rows:
                nullable = "NULL" if r["is_nullable"] == "YES" else "NOT NULL"
                default = f" DEFAULT {r['column_default']}" if r["column_default"] else ""
                print(f"  - {r['column_name']}: {r['data_type']} {nullable}{default}")
            print(f"  Total: {len(rows)} kolom")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
