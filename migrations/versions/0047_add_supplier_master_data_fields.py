"""add missing supplier master data fields (company_name, tax_name, mobile,
province, credit_limit, opening_balance, opening_balance_date, remarks)

Revision ID: supp_0047_master_data
Revises: 0046
Create Date: 2026-08-07 00:00:00.000000

Context:
    Modul Supplier/Vendor sebelumnya tidak sinkron antara Frontend, Backend
    Service, dan Database: field `credit_limit` sudah dipakai di request
    frontend & router tapi kolomnya TIDAK PERNAH ADA di tabel `supplier`.
    Migration ini menambahkan seluruh kolom yang dibutuhkan supaya form
    Tambah/Ubah Supplier di frontend benar-benar bisa disimpan & dibaca
    kembali dari database (lihat juga service_supplier.py &
    fastapi_supplier_router.py yang direfactor bersamaan dengan migration
    ini).

    CATATAN: revision ID sengaja dibuat berupa string unik
    "supp_0047_master_data" (bukan angka polos "0047") karena project ini
    ternyata sudah punya file migration lain dengan revision id "0047" —
    alembic mencocokkan berdasarkan isi variabel `revision`, bukan nama
    file, sehingga dua file boleh punya nama mirip asal revision id-nya
    unik.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import NUMERIC

revision: str = "supp_0047_master_data"
down_revision: Union[str, None] = "0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("supplier", sa.Column("company_name", sa.String(200), nullable=True))
    op.add_column("supplier", sa.Column("tax_name", sa.String(200), nullable=True))
    op.add_column("supplier", sa.Column("province", sa.String(100), nullable=True))
    op.add_column("supplier", sa.Column("mobile", sa.String(20), nullable=True))
    op.add_column(
        "supplier",
        sa.Column("credit_limit", NUMERIC(20, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "supplier",
        sa.Column("opening_balance", NUMERIC(20, 2), nullable=False, server_default="0"),
    )
    op.add_column("supplier", sa.Column("opening_balance_date", sa.Date, nullable=True))
    op.add_column("supplier", sa.Column("remarks", sa.Text, nullable=True))

    # credit_limit / opening_balance tidak boleh negatif, sesuai kebijakan
    # bisnis (lihat dokumen requirement modul Supplier bagian "Validasi Backend").
    op.create_check_constraint(
        "ck_supplier_credit_limit_nonneg", "supplier", "credit_limit >= 0"
    )
    op.create_check_constraint(
        "ck_supplier_opening_balance_nonneg", "supplier", "opening_balance >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_supplier_credit_limit_nonneg", "supplier", type_="check")
    op.drop_constraint("ck_supplier_opening_balance_nonneg", "supplier", type_="check")
    op.drop_column("supplier", "remarks")
    op.drop_column("supplier", "opening_balance_date")
    op.drop_column("supplier", "opening_balance")
    op.drop_column("supplier", "credit_limit")
    op.drop_column("supplier", "mobile")
    op.drop_column("supplier", "province")
    op.drop_column("supplier", "tax_name")
    op.drop_column("supplier", "company_name")
