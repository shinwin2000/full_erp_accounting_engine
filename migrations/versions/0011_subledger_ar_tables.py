"""create subledger AR tables: ar_invoice, ar_invoice_line, ar_payment, ar_credit_note

Revision ID: 0011
Revises: 0010
Create Date: 2025-01-01 00:00:10.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, NUMERIC

revision: str = '0011'
down_revision = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'ar_invoice',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('invoice_number', sa.String(50), nullable=False),
        sa.Column('invoice_date', sa.Date, nullable=False),
        sa.Column('due_date', sa.Date, nullable=False),
        sa.Column('customer_id', UUID(as_uuid=True), nullable=False),
        sa.Column('total_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('paid_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('tax_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('discount_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('reference_number', sa.String(100), nullable=True),
        sa.Column('sales_order_id', UUID(as_uuid=True), nullable=True),
        sa.Column('tax_invoice_number', sa.String(50), nullable=True),
        sa.Column('approved_by', UUID(as_uuid=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_ar_invoice_number', 'ar_invoice', ['invoice_number'])
    op.create_index('idx_ar_invoice_customer', 'ar_invoice', ['customer_id'])
    op.create_index('idx_ar_invoice_date', 'ar_invoice', ['invoice_date'])
    op.create_index('idx_ar_invoice_due_date', 'ar_invoice', ['due_date'])
    op.create_index('idx_ar_invoice_status', 'ar_invoice', ['status'])
    op.create_index('idx_ar_invoice_legal_entity', 'ar_invoice', ['legal_entity_id'])
    op.create_index('idx_ar_invoice_sales_order', 'ar_invoice', ['sales_order_id'])
    op.create_index('idx_ar_invoice_outstanding', 'ar_invoice', ['total_amount', 'paid_amount'])
    op.create_unique_constraint('uq_ar_invoice_number_legal_entity', 'ar_invoice', ['invoice_number', 'legal_entity_id'])
    op.create_foreign_key('fk_ar_invoice_customer', 'ar_invoice', 'customer', ['customer_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_ar_invoice_legal_entity', 'ar_invoice', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_ar_invoice_approved_by', 'ar_invoice', 'iam_user', ['approved_by'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_ar_invoice_status', 'ar_invoice', "status IN ('draft', 'submitted', 'approved', 'partially_paid', 'paid', 'overdue', 'cancelled')")

    op.create_table(
        'ar_invoice_line',
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
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
    )
    op.create_index('idx_ar_invoice_line_invoice', 'ar_invoice_line', ['invoice_id'])
    op.create_index('idx_ar_invoice_line_number', 'ar_invoice_line', ['invoice_id', 'line_number'])
    op.create_foreign_key('fk_ar_invoice_line_invoice', 'ar_invoice_line', 'ar_invoice', ['invoice_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_ar_invoice_line_legal_entity', 'ar_invoice_line', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_ar_invoice_line_quantity', 'ar_invoice_line', 'quantity >= 0')
    op.create_check_constraint('ck_ar_invoice_line_unit_price', 'ar_invoice_line', 'unit_price >= 0')

    op.create_table(
        'ar_payment',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('payment_number', sa.String(50), nullable=False),
        sa.Column('payment_date', sa.Date, nullable=False),
        sa.Column('invoice_id', UUID(as_uuid=True), nullable=False),
        sa.Column('customer_id', UUID(as_uuid=True), nullable=False),
        sa.Column('amount', NUMERIC(20, 2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('payment_method', sa.String(20), nullable=False),
        sa.Column('reference_number', sa.String(100), nullable=True),
        sa.Column('bank_account_id', UUID(as_uuid=True), nullable=True),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_ar_payment_number', 'ar_payment', ['payment_number'])
    op.create_index('idx_ar_payment_invoice', 'ar_payment', ['invoice_id'])
    op.create_index('idx_ar_payment_customer', 'ar_payment', ['customer_id'])
    op.create_index('idx_ar_payment_date', 'ar_payment', ['payment_date'])
    op.create_index('idx_ar_payment_status', 'ar_payment', ['status'])
    op.create_index('idx_ar_payment_reference', 'ar_payment', ['reference_number'])
    op.create_unique_constraint('uq_ar_payment_number_legal_entity', 'ar_payment', ['payment_number', 'legal_entity_id'])
    op.create_foreign_key('fk_ar_payment_invoice', 'ar_payment', 'ar_invoice', ['invoice_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_ar_payment_customer', 'ar_payment', 'customer', ['customer_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_ar_payment_legal_entity', 'ar_payment', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_ar_payment_bank_account', 'ar_payment', 'bank_account', ['bank_account_id'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_ar_payment_method', 'ar_payment', "payment_method IN ('cash', 'transfer', 'credit_card', 'giro', 'other')")
    op.create_check_constraint('ck_ar_payment_status', 'ar_payment', "status IN ('pending', 'completed', 'failed', 'cancelled')")

    op.create_table(
        'ar_credit_note',
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
    op.create_index('idx_ar_credit_note_number', 'ar_credit_note', ['credit_note_number'])
    op.create_index('idx_ar_credit_note_invoice', 'ar_credit_note', ['invoice_id'])
    op.create_index('idx_ar_credit_note_date', 'ar_credit_note', ['credit_note_date'])
    op.create_index('idx_ar_credit_note_status', 'ar_credit_note', ['status'])
    op.create_unique_constraint('uq_ar_credit_note_number_legal_entity', 'ar_credit_note', ['credit_note_number', 'legal_entity_id'])
    op.create_foreign_key('fk_ar_credit_note_invoice', 'ar_credit_note', 'ar_invoice', ['invoice_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_ar_credit_note_legal_entity', 'ar_credit_note', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_ar_credit_note_applied_by', 'ar_credit_note', 'iam_user', ['applied_by'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_ar_credit_note_status', 'ar_credit_note', "status IN ('active', 'applied', 'cancelled')")

def downgrade() -> None:
    op.drop_constraint('fk_ar_credit_note_invoice', 'ar_credit_note', type_='foreignkey')
    op.drop_constraint('fk_ar_credit_note_legal_entity', 'ar_credit_note', type_='foreignkey')
    op.drop_constraint('fk_ar_credit_note_applied_by', 'ar_credit_note', type_='foreignkey')
    op.drop_constraint('uq_ar_credit_note_number_legal_entity', 'ar_credit_note', type_='unique')
    op.drop_constraint('ck_ar_credit_note_status', 'ar_credit_note', type_='check')
    op.drop_index('idx_ar_credit_note_number', table_name='ar_credit_note')
    op.drop_index('idx_ar_credit_note_invoice', table_name='ar_credit_note')
    op.drop_index('idx_ar_credit_note_date', table_name='ar_credit_note')
    op.drop_index('idx_ar_credit_note_status', table_name='ar_credit_note')
    op.drop_table('ar_credit_note')

    op.drop_constraint('fk_ar_payment_invoice', 'ar_payment', type_='foreignkey')
    op.drop_constraint('fk_ar_payment_customer', 'ar_payment', type_='foreignkey')
    op.drop_constraint('fk_ar_payment_legal_entity', 'ar_payment', type_='foreignkey')
    op.drop_constraint('fk_ar_payment_bank_account', 'ar_payment', type_='foreignkey')
    op.drop_constraint('uq_ar_payment_number_legal_entity', 'ar_payment', type_='unique')
    op.drop_constraint('ck_ar_payment_method', 'ar_payment', type_='check')
    op.drop_constraint('ck_ar_payment_status', 'ar_payment', type_='check')
    op.drop_index('idx_ar_payment_number', table_name='ar_payment')
    op.drop_index('idx_ar_payment_invoice', table_name='ar_payment')
    op.drop_index('idx_ar_payment_customer', table_name='ar_payment')
    op.drop_index('idx_ar_payment_date', table_name='ar_payment')
    op.drop_index('idx_ar_payment_status', table_name='ar_payment')
    op.drop_index('idx_ar_payment_reference', table_name='ar_payment')
    op.drop_table('ar_payment')

    op.drop_constraint('fk_ar_invoice_line_invoice', 'ar_invoice_line', type_='foreignkey')
    op.drop_constraint('fk_ar_invoice_line_legal_entity', 'ar_invoice_line', type_='foreignkey')
    op.drop_constraint('ck_ar_invoice_line_quantity', 'ar_invoice_line', type_='check')
    op.drop_constraint('ck_ar_invoice_line_unit_price', 'ar_invoice_line', type_='check')
    op.drop_index('idx_ar_invoice_line_invoice', table_name='ar_invoice_line')
    op.drop_index('idx_ar_invoice_line_number', table_name='ar_invoice_line')
    op.drop_table('ar_invoice_line')

    op.drop_constraint('fk_ar_invoice_customer', 'ar_invoice', type_='foreignkey')
    op.drop_constraint('fk_ar_invoice_legal_entity', 'ar_invoice', type_='foreignkey')
    op.drop_constraint('fk_ar_invoice_approved_by', 'ar_invoice', type_='foreignkey')
    op.drop_constraint('uq_ar_invoice_number_legal_entity', 'ar_invoice', type_='unique')
    op.drop_constraint('ck_ar_invoice_status', 'ar_invoice', type_='check')
    op.drop_index('idx_ar_invoice_number', table_name='ar_invoice')
    op.drop_index('idx_ar_invoice_customer', table_name='ar_invoice')
    op.drop_index('idx_ar_invoice_date', table_name='ar_invoice')
    op.drop_index('idx_ar_invoice_due_date', table_name='ar_invoice')
    op.drop_index('idx_ar_invoice_status', table_name='ar_invoice')
    op.drop_index('idx_ar_invoice_legal_entity', table_name='ar_invoice')
    op.drop_index('idx_ar_invoice_sales_order', table_name='ar_invoice')
    op.drop_index('idx_ar_invoice_outstanding', table_name='ar_invoice')
    op.drop_table('ar_invoice')