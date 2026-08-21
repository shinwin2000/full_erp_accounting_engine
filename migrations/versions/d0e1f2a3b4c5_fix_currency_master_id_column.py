"""fix_currency_master_id_column

Bug: migrasi sebelumnya (b2c3d4e5f6a7) membuat tabel currency_master
dengan `code` sebagai primary key, TANPA kolom `id`. Tapi class dasar
ORM bersama (infrastructure.persistence_orm.base_model.Base) otomatis
menambahkan kolom `id: Mapped[UUID]` ke SEMUA tabel turunannya -
CurrencyMasterTable(Base) ikut mewarisi ini meskipun tidak diminta
eksplisit. Akibatnya query SELECT selalu menyertakan "currency_master.id"
yang tidak ada di skema DB asli -> UndefinedColumnError setiap endpoint
/forex/forex/currencies dipanggil.

Fix: tambah kolom id (UUID, default gen_random_uuid()), isi untuk baris
yang sudah ada, jadikan primary key baru menggantikan code. code tetap
unique (bukan lagi PK) supaya kompatibel dengan lookup by-code yang
sudah ada di service/repo.

Revision ID: d0e1f2a3b4c5
Revises: b2c3d4e5f6a7
Create Date: 2026-08-18 07:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Tambah kolom id, isi untuk baris existing (dari seed migrasi
    #    sebelumnya), baru jadikan NOT NULL.
    bind.execute(text(
        "ALTER TABLE currency_master ADD COLUMN IF NOT EXISTS id UUID DEFAULT gen_random_uuid();"
    ))
    bind.execute(text(
        "UPDATE currency_master SET id = gen_random_uuid() WHERE id IS NULL;"
    ))
    bind.execute(text(
        "ALTER TABLE currency_master ALTER COLUMN id SET NOT NULL;"
    ))

    # 2) Lepas code dari primary key, jadikan id primary key baru, code
    #    tetap unique (dipakai lookup by-code di service/repo).
    bind.execute(text("""
        DO $$
        BEGIN
            ALTER TABLE currency_master DROP CONSTRAINT currency_master_pkey;
        EXCEPTION
            WHEN undefined_object THEN NULL;
        END $$;
    """))
    bind.execute(text("ALTER TABLE currency_master ADD PRIMARY KEY (id);"))
    bind.execute(text("""
        DO $$
        BEGIN
            ALTER TABLE currency_master ADD CONSTRAINT uq_currency_master_code UNIQUE (code);
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
    """))


def downgrade() -> None:
    op.execute("ALTER TABLE currency_master DROP CONSTRAINT IF EXISTS uq_currency_master_code;")
    op.execute("ALTER TABLE currency_master DROP CONSTRAINT IF EXISTS currency_master_pkey;")
    op.execute("ALTER TABLE currency_master ADD PRIMARY KEY (code);")
    op.execute("ALTER TABLE currency_master DROP COLUMN IF EXISTS id;")
