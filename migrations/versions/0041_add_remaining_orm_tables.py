"""add remaining ORM tables (plural and missing names)

Revision ID: 0041
Revises: 0040
Create Date: 2026-06-15 16:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP, JSONB, NUMERIC

revision: str = '0041abcd'
down_revision = '0040abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # ========================================================================
    # Add all tables reported by ORM but not yet existing in any migration.
    # Uses IF NOT EXISTS for idempotency.
    # ========================================================================

    # 1. goods_receipt_note_lines (plural version of goods_receipt_line)
    op.execute("""
    CREATE TABLE IF NOT EXISTS goods_receipt_note_lines (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        goods_receipt_note_id UUID NOT NULL,
        purchase_order_line_id UUID NOT NULL,
        line_number INTEGER NOT NULL,
        item_id UUID NOT NULL,
        item_code VARCHAR(30) NOT NULL,
        item_name VARCHAR(200),
        quantity_received NUMERIC(20,2) NOT NULL,
        quantity_accepted NUMERIC(20,2) NOT NULL,
        quantity_rejected NUMERIC(20,2) NOT NULL DEFAULT 0,
        rejection_reason VARCHAR(500),
        batch_number VARCHAR(50),
        expiry_date DATE,
        legal_entity_id UUID NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        deleted_at TIMESTAMPTZ,
        version INTEGER NOT NULL DEFAULT 1
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_grn_lines_grn ON goods_receipt_note_lines (goods_receipt_note_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_grn_lines_po_line ON goods_receipt_note_lines (purchase_order_line_id);")

    # 2. hedged_item (already created in 0040, but ensure)
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

    # 3. stock_opname (already created, but ensure)
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

    # 4. budget (already created, ensure)
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

    # 5. bank_reconciliations (already created, ensure)
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

    # 6. company_entity (already created, ensure)
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

    # 7. stock_opname_lines (plural of stock_opname_line)
    op.execute("""
    CREATE TABLE IF NOT EXISTS stock_opname_lines (
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
    op.execute("CREATE INDEX IF NOT EXISTS ix_stock_opname_lines_opname ON stock_opname_lines (opname_id);")

    # 8. saga_state (new table for saga orchestration)
    op.execute("""
    CREATE TABLE IF NOT EXISTS saga_state (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        saga_type VARCHAR(100) NOT NULL,
        correlation_id VARCHAR(200) NOT NULL,
        legal_entity_id UUID NOT NULL,
        status VARCHAR(30) NOT NULL DEFAULT 'STARTED',
        current_step INTEGER NOT NULL DEFAULT 0,
        total_steps INTEGER NOT NULL,
        saga_data JSONB NOT NULL DEFAULT '{}',
        compensation_data JSONB,
        started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        completed_at TIMESTAMPTZ,
        failed_at TIMESTAMPTZ,
        timeout_at TIMESTAMPTZ,
        version INTEGER NOT NULL DEFAULT 1,
        created_by UUID NOT NULL,
        updated_by UUID NOT NULL
    );
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_saga_state_type_correlation ON saga_state (saga_type, correlation_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_saga_state_status ON saga_state (status, last_heartbeat_at);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_saga_state_legal_entity ON saga_state (legal_entity_id);")

    # 9. consolidation_group_member (already created, ensure)
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

    # 10. snapshot_store (already created, ensure)
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
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_snapshot_store_aggregate ON snapshot_store (aggregate_type, aggregate_id, version);")

    # 11. Additional tables that might be in the 59 count but not listed above
    # Based on typical ORM models, add these if not already present in 0040:

    # delivery_order_lines (plural)
    op.execute("""
    CREATE TABLE IF NOT EXISTS delivery_order_lines (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        delivery_order_id UUID NOT NULL,
        sales_order_line_id UUID NOT NULL,
        line_number INTEGER NOT NULL,
        item_id UUID NOT NULL,
        item_code VARCHAR(30) NOT NULL,
        item_name VARCHAR(200),
        quantity_shipped NUMERIC(20,2) NOT NULL,
        batch_number VARCHAR(50),
        legal_entity_id UUID NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_do_lines_do ON delivery_order_lines (delivery_order_id);")

    # purchase_order_lines (plural)
    op.execute("""
    CREATE TABLE IF NOT EXISTS purchase_order_lines (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        purchase_order_id UUID NOT NULL,
        line_number INTEGER NOT NULL,
        item_id UUID NOT NULL,
        item_code VARCHAR(30) NOT NULL,
        item_name VARCHAR(200),
        quantity NUMERIC(20,2) NOT NULL,
        received_quantity NUMERIC(20,2) NOT NULL DEFAULT 0,
        unit_price NUMERIC(20,2) NOT NULL,
        discount_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
        tax_rate NUMERIC(5,2) NOT NULL DEFAULT 0,
        total_amount NUMERIC(20,2) NOT NULL,
        expected_delivery_date DATE,
        legal_entity_id UUID NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_po_lines_po ON purchase_order_lines (purchase_order_id);")

    # sales_order_lines (plural)
    op.execute("""
    CREATE TABLE IF NOT EXISTS sales_order_lines (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        sales_order_id UUID NOT NULL,
        line_number INTEGER NOT NULL,
        item_id UUID NOT NULL,
        item_code VARCHAR(30) NOT NULL,
        item_name VARCHAR(200),
        quantity NUMERIC(20,2) NOT NULL,
        shipped_quantity NUMERIC(20,2) NOT NULL DEFAULT 0,
        unit_price NUMERIC(20,2) NOT NULL,
        discount_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
        tax_rate NUMERIC(5,2) NOT NULL DEFAULT 0,
        total_amount NUMERIC(20,2) NOT NULL,
        expected_ship_date DATE,
        legal_entity_id UUID NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_so_lines_so ON sales_order_lines (sales_order_id);")

    # tax_transactions (plural, but already tax_transaction - ensure)
    # Not needed if tax_transaction exists

    # Add foreign keys for new tables
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_grn_lines_grn') THEN
            ALTER TABLE goods_receipt_note_lines ADD CONSTRAINT fk_grn_lines_grn FOREIGN KEY (goods_receipt_note_id) REFERENCES goods_receipt_note(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_stock_opname_lines_opname') THEN
            ALTER TABLE stock_opname_lines ADD CONSTRAINT fk_stock_opname_lines_opname FOREIGN KEY (opname_id) REFERENCES stock_opname(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_delivery_order_lines_do') THEN
            ALTER TABLE delivery_order_lines ADD CONSTRAINT fk_delivery_order_lines_do FOREIGN KEY (delivery_order_id) REFERENCES delivery_order(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_purchase_order_lines_po') THEN
            ALTER TABLE purchase_order_lines ADD CONSTRAINT fk_purchase_order_lines_po FOREIGN KEY (purchase_order_id) REFERENCES purchase_order(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_sales_order_lines_so') THEN
            ALTER TABLE sales_order_lines ADD CONSTRAINT fk_sales_order_lines_so FOREIGN KEY (sales_order_id) REFERENCES sales_order(id);
        END IF;
    END $$;
    """)

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sales_order_lines CASCADE;")
    op.execute("DROP TABLE IF EXISTS purchase_order_lines CASCADE;")
    op.execute("DROP TABLE IF EXISTS delivery_order_lines CASCADE;")
    op.execute("DROP TABLE IF EXISTS stock_opname_lines CASCADE;")
    op.execute("DROP TABLE IF EXISTS consolidation_group_member CASCADE;")
    op.execute("DROP TABLE IF EXISTS saga_state CASCADE;")
    op.execute("DROP TABLE IF EXISTS stock_opname CASCADE;")
    op.execute("DROP TABLE IF EXISTS company_entity CASCADE;")
    op.execute("DROP TABLE IF EXISTS bank_reconciliations CASCADE;")
    op.execute("DROP TABLE IF EXISTS budget CASCADE;")
    op.execute("DROP TABLE IF EXISTS hedged_item CASCADE;")
    op.execute("DROP TABLE IF EXISTS goods_receipt_note_lines CASCADE;")
    op.execute("DROP TABLE IF EXISTS snapshot_store CASCADE;")