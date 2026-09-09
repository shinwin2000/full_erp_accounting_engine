"""add status, serial_number, reversed_at, reversed_by to inventory_movement

Revision ID: inv_mvmt_add_status_fields_002
Revises: inv_mvmt_merge_heads_001
Create Date: 2026-09-08 00:05:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP

# revision identifiers, used by Alembic.
revision = 'inv_mvmt_add_status_fields_002'
down_revision = 'd0e1f2a3b4c5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'inventory_movement',
        sa.Column('status', sa.String(20), nullable=False, server_default='confirmed'),
    )
    op.add_column(
        'inventory_movement',
        sa.Column('serial_number', sa.String(100), nullable=True),
    )
    op.add_column(
        'inventory_movement',
        sa.Column('reversed_at', TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        'inventory_movement',
        sa.Column('reversed_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        'ix_inventory_movement_status', 'inventory_movement', ['status', 'legal_entity_id']
    )


def downgrade():
    op.drop_index('ix_inventory_movement_status', table_name='inventory_movement')
    op.drop_column('inventory_movement', 'reversed_by')
    op.drop_column('inventory_movement', 'reversed_at')
    op.drop_column('inventory_movement', 'serial_number')
    op.drop_column('inventory_movement', 'status')
