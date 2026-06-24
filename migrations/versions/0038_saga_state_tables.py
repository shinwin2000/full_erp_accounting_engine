"""0038_saga_state_tables.py

Revision ID: 0038
Revises: 0037
Create Date: 2026-05-30 15:30:00.000000

Layer: Infrastructure / Database Migration
Responsibility: Tabel untuk persistent state saga (orchestrator-based distributed transaction)
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP

revision: str = '0038abcd'
down_revision: Union[str, None] = '0037abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tabel utama saga instance
    op.create_table(
        'saga_instance',
        sa.Column('id', UUID(as_uuid=False), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('saga_type', sa.String(100), nullable=False),
        sa.Column('correlation_id', sa.String(200), nullable=False),
        sa.Column('legal_entity_id', UUID(as_uuid=False), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='STARTED'),
        sa.Column('current_step', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_steps', sa.Integer(), nullable=False),
        sa.Column('saga_data', JSONB, nullable=False, server_default='{}'),
        sa.Column('compensation_data', JSONB, nullable=True),
        sa.Column('started_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('last_heartbeat_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('completed_at', TIMESTAMP(timezone=True), nullable=True),
        sa.Column('failed_at', TIMESTAMP(timezone=True), nullable=True),
        sa.Column('timeout_at', TIMESTAMP(timezone=True), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=False), nullable=False),
        sa.Column('updated_by', UUID(as_uuid=False), nullable=False),
    )
    op.create_index('ix_saga_instance_type_correlation', 'saga_instance', ['saga_type', 'correlation_id'], unique=True)
    op.create_index('ix_saga_instance_status', 'saga_instance', ['status', 'last_heartbeat_at'])
    op.create_index('ix_saga_instance_entity', 'saga_instance', ['legal_entity_id'])

    # Tabel step execution log
    op.create_table(
        'saga_step_log',
        sa.Column('id', UUID(as_uuid=False), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('saga_instance_id', UUID(as_uuid=False), nullable=False),
        sa.Column('step_index', sa.Integer(), nullable=False),
        sa.Column('step_name', sa.String(100), nullable=False),
        sa.Column('action_type', sa.String(20), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('input_payload', JSONB, nullable=True),
        sa.Column('output_payload', JSONB, nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', TIMESTAMP(timezone=True), nullable=True),
        sa.Column('completed_at', TIMESTAMP(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
    )
    op.create_index('ix_saga_step_log_instance', 'saga_step_log', ['saga_instance_id', 'step_index'])

    # Tabel saga lock
    op.create_table(
        'saga_lock',
        sa.Column('saga_type', sa.String(100), nullable=False, primary_key=True),
        sa.Column('correlation_id', sa.String(200), nullable=False, primary_key=True),
        sa.Column('lock_acquired_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('lock_expires_at', TIMESTAMP(timezone=True), nullable=False),
        sa.Column('locked_by', sa.String(100), nullable=False),
    )
    op.create_index('ix_saga_lock_expiry', 'saga_lock', ['lock_expires_at'])

    # Tabel saga event outbox
    op.create_table(
        'saga_event',
        sa.Column('id', UUID(as_uuid=False), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('saga_instance_id', UUID(as_uuid=False), nullable=True),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('payload', JSONB, nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),
        sa.Column('created_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('processed_at', TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index('ix_saga_event_status', 'saga_event', ['status', 'created_at'])

    # Fungsi untuk cleanup saga stale (timeout)
    op.execute("""
        CREATE OR REPLACE FUNCTION cleanup_stale_saga_instances()
        RETURNS INTEGER AS $$
        DECLARE
            stale_count INTEGER;
        BEGIN
            UPDATE saga_instance
            SET status = 'TIMEOUT',
                failed_at = now(),
                timeout_at = now()
            WHERE status IN ('STARTED', 'COMPENSATING')
              AND last_heartbeat_at < NOW() - INTERVAL '30 minutes'
              AND timeout_at IS NULL;

            GET DIAGNOSTICS stale_count = ROW_COUNT;
            RETURN stale_count;
        END;
        $$ LANGUAGE plpgsql
    """)

    # Fungsi trigger untuk update heartbeat
    op.execute("""
        CREATE OR REPLACE FUNCTION update_saga_heartbeat()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.last_heartbeat_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    op.execute("""
        CREATE TRIGGER trg_saga_heartbeat
        BEFORE UPDATE ON saga_instance
        FOR EACH ROW
        EXECUTE FUNCTION update_saga_heartbeat()
    """)

    # CATATAN: pg_cron tidak tersedia di Windows PostgreSQL.
    # Cleanup stale saga dapat dipanggil manual atau via aplikasi scheduler (APScheduler/Celery).
    # Untuk production Linux, uncomment baris berikut setelah install pg_cron:
    # op.execute("CREATE EXTENSION IF NOT EXISTS pg_cron")
    # op.execute("SELECT cron.schedule('cleanup-stale-saga', '*/5 * * * *', 'SELECT cleanup_stale_saga_instances();')")


def downgrade() -> None:
    # CATATAN: skip cron.unschedule karena pg_cron tidak diaktifkan
    # op.execute("SELECT cron.unschedule('cleanup-stale-saga');")
    # op.execute("DROP EXTENSION IF EXISTS pg_cron CASCADE;")

    op.execute("DROP TRIGGER IF EXISTS trg_saga_heartbeat ON saga_instance")
    op.execute("DROP FUNCTION IF EXISTS update_saga_heartbeat()")
    op.execute("DROP FUNCTION IF EXISTS cleanup_stale_saga_instances()")
    op.drop_table('saga_event')
    op.drop_table('saga_lock')
    op.drop_table('saga_step_log')
    op.drop_table('saga_instance')
