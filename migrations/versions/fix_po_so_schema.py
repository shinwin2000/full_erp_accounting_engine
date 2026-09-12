"""reconcile purchase_order / sales_order schema with API contract

Revision ID: fix_po_so_schema
Revises: fix_budget_version_label
Create Date: 2026-09-11

LATAR BELAKANG (temuan investigasi):
Endpoint Purchase Order & Sales Order (fastapi_purchase_sales_router.py)
sudah sejak awal memanggil PurchaseSalesService dengan kontrak field
`item_id/item_code/item_name/discount_percent/tax_rate/description` dan
mengharapkan response dengan field lengkap seperti `invoiced_amount`,
`order_type`, `rejected_at/rejected_by/rejection_reason`,
`cancelled_at/cancelled_by`, `closed_at`, `is_locked`, dll.

Tapi riwayat migrasi tabel `purchase_order_line` & `sales_order_line`
sangat berantakan -- berkali-kali di-drop, dibuat ulang, dan di-"sync"
otomatis (lihat 0044_sync_orm_columns.py & 0046_..._partitioning_.py)
sampai akhirnya kolom-kolom penting seperti item_id/discount_percent/
tax_rate/legal_entity_id/total_amount HILANG dari purchase_order_line,
diganti nama jadi product_id/product_code/product_name/total_price/
unit_of_measure yang TIDAK dipakai API sama sekali. Tabel header
`purchase_order`/`sales_order` juga tidak pernah punya kolom untuk
melacak invoiced_amount/order_type/rejected_*/cancelled_*/closed_at/
is_locked meski API & router sudah mengharapkannya sejak awal.

Migrasi ini MEREKONSILIASI skema ke kontrak API yang sebenarnya dipakai,
dengan idempotent check (aman dijalankan berkali-kali / dari kondisi
skema apa pun peninggalan migrasi-migrasi sebelumnya).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'fix_po_so_schema'
down_revision = 'fix_budget_version_label'
branch_labels = None
depends_on = None


def _cols(inspector, table_name: str) -> dict:
    if table_name not in inspector.get_table_names():
        return None
    return {c["name"]: c for c in inspector.get_columns(table_name)}


def _add_col_if_missing(table_name: str, col: sa.Column, existing_cols: dict) -> None:
    if col.name not in existing_cols:
        op.add_column(table_name, col)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ========================================================================
    # 1) HEADER `purchase_order` -- tambah kolom yang selama ini hilang
    #    (dibutuhkan PurchaseOrderResponseSchema tapi tidak pernah ada).
    # ========================================================================
    po_cols = _cols(inspector, "purchase_order")
    if po_cols is not None:
        _add_col_if_missing("purchase_order", sa.Column("invoiced_amount", sa.Numeric(20, 2), nullable=False, server_default="0"), po_cols)
        _add_col_if_missing("purchase_order", sa.Column("order_type", sa.String(20), nullable=False, server_default="standard"), po_cols)
        _add_col_if_missing("purchase_order", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True), po_cols)
        _add_col_if_missing("purchase_order", sa.Column("rejected_by", postgresql.UUID(as_uuid=True), nullable=True), po_cols)
        _add_col_if_missing("purchase_order", sa.Column("rejection_reason", sa.Text(), nullable=True), po_cols)
        _add_col_if_missing("purchase_order", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True), po_cols)
        _add_col_if_missing("purchase_order", sa.Column("cancelled_by", postgresql.UUID(as_uuid=True), nullable=True), po_cols)
        _add_col_if_missing("purchase_order", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True), po_cols)
        _add_col_if_missing("purchase_order", sa.Column("is_locked", sa.Boolean(), nullable=False, server_default="false"), po_cols)

        # Ganti CHECK constraint status: constraint lama cuma izinkan 7 nilai,
        # padahal PurchaseOrderStatus (enum di router) punya jauh lebih
        # banyak status (rejected, pending_approval, partially_invoiced, dst).
        # Tanpa ini, reject_purchase_order() akan gagal dengan
        # CheckViolationError begitu status di-set 'rejected'.
        try:
            op.drop_constraint("ck_po_status", "purchase_order", type_="check")
        except Exception:
            pass
        op.create_check_constraint(
            "ck_po_status",
            "purchase_order",
            "status IN ('draft','submitted','pending_approval','approved','rejected',"
            "'partially_received','fully_received','partially_invoiced','fully_invoiced',"
            "'partially_paid','paid','cancelled','closed','locked','archived')",
        )

    # ========================================================================
    # 2) HEADER `sales_order` -- kolom yang sama, sisi Sales Order.
    # ========================================================================
    so_cols = _cols(inspector, "sales_order")
    if so_cols is not None:
        _add_col_if_missing("sales_order", sa.Column("order_type", sa.String(20), nullable=False, server_default="standard"), so_cols)
        _add_col_if_missing("sales_order", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True), so_cols)
        _add_col_if_missing("sales_order", sa.Column("rejected_by", postgresql.UUID(as_uuid=True), nullable=True), so_cols)
        _add_col_if_missing("sales_order", sa.Column("rejection_reason", sa.Text(), nullable=True), so_cols)
        _add_col_if_missing("sales_order", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True), so_cols)
        _add_col_if_missing("sales_order", sa.Column("cancelled_by", postgresql.UUID(as_uuid=True), nullable=True), so_cols)
        _add_col_if_missing("sales_order", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True), so_cols)
        _add_col_if_missing("sales_order", sa.Column("is_locked", sa.Boolean(), nullable=False, server_default="false"), so_cols)
        try:
            op.drop_constraint("ck_so_status", "sales_order", type_="check")
        except Exception:
            pass
        try:
            op.create_check_constraint(
                "ck_so_status",
                "sales_order",
                "status IN ('draft','submitted','pending_approval','approved','rejected',"
                "'partially_shipped','fully_shipped','partially_invoiced','fully_invoiced',"
                "'partially_paid','paid','cancelled','closed','locked','archived')",
            )
        except Exception:
            pass

    # ========================================================================
    # 3) LINE `purchase_order_line` -- rekonsiliasi total ke kontrak
    #    POLineSchema (item_id/item_code/item_name/discount_percent/
    #    tax_rate/total_amount/notes), TERLEPAS dari kondisi kolom
    #    sekarang (bisa jadi masih product_id/total_price/unit_of_measure
    #    peninggalan migrasi 0044/0046, atau malah tabelnya sudah tidak
    #    ada karena sempat ke-drop oleh 81de37e7a243).
    # ========================================================================
    pol_cols = _cols(inspector, "purchase_order_line")
    if pol_cols is None:
        op.create_table(
            "purchase_order_line",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("purchase_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_order.id", ondelete="CASCADE"), nullable=False),
            sa.Column("line_number", sa.Integer(), nullable=False),
            sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("item_code", sa.String(50), nullable=False, server_default=""),
            sa.Column("item_name", sa.String(200), nullable=False, server_default=""),
            sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
            sa.Column("received_quantity", sa.Numeric(20, 6), nullable=False, server_default="0"),
            sa.Column("unit_price", sa.Numeric(20, 2), nullable=False),
            sa.Column("discount_percent", sa.Numeric(5, 2), nullable=False, server_default="0"),
            sa.Column("tax_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
            sa.Column("total_amount", sa.Numeric(20, 2), nullable=False),
            sa.Column("expected_delivery_date", sa.Date(), nullable=True),
            sa.Column("notes", sa.String(500), nullable=True),
            sa.Column("legal_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        )
        op.create_index("idx_po_line_po", "purchase_order_line", ["purchase_order_id"])
        op.create_unique_constraint("uq_po_line_number", "purchase_order_line", ["purchase_order_id", "line_number"])
    else:
        # Rename kolom lama (peninggalan migrasi 0044/0046) ke nama yang
        # dipakai kontrak API, kalau memang masih ada dalam bentuk lama.
        renames = [
            ("po_id", "purchase_order_id"),
            ("product_id", "item_id"),
            ("product_code", "item_code"),
            ("product_name", "item_name"),
            ("total_price", "total_amount"),
        ]
        for old, new in renames:
            if old in pol_cols and new not in pol_cols:
                op.alter_column("purchase_order_line", old, new_column_name=new)
                pol_cols[new] = pol_cols.pop(old)

        # Kolom yang harus ada tapi mungkin sudah ke-drop total di masa
        # lalu -- tambahkan balik dengan default aman.
        _add_col_if_missing("purchase_order_line", sa.Column("discount_percent", sa.Numeric(5, 2), nullable=False, server_default="0"), pol_cols)
        _add_col_if_missing("purchase_order_line", sa.Column("tax_rate", sa.Numeric(5, 2), nullable=False, server_default="0"), pol_cols)
        _add_col_if_missing("purchase_order_line", sa.Column("expected_delivery_date", sa.Date(), nullable=True), pol_cols)
        _add_col_if_missing("purchase_order_line", sa.Column("legal_entity_id", postgresql.UUID(as_uuid=True), nullable=True), pol_cols)
        _add_col_if_missing("purchase_order_line", sa.Column("notes", sa.String(500), nullable=True), pol_cols)
        _add_col_if_missing("purchase_order_line", sa.Column("purchase_order_id", postgresql.UUID(as_uuid=True), nullable=True), pol_cols)
        _add_col_if_missing("purchase_order_line", sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=True), pol_cols)
        _add_col_if_missing("purchase_order_line", sa.Column("total_amount", sa.Numeric(20, 2), nullable=True), pol_cols)
        _add_col_if_missing("purchase_order_line", sa.Column("line_number", sa.Integer(), nullable=True), pol_cols)
        _add_col_if_missing("purchase_order_line", sa.Column("version", sa.Integer(), nullable=False, server_default="1"), pol_cols)
        _add_col_if_missing("purchase_order_line", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True), pol_cols)
        # Kolom lama yang sudah tidak dipakai (unit_of_measure) SENGAJA
        # dibiarkan apa adanya (tidak di-drop) supaya migrasi ini tidak
        # merusak data historis apa pun -- cukup tidak dipakai lagi oleh
        # ORM/service yang baru.

    # ========================================================================
    # 4) LINE `sales_order_line` -- rekonsiliasi serupa (ORM-nya
    #    infrastructure/persistence_orm/sales_order_line_table.py sudah
    #    benar memakai item_id/item_code/dst, tinggal pastikan tabel fisik
    #    di DB benar-benar cocok, karena tabel ini sempat ikut ke-drop di
    #    81de37e7a243_sync_budget_table_columns.py).
    # ========================================================================
    sol_cols = _cols(inspector, "sales_order_line")
    if sol_cols is None:
        op.create_table(
            "sales_order_line",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("sales_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sales_order.id", ondelete="CASCADE"), nullable=False),
            sa.Column("line_number", sa.Integer(), nullable=False),
            sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("item_code", sa.String(30), nullable=False, server_default=""),
            sa.Column("item_name", sa.String(200), nullable=False, server_default=""),
            sa.Column("quantity", sa.Numeric(19, 4), nullable=False),
            sa.Column("shipped_quantity", sa.Numeric(19, 4), nullable=False, server_default="0"),
            sa.Column("unit_price", sa.Numeric(19, 4), nullable=False),
            sa.Column("discount_percent", sa.Numeric(5, 2), nullable=False, server_default="0"),
            sa.Column("tax_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
            sa.Column("total_amount", sa.Numeric(19, 4), nullable=False),
            sa.Column("expected_ship_date", sa.Date(), nullable=True),
            sa.Column("legal_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        )
        op.create_index("idx_so_line_so", "sales_order_line", ["sales_order_id"])
        op.create_unique_constraint("uq_so_line_number", "sales_order_line", ["sales_order_id", "line_number"])
    else:
        _add_col_if_missing("sales_order_line", sa.Column("discount_percent", sa.Numeric(5, 2), nullable=False, server_default="0"), sol_cols)
        _add_col_if_missing("sales_order_line", sa.Column("tax_rate", sa.Numeric(5, 2), nullable=False, server_default="0"), sol_cols)
        _add_col_if_missing("sales_order_line", sa.Column("shipped_quantity", sa.Numeric(19, 4), nullable=False, server_default="0"), sol_cols)
        _add_col_if_missing("sales_order_line", sa.Column("legal_entity_id", postgresql.UUID(as_uuid=True), nullable=True), sol_cols)
        _add_col_if_missing("sales_order_line", sa.Column("line_number", sa.Integer(), nullable=True), sol_cols)
        _add_col_if_missing("sales_order_line", sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sol_cols)


def downgrade() -> None:
    # Downgrade sengaja tidak mengembalikan skema ke kondisi drift lama
    # (product_id/total_price/dll) -- cukup hapus kolom tambahan yang
    # murni additive, supaya downgrade tetap aman tanpa risiko kehilangan
    # data pada rename.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, cols in [
        ("purchase_order", ["invoiced_amount", "order_type", "rejected_at", "rejected_by",
                             "rejection_reason", "cancelled_at", "cancelled_by", "closed_at", "is_locked"]),
        ("sales_order", ["order_type", "rejected_at", "rejected_by", "rejection_reason",
                          "cancelled_at", "cancelled_by", "closed_at", "is_locked"]),
    ]:
        existing = _cols(inspector, table)
        if existing is None:
            continue
        for col in cols:
            if col in existing:
                op.drop_column(table, col)
