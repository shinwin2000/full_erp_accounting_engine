"""create outbox_checkpoint, outbox_kafka_partition_checkpoint, outbox_relay_metrics tables

Revision ID: 0039
Revises: 0038
Create Date: 2026-05-30 15:45:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP

revision: str = '0039'  # <-- diperbaiki
down_revision = '0038'  # <-- diperbaiki
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS outbox_checkpoint (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
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

    op.execute("""
    CREATE TABLE IF NOT EXISTS outbox_kafka_partition_checkpoint (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        topic VARCHAR(200) NOT NULL,
        partition INTEGER NOT NULL,
        consumer_group VARCHAR(200) NOT NULL,
        last_offset BIGINT NOT NULL DEFAULT -1,
        last_committed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        committed_by VARCHAR(100) NOT NULL
    );
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_outbox_kafka_partition ON outbox_kafka_partition_checkpoint (topic, partition, consumer_group);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS outbox_relay_metrics (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        consumer_group VARCHAR(200) NOT NULL,
        poll_interval_ms INTEGER,
        batch_size INTEGER,
        processing_latency_avg_ms INTEGER,
        events_per_second NUMERIC(10,2),
        queue_depth INTEGER,
        last_poll_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_outbox_relay_metrics_group ON outbox_relay_metrics (consumer_group, created_at);")

    op.execute("DROP FUNCTION IF EXISTS update_outbox_checkpoint(TEXT, UUID, TEXT);")
    op.execute("""
    CREATE OR REPLACE FUNCTION update_outbox_checkpoint(p_consumer_group TEXT, p_outbox_id UUID, p_processed_by TEXT)
    RETURNS BOOLEAN AS $$
    DECLARE
        current_last_id UUID;
    BEGIN
        SELECT last_processed_outbox_id INTO current_last_id FROM outbox_checkpoint WHERE consumer_group = p_consumer_group FOR UPDATE;
        IF current_last_id IS NULL THEN
            INSERT INTO outbox_checkpoint (consumer_group, last_processed_outbox_id, processed_by) VALUES (p_consumer_group, p_outbox_id, p_processed_by);
            RETURN TRUE;
        ELSIF p_outbox_id > current_last_id THEN
            UPDATE outbox_checkpoint SET last_processed_outbox_id = p_outbox_id, last_processed_at = now(), processed_by = p_processed_by, total_processed_count = total_processed_count + 1, version = version + 1
            WHERE consumer_group = p_consumer_group;
            RETURN TRUE;
        ELSE
            RETURN FALSE;
        END IF;
    END;
    $$ LANGUAGE plpgsql;
    """)

    op.execute("DROP FUNCTION IF EXISTS update_outbox_checkpoint_batch(TEXT, UUID, TEXT, INTEGER);")
    op.execute("""
    CREATE OR REPLACE FUNCTION update_outbox_checkpoint_batch(p_consumer_group TEXT, p_max_outbox_id UUID, p_processed_by TEXT, p_batch_size INTEGER)
    RETURNS INTEGER AS $$
    DECLARE
        v_updated_count INTEGER := 0;
        v_current_last_id UUID;
    BEGIN
        SELECT last_processed_outbox_id INTO v_current_last_id FROM outbox_checkpoint WHERE consumer_group = p_consumer_group FOR UPDATE;
        IF v_current_last_id IS NULL THEN
            INSERT INTO outbox_checkpoint (consumer_group, last_processed_outbox_id, processed_by) VALUES (p_consumer_group, p_max_outbox_id, p_processed_by);
            RETURN 1;
        END IF;
        SELECT COUNT(*) INTO v_updated_count FROM outbox WHERE id > v_current_last_id AND id <= p_max_outbox_id;
        IF v_updated_count > 0 THEN
            UPDATE outbox_checkpoint SET last_processed_outbox_id = p_max_outbox_id, last_processed_at = now(), processed_by = p_processed_by, total_processed_count = total_processed_count + v_updated_count, version = version + 1
            WHERE consumer_group = p_consumer_group;
        END IF;
        RETURN v_updated_count;
    END;
    $$ LANGUAGE plpgsql;
    """)

    op.execute("DROP FUNCTION IF EXISTS reset_outbox_checkpoint(TEXT, UUID);")
    op.execute("""
    CREATE OR REPLACE FUNCTION reset_outbox_checkpoint(p_consumer_group TEXT, p_reset_to_id UUID DEFAULT NULL)
    RETURNS BOOLEAN AS $$
    BEGIN
        IF p_reset_to_id IS NULL THEN
            DELETE FROM outbox_checkpoint WHERE consumer_group = p_consumer_group;
        ELSE
            UPDATE outbox_checkpoint SET last_processed_outbox_id = p_reset_to_id, last_processed_at = now(), total_processed_count = 0, total_failed_count = 0, version = version + 1
            WHERE consumer_group = p_consumer_group;
        END IF;
        RETURN FOUND;
    END;
    $$ LANGUAGE plpgsql;
    """)

    op.execute("DROP FUNCTION IF EXISTS update_outbox_queue_depth();")
    op.execute("""
    CREATE OR REPLACE FUNCTION update_outbox_queue_depth()
    RETURNS TRIGGER AS $$
    DECLARE
        v_depth INTEGER;
        v_consumer_group TEXT;
    BEGIN
        FOR v_consumer_group IN SELECT DISTINCT consumer_group FROM outbox_checkpoint LOOP
            SELECT COUNT(*) INTO v_depth FROM outbox WHERE status = 'PENDING' AND id > (SELECT last_processed_outbox_id FROM outbox_checkpoint WHERE consumer_group = v_consumer_group);
            INSERT INTO outbox_relay_metrics (consumer_group, queue_depth, last_poll_at) VALUES (v_consumer_group, v_depth, now()) ON CONFLICT DO NOTHING;
        END LOOP;
        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql;
    """)

def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS update_outbox_checkpoint(TEXT, UUID, TEXT);")
    op.execute("DROP FUNCTION IF EXISTS update_outbox_checkpoint_batch(TEXT, UUID, TEXT, INTEGER);")
    op.execute("DROP FUNCTION IF EXISTS reset_outbox_checkpoint(TEXT, UUID);")
    op.execute("DROP FUNCTION IF EXISTS update_outbox_queue_depth();")
    op.execute("DROP TABLE IF EXISTS outbox_relay_metrics;")
    op.execute("DROP TABLE IF EXISTS outbox_kafka_partition_checkpoint;")
    op.execute("DROP TABLE IF EXISTS outbox_checkpoint;")