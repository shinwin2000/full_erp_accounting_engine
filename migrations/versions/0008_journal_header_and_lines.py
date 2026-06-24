"""create journal_header and journal_line tables

Revision ID: 0008
Revises: 0007
Create Date: 2025-01-01 00:00:07.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, NUMERIC

revision: str = '0008abcd'
down_revision = '0007abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'journal_header',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('voucher_number', sa.String(50), nullable=False),
        sa.Column('journal_date', sa.Date, nullable=False),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('total_debit', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('total_credit', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('approved_by', UUID(as_uuid=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('posted_by', UUID(as_uuid=True), nullable=True),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reversed_by', UUID(as_uuid=True), nullable=True),
        sa.Column('reversed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reversed_journal_id', UUID(as_uuid=True), nullable=True),
        sa.Column('original_journal_id', UUID(as_uuid=True), nullable=True),
        sa.Column('reference_number', sa.String(100), nullable=True),
        sa.Column('source_type', sa.String(50), nullable=False, server_default='manual'),
        sa.Column('source_id', UUID(as_uuid=True), nullable=True),
        sa.Column('period_id', UUID(as_uuid=True), nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_journal_header_voucher', 'journal_header', ['voucher_number'])
    op.create_index('idx_journal_header_date', 'journal_header', ['journal_date'])
    op.create_index('idx_journal_header_status', 'journal_header', ['status'])
    op.create_index('idx_journal_header_legal_entity', 'journal_header', ['legal_entity_id'])
    op.create_index('idx_journal_header_period', 'journal_header', ['period_id'])
    op.create_index('idx_journal_header_source', 'journal_header', ['source_type', 'source_id'])
    op.create_index('idx_journal_header_created_by', 'journal_header', ['created_by'])
    op.create_index('idx_journal_header_approved_by', 'journal_header', ['approved_by'])
    op.create_index('idx_journal_header_posted_by', 'journal_header', ['posted_by'])
    op.create_unique_constraint('uq_journal_header_voucher_legal_entity', 'journal_header', ['voucher_number', 'legal_entity_id'])
    op.create_foreign_key('fk_journal_header_legal_entity', 'journal_header', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_journal_header_approved_by', 'journal_header', 'iam_user', ['approved_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_journal_header_posted_by', 'journal_header', 'iam_user', ['posted_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_journal_header_reversed', 'journal_header', 'journal_header', ['reversed_journal_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_journal_header_original', 'journal_header', 'journal_header', ['original_journal_id'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_journal_header_status', 'journal_header', "status IN ('draft', 'submitted', 'approved', 'posted', 'reversed', 'cancelled')")

    op.create_table(
        'journal_line',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('journal_id', UUID(as_uuid=True), nullable=False),
        sa.Column('line_number', sa.Integer, nullable=False),
        sa.Column('account_code', sa.String(20), nullable=False),
        sa.Column('account_name', sa.String(200), nullable=True),
        sa.Column('debit_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('credit_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('cost_center', sa.String(20), nullable=True),
        sa.Column('department', sa.String(20), nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
    )
    op.create_index('idx_journal_line_journal', 'journal_line', ['journal_id'])
    op.create_index('idx_journal_line_account', 'journal_line', ['account_code'])
    op.create_index('idx_journal_line_legal_entity', 'journal_line', ['legal_entity_id'])
    op.create_index('idx_journal_line_cost_center', 'journal_line', ['cost_center'])
    op.create_foreign_key('fk_journal_line_journal', 'journal_line', 'journal_header', ['journal_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_journal_line_legal_entity', 'journal_line', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_journal_line_nonzero', 'journal_line', 'debit_amount > 0 OR credit_amount > 0')
    op.create_check_constraint('ck_journal_line_line_number', 'journal_line', 'line_number >= 1')

def downgrade() -> None:
    op.drop_constraint('fk_journal_line_journal', 'journal_line', type_='foreignkey')
    op.drop_constraint('fk_journal_line_legal_entity', 'journal_line', type_='foreignkey')
    op.drop_constraint('ck_journal_line_nonzero', 'journal_line', type_='check')
    op.drop_constraint('ck_journal_line_line_number', 'journal_line', type_='check')
    op.drop_index('idx_journal_line_journal', table_name='journal_line')
    op.drop_index('idx_journal_line_account', table_name='journal_line')
    op.drop_index('idx_journal_line_legal_entity', table_name='journal_line')
    op.drop_index('idx_journal_line_cost_center', table_name='journal_line')
    op.drop_table('journal_line')

    op.drop_constraint('fk_journal_header_legal_entity', 'journal_header', type_='foreignkey')
    op.drop_constraint('fk_journal_header_approved_by', 'journal_header', type_='foreignkey')
    op.drop_constraint('fk_journal_header_posted_by', 'journal_header', type_='foreignkey')
    op.drop_constraint('fk_journal_header_reversed', 'journal_header', type_='foreignkey')
    op.drop_constraint('fk_journal_header_original', 'journal_header', type_='foreignkey')
    op.drop_constraint('uq_journal_header_voucher_legal_entity', 'journal_header', type_='unique')
    op.drop_constraint('ck_journal_header_status', 'journal_header', type_='check')
    op.drop_index('idx_journal_header_voucher', table_name='journal_header')
    op.drop_index('idx_journal_header_date', table_name='journal_header')
    op.drop_index('idx_journal_header_status', table_name='journal_header')
    op.drop_index('idx_journal_header_legal_entity', table_name='journal_header')
    op.drop_index('idx_journal_header_period', table_name='journal_header')
    op.drop_index('idx_journal_header_source', table_name='journal_header')
    op.drop_index('idx_journal_header_created_by', table_name='journal_header')
    op.drop_index('idx_journal_header_approved_by', table_name='journal_header')
    op.drop_index('idx_journal_header_posted_by', table_name='journal_header')
    op.drop_table('journal_header')