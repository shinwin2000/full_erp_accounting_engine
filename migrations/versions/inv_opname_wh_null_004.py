"""make stock_opname_line.warehouse_id nullable

Revision ID: inv_opname_line_warehouse_nullable_004
Revises: inv_mvmt_warehouse_nullable_003
Create Date: 2026-09-08 06:15:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'inv_opname_wh_null_004'
down_revision = 'inv_mvmt_warehouse_nullable_003'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'stock_opname_line',
        'warehouse_id',
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade():
    op.alter_column(
        'stock_opname_line',
        'warehouse_id',
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )
