"""supplier history updated_at

Revision ID: 0052_supplier_history_updated_at
Revises: 0051_supplier_child_tables_full
Create Date: 2026-10-13

Tambah kolom `updated_at` ke 2 tabel audit supplier yang mewarisi
TimestampMixin tapi lupa dibuatkan kolom updated_at di migrasi 0051:
    - supplier_credit_history
    - supplier_balance_history

Error sebelum fix:
    asyncpg.exceptions.UndefinedColumnError:
    column supplier_credit_history.updated_at does not exist
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0052_supplier_history_updated_at"
down_revision = "0051_supplier_child_tables_full"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # supplier_credit_history
    op.add_column(
        "supplier_credit_history",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # supplier_balance_history
    op.add_column(
        "supplier_balance_history",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_column("supplier_balance_history", "updated_at")
    op.drop_column("supplier_credit_history", "updated_at")
    