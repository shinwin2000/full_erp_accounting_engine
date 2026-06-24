"""create audit_append_only_trigger for event_store table

Revision ID: 0010
Revises: 0009
Create Date: 2025-01-01 00:00:09.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0010abcd'
down_revision: Union[str, None] = '0009abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create schema audit if not exists
    op.execute('CREATE SCHEMA IF NOT EXISTS audit')

    # Create audit_log table
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit.audit_log (
            id BIGSERIAL PRIMARY KEY,
            event_type VARCHAR(50) NOT NULL,
            table_name VARCHAR(100) NOT NULL,
            operation VARCHAR(10) NOT NULL,
            attempted_data TEXT,
            error_message TEXT,
            attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_log_attempted_at "
        "ON audit.audit_log(attempted_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_log_event_type "
        "ON audit.audit_log(event_type)"
    )

    # Create function to prevent UPDATE/DELETE on event_store
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_event_store_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION 'UPDATE not allowed on event_store table (append-only)';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'DELETE not allowed on event_store table (append-only)';
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
    """)

    # Create function to log modification attempts
    op.execute("""
        CREATE OR REPLACE FUNCTION log_modification_attempt()
        RETURNS TRIGGER AS $$
        BEGIN
            INSERT INTO audit.audit_log (
                event_type, table_name, operation, attempted_data, error_message
            ) VALUES (
                'security_violation',
                'event_store',
                TG_OP,
                CASE
                    WHEN TG_OP = 'UPDATE' THEN ROW(OLD.*, NEW.*)::TEXT
                    WHEN TG_OP = 'DELETE' THEN ROW(OLD.*)::TEXT
                    ELSE NULL
                END,
                'Attempted to modify append-only table'
            );
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
    """)

    # Create triggers on event_store only if table exists (created in migration 0030)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'event_store' AND table_schema = 'public') THEN
                DROP TRIGGER IF EXISTS trigger_prevent_update ON event_store;
                CREATE TRIGGER trigger_prevent_update
                    BEFORE UPDATE ON event_store
                    FOR EACH ROW
                    EXECUTE FUNCTION prevent_event_store_modification();

                DROP TRIGGER IF EXISTS trigger_prevent_delete ON event_store;
                CREATE TRIGGER trigger_prevent_delete
                    BEFORE DELETE ON event_store
                    FOR EACH ROW
                    EXECUTE FUNCTION prevent_event_store_modification();

                DROP TRIGGER IF EXISTS trigger_log_modification ON event_store;
                CREATE TRIGGER trigger_log_modification
                    BEFORE UPDATE OR DELETE ON event_store
                    FOR EACH ROW
                    EXECUTE FUNCTION log_modification_attempt();
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trigger_prevent_update ON event_store")
    op.execute("DROP TRIGGER IF EXISTS trigger_prevent_delete ON event_store")
    op.execute("DROP TRIGGER IF EXISTS trigger_log_modification ON event_store")
    op.execute("DROP FUNCTION IF EXISTS prevent_event_store_modification() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS log_modification_attempt() CASCADE")
    op.execute("DROP TABLE IF EXISTS audit.audit_log")
    op.execute("DROP SCHEMA IF EXISTS audit CASCADE")
