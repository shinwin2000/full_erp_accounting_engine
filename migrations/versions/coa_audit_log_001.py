"""create coa_audit_log (append-only, hash per baris) untuk jejak perubahan COA

Revision ID: coa_audit_log_001
Revises: 645713879b2d, employee_documents_seq_001
Create Date: 2026-10-09 19:00:00.000000

Menggabungkan dua head yang ada (645713879b2d & employee_documents_seq_001)
sekaligus membuat tabel audit COA. Tabel bersifat append-only (trigger
menolak UPDATE/DELETE/TRUNCATE).
"""
from alembic import op

revision = "coa_audit_log_001"
down_revision = ("645713879b2d", "employee_documents_seq_001")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS coa_audit_log (
            id            UUID PRIMARY KEY,
            legal_entity_id UUID NOT NULL,
            account_id    UUID,
            account_code  VARCHAR(20),
            action        VARCHAR(50) NOT NULL,
            field_name    VARCHAR(100),
            old_value     TEXT,
            new_value     TEXT,
            details       JSONB NOT NULL DEFAULT '{}'::jsonb,
            reason        VARCHAR(500),
            actor_id      UUID,
            occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            row_hash      CHAR(64) NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_coa_audit_account "
        "ON coa_audit_log (legal_entity_id, account_id, occurred_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_coa_audit_code ON coa_audit_log (legal_entity_id, account_code)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION coa_audit_log_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'coa_audit_log bersifat append-only: % tidak diizinkan', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_coa_audit_log_no_change ON coa_audit_log")
    op.execute(
        "CREATE TRIGGER trg_coa_audit_log_no_change BEFORE UPDATE OR DELETE ON coa_audit_log "
        "FOR EACH ROW EXECUTE FUNCTION coa_audit_log_immutable()"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_coa_audit_log_no_truncate ON coa_audit_log")
    op.execute(
        "CREATE TRIGGER trg_coa_audit_log_no_truncate BEFORE TRUNCATE ON coa_audit_log "
        "FOR EACH STATEMENT EXECUTE FUNCTION coa_audit_log_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS coa_audit_log")
    op.execute("DROP FUNCTION IF EXISTS coa_audit_log_immutable()")
