#!/usr/bin/env python3
"""
create_generated_report_table.py

Perbaikan modul Reports: membuat tabel `generated_report` yang dipakai
untuk menyimpan metadata laporan hasil generate (list/get/status/history/
delete report) di fastapi_report_router.py. Tabel ini BELUM ada di
database manapun sebelumnya (fitur baru, bukan schema drift dari kolom
yang hilang seperti kasus umkm_journal).

Idempotent (CREATE TABLE IF NOT EXISTS), jadi aman dijalankan berkali-kali.

Cara pakai:
    python scripts/create_generated_report_table.py
    python scripts/create_generated_report_table.py --database-url "postgresql://postgres:PASSWORD@127.0.0.1:5432/erp_db"

Dependensi: asyncpg (sudah dipakai aplikasi utama).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

try:
    import asyncpg
except ImportError:
    print(
        "ERROR: modul 'asyncpg' tidak ditemukan. Install dulu dengan:\n"
        "    pip install asyncpg",
        file=sys.stderr,
    )
    sys.exit(1)


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS generated_report (
    id UUID PRIMARY KEY,
    legal_entity_id UUID NOT NULL,
    report_number VARCHAR(50) NOT NULL UNIQUE,
    report_type VARCHAR(40) NOT NULL,
    report_format VARCHAR(10) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    file_path TEXT,
    file_size_bytes INTEGER,
    parameters JSON,
    error_message TEXT,
    generated_at TIMESTAMP NOT NULL,
    generated_by UUID NOT NULL,
    generated_by_name VARCHAR(200),
    expires_at TIMESTAMP,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMP,
    deleted_by UUID,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
)
"""

STATEMENTS: list[str] = [
    CREATE_TABLE_SQL,
    "CREATE INDEX IF NOT EXISTS ix_generated_report_legal_entity ON generated_report (legal_entity_id)",
    "CREATE INDEX IF NOT EXISTS ix_generated_report_type ON generated_report (report_type)",
    "CREATE INDEX IF NOT EXISTS ix_generated_report_status ON generated_report (status)",
    "CREATE INDEX IF NOT EXISTS ix_generated_report_generated_at ON generated_report (generated_at)",
]

EXPECTED_COLUMNS = {
    "id", "legal_entity_id", "report_number", "report_type", "report_format",
    "status", "file_path", "file_size_bytes", "parameters", "error_message",
    "generated_at", "generated_by", "generated_by_name", "expires_at",
    "is_deleted", "deleted_at", "deleted_by", "created_at",
}


def _normalize_dsn(raw_url: str) -> str:
    if raw_url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + raw_url[len("postgresql+asyncpg://"):]
    if raw_url.startswith("postgres+asyncpg://"):
        return "postgresql://" + raw_url[len("postgres+asyncpg://"):]
    return raw_url


def _resolve_dsn(cli_url: str | None) -> str:
    dsn = cli_url or os.environ.get("DATABASE_URL")
    if not dsn:
        print(
            "ERROR: DATABASE_URL tidak diset dan --database-url tidak diberikan.\n"
            "Contoh (PowerShell):\n"
            '  $env:DATABASE_URL="postgresql+asyncpg://postgres:PASSWORD@127.0.0.1:5432/erp_db"\n'
            "  python scripts/create_generated_report_table.py",
            file=sys.stderr,
        )
        sys.exit(1)
    return _normalize_dsn(dsn)


async def run(dsn: str) -> None:
    print(f"Menghubungkan ke database... ({dsn.split('@')[-1]})")
    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            for stmt in STATEMENTS:
                print(f"  > {stmt.strip().splitlines()[0]}...")
                await conn.execute(stmt)

        rows = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'generated_report'"
        )
        existing_columns = {r["column_name"] for r in rows}
        missing = EXPECTED_COLUMNS - existing_columns
        if missing:
            print(f"WARNING: kolom berikut masih belum ada setelah dijalankan: {missing}", file=sys.stderr)
            sys.exit(1)

        print("\nOK - tabel 'generated_report' sudah siap dipakai.")
        print("Restart uvicorn supaya SQLAlchemy ORM membaca skema terbaru.")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override DATABASE_URL (kalau tidak diberikan, dibaca dari environment variable DATABASE_URL)",
    )
    args = parser.parse_args()
    dsn = _resolve_dsn(args.database_url)
    asyncio.run(run(dsn))


if __name__ == "__main__":
    main()
