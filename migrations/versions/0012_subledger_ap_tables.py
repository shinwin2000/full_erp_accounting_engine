"""create subledger AP tables: ap_invoice, ap_invoice_line, ap_payment, ap_credit_note

Revision ID: 0012
Revises: 0011
Create Date: 2025-01-01 00:00:11.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, NUMERIC

revision: str = '0012abcd'
down_revision = '0011abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'ap_invoice',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('invoice_number', sa.String(50), nullable=False),
        sa.Column('invoice_date', sa.Date, nullable=False),
        sa.Column('due_date', sa.Date, nullable=False),
        sa.Column('invoice_number_vendor', sa.String(50), nullable=False),
        sa.Column('vendor_id', UUID(as_uuid=True), nullable=False),
        sa.Column('total_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('paid_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('tax_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('discount_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('reference_number', sa.String(100), nullable=True),
        sa.Column('purchase_order_id', UUID(as_uuid=True), nullable=True),
        sa.Column('goods_receipt_note_id', UUID(as_uuid=True), nullable=True),
        sa.Column('tax_invoice_number', sa.String(50), nullable=True),
        sa.Column('three_way_match_status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('approved_by', UUID(as_uuid=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('payment_run_id', UUID(as_uuid=True), nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_ap_invoice_number', 'ap_invoice', ['invoice_number'])
    op.create_index('idx_ap_invoice_vendor', 'ap_invoice', ['vendor_id'])
    op.create_index('idx_ap_invoice_date', 'ap_invoice', ['invoice_date'])
    op.create_index('idx_ap_invoice_due_date', 'ap_invoice', ['due_date'])
    op.create_index('idx_ap_invoice_status', 'ap_invoice', ['status'])
    op.create_index('idx_ap_invoice_legal_entity', 'ap_invoice', ['legal_entity_id'])
    op.create_index('idx_ap_invoice_po', 'ap_invoice', ['purchase_order_id'])
    op.create_index('idx_ap_invoice_grn', 'ap_invoice', ['goods_receipt_note_id'])
    op.create_index('idx_ap_invoice_3way_status', 'ap_invoice', ['three_way_match_status'])
    op.create_index('idx_ap_invoice_vendor_number', 'ap_invoice', ['invoice_number_vendor'])
    op.create_unique_constraint('uq_ap_invoice_number_legal_entity', 'ap_invoice', ['invoice_number', 'legal_entity_id'])
    op.create_foreign_key('fk_ap_invoice_vendor', 'ap_invoice', 'supplier', ['vendor_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_ap_invoice_legal_entity', 'ap_invoice', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_ap_invoice_approved_by', 'ap_invoice', 'iam_user', ['approved_by'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_ap_invoice_status', 'ap_invoice', "status IN ('draft', 'submitted', 'approved', 'partially_paid', 'paid', 'cancelled')")
    op.create_check_constraint('ck_ap_invoice_3way_status', 'ap_invoice', "three_way_match_status IN ('pending', 'match', 'mismatch', 'not_applicable')")

    op.create_table(
        'ap_invoice_line',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('invoice_id', UUID(as_uuid=True), nullable=False),
        sa.Column('line_number', sa.Integer, nullable=False),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('quantity', NUMERIC(20, 2), nullable=False, server_default='1'),
        sa.Column('unit_price', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('discount_percent', NUMERIC(5, 2), nullable=False, server_default='0'),
        sa.Column('tax_rate', NUMERIC(5, 2), nullable=False, server_default='0'),
        sa.Column('account_code', sa.String(20), nullable=False),
        sa.Column('total_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('tax_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('purchase_order_line_id', UUID(as_uuid=True), nullable=True),
        sa.Column('goods_receipt_line_id', UUID(as_uuid=True), nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
    )
    op.create_index('idx_ap_invoice_line_invoice', 'ap_invoice_line', ['invoice_id'])
    op.create_index('idx_ap_invoice_line_number', 'ap_invoice_line', ['invoice_id', 'line_number'])
    op.create_foreign_key('fk_ap_invoice_line_invoice', 'ap_invoice_line', 'ap_invoice', ['invoice_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_ap_invoice_line_legal_entity', 'ap_invoice_line', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_ap_invoice_line_quantity', 'ap_invoice_line', 'quantity >= 0')
    op.create_check_constraint('ck_ap_invoice_line_unit_price', 'ap_invoice_line', 'unit_price >= 0')

    op.create_table(
        'ap_payment',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('payment_number', sa.String(50), nullable=False),
        sa.Column('payment_date', sa.Date, nullable=False),
        sa.Column('invoice_id', UUID(as_uuid=True), nullable=False),
        sa.Column('supplier_id', UUID(as_uuid=True), nullable=False),
        sa.Column('amount', NUMERIC(20, 2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('payment_method', sa.String(20), nullable=False),
        sa.Column('reference_number', sa.String(100), nullable=True),
        sa.Column('bank_account_id', UUID(as_uuid=True), nullable=True),
        sa.Column('payment_run_id', UUID(as_uuid=True), nullable=True),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_ap_payment_number', 'ap_payment', ['payment_number'])
    op.create_index('idx_ap_payment_invoice', 'ap_payment', ['invoice_id'])
    op.create_index('idx_ap_payment_supplier', 'ap_payment', ['supplier_id'])
    op.create_index('idx_ap_payment_date', 'ap_payment', ['payment_date'])
    op.create_index('idx_ap_payment_status', 'ap_payment', ['status'])
    op.create_index('idx_ap_payment_reference', 'ap_payment', ['reference_number'])
    op.create_index('idx_ap_payment_bank_account', 'ap_payment', ['bank_account_id'])
    op.create_index('idx_ap_payment_run', 'ap_payment', ['payment_run_id'])
    op.create_unique_constraint('uq_ap_payment_number_legal_entity', 'ap_payment', ['payment_number', 'legal_entity_id'])
    op.create_foreign_key('fk_ap_payment_invoice', 'ap_payment', 'ap_invoice', ['invoice_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_ap_payment_supplier', 'ap_payment', 'supplier', ['supplier_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_ap_payment_legal_entity', 'ap_payment', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_ap_payment_bank_account', 'ap_payment', 'bank_account', ['bank_account_id'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_ap_payment_method', 'ap_payment', "payment_method IN ('cash', 'transfer', 'giro', 'skbdn', 'other')")
    op.create_check_constraint('ck_ap_payment_status', 'ap_payment', "status IN ('pending', 'processed', 'completed', 'failed', 'cancelled')")

    op.create_table(
        'ap_credit_note',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('credit_note_number', sa.String(50), nullable=False),
        sa.Column('credit_note_date', sa.Date, nullable=False),
        sa.Column('invoice_id', UUID(as_uuid=True), nullable=False),
        sa.Column('amount', NUMERIC(20, 2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('reason', sa.Text, nullable=False),
        sa.Column('reference_number', sa.String(100), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('applied_by', UUID(as_uuid=True), nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_ap_credit_note_number', 'ap_credit_note', ['credit_note_number'])
    op.create_index('idx_ap_credit_note_invoice', 'ap_credit_note', ['invoice_id'])
    op.create_index('idx_ap_credit_note_date', 'ap_credit_note', ['credit_note_date'])
    op.create_index('idx_ap_credit_note_status', 'ap_credit_note', ['status'])
    op.create_unique_constraint('uq_ap_credit_note_number_legal_entity', 'ap_credit_note', ['credit_note_number', 'legal_entity_id'])
    op.create_foreign_key('fk_ap_credit_note_invoice', 'ap_credit_note', 'ap_invoice', ['invoice_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_ap_credit_note_legal_entity', 'ap_credit_note', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_ap_credit_note_applied_by', 'ap_credit_note', 'iam_user', ['applied_by'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_ap_credit_note_status', 'ap_credit_note', "status IN ('active', 'applied', 'cancelled')")

def downgrade() -> None:
    op.drop_constraint('fk_ap_credit_note_invoice', 'ap_credit_note', type_='foreignkey')
    op.drop_constraint('fk_ap_credit_note_legal_entity', 'ap_credit_note', type_='foreignkey')
    op.drop_constraint('fk_ap_credit_note_applied_by', 'ap_credit_note', type_='foreignkey')
    op.drop_constraint('uq_ap_credit_note_number_legal_entity', 'ap_credit_note', type_='unique')
    op.drop_constraint('ck_ap_credit_note_status', 'ap_credit_note', type_='check')
    op.drop_index('idx_ap_credit_note_number', table_name='ap_credit_note')
    op.drop_index('idx_ap_credit_note_invoice', table_name='ap_credit_note')
    op.drop_index('idx_ap_credit_note_date', table_name='ap_credit_note')
    op.drop_index('idx_ap_credit_note_status', table_name='ap_credit_note')
    op.drop_table('ap_credit_note')

    op.drop_constraint('fk_ap_payment_invoice', 'ap_payment', type_='foreignkey')
    op.drop_constraint('fk_ap_payment_supplier', 'ap_payment', type_='foreignkey')
    op.drop_constraint('fk_ap_payment_legal_entity', 'ap_payment', type_='foreignkey')
    op.drop_constraint('fk_ap_payment_bank_account', 'ap_payment', type_='foreignkey')
    op.drop_constraint('uq_ap_payment_number_legal_entity', 'ap_payment', type_='unique')
    op.drop_constraint('ck_ap_payment_method', 'ap_payment', type_='check')
    op.drop_constraint('ck_ap_payment_status', 'ap_payment', type_='check')
    op.drop_index('idx_ap_payment_number', table_name='ap_payment')
    op.drop_index('idx_ap_payment_invoice', table_name='ap_payment')
    op.drop_index('idx_ap_payment_supplier', table_name='ap_payment')
    op.drop_index('idx_ap_payment_date', table_name='ap_payment')
    op.drop_index('idx_ap_payment_status', table_name='ap_payment')
    op.drop_index('idx_ap_payment_reference', table_name='ap_payment')
    op.drop_index('idx_ap_payment_bank_account', table_name='ap_payment')
    op.drop_index('idx_ap_payment_run', table_name='ap_payment')
    op.drop_table('ap_payment')

    op.drop_constraint('fk_ap_invoice_line_invoice', 'ap_invoice_line', type_='foreignkey')
    op.drop_constraint('fk_ap_invoice_line_legal_entity', 'ap_invoice_line', type_='foreignkey')
    op.drop_constraint('ck_ap_invoice_line_quantity', 'ap_invoice_line', type_='check')
    op.drop_constraint('ck_ap_invoice_line_unit_price', 'ap_invoice_line', type_='check')
    op.drop_index('idx_ap_invoice_line_invoice', table_name='ap_invoice_line')
    op.drop_index('idx_ap_invoice_line_number', table_name='ap_invoice_line')
    op.drop_table('ap_invoice_line')

    op.drop_constraint('fk_ap_invoice_vendor', 'ap_invoice', type_='foreignkey')
    op.drop_constraint('fk_ap_invoice_legal_entity', 'ap_invoice', type_='foreignkey')
    op.drop_constraint('fk_ap_invoice_approved_by', 'ap_invoice', type_='foreignkey')
    op.drop_constraint('uq_ap_invoice_number_legal_entity', 'ap_invoice', type_='unique')
    op.drop_constraint('ck_ap_invoice_status', 'ap_invoice', type_='check')
    op.drop_constraint('ck_ap_invoice_3way_status', 'ap_invoice', type_='check')
    op.drop_index('idx_ap_invoice_number', table_name='ap_invoice')
    op.drop_index('idx_ap_invoice_vendor', table_name='ap_invoice')
    op.drop_index('idx_ap_invoice_date', table_name='ap_invoice')
    op.drop_index('idx_ap_invoice_due_date', table_name='ap_invoice')
    op.drop_index('idx_ap_invoice_status', table_name='ap_invoice')
    op.drop_index('idx_ap_invoice_legal_entity', table_name='ap_invoice')
    op.drop_index('idx_ap_invoice_po', table_name='ap_invoice')
    op.drop_index('idx_ap_invoice_grn', table_name='ap_invoice')
    op.drop_index('idx_ap_invoice_3way_status', table_name='ap_invoice')
    op.drop_index('idx_ap_invoice_vendor_number', table_name='ap_invoice')
    op.drop_table('ap_invoice')