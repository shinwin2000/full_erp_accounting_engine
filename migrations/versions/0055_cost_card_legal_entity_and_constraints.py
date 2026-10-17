"""add manufacturing_cost_card: legal_entity_id + unique/index constraints

Revision ID: 0055_cost_card_le_constraints
Revises: 0054_cost_card_qb_fields
Create Date: 2026-10-16

Changelog:
    FIX: migrasi 0054 hanya mencatat dirinya sebagai applied, tapi
    body-nya tidak menambahkan legal_entity_id, unique constraint,
    dan beberapa index. Migrasi ini melengkapi dengan aman (idempotent).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect, text


revision = "0055_cost_card_le_constraints"
down_revision = "0054_cost_card_qb_fields"
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
    try:
        return name in {c["name"] for c in inspector.get_unique_constraints(table)}
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = _get_inspector()

    # ----------------------------------------------------------------
    # 1. Kolom legal_entity_id
    # ----------------------------------------------------------------
    if not _column_exists(inspector, TABLE, "legal_entity_id"):
        op.add_column(
            TABLE,
            sa.Column(
                "legal_entity_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
                comment="Multi-tenant boundary",
            ),
        )
        print("[0055] Added column legal_entity_id")
    else:
        print("[0055] Column legal_entity_id already exists, skipping")

    # ----------------------------------------------------------------
    # 2. Backfill legal_entity_id dari work order (kalau relasi ada)
    # ----------------------------------------------------------------
    inspector = _get_inspector()
    if _column_exists(inspector, "manufacturing_work_order", "legal_entity_id"):
        try:
            bind.execute(
                text(
                    f"""
                    UPDATE {TABLE} c
                       SET legal_entity_id = w.legal_entity_id
                      FROM manufacturing_work_order w
                     WHERE c.cost_card_id = w.id
                       AND c.legal_entity_id IS NULL
                    """
                )
            )
            print("[0055] Backfilled legal_entity_id from manufacturing_work_order")
        except Exception as e:
            print(f"[0055] Backfill skipped: {e}")

    # ----------------------------------------------------------------
    # 3. Unique constraint (product_id, period, legal_entity_id)
    # ----------------------------------------------------------------
    inspector = _get_inspector()
    if not _unique_constraint_exists(
        inspector, TABLE, "uq_mfg_cost_card_product_period_le"
    ):
        dup = bind.execute(
            text(
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
            print(
                f"[0055][WARN] Duplikat ditemukan, skip unique constraint: {dup}"
            )
        else:
            op.create_unique_constraint(
                "uq_mfg_cost_card_product_period_le",
                TABLE,
                ["product_id", "period", "legal_entity_id"],
            )
            print("[0055] Created unique constraint uq_mfg_cost_card_product_period_le")
    else:
        print("[0055] Unique constraint already exists, skipping")

    # ----------------------------------------------------------------
    # 4. Index
    # ----------------------------------------------------------------
    inspector = _get_inspector()
    if not _index_exists(inspector, TABLE, "ix_mfg_cost_card_le_product_period"):
        op.create_index(
            "ix_mfg_cost_card_le_product_period",
            TABLE,
            ["legal_entity_id", "product_id", "period"],
        )
        print("[0055] Created index ix_mfg_cost_card_le_product_period")

    if not _index_exists(inspector, TABLE, "ix_mfg_cost_card_status_period"):
        op.create_index(
            "ix_mfg_cost_card_status_period",
            TABLE,
            ["status", "period"],
        )
        print("[0055] Created index ix_mfg_cost_card_status_period")

    if not _index_exists(inspector, TABLE, "ix_mfg_cost_card_legal_entity_id"):
        op.create_index(
            "ix_mfg_cost_card_legal_entity_id",
            TABLE,
            ["legal_entity_id"],
        )
        print("[0055] Created index ix_mfg_cost_card_legal_entity_id")

    # ----------------------------------------------------------------
    # 5. ALTER product_code -> nullable
    # ----------------------------------------------------------------
    inspector = _get_inspector()
    pc_col = next(
        (c for c in inspector.get_columns(TABLE) if c["name"] == "product_code"),
        None,
    )
    if pc_col and not pc_col.get("nullable", True):
        op.alter_column(
            TABLE,
            "product_code",
            existing_type=sa.String(50),
            nullable=True,
        )
        print("[0055] Altered product_code to NULLABLE")

    # ----------------------------------------------------------------
    # 6. Ensure server_default untuk kolom baru
    # ----------------------------------------------------------------
    op.execute(f"ALTER TABLE {TABLE} ALTER COLUMN quantity_base SET DEFAULT 1")
    op.execute(f"ALTER TABLE {TABLE} ALTER COLUMN unit_of_measure SET DEFAULT 'pcs'")
    op.execute(f"ALTER TABLE {TABLE} ALTER COLUMN other_cost SET DEFAULT 0")
    op.execute(f"ALTER TABLE {TABLE} ALTER COLUMN status SET DEFAULT 'open'")
    print("[0055] Ensured server_default for new columns")


def downgrade() -> None:
    inspector = _get_inspector()

    for idx in (
        "ix_mfg_cost_card_legal_entity_id",
        "ix_mfg_cost_card_status_period",
        "ix_mfg_cost_card_le_product_period",
    ):
        if _index_exists(inspector, TABLE, idx):
            op.drop_index(idx, table_name=TABLE)

    if _unique_constraint_exists(
        inspector, TABLE, "uq_mfg_cost_card_product_period_le"
    ):
        op.drop_constraint(
            "uq_mfg_cost_card_product_period_le", TABLE, type_="unique"
        )

    inspector = _get_inspector()
    if _column_exists(inspector, TABLE, "legal_entity_id"):
        op.drop_column(TABLE, "legal_entity_id")
        