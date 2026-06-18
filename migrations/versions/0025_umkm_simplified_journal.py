"""create umkm_journal table for simplified accounting

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-30 12:45:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP

revision: str = '0025'
down_revision = '0024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'umkm_journal',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('journal_date', sa.Date(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('debit_account_code', sa.String(20), nullable=False),
        sa.Column('credit_account_code', sa.String(20), nullable=False),
        sa.Column('amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('tax_id', UUID(as_uuid=True), nullable=True),
        sa.Column('attachment_url', sa.String(500), nullable=True),
        sa.Column('status', sa.String(20), server_default='DRAFT'),
        sa.Column('version', sa.Integer(), server_default='1'),
        sa.Column('created_at', TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=False),
    )
    op.create_index('ix_umkm_journal_date', 'umkm_journal', ['journal_date'])

def downgrade() -> None:
    op.drop_table('umkm_journal')