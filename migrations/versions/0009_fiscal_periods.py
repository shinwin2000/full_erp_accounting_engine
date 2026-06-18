"""create fiscal_period table

Revision ID: 0009
Revises: 0008
Create Date: 2025-01-01 00:00:08.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = '0009'
down_revision = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'fiscal_period',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('fiscal_year', sa.Integer, nullable=False),
        sa.Column('period_number', sa.Integer, nullable=False),
        sa.Column('period_type', sa.String(10), nullable=False, server_default='month'),
        sa.Column('start_date', sa.Date, nullable=False),
        sa.Column('end_date', sa.Date, nullable=False),
        sa.Column('period_name', sa.String(50), nullable=False),
        sa.Column('status', sa.String(10), nullable=False, server_default='open'),
        sa.Column('closed_by', UUID(as_uuid=True), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('locked_by', UUID(as_uuid=True), nullable=True),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_fiscal_period_legal_entity', 'fiscal_period', ['legal_entity_id'])
    op.create_index('idx_fiscal_period_dates', 'fiscal_period', ['start_date', 'end_date'])
    op.create_index('idx_fiscal_period_status', 'fiscal_period', ['status'])
    op.create_index('idx_fiscal_period_year', 'fiscal_period', ['fiscal_year'])
    op.create_unique_constraint('uq_fiscal_period_year_period', 'fiscal_period', ['legal_entity_id', 'fiscal_year', 'period_number'])
    op.create_foreign_key('fk_fiscal_period_legal_entity', 'fiscal_period', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_fiscal_period_closed_by', 'fiscal_period', 'iam_user', ['closed_by'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_fiscal_period_number', 'fiscal_period', 'period_number BETWEEN 1 AND 13')
    op.create_check_constraint('ck_fiscal_period_type', 'fiscal_period', "period_type IN ('month', 'quarter', 'year')")
    op.create_check_constraint('ck_fiscal_period_status', 'fiscal_period', "status IN ('open', 'closed', 'locked')")
    op.create_check_constraint('ck_fiscal_period_dates', 'fiscal_period', 'start_date <= end_date')

    # FK dari journal_header ke fiscal_period (ditambahkan setelah tabel fiscal_period ada)
    op.create_foreign_key('fk_journal_header_period', 'journal_header', 'fiscal_period', ['period_id'], ['id'], ondelete='SET NULL')

def downgrade() -> None:
    op.drop_constraint('fk_journal_header_period', 'journal_header', type_='foreignkey')
    op.drop_constraint('fk_fiscal_period_legal_entity', 'fiscal_period', type_='foreignkey')
    op.drop_constraint('fk_fiscal_period_closed_by', 'fiscal_period', type_='foreignkey')
    op.drop_constraint('uq_fiscal_period_year_period', 'fiscal_period', type_='unique')
    op.drop_constraint('ck_fiscal_period_number', 'fiscal_period', type_='check')
    op.drop_constraint('ck_fiscal_period_type', 'fiscal_period', type_='check')
    op.drop_constraint('ck_fiscal_period_status', 'fiscal_period', type_='check')
    op.drop_constraint('ck_fiscal_period_dates', 'fiscal_period', type_='check')
    op.drop_index('idx_fiscal_period_legal_entity', table_name='fiscal_period')
    op.drop_index('idx_fiscal_period_dates', table_name='fiscal_period')
    op.drop_index('idx_fiscal_period_status', table_name='fiscal_period')
    op.drop_index('idx_fiscal_period_year', table_name='fiscal_period')
    op.drop_table('fiscal_period')