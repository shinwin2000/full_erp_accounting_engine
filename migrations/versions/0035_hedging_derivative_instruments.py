"""create hedging_relationship, derivative_instrument, fair_value_hierarchy, hedge_effectiveness_test tables

Revision ID: 0035
Revises: 0034
Create Date: 2026-05-30 14:45:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP

revision: str = '0035abcd'
down_revision = '0034abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # ========================================================================
    # 1. Tabel hedging_relationship
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS hedging_relationship (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        legal_entity_id UUID NOT NULL,
        hedge_type VARCHAR(30) NOT NULL,
        hedge_status VARCHAR(30) NOT NULL DEFAULT 'DESIGNATED',
        designation_date DATE NOT NULL,
        effective_start_date DATE NOT NULL,
        effective_end_date DATE,
        hedged_item_type VARCHAR(50) NOT NULL,
        hedged_item_id UUID NOT NULL,
        hedged_item_description TEXT NOT NULL,
        hedging_instrument_type VARCHAR(50) NOT NULL,
        hedging_instrument_id UUID NOT NULL,
        notional_amount NUMERIC(18,2) NOT NULL,
        currency_code VARCHAR(3) NOT NULL DEFAULT 'IDR',
        hedge_ratio NUMERIC(10,6) NOT NULL DEFAULT 1.0,
        ineffectiveness_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
        ineffectiveness_reason TEXT,
        documentation_path VARCHAR(500),
        version INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_hedging_relationship_entity_status ON hedging_relationship (legal_entity_id, hedge_status);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_hedging_relationship_effective ON hedging_relationship (effective_start_date, effective_end_date);")

    # ========================================================================
    # 2. Tabel derivative_instrument
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS derivative_instrument (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        legal_entity_id UUID NOT NULL,
        instrument_code VARCHAR(50) NOT NULL UNIQUE,
        instrument_type VARCHAR(30) NOT NULL,
        counterparty_id UUID NOT NULL,
        underlying_asset VARCHAR(100) NOT NULL,
        notional_amount NUMERIC(18,2) NOT NULL,
        currency_code VARCHAR(3) NOT NULL,
        settlement_date DATE,
        maturity_date DATE NOT NULL,
        strike_price NUMERIC(18,6),
        premium_paid NUMERIC(18,2) NOT NULL DEFAULT 0,
        fair_value_at_reporting NUMERIC(18,2) NOT NULL DEFAULT 0,
        valuation_method VARCHAR(50) NOT NULL DEFAULT 'MARK_TO_MARKET',
        is_designated_hedge BOOLEAN NOT NULL DEFAULT false,
        hedging_relationship_id UUID,
        status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
        version INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_derivative_instrument_code ON derivative_instrument (instrument_code);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_derivative_instrument_counterparty ON derivative_instrument (counterparty_id);")

    # ========================================================================
    # 3. Tabel fair_value_hierarchy
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS fair_value_hierarchy (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        financial_instrument_id UUID NOT NULL,
        instrument_type VARCHAR(30) NOT NULL,
        valuation_date DATE NOT NULL,
        fair_value NUMERIC(18,2) NOT NULL,
        level_input INTEGER NOT NULL,
        level_description TEXT,
        unobservable_inputs JSONB,
        sensitivity_analysis JSONB,
        valuer_name VARCHAR(200),
        valuation_report_path VARCHAR(500),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_fair_value_hierarchy_instrument_date ON fair_value_hierarchy (financial_instrument_id, valuation_date);")

    # ========================================================================
    # 4. Tabel hedge_effectiveness_test
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS hedge_effectiveness_test (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
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
    op.execute("CREATE INDEX IF NOT EXISTS ix_hedge_effectiveness_test_relationship ON hedge_effectiveness_test (hedging_relationship_id, test_date);")

    # ========================================================================
    # 5. Foreign keys (DO block untuk kompatibilitas)
    # ========================================================================
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_derivative_hedge_relationship') THEN
            EXECUTE 'ALTER TABLE derivative_instrument ADD CONSTRAINT fk_derivative_hedge_relationship FOREIGN KEY (hedging_relationship_id) REFERENCES hedging_relationship(id)';
        END IF;
    END;
    $$;
    """)

    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_effectiveness_hedge') THEN
            EXECUTE 'ALTER TABLE hedge_effectiveness_test ADD CONSTRAINT fk_effectiveness_hedge FOREIGN KEY (hedging_relationship_id) REFERENCES hedging_relationship(id)';
        END IF;
    END;
    $$;
    """)

    # ========================================================================
    # 6. Trigger untuk update timestamp
    # ========================================================================
    op.execute("""
    CREATE OR REPLACE FUNCTION update_fair_value_auto()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = now();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_derivative_update ON derivative_instrument;")
    op.execute("CREATE TRIGGER trg_derivative_update BEFORE UPDATE ON derivative_instrument FOR EACH ROW EXECUTE FUNCTION update_fair_value_auto();")

def downgrade() -> None:
    # Hapus trigger
    op.execute("DROP TRIGGER IF EXISTS trg_derivative_update ON derivative_instrument;")
    op.execute("DROP FUNCTION IF EXISTS update_fair_value_auto();")

    # Hapus foreign keys
    op.execute("ALTER TABLE derivative_instrument DROP CONSTRAINT IF EXISTS fk_derivative_hedge_relationship;")
    op.execute("ALTER TABLE hedge_effectiveness_test DROP CONSTRAINT IF EXISTS fk_effectiveness_hedge;")

    # Hapus tabel (urutan terbalik dari pembuatan)
    op.execute("DROP TABLE IF EXISTS hedge_effectiveness_test;")
    op.execute("DROP TABLE IF EXISTS fair_value_hierarchy;")
    op.execute("DROP TABLE IF EXISTS derivative_instrument;")
    op.execute("DROP TABLE IF EXISTS hedging_relationship;")