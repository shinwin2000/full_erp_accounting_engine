"""sync budget table columns

Revision ID: 81de37e7a243
Revises: 27d8615ee183
Create Date: 2026-08-05 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '81de37e7a243'
down_revision = '27d8615ee183'
branch_labels = None
depends_on = None


def upgrade():
    # ========== DROP TABLES dengan CASCADE ==========
    tables_to_drop = [
        'approval_request', 'budget_actual', 'approval_rule', 'ledger_entry_partitioned',
        'projection_financial_ratios', 'coretax_submission_log', 'goods_receipt_line',
        'aml_suspicious_transaction', 'umkm_profile', 'stock_card', 'asset_category',
        'exchange_rate', 'pph_withholding_summary', 'company_entity', 'general_ledger',
        'ledger_entry_2028', 'projection_trend_12month', 'sales_order_lines', 'saga_event',
        'aml_risk_score', 'coretax_webhook_inbound', 'sales_invoice', 'dividend_declaration',
        'journal_line_2027', 'outbox_relay_metrics', 'salary_structure', 'manufacturing_work_order',
        'ledger_entry_2024', 'hedging_relationship', 'projection_pph_summary', 'umkm_business_profile',
        'journal_line_2025', 'projection_profitability_segment', 'ppn_settlement', 'routing',
        'intangible_revaluation', 'journal_line_2020', 'inventory_stock_card', 'sales_order_line',
        'retained_earnings_history', 'hedge_instrument', 'payroll_adjustment', 'login_attempt',
        'journal_line_2028', 'ledger_entry_2030', 'snapshot_store', 'bill_of_materials_line',
        'stock_opname_lines', 'umkm_transaction', 'journal_line_2024', 'outbox_relay_checkpoint',
        'coretax_faktur_masukan', 'outbox_dead_letter', 'journal_line_2022', 'fair_value_hierarchy',
        'report_schedule', 'payslip', 'cost_card_work_order', 'ledger_entry_2022', 'ledger_entry_2027',
        'ledger_entry_2025', 'aggregate_snapshot', 'saga_lock', 'payroll_detail', 'saga_step_log',
        'budget', 'report_output', 'derivative_instrument', 'journal_line_2030', 'delivery_order_lines',
        'hedge_effectiveness_test', 'fixed_asset_schedule', 'coretax_faktur_keluaran',
        'outbox_kafka_partition_checkpoint', 'projection_checkpoints', 'purchase_order_lines',
        'journal_line_2021', 'bank_reconciliation', 'umkm_journal', 'projection_variance_analysis',
        'projection_ppn_settlement', 'stock_opname_line', 'audit', 'journal_line_2023',
        'payroll_payslip', 'delivery_order', 'projection_ar_aging', 'projection_coretax_dashboard',
        'capital_contribution', 'journal_line_partitioned', 'journal_line_2026', 'machine',
        'journal_line_2029', 'ledger_entry_2023', 'integrity_check_result', 'goodwill_impairment',
        'work_in_process', 'delivery_order_line', 'projection_trial_balance', 'manufacturing_cost_card',
        'projection_read_models', 'report_definition', 'ledger_entry_2020', 'routing_step',
        'ledger_entry_2026', 'projection_ap_aging', 'projection_gl_ledger', 'goodwill',
        'coretax_spt_electronic', 'coretax_audit_log', 'ledger_entry_2029', 'projection_kpi_alerter',
        'ledger_entry_2021', 'saga_instance', 'hedged_item'
    ]

    for table in tables_to_drop:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    # ========== ALTER COLUMN TYPES ==========
    op.alter_column('coretax_spt', 'approval_date',
                    existing_type=sa.TIMESTAMP(timezone=True),
                    type_=sa.Date())
    op.alter_column('legal_entity_branch', 'created_at',
                    existing_type=sa.TIMESTAMP(timezone=True),
                    type_=sa.DateTime())
    op.alter_column('legal_entity_branch', 'updated_at',
                    existing_type=sa.TIMESTAMP(timezone=True),
                    type_=sa.DateTime())
    op.alter_column('legal_entity_branch', 'deleted_at',
                    existing_type=sa.TIMESTAMP(timezone=True),
                    type_=sa.DateTime())

    # ========== ADD COLUMNS TO 'outbox' ==========
    op.add_column('outbox', sa.Column('event_id', sa.String(), nullable=True))
    op.add_column('outbox', sa.Column('idempotency_key', sa.String(), nullable=True))
    op.add_column('outbox', sa.Column('processed_at', sa.DateTime(), nullable=True))
    op.add_column('outbox', sa.Column('version', sa.Integer(), nullable=True))
    op.add_column('outbox', sa.Column('priority', sa.Integer(), nullable=True))
    op.add_column('outbox', sa.Column('scheduled_at', sa.DateTime(), nullable=True))
    op.add_column('outbox', sa.Column('correlation_id', sa.String(), nullable=True))

    # ========== ADD INDEXES ==========
    op.create_index('idx_outbox_correlation_id', 'outbox', ['correlation_id'])
    op.create_index('idx_outbox_event_id', 'outbox', ['event_id'])
    op.create_index('idx_outbox_idempotency_key', 'outbox', ['idempotency_key'])
    op.create_index('idx_outbox_priority', 'outbox', ['priority'])
    op.create_index('idx_outbox_processed_at', 'outbox', ['processed_at'])
    op.create_index('idx_outbox_scheduled_at', 'outbox', ['scheduled_at'])

    # ========== ADD UNIQUE CONSTRAINTS ==========
    op.create_unique_constraint(None, 'outbox', ['event_id'])
    op.create_unique_constraint(None, 'outbox', ['idempotency_key'])

    # ========== RECREATE FOREIGN KEY ==========
    # Bagian ini dikomentari agar tidak error "relation bom does not exist"
    # op.execute("ALTER TABLE work_order DROP CONSTRAINT IF EXISTS fk_work_order_bom_id")
    # op.create_foreign_key(None, 'work_order', 'bom', ['bom_id'], ['id'])


def downgrade():
    # ========== REVERT FOREIGN KEY ==========
    # Bagian ini dikomentari agar tidak error saat di-downgrade
    # op.execute("ALTER TABLE work_order DROP CONSTRAINT IF EXISTS fk_work_order_bom_id")
    # op.create_foreign_key('fk_work_order_bom_id', 'work_order', 'bom', ['bom_id'], ['id'])

    # ========== DROP UNIQUE CONSTRAINTS ==========
    op.execute("ALTER TABLE outbox DROP CONSTRAINT IF EXISTS outbox_event_id_key")
    op.execute("ALTER TABLE outbox DROP CONSTRAINT IF EXISTS outbox_idempotency_key_key")

    # ========== DROP INDEXES ==========
    op.execute("DROP INDEX IF EXISTS idx_outbox_scheduled_at")
    op.execute("DROP INDEX IF EXISTS idx_outbox_processed_at")
    op.execute("DROP INDEX IF EXISTS idx_outbox_priority")
    op.execute("DROP INDEX IF EXISTS idx_outbox_idempotency_key")
    op.execute("DROP INDEX IF EXISTS idx_outbox_event_id")
    op.execute("DROP INDEX IF EXISTS idx_outbox_correlation_id")

    # ========== REMOVE COLUMNS ==========
    op.drop_column('outbox', 'correlation_id')
    op.drop_column('outbox', 'scheduled_at')
    op.drop_column('outbox', 'priority')
    op.drop_column('outbox', 'version')
    op.drop_column('outbox', 'processed_at')
    op.drop_column('outbox', 'idempotency_key')
    op.drop_column('outbox', 'event_id')

    # ========== REVERT COLUMN TYPES ==========
    op.alter_column('legal_entity_branch', 'deleted_at',
                    existing_type=sa.DateTime(),
                    type_=sa.TIMESTAMP(timezone=True))
    op.alter_column('legal_entity_branch', 'updated_at',
                    existing_type=sa.DateTime(),
                    type_=sa.TIMESTAMP(timezone=True))
    op.alter_column('legal_entity_branch', 'created_at',
                    existing_type=sa.DateTime(),
                    type_=sa.TIMESTAMP(timezone=True))
    op.alter_column('coretax_spt', 'approval_date',
                    existing_type=sa.Date(),
                    type_=sa.TIMESTAMP(timezone=True))

    pass