"""extend chart of accounts (account table) with production-grade COA fields

Menambahkan kolom yang sebelumnya HANYA dipakai oleh
fastapi_coa_router.py / frontend coa_page.py secara "virtual" (tidak
benar-benar tersimpan di DB, lihat catatan lama di service_coa.py):
category -> account_group, budget_control, is_locked, dsb. Juga
menambah field pelaporan tambahan (tax_code, cashflow_type,
account_name_en, sort_order, allow_posting, reconciliation_required)
sesuai kebutuhan COA production (lihat dokumentasi COA yang dilampirkan).

Revision ID: 0047coa
Revises: journal_header_fix_001
Create Date: 2026-08-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision: str = "0047coa"
down_revision: Union[str, None] = "journal_header_fix_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("account", sa.Column("account_name_en", sa.String(200), nullable=True))
    op.add_column("account", sa.Column("account_group", sa.String(100), nullable=True))
    op.add_column("account", sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"))
    op.add_column("account", sa.Column("allow_posting", sa.Boolean, nullable=False, server_default="true"))
    op.add_column("account", sa.Column("budget_control", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("account", sa.Column("reconciliation_required", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("account", sa.Column("tax_code", sa.String(30), nullable=True))
    op.add_column("account", sa.Column("cashflow_type", sa.String(20), nullable=True))
    op.add_column("account", sa.Column("is_locked", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("account", sa.Column("lock_reason", sa.String(500), nullable=True))
    op.add_column("account", sa.Column("updated_by", PGUUID(as_uuid=True), nullable=True))

    # `level` di migration lama diberi CHECK 1..10 dengan default server '1'.
    # Root account (tanpa parent) secara konsep ada di level 0 supaya anak
    # langsungnya level 1, dst — selaraskan constraint dan default.
    op.alter_column("account", "level", server_default="0")
    op.drop_constraint("ck_account_level", "account", type_="check")
    op.create_check_constraint("ck_account_level", "account", "level BETWEEN 0 AND 10")

    op.create_check_constraint(
        "ck_account_cashflow_type",
        "account",
        "cashflow_type IS NULL OR cashflow_type IN ('operating', 'investing', 'financing')",
    )
    op.create_check_constraint(
        "ck_account_status",
        "account",
        "status IN ('active', 'inactive', 'suspended', 'locked', 'archived')",
    )

    op.create_index("idx_account_group", "account", ["account_group"])
    op.create_index("idx_account_sort_order", "account", ["sort_order"])

    # Backfill: akun yang lama-lama dibuat dengan status non-standar (mis.
    # hanya 'active'/'inactive' dari constraint versi 0002) tetap valid;
    # tidak ada backfill data diperlukan untuk kolom baru (semua nullable
    # atau punya default aman).


def downgrade() -> None:
    op.drop_index("idx_account_sort_order", table_name="account")
    op.drop_index("idx_account_group", table_name="account")

    op.drop_constraint("ck_account_status", "account", type_="check")
    op.create_check_constraint(
        "ck_account_status", "account", "status IN ('active', 'inactive', 'suspended')"
    )
    op.drop_constraint("ck_account_cashflow_type", "account", type_="check")

    op.drop_constraint("ck_account_level", "account", type_="check")
    op.create_check_constraint("ck_account_level", "account", "level BETWEEN 1 AND 10")
    op.alter_column("account", "level", server_default="1")

    op.drop_column("account", "updated_by")
    op.drop_column("account", "lock_reason")
    op.drop_column("account", "is_locked")
    op.drop_column("account", "cashflow_type")
    op.drop_column("account", "tax_code")
    op.drop_column("account", "reconciliation_required")
    op.drop_column("account", "budget_control")
    op.drop_column("account", "allow_posting")
    op.drop_column("account", "sort_order")
    op.drop_column("account", "account_group")
    op.drop_column("account", "account_name_en")
