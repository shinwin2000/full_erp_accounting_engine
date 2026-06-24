"""create coretax faktur keluaran and masukan tables

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-30 12:00:22.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP

revision: str = '0022abcd'
down_revision = '0021abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'coretax_faktur_keluaran',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('nsfp', sa.String(16), nullable=False),
        sa.Column('faktur_number', sa.String(30), nullable=False, unique=True),
        sa.Column('faktur_date', sa.Date(), nullable=False),
        sa.Column('customer_npwp', sa.String(20), nullable=False),
        sa.Column('customer_name', sa.String(200), nullable=False),
        sa.Column('dpp_total', sa.Numeric(18, 2), nullable=False),
        sa.Column('ppn_total', sa.Numeric(18, 2), nullable=False),
        sa.Column('ppnbm_total', sa.Numeric(18, 2), nullable=True),
        sa.Column('tarif_ppn', sa.Numeric(5, 2), nullable=False, server_default='11.00'),
        sa.Column('status', sa.String(20), nullable=False, server_default='DRAFT'),
        sa.Column('approval_code', sa.String(50), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('submitted_at', TIMESTAMP(timezone=True), nullable=True),
        sa.Column('approved_at', TIMESTAMP(timezone=True), nullable=True),
        sa.Column('voided_at', TIMESTAMP(timezone=True), nullable=True),
        sa.Column('source_document_type', sa.String(50), nullable=False),
        sa.Column('source_document_id', UUID(as_uuid=True), nullable=False),
        sa.Column('original_faktur_id', UUID(as_uuid=True), nullable=True),
        sa.Column('hash_link', sa.String(128), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=False),
        sa.Column('updated_by', UUID(as_uuid=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.create_index('ix_coretax_faktur_keluaran_legal_entity', 'coretax_faktur_keluaran', ['legal_entity_id'])
    op.create_index('ix_coretax_faktur_keluaran_nsfp', 'coretax_faktur_keluaran', ['nsfp'])
    op.create_index('ix_coretax_faktur_keluaran_status', 'coretax_faktur_keluaran', ['status'])
    op.create_index('ix_coretax_faktur_keluaran_source', 'coretax_faktur_keluaran', ['source_document_type', 'source_document_id'])
    op.create_index('ix_coretax_faktur_keluaran_date', 'coretax_faktur_keluaran', ['faktur_date'])

    op.create_table(
        'coretax_faktur_masukan',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('faktur_number', sa.String(30), nullable=False, unique=True),
        sa.Column('faktur_date', sa.Date(), nullable=False),
        sa.Column('supplier_npwp', sa.String(20), nullable=False),
        sa.Column('supplier_name', sa.String(200), nullable=False),
        sa.Column('dpp_total', sa.Numeric(18, 2), nullable=False),
        sa.Column('ppn_total', sa.Numeric(18, 2), nullable=False),
        sa.Column('ppnbm_total', sa.Numeric(18, 2), nullable=True),
        sa.Column('tarif_ppn', sa.Numeric(5, 2), nullable=False, server_default='11.00'),
        sa.Column('status_pengkreditan', sa.String(20), nullable=False, server_default='BELUM_KREDIT'),
        sa.Column('credit_period_month', sa.Integer(), nullable=True),
        sa.Column('credit_period_year', sa.Integer(), nullable=True),
        sa.Column('posted_to_journal_id', UUID(as_uuid=True), nullable=True),
        sa.Column('hash_link', sa.String(128), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=False),
        sa.Column('updated_by', UUID(as_uuid=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.create_index('ix_coretax_faktur_masukan_legal_entity', 'coretax_faktur_masukan', ['legal_entity_id'])
    op.create_index('ix_coretax_faktur_masukan_supplier', 'coretax_faktur_masukan', ['supplier_npwp'])
    op.create_index('ix_coretax_faktur_masukan_date', 'coretax_faktur_masukan', ['faktur_date'])

    op.add_column('tax_transaction', sa.Column('coretax_faktur_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_tax_transaction_coretax_faktur_keluaran', 'tax_transaction', 'coretax_faktur_keluaran', ['coretax_faktur_id'], ['id'])

def downgrade() -> None:
    op.drop_constraint('fk_tax_transaction_coretax_faktur_keluaran', 'tax_transaction', type_='foreignkey')
    op.drop_column('tax_transaction', 'coretax_faktur_id')
    op.drop_table('coretax_faktur_masukan')
    op.drop_table('coretax_faktur_keluaran')