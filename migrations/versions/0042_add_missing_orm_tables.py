"""Add missing ORM tables

Revision ID: 0042
Revises: 0041
Create Date: 2026-06-20 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = '0042abcd'
down_revision = '0041abcd'
branch_labels = None
depends_on = None



def _table_exists_mig(table_name: str) -> bool:
    """Check if table exists - idempotency guard."""
    try:
        bind = op.get_bind()
        result = bind.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=:t"
        ), {"t": table_name})
        return result.fetchone() is not None
    except Exception:
        return False


def upgrade() -> None:
    # ========================================================================
    # 1. CORE SYSTEM TABLES
    # ========================================================================

    # audit_event
    if not _table_exists_mig('audit_event'):
        op.create_table('audit_event',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('event_id', sa.String(100), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('aggregate_id', UUID(as_uuid=True), nullable=True),
        sa.Column('aggregate_type', sa.String(100), nullable=True),
        sa.Column('user_id', UUID(as_uuid=True), nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=True),
        sa.Column('data', JSONB, nullable=True),
        sa.Column('previous_hash', sa.String(64), nullable=True),
        sa.Column('hash', sa.String(64), nullable=False),
        sa.Column('timestamp', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('version', sa.Integer(), server_default='1'),
    )

    # event_store
    if not _table_exists_mig('event_store'):
        op.create_table('event_store',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('stream_name', sa.String(255), nullable=False),
        sa.Column('stream_id', UUID(as_uuid=True), nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('event_data', JSONB, nullable=False),
        sa.Column('metadata', JSONB, nullable=True),
        sa.Column('position', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('version', sa.Integer(), server_default='1'),
    )

    # hash_chain
    if not _table_exists_mig('hash_chain'):
        op.create_table('hash_chain',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('chain_name', sa.String(100), nullable=False),
        sa.Column('entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('previous_hash', sa.String(64), nullable=True),
        sa.Column('current_hash', sa.String(64), nullable=False),
        sa.Column('data_hash', sa.String(64), nullable=False),
        sa.Column('timestamp', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('version', sa.Integer(), server_default='1'),
    )

    # snapshot_store
    if not _table_exists_mig('snapshot_store'):
        op.create_table('snapshot_store',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('aggregate_id', UUID(as_uuid=True), nullable=False),
        sa.Column('aggregate_type', sa.String(100), nullable=False),
        sa.Column('snapshot_data', JSONB, nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    # outbox
    if not _table_exists_mig('outbox'):
        op.create_table('outbox',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('aggregate_id', UUID(as_uuid=True), nullable=True),
        sa.Column('aggregate_type', sa.String(100), nullable=True),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('payload', JSONB, nullable=False),
        sa.Column('metadata', JSONB, nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),
        sa.Column('attempts', sa.Integer(), server_default='0'),
        sa.Column('last_attempt', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('error', sa.String(500), nullable=True),
    )

    # outbox_checkpoint
    if not _table_exists_mig('outbox_checkpoint'):
        op.create_table('outbox_checkpoint',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('consumer_group', sa.String(100), nullable=False),
        sa.Column('last_processed_id', UUID(as_uuid=True), nullable=True),
        sa.Column('last_processed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    # dead_letter_events
    if not _table_exists_mig('dead_letter_events'):
        op.create_table('dead_letter_events',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('topic', sa.String(100), nullable=False),
        sa.Column('key', sa.String(255), nullable=True),
        sa.Column('value', JSONB, nullable=False),
        sa.Column('headers', JSONB, nullable=True),
        sa.Column('error', sa.String(500), nullable=False),
        sa.Column('retry_count', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
    )

    # ========================================================================
    # 2. BUDGET TABLES
    # ========================================================================

    # budget
    if not _table_exists_mig('budget'):
        op.create_table('budget',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('budget_code', sa.String(50), nullable=False),
        sa.Column('budget_name', sa.String(200), nullable=False),
        sa.Column('budget_type', sa.String(50), nullable=False),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('fiscal_year', sa.Integer(), nullable=False),
        sa.Column('period', sa.String(20), nullable=False),
        sa.Column('version', sa.String(20), nullable=False, server_default='1.0'),
        sa.Column('status', sa.String(30), nullable=False, server_default='draft'),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('total_amount', sa.Numeric(19,4), nullable=False),
        sa.Column('actual_amount_ytd', sa.Numeric(19,4), server_default='0'),
        sa.Column('variance_amount', sa.Numeric(19,4), server_default='0'),
        sa.Column('variance_percent', sa.Numeric(10,2), server_default='0'),
        sa.Column('consumption_percent', sa.Numeric(10,2), server_default='0'),
        sa.Column('is_locked', sa.Boolean(), server_default='false'),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('tags', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('approved_by', UUID(as_uuid=True), nullable=True),
    )

    # budget_actual
    if not _table_exists_mig('budget_actual'):
        op.create_table('budget_actual',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('budget_id', UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', UUID(as_uuid=True), nullable=False),
        sa.Column('fiscal_year', sa.Integer(), nullable=False),
        sa.Column('period', sa.Integer(), nullable=False),
        sa.Column('budget_amount', sa.Numeric(19,4), nullable=False),
        sa.Column('actual_amount', sa.Numeric(19,4), nullable=False),
        sa.Column('variance_amount', sa.Numeric(19,4), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    # ========================================================================
    # 3. CONSOLIDATION TABLES
    # ========================================================================

    # consolidation_group
    if not _table_exists_mig('consolidation_group'):
        op.create_table('consolidation_group',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('group_code', sa.String(50), nullable=False),
        sa.Column('group_name', sa.String(200), nullable=False),
        sa.Column('parent_legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('status', sa.String(30), nullable=False, server_default='active'),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # consolidation_group_member
    if not _table_exists_mig('consolidation_group_member'):
        op.create_table('consolidation_group_member',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('group_id', UUID(as_uuid=True), nullable=False),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('ownership_percentage', sa.Numeric(5,2), nullable=False),
        sa.Column('from_date', sa.Date(), nullable=False),
        sa.Column('to_date', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    # ========================================================================
    # 4. CORETAX TABLES
    # ========================================================================

    # coretax_faktur
    if not _table_exists_mig('coretax_faktur'):
        op.create_table('coretax_faktur',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('faktur_number', sa.String(30), nullable=False),
        sa.Column('faktur_code', sa.String(3), nullable=False),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('customer_id', UUID(as_uuid=True), nullable=True),
        sa.Column('customer_npwp', sa.String(15), nullable=True),
        sa.Column('customer_name', sa.String(200), nullable=False),
        sa.Column('transaction_date', sa.Date(), nullable=False),
        sa.Column('dpp_amount', sa.Numeric(19,4), nullable=False),
        sa.Column('ppn_amount', sa.Numeric(19,4), nullable=False),
        sa.Column('ppn_rate', sa.Numeric(5,2), nullable=False),
        sa.Column('masa_pajak', sa.String(7), nullable=False),
        sa.Column('tahun_pajak', sa.String(4), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='draft'),
        sa.Column('nsfp_used', sa.String(20), nullable=True),
        sa.Column('submission_date', sa.DateTime(), nullable=True),
        sa.Column('response_data', JSONB, nullable=True),
        sa.Column('error_message', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # coretax_faktur_line
    if not _table_exists_mig('coretax_faktur_line'):
        op.create_table('coretax_faktur_line',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('faktur_id', UUID(as_uuid=True), nullable=False),
        sa.Column('item_description', sa.String(500), nullable=False),
        sa.Column('quantity', sa.Numeric(19,4), nullable=False),
        sa.Column('unit_price', sa.Numeric(19,4), nullable=False),
        sa.Column('amount', sa.Numeric(19,4), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    # coretax_bupot
    if not _table_exists_mig('coretax_bupot'):
        op.create_table('coretax_bupot',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('bupot_number', sa.String(30), nullable=False),
        sa.Column('bupot_type', sa.String(10), nullable=False),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('vendor_id', UUID(as_uuid=True), nullable=True),
        sa.Column('vendor_npwp', sa.String(15), nullable=True),
        sa.Column('vendor_name', sa.String(200), nullable=False),
        sa.Column('transaction_date', sa.Date(), nullable=False),
        sa.Column('gross_amount', sa.Numeric(19,4), nullable=False),
        sa.Column('tax_rate', sa.Numeric(5,2), nullable=False),
        sa.Column('tax_amount', sa.Numeric(19,4), nullable=False),
        sa.Column('masa_pajak', sa.String(7), nullable=False),
        sa.Column('tahun_pajak', sa.String(4), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='draft'),
        sa.Column('submission_date', sa.DateTime(), nullable=True),
        sa.Column('response_data', JSONB, nullable=True),
        sa.Column('error_message', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # coretax_spt
    if not _table_exists_mig('coretax_spt'):
        op.create_table('coretax_spt',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('spt_number', sa.String(30), nullable=False),
        sa.Column('spt_type', sa.String(20), nullable=False),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('masa_pajak', sa.String(7), nullable=False),
        sa.Column('tahun_pajak', sa.String(4), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='draft'),
        sa.Column('total_ppn', sa.Numeric(19,4), nullable=True),
        sa.Column('total_pph', sa.Numeric(19,4), nullable=True),
        sa.Column('submission_date', sa.DateTime(), nullable=True),
        sa.Column('response_data', JSONB, nullable=True),
        sa.Column('error_message', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # coretax_ntpn
    if not _table_exists_mig('coretax_ntpn'):
        op.create_table('coretax_ntpn',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('ntpn', sa.String(16), nullable=False),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('payment_date', sa.Date(), nullable=False),
        sa.Column('payment_amount', sa.Numeric(19,4), nullable=False),
        sa.Column('tax_type', sa.String(20), nullable=False),
        sa.Column('masa_pajak', sa.String(7), nullable=False),
        sa.Column('tahun_pajak', sa.String(4), nullable=False),
        sa.Column('billing_code', sa.String(16), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('validation_date', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    # coretax_nsfp
    if not _table_exists_mig('coretax_nsfp'):
        op.create_table('coretax_nsfp',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('tahun', sa.Integer(), nullable=False),
        sa.Column('bulan', sa.Integer(), nullable=False),
        sa.Column('nomor_awal', sa.Integer(), nullable=False),
        sa.Column('nomor_akhir', sa.Integer(), nullable=False),
        sa.Column('nomor_terpakai', sa.Integer(), server_default='0'),
        sa.Column('status', sa.String(30), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # coretax_emeterai
    if not _table_exists_mig('coretax_emeterai'):
        op.create_table('coretax_emeterai',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('meterai_number', sa.String(30), nullable=False),
        sa.Column('meterai_type', sa.String(20), nullable=False),
        sa.Column('value', sa.Numeric(19,4), nullable=False),
        sa.Column('purchase_date', sa.Date(), nullable=False),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='available'),
        sa.Column('used_date', sa.DateTime(), nullable=True),
        sa.Column('used_on_document', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # coretax_submission_log
    if not _table_exists_mig('coretax_submission_log'):
        op.create_table('coretax_submission_log',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('submission_type', sa.String(50), nullable=False),
        sa.Column('submission_id', UUID(as_uuid=True), nullable=False),
        sa.Column('request_data', JSONB, nullable=False),
        sa.Column('response_data', JSONB, nullable=True),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('error_code', sa.String(50), nullable=True),
        sa.Column('error_message', sa.String(500), nullable=True),
        sa.Column('attempt', sa.Integer(), server_default='1'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    # ========================================================================
    # 5. FIXED ASSET & INTANGIBLE TABLES
    # ========================================================================

    # fixed_asset_schedule
    if not _table_exists_mig('fixed_asset_schedule'):
        op.create_table('fixed_asset_schedule',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('asset_id', UUID(as_uuid=True), nullable=False),
        sa.Column('period', sa.Integer(), nullable=False),
        sa.Column('fiscal_year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('period_name', sa.String(20), nullable=False),
        sa.Column('depreciation_amount', sa.Numeric(19,4), nullable=False),
        sa.Column('accumulated_depreciation', sa.Numeric(19,4), nullable=False),
        sa.Column('net_book_value', sa.Numeric(19,4), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('journal_id', UUID(as_uuid=True), nullable=True),
        sa.Column('posted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    # impairment_test
    if not _table_exists_mig('impairment_test'):
        op.create_table('impairment_test',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('asset_id', UUID(as_uuid=True), nullable=False),
        sa.Column('asset_type', sa.String(20), nullable=False),
        sa.Column('test_date', sa.Date(), nullable=False),
        sa.Column('carrying_amount', sa.Numeric(19,4), nullable=False),
        sa.Column('recoverable_amount', sa.Numeric(19,4), nullable=False),
        sa.Column('impairment_loss', sa.Numeric(19,4), nullable=False),
        sa.Column('impairment_percentage', sa.Numeric(10,2), nullable=False),
        sa.Column('reason', sa.String(500), nullable=True),
        sa.Column('valuation_method', sa.String(100), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('journal_id', UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # revaluation
    if not _table_exists_mig('revaluation'):
        op.create_table('revaluation',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('asset_id', UUID(as_uuid=True), nullable=False),
        sa.Column('asset_type', sa.String(20), nullable=False),
        sa.Column('revaluation_date', sa.Date(), nullable=False),
        sa.Column('old_acquisition_cost', sa.Numeric(19,4), nullable=False),
        sa.Column('new_acquisition_cost', sa.Numeric(19,4), nullable=False),
        sa.Column('old_accumulated_amortization', sa.Numeric(19,4), nullable=False),
        sa.Column('new_accumulated_amortization', sa.Numeric(19,4), nullable=False),
        sa.Column('old_nbv', sa.Numeric(19,4), nullable=False),
        sa.Column('new_nbv', sa.Numeric(19,4), nullable=False),
        sa.Column('surplus_deficit', sa.Numeric(19,4), nullable=False),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('appraiser_name', sa.String(200), nullable=True),
        sa.Column('appraisal_report_number', sa.String(50), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('journal_id', UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # disposal
    if not _table_exists_mig('disposal'):
        op.create_table('disposal',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('asset_id', UUID(as_uuid=True), nullable=False),
        sa.Column('asset_type', sa.String(20), nullable=False),
        sa.Column('disposal_date', sa.Date(), nullable=False),
        sa.Column('disposal_type', sa.String(20), nullable=False),
        sa.Column('disposal_proceeds', sa.Numeric(19,4), server_default='0'),
        sa.Column('disposal_cost', sa.Numeric(19,4), server_default='0'),
        sa.Column('net_proceeds', sa.Numeric(19,4), nullable=True),
        sa.Column('nbv_at_disposal', sa.Numeric(19,4), nullable=False),
        sa.Column('gain_loss', sa.Numeric(19,4), nullable=True),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('buyer_name', sa.String(200), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('journal_id', UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # intangible_revaluation
    if not _table_exists_mig('intangible_revaluation'):
        op.create_table('intangible_revaluation',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('asset_id', UUID(as_uuid=True), nullable=False),
        sa.Column('revaluation_date', sa.Date(), nullable=False),
        sa.Column('old_acquisition_cost', sa.Numeric(19,4), nullable=False),
        sa.Column('new_acquisition_cost', sa.Numeric(19,4), nullable=False),
        sa.Column('old_accumulated_amortization', sa.Numeric(19,4), nullable=False),
        sa.Column('new_accumulated_amortization', sa.Numeric(19,4), nullable=False),
        sa.Column('old_nbv', sa.Numeric(19,4), nullable=False),
        sa.Column('new_nbv', sa.Numeric(19,4), nullable=False),
        sa.Column('surplus_deficit', sa.Numeric(19,4), nullable=False),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('journal_id', UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # ========================================================================
    # 6. GOODWILL TABLES
    # ========================================================================

    # goodwill
    if not _table_exists_mig('goodwill'):
        op.create_table('goodwill',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('goodwill_code', sa.String(50), nullable=False),
        sa.Column('goodwill_name', sa.String(200), nullable=False),
        sa.Column('acquisition_date', sa.Date(), nullable=False),
        sa.Column('acquisition_cost', sa.Numeric(19,4), nullable=False),
        sa.Column('useful_life_years', sa.Integer(), nullable=False),
        sa.Column('amortization_method', sa.String(30), nullable=False, server_default='straight_line'),
        sa.Column('accumulated_amortization', sa.Numeric(19,4), server_default='0'),
        sa.Column('accumulated_impairment', sa.Numeric(19,4), server_default='0'),
        sa.Column('net_book_value', sa.Numeric(19,4), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='active'),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # goodwill_impairment
    if not _table_exists_mig('goodwill_impairment'):
        op.create_table('goodwill_impairment',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('goodwill_id', UUID(as_uuid=True), nullable=False),
        sa.Column('impairment_date', sa.Date(), nullable=False),
        sa.Column('carrying_amount', sa.Numeric(19,4), nullable=False),
        sa.Column('recoverable_amount', sa.Numeric(19,4), nullable=False),
        sa.Column('impairment_loss', sa.Numeric(19,4), nullable=False),
        sa.Column('reason', sa.String(500), nullable=True),
        sa.Column('valuation_method', sa.String(100), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('journal_id', UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # ========================================================================
    # 7. HEDGE TABLES
    # ========================================================================

    # hedge_instrument
    if not _table_exists_mig('hedge_instrument'):
        op.create_table('hedge_instrument',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('instrument_code', sa.String(50), nullable=False),
        sa.Column('instrument_name', sa.String(200), nullable=False),
        sa.Column('instrument_type', sa.String(50), nullable=False),
        sa.Column('hedge_relationship_id', UUID(as_uuid=True), nullable=False),
        sa.Column('nominal_amount', sa.Numeric(19,4), nullable=False),
        sa.Column('fair_value', sa.Numeric(19,4), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('maturity_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='active'),
        sa.Column('effectiveness_rating', sa.Numeric(5,2), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # hedged_item
    if not _table_exists_mig('hedged_item'):
        op.create_table('hedged_item',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('hedge_relationship_id', UUID(as_uuid=True), nullable=False),
        sa.Column('item_type', sa.String(50), nullable=False),
        sa.Column('item_id', UUID(as_uuid=True), nullable=False),
        sa.Column('item_description', sa.String(500), nullable=False),
        sa.Column('risk_type', sa.String(50), nullable=False),
        sa.Column('exposure_amount', sa.Numeric(19,4), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    # hedge_effectiveness_test
    if not _table_exists_mig('hedge_effectiveness_test'):
        op.create_table('hedge_effectiveness_test',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('hedge_relationship_id', UUID(as_uuid=True), nullable=False),
        sa.Column('test_date', sa.Date(), nullable=False),
        sa.Column('method', sa.String(50), nullable=False),
        sa.Column('result', sa.String(30), nullable=False),
        sa.Column('ratio', sa.Numeric(10,4), nullable=True),
        sa.Column('data', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # ========================================================================
    # 8. INVENTORY TABLES
    # ========================================================================

    # inventory_stock_card
    if not _table_exists_mig('inventory_stock_card'):
        op.create_table('inventory_stock_card',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('item_id', UUID(as_uuid=True), nullable=False),
        sa.Column('warehouse_id', UUID(as_uuid=True), nullable=False),
        sa.Column('transaction_date', sa.Date(), nullable=False),
        sa.Column('transaction_type', sa.String(30), nullable=False),
        sa.Column('reference_id', UUID(as_uuid=True), nullable=True),
        sa.Column('reference_number', sa.String(50), nullable=True),
        sa.Column('quantity_in', sa.Numeric(19,4), server_default='0'),
        sa.Column('quantity_out', sa.Numeric(19,4), server_default='0'),
        sa.Column('balance_quantity', sa.Numeric(19,4), nullable=False),
        sa.Column('unit_cost', sa.Numeric(19,4), nullable=True),
        sa.Column('balance_value', sa.Numeric(19,4), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # stock_card (alias untuk inventory_stock_card)
    if not _table_exists_mig('stock_card'):
        op.create_table('stock_card',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('item_id', UUID(as_uuid=True), nullable=False),
        sa.Column('warehouse_id', UUID(as_uuid=True), nullable=False),
        sa.Column('transaction_date', sa.Date(), nullable=False),
        sa.Column('transaction_type', sa.String(30), nullable=False),
        sa.Column('reference_id', UUID(as_uuid=True), nullable=True),
        sa.Column('reference_number', sa.String(50), nullable=True),
        sa.Column('quantity_in', sa.Numeric(19,4), server_default='0'),
        sa.Column('quantity_out', sa.Numeric(19,4), server_default='0'),
        sa.Column('balance_quantity', sa.Numeric(19,4), nullable=False),
        sa.Column('unit_cost', sa.Numeric(19,4), nullable=True),
        sa.Column('balance_value', sa.Numeric(19,4), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # stock_opname
    if not _table_exists_mig('stock_opname'):
        op.create_table('stock_opname',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('warehouse_id', UUID(as_uuid=True), nullable=False),
        sa.Column('opname_number', sa.String(50), nullable=False),
        sa.Column('opname_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='draft'),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('approved_by', UUID(as_uuid=True), nullable=True),
    )

    # stock_opname_line
    if not _table_exists_mig('stock_opname_line'):
        op.create_table('stock_opname_line',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('opname_id', UUID(as_uuid=True), nullable=False),
        sa.Column('item_id', UUID(as_uuid=True), nullable=False),
        sa.Column('system_quantity', sa.Numeric(19,4), nullable=False),
        sa.Column('physical_quantity', sa.Numeric(19,4), nullable=False),
        sa.Column('difference_quantity', sa.Numeric(19,4), nullable=False),
        sa.Column('unit_cost', sa.Numeric(19,4), nullable=True),
        sa.Column('difference_value', sa.Numeric(19,4), nullable=True),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    # ========================================================================
    # 9. LEGAL ENTITY & COMPANY TABLES
    # ========================================================================

    # legal_entity_branch
    if not _table_exists_mig('legal_entity_branch'):
        op.create_table('legal_entity_branch',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('branch_code', sa.String(50), nullable=False),
        sa.Column('branch_name', sa.String(200), nullable=False),
        sa.Column('address', sa.String(500), nullable=True),
        sa.Column('city', sa.String(100), nullable=True),
        sa.Column('province', sa.String(100), nullable=True),
        sa.Column('postal_code', sa.String(10), nullable=True),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('email', sa.String(200), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # company_entity (alias untuk legal_entity)
    if not _table_exists_mig('company_entity'):
        op.create_table('company_entity',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('company_code', sa.String(50), nullable=False),
        sa.Column('company_name', sa.String(200), nullable=False),
        sa.Column('npwp', sa.String(15), nullable=True),
        sa.Column('address', sa.String(500), nullable=True),
        sa.Column('city', sa.String(100), nullable=True),
        sa.Column('province', sa.String(100), nullable=True),
        sa.Column('postal_code', sa.String(10), nullable=True),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('email', sa.String(200), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # ========================================================================
    # 10. REPORT TABLES
    # ========================================================================

    # report_definition
    if not _table_exists_mig('report_definition'):
        op.create_table('report_definition',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('report_code', sa.String(50), nullable=False),
        sa.Column('report_name', sa.String(200), nullable=False),
        sa.Column('report_type', sa.String(50), nullable=False),
        sa.Column('definition', JSONB, nullable=False),
        sa.Column('parameters', JSONB, nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # report_output
    if not _table_exists_mig('report_output'):
        op.create_table('report_output',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('report_definition_id', UUID(as_uuid=True), nullable=False),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('execution_date', sa.DateTime(), nullable=False),
        sa.Column('parameters_used', JSONB, nullable=True),
        sa.Column('output_format', sa.String(20), nullable=False),
        sa.Column('output_data', sa.Text(), nullable=True),
        sa.Column('file_path', sa.String(500), nullable=True),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('error_message', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # report_schedule
    if not _table_exists_mig('report_schedule'):
        op.create_table('report_schedule',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('report_definition_id', UUID(as_uuid=True), nullable=False),
        sa.Column('schedule_type', sa.String(20), nullable=False),
        sa.Column('cron_expression', sa.String(100), nullable=True),
        sa.Column('interval_minutes', sa.Integer(), nullable=True),
        sa.Column('start_date', sa.DateTime(), nullable=False),
        sa.Column('end_date', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # ========================================================================
    # 11. MANUFACTURING TABLES
    # ========================================================================

    # manufacturing_work_order
    if not _table_exists_mig('manufacturing_work_order'):
        op.create_table('manufacturing_work_order',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('work_order_number', sa.String(50), nullable=False),
        sa.Column('product_id', UUID(as_uuid=True), nullable=False),
        sa.Column('product_code', sa.String(50), nullable=False),
        sa.Column('product_name', sa.String(200), nullable=False),
        sa.Column('quantity_planned', sa.Numeric(19,4), nullable=False),
        sa.Column('quantity_produced', sa.Numeric(19,4), server_default='0'),
        sa.Column('quantity_scrap', sa.Numeric(19,4), server_default='0'),
        sa.Column('bom_id', UUID(as_uuid=True), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='draft'),
        sa.Column('priority', sa.Integer(), server_default='1'),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('approved_by', UUID(as_uuid=True), nullable=True),
    )

    # manufacturing_cost_card
    if not _table_exists_mig('manufacturing_cost_card'):
        op.create_table('manufacturing_cost_card',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('work_order_id', UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', UUID(as_uuid=True), nullable=False),
        sa.Column('cost_element', sa.String(50), nullable=False),
        sa.Column('amount', sa.Numeric(19,4), nullable=False),
        sa.Column('quantity', sa.Numeric(19,4), nullable=True),
        sa.Column('unit_cost', sa.Numeric(19,4), nullable=True),
        sa.Column('reference_type', sa.String(50), nullable=True),
        sa.Column('reference_id', UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    # ========================================================================
    # 12. SALES TABLES
    # ========================================================================

    # sales_invoice
    if not _table_exists_mig('sales_invoice'):
        op.create_table('sales_invoice',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('invoice_number', sa.String(50), nullable=False),
        sa.Column('invoice_date', sa.Date(), nullable=False),
        sa.Column('customer_id', UUID(as_uuid=True), nullable=False),
        sa.Column('customer_name', sa.String(200), nullable=False),
        sa.Column('customer_npwp', sa.String(15), nullable=True),
        sa.Column('sales_order_id', UUID(as_uuid=True), nullable=True),
        sa.Column('subtotal', sa.Numeric(19,4), nullable=False),
        sa.Column('discount_amount', sa.Numeric(19,4), server_default='0'),
        sa.Column('tax_amount', sa.Numeric(19,4), server_default='0'),
        sa.Column('total_amount', sa.Numeric(19,4), nullable=False),
        sa.Column('paid_amount', sa.Numeric(19,4), server_default='0'),
        sa.Column('outstanding_amount', sa.Numeric(19,4), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='draft'),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('approved_by', UUID(as_uuid=True), nullable=True),
    )

    # ========================================================================
    # 13. BANK & CASH TABLES
    # ========================================================================

    # bank_reconciliations
    if not _table_exists_mig('bank_reconciliations'):
        op.create_table('bank_reconciliations',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('bank_account_id', UUID(as_uuid=True), nullable=False),
        sa.Column('reconciliation_date', sa.Date(), nullable=False),
        sa.Column('statement_balance', sa.Numeric(19,4), nullable=False),
        sa.Column('ledger_balance', sa.Numeric(19,4), nullable=False),
        sa.Column('difference', sa.Numeric(19,4), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('approved_by', UUID(as_uuid=True), nullable=True),
    )

    # bank_reconciliation_items
    if not _table_exists_mig('bank_reconciliation_items'):
        op.create_table('bank_reconciliation_items',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('reconciliation_id', UUID(as_uuid=True), nullable=False),
        sa.Column('transaction_id', UUID(as_uuid=True), nullable=False),
        sa.Column('transaction_type', sa.String(30), nullable=False),
        sa.Column('amount', sa.Numeric(19,4), nullable=False),
        sa.Column('transaction_date', sa.Date(), nullable=False),
        sa.Column('cleared_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    # ========================================================================
    # 14. APPROVAL TABLES
    # ========================================================================

    # approval_request
    if not _table_exists_mig('approval_request'):
        op.create_table('approval_request',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('request_number', sa.String(50), nullable=False),
        sa.Column('requested_by', UUID(as_uuid=True), nullable=False),
        sa.Column('requested_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('approval_level', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('approved_by', UUID(as_uuid=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('rejected_by', UUID(as_uuid=True), nullable=True),
        sa.Column('rejected_at', sa.DateTime(), nullable=True),
        sa.Column('rejection_reason', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    # approval_rule
    if not _table_exists_mig('approval_rule'):
        op.create_table('approval_rule',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('rule_name', sa.String(200), nullable=False),
        sa.Column('approval_levels', JSONB, nullable=False),
        sa.Column('min_amount', sa.Numeric(19,4), nullable=True),
        sa.Column('max_amount', sa.Numeric(19,4), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # ========================================================================
    # 15. PROJECTION TABLES
    # ========================================================================

    # projection_checkpoint
    if not _table_exists_mig('projection_checkpoint'):
        op.create_table('projection_checkpoint',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('projection_name', sa.String(100), nullable=False),
        sa.Column('last_position', sa.BigInteger(), nullable=False),
        sa.Column('last_event_id', UUID(as_uuid=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    # ========================================================================
    # 16. GENERAL LEDGER TABLES
    # ========================================================================

    # general_ledger
    if not _table_exists_mig('general_ledger'):
        op.create_table('general_ledger',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', UUID(as_uuid=True), nullable=False),
        sa.Column('account_code', sa.String(20), nullable=False),
        sa.Column('account_name', sa.String(200), nullable=False),
        sa.Column('transaction_date', sa.Date(), nullable=False),
        sa.Column('reference_id', UUID(as_uuid=True), nullable=True),
        sa.Column('reference_type', sa.String(50), nullable=True),
        sa.Column('reference_number', sa.String(50), nullable=True),
        sa.Column('debit_amount', sa.Numeric(19,4), server_default='0'),
        sa.Column('credit_amount', sa.Numeric(19,4), server_default='0'),
        sa.Column('balance', sa.Numeric(19,4), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # ledger_entry
    if not _table_exists_mig('ledger_entry'):
        op.create_table('ledger_entry',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('journal_id', UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', UUID(as_uuid=True), nullable=False),
        sa.Column('account_code', sa.String(20), nullable=False),
        sa.Column('debit', sa.Numeric(19,4), server_default='0'),
        sa.Column('credit', sa.Numeric(19,4), server_default='0'),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('transaction_date', sa.Date(), nullable=False),
        sa.Column('period', sa.String(7), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # ========================================================================
    # 17. AML TABLES
    # ========================================================================

    # aml_risk_score
    if not _table_exists_mig('aml_risk_score'):
        op.create_table('aml_risk_score',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('risk_score', sa.Integer(), nullable=False),
        sa.Column('risk_level', sa.String(20), nullable=False),
        sa.Column('assessment_date', sa.Date(), nullable=False),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('factors', JSONB, nullable=True),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # aml_suspicious_transaction
    if not _table_exists_mig('aml_suspicious_transaction'):
        op.create_table('aml_suspicious_transaction',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('transaction_id', UUID(as_uuid=True), nullable=False),
        sa.Column('transaction_type', sa.String(50), nullable=False),
        sa.Column('amount', sa.Numeric(19,4), nullable=False),
        sa.Column('transaction_date', sa.Date(), nullable=False),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('risk_score', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='reported'),
        sa.Column('reported_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # ========================================================================
    # 18. UMKM TABLES
    # ========================================================================

    # umkm_profile
    if not _table_exists_mig('umkm_profile'):
        op.create_table('umkm_profile',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('business_name', sa.String(200), nullable=False),
        sa.Column('business_type', sa.String(50), nullable=False),
        sa.Column('business_scale', sa.String(30), nullable=False),
        sa.Column('npwp', sa.String(15), nullable=True),
        sa.Column('annual_revenue', sa.Numeric(19,4), nullable=True),
        sa.Column('employees_count', sa.Integer(), nullable=True),
        sa.Column('address', sa.String(500), nullable=True),
        sa.Column('city', sa.String(100), nullable=True),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('email', sa.String(200), nullable=True),
        sa.Column('tax_method', sa.String(30), nullable=False, server_default='standard'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # umkm_transaction
    if not _table_exists_mig('umkm_transaction'):
        op.create_table('umkm_transaction',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('umkm_profile_id', UUID(as_uuid=True), nullable=False),
        sa.Column('transaction_date', sa.Date(), nullable=False),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('amount', sa.Numeric(19,4), nullable=False),
        sa.Column('transaction_type', sa.String(30), nullable=False),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('reference_id', UUID(as_uuid=True), nullable=True),
        sa.Column('reference_type', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # ========================================================================
    # 19. SAGA STATE TABLES
    # ========================================================================

    # saga_state
    if not _table_exists_mig('saga_state'):
        op.create_table('saga_state',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('saga_id', UUID(as_uuid=True), nullable=False),
        sa.Column('saga_type', sa.String(100), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('current_step', sa.Integer(), nullable=False),
        sa.Column('total_steps', sa.Integer(), nullable=False),
        sa.Column('data', JSONB, nullable=False),
        sa.Column('error', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('started_by', UUID(as_uuid=True), nullable=True),
    )

    # ========================================================================
    # 20. EXCHANGE RATE TABLE
    # ========================================================================

    # exchange_rate
    if not _table_exists_mig('exchange_rate'):
        op.create_table('exchange_rate',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('currency_from', sa.String(3), nullable=False),
        sa.Column('currency_to', sa.String(3), nullable=False),
        sa.Column('rate', sa.Numeric(19,6), nullable=False),
        sa.Column('rate_date', sa.Date(), nullable=False),
        sa.Column('source', sa.String(50), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # ========================================================================
    # 21. ASSET CATEGORY TABLE
    # ========================================================================

    # asset_categories
    if not _table_exists_mig('asset_categories'):
        op.create_table('asset_categories',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('category_code', sa.String(50), nullable=False),
        sa.Column('category_name', sa.String(200), nullable=False),
        sa.Column('category_type', sa.String(20), nullable=False),
        sa.Column('parent_id', UUID(as_uuid=True), nullable=True),
        sa.Column('useful_life_years', sa.Integer(), nullable=True),
        sa.Column('depreciation_method', sa.String(30), nullable=True),
        sa.Column('depreciation_rate', sa.Numeric(5,2), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )

    # ========================================================================
    # 22. GOODS RECEIPT NOTE LINES
    # ========================================================================

    # goods_receipt_note_lines
    if not _table_exists_mig('goods_receipt_note_lines'):
        op.create_table('goods_receipt_note_lines',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('goods_receipt_note_id', UUID(as_uuid=True), nullable=False),
        sa.Column('purchase_order_line_id', UUID(as_uuid=True), nullable=True),
        sa.Column('item_id', UUID(as_uuid=True), nullable=False),
        sa.Column('item_code', sa.String(50), nullable=False),
        sa.Column('item_name', sa.String(200), nullable=False),
        sa.Column('quantity_received', sa.Numeric(19,4), nullable=False),
        sa.Column('quantity_accepted', sa.Numeric(19,4), nullable=False),
        sa.Column('quantity_rejected', sa.Numeric(19,4), server_default='0'),
        sa.Column('unit_cost', sa.Numeric(19,4), nullable=False),
        sa.Column('total_cost', sa.Numeric(19,4), nullable=False),
        sa.Column('warehouse_id', UUID(as_uuid=True), nullable=False),
        sa.Column('bin_location', sa.String(50), nullable=True),
        sa.Column('batch_number', sa.String(50), nullable=True),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    # ========================================================================
    # 23. PAYSLIP TABLE
    # ========================================================================

    # payslip
    if not _table_exists_mig('payslip'):
        op.create_table('payslip',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('employee_id', UUID(as_uuid=True), nullable=False),
        sa.Column('payslip_number', sa.String(50), nullable=False),
        sa.Column('period', sa.String(7), nullable=False),
        sa.Column('gross_salary', sa.Numeric(19,4), nullable=False),
        sa.Column('allowances', sa.Numeric(19,4), server_default='0'),
        sa.Column('bonuses', sa.Numeric(19,4), server_default='0'),
        sa.Column('overtime_pay', sa.Numeric(19,4), server_default='0'),
        sa.Column('total_deductions', sa.Numeric(19,4), server_default='0'),
        sa.Column('bpjs_tk', sa.Numeric(19,4), server_default='0'),
        sa.Column('bpjs_kes', sa.Numeric(19,4), server_default='0'),
        sa.Column('pph21', sa.Numeric(19,4), server_default='0'),
        sa.Column('net_salary', sa.Numeric(19,4), nullable=False),
        sa.Column('payment_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='draft'),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('approved_by', UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    # Drop all tables in reverse order
    tables = [
        'payslip',
        'goods_receipt_note_lines',
        'asset_categories',
        'exchange_rate',
        'saga_state',
        'umkm_transaction',
        'umkm_profile',
        'aml_suspicious_transaction',
        'aml_risk_score',
        'ledger_entry',
        'general_ledger',
        'projection_checkpoint',
        'approval_rule',
        'approval_request',
        'bank_reconciliation_items',
        'bank_reconciliations',
        'sales_invoice',
        'manufacturing_cost_card',
        'manufacturing_work_order',
        'report_schedule',
        'report_output',
        'report_definition',
        'company_entity',
        'legal_entity_branch',
        'stock_opname_line',
        'stock_opname',
        'stock_card',
        'inventory_stock_card',
        'hedge_effectiveness_test',
        'hedged_item',
        'hedge_instrument',
        'goodwill_impairment',
        'goodwill',
        'intangible_revaluation',
        'disposal',
        'revaluation',
        'impairment_test',
        'fixed_asset_schedule',
        'coretax_submission_log',
        'coretax_emeterai',
        'coretax_nsfp',
        'coretax_ntpn',
        'coretax_spt',
        'coretax_bupot',
        'coretax_faktur_line',
        'coretax_faktur',
        'consolidation_group_member',
        'consolidation_group',
        'budget_actual',
        'budget',
        'dead_letter_events',
        'outbox_checkpoint',
        'outbox',
        'snapshot_store',
        'hash_chain',
        'event_store',
        'audit_event',
    ]
    for table in tables:
        op.drop_table(table)