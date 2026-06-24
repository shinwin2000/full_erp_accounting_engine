"""create intangible_asset and amortization_schedule tables

Revision ID: 0016
Revises: 0015
Create Date: 2025-01-01 00:00:15.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, NUMERIC

revision: str = '0016abcd'
down_revision = '0015abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'intangible_asset',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('asset_code', sa.String(30), nullable=False),
        sa.Column('asset_name', sa.String(200), nullable=False),
        sa.Column('asset_category', sa.String(50), nullable=False),
        sa.Column('acquisition_date', sa.Date, nullable=False),
        sa.Column('acquisition_cost', NUMERIC(20, 2), nullable=False),
        sa.Column('residual_value', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('useful_life_years', sa.Integer, nullable=False),
        sa.Column('amortization_method', sa.String(25), nullable=False, server_default='straight_line'),
        sa.Column('amortization_rate', NUMERIC(5, 2), nullable=True),
        sa.Column('accumulated_amortization', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('last_amortization_date', sa.Date, nullable=True),
        sa.Column('current_period_amortization', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_intangible_asset_code', 'intangible_asset', ['asset_code'])
    op.create_index('idx_intangible_asset_category', 'intangible_asset', ['asset_category'])
    op.create_index('idx_intangible_asset_status', 'intangible_asset', ['status'])
    op.create_index('idx_intangible_asset_legal_entity', 'intangible_asset', ['legal_entity_id'])
    op.create_index('idx_intangible_asset_acquisition_date', 'intangible_asset', ['acquisition_date'])
    op.create_index('idx_intangible_asset_is_active', 'intangible_asset', ['is_active'])
    op.create_unique_constraint('uq_intangible_asset_code_legal_entity', 'intangible_asset', ['asset_code', 'legal_entity_id'])
    op.create_foreign_key('fk_intangible_asset_legal_entity', 'intangible_asset', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_intangible_asset_amortization_method', 'intangible_asset', "amortization_method IN ('straight_line', 'declining_balance', 'sum_of_years')")
    op.create_check_constraint('ck_intangible_asset_status', 'intangible_asset', "status IN ('active', 'fully_amortized', 'impaired')")
    op.create_check_constraint('ck_intangible_asset_cost_nonneg', 'intangible_asset', 'acquisition_cost >= 0')
    op.create_check_constraint('ck_intangible_asset_residual_nonneg', 'intangible_asset', 'residual_value >= 0')

    op.create_table(
        'amortization_schedule',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('asset_id', UUID(as_uuid=True), nullable=False),
        sa.Column('period', sa.Integer, nullable=False),
        sa.Column('fiscal_year', sa.Integer, nullable=False),
        sa.Column('month', sa.Integer, nullable=False),
        sa.Column('amortization_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('accumulated_amortization', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('net_book_value', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('journal_id', UUID(as_uuid=True), nullable=True),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_unique_constraint('uq_amortization_schedule_asset_period', 'amortization_schedule', ['asset_id', 'fiscal_year', 'month'])
    op.create_index('idx_amortization_schedule_asset', 'amortization_schedule', ['asset_id'])
    op.create_index('idx_amortization_schedule_period', 'amortization_schedule', ['fiscal_year', 'month'])
    op.create_index('idx_amortization_schedule_status', 'amortization_schedule', ['status'])
    op.create_index('idx_amortization_schedule_legal_entity', 'amortization_schedule', ['legal_entity_id'])
    op.create_foreign_key('fk_amortization_schedule_asset', 'amortization_schedule', 'intangible_asset', ['asset_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_amortization_schedule_legal_entity', 'amortization_schedule', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_amortization_schedule_journal', 'amortization_schedule', 'journal_header', ['journal_id'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_amortization_schedule_amount_nonneg', 'amortization_schedule', 'amortization_amount >= 0')
    op.create_check_constraint('ck_amortization_schedule_accum_nonneg', 'amortization_schedule', 'accumulated_amortization >= 0')
    op.create_check_constraint('ck_amortization_schedule_nbv_nonneg', 'amortization_schedule', 'net_book_value >= 0')
    op.create_check_constraint('ck_amortization_schedule_period_range', 'amortization_schedule', 'period >= 1 AND period <= 1200')
    op.create_check_constraint('ck_amortization_schedule_month_range', 'amortization_schedule', 'month BETWEEN 1 AND 13')
    op.create_check_constraint('ck_amortization_schedule_status', 'amortization_schedule', "status IN ('pending', 'posted')")

def downgrade() -> None:
    op.drop_constraint('fk_amortization_schedule_asset', 'amortization_schedule', type_='foreignkey')
    op.drop_constraint('fk_amortization_schedule_legal_entity', 'amortization_schedule', type_='foreignkey')
    op.drop_constraint('fk_amortization_schedule_journal', 'amortization_schedule', type_='foreignkey')
    op.drop_constraint('uq_amortization_schedule_asset_period', 'amortization_schedule', type_='unique')
    op.drop_constraint('ck_amortization_schedule_amount_nonneg', 'amortization_schedule', type_='check')
    op.drop_constraint('ck_amortization_schedule_accum_nonneg', 'amortization_schedule', type_='check')
    op.drop_constraint('ck_amortization_schedule_nbv_nonneg', 'amortization_schedule', type_='check')
    op.drop_constraint('ck_amortization_schedule_period_range', 'amortization_schedule', type_='check')
    op.drop_constraint('ck_amortization_schedule_month_range', 'amortization_schedule', type_='check')
    op.drop_constraint('ck_amortization_schedule_status', 'amortization_schedule', type_='check')
    op.drop_index('idx_amortization_schedule_asset', table_name='amortization_schedule')
    op.drop_index('idx_amortization_schedule_period', table_name='amortization_schedule')
    op.drop_index('idx_amortization_schedule_status', table_name='amortization_schedule')
    op.drop_index('idx_amortization_schedule_legal_entity', table_name='amortization_schedule')
    op.drop_table('amortization_schedule')

    op.drop_constraint('fk_intangible_asset_legal_entity', 'intangible_asset', type_='foreignkey')
    op.drop_constraint('uq_intangible_asset_code_legal_entity', 'intangible_asset', type_='unique')
    op.drop_constraint('ck_intangible_asset_amortization_method', 'intangible_asset', type_='check')
    op.drop_constraint('ck_intangible_asset_status', 'intangible_asset', type_='check')
    op.drop_constraint('ck_intangible_asset_cost_nonneg', 'intangible_asset', type_='check')
    op.drop_constraint('ck_intangible_asset_residual_nonneg', 'intangible_asset', type_='check')
    op.drop_index('idx_intangible_asset_code', table_name='intangible_asset')
    op.drop_index('idx_intangible_asset_category', table_name='intangible_asset')
    op.drop_index('idx_intangible_asset_status', table_name='intangible_asset')
    op.drop_index('idx_intangible_asset_legal_entity', table_name='intangible_asset')
    op.drop_index('idx_intangible_asset_acquisition_date', table_name='intangible_asset')
    op.drop_index('idx_intangible_asset_is_active', table_name='intangible_asset')
    op.drop_table('intangible_asset')