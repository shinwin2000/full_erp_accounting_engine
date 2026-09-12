from __future__ import annotations

"""
fix_budget_table_schema.py
===========================
Perbaikan darurat untuk schema drift tabel `budget`.

MASALAH:
    Model ORM `BudgetTable` (infrastructure/persistence_orm/budget_table.py)
    punya kolom `version_label` (String, label budget mis. "1.0"), terpisah
    dari kolom `version` bawaan `VersionMixin` (Integer, dipakai untuk
    optimistic locking).

    Migrasi awal (2cd2bd2d5b07_add_budget_table.py) hanya membuat SATU kolom
    bernama `version` bertipe String(20) — tidak pernah membuat kolom
    `version_label` sama sekali, dan tipe kolom `version` tidak cocok dengan
    yang dibutuhkan VersionMixin (Integer). Akibatnya SETIAP query yang
    men-select BudgetTable (list, dashboard, alerts, get, dst.) gagal dengan:

        asyncpg.exceptions.UndefinedColumnError: column budget.version_label
        does not exist

    Migrasi lain (81de37e7a243_sync_budget_table_columns.py) yang seharusnya
    bisa memperbaiki ini berada di cabang Alembic yang terpisah dan tidak
    pernah bertemu dengan cabang tempat tabel `budget` dibuat (repo ini
    punya 20+ head migration yang belum di-merge — masalah terpisah dari
    budget module, lihat catatan di akhir file ini).

APA YANG DILAKUKAN SCRIPT INI (idempotent, aman dijalankan berkali-kali):
    1. Jika kolom `version_label` belum ada -> tambahkan (VARCHAR(20)).
    2. Jika kolom `version` lama (String) masih menyimpan label budget
       (mis. "1.0", "2.1") -> salin isinya ke `version_label` dulu supaya
       tidak ada data yang hilang.
    3. Set `version_label` NOT NULL DEFAULT '1.0'.
    4. Jika kolom `version` BUKAN integer -> ubah tipenya jadi INTEGER
       (dipakai sebagai optimistic-lock counter oleh VersionMixin). Nilai
       lama yang tidak bisa di-parse sebagai integer di-reset ke 1 (aman,
       karena ini cuma counter konkurensi, bukan data bisnis).
    5. Set `version` NOT NULL DEFAULT 1.

CARA PAKAI:
    Jalankan langsung terhadap Postgres, tidak butuh Alembic:

        python deployment/scripts/fix_budget_table_schema.py

    Script membaca DATABASE_URL dari environment (format yang sama dengan
    yang dipakai app: postgresql+asyncpg://user:pass@host:port/db). Bisa
    override lewat argumen: --database-url "postgresql://..."

CATATAN PENTING (di luar scope budget module, tapi wajib diketahui):
    Folder migrations/versions/ punya lebih dari 20 head yang belum
    di-merge (cek dengan `alembic heads`). Ini artinya `alembic upgrade
    head` kemungkinan besar akan gagal dengan error "Multiple head
    revisions". Sebuah migrasi baru (lihat
    migrations/versions/<rev>_fix_budget_version_columns.py) sudah dibuat
    untuk mencatat perbaikan ini secara resmi di riwayat migrasi begitu
    head-head tersebut sudah di-merge (`alembic merge heads`), tapi
    JANGAN mengandalkan itu untuk perbaikan langsung — pakai script ini
    dulu untuk unblock development sekarang.
"""

import argparse
import asyncio
import os
import re
import sys


def _normalize_dsn(dsn: str) -> str:
    """asyncpg.connect() tidak mengerti dialect suffix SQLAlchemy (+asyncpg)."""
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", dsn)


