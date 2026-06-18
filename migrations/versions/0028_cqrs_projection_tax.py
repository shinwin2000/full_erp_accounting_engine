"""create projection_ppn_settlement, projection_pph_summary, projection_coretax_dashboard tables

Revision ID: 0028
Revises: 0027
Create Date: 2026-05-30 13:30:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP

revision: str = '0028'
down_revision = '0027'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'projection_ppn_settlement',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('tax_period_month', sa.Integer(), nullable=False),
        sa.Column('tax_period_year', sa.Integer(), nullable=False),
        sa.Column('ppn_output', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('ppn_input', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('ppn_net', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('ppn_paid', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('ppn_due', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('spt_status', sa.String(30), nullable=False, server_default='NOT_FILED'),
        sa.Column('spt_filed_at', TIMESTAMP(timezone=True), nullable=True),
        sa.Column('coretax_submission_id', UUID(as_uuid=True), nullable=True),
        sa.Column('last_updated_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('last_updated_by', UUID(as_uuid=True), nullable=False),
    )
    op.create_index('ix_projection_ppn_settlement_entity_period', 'projection_ppn_settlement', ['legal_entity_id', 'tax_period_year', 'tax_period_month'], unique=True)

    op.create_table(
        'projection_pph_summary',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('tax_period_month', sa.Integer(), nullable=True),
        sa.Column('tax_period_year', sa.Integer(), nullable=False),
        sa.Column('pph_type', sa.String(10), nullable=False),
        sa.Column('amount_due', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('amount_paid', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('amount_credit', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('spt_status', sa.String(30), nullable=False, server_default='NOT_FILED'),
        sa.Column('spt_filed_at', TIMESTAMP(timezone=True), nullable=True),
        sa.Column('coretax_submission_id', UUID(as_uuid=True), nullable=True),
        sa.Column('last_updated_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('last_updated_by', UUID(as_uuid=True), nullable=False),
    )
    op.create_index('ix_projection_pph_summary_entity_period_type', 'projection_pph_summary', ['legal_entity_id', 'tax_period_year', 'tax_period_month', 'pph_type'], unique=True)

    op.create_table(
        'projection_coretax_dashboard',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('total_faktur_keluaran_draft', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_faktur_keluaran_submitted', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_faktur_keluaran_approved', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_faktur_keluaran_rejected', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_faktur_masukan_belum_kredit', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_faktur_masukan_dikreditkan', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_spt_masa_ppn_filed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_spt_masa_pph_filed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_sync_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('last_updated_by', UUID(as_uuid=True), nullable=False),
    )
    op.create_index('ix_projection_coretax_dashboard_entity', 'projection_coretax_dashboard', ['legal_entity_id'], unique=True)

def downgrade() -> None:
    op.drop_table('projection_coretax_dashboard')
    op.drop_table('projection_pph_summary')
    op.drop_table('projection_ppn_settlement')