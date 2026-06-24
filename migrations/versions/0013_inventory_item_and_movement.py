"""create warehouse, inventory_item and inventory_movement tables

Revision ID: 0013
Revises: 0012
Create Date: 2025-01-01 00:00:12.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, NUMERIC

revision: str = '0013abcd'
down_revision = '0012abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'warehouse',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('warehouse_code', sa.String(20), nullable=False),
        sa.Column('warehouse_name', sa.String(100), nullable=False),
        sa.Column('address', sa.Text, nullable=True),
        sa.Column('city', sa.String(100), nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=False),
        sa.Column('updated_by', UUID(as_uuid=True), nullable=False),
    )
    op.create_index('idx_warehouse_legal_entity', 'warehouse', ['legal_entity_id'])
    op.create_index('idx_warehouse_code', 'warehouse', ['warehouse_code'])

    op.create_table(
        'inventory_item',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('item_code', sa.String(30), nullable=False),
        sa.Column('item_name', sa.String(200), nullable=False),
        sa.Column('item_type', sa.String(20), nullable=False, server_default='trading'),
        sa.Column('unit_of_measure', sa.String(10), nullable=False, server_default='pcs'),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('brand', sa.String(100), nullable=True),
        sa.Column('reorder_point', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('reorder_quantity', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('min_stock', NUMERIC(20, 2), nullable=True),
        sa.Column('max_stock', NUMERIC(20, 2), nullable=True),
        sa.Column('standard_cost', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('last_cost', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('average_cost', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('valuation_method', sa.String(10), nullable=False, server_default='FIFO'),
        sa.Column('selling_price', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('currency_code', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('current_stock', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('tax_rate_purchase', NUMERIC(5, 2), nullable=False, server_default='11'),
        sa.Column('tax_rate_sales', NUMERIC(5, 2), nullable=False, server_default='11'),
        sa.Column('warehouse_id', UUID(as_uuid=True), nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_inventory_item_code', 'inventory_item', ['item_code'])
    op.create_index('idx_inventory_item_name', 'inventory_item', ['item_name'])
    op.create_index('idx_inventory_item_type', 'inventory_item', ['item_type'])
    op.create_index('idx_inventory_item_legal_entity', 'inventory_item', ['legal_entity_id'])
    op.create_index('idx_inventory_item_warehouse', 'inventory_item', ['warehouse_id'])
    op.create_index('idx_inventory_item_valuation', 'inventory_item', ['valuation_method'])
    op.create_index('idx_inventory_item_stock_status', 'inventory_item', ['current_stock', 'reorder_point'])
    op.create_index('idx_inventory_item_is_active', 'inventory_item', ['is_active'])
    op.create_unique_constraint('uq_inventory_item_code_legal_entity', 'inventory_item', ['item_code', 'legal_entity_id'])
    op.create_foreign_key('fk_inventory_item_legal_entity', 'inventory_item', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_inventory_item_warehouse', 'inventory_item', 'warehouse', ['warehouse_id'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_inventory_item_type', 'inventory_item', "item_type IN ('raw_material', 'work_in_process', 'finished_good', 'trading')")
    op.create_check_constraint('ck_inventory_item_valuation', 'inventory_item', "valuation_method IN ('FIFO', 'LIFO', 'AVERAGE', 'STANDARD')")

    op.create_table(
        'inventory_movement',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('movement_number', sa.String(50), nullable=False),
        sa.Column('movement_type', sa.String(15), nullable=False),
        sa.Column('item_id', UUID(as_uuid=True), nullable=False),
        sa.Column('quantity', NUMERIC(20, 2), nullable=False),
        sa.Column('uom', sa.String(10), nullable=False),
        sa.Column('unit_cost', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('total_cost', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('movement_date', sa.Date, nullable=False),
        sa.Column('reference_type', sa.String(50), nullable=False),
        sa.Column('reference_id', UUID(as_uuid=True), nullable=True),
        sa.Column('warehouse_id', UUID(as_uuid=True), nullable=False),
        sa.Column('to_warehouse_id', UUID(as_uuid=True), nullable=True),
        sa.Column('batch_number', sa.String(50), nullable=True),
        sa.Column('expiry_date', sa.Date, nullable=True),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_inventory_movement_number', 'inventory_movement', ['movement_number'])
    op.create_index('idx_inventory_movement_item', 'inventory_movement', ['item_id'])
    op.create_index('idx_inventory_movement_type', 'inventory_movement', ['movement_type'])
    op.create_index('idx_inventory_movement_date', 'inventory_movement', ['movement_date'])
    op.create_index('idx_inventory_movement_warehouse', 'inventory_movement', ['warehouse_id'])
    op.create_index('idx_inventory_movement_to_warehouse', 'inventory_movement', ['to_warehouse_id'])
    op.create_index('idx_inventory_movement_reference', 'inventory_movement', ['reference_type', 'reference_id'])
    op.create_index('idx_inventory_movement_batch', 'inventory_movement', ['batch_number'])
    op.create_index('idx_inventory_movement_legal_entity', 'inventory_movement', ['legal_entity_id'])
    op.create_unique_constraint('uq_inventory_movement_number_legal_entity', 'inventory_movement', ['movement_number', 'legal_entity_id'])
    op.create_foreign_key('fk_inventory_movement_item', 'inventory_movement', 'inventory_item', ['item_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_inventory_movement_warehouse', 'inventory_movement', 'warehouse', ['warehouse_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_inventory_movement_to_warehouse', 'inventory_movement', 'warehouse', ['to_warehouse_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_inventory_movement_legal_entity', 'inventory_movement', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_inventory_movement_type', 'inventory_movement', "movement_type IN ('IN', 'OUT', 'ADJUSTMENT', 'TRANSFER_IN', 'TRANSFER_OUT')")
    op.create_check_constraint('ck_inventory_movement_quantity_positive', 'inventory_movement', 'quantity > 0')
    op.create_check_constraint('ck_inventory_movement_unit_cost_nonneg', 'inventory_movement', 'unit_cost >= 0')

def downgrade() -> None:
    op.drop_constraint('fk_inventory_movement_item', 'inventory_movement', type_='foreignkey')
    op.drop_constraint('fk_inventory_movement_warehouse', 'inventory_movement', type_='foreignkey')
    op.drop_constraint('fk_inventory_movement_to_warehouse', 'inventory_movement', type_='foreignkey')
    op.drop_constraint('fk_inventory_movement_legal_entity', 'inventory_movement', type_='foreignkey')
    op.drop_constraint('uq_inventory_movement_number_legal_entity', 'inventory_movement', type_='unique')
    op.drop_constraint('ck_inventory_movement_type', 'inventory_movement', type_='check')
    op.drop_constraint('ck_inventory_movement_quantity_positive', 'inventory_movement', type_='check')
    op.drop_constraint('ck_inventory_movement_unit_cost_nonneg', 'inventory_movement', type_='check')
    op.drop_index('idx_inventory_movement_number', table_name='inventory_movement')
    op.drop_index('idx_inventory_movement_item', table_name='inventory_movement')
    op.drop_index('idx_inventory_movement_type', table_name='inventory_movement')
    op.drop_index('idx_inventory_movement_date', table_name='inventory_movement')
    op.drop_index('idx_inventory_movement_warehouse', table_name='inventory_movement')
    op.drop_index('idx_inventory_movement_to_warehouse', table_name='inventory_movement')
    op.drop_index('idx_inventory_movement_reference', table_name='inventory_movement')
    op.drop_index('idx_inventory_movement_batch', table_name='inventory_movement')
    op.drop_index('idx_inventory_movement_legal_entity', table_name='inventory_movement')
    op.drop_table('inventory_movement')

    op.drop_constraint('fk_inventory_item_legal_entity', 'inventory_item', type_='foreignkey')
    op.drop_constraint('fk_inventory_item_warehouse', 'inventory_item', type_='foreignkey')
    op.drop_constraint('uq_inventory_item_code_legal_entity', 'inventory_item', type_='unique')
    op.drop_constraint('ck_inventory_item_type', 'inventory_item', type_='check')
    op.drop_constraint('ck_inventory_item_valuation', 'inventory_item', type_='check')
    op.drop_index('idx_inventory_item_code', table_name='inventory_item')
    op.drop_index('idx_inventory_item_name', table_name='inventory_item')
    op.drop_index('idx_inventory_item_type', table_name='inventory_item')
    op.drop_index('idx_inventory_item_legal_entity', table_name='inventory_item')
    op.drop_index('idx_inventory_item_warehouse', table_name='inventory_item')
    op.drop_index('idx_inventory_item_valuation', table_name='inventory_item')
    op.drop_index('idx_inventory_item_stock_status', table_name='inventory_item')
    op.drop_index('idx_inventory_item_is_active', table_name='inventory_item')
    op.drop_table('inventory_item')

    op.drop_index('idx_warehouse_legal_entity', table_name='warehouse')
    op.drop_index('idx_warehouse_code', table_name='warehouse')
    op.drop_table('warehouse')