async def _run(dsn: str) -> None:
    try:
        import asyncpg
    except ImportError:
        print(
            "ERROR: paket 'asyncpg' tidak ditemukan di environment ini. "
            "Jalankan script ini dari virtualenv yang sama dengan aplikasi.",
            file=sys.stderr,
        )
        sys.exit(1)

    conn = await asyncpg.connect(dsn)
    try:
        table_exists = await conn.fetchval(
            "SELECT to_regclass('public.budget') IS NOT NULL"
        )
        if not table_exists:
            print("Tabel 'budget' belum ada — tidak ada yang perlu diperbaiki "
                  "(kemungkinan migrasi awal belum pernah dijalankan sama sekali).")
            return

        columns = await conn.fetch(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'budget'
            """
        )
        col_types = {row["column_name"]: row["data_type"] for row in columns}

        has_version = "version" in col_types
        has_version_label = "version_label" in col_types

        async with conn.transaction():
            # 1) Tambahkan version_label kalau belum ada
            if not has_version_label:
                print("[1/5] Menambahkan kolom 'version_label' (VARCHAR(20))...")
                await conn.execute(
                    "ALTER TABLE budget ADD COLUMN version_label VARCHAR(20)"
                )
            else:
                print("[1/5] Kolom 'version_label' sudah ada, lewati.")

            # 2) Salin data lama dari 'version' (kalau dulu bertipe teks/label)
            #    ke 'version_label', supaya label budget yang sudah ada tidak hilang.
            if has_version and col_types.get("version") in (
                "character varying", "text", "varchar",
            ):
                print("[2/5] Menyalin nilai label lama dari kolom 'version' "
                      "(teks) ke 'version_label'...")
                await conn.execute(
                    """
                    UPDATE budget
                    SET version_label = version
                    WHERE version_label IS NULL AND version IS NOT NULL
                    """
                )
            else:
                print("[2/5] Kolom 'version' bukan teks (atau tidak ada), "
                      "tidak ada yang perlu disalin.")

            # 3) Backfill sisa NULL, lalu set NOT NULL DEFAULT '1.0'
            print("[3/5] Backfill version_label kosong -> '1.0', set NOT NULL DEFAULT...")
            await conn.execute(
                "UPDATE budget SET version_label = '1.0' WHERE version_label IS NULL"
            )
            await conn.execute(
                "ALTER TABLE budget ALTER COLUMN version_label SET DEFAULT '1.0'"
            )
            await conn.execute(
                "ALTER TABLE budget ALTER COLUMN version_label SET NOT NULL"
            )

            # 4) Pastikan kolom 'version' bertipe INTEGER (dipakai VersionMixin
            #    sebagai optimistic-lock counter, bukan label budget lagi).
            if not has_version:
                print("[4/5] Kolom 'version' tidak ada, menambahkan sebagai "
                      "INTEGER NOT NULL DEFAULT 1...")
                await conn.execute(
                    "ALTER TABLE budget ADD COLUMN version INTEGER NOT NULL DEFAULT 1"
                )
            elif col_types.get("version") != "integer":
                print(f"[4/5] Kolom 'version' saat ini bertipe "
                      f"'{col_types.get('version')}', mengubah ke INTEGER "
                      f"(nilai lama yang tidak berbentuk angka di-reset ke 1)...")
                await conn.execute(
                    """
                    ALTER TABLE budget
                    ALTER COLUMN version TYPE INTEGER
                    USING (
                        CASE
                            WHEN version::text ~ '^[0-9]+$' THEN version::text::integer
                            ELSE 1
                        END
                    )
                    """
                )
                await conn.execute(
                    "ALTER TABLE budget ALTER COLUMN version SET DEFAULT 1"
                )
                await conn.execute(
                    "ALTER TABLE budget ALTER COLUMN version SET NOT NULL"
                )
            else:
                print("[4/5] Kolom 'version' sudah INTEGER, lewati.")

            print("[5/5] Selesai.")

        # Verifikasi akhir
        final_cols = await conn.fetch(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'budget'
              AND column_name IN ('version', 'version_label')
            ORDER BY column_name
            """
        )
        print("\nStatus akhir kolom 'budget':")
        for row in final_cols:
            print(f"  - {row['column_name']}: {row['data_type']}, "
                  f"nullable={row['is_nullable']}, default={row['column_default']}")

    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Postgres DSN (default: env DATABASE_URL)",
    )
    args = parser.parse_args()

    if not args.database_url:
        print("ERROR: DATABASE_URL tidak diset dan --database-url tidak diberikan.",
              file=sys.stderr)
        sys.exit(1)

    dsn = _normalize_dsn(args.database_url)
    asyncio.run(_run(dsn))


if __name__ == "__main__":
    main()
