"""create projection_gl_ledger and projection_trial_balance tables

Revision ID: 0026
Revises: 0025
Create Date: 2026-05-30 13:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP

revision: str = '0026'
down_revision = '0025'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'projection_gl_ledger',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', UUID(as_uuid=True), nullable=False),
        sa.Column('account_code', sa.String(30), nullable=False),
        sa.Column('fiscal_year', sa.Integer(), nullable=False),
        sa.Column('period', sa.Integer(), nullable=False),
        sa.Column('opening_balance', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('debit_movement', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('credit_movement', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('closing_balance', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('last_updated_at', TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.Column('last_updated_by', UUID(as_uuid=True), nullable=False),
    )
    op.create_index('ix_projection_gl_ledger_entity_period', 'projection_gl_ledger', ['legal_entity_id', 'fiscal_year', 'period', 'account_id'], unique=True)

    op.create_table(
        'projection_trial_balance',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('as_of_date', sa.Date(), nullable=False),
        sa.Column('account_code', sa.String(30), nullable=False),
        sa.Column('debit_balance', sa.Numeric(18, 2), nullable=False),
        sa.Column('credit_balance', sa.Numeric(18, 2), nullable=False),
        sa.Column('is_adjusted', sa.Boolean(), default=False),
    )

def downgrade() -> None:
    op.drop_table('projection_trial_balance')
    op.drop_table('projection_gl_ledger')