"""add final missing ORM tables: umkm_transaction, hedge_instrument, coretax_faktur

Revision ID: 0042
Revises: 0041
Create Date: 2026-06-15 17:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP, JSONB, NUMERIC

revision: str = '0042'
down_revision = '0041'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # ========================================================================
    # 1. umkm_transaction (simplified journal entries for UMKM)
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS umkm_transaction (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        transaction_date DATE NOT NULL,
        description TEXT NOT NULL,
        debit_account_code VARCHAR(20) NOT NULL,
        credit_account_code VARCHAR(20) NOT NULL,
        amount NUMERIC(20,2) NOT NULL,
        tax_id UUID,
        attachment_url VARCHAR(500),
        status VARCHAR(20) NOT NULL DEFAULT 'draft',
        version INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_umkm_transaction_date ON umkm_transaction (transaction_date);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_umkm_transaction_legal_entity ON umkm_transaction (legal_entity_id);")

    # ========================================================================
    # 2. hedge_instrument (derivative instruments for hedge accounting)
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS hedge_instrument (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        instrument_code VARCHAR(50) NOT NULL UNIQUE,
        instrument_type VARCHAR(30) NOT NULL,
        counterparty_id UUID NOT NULL,
        underlying_asset VARCHAR(100) NOT NULL,
        notional_amount NUMERIC(20,2) NOT NULL,
        currency_code VARCHAR(3) NOT NULL,
        settlement_date DATE,
        maturity_date DATE NOT NULL,
        strike_price NUMERIC(18,6),
        premium_paid NUMERIC(20,2) NOT NULL DEFAULT 0,
        fair_value_at_reporting NUMERIC(20,2) NOT NULL DEFAULT 0,
        valuation_method VARCHAR(50) NOT NULL DEFAULT 'MARK_TO_MARKET',
        is_designated_hedge BOOLEAN NOT NULL DEFAULT false,
        hedging_relationship_id UUID,
        status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
        version INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_hedge_instrument_code ON hedge_instrument (instrument_code);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_hedge_instrument_counterparty ON hedge_instrument (counterparty_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_hedge_instrument_legal_entity ON hedge_instrument (legal_entity_id);")

    # ========================================================================
    # 3. coretax_faktur (generic faktur table – if ORM expects this name)
    #    Note: We already have coretax_faktur_keluaran and coretax_faktur_masukan.
    #    This table may be a superclass or a separate view; we create it with
    #    minimal required columns.
    # ========================================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS coretax_faktur (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        faktur_number VARCHAR(30) NOT NULL UNIQUE,
        faktur_date DATE NOT NULL,
        counterparty_npwp VARCHAR(20) NOT NULL,
        counterparty_name VARCHAR(200) NOT NULL,
        dpp_total NUMERIC(18,2) NOT NULL,
        ppn_total NUMERIC(18,2) NOT NULL,
        ppnbm_total NUMERIC(18,2),
        tarif_ppn NUMERIC(5,2) NOT NULL DEFAULT 11.00,
        status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
        approval_code VARCHAR(50),
        rejection_reason TEXT,
        submitted_at TIMESTAMPTZ,
        approved_at TIMESTAMPTZ,
        voided_at TIMESTAMPTZ,
        source_document_type VARCHAR(50),
        source_document_id UUID,
        hash_link VARCHAR(128),
        version INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        updated_by UUID NOT NULL,
        is_deleted BOOLEAN NOT NULL DEFAULT false
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_coretax_faktur_legal_entity ON coretax_faktur (legal_entity_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_coretax_faktur_number ON coretax_faktur (faktur_number);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_coretax_faktur_status ON coretax_faktur (status);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_coretax_faktur_date ON coretax_faktur (faktur_date);")

    # Foreign keys (optional – adjust if needed)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_umkm_transaction_legal_entity') THEN
            ALTER TABLE umkm_transaction ADD CONSTRAINT fk_umkm_transaction_legal_entity FOREIGN KEY (legal_entity_id) REFERENCES legal_entity(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_hedge_instrument_legal_entity') THEN
            ALTER TABLE hedge_instrument ADD CONSTRAINT fk_hedge_instrument_legal_entity FOREIGN KEY (legal_entity_id) REFERENCES legal_entity(id);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_coretax_faktur_legal_entity') THEN
            ALTER TABLE coretax_faktur ADD CONSTRAINT fk_coretax_faktur_legal_entity FOREIGN KEY (legal_entity_id) REFERENCES legal_entity(id);
        END IF;
    END $$;
    """)

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS coretax_faktur CASCADE;")
    op.execute("DROP TABLE IF EXISTS hedge_instrument CASCADE;")
    op.execute("DROP TABLE IF EXISTS umkm_transaction CASCADE;")