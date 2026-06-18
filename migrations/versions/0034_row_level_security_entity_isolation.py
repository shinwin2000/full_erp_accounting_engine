"""enable row-level security for multi-tenant isolation (legal entity)

Revision ID: 0034
Revises: 0033
Create Date: 2026-05-30 14:30:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = '0034'
down_revision = '0033'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS app;")

    # Create function to get current legal entity IDs from session setting
    op.execute("""
    CREATE OR REPLACE FUNCTION get_current_legal_entity_ids()
    RETURNS UUID[] AS $$
    DECLARE
        setting_text TEXT;
        result_ids UUID[] := ARRAY[]::UUID[];
    BEGIN
        BEGIN
            setting_text := current_setting('app.current_legal_entity_ids', true);
        EXCEPTION WHEN OTHERS THEN
            setting_text := NULL;
        END;
        IF setting_text IS NOT NULL AND setting_text != '' THEN
            SELECT ARRAY(SELECT DISTINCT uuid::UUID FROM unnest(string_to_array(setting_text, ',')) AS u WHERE u ~ '^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$') INTO result_ids;
        END IF;
        RETURN result_ids;
    END;
    $$ LANGUAGE plpgsql STABLE;
    """)

    # Enable RLS and create policies for all tables with legal_entity_id
    main_tables = [
        'legal_entity', 'account', 'journal_header', 'journal_line_partitioned',
        'ledger_entry_partitioned', 'ar_invoice', 'ap_invoice', 'inventory_item',
        'fixed_asset', 'bank_account', 'customer', 'supplier', 'employee',
        'purchase_order', 'sales_order', 'work_order', 'project',
        'tax_transaction', 'coretax_faktur_keluaran', 'coretax_faktur_masukan',
        'event_store', 'outbox', 'hash_chain', 'warehouse',
        'intangible_asset', 'payroll_run', 'payroll_detail', 'salary_structure',
        'salary_component', 'payroll_adjustment', 'cost_card', 'bill_of_materials',
        'routing', 'work_in_process', 'depreciation_schedule', 'amortization_schedule',
        'goods_receipt_note', 'delivery_order', 'ap_credit_note', 'ar_credit_note',
        'ap_payment', 'ar_payment', 'ppn_settlement', 'pph_withholding_summary',
        'projection_gl_ledger', 'projection_trial_balance', 'projection_ar_aging',
        'projection_ap_aging', 'projection_ppn_settlement', 'projection_pph_summary',
        'projection_coretax_dashboard', 'projection_trend_12month',
        'projection_variance_analysis', 'projection_profitability_segment',
        'projection_financial_ratios', 'projection_kpi_alerter'
    ]
    for table in main_tables:
        column = 'id' if table == 'legal_entity' else 'legal_entity_id'
        op.execute(f"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = '{table}' AND column_name = '{column}') THEN
                EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', '{table}');
                EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', '{table}');
                EXECUTE format('CREATE POLICY select_entity_isolation_{table} ON %I FOR SELECT USING ({column} = ANY(get_current_legal_entity_ids()) OR current_setting(''app.is_superuser'', true) = ''true'')', '{table}');
                EXECUTE format('CREATE POLICY modify_entity_isolation_{table} ON %I FOR ALL USING ({column} = ANY(get_current_legal_entity_ids())) WITH CHECK ({column} = ANY(get_current_legal_entity_ids()))', '{table}');
            END IF;
        END $$;
        """)

    # Special policy for iam_user
    op.execute("""
    DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'iam_user' AND column_name = 'legal_entity_id') THEN
            EXECUTE 'CREATE POLICY select_user_isolation ON iam_user FOR SELECT USING (legal_entity_id = ANY(get_current_legal_entity_ids()) OR id = current_setting(''app.current_user_id'', true)::UUID OR current_setting(''app.is_superuser'', true) = ''true'')';
        END IF;
    END $$;
    """)

    # Function to set tenant context from application
    op.execute("""
    CREATE OR REPLACE FUNCTION app.set_tenant_context(p_legal_entity_ids TEXT, p_user_id UUID, p_is_superuser BOOLEAN DEFAULT FALSE)
    RETURNS VOID AS $$
    BEGIN
        PERFORM set_config('app.current_legal_entity_ids', p_legal_entity_ids, false);
        PERFORM set_config('app.current_user_id', p_user_id::TEXT, false);
        PERFORM set_config('app.is_superuser', CASE WHEN p_is_superuser THEN 'true' ELSE 'false' END, false);
    END;
    $$ LANGUAGE plpgsql SECURITY DEFINER;
    """)

def downgrade() -> None:
    # Drop policies
    tables = ['legal_entity', 'account', 'journal_header', 'journal_line_partitioned',
              'ledger_entry_partitioned', 'ar_invoice', 'ap_invoice', 'inventory_item',
              'fixed_asset', 'bank_account', 'customer', 'supplier', 'employee',
              'purchase_order', 'sales_order', 'work_order', 'project',
              'tax_transaction', 'coretax_faktur_keluaran', 'coretax_faktur_masukan',
              'event_store', 'outbox', 'hash_chain', 'warehouse', 'intangible_asset',
              'payroll_run', 'payroll_detail', 'salary_structure', 'salary_component',
              'payroll_adjustment', 'cost_card', 'bill_of_materials', 'routing',
              'work_in_process', 'depreciation_schedule', 'amortization_schedule',
              'goods_receipt_note', 'delivery_order', 'ap_credit_note', 'ar_credit_note',
              'ap_payment', 'ar_payment', 'ppn_settlement', 'pph_withholding_summary',
              'projection_gl_ledger', 'projection_trial_balance', 'projection_ar_aging',
              'projection_ap_aging', 'projection_ppn_settlement', 'projection_pph_summary',
              'projection_coretax_dashboard', 'projection_trend_12month',
              'projection_variance_analysis', 'projection_profitability_segment',
              'projection_financial_ratios', 'projection_kpi_alerter']
    for table in tables:
        op.execute(f"DROP POLICY IF EXISTS select_entity_isolation_{table} ON {table};")
        op.execute(f"DROP POLICY IF EXISTS modify_entity_isolation_{table} ON {table};")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS select_user_isolation ON iam_user;")
    op.execute("DROP FUNCTION IF EXISTS app.set_tenant_context(TEXT, UUID, BOOLEAN);")
    op.execute("DROP FUNCTION IF EXISTS get_current_legal_entity_ids();")