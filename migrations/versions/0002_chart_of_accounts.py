"""create account table (Chart of Accounts)

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-01 00:00:01.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, NUMERIC

revision: str = '0002abcd'
down_revision = '0001abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'account',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('account_code', sa.String(20), nullable=False),
        sa.Column('account_name', sa.String(200), nullable=False),
        sa.Column('account_type', sa.String(20), nullable=False),
        sa.Column('normal_balance', sa.String(6), nullable=False),
        sa.Column('parent_account_id', UUID(as_uuid=True), nullable=True),
        sa.Column('level', sa.Integer, nullable=False, server_default='1'),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('currency_code', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('is_bank_account', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('is_cash_account', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('is_intercompany', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('is_header', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('opening_balance_debit', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('opening_balance_credit', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_account_account_code', 'account', ['account_code'])
    op.create_index('idx_account_type', 'account', ['account_type'])
    op.create_index('idx_account_parent', 'account', ['parent_account_id'])
    op.create_index('idx_account_legal_entity', 'account', ['legal_entity_id'])
    op.create_index('idx_account_status', 'account', ['status'])
    op.create_unique_constraint('uq_account_code_legal_entity', 'account', ['account_code', 'legal_entity_id'])
    op.create_foreign_key('fk_account_parent', 'account', 'account', ['parent_account_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_account_legal_entity', 'account', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_account_type', 'account', "account_type IN ('Asset', 'Liability', 'Equity', 'Revenue', 'Expense', 'ContraAsset', 'ContraLiability', 'ContraEquity')")
    op.create_check_constraint('ck_normal_balance', 'account', "normal_balance IN ('debit', 'credit')")
    op.create_check_constraint('ck_account_level', 'account', 'level BETWEEN 1 AND 10')

def downgrade() -> None:
    op.drop_constraint('fk_account_parent', 'account', type_='foreignkey')
    op.drop_constraint('fk_account_legal_entity', 'account', type_='foreignkey')
    op.drop_constraint('uq_account_code_legal_entity', 'account', type_='unique')
    op.drop_constraint('ck_account_type', 'account', type_='check')
    op.drop_constraint('ck_normal_balance', 'account', type_='check')
    op.drop_constraint('ck_account_level', 'account', type_='check')
    op.drop_index('idx_account_account_code', table_name='account')
    op.drop_index('idx_account_type', table_name='account')
    op.drop_index('idx_account_parent', table_name='account')
    op.drop_index('idx_account_legal_entity', table_name='account')
    op.drop_index('idx_account_status', table_name='account')
    op.drop_table('account')