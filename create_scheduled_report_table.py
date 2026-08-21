#!/usr/bin/env python3
"""
create_scheduled_report_table.py

Perbaikan modul Reports (Tier 2 - penjadwalan): membuat tabel
`scheduled_report` yang dipakai untuk menyimpan konfigurasi jadwal laporan
otomatis (POST/GET/PUT/DELETE /api/v1/reports/schedule di
fastapi_report_router.py). Tabel ini belum ada di database manapun
sebelumnya.

Idempotent (CREATE TABLE IF NOT EXISTS), aman dijalankan berkali-kali.

Cara pakai:
    python scripts/create_scheduled_report_table.py
    python scripts/create_scheduled_report_table.py --database-url "postgresql://postgres:PASSWORD@127.0.0.1:5432/erp_db"
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
CREATE TABLE IF NOT EXISTS scheduled_report (
    id UUID PRIMARY KEY,
    legal_entity_id UUID NOT NULL,
    schedule_name VARCHAR(200) NOT NULL,
    report_type VARCHAR(40) NOT NULL,
    schedule_frequency VARCHAR(20) NOT NULL,
    schedule_time VARCHAR(5),
    schedule_day_of_week INTEGER,
    schedule_day_of_month INTEGER,
    report_format VARCHAR(10) NOT NULL DEFAULT 'pdf',
    parameters JSON NOT NULL DEFAULT '{}',
    recipient_emails JSON NOT NULL DEFAULT '[]',
    recipient_whatsapps JSON NOT NULL DEFAULT '[]',
    delivery_methods JSON NOT NULL DEFAULT '[]',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT,
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_by UUID NOT NULL,
    updated_by UUID,
    created_by_name VARCHAR(200),
    version INTEGER NOT NULL DEFAULT 1
)
"""

STATEMENTS: list[str] = [
    CREATE_TABLE_SQL,
    "CREATE INDEX IF NOT EXISTS ix_scheduled_report_legal_entity ON scheduled_report (legal_entity_id)",
    "CREATE INDEX IF NOT EXISTS ix_scheduled_report_type ON scheduled_report (report_type)",
    "CREATE INDEX IF NOT EXISTS ix_scheduled_report_active ON scheduled_report (is_active)",
    "CREATE INDEX IF NOT EXISTS ix_scheduled_report_next_run ON scheduled_report (next_run_at)",
]

EXPECTED_COLUMNS = {
    "id", "legal_entity_id", "schedule_name", "report_type", "schedule_frequency",
    "schedule_time", "schedule_day_of_week", "schedule_day_of_month", "report_format",
    "parameters", "recipient_emails", "recipient_whatsapps", "delivery_methods",
    "is_active", "notes", "last_run_at", "next_run_at", "created_at", "updated_at",
    "created_by", "updated_by", "created_by_name", "version",
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
            "  python scripts/create_scheduled_report_table.py",
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
            "WHERE table_name = 'scheduled_report'"
        )
        existing_columns = {r["column_name"] for r in rows}
        missing = EXPECTED_COLUMNS - existing_columns
        if missing:
            print(f"WARNING: kolom berikut masih belum ada setelah dijalankan: {missing}", file=sys.stderr)
            sys.exit(1)

        print("\nOK - tabel 'scheduled_report' sudah siap dipakai.")
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
