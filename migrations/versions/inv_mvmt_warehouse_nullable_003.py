"""make inventory_movement.warehouse_id nullable

Revision ID: inv_mvmt_warehouse_nullable_003
Revises: inv_mvmt_add_status_fields_002
Create Date: 2026-09-08 06:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'inv_mvmt_warehouse_nullable_003'
down_revision = 'inv_mvmt_add_status_fields_002'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'inventory_movement',
        'warehouse_id',
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade():
    op.alter_column(
        'inventory_movement',
        'warehouse_id',
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )
