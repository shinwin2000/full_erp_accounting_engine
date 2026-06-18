"""add all missing ORM tables (idempotent version)

Revision ID: 0040
Revises: 0039
Create Date: 2026-06-15 15:30:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP, JSONB, NUMERIC

revision: str = '0040'
down_revision = '0039'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # ========================================================================
    # This migration adds ALL tables that exist in the ORM layer
    # but were missing from previous migrations.
    # All operations are idempotent (IF NOT EXISTS) to avoid errors.
    # ========================================================================

    # ========================================================================
    # 1. Approval & Workflow
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS approval_request (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        request_type VARCHAR(50) NOT NULL,
        request_data JSONB NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        submitted_by UUID NOT NULL,
        submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        approved_by UUID,
        approved_at TIMESTAMPTZ,
        rejection_reason TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        updated_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_approval_request_legal_entity ON approval_request (legal_entity_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_approval_request_status ON approval_request (status);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS approval_rule (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        rule_name VARCHAR(100) NOT NULL,
        entity_type VARCHAR(50) NOT NULL,
        min_amount NUMERIC(20,2) NOT NULL DEFAULT 0,
        approver_role_ids JSONB NOT NULL,
        requires_second_approval BOOLEAN NOT NULL DEFAULT false,
        is_active BOOLEAN NOT NULL DEFAULT true,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        updated_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_approval_rule_legal_entity ON approval_rule (legal_entity_id);")

    # ========================================================================
    # 2. Asset Management
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS asset_category (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        category_code VARCHAR(30) NOT NULL,
        category_name VARCHAR(200) NOT NULL,
        useful_life_years INTEGER NOT NULL,
        depreciation_method VARCHAR(25) NOT NULL,
        salvage_value_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        updated_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_asset_category_legal_entity ON asset_category (legal_entity_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS asset_categories (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        category_code VARCHAR(30) NOT NULL,
        category_name VARCHAR(200) NOT NULL,
        useful_life_years INTEGER NOT NULL,
        depreciation_method VARCHAR(25) NOT NULL,
        salvage_value_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        updated_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_asset_categories_legal_entity ON asset_categories (legal_entity_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS revaluation (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        asset_id UUID NOT NULL,
        revaluation_date DATE NOT NULL,
        old_value NUMERIC(20,2) NOT NULL,
        new_value NUMERIC(20,2) NOT NULL,
        revaluation_surplus NUMERIC(20,2) NOT NULL,
        journal_id UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_revaluation_asset ON revaluation (asset_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS disposal (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        asset_id UUID NOT NULL,
        disposal_date DATE NOT NULL,
        proceeds NUMERIC(20,2) NOT NULL,
        gain_loss NUMERIC(20,2) NOT NULL,
        journal_id UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_disposal_asset ON disposal (asset_id);")

    # ========================================================================
    # 3. Audit & Logging
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS audit_event (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        event_type VARCHAR(50) NOT NULL,
        aggregate_type VARCHAR(100) NOT NULL,
        aggregate_id UUID NOT NULL,
        event_data JSONB NOT NULL,
        user_id UUID NOT NULL,
        ip_address VARCHAR(45),
        user_agent VARCHAR(500),
        occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_event_legal_entity ON audit_event (legal_entity_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_event_aggregate ON audit_event (aggregate_type, aggregate_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_event_occurred_at ON audit_event (occurred_at);")

    # ========================================================================
    # 4. Banking & Cash Management
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS bank_reconciliation (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        bank_account_id UUID NOT NULL,
        reconciliation_date DATE NOT NULL,
        statement_balance NUMERIC(20,2) NOT NULL,
        book_balance NUMERIC(20,2) NOT NULL,
        difference NUMERIC(20,2) NOT NULL,
        is_reconciled BOOLEAN NOT NULL DEFAULT false,
        reconciled_by UUID,
        reconciled_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        updated_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_bank_reconciliation_legal_entity ON bank_reconciliation (legal_entity_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_bank_reconciliation_account ON bank_reconciliation (bank_account_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS bank_reconciliations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        bank_account_id UUID NOT NULL,
        reconciliation_date DATE NOT NULL,
        statement_balance NUMERIC(20,2) NOT NULL,
        book_balance NUMERIC(20,2) NOT NULL,
        difference NUMERIC(20,2) NOT NULL,
        is_reconciled BOOLEAN NOT NULL DEFAULT false,
        reconciled_by UUID,
        reconciled_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        updated_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_bank_reconciliations_entity ON bank_reconciliations (legal_entity_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS bank_reconciliation_items (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        reconciliation_id UUID NOT NULL,
        bank_transaction_id UUID,
        statement_line_id UUID,
        amount NUMERIC(20,2) NOT NULL,
        is_matched BOOLEAN NOT NULL DEFAULT false,
        match_status VARCHAR(20) NOT NULL DEFAULT 'pending',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_bank_reconciliation_items_rec ON bank_reconciliation_items (reconciliation_id);")

    # ========================================================================
    # 5. Budgeting
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS budget (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        budget_code VARCHAR(50) NOT NULL,
        fiscal_year INTEGER NOT NULL,
        account_id UUID NOT NULL,
        amount NUMERIC(20,2) NOT NULL,
        currency VARCHAR(3) NOT NULL DEFAULT 'IDR',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        updated_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_budget_legal_entity ON budget (legal_entity_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_budget_account ON budget (account_id, fiscal_year);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS budget_actual (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        account_id UUID NOT NULL,
        fiscal_year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        actual_amount NUMERIC(20,2) NOT NULL DEFAULT 0,
        budget_amount NUMERIC(20,2) NOT NULL DEFAULT 0,
        variance NUMERIC(20,2) NOT NULL DEFAULT 0,
        variance_percent NUMERIC(10,2) NOT NULL DEFAULT 0,
        last_updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_budget_actual_entity_account_period ON budget_actual (legal_entity_id, account_id, fiscal_year, period);")

    # ========================================================================
    # 6. Company Structure
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS company_entity (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        entity_code VARCHAR(30) NOT NULL,
        entity_name VARCHAR(200) NOT NULL,
        entity_type VARCHAR(20) NOT NULL,
        parent_entity_id UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        updated_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_company_entity_legal_entity ON company_entity (legal_entity_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS legal_entity_branch (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        branch_code VARCHAR(30) NOT NULL,
        branch_name VARCHAR(200) NOT NULL,
        address TEXT,
        city VARCHAR(100),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        updated_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_legal_entity_branch_legal_entity ON legal_entity_branch (legal_entity_id);")

    # ========================================================================
    # 7. Consolidation
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS consolidation_group (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        group_code VARCHAR(30) NOT NULL,
        group_name VARCHAR(200) NOT NULL,
        parent_legal_entity_id UUID NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        updated_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_consolidation_group_parent ON consolidation_group (parent_legal_entity_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS consolidation_group_member (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        group_id UUID NOT NULL,
        legal_entity_id UUID NOT NULL,
        ownership_percentage NUMERIC(5,2) NOT NULL,
        effective_date DATE NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_consolidation_member_group ON consolidation_group_member (group_id);")

    # ========================================================================
    # 8. Coretax (additional tables)
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS coretax_nsfp (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        nsfp_range_start VARCHAR(16) NOT NULL,
        nsfp_range_end VARCHAR(16) NOT NULL,
        current_sequence VARCHAR(16) NOT NULL,
        request_date DATE NOT NULL,
        expiry_date DATE NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_coretax_nsfp_legal_entity ON coretax_nsfp (legal_entity_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS coretax_ntpn (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        ntpn VARCHAR(16) NOT NULL UNIQUE,
        payment_amount NUMERIC(20,2) NOT NULL,
        payment_date DATE NOT NULL,
        tax_type VARCHAR(20) NOT NULL,
        period_month INTEGER NOT NULL,
        period_year INTEGER NOT NULL,
        validation_status VARCHAR(20) NOT NULL DEFAULT 'pending',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_coretax_ntpn_validation ON coretax_ntpn (validation_status);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS coretax_bupot (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        bupot_number VARCHAR(50) NOT NULL,
        bupot_date DATE NOT NULL,
        counterparty_npwp VARCHAR(20) NOT NULL,
        pph_type VARCHAR(10) NOT NULL,
        dpp NUMERIC(20,2) NOT NULL,
        pph_amount NUMERIC(20,2) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_coretax_bupot_legal_entity ON coretax_bupot (legal_entity_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS coretax_emeterai (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        meterai_code VARCHAR(50) NOT NULL,
        purchased_at TIMESTAMPTZ NOT NULL,
        used_at TIMESTAMPTZ,
        document_reference VARCHAR(200),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_coretax_emeterai_legal_entity ON coretax_emeterai (legal_entity_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS coretax_spt (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        spt_type VARCHAR(20) NOT NULL,
        period_month INTEGER,
        period_year INTEGER NOT NULL,
        spt_number VARCHAR(100) NOT NULL,
        status VARCHAR(30) NOT NULL,
        submitted_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_coretax_spt_entity_period ON coretax_spt (legal_entity_id, period_year, period_month);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_coretax_spt_status ON coretax_spt (status);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS coretax_submission_log (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        submission_type VARCHAR(50) NOT NULL,
        submission_payload JSONB NOT NULL,
        response_payload JSONB,
        status VARCHAR(20) NOT NULL,
        error_message TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_coretax_submission_log_entity ON coretax_submission_log (legal_entity_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS coretax_faktur_line (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        faktur_id UUID NOT NULL,
        line_number INTEGER NOT NULL,
        description VARCHAR(500) NOT NULL,
        quantity NUMERIC(20,2) NOT NULL,
        unit_price NUMERIC(20,2) NOT NULL,
        dpp NUMERIC(20,2) NOT NULL,
        ppn NUMERIC(20,2) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_coretax_faktur_line_faktur ON coretax_faktur_line (faktur_id);")

    # ========================================================================
    # 9. Dead Letter & Error Handling
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS dead_letter_events (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        event_type VARCHAR(200) NOT NULL,
        aggregate_type VARCHAR(100) NOT NULL,
        aggregate_id UUID NOT NULL,
        payload JSONB NOT NULL,
        error TEXT NOT NULL,
        failed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        status VARCHAR(20) NOT NULL DEFAULT 'pending'
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_dead_letter_status ON dead_letter_events (status);")

    # ========================================================================
    # 10. Exchange Rate
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS exchange_rate (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        from_currency VARCHAR(3) NOT NULL,
        to_currency VARCHAR(3) NOT NULL,
        rate NUMERIC(18,6) NOT NULL,
        rate_date DATE NOT NULL,
        source VARCHAR(50) NOT NULL DEFAULT 'manual',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_exchange_rate_legal_entity ON exchange_rate (legal_entity_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_exchange_rate_date ON exchange_rate (rate_date);")

    # ========================================================================
    # 11. General Ledger (non-partitioned)
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS general_ledger (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        account_id UUID NOT NULL,
        account_code VARCHAR(30) NOT NULL,
        posting_date DATE NOT NULL,
        debit_amount NUMERIC(20,2) NOT NULL DEFAULT 0,
        credit_amount NUMERIC(20,2) NOT NULL DEFAULT 0,
        journal_id UUID NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_general_ledger_legal_entity ON general_ledger (legal_entity_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_general_ledger_account ON general_ledger (account_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS ledger_entry (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        account_id UUID NOT NULL,
        debit_amount NUMERIC(20,2) NOT NULL DEFAULT 0,
        credit_amount NUMERIC(20,2) NOT NULL DEFAULT 0,
        posting_date DATE NOT NULL,
        journal_id UUID NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ledger_entry_legal_entity ON ledger_entry (legal_entity_id);")

    # ========================================================================
    # 12. Goodwill
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS goodwill (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        acquisition_date DATE NOT NULL,
        cost NUMERIC(20,2) NOT NULL,
        accumulated_impairment NUMERIC(20,2) NOT NULL DEFAULT 0,
        net_book_value NUMERIC(20,2) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_goodwill_legal_entity ON goodwill (legal_entity_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS goodwill_impairment (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        goodwill_id UUID NOT NULL,
        test_date DATE NOT NULL,
        recoverable_amount NUMERIC(20,2) NOT NULL,
        impairment_loss NUMERIC(20,2) NOT NULL,
        journal_id UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_goodwill_impairment_goodwill ON goodwill_impairment (goodwill_id);")

    # ========================================================================
    # 13. Hedge Accounting
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS hedge_effectiveness_test (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        hedging_relationship_id UUID NOT NULL,
        test_date DATE NOT NULL,
        test_method VARCHAR(30) NOT NULL,
        effectiveness_ratio NUMERIC(10,6) NOT NULL,
        is_effective BOOLEAN NOT NULL,
        ineffectiveness_amount NUMERIC(18,2) NOT NULL,
        test_details JSONB,
        performed_by UUID NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_hedge_effectiveness_test_relationship ON hedge_effectiveness_test (hedging_relationship_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS hedged_item (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        hedging_relationship_id UUID NOT NULL,
        item_type VARCHAR(50) NOT NULL,
        item_id UUID NOT NULL,
        fair_value NUMERIC(20,2) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_hedged_item_relationship ON hedged_item (hedging_relationship_id);")

    # ========================================================================
    # 14. Impairment Testing
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS impairment_test (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        asset_id UUID NOT NULL,
        test_date DATE NOT NULL,
        carrying_amount NUMERIC(20,2) NOT NULL,
        recoverable_amount NUMERIC(20,2) NOT NULL,
        impairment_loss NUMERIC(20,2) NOT NULL,
        journal_id UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_impairment_test_asset ON impairment_test (asset_id);")

    # ========================================================================
    # 15. Intangible Asset Revaluation
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS intangible_revaluation (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        asset_id UUID NOT NULL,
        revaluation_date DATE NOT NULL,
        old_value NUMERIC(20,2) NOT NULL,
        new_value NUMERIC(20,2) NOT NULL,
        journal_id UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_intangible_revaluation_asset ON intangible_revaluation (asset_id);")

    # ========================================================================
    # 16. Inventory Stock Card (denormalized)
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS inventory_stock_card (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        item_id UUID NOT NULL,
        warehouse_id UUID NOT NULL,
        transaction_date DATE NOT NULL,
        in_quantity NUMERIC(20,2) NOT NULL DEFAULT 0,
        out_quantity NUMERIC(20,2) NOT NULL DEFAULT 0,
        balance_quantity NUMERIC(20,2) NOT NULL,
        unit_cost NUMERIC(20,2) NOT NULL,
        total_value NUMERIC(20,2) NOT NULL,
        reference_type VARCHAR(50) NOT NULL,
        reference_id UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_inventory_stock_card_item ON inventory_stock_card (item_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_inventory_stock_card_date ON inventory_stock_card (transaction_date);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS stock_card (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        item_id UUID NOT NULL,
        warehouse_id UUID NOT NULL,
        movement_date DATE NOT NULL,
        movement_type VARCHAR(20) NOT NULL,
        quantity NUMERIC(20,2) NOT NULL,
        balance NUMERIC(20,2) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_stock_card_item ON stock_card (item_id);")

    # ========================================================================
    # 17. Manufacturing
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS manufacturing_work_order (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        work_order_number VARCHAR(50) NOT NULL,
        product_id UUID NOT NULL,
        product_name VARCHAR(200),
        planned_quantity NUMERIC(20,2) NOT NULL,
        completed_quantity NUMERIC(20,2) NOT NULL DEFAULT 0,
        rejected_quantity NUMERIC(20,2) NOT NULL DEFAULT 0,
        bom_id UUID,
        routing_id UUID,
        planned_start_date DATE NOT NULL,
        planned_end_date DATE NOT NULL,
        actual_start_date DATE,
        actual_end_date DATE,
        standard_cost NUMERIC(20,2) NOT NULL DEFAULT 0,
        actual_cost NUMERIC(20,2) NOT NULL DEFAULT 0,
        status VARCHAR(20) NOT NULL DEFAULT 'planned',
        cost_center VARCHAR(20),
        notes VARCHAR(500),
        legal_entity_id UUID NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        deleted_at TIMESTAMPTZ,
        version INTEGER NOT NULL DEFAULT 1,
        created_by UUID,
        updated_by UUID
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_mfg_work_order_number ON manufacturing_work_order (work_order_number);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_mfg_work_order_legal_entity ON manufacturing_work_order (legal_entity_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_mfg_work_order_status ON manufacturing_work_order (status);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS manufacturing_cost_card (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        cost_card_code VARCHAR(50) NOT NULL,
        product_id UUID NOT NULL,
        product_name VARCHAR(200),
        effective_date DATE NOT NULL,
        expiry_date DATE,
        cost_card_version INTEGER NOT NULL DEFAULT 1,
        material_cost NUMERIC(20,2) NOT NULL DEFAULT 0,
        labor_cost NUMERIC(20,2) NOT NULL DEFAULT 0,
        overhead_cost NUMERIC(20,2) NOT NULL DEFAULT 0,
        other_cost NUMERIC(20,2) NOT NULL DEFAULT 0,
        total_cost NUMERIC(20,2) NOT NULL DEFAULT 0,
        currency VARCHAR(3) NOT NULL DEFAULT 'IDR',
        quantity_base NUMERIC(20,2) NOT NULL DEFAULT 1,
        unit_of_measure VARCHAR(10) NOT NULL DEFAULT 'pcs',
        status VARCHAR(20) NOT NULL DEFAULT 'draft',
        is_active BOOLEAN NOT NULL DEFAULT true,
        notes VARCHAR(500),
        breakdown JSONB,
        legal_entity_id UUID NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID,
        updated_by UUID
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_mfg_cost_card_code ON manufacturing_cost_card (cost_card_code);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_mfg_cost_card_product ON manufacturing_cost_card (product_id);")

    # ========================================================================
    # 18. Outbox (and checkpoint)
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS outbox (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        aggregate_type VARCHAR(100) NOT NULL,
        aggregate_id UUID NOT NULL,
        event_type VARCHAR(200) NOT NULL,
        event_version INTEGER NOT NULL DEFAULT 1,
        payload JSONB NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}',
        kafka_topic VARCHAR(200) NOT NULL,
        kafka_key VARCHAR(200),
        kafka_partition INTEGER,
        status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
        retry_count INTEGER NOT NULL DEFAULT 0,
        last_attempt_at TIMESTAMPTZ,
        last_error TEXT,
        locked_by VARCHAR(100),
        locked_until TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        sent_at TIMESTAMPTZ
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_outbox_status_created ON outbox (status, created_at);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_outbox_lock ON outbox (locked_by, locked_until);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_outbox_aggregate ON outbox (aggregate_type, aggregate_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS outbox_checkpoint (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        consumer_group VARCHAR(200) NOT NULL UNIQUE,
        last_processed_outbox_id UUID NOT NULL,
        last_processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        processed_by VARCHAR(100) NOT NULL,
        total_processed_count BIGINT NOT NULL DEFAULT 0,
        total_failed_count BIGINT NOT NULL DEFAULT 0,
        last_error TEXT,
        version INTEGER NOT NULL DEFAULT 1
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_outbox_checkpoint_group ON outbox_checkpoint (consumer_group);")

    # ========================================================================
    # 19. Payroll
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS payroll_payslip (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        employee_id UUID NOT NULL,
        payroll_run_id UUID NOT NULL,
        period_year INTEGER NOT NULL,
        period_month INTEGER NOT NULL,
        gross_pay NUMERIC(20,2) NOT NULL,
        deductions NUMERIC(20,2) NOT NULL,
        net_pay NUMERIC(20,2) NOT NULL,
        pdf_url VARCHAR(500),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_payroll_payslip_employee ON payroll_payslip (employee_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS payslip (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        employee_id UUID NOT NULL,
        period VARCHAR(7) NOT NULL,
        gross NUMERIC(20,2) NOT NULL,
        net NUMERIC(20,2) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_payslip_employee ON payslip (employee_id);")

    # ========================================================================
    # 20. Projection Checkpoint
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS projection_checkpoint (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        projection_name VARCHAR(100) NOT NULL,
        last_processed_event_id UUID,
        last_processed_at TIMESTAMPTZ,
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_projection_checkpoint_name ON projection_checkpoint (projection_name);")

    # ========================================================================
    # 21. Reporting
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS report_definition (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        report_code VARCHAR(50) NOT NULL,
        report_name VARCHAR(200) NOT NULL,
        report_type VARCHAR(30) NOT NULL,
        query_definition JSONB NOT NULL,
        parameters_schema JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        updated_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_definition_legal_entity ON report_definition (legal_entity_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS report_schedule (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        report_definition_id UUID NOT NULL,
        schedule_cron VARCHAR(100) NOT NULL,
        recipient_emails JSONB NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT true,
        last_run_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_schedule_definition ON report_schedule (report_definition_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS report_output (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        report_definition_id UUID NOT NULL,
        generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        file_url VARCHAR(500) NOT NULL,
        file_format VARCHAR(10) NOT NULL,
        parameters_used JSONB NOT NULL,
        generated_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_output_definition ON report_output (report_definition_id);")

    # ========================================================================
    # 22. Sales Invoice (if separate from AR Invoice)
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS sales_invoice (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        invoice_number VARCHAR(50) NOT NULL,
        customer_id UUID NOT NULL,
        invoice_date DATE NOT NULL,
        total_amount NUMERIC(20,2) NOT NULL,
        paid_amount NUMERIC(20,2) NOT NULL DEFAULT 0,
        status VARCHAR(20) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_sales_invoice_legal_entity ON sales_invoice (legal_entity_id);")

    # ========================================================================
    # 23. Snapshot Store
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS snapshot_store (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        aggregate_type VARCHAR(100) NOT NULL,
        aggregate_id UUID NOT NULL,
        version BIGINT NOT NULL,
        snapshot_data JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_snapshot_store_aggregate ON snapshot_store (aggregate_type, aggregate_id, version);")

    # ========================================================================
    # 24. Hash Chain (already exists in 0031, but ensure)
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS hash_chain (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        chain_type VARCHAR(50) NOT NULL,
        chain_id UUID NOT NULL,
        sequence BIGINT NOT NULL,
        prev_hash VARCHAR(128),
        current_hash VARCHAR(128) NOT NULL,
        payload_hash VARCHAR(128) NOT NULL,
        timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        signature VARCHAR(512),
        signer_cert_fingerprint VARCHAR(128)
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_hash_chain_chain_seq ON hash_chain (chain_type, chain_id, sequence);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_hash_chain_current_hash ON hash_chain (current_hash);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_hash_chain_timestamp ON hash_chain (timestamp);")

    # ========================================================================
    # 25. Fixed Asset Schedule (depreciation schedule for fixed assets)
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS fixed_asset_schedule (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        asset_id UUID NOT NULL,
        period INTEGER NOT NULL,
        fiscal_year INTEGER NOT NULL,
        month INTEGER NOT NULL,
        depreciation_amount NUMERIC(20,2) NOT NULL DEFAULT 0,
        accumulated_depreciation NUMERIC(20,2) NOT NULL DEFAULT 0,
        net_book_value NUMERIC(20,2) NOT NULL DEFAULT 0,
        currency VARCHAR(3) NOT NULL DEFAULT 'IDR',
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        journal_id UUID,
        posted_at TIMESTAMPTZ,
        notes VARCHAR(500),
        legal_entity_id UUID NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_fixed_asset_schedule_asset ON fixed_asset_schedule (asset_id);")

    # ========================================================================
    # 26. Stock Opname
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS stock_opname (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        opname_number VARCHAR(50) NOT NULL,
        opname_date DATE NOT NULL,
        warehouse_id UUID NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'draft',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_stock_opname_legal_entity ON stock_opname (legal_entity_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS stock_opname_line (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        opname_id UUID NOT NULL,
        item_id UUID NOT NULL,
        system_quantity NUMERIC(20,2) NOT NULL,
        physical_quantity NUMERIC(20,2) NOT NULL,
        variance NUMERIC(20,2) NOT NULL,
        adjustment_journal_id UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_stock_opname_line_opname ON stock_opname_line (opname_id);")

    # ========================================================================
    # 27. UMKM Profile
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS umkm_business_profile (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        business_type VARCHAR(50) NOT NULL,
        annual_turnover NUMERIC(20,2) NOT NULL,
        uses_simplified_journal BOOLEAN NOT NULL DEFAULT false,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        updated_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_umkm_business_profile_legal_entity ON umkm_business_profile (legal_entity_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS umkm_profile (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        business_type VARCHAR(50) NOT NULL,
        annual_turnover NUMERIC(20,2) NOT NULL,
        uses_simplified_journal BOOLEAN NOT NULL DEFAULT false,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        updated_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_umkm_profile_legal_entity ON umkm_profile (legal_entity_id);")

    # ========================================================================
    # 28. AML
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS aml_risk_score (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        customer_id UUID,
        supplier_id UUID,
        risk_score INTEGER NOT NULL,
        risk_level VARCHAR(20) NOT NULL,
        calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        valid_until TIMESTAMPTZ,
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_aml_risk_score_customer ON aml_risk_score (customer_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS aml_suspicious_transaction (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        transaction_type VARCHAR(50) NOT NULL,
        transaction_id UUID NOT NULL,
        amount NUMERIC(20,2) NOT NULL,
        reason TEXT NOT NULL,
        detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        review_status VARCHAR(20) NOT NULL DEFAULT 'pending',
        reviewed_by UUID,
        reviewed_at TIMESTAMPTZ
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_aml_suspicious_legal_entity ON aml_suspicious_transaction (legal_entity_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_aml_suspicious_status ON aml_suspicious_transaction (review_status);")

    # ========================================================================
    # Foreign keys (idempotent using DO blocks)
    # ========================================================================
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_approval_request_legal_entity') THEN
            ALTER TABLE approval_request ADD CONSTRAINT fk_approval_request_legal_entity FOREIGN KEY (legal_entity_id) REFERENCES legal_entity(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_revaluation_asset') THEN
            ALTER TABLE revaluation ADD CONSTRAINT fk_revaluation_asset FOREIGN KEY (asset_id) REFERENCES fixed_asset(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_disposal_asset') THEN
            ALTER TABLE disposal ADD CONSTRAINT fk_disposal_asset FOREIGN KEY (asset_id) REFERENCES fixed_asset(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_bank_reconciliation_account') THEN
            ALTER TABLE bank_reconciliation ADD CONSTRAINT fk_bank_reconciliation_account FOREIGN KEY (bank_account_id) REFERENCES bank_account(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_budget_account') THEN
            ALTER TABLE budget ADD CONSTRAINT fk_budget_account FOREIGN KEY (account_id) REFERENCES account(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_coretax_faktur_line_faktur') THEN
            ALTER TABLE coretax_faktur_line ADD CONSTRAINT fk_coretax_faktur_line_faktur FOREIGN KEY (faktur_id) REFERENCES coretax_faktur_keluaran(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_goodwill_impairment_goodwill') THEN
            ALTER TABLE goodwill_impairment ADD CONSTRAINT fk_goodwill_impairment_goodwill FOREIGN KEY (goodwill_id) REFERENCES goodwill(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_hedge_effectiveness_test_relationship') THEN
            ALTER TABLE hedge_effectiveness_test ADD CONSTRAINT fk_hedge_effectiveness_test_relationship FOREIGN KEY (hedging_relationship_id) REFERENCES hedging_relationship(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_inventory_stock_card_item') THEN
            ALTER TABLE inventory_stock_card ADD CONSTRAINT fk_inventory_stock_card_item FOREIGN KEY (item_id) REFERENCES inventory_item(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_report_schedule_definition') THEN
            ALTER TABLE report_schedule ADD CONSTRAINT fk_report_schedule_definition FOREIGN KEY (report_definition_id) REFERENCES report_definition(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_sales_invoice_customer') THEN
            ALTER TABLE sales_invoice ADD CONSTRAINT fk_sales_invoice_customer FOREIGN KEY (customer_id) REFERENCES customer(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_stock_opname_warehouse') THEN
            ALTER TABLE stock_opname ADD CONSTRAINT fk_stock_opname_warehouse FOREIGN KEY (warehouse_id) REFERENCES warehouse(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_payslip_employee') THEN
            ALTER TABLE payslip ADD CONSTRAINT fk_payslip_employee FOREIGN KEY (employee_id) REFERENCES employee(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_umkm_profile_legal_entity') THEN
            ALTER TABLE umkm_profile ADD CONSTRAINT fk_umkm_profile_legal_entity FOREIGN KEY (legal_entity_id) REFERENCES legal_entity(id);
        END IF;
    END $$;
    """)

def downgrade() -> None:
    # Drop all tables created in this migration (reverse order)
    op.execute("DROP TABLE IF EXISTS aml_suspicious_transaction CASCADE;")
    op.execute("DROP TABLE IF EXISTS aml_risk_score CASCADE;")
    op.execute("DROP TABLE IF EXISTS umkm_profile CASCADE;")
    op.execute("DROP TABLE IF EXISTS umkm_business_profile CASCADE;")
    op.execute("DROP TABLE IF EXISTS stock_opname_line CASCADE;")
    op.execute("DROP TABLE IF EXISTS stock_opname CASCADE;")
    op.execute("DROP TABLE IF EXISTS fixed_asset_schedule CASCADE;")
    op.execute("DROP TABLE IF EXISTS hash_chain CASCADE;")
    op.execute("DROP TABLE IF EXISTS snapshot_store CASCADE;")
    op.execute("DROP TABLE IF EXISTS sales_invoice CASCADE;")
    op.execute("DROP TABLE IF EXISTS report_output CASCADE;")
    op.execute("DROP TABLE IF EXISTS report_schedule CASCADE;")
    op.execute("DROP TABLE IF EXISTS report_definition CASCADE;")
    op.execute("DROP TABLE IF EXISTS projection_checkpoint CASCADE;")
    op.execute("DROP TABLE IF EXISTS payslip CASCADE;")
    op.execute("DROP TABLE IF EXISTS payroll_payslip CASCADE;")
    op.execute("DROP TABLE IF EXISTS outbox_checkpoint CASCADE;")
    op.execute("DROP TABLE IF EXISTS outbox CASCADE;")
    op.execute("DROP TABLE IF EXISTS manufacturing_cost_card CASCADE;")
    op.execute("DROP TABLE IF EXISTS manufacturing_work_order CASCADE;")
    op.execute("DROP TABLE IF EXISTS stock_card CASCADE;")
    op.execute("DROP TABLE IF EXISTS inventory_stock_card CASCADE;")
    op.execute("DROP TABLE IF EXISTS intangible_revaluation CASCADE;")
    op.execute("DROP TABLE IF EXISTS impairment_test CASCADE;")
    op.execute("DROP TABLE IF EXISTS hedged_item CASCADE;")
    op.execute("DROP TABLE IF EXISTS hedge_effectiveness_test CASCADE;")
    op.execute("DROP TABLE IF EXISTS goodwill_impairment CASCADE;")
    op.execute("DROP TABLE IF EXISTS goodwill CASCADE;")
    op.execute("DROP TABLE IF EXISTS ledger_entry CASCADE;")
    op.execute("DROP TABLE IF EXISTS general_ledger CASCADE;")
    op.execute("DROP TABLE IF EXISTS exchange_rate CASCADE;")
    op.execute("DROP TABLE IF EXISTS dead_letter_events CASCADE;")
    op.execute("DROP TABLE IF EXISTS coretax_faktur_line CASCADE;")
    op.execute("DROP TABLE IF EXISTS coretax_submission_log CASCADE;")
    op.execute("DROP TABLE IF EXISTS coretax_spt CASCADE;")
    op.execute("DROP TABLE IF EXISTS coretax_emeterai CASCADE;")
    op.execute("DROP TABLE IF EXISTS coretax_bupot CASCADE;")
    op.execute("DROP TABLE IF EXISTS coretax_ntpn CASCADE;")
    op.execute("DROP TABLE IF EXISTS coretax_nsfp CASCADE;")
    op.execute("DROP TABLE IF EXISTS consolidation_group_member CASCADE;")
    op.execute("DROP TABLE IF EXISTS consolidation_group CASCADE;")
    op.execute("DROP TABLE IF EXISTS legal_entity_branch CASCADE;")
    op.execute("DROP TABLE IF EXISTS company_entity CASCADE;")
    op.execute("DROP TABLE IF EXISTS budget_actual CASCADE;")
    op.execute("DROP TABLE IF EXISTS budget CASCADE;")
    op.execute("DROP TABLE IF EXISTS bank_reconciliation_items CASCADE;")
    op.execute("DROP TABLE IF EXISTS bank_reconciliations CASCADE;")
    op.execute("DROP TABLE IF EXISTS bank_reconciliation CASCADE;")
    op.execute("DROP TABLE IF EXISTS audit_event CASCADE;")
    op.execute("DROP TABLE IF EXISTS disposal CASCADE;")
    op.execute("DROP TABLE IF EXISTS revaluation CASCADE;")
    op.execute("DROP TABLE IF EXISTS asset_categories CASCADE;")
    op.execute("DROP TABLE IF EXISTS asset_category CASCADE;")
    op.execute("DROP TABLE IF EXISTS approval_rule CASCADE;")
    op.execute("DROP TABLE IF EXISTS approval_request CASCADE;")