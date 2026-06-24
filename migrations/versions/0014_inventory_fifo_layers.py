"""create inventory_fifo_layer table for FIFO valuation tracking

Revision ID: 0014
Revises: 0013
Create Date: 2025-01-01 00:00:13.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, NUMERIC

revision: str = '0014abcd'
down_revision = '0013abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'inventory_fifo_layer',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('item_id', UUID(as_uuid=True), nullable=False),
        sa.Column('quantity', NUMERIC(20, 2), nullable=False),
        sa.Column('remaining_quantity', NUMERIC(20, 2), nullable=False),
        sa.Column('uom', sa.String(10), nullable=False, server_default='pcs'),
        sa.Column('unit_cost', NUMERIC(20, 2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('purchase_date', sa.Date, nullable=False),
        sa.Column('movement_id', UUID(as_uuid=True), nullable=True),
        sa.Column('batch_number', sa.String(50), nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_inventory_fifo_layer_item', 'inventory_fifo_layer', ['item_id'])
    op.create_index('idx_inventory_fifo_layer_item_remaining', 'inventory_fifo_layer', ['item_id', 'remaining_quantity'])
    op.create_index('idx_inventory_fifo_layer_purchase_date', 'inventory_fifo_layer', ['purchase_date'])
    op.create_index('idx_inventory_fifo_layer_movement', 'inventory_fifo_layer', ['movement_id'])
    op.create_index('idx_inventory_fifo_layer_legal_entity', 'inventory_fifo_layer', ['legal_entity_id'])
    op.create_index('idx_inventory_fifo_layer_remaining_only', 'inventory_fifo_layer', ['remaining_quantity', 'item_id'])
    op.create_foreign_key('fk_inventory_fifo_layer_item', 'inventory_fifo_layer', 'inventory_item', ['item_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_inventory_fifo_layer_movement', 'inventory_fifo_layer', 'inventory_movement', ['movement_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_inventory_fifo_layer_legal_entity', 'inventory_fifo_layer', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_inventory_fifo_layer_quantity_positive', 'inventory_fifo_layer', 'quantity > 0')
    op.create_check_constraint('ck_inventory_fifo_layer_remaining_nonneg', 'inventory_fifo_layer', 'remaining_quantity >= 0')
    op.create_check_constraint('ck_inventory_fifo_layer_remaining_not_exceed', 'inventory_fifo_layer', 'remaining_quantity <= quantity')
    op.create_check_constraint('ck_inventory_fifo_layer_unit_cost_nonneg', 'inventory_fifo_layer', 'unit_cost >= 0')

def downgrade() -> None:
    op.drop_constraint('fk_inventory_fifo_layer_item', 'inventory_fifo_layer', type_='foreignkey')
    op.drop_constraint('fk_inventory_fifo_layer_movement', 'inventory_fifo_layer', type_='foreignkey')
    op.drop_constraint('fk_inventory_fifo_layer_legal_entity', 'inventory_fifo_layer', type_='foreignkey')
    op.drop_constraint('ck_inventory_fifo_layer_quantity_positive', 'inventory_fifo_layer', type_='check')
    op.drop_constraint('ck_inventory_fifo_layer_remaining_nonneg', 'inventory_fifo_layer', type_='check')
    op.drop_constraint('ck_inventory_fifo_layer_remaining_not_exceed', 'inventory_fifo_layer', type_='check')
    op.drop_constraint('ck_inventory_fifo_layer_unit_cost_nonneg', 'inventory_fifo_layer', type_='check')
    op.drop_index('idx_inventory_fifo_layer_item', table_name='inventory_fifo_layer')
    op.drop_index('idx_inventory_fifo_layer_item_remaining', table_name='inventory_fifo_layer')
    op.drop_index('idx_inventory_fifo_layer_purchase_date', table_name='inventory_fifo_layer')
    op.drop_index('idx_inventory_fifo_layer_movement', table_name='inventory_fifo_layer')
    op.drop_index('idx_inventory_fifo_layer_legal_entity', table_name='inventory_fifo_layer')
    op.drop_index('idx_inventory_fifo_layer_remaining_only', table_name='inventory_fifo_layer')
    op.drop_table('inventory_fifo_layer')