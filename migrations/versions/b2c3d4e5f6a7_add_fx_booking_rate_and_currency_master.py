"""add_fx_booking_rate_and_currency_master

Dua perbaikan sekaligus untuk modul Forex:

1. journal_line SEBELUMNYA tidak pernah menyimpan kurs yang dipakai saat
   transaksi dibukukan (booking_rate) maupun jumlah asli dalam mata uang
   asing terpisah dari nilai yang dibukukan (fc_amount) - cuma ada kolom
   `amount` tunggal + `currency`. Tanpa ini, unrealized gain/loss forex
   TIDAK BISA dihitung akurat (butuh baseline "dibukukan di kurs berapa"
   dibanding kurs sekarang). Tambah fc_amount & booking_rate, nullable
   (baris lama tidak punya data ini, akan dikecualikan dari perhitungan
   gain/loss sampai dibukukan ulang atau diisi manual).

2. Tabel currency_master baru - sebelumnya daftar mata uang di-hardcode
   sebagai Python Enum (CurrencyCode) di fastapi_forex_router.py, jadi
   fitur "Tambah Mata Uang Baru" di UI selalu gagal (endpoint /currencies
   memang belum pernah dibuat, dan validasi Enum tetap menolak mata uang
   di luar daftar hardcode itu meskipun endpoint-nya ada). Diseed dengan
   nilai enum lama supaya tidak ada regresi untuk mata uang yang sudah
   dipakai.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-14 05:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    for ddl in (
        "ALTER TABLE journal_line ADD COLUMN IF NOT EXISTS fc_amount NUMERIC(20, 4)",
        "ALTER TABLE journal_line ADD COLUMN IF NOT EXISTS booking_rate NUMERIC(20, 6)",
    ):
        bind.execute(text(ddl))

    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS currency_master (
            code VARCHAR(3) PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            symbol VARCHAR(10),
            decimal_places INTEGER NOT NULL DEFAULT 2,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by UUID
        );
    """))

    # Seed dengan nilai CurrencyCode enum lama supaya kurs/entitas yang
    # sudah pakai kode2 ini tidak tiba2 dianggap "tidak valid".
    seed_rows = [
        ("IDR", "Indonesian Rupiah", "Rp", 0),
        ("USD", "US Dollar", "$", 2),
        ("EUR", "Euro", "€", 2),
        ("SGD", "Singapore Dollar", "S$", 2),
        ("JPY", "Japanese Yen", "¥", 0),
        ("CNY", "Chinese Yuan", "¥", 2),
        ("GBP", "British Pound", "£", 2),
        ("AUD", "Australian Dollar", "A$", 2),
        ("MYR", "Malaysian Ringgit", "RM", 2),
        ("THB", "Thai Baht", "฿", 2),
        ("KRW", "Korean Won", "₩", 0),
        ("HKD", "Hong Kong Dollar", "HK$", 2),
        ("CHF", "Swiss Franc", "Fr", 2),
        ("CAD", "Canadian Dollar", "C$", 2),
        ("SAR", "Saudi Riyal", "﷼", 2),
        ("INR", "Indian Rupee", "₹", 2),
    ]
    for code, name, symbol, decimals in seed_rows:
        bind.execute(text("""
            INSERT INTO currency_master (code, name, symbol, decimal_places, is_active)
            VALUES (:code, :name, :symbol, :decimals, true)
            ON CONFLICT (code) DO NOTHING;
        """), {"code": code, "name": name, "symbol": symbol, "decimals": decimals})


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS currency_master;")
    op.execute("ALTER TABLE journal_line DROP COLUMN IF EXISTS fc_amount;")
    op.execute("ALTER TABLE journal_line DROP COLUMN IF EXISTS booking_rate;")
