"""create projection_trend_12month, projection_variance_analysis, projection_profitability_segment,
   projection_financial_ratios, projection_kpi_alerter tables

Revision ID: 0029
Revises: 0028
Create Date: 2026-05-30 13:45:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP

revision: str = '0029abcd'
down_revision = '0028abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'projection_trend_12month',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', UUID(as_uuid=True), nullable=False),
        sa.Column('account_code', sa.String(30), nullable=False),
        sa.Column('fiscal_year', sa.Integer(), nullable=False),
        sa.Column('month_1', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('month_2', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('month_3', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('month_4', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('month_5', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('month_6', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('month_7', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('month_8', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('month_9', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('month_10', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('month_11', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('month_12', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('ytd_total', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('last_updated_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_trend_12month_entity_account_year', 'projection_trend_12month', ['legal_entity_id', 'account_id', 'fiscal_year'], unique=True)

    op.create_table(
        'projection_variance_analysis',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', UUID(as_uuid=True), nullable=False),
        sa.Column('account_code', sa.String(30), nullable=False),
        sa.Column('fiscal_year', sa.Integer(), nullable=False),
        sa.Column('period', sa.Integer(), nullable=False),
        sa.Column('actual_amount', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('budget_amount', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('variance_amount', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('variance_percentage', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('variance_type', sa.String(20), nullable=False, server_default='NEUTRAL'),
        sa.Column('last_updated_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('last_updated_by', UUID(as_uuid=True), nullable=False),
    )
    op.create_index('ix_variance_entity_account_year_period', 'projection_variance_analysis', ['legal_entity_id', 'account_id', 'fiscal_year', 'period'], unique=True)

    op.create_table(
        'projection_profitability_segment',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('segment_type', sa.String(30), nullable=False),
        sa.Column('segment_id', UUID(as_uuid=True), nullable=False),
        sa.Column('segment_name', sa.String(200), nullable=False),
        sa.Column('fiscal_year', sa.Integer(), nullable=False),
        sa.Column('period', sa.Integer(), nullable=False),
        sa.Column('revenue', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('direct_cost', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('indirect_cost_allocated', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('gross_profit', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('gross_margin_percentage', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('operating_profit', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('net_profit', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('last_updated_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_profitability_segment_entity_type_period', 'projection_profitability_segment', ['legal_entity_id', 'segment_type', 'segment_id', 'fiscal_year', 'period'], unique=True)

    op.create_table(
        'projection_financial_ratios',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('as_of_date', sa.Date(), nullable=False),
        sa.Column('current_ratio', sa.Numeric(12, 4), nullable=False, server_default='0'),
        sa.Column('quick_ratio', sa.Numeric(12, 4), nullable=False, server_default='0'),
        sa.Column('debt_to_equity', sa.Numeric(12, 4), nullable=False, server_default='0'),
        sa.Column('roa', sa.Numeric(12, 4), nullable=False, server_default='0'),
        sa.Column('roe', sa.Numeric(12, 4), nullable=False, server_default='0'),
        sa.Column('gross_margin', sa.Numeric(12, 4), nullable=False, server_default='0'),
        sa.Column('net_margin', sa.Numeric(12, 4), nullable=False, server_default='0'),
        sa.Column('inventory_turnover', sa.Numeric(12, 4), nullable=False, server_default='0'),
        sa.Column('receivable_turnover', sa.Numeric(12, 4), nullable=False, server_default='0'),
        sa.Column('payable_turnover', sa.Numeric(12, 4), nullable=False, server_default='0'),
        sa.Column('last_updated_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_financial_ratios_entity_date', 'projection_financial_ratios', ['legal_entity_id', 'as_of_date'], unique=True)

    op.create_table(
        'projection_kpi_alerter',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('kpi_name', sa.String(100), nullable=False),
        sa.Column('current_value', sa.Numeric(18, 4), nullable=False),
        sa.Column('threshold_lower', sa.Numeric(18, 4), nullable=True),
        sa.Column('threshold_upper', sa.Numeric(18, 4), nullable=True),
        sa.Column('breach_status', sa.String(20), nullable=False, server_default='NORMAL'),
        sa.Column('breach_detected_at', TIMESTAMP(timezone=True), nullable=True),
        sa.Column('alert_sent_at', TIMESTAMP(timezone=True), nullable=True),
        sa.Column('last_updated_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_kpi_alerter_entity_kpi', 'projection_kpi_alerter', ['legal_entity_id', 'kpi_name'], unique=True)

def downgrade() -> None:
    op.drop_table('projection_kpi_alerter')
    op.drop_table('projection_financial_ratios')
    op.drop_table('projection_profitability_segment')
    op.drop_table('projection_variance_analysis')
    op.drop_table('projection_trend_12month')