"""create saga_instance, saga_step_log, saga_lock, saga_event tables

Revision ID: 0038
Revises: 0037
Create Date: 2026-05-30 15:30:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP

revision: str = '0038'
down_revision = '0037'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS saga_instance (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
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
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_saga_instance_type_correlation ON saga_instance (saga_type, correlation_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_saga_instance_status ON saga_instance (status, last_heartbeat_at);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_saga_instance_entity ON saga_instance (legal_entity_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS saga_step_log (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        saga_instance_id UUID NOT NULL,
        step_index INTEGER NOT NULL,
        step_name VARCHAR(100) NOT NULL,
        action_type VARCHAR(20) NOT NULL,
        status VARCHAR(20) NOT NULL,
        input_payload JSONB,
        output_payload JSONB,
        error_message TEXT,
        retry_count INTEGER NOT NULL DEFAULT 0,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        duration_ms INTEGER
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_saga_step_log_instance ON saga_step_log (saga_instance_id, step_index);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS saga_lock (
        saga_type VARCHAR(100) NOT NULL,
        correlation_id VARCHAR(200) NOT NULL,
        lock_acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        lock_expires_at TIMESTAMPTZ NOT NULL,
        locked_by VARCHAR(100) NOT NULL,
        PRIMARY KEY (saga_type, correlation_id)
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_saga_lock_expiry ON saga_lock (lock_expires_at);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS saga_event (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        saga_instance_id UUID,
        event_type VARCHAR(100) NOT NULL,
        payload JSONB NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        processed_at TIMESTAMPTZ
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_saga_event_status ON saga_event (status, created_at);")

    op.execute("""
    CREATE OR REPLACE FUNCTION cleanup_stale_saga_instances()
    RETURNS INTEGER AS $$
    DECLARE
        stale_count INTEGER;
    BEGIN
        UPDATE saga_instance
        SET status = 'TIMEOUT', failed_at = now(), timeout_at = now()
        WHERE status IN ('STARTED', 'COMPENSATING')
          AND last_heartbeat_at < NOW() - INTERVAL '30 minutes'
          AND timeout_at IS NULL;
        GET DIAGNOSTICS stale_count = ROW_COUNT;
        RETURN stale_count;
    END;
    $$ LANGUAGE plpgsql;
    """)

    op.execute("""
    CREATE OR REPLACE FUNCTION update_saga_heartbeat()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.last_heartbeat_at = now();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_saga_heartbeat ON saga_instance;")
    op.execute("CREATE TRIGGER trg_saga_heartbeat BEFORE UPDATE ON saga_instance FOR EACH ROW EXECUTE FUNCTION update_saga_heartbeat();")

def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_saga_heartbeat ON saga_instance;")
    op.execute("DROP FUNCTION IF EXISTS cleanup_stale_saga_instances();")
    op.execute("DROP FUNCTION IF EXISTS update_saga_heartbeat();")
    op.execute("DROP TABLE IF EXISTS saga_event;")
    op.execute("DROP TABLE IF EXISTS saga_lock;")
    op.execute("DROP TABLE IF EXISTS saga_step_log;")
    op.execute("DROP TABLE IF EXISTS saga_instance;")