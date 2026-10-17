"""add cost_card: quantity_base, unit_of_measure, other_cost, status,
legal_entity_id + unique/index constraints

Revision ID: 0054_cost_card_qb_fields
Revises: 0053_employee_ptkp_and_type
Create Date: 2026-10-16

Changelog:
    FIX BUG: GET /manufacturing/cost-cards menampilkan unit_cost == total_cost
    (mis. total=320, unit=320) padahal seharusnya unit = total / quantity_base
    (mis. 320/20 = 16).

    Migrasi ini:
      1. Tambah kolom `quantity_base`, `unit_of_measure`, `other_cost`,
         `status`, `legal_entity_id` (idempotent: skip kalau sudah ada).
      2. Backfill quantity_base dari quantity_produced.
      3. Backfill unit_cost = total_cost / quantity_base.
      4. Tambah UniqueConstraint (product_id, period, legal_entity_id).
      5. Tambah Index untuk listing cepat.

    Catatan: pakai helper `_column_exists` dan `_index_exists` supaya aman
    dijalankan berulang kali.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0054_cost_card_qb_fields"
down_revision = "0053_employee_ptkp_and_type"
branch_labels = None
depends_on = None


TABLE = "manufacturing_cost_card"


def _get_inspector():
    return inspect(op.get_bind())


def _column_exists(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def _index_exists(inspector, table: str, index_name: str) -> bool:
    return index_name in {i["name"] for i in inspector.get_indexes(table)}


def _unique_constraint_exists(inspector, table: str, name: str) -> bool:
    return name in {c["name"] for c in inspector.get_unique_constraints(table)}


def upgrade() -> None:
    inspector = _get_inspector()

    # ----------------------------------------------------------------
    # 1. Tambah kolom (idempotent)
    # ----------------------------------------------------------------
    if not _column_exists(inspector, TABLE, "quantity_base"):
        op.add_column(
            TABLE,
            sa.Column(
                "quantity_base",
                sa.Numeric(18, 4),
                nullable=False,
                server_default=sa.text("1"),
                comment="Basis hitung unit_cost",
            ),
        )

    if not _column_exists(inspector, TABLE, "unit_of_measure"):
        op.add_column(
            TABLE,
            sa.Column(
                "unit_of_measure",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'pcs'"),
            ),
        )

    if not _column_exists(inspector, TABLE, "other_cost"):
        op.add_column(
            TABLE,
            sa.Column(
                "other_cost",
                sa.Numeric(18, 2),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )

    if not _column_exists(inspector, TABLE, "status"):
        op.add_column(
            TABLE,
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'open'"),
            ),
        )

    if not _column_exists(inspector, TABLE, "legal_entity_id"):
        op.add_column(
            TABLE,
            sa.Column(
                "legal_entity_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                nullable=True,
                comment="Multi-tenant boundary; backfill via migrasi",
            ),
        )

    # ----------------------------------------------------------------
    # 2. Backfill quantity_base dari quantity_produced (kalau ada)
    # ----------------------------------------------------------------
    inspector = _get_inspector()  # refresh
    if _column_exists(inspector, TABLE, "quantity_produced"):
        op.execute(
            f"""
            UPDATE {TABLE}
               SET quantity_base = quantity_produced
             WHERE quantity_base = 1
               AND quantity_produced IS NOT NULL
               AND quantity_produced > 0
            """
        )

    # ----------------------------------------------------------------
    # 3. Backfill unit_cost = total_cost / quantity_base
    # ----------------------------------------------------------------
    op.execute(
        f"""
        UPDATE {TABLE}
           SET unit_cost = ROUND(total_cost / NULLIF(quantity_base, 0), 4)
         WHERE quantity_base IS NOT NULL
           AND quantity_base > 0
           AND (unit_cost IS NULL OR unit_cost = 0)
           AND total_cost > 0
        """
    )

    # ----------------------------------------------------------------
    # 4. UniqueConstraint (product_id, period, legal_entity_id)
    # ----------------------------------------------------------------
    if not _unique_constraint_exists(
        inspector, TABLE, "uq_mfg_cost_card_product_period_le"
    ):
        # Cek dulu apakah ada duplikat yang akan melanggar constraint.
        # Kalau ada, log warning (tidak raise) supaya migrasi tetap jalan.
        bind = op.get_bind()
        dup = bind.execute(
            sa.text(
                f"""
                SELECT product_id, period, legal_entity_id, COUNT(*) AS n
                  FROM {TABLE}
                 GROUP BY product_id, period, legal_entity_id
                HAVING COUNT(*) > 1
                 LIMIT 5
                """
            )
        ).fetchall()
        if dup:
            # Ada duplikat — jangan pasang constraint, catat saja.
            # User harus bersihkan manual dulu.
            print(
                f"[WARN] Duplikat (product_id, period, legal_entity_id) "
                f"ditemukan: {dup}. UniqueConstraint TIDAK dipasang."
            )
        else:
            op.create_unique_constraint(
                "uq_mfg_cost_card_product_period_le",
                TABLE,
                ["product_id", "period", "legal_entity_id"],
            )

    # ----------------------------------------------------------------
    # 5. Index (idempotent)
    # ----------------------------------------------------------------
    if not _index_exists(inspector, TABLE, "ix_mfg_cost_card_le_product_period"):
        op.create_index(
            "ix_mfg_cost_card_le_product_period",
            TABLE,
            ["legal_entity_id", "product_id", "period"],
        )

    if not _index_exists(inspector, TABLE, "ix_mfg_cost_card_status_period"):
        op.create_index(
            "ix_mfg_cost_card_status_period",
            TABLE,
            ["status", "period"],
        )

    # legal_entity_id single-column index (untuk filter by LE saja)
    if not _index_exists(inspector, TABLE, "ix_mfg_cost_card_legal_entity_id"):
        op.create_index(
            "ix_mfg_cost_card_legal_entity_id",
            TABLE,
            ["legal_entity_id"],
        )


def downgrade() -> None:
    inspector = _get_inspector()

    # Drop index
    for idx in (
        "ix_mfg_cost_card_legal_entity_id",
        "ix_mfg_cost_card_status_period",
        "ix_mfg_cost_card_le_product_period",
    ):
        if _index_exists(inspector, TABLE, idx):
            op.drop_index(idx, table_name=TABLE)

    # Drop constraint
    if _unique_constraint_exists(
        inspector, TABLE, "uq_mfg_cost_card_product_period_le"
    ):
        op.drop_constraint(
            "uq_mfg_cost_card_product_period_le", TABLE, type_="unique"
        )

    # Drop column (hanya kalau ada)
    inspector = _get_inspector()
    for col in (
        "legal_entity_id",
        "status",
        "other_cost",
        "unit_of_measure",
        "quantity_base",
    ):
        if _column_exists(inspector, TABLE, col):
            op.drop_column(TABLE, col)
            