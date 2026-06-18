"""create event_store, aggregate_snapshot tables with append-only triggers

Revision ID: 0030
Revises: 0029
Create Date: 2026-05-30 13:30:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP

revision: str = '0030'
down_revision = '0029'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Create event_store table (append-only)
    op.execute("""
    CREATE TABLE IF NOT EXISTS event_store (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        aggregate_type VARCHAR(100) NOT NULL,
        aggregate_id UUID NOT NULL,
        version BIGINT NOT NULL,
        event_type VARCHAR(200) NOT NULL,
        event_data JSONB NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}',
        hash_prev VARCHAR(128),
        hash_current VARCHAR(128) NOT NULL,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        recorded_by UUID NOT NULL,
        is_void BOOLEAN NOT NULL DEFAULT false,
        void_reason TEXT,
        voided_at TIMESTAMPTZ,
        voided_by UUID
    );
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_event_store_aggregate ON event_store (aggregate_type, aggregate_id, version);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_event_store_aggregate_latest ON event_store (aggregate_type, aggregate_id, version DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_event_store_event_type ON event_store (event_type);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_event_store_recorded_at ON event_store (recorded_at);")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_event_store_hash_current ON event_store (hash_current);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_event_store_aggregate_void ON event_store (aggregate_type, aggregate_id, is_void);")

    # Append-only trigger functions (from migration 0010)
    op.execute("""
    CREATE OR REPLACE FUNCTION prevent_event_store_modification()
    RETURNS TRIGGER AS $$
    BEGIN
        IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION 'UPDATE not allowed on event_store (append-only)';
        ELSIF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'DELETE not allowed on event_store (append-only)';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)

    op.execute("""
    CREATE OR REPLACE FUNCTION log_modification_attempt()
    RETURNS TRIGGER AS $$
    BEGIN
        INSERT INTO audit.audit_log (event_type, table_name, operation, attempted_data, error_message)
        VALUES ('security_violation', TG_TABLE_NAME, TG_OP, ROW(OLD.*, NEW.*)::TEXT, 'Attempted to modify append-only table');
        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql;
    """)

    # Apply triggers
    op.execute("DROP TRIGGER IF EXISTS trigger_prevent_update ON event_store;")
    op.execute("CREATE TRIGGER trigger_prevent_update BEFORE UPDATE ON event_store FOR EACH ROW EXECUTE FUNCTION prevent_event_store_modification();")
    op.execute("DROP TRIGGER IF EXISTS trigger_prevent_delete ON event_store;")
    op.execute("CREATE TRIGGER trigger_prevent_delete BEFORE DELETE ON event_store FOR EACH ROW EXECUTE FUNCTION prevent_event_store_modification();")
    op.execute("DROP TRIGGER IF EXISTS trigger_log_modification ON event_store;")
    op.execute("CREATE TRIGGER trigger_log_modification BEFORE UPDATE OR DELETE ON event_store FOR EACH ROW EXECUTE FUNCTION log_modification_attempt();")

    # Aggregate snapshot table
    op.execute("""
    CREATE TABLE IF NOT EXISTS aggregate_snapshot (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        aggregate_type VARCHAR(100) NOT NULL,
        aggregate_id UUID NOT NULL,
        version BIGINT NOT NULL,
        snapshot_data JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_aggregate_snapshot ON aggregate_snapshot (aggregate_type, aggregate_id, version);")

def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trigger_prevent_update ON event_store;")
    op.execute("DROP TRIGGER IF EXISTS trigger_prevent_delete ON event_store;")
    op.execute("DROP TRIGGER IF EXISTS trigger_log_modification ON event_store;")
    op.execute("DROP FUNCTION IF EXISTS prevent_event_store_modification() CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS log_modification_attempt() CASCADE;")
    op.execute("DROP TABLE IF EXISTS aggregate_snapshot;")
    op.execute("DROP TABLE IF EXISTS event_store;")