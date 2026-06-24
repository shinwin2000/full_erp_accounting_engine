"""create outbox, outbox_relay_checkpoint, outbox_dead_letter tables

Revision ID: 0032
Revises: 0031
Create Date: 2026-05-30 14:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP

revision: str = '0032abcd'
down_revision = '0031abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS outbox (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
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
    CREATE TABLE IF NOT EXISTS outbox_relay_checkpoint (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        consumer_group VARCHAR(200) NOT NULL UNIQUE,
        last_processed_id UUID NOT NULL,
        last_processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        processed_by VARCHAR(100) NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_outbox_checkpoint_group ON outbox_relay_checkpoint (consumer_group);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS outbox_dead_letter (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        original_outbox_id UUID NOT NULL,
        aggregate_type VARCHAR(100) NOT NULL,
        aggregate_id UUID NOT NULL,
        event_type VARCHAR(200) NOT NULL,
        payload JSONB NOT NULL,
        metadata JSONB NOT NULL,
        kafka_topic VARCHAR(200) NOT NULL,
        final_error TEXT NOT NULL,
        failed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        resolution_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
        resolved_at TIMESTAMPTZ,
        resolved_by UUID
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_dead_letter_status ON outbox_dead_letter (resolution_status);")

    op.execute("""
    CREATE OR REPLACE FUNCTION outbox_mark_stale()
    RETURNS TRIGGER AS $$
    BEGIN
        IF NEW.status = 'PENDING' AND NEW.created_at < NOW() - INTERVAL '7 days' THEN
            UPDATE outbox
            SET status = 'DEAD_LETTER',
                last_error = 'Auto-moved to dead letter after 7 days pending'
            WHERE id = NEW.id;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)
    op.execute("DROP TRIGGER IF EXISTS outbox_stale_check_trigger ON outbox;")
    op.execute("CREATE TRIGGER outbox_stale_check_trigger AFTER INSERT OR UPDATE ON outbox FOR EACH ROW EXECUTE FUNCTION outbox_mark_stale();")

def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS outbox_stale_check_trigger ON outbox;")
    op.execute("DROP FUNCTION IF EXISTS outbox_mark_stale();")
    op.execute("DROP TABLE IF EXISTS outbox_dead_letter;")
    op.execute("DROP TABLE IF EXISTS outbox_relay_checkpoint;")
    op.execute("DROP TABLE IF EXISTS outbox;")