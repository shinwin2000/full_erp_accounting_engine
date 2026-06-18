"""partition ledger_entry and journal_line by fiscal_year (range partitioning)

Revision ID: 0033
Revises: 0032
Create Date: 2026-05-30 14:15:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0033'
down_revision = '0032'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Create partitioned tables (if not already)
    op.execute("""
    CREATE TABLE IF NOT EXISTS ledger_entry_partitioned (
        id UUID DEFAULT gen_random_uuid(),
        legal_entity_id UUID NOT NULL,
        journal_id UUID NOT NULL,
        journal_line_id UUID NOT NULL,
        account_id UUID NOT NULL,
        account_code VARCHAR(30) NOT NULL,
        debit_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
        credit_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
        posting_date DATE NOT NULL,
        fiscal_year INTEGER NOT NULL,
        period INTEGER NOT NULL,
        description TEXT,
        reference_number VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT now(),
        created_by UUID NOT NULL,
        hash_link VARCHAR(128) NOT NULL,
        version INTEGER DEFAULT 1,
        PRIMARY KEY (id, fiscal_year)
    ) PARTITION BY RANGE (fiscal_year);
    """)
    # Create partitions for years 2020-2030
    start_year = 2020
    end_year = 2030
    for year in range(start_year, end_year + 1):
        next_year = year + 1
        op.execute(f"""
        CREATE TABLE IF NOT EXISTS ledger_entry_{year} PARTITION OF ledger_entry_partitioned
        FOR VALUES FROM ({year}) TO ({next_year});
        """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_ledger_partitioned_entity_date ON ledger_entry_partitioned (legal_entity_id, posting_date);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ledger_partitioned_account ON ledger_entry_partitioned (account_id, fiscal_year, period);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ledger_partitioned_journal ON ledger_entry_partitioned (journal_id);")

    # Journal line partitioned
    op.execute("""
    CREATE TABLE IF NOT EXISTS journal_line_partitioned (
        id UUID DEFAULT gen_random_uuid(),
        journal_header_id UUID NOT NULL,
        line_number INTEGER NOT NULL,
        account_id UUID NOT NULL,
        account_code VARCHAR(30) NOT NULL,
        debit_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
        credit_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
        currency_code VARCHAR(3) NOT NULL DEFAULT 'IDR',
        exchange_rate NUMERIC(12,6) DEFAULT 1,
        description TEXT,
        cost_center VARCHAR(50),
        department_id UUID,
        project_id UUID,
        posting_date DATE NOT NULL,
        fiscal_year INTEGER NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now(),
        created_by UUID NOT NULL,
        version INTEGER DEFAULT 1,
        PRIMARY KEY (id, fiscal_year)
    ) PARTITION BY RANGE (fiscal_year);
    """)
    for year in range(start_year, end_year + 1):
        next_year = year + 1
        op.execute(f"""
        CREATE TABLE IF NOT EXISTS journal_line_{year} PARTITION OF journal_line_partitioned
        FOR VALUES FROM ({year}) TO ({next_year});
        """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_journal_line_partitioned_header ON journal_line_partitioned (journal_header_id, fiscal_year);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_journal_line_partitioned_account ON journal_line_partitioned (account_id, fiscal_year);")

    # Trigger to set fiscal_year automatically
    op.execute("DROP FUNCTION IF EXISTS set_fiscal_year();")
    op.execute("""
    CREATE OR REPLACE FUNCTION set_fiscal_year()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.fiscal_year := EXTRACT(YEAR FROM NEW.posting_date);
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_ledger_entry_fiscal_year ON ledger_entry_partitioned;")
    op.execute("CREATE TRIGGER trg_ledger_entry_fiscal_year BEFORE INSERT ON ledger_entry_partitioned FOR EACH ROW EXECUTE FUNCTION set_fiscal_year();")
    op.execute("DROP TRIGGER IF EXISTS trg_journal_line_fiscal_year ON journal_line_partitioned;")
    op.execute("CREATE TRIGGER trg_journal_line_fiscal_year BEFORE INSERT ON journal_line_partitioned FOR EACH ROW EXECUTE FUNCTION set_fiscal_year();")

def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_ledger_entry_fiscal_year ON ledger_entry_partitioned;")
    op.execute("DROP TRIGGER IF EXISTS trg_journal_line_fiscal_year ON journal_line_partitioned;")
    op.execute("DROP FUNCTION IF EXISTS set_fiscal_year();")
    for year in range(2020, 2031):
        op.execute(f"DROP TABLE IF EXISTS ledger_entry_{year};")
        op.execute(f"DROP TABLE IF EXISTS journal_line_{year};")
    op.execute("DROP TABLE IF EXISTS ledger_entry_partitioned;")
    op.execute("DROP TABLE IF EXISTS journal_line_partitioned;")