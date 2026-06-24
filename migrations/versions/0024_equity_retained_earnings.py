"""create capital_contribution, retained_earnings_history, dividend_declaration tables

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-30 12:30:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP

revision: str = '0024abcd'
down_revision = '0023abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'capital_contribution',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('contribution_date', sa.Date(), nullable=False),
        sa.Column('amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('currency_code', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('contribution_type', sa.String(30), nullable=False),
        sa.Column('shareholder_name', sa.String(200), nullable=False),
        sa.Column('journal_id', UUID(as_uuid=True), nullable=False),
        sa.Column('version', sa.Integer(), server_default='1'),
        sa.Column('created_at', TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=False),
    )
    op.create_table(
        'retained_earnings_history',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('fiscal_year', sa.Integer(), nullable=False),
        sa.Column('opening_balance', sa.Numeric(18, 2), nullable=False),
        sa.Column('net_income', sa.Numeric(18, 2), nullable=False),
        sa.Column('dividends_declared', sa.Numeric(18, 2), nullable=False),
        sa.Column('closing_balance', sa.Numeric(18, 2), nullable=False),
        sa.Column('is_closed', sa.Boolean(), default=False),
        sa.Column('closed_at', TIMESTAMP(timezone=True), nullable=True),
        sa.Column('version', sa.Integer(), server_default='1'),
    )
    op.create_table(
        'dividend_declaration',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('declaration_date', sa.Date(), nullable=False),
        sa.Column('payment_date', sa.Date(), nullable=True),
        sa.Column('total_dividend', sa.Numeric(18, 2), nullable=False),
        sa.Column('status', sa.String(20), server_default='PROPOSED'),
        sa.Column('journal_id', UUID(as_uuid=True), nullable=True),
    )

def downgrade() -> None:
    op.drop_table('dividend_declaration')
    op.drop_table('retained_earnings_history')
    op.drop_table('capital_contribution')