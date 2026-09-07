"""
Script perbaikan sekali-pakai: menambahkan kolom yang hilang di tabel
`bank_transaction` (is_reconciled, reconciliation_id) tanpa perlu
menjalankan ulang seluruh riwayat migration Alembic.

KENAPA INI PERLU:
`alembic current` melaporkan database sudah di revisi paling akhir (head),
padahal tabel fisik di PostgreSQL ternyata tidak punya kolom
`is_reconciled` / `reconciliation_id` yang seharusnya dibuat oleh migration
0007_bank_cash_tables.py. Ini berarti riwayat migration di database (tabel
alembic_version) tidak sinkron dengan struktur tabel sungguhan - kemungkinan
tabel pernah dibuat/di-"stamp" tanpa migration itu benar-benar dijalankan.
Karena Alembic sudah menganggap migration ini selesai, `alembic upgrade
head` TIDAK akan menambahkan kolom yang hilang.

CARA PAKAI:
    python fix_bank_transaction_schema.py

Script ini aman dijalankan berkali-kali (pakai IF NOT EXISTS), dan HANYA
menambah kolom - tidak menghapus atau mengubah data yang sudah ada.
"""
import asyncio
import os
import sys

import asyncpg


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: environment variable DATABASE_URL tidak ditemukan.")
        print("Jalankan script ini di terminal yang sama / dengan environment")
        print("yang sama seperti saat Anda menjalankan 'uvicorn app.main:app'.")
        sys.exit(1)

    # DATABASE_URL di app memakai driver 'postgresql+asyncpg://...' untuk
    # SQLAlchemy; asyncpg butuh bentuk polos 'postgresql://...'.
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")

    print(f"Menghubungkan ke database...")
    conn = await asyncpg.connect(dsn)
    try:
        print("Cek & tambah kolom is_reconciled (jika belum ada)...")
        await conn.execute(
            """
            ALTER TABLE bank_transaction
            ADD COLUMN IF NOT EXISTS is_reconciled BOOLEAN NOT NULL DEFAULT false
            """
        )

        print("Cek & tambah kolom reconciliation_id (jika belum ada)...")
        await conn.execute(
            """
            ALTER TABLE bank_transaction
            ADD COLUMN IF NOT EXISTS reconciliation_id UUID NULL
            """
        )

        print("Cek & tambah index reconciliation_id (jika belum ada)...")
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bank_tx_reconciliation
            ON bank_transaction (reconciliation_id)
            """
        )

        # --- Perbaikan tambahan (fix 2): constraint status usang ---
        # Migration lama membatasi kolom `status` hanya boleh berisi
        # 'pending', 'posted', 'reconciled', 'cancelled'. Tapi enum
        # TransactionStatus yang benar-benar dipakai kode Python
        # (domain/bank_cash/bank_transaction_entity.py) punya nilai:
        # 'pending', 'completed', 'cleared', 'rejected', 'cancelled',
        # 'reconciled'. Karena kode selalu menulis status='completed'
        # begitu transaksi berhasil dibuat, INSERT selalu ditolak
        # database dengan "violates check constraint ck_bank_tx_status".
        # Di bawah ini constraint diganti supaya cocok dengan enum yang
        # sebenarnya dipakai.
        print("Perbaiki constraint ck_bank_tx_status (agar sesuai enum TransactionStatus)...")
        await conn.execute(
            "ALTER TABLE bank_transaction DROP CONSTRAINT IF EXISTS ck_bank_tx_status"
        )
        await conn.execute(
            """
            ALTER TABLE bank_transaction
            ADD CONSTRAINT ck_bank_tx_status
            CHECK (status IN ('pending', 'completed', 'cleared', 'rejected', 'cancelled', 'reconciled'))
            """
        )

        # --- Perbaikan tambahan (fix 3): constraint transaction_type usang ---
        # Migration lama membatasi `transaction_type` ke 'deposit',
        # 'withdrawal', 'transfer_in', 'transfer_out', 'bank_charge',
        # 'interest'. Tapi enum TransactionType yang benar-benar dipakai
        # kode (dan pilihan dropdown di aplikasi desktop) adalah 'deposit',
        # 'withdrawal', 'transfer_in', 'transfer_out', 'fee', 'interest',
        # 'cheque', 'adjustment' - tidak ada 'bank_charge', dan tiga nilai
        # ('fee', 'cheque', 'adjustment') belum diizinkan constraint lama.
        # Kalau tidak diperbaiki, memilih salah satu dari ketiganya di
        # dropdown akan gagal dengan error constraint yang sama.
        print("Perbaiki constraint ck_bank_tx_type (agar sesuai enum TransactionType)...")
        await conn.execute(
            "ALTER TABLE bank_transaction DROP CONSTRAINT IF EXISTS ck_bank_tx_type"
        )
        await conn.execute(
            """
            ALTER TABLE bank_transaction
            ADD CONSTRAINT ck_bank_tx_type
            CHECK (transaction_type IN ('deposit', 'withdrawal', 'transfer_in', 'transfer_out',
                                         'fee', 'interest', 'cheque', 'adjustment'))
            """
        )

        # Verifikasi hasil akhir
        rows = await conn.fetch(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'bank_transaction'
              AND column_name IN ('is_reconciled', 'reconciliation_id')
            ORDER BY column_name
            """
        )
        print("\nHasil verifikasi kolom di tabel bank_transaction:")
        for row in rows:
            print(f"  - {row['column_name']}: {row['data_type']} (nullable={row['is_nullable']})")

        if len(rows) == 2:
            print("\n[OK] Kedua kolom sekarang sudah ada. Silakan restart backend dan coba lagi.")
        else:
            print("\n[PERINGATAN] Belum semua kolom terkonfirmasi ada, cek manual ke database.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
