"""create tax_transaction and ppn_settlement tables

Revision ID: 0021
Revises: 0020
Create Date: 2025-01-01 00:00:20.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, NUMERIC, JSONB

revision: str = '0021abcd'
down_revision = '0020abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'tax_transaction',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('transaction_number', sa.String(50), nullable=False),
        sa.Column('transaction_date', sa.Date, nullable=False),
        sa.Column('tax_type', sa.String(20), nullable=False),
        sa.Column('tax_period_type', sa.String(10), nullable=False, server_default='monthly'),
        sa.Column('tax_period_year', sa.Integer, nullable=False),
        sa.Column('tax_period_month', sa.Integer, nullable=False),
        sa.Column('taxable_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('tax_rate', NUMERIC(5, 2), nullable=False, server_default='0'),
        sa.Column('tax_amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('is_withholding', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('counterparty_tax_id', sa.String(20), nullable=True),
        sa.Column('counterparty_name', sa.String(200), nullable=True),
        sa.Column('ntpn', sa.String(16), nullable=True),
        sa.Column('payment_date', sa.Date, nullable=True),
        sa.Column('reference_type', sa.String(50), nullable=False),
        sa.Column('reference_id', UUID(as_uuid=True), nullable=True),
        sa.Column('spt_number', sa.String(50), nullable=True),
        sa.Column('filing_date', sa.Date, nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='calculated'),
        sa.Column('metadata', JSONB, nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_tax_transaction_number', 'tax_transaction', ['transaction_number'])
    op.create_index('idx_tax_tx_type_period', 'tax_transaction', ['tax_type', 'tax_period_year', 'tax_period_month'])
    op.create_index('idx_tax_tx_status', 'tax_transaction', ['status'])
    op.create_index('idx_tax_tx_reference', 'tax_transaction', ['reference_type', 'reference_id'])
    op.create_index('idx_tax_tx_legal_entity', 'tax_transaction', ['legal_entity_id'])
    op.create_unique_constraint('uq_tax_transaction_number_legal_entity', 'tax_transaction', ['transaction_number', 'legal_entity_id'])
    op.create_foreign_key('fk_tax_transaction_legal_entity', 'tax_transaction', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_tax_tx_type', 'tax_transaction', "tax_type IN ('ppn', 'pph21', 'pph22', 'pph23', 'pph25', 'pph26', 'pph4_2', 'pph_badan', 'other')")
    op.create_check_constraint('ck_tax_tx_period_type', 'tax_transaction', "tax_period_type IN ('monthly', 'quarterly', 'annual')")
    op.create_check_constraint('ck_tax_tx_taxable_nonneg', 'tax_transaction', 'taxable_amount >= 0')
    op.create_check_constraint('ck_tax_tx_amount_nonneg', 'tax_transaction', 'tax_amount >= 0')
    op.create_check_constraint('ck_tax_tx_status', 'tax_transaction', "status IN ('calculated', 'reported', 'paid', 'adjusted', 'cancelled')")

    op.create_table(
        'ppn_settlement',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('npwp', sa.String(20), nullable=False),
        sa.Column('masa_pajak', sa.Integer, nullable=False),
        sa.Column('tahun_pajak', sa.Integer, nullable=False),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('period_start', sa.Date, nullable=False),
        sa.Column('period_end', sa.Date, nullable=False),
        sa.Column('total_ppn_keluaran', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('total_ppn_masukan', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('kompensasi_dari_sebelumnya', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('ppn_kurang_bayar', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('ppn_lebih_bayar', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('status_pembayaran', sa.String(20), nullable=False, server_default='unpaid'),
        sa.Column('ntpn', sa.String(16), nullable=True),
        sa.Column('payment_date', sa.Date, nullable=True),
        sa.Column('settlement_status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('spt_number', sa.String(50), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_ppn_settlement_npwp', 'ppn_settlement', ['npwp'])
    op.create_index('idx_ppn_settlement_period', 'ppn_settlement', ['tahun_pajak', 'masa_pajak'])
    op.create_index('idx_ppn_settlement_legal_entity', 'ppn_settlement', ['legal_entity_id'])
    op.create_index('idx_ppn_settlement_status', 'ppn_settlement', ['settlement_status'])
    op.create_unique_constraint('uq_ppn_settlement_npwp_period', 'ppn_settlement', ['npwp', 'tahun_pajak', 'masa_pajak', 'legal_entity_id'])
    op.create_foreign_key('fk_ppn_settlement_legal_entity', 'ppn_settlement', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_ppn_settlement_created_by', 'ppn_settlement', 'iam_user', ['created_by'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_ppn_settlement_masa', 'ppn_settlement', 'masa_pajak BETWEEN 1 AND 13')
    op.create_check_constraint('ck_ppn_settlement_status_payment', 'ppn_settlement', "status_pembayaran IN ('unpaid', 'paid')")
    op.create_check_constraint('ck_ppn_settlement_status', 'ppn_settlement', "settlement_status IN ('draft', 'final', 'submitted')")
    op.create_check_constraint('ck_ppn_settlement_npwp_len', 'ppn_settlement', "LENGTH(npwp) = 15")

    op.create_table(
        'pph_withholding_summary',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('npwp_pemotong', sa.String(20), nullable=False),
        sa.Column('pph_type', sa.String(10), nullable=False),
        sa.Column('masa_pajak', sa.Integer, nullable=False),
        sa.Column('tahun_pajak', sa.Integer, nullable=False),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('period_start', sa.Date, nullable=False),
        sa.Column('period_end', sa.Date, nullable=False),
        sa.Column('total_dpp', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('total_pph_dipotong', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('kompensasi', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('kurang_bayar', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('lebih_bayar', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('payment_status', sa.String(20), nullable=False, server_default='unpaid'),
        sa.Column('ntpn', sa.String(16), nullable=True),
        sa.Column('payment_date', sa.Date, nullable=True),
        sa.Column('spt_number', sa.String(50), nullable=True),
        sa.Column('spt_status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('bupot_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_pph_summary_npwp', 'pph_withholding_summary', ['npwp_pemotong'])
    op.create_index('idx_pph_summary_period', 'pph_withholding_summary', ['tahun_pajak', 'masa_pajak', 'pph_type'])
    op.create_index('idx_pph_summary_legal_entity', 'pph_withholding_summary', ['legal_entity_id'])
    op.create_unique_constraint('uq_pph_summary_npwp_period_type', 'pph_withholding_summary', ['npwp_pemotong', 'tahun_pajak', 'masa_pajak', 'pph_type', 'legal_entity_id'])
    op.create_foreign_key('fk_pph_summary_legal_entity', 'pph_withholding_summary', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_pph_summary_created_by', 'pph_withholding_summary', 'iam_user', ['created_by'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_pph_summary_type', 'pph_withholding_summary', "pph_type IN ('21', '22', '23', '26', '4_2', '25', '29')")
    op.create_check_constraint('ck_pph_summary_payment', 'pph_withholding_summary', "payment_status IN ('unpaid', 'paid', 'overpaid')")
    op.create_check_constraint('ck_pph_summary_spt_status', 'pph_withholding_summary', "spt_status IN ('draft', 'submitted', 'approved')")

def downgrade() -> None:
    op.drop_constraint('fk_pph_summary_legal_entity', 'pph_withholding_summary', type_='foreignkey')
    op.drop_constraint('fk_pph_summary_created_by', 'pph_withholding_summary', type_='foreignkey')
    op.drop_constraint('uq_pph_summary_npwp_period_type', 'pph_withholding_summary', type_='unique')
    op.drop_constraint('ck_pph_summary_type', 'pph_withholding_summary', type_='check')
    op.drop_constraint('ck_pph_summary_payment', 'pph_withholding_summary', type_='check')
    op.drop_constraint('ck_pph_summary_spt_status', 'pph_withholding_summary', type_='check')
    op.drop_index('idx_pph_summary_npwp', table_name='pph_withholding_summary')
    op.drop_index('idx_pph_summary_period', table_name='pph_withholding_summary')
    op.drop_index('idx_pph_summary_legal_entity', table_name='pph_withholding_summary')
    op.drop_table('pph_withholding_summary')

    op.drop_constraint('fk_ppn_settlement_legal_entity', 'ppn_settlement', type_='foreignkey')
    op.drop_constraint('fk_ppn_settlement_created_by', 'ppn_settlement', type_='foreignkey')
    op.drop_constraint('uq_ppn_settlement_npwp_period', 'ppn_settlement', type_='unique')
    op.drop_constraint('ck_ppn_settlement_masa', 'ppn_settlement', type_='check')
    op.drop_constraint('ck_ppn_settlement_status_payment', 'ppn_settlement', type_='check')
    op.drop_constraint('ck_ppn_settlement_status', 'ppn_settlement', type_='check')
    op.drop_constraint('ck_ppn_settlement_npwp_len', 'ppn_settlement', type_='check')
    op.drop_index('idx_ppn_settlement_npwp', table_name='ppn_settlement')
    op.drop_index('idx_ppn_settlement_period', table_name='ppn_settlement')
    op.drop_index('idx_ppn_settlement_legal_entity', table_name='ppn_settlement')
    op.drop_index('idx_ppn_settlement_status', table_name='ppn_settlement')
    op.drop_table('ppn_settlement')

    op.drop_constraint('fk_tax_transaction_legal_entity', 'tax_transaction', type_='foreignkey')
    op.drop_constraint('uq_tax_transaction_number_legal_entity', 'tax_transaction', type_='unique')
    op.drop_constraint('ck_tax_tx_type', 'tax_transaction', type_='check')
    op.drop_constraint('ck_tax_tx_period_type', 'tax_transaction', type_='check')
    op.drop_constraint('ck_tax_tx_taxable_nonneg', 'tax_transaction', type_='check')
    op.drop_constraint('ck_tax_tx_amount_nonneg', 'tax_transaction', type_='check')
    op.drop_constraint('ck_tax_tx_status', 'tax_transaction', type_='check')
    op.drop_index('idx_tax_transaction_number', table_name='tax_transaction')
    op.drop_index('idx_tax_tx_type_period', table_name='tax_transaction')
    op.drop_index('idx_tax_tx_status', table_name='tax_transaction')
    op.drop_index('idx_tax_tx_reference', table_name='tax_transaction')
    op.drop_index('idx_tax_tx_legal_entity', table_name='tax_transaction')
    op.drop_table('tax_transaction')