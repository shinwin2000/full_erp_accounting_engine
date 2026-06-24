"""create fixed_asset and depreciation_schedule tables

Revision ID: 0015
Revises: 0014
Create Date: 2025-01-01 00:00:14.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, NUMERIC

revision: str = '0015abcd'
down_revision = '0014abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'fixed_asset',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('asset_code', sa.String(30), nullable=False),
        sa.Column('asset_name', sa.String(200), nullable=False),
        sa.Column('asset_category', sa.String(50), nullable=False),
        sa.Column('acquisition_date', sa.Date, nullable=False),
        sa.Column('acquisition_cost', NUMERIC(20, 2), nullable=False),
        sa.Column('residual_value', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('useful_life_years', sa.Integer, nullable=False),
        sa.Column('depreciation_method', sa.String(25), nullable=False, server_default='straight_line'),
        sa.Column('depreciation_rate', NUMERIC(5, 2), nullable=True),
        sa.Column('accumulated_depreciation', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('last_depreciation_date', sa.Date, nullable=True),
        sa.Column('current_period_depreciation', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('location', sa.String(200), nullable=True),
        sa.Column('responsible_party', sa.String(100), nullable=True),
        sa.Column('supplier_id', UUID(as_uuid=True), nullable=True),
        sa.Column('purchase_order_id', UUID(as_uuid=True), nullable=True),
        sa.Column('invoice_id', UUID(as_uuid=True), nullable=True),
        sa.Column('serial_number', sa.String(100), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('revaluation_frequency', sa.String(20), nullable=False, server_default='never'),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_fixed_asset_code', 'fixed_asset', ['asset_code'])
    op.create_index('idx_fixed_asset_category', 'fixed_asset', ['asset_category'])
    op.create_index('idx_fixed_asset_status', 'fixed_asset', ['status'])
    op.create_index('idx_fixed_asset_legal_entity', 'fixed_asset', ['legal_entity_id'])
    op.create_index('idx_fixed_asset_acquisition_date', 'fixed_asset', ['acquisition_date'])
    op.create_index('idx_fixed_asset_supplier', 'fixed_asset', ['supplier_id'])
    op.create_index('idx_fixed_asset_is_active', 'fixed_asset', ['is_active'])
    op.create_unique_constraint('uq_fixed_asset_code_legal_entity', 'fixed_asset', ['asset_code', 'legal_entity_id'])
    op.create_foreign_key('fk_fixed_asset_legal_entity', 'fixed_asset', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_fixed_asset_supplier', 'fixed_asset', 'supplier', ['supplier_id'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_fixed_asset_depreciation_method', 'fixed_asset', "depreciation_method IN ('straight_line', 'declining_balance', 'sum_of_years', 'units_of_production')")
    op.create_check_constraint('ck_fixed_asset_status', 'fixed_asset', "status IN ('active', 'fully_depreciated', 'disposed', 'impaired')")
    op.create_check_constraint('ck_fixed_asset_cost_nonneg', 'fixed_asset', 'acquisition_cost >= 0')
    op.create_check_constraint('ck_fixed_asset_residual_nonneg', 'fixed_asset', 'residual_value >= 0')
    op.create_check_constraint('ck_fixed_asset_residual_not_exceed', 'fixed_asset', 'residual_value <= acquisition_cost')
    op.create_check_constraint('ck_fixed_asset_life_positive', 'fixed_asset', 'useful_life_years > 0')
    op.create_check_constraint('ck_fixed_asset_accum_dep_nonneg', 'fixed_asset', 'accumulated_depreciation >= 0')

    op.create_table(
        'depreciation_schedule',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('asset_id', UUID(as_uuid=True), nullable=False),
        sa.Column('period', sa.Integer, nullable=False),
        sa.Column('fiscal_year', sa.Integer, nullable=False),
        sa.Column('month', sa.Integer, nullable=False),
        sa.Column('depreciation_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('accumulated_depreciation', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('net_book_value', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('journal_id', UUID(as_uuid=True), nullable=True),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_unique_constraint('uq_depreciation_schedule_asset_period', 'depreciation_schedule', ['asset_id', 'fiscal_year', 'month'])
    op.create_index('idx_depreciation_schedule_asset', 'depreciation_schedule', ['asset_id'])
    op.create_index('idx_depreciation_schedule_period', 'depreciation_schedule', ['fiscal_year', 'month'])
    op.create_index('idx_depreciation_schedule_status', 'depreciation_schedule', ['status'])
    op.create_index('idx_depreciation_schedule_legal_entity', 'depreciation_schedule', ['legal_entity_id'])
    op.create_foreign_key('fk_depreciation_schedule_asset', 'depreciation_schedule', 'fixed_asset', ['asset_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_depreciation_schedule_legal_entity', 'depreciation_schedule', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_depreciation_schedule_journal', 'depreciation_schedule', 'journal_header', ['journal_id'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_depreciation_schedule_amount_nonneg', 'depreciation_schedule', 'depreciation_amount >= 0')
    op.create_check_constraint('ck_depreciation_schedule_accum_nonneg', 'depreciation_schedule', 'accumulated_depreciation >= 0')
    op.create_check_constraint('ck_depreciation_schedule_nbv_nonneg', 'depreciation_schedule', 'net_book_value >= 0')
    op.create_check_constraint('ck_depreciation_schedule_period_range', 'depreciation_schedule', 'period >= 1 AND period <= 1200')
    op.create_check_constraint('ck_depreciation_schedule_month_range', 'depreciation_schedule', 'month BETWEEN 1 AND 13')
    op.create_check_constraint('ck_depreciation_schedule_status', 'depreciation_schedule', "status IN ('pending', 'posted', 'skipped')")

def downgrade() -> None:
    op.drop_constraint('fk_depreciation_schedule_asset', 'depreciation_schedule', type_='foreignkey')
    op.drop_constraint('fk_depreciation_schedule_legal_entity', 'depreciation_schedule', type_='foreignkey')
    op.drop_constraint('fk_depreciation_schedule_journal', 'depreciation_schedule', type_='foreignkey')
    op.drop_constraint('uq_depreciation_schedule_asset_period', 'depreciation_schedule', type_='unique')
    op.drop_constraint('ck_depreciation_schedule_amount_nonneg', 'depreciation_schedule', type_='check')
    op.drop_constraint('ck_depreciation_schedule_accum_nonneg', 'depreciation_schedule', type_='check')
    op.drop_constraint('ck_depreciation_schedule_nbv_nonneg', 'depreciation_schedule', type_='check')
    op.drop_constraint('ck_depreciation_schedule_period_range', 'depreciation_schedule', type_='check')
    op.drop_constraint('ck_depreciation_schedule_month_range', 'depreciation_schedule', type_='check')
    op.drop_constraint('ck_depreciation_schedule_status', 'depreciation_schedule', type_='check')
    op.drop_index('idx_depreciation_schedule_asset', table_name='depreciation_schedule')
    op.drop_index('idx_depreciation_schedule_period', table_name='depreciation_schedule')
    op.drop_index('idx_depreciation_schedule_status', table_name='depreciation_schedule')
    op.drop_index('idx_depreciation_schedule_legal_entity', table_name='depreciation_schedule')
    op.drop_table('depreciation_schedule')

    op.drop_constraint('fk_fixed_asset_legal_entity', 'fixed_asset', type_='foreignkey')
    op.drop_constraint('fk_fixed_asset_supplier', 'fixed_asset', type_='foreignkey')
    op.drop_constraint('uq_fixed_asset_code_legal_entity', 'fixed_asset', type_='unique')
    op.drop_constraint('ck_fixed_asset_depreciation_method', 'fixed_asset', type_='check')
    op.drop_constraint('ck_fixed_asset_status', 'fixed_asset', type_='check')
    op.drop_constraint('ck_fixed_asset_cost_nonneg', 'fixed_asset', type_='check')
    op.drop_constraint('ck_fixed_asset_residual_nonneg', 'fixed_asset', type_='check')
    op.drop_constraint('ck_fixed_asset_residual_not_exceed', 'fixed_asset', type_='check')
    op.drop_constraint('ck_fixed_asset_life_positive', 'fixed_asset', type_='check')
    op.drop_constraint('ck_fixed_asset_accum_dep_nonneg', 'fixed_asset', type_='check')
    op.drop_index('idx_fixed_asset_code', table_name='fixed_asset')
    op.drop_index('idx_fixed_asset_category', table_name='fixed_asset')
    op.drop_index('idx_fixed_asset_status', table_name='fixed_asset')
    op.drop_index('idx_fixed_asset_legal_entity', table_name='fixed_asset')
    op.drop_index('idx_fixed_asset_acquisition_date', table_name='fixed_asset')
    op.drop_index('idx_fixed_asset_supplier', table_name='fixed_asset')
    op.drop_index('idx_fixed_asset_is_active', table_name='fixed_asset')
    op.drop_table('fixed_asset')