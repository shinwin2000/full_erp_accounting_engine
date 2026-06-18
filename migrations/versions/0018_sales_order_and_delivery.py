"""create sales_order and delivery_order tables

Revision ID: 0018
Revises: 0017
Create Date: 2025-01-01 00:00:17.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, NUMERIC

revision: str = '0018'
down_revision = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'sales_order',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('so_number', sa.String(50), nullable=False),
        sa.Column('so_date', sa.Date, nullable=False),
        sa.Column('customer_id', UUID(as_uuid=True), nullable=False),
        sa.Column('total_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('shipped_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('invoiced_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('paid_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('tax_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('discount_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('expected_ship_date', sa.Date, nullable=True),
        sa.Column('actual_ship_date', sa.Date, nullable=True),
        sa.Column('status', sa.String(25), nullable=False, server_default='draft'),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('approved_by', UUID(as_uuid=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('shipping_term_days', sa.Integer, nullable=False, server_default='7'),
        sa.Column('payment_term_days', sa.Integer, nullable=False, server_default='30'),
        sa.Column('incoterm', sa.String(20), nullable=True),
        sa.Column('reference_number', sa.String(100), nullable=True),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_so_number', 'sales_order', ['so_number'])
    op.create_index('idx_so_customer', 'sales_order', ['customer_id'])
    op.create_index('idx_so_date', 'sales_order', ['so_date'])
    op.create_index('idx_so_status', 'sales_order', ['status'])
    op.create_index('idx_so_legal_entity', 'sales_order', ['legal_entity_id'])
    op.create_index('idx_so_expected_ship_date', 'sales_order', ['expected_ship_date'])
    op.create_index('idx_so_approved_by', 'sales_order', ['approved_by'])
    op.create_unique_constraint('uq_sales_order_number_legal_entity', 'sales_order', ['so_number', 'legal_entity_id'])
    op.create_foreign_key('fk_sales_order_customer', 'sales_order', 'customer', ['customer_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_sales_order_legal_entity', 'sales_order', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_sales_order_approved_by', 'sales_order', 'iam_user', ['approved_by'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_so_status', 'sales_order', "status IN ('draft', 'submitted', 'approved', 'partially_shipped', 'fully_shipped', 'cancelled', 'closed')")

    op.create_table(
        'sales_order_line',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('sales_order_id', UUID(as_uuid=True), nullable=False),
        sa.Column('line_number', sa.Integer, nullable=False),
        sa.Column('item_id', UUID(as_uuid=True), nullable=False),
        sa.Column('item_code', sa.String(30), nullable=False),
        sa.Column('item_name', sa.String(200), nullable=True),
        sa.Column('quantity', NUMERIC(20, 2), nullable=False),
        sa.Column('shipped_quantity', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('unit_price', NUMERIC(20, 2), nullable=False),
        sa.Column('discount_percent', NUMERIC(5, 2), nullable=False, server_default='0'),
        sa.Column('tax_rate', NUMERIC(5, 2), nullable=False, server_default='0'),
        sa.Column('total_amount', NUMERIC(20, 2), nullable=False),
        sa.Column('expected_ship_date', sa.Date, nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
    )
    op.create_index('idx_so_line_so', 'sales_order_line', ['sales_order_id'])
    op.create_index('idx_so_line_item', 'sales_order_line', ['item_id'])
    op.create_index('idx_so_line_number', 'sales_order_line', ['sales_order_id', 'line_number'])
    op.create_foreign_key('fk_so_line_so', 'sales_order_line', 'sales_order', ['sales_order_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_so_line_item', 'sales_order_line', 'inventory_item', ['item_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_so_line_legal_entity', 'sales_order_line', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_so_line_quantity_positive', 'sales_order_line', 'quantity > 0')
    op.create_check_constraint('ck_so_line_shipped_not_exceed', 'sales_order_line', 'shipped_quantity <= quantity')

    op.create_table(
        'delivery_order',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('do_number', sa.String(50), nullable=False),
        sa.Column('do_date', sa.Date, nullable=False),
        sa.Column('sales_order_id', UUID(as_uuid=True), nullable=False),
        sa.Column('customer_id', UUID(as_uuid=True), nullable=False),
        sa.Column('shipping_address', sa.Text, nullable=True),
        sa.Column('shipped_by', UUID(as_uuid=True), nullable=True),
        sa.Column('tracking_number', sa.String(100), nullable=True),
        sa.Column('carrier', sa.String(100), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_do_number', 'delivery_order', ['do_number'])
    op.create_index('idx_do_so', 'delivery_order', ['sales_order_id'])
    op.create_index('idx_do_customer', 'delivery_order', ['customer_id'])
    op.create_index('idx_do_status', 'delivery_order', ['status'])
    op.create_index('idx_do_tracking', 'delivery_order', ['tracking_number'])
    op.create_unique_constraint('uq_do_number_legal_entity', 'delivery_order', ['do_number', 'legal_entity_id'])
    op.create_foreign_key('fk_delivery_order_so', 'delivery_order', 'sales_order', ['sales_order_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_delivery_order_customer', 'delivery_order', 'customer', ['customer_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_delivery_order_shipped_by', 'delivery_order', 'iam_user', ['shipped_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_delivery_order_legal_entity', 'delivery_order', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_do_status', 'delivery_order', "status IN ('draft', 'confirmed', 'shipped', 'delivered', 'cancelled')")

    op.create_table(
        'delivery_order_line',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('delivery_order_id', UUID(as_uuid=True), nullable=False),
        sa.Column('sales_order_line_id', UUID(as_uuid=True), nullable=False),
        sa.Column('line_number', sa.Integer, nullable=False),
        sa.Column('item_id', UUID(as_uuid=True), nullable=False),
        sa.Column('item_code', sa.String(30), nullable=False),
        sa.Column('item_name', sa.String(200), nullable=True),
        sa.Column('quantity_shipped', NUMERIC(20, 2), nullable=False),
        sa.Column('batch_number', sa.String(50), nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
    )
    op.create_index('idx_do_line_do', 'delivery_order_line', ['delivery_order_id'])
    op.create_index('idx_do_line_so_line', 'delivery_order_line', ['sales_order_line_id'])
    op.create_index('idx_do_line_item', 'delivery_order_line', ['item_id'])
    op.create_index('idx_do_line_number', 'delivery_order_line', ['delivery_order_id', 'line_number'])
    op.create_foreign_key('fk_do_line_do', 'delivery_order_line', 'delivery_order', ['delivery_order_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_do_line_so_line', 'delivery_order_line', 'sales_order_line', ['sales_order_line_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_do_line_item', 'delivery_order_line', 'inventory_item', ['item_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_do_line_legal_entity', 'delivery_order_line', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_do_line_quantity_positive', 'delivery_order_line', 'quantity_shipped > 0')

    op.create_foreign_key('fk_ar_invoice_sales_order', 'ar_invoice', 'sales_order', ['sales_order_id'], ['id'], ondelete='SET NULL')

def downgrade() -> None:
    op.drop_constraint('fk_ar_invoice_sales_order', 'ar_invoice', type_='foreignkey')
    op.drop_constraint('fk_do_line_do', 'delivery_order_line', type_='foreignkey')
    op.drop_constraint('fk_do_line_so_line', 'delivery_order_line', type_='foreignkey')
    op.drop_constraint('fk_do_line_item', 'delivery_order_line', type_='foreignkey')
    op.drop_constraint('fk_do_line_legal_entity', 'delivery_order_line', type_='foreignkey')
    op.drop_constraint('ck_do_line_quantity_positive', 'delivery_order_line', type_='check')
    op.drop_index('idx_do_line_do', table_name='delivery_order_line')
    op.drop_index('idx_do_line_so_line', table_name='delivery_order_line')
    op.drop_index('idx_do_line_item', table_name='delivery_order_line')
    op.drop_index('idx_do_line_number', table_name='delivery_order_line')
    op.drop_table('delivery_order_line')

    op.drop_constraint('fk_delivery_order_so', 'delivery_order', type_='foreignkey')
    op.drop_constraint('fk_delivery_order_customer', 'delivery_order', type_='foreignkey')
    op.drop_constraint('fk_delivery_order_shipped_by', 'delivery_order', type_='foreignkey')
    op.drop_constraint('fk_delivery_order_legal_entity', 'delivery_order', type_='foreignkey')
    op.drop_constraint('uq_do_number_legal_entity', 'delivery_order', type_='unique')
    op.drop_constraint('ck_do_status', 'delivery_order', type_='check')
    op.drop_index('idx_do_number', table_name='delivery_order')
    op.drop_index('idx_do_so', table_name='delivery_order')
    op.drop_index('idx_do_customer', table_name='delivery_order')
    op.drop_index('idx_do_status', table_name='delivery_order')
    op.drop_index('idx_do_tracking', table_name='delivery_order')
    op.drop_table('delivery_order')

    op.drop_constraint('fk_so_line_so', 'sales_order_line', type_='foreignkey')
    op.drop_constraint('fk_so_line_item', 'sales_order_line', type_='foreignkey')
    op.drop_constraint('fk_so_line_legal_entity', 'sales_order_line', type_='foreignkey')
    op.drop_constraint('ck_so_line_quantity_positive', 'sales_order_line', type_='check')
    op.drop_constraint('ck_so_line_shipped_not_exceed', 'sales_order_line', type_='check')
    op.drop_index('idx_so_line_so', table_name='sales_order_line')
    op.drop_index('idx_so_line_item', table_name='sales_order_line')
    op.drop_index('idx_so_line_number', table_name='sales_order_line')
    op.drop_table('sales_order_line')

    op.drop_constraint('fk_sales_order_customer', 'sales_order', type_='foreignkey')
    op.drop_constraint('fk_sales_order_legal_entity', 'sales_order', type_='foreignkey')
    op.drop_constraint('fk_sales_order_approved_by', 'sales_order', type_='foreignkey')
    op.drop_constraint('uq_sales_order_number_legal_entity', 'sales_order', type_='unique')
    op.drop_constraint('ck_so_status', 'sales_order', type_='check')
    op.drop_index('idx_so_number', table_name='sales_order')
    op.drop_index('idx_so_customer', table_name='sales_order')
    op.drop_index('idx_so_date', table_name='sales_order')
    op.drop_index('idx_so_status', table_name='sales_order')
    op.drop_index('idx_so_legal_entity', table_name='sales_order')
    op.drop_index('idx_so_expected_ship_date', table_name='sales_order')
    op.drop_index('idx_so_approved_by', table_name='sales_order')
    op.drop_table('sales_order')