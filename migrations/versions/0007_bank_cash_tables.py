"""create bank_account, bank_transaction, cash_book, petty_cash_fund tables

Revision ID: 0007
Revises: 0006
Create Date: 2025-01-01 00:00:06.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, NUMERIC

revision: str = '0007'
down_revision = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # bank_account table
    op.create_table(
        'bank_account',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('account_number', sa.String(50), nullable=False),
        sa.Column('bank_name', sa.String(100), nullable=False),
        sa.Column('bank_code', sa.String(10), nullable=False),
        sa.Column('account_name', sa.String(200), nullable=False),
        sa.Column('currency_code', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('account_type', sa.String(20), nullable=False, server_default='checking'),
        sa.Column('current_balance', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('available_balance', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('gl_account_id', UUID(as_uuid=True), nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('is_default', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('opening_balance', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('opening_balance_date', sa.Date, nullable=False),
        sa.Column('last_reconciliation_date', sa.Date, nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_bank_account_number', 'bank_account', ['account_number'])
    op.create_index('idx_bank_account_legal_entity', 'bank_account', ['legal_entity_id'])
    op.create_index('idx_bank_account_status', 'bank_account', ['status'])
    op.create_index('idx_bank_account_gl_account', 'bank_account', ['gl_account_id'])
    op.create_unique_constraint('uq_bank_account_number_legal_entity', 'bank_account', ['account_number', 'legal_entity_id'])
    op.create_foreign_key('fk_bank_account_legal_entity', 'bank_account', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_bank_account_gl', 'bank_account', 'account', ['gl_account_id'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_bank_account_type', 'bank_account', "account_type IN ('checking', 'savings', 'deposit')")
    op.create_check_constraint('ck_bank_account_status', 'bank_account', "status IN ('active', 'inactive', 'closed')")

    # bank_transaction table
    op.create_table(
        'bank_transaction',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('transaction_number', sa.String(50), nullable=False),
        sa.Column('bank_account_id', UUID(as_uuid=True), nullable=False),
        sa.Column('transaction_date', sa.Date, nullable=False),
        sa.Column('transaction_type', sa.String(20), nullable=False),
        sa.Column('amount', NUMERIC(20, 2), nullable=False),
        sa.Column('currency_code', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('reference_number', sa.String(100), nullable=True),
        sa.Column('counterparty_account', sa.String(50), nullable=True),
        sa.Column('counterparty_name', sa.String(200), nullable=True),
        sa.Column('journal_id', UUID(as_uuid=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('is_reconciled', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('reconciliation_id', UUID(as_uuid=True), nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_bank_tx_account', 'bank_transaction', ['bank_account_id'])
    op.create_index('idx_bank_tx_date', 'bank_transaction', ['transaction_date'])
    op.create_index('idx_bank_tx_type', 'bank_transaction', ['transaction_type'])
    op.create_index('idx_bank_tx_status', 'bank_transaction', ['status'])
    op.create_index('idx_bank_tx_reference', 'bank_transaction', ['reference_number'])
    op.create_index('idx_bank_tx_reconciliation', 'bank_transaction', ['reconciliation_id'])
    op.create_unique_constraint('uq_bank_transaction_number_legal_entity', 'bank_transaction', ['transaction_number', 'legal_entity_id'])
    op.create_foreign_key('fk_bank_tx_account', 'bank_transaction', 'bank_account', ['bank_account_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_bank_tx_legal_entity', 'bank_transaction', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_bank_tx_type', 'bank_transaction', "transaction_type IN ('deposit', 'withdrawal', 'transfer_in', 'transfer_out', 'bank_charge', 'interest')")
    op.create_check_constraint('ck_bank_tx_status', 'bank_transaction', "status IN ('pending', 'posted', 'reconciled', 'cancelled')")

    # cash_book table
    op.create_table(
        'cash_book',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('currency_code', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('current_balance', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('opening_balance', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('opening_balance_date', sa.Date, nullable=False),
        sa.Column('gl_cash_account_id', UUID(as_uuid=True), nullable=True),
        sa.Column('gl_bank_account_id', UUID(as_uuid=True), nullable=True),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_unique_constraint('uq_cash_book_legal_entity_currency', 'cash_book', ['legal_entity_id', 'currency_code'])
    op.create_index('idx_cash_book_legal_entity', 'cash_book', ['legal_entity_id'])
    op.create_index('idx_cash_book_currency', 'cash_book', ['currency_code'])
    op.create_foreign_key('fk_cash_book_legal_entity', 'cash_book', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_cash_book_gl_cash', 'cash_book', 'account', ['gl_cash_account_id'], ['id'], ondelete='SET NULL')

    # petty_cash_fund table
    op.create_table(
        'petty_cash_fund',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('fund_name', sa.String(100), nullable=False),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('currency_code', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('current_balance', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('initial_amount', NUMERIC(20, 2), nullable=False),
        sa.Column('custodian_id', UUID(as_uuid=True), nullable=False),
        sa.Column('gl_account_id', UUID(as_uuid=True), nullable=False),
        sa.Column('reimbursement_threshold', NUMERIC(20, 2), nullable=False, server_default='1000000'),
        sa.Column('fund_location', sa.String(200), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_unique_constraint('uq_petty_cash_name_legal_entity', 'petty_cash_fund', ['fund_name', 'legal_entity_id'])
    op.create_index('idx_petty_cash_legal_entity', 'petty_cash_fund', ['legal_entity_id'])
    op.create_index('idx_petty_cash_custodian', 'petty_cash_fund', ['custodian_id'])
    op.create_foreign_key('fk_petty_cash_legal_entity', 'petty_cash_fund', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_petty_cash_gl', 'petty_cash_fund', 'account', ['gl_account_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_petty_cash_custodian', 'petty_cash_fund', 'employee', ['custodian_id'], ['id'], ondelete='RESTRICT')
    op.create_check_constraint('ck_petty_cash_status', 'petty_cash_fund', "status IN ('active', 'closed')")

def downgrade() -> None:
    op.drop_constraint('fk_petty_cash_legal_entity', 'petty_cash_fund', type_='foreignkey')
    op.drop_constraint('fk_petty_cash_gl', 'petty_cash_fund', type_='foreignkey')
    op.drop_constraint('fk_petty_cash_custodian', 'petty_cash_fund', type_='foreignkey')
    op.drop_constraint('uq_petty_cash_name_legal_entity', 'petty_cash_fund', type_='unique')
    op.drop_constraint('ck_petty_cash_status', 'petty_cash_fund', type_='check')
    op.drop_index('idx_petty_cash_legal_entity', table_name='petty_cash_fund')
    op.drop_index('idx_petty_cash_custodian', table_name='petty_cash_fund')
    op.drop_table('petty_cash_fund')

    op.drop_constraint('fk_cash_book_legal_entity', 'cash_book', type_='foreignkey')
    op.drop_constraint('fk_cash_book_gl_cash', 'cash_book', type_='foreignkey')
    op.drop_constraint('uq_cash_book_legal_entity_currency', 'cash_book', type_='unique')
    op.drop_index('idx_cash_book_legal_entity', table_name='cash_book')
    op.drop_index('idx_cash_book_currency', table_name='cash_book')
    op.drop_table('cash_book')

    op.drop_constraint('fk_bank_tx_account', 'bank_transaction', type_='foreignkey')
    op.drop_constraint('fk_bank_tx_legal_entity', 'bank_transaction', type_='foreignkey')
    op.drop_constraint('uq_bank_transaction_number_legal_entity', 'bank_transaction', type_='unique')
    op.drop_constraint('ck_bank_tx_type', 'bank_transaction', type_='check')
    op.drop_constraint('ck_bank_tx_status', 'bank_transaction', type_='check')
    op.drop_index('idx_bank_tx_account', table_name='bank_transaction')
    op.drop_index('idx_bank_tx_date', table_name='bank_transaction')
    op.drop_index('idx_bank_tx_type', table_name='bank_transaction')
    op.drop_index('idx_bank_tx_status', table_name='bank_transaction')
    op.drop_index('idx_bank_tx_reference', table_name='bank_transaction')
    op.drop_index('idx_bank_tx_reconciliation', table_name='bank_transaction')
    op.drop_table('bank_transaction')

    op.drop_constraint('fk_bank_account_legal_entity', 'bank_account', type_='foreignkey')
    op.drop_constraint('fk_bank_account_gl', 'bank_account', type_='foreignkey')
    op.drop_constraint('uq_bank_account_number_legal_entity', 'bank_account', type_='unique')
    op.drop_constraint('ck_bank_account_type', 'bank_account', type_='check')
    op.drop_constraint('ck_bank_account_status', 'bank_account', type_='check')
    op.drop_index('idx_bank_account_number', table_name='bank_account')
    op.drop_index('idx_bank_account_legal_entity', table_name='bank_account')
    op.drop_index('idx_bank_account_status', table_name='bank_account')
    op.drop_index('idx_bank_account_gl_account', table_name='bank_account')
    op.drop_table('bank_account')