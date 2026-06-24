"""create purchase_order and goods_receipt_note tables

Revision ID: 0017
Revises: 0016
Create Date: 2025-01-01 00:00:16.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, NUMERIC

revision: str = '0017abcd'
down_revision = '0016abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'purchase_order',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('po_number', sa.String(50), nullable=False),
        sa.Column('po_date', sa.Date, nullable=False),
        sa.Column('supplier_id', UUID(as_uuid=True), nullable=False),
        sa.Column('total_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('received_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('paid_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('tax_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('discount_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('expected_delivery_date', sa.Date, nullable=True),
        sa.Column('actual_delivery_date', sa.Date, nullable=True),
        sa.Column('status', sa.String(25), nullable=False, server_default='draft'),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('approved_by', UUID(as_uuid=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivery_term_days', sa.Integer, nullable=False, server_default='30'),
        sa.Column('payment_term_days', sa.Integer, nullable=False, server_default='30'),
        sa.Column('incoterm', sa.String(20), nullable=True),
        sa.Column('reference_number', sa.String(100), nullable=True),
        sa.Column('requested_by', UUID(as_uuid=True), nullable=True),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_po_number', 'purchase_order', ['po_number'])
    op.create_index('idx_po_supplier', 'purchase_order', ['supplier_id'])
    op.create_index('idx_po_date', 'purchase_order', ['po_date'])
    op.create_index('idx_po_status', 'purchase_order', ['status'])
    op.create_index('idx_po_legal_entity', 'purchase_order', ['legal_entity_id'])
    op.create_index('idx_po_expected_date', 'purchase_order', ['expected_delivery_date'])
    op.create_index('idx_po_approved_by', 'purchase_order', ['approved_by'])
    op.create_unique_constraint('uq_purchase_order_number_legal_entity', 'purchase_order', ['po_number', 'legal_entity_id'])
    op.create_foreign_key('fk_purchase_order_supplier', 'purchase_order', 'supplier', ['supplier_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_purchase_order_legal_entity', 'purchase_order', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_purchase_order_approved_by', 'purchase_order', 'iam_user', ['approved_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_purchase_order_requested_by', 'purchase_order', 'iam_user', ['requested_by'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_po_status', 'purchase_order', "status IN ('draft', 'submitted', 'approved', 'partially_received', 'fully_received', 'cancelled', 'closed')")

    op.create_table(
        'purchase_order_line',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('purchase_order_id', UUID(as_uuid=True), nullable=False),
        sa.Column('line_number', sa.Integer, nullable=False),
        sa.Column('item_id', UUID(as_uuid=True), nullable=False),
        sa.Column('item_code', sa.String(30), nullable=False),
        sa.Column('item_name', sa.String(200), nullable=True),
        sa.Column('quantity', NUMERIC(20, 2), nullable=False),
        sa.Column('received_quantity', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('unit_price', NUMERIC(20, 2), nullable=False),
        sa.Column('discount_percent', NUMERIC(5, 2), nullable=False, server_default='0'),
        sa.Column('tax_rate', NUMERIC(5, 2), nullable=False, server_default='0'),
        sa.Column('total_amount', NUMERIC(20, 2), nullable=False),
        sa.Column('expected_delivery_date', sa.Date, nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
    )
    op.create_index('idx_po_line_po', 'purchase_order_line', ['purchase_order_id'])
    op.create_index('idx_po_line_item', 'purchase_order_line', ['item_id'])
    op.create_index('idx_po_line_number', 'purchase_order_line', ['purchase_order_id', 'line_number'])
    op.create_foreign_key('fk_po_line_po', 'purchase_order_line', 'purchase_order', ['purchase_order_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_po_line_item', 'purchase_order_line', 'inventory_item', ['item_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_po_line_legal_entity', 'purchase_order_line', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_po_line_quantity_positive', 'purchase_order_line', 'quantity > 0')
    op.create_check_constraint('ck_po_line_received_not_exceed', 'purchase_order_line', 'received_quantity <= quantity')

    op.create_table(
        'goods_receipt_note',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('grn_number', sa.String(50), nullable=False),
        sa.Column('grn_date', sa.Date, nullable=False),
        sa.Column('purchase_order_id', UUID(as_uuid=True), nullable=False),
        sa.Column('supplier_id', UUID(as_uuid=True), nullable=False),
        sa.Column('received_by', UUID(as_uuid=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_grn_number', 'goods_receipt_note', ['grn_number'])
    op.create_index('idx_grn_po', 'goods_receipt_note', ['purchase_order_id'])
    op.create_index('idx_grn_supplier', 'goods_receipt_note', ['supplier_id'])
    op.create_index('idx_grn_status', 'goods_receipt_note', ['status'])
    op.create_unique_constraint('uq_grn_number_legal_entity', 'goods_receipt_note', ['grn_number', 'legal_entity_id'])
    op.create_foreign_key('fk_grn_po', 'goods_receipt_note', 'purchase_order', ['purchase_order_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_grn_supplier', 'goods_receipt_note', 'supplier', ['supplier_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_grn_received_by', 'goods_receipt_note', 'iam_user', ['received_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_grn_legal_entity', 'goods_receipt_note', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_grn_status', 'goods_receipt_note', "status IN ('draft', 'confirmed', 'cancelled')")

    op.create_table(
        'goods_receipt_line',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('goods_receipt_note_id', UUID(as_uuid=True), nullable=False),
        sa.Column('purchase_order_line_id', UUID(as_uuid=True), nullable=False),
        sa.Column('line_number', sa.Integer, nullable=False),
        sa.Column('item_id', UUID(as_uuid=True), nullable=False),
        sa.Column('item_code', sa.String(30), nullable=False),
        sa.Column('item_name', sa.String(200), nullable=True),
        sa.Column('quantity_received', NUMERIC(20, 2), nullable=False),
        sa.Column('quantity_accepted', NUMERIC(20, 2), nullable=False),
        sa.Column('quantity_rejected', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('rejection_reason', sa.String(500), nullable=True),
        sa.Column('batch_number', sa.String(50), nullable=True),
        sa.Column('expiry_date', sa.Date, nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
    )
    op.create_index('idx_grn_line_grn', 'goods_receipt_line', ['goods_receipt_note_id'])
    op.create_index('idx_grn_line_po_line', 'goods_receipt_line', ['purchase_order_line_id'])
    op.create_index('idx_grn_line_item', 'goods_receipt_line', ['item_id'])
    op.create_index('idx_grn_line_number', 'goods_receipt_line', ['goods_receipt_note_id', 'line_number'])
    op.create_foreign_key('fk_grn_line_grn', 'goods_receipt_line', 'goods_receipt_note', ['goods_receipt_note_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_grn_line_po_line', 'goods_receipt_line', 'purchase_order_line', ['purchase_order_line_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_grn_line_item', 'goods_receipt_line', 'inventory_item', ['item_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_grn_line_legal_entity', 'goods_receipt_line', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_grn_line_quantity_positive', 'goods_receipt_line', 'quantity_received > 0')
    op.create_check_constraint('ck_grn_line_quantity_relation', 'goods_receipt_line', 'quantity_received = quantity_accepted + quantity_rejected')
    op.create_check_constraint('ck_grn_line_accepted_nonneg', 'goods_receipt_line', 'quantity_accepted >= 0')
    op.create_check_constraint('ck_grn_line_rejected_nonneg', 'goods_receipt_line', 'quantity_rejected >= 0')

def downgrade() -> None:
    op.drop_constraint('fk_grn_line_grn', 'goods_receipt_line', type_='foreignkey')
    op.drop_constraint('fk_grn_line_po_line', 'goods_receipt_line', type_='foreignkey')
    op.drop_constraint('fk_grn_line_item', 'goods_receipt_line', type_='foreignkey')
    op.drop_constraint('fk_grn_line_legal_entity', 'goods_receipt_line', type_='foreignkey')
    op.drop_constraint('ck_grn_line_quantity_positive', 'goods_receipt_line', type_='check')
    op.drop_constraint('ck_grn_line_quantity_relation', 'goods_receipt_line', type_='check')
    op.drop_constraint('ck_grn_line_accepted_nonneg', 'goods_receipt_line', type_='check')
    op.drop_constraint('ck_grn_line_rejected_nonneg', 'goods_receipt_line', type_='check')
    op.drop_index('idx_grn_line_grn', table_name='goods_receipt_line')
    op.drop_index('idx_grn_line_po_line', table_name='goods_receipt_line')
    op.drop_index('idx_grn_line_item', table_name='goods_receipt_line')
    op.drop_index('idx_grn_line_number', table_name='goods_receipt_line')
    op.drop_table('goods_receipt_line')

    op.drop_constraint('fk_grn_po', 'goods_receipt_note', type_='foreignkey')
    op.drop_constraint('fk_grn_supplier', 'goods_receipt_note', type_='foreignkey')
    op.drop_constraint('fk_grn_received_by', 'goods_receipt_note', type_='foreignkey')
    op.drop_constraint('fk_grn_legal_entity', 'goods_receipt_note', type_='foreignkey')
    op.drop_constraint('uq_grn_number_legal_entity', 'goods_receipt_note', type_='unique')
    op.drop_constraint('ck_grn_status', 'goods_receipt_note', type_='check')
    op.drop_index('idx_grn_number', table_name='goods_receipt_note')
    op.drop_index('idx_grn_po', table_name='goods_receipt_note')
    op.drop_index('idx_grn_supplier', table_name='goods_receipt_note')
    op.drop_index('idx_grn_status', table_name='goods_receipt_note')
    op.drop_table('goods_receipt_note')

    op.drop_constraint('fk_po_line_po', 'purchase_order_line', type_='foreignkey')
    op.drop_constraint('fk_po_line_item', 'purchase_order_line', type_='foreignkey')
    op.drop_constraint('fk_po_line_legal_entity', 'purchase_order_line', type_='foreignkey')
    op.drop_constraint('ck_po_line_quantity_positive', 'purchase_order_line', type_='check')
    op.drop_constraint('ck_po_line_received_not_exceed', 'purchase_order_line', type_='check')
    op.drop_index('idx_po_line_po', table_name='purchase_order_line')
    op.drop_index('idx_po_line_item', table_name='purchase_order_line')
    op.drop_index('idx_po_line_number', table_name='purchase_order_line')
    op.drop_table('purchase_order_line')

    op.drop_constraint('fk_purchase_order_supplier', 'purchase_order', type_='foreignkey')
    op.drop_constraint('fk_purchase_order_legal_entity', 'purchase_order', type_='foreignkey')
    op.drop_constraint('fk_purchase_order_approved_by', 'purchase_order', type_='foreignkey')
    op.drop_constraint('fk_purchase_order_requested_by', 'purchase_order', type_='foreignkey')
    op.drop_constraint('uq_purchase_order_number_legal_entity', 'purchase_order', type_='unique')
    op.drop_constraint('ck_po_status', 'purchase_order', type_='check')
    op.drop_index('idx_po_number', table_name='purchase_order')
    op.drop_index('idx_po_supplier', table_name='purchase_order')
    op.drop_index('idx_po_date', table_name='purchase_order')
    op.drop_index('idx_po_status', table_name='purchase_order')
    op.drop_index('idx_po_legal_entity', table_name='purchase_order')
    op.drop_index('idx_po_expected_date', table_name='purchase_order')
    op.drop_index('idx_po_approved_by', table_name='purchase_order')
    op.drop_table('purchase_order')