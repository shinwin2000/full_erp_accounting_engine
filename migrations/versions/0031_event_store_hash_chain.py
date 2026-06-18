"""create hash_chain and integrity_check_result tables for tamper detection

Revision ID: 0031
Revises: 0030
Create Date: 2026-05-30 13:45:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP

revision: str = '0031'
down_revision = '0030'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS hash_chain (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
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
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_hash_chain_chain_seq ON hash_chain (chain_type, chain_id, sequence);")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_hash_chain_current_hash ON hash_chain (current_hash);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_hash_chain_timestamp ON hash_chain (timestamp);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS integrity_check_result (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        check_started_at TIMESTAMPTZ NOT NULL,
        check_completed_at TIMESTAMPTZ NOT NULL,
        chain_type VARCHAR(50) NOT NULL,
        chain_id_start UUID,
        chain_id_end UUID,
        total_entries_checked BIGINT NOT NULL,
        total_entries_valid BIGINT NOT NULL,
        total_entries_invalid BIGINT NOT NULL,
        invalid_chain_ids JSONB,
        status VARCHAR(20) NOT NULL DEFAULT 'PASSED',
        report_path VARCHAR(500),
        triggered_by UUID NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_integrity_check_time ON integrity_check_result (check_started_at);")

    op.execute("""
    CREATE OR REPLACE FUNCTION verify_hash_chain(p_chain_type TEXT, p_chain_id UUID)
    RETURNS TABLE(sequence BIGINT, is_valid BOOLEAN, computed_hash TEXT, stored_hash TEXT) AS $$
    DECLARE
        rec RECORD;
        prev_hash_calc TEXT := NULL;
        current_hash_calc TEXT;
    BEGIN
        FOR rec IN
            SELECT sequence, prev_hash, current_hash, payload_hash
            FROM hash_chain
            WHERE chain_type = p_chain_type AND chain_id = p_chain_id
            ORDER BY sequence ASC
        LOOP
            current_hash_calc := encode(sha3_256((rec.payload_hash || COALESCE(prev_hash_calc, ''))::bytea), 'hex');
            is_valid := (current_hash_calc = rec.current_hash);
            computed_hash := current_hash_calc;
            stored_hash := rec.current_hash;
            sequence := rec.sequence;
            prev_hash_calc := rec.current_hash;
            RETURN NEXT;
        END LOOP;
    END;
    $$ LANGUAGE plpgsql STABLE;
    """)

def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS verify_hash_chain(TEXT, UUID);")
    op.execute("DROP TABLE IF EXISTS integrity_check_result;")
    op.execute("DROP TABLE IF EXISTS hash_chain;")