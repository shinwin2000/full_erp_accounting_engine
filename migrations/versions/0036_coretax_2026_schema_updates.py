"""update coretax tables with 2026 features (QR code, prepopulated data, SPT electronic)

Revision ID: 0036
Revises: 0035
Create Date: 2026-05-30 15:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP

revision: str = '0036abcd'
down_revision = '0035abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Add columns to coretax_faktur_keluaran
    op.add_column('coretax_faktur_keluaran', sa.Column('qr_code_url', sa.String(500), nullable=True))
    op.add_column('coretax_faktur_keluaran', sa.Column('prepopulated_data', JSONB, nullable=True))
    op.add_column('coretax_faktur_keluaran', sa.Column('signature_djp', sa.String(512), nullable=True))
    op.add_column('coretax_faktur_keluaran', sa.Column('validation_token', sa.String(200), nullable=True))
    op.add_column('coretax_faktur_keluaran', sa.Column('sync_attempts', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('coretax_faktur_keluaran', sa.Column('last_sync_at', TIMESTAMP(timezone=True), nullable=True))
    op.add_column('coretax_faktur_keluaran', sa.Column('is_latest_version', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('coretax_faktur_keluaran', sa.Column('previous_version_id', UUID(as_uuid=True), nullable=True))
    op.create_index('ix_coretax_faktur_keluaran_sync', 'coretax_faktur_keluaran', ['sync_attempts', 'last_sync_at'])
    op.create_index('ix_coretax_faktur_keluaran_qr', 'coretax_faktur_keluaran', ['qr_code_url'])

    # Coretax audit log
    op.execute("""
    CREATE TABLE IF NOT EXISTS coretax_audit_log (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        legal_entity_id UUID NOT NULL,
        api_endpoint VARCHAR(200) NOT NULL,
        request_payload JSONB NOT NULL,
        response_payload JSONB,
        http_status INTEGER,
        coretax_tracking_id VARCHAR(100),
        duration_ms INTEGER NOT NULL,
        is_success BOOLEAN NOT NULL,
        error_message TEXT,
        retry_count INTEGER NOT NULL DEFAULT 0,
        ip_address VARCHAR(45),
        user_agent VARCHAR(500),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL
    );
    """)
    op.create_index('ix_coretax_audit_log_entity_date', 'coretax_audit_log', ['legal_entity_id', 'created_at'])
    op.create_index('ix_coretax_audit_log_tracking', 'coretax_audit_log', ['coretax_tracking_id'])

    # Coretax SPT electronic
    op.execute("""
    CREATE TABLE IF NOT EXISTS coretax_spt_electronic (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        legal_entity_id UUID NOT NULL,
        spt_type VARCHAR(20) NOT NULL,
        tax_period_month INTEGER,
        tax_period_year INTEGER NOT NULL,
        spt_number VARCHAR(100) NOT NULL UNIQUE,
        spt_version INTEGER NOT NULL DEFAULT 1,
        status VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
        submitted_at TIMESTAMPTZ,
        approved_at TIMESTAMPTZ,
        rejection_reason TEXT,
        payment_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
        payment_reference VARCHAR(100),
        ntpn VARCHAR(50),
        xml_content TEXT,
        pdf_attachment VARCHAR(500),
        signed_by UUID,
        signed_at TIMESTAMPTZ,
        digital_signature VARCHAR(512),
        is_amendment BOOLEAN NOT NULL DEFAULT false,
        original_spt_id UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by UUID NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_by UUID NOT NULL
    );
    """)
    op.create_index('ix_coretax_spt_entity_period', 'coretax_spt_electronic', ['legal_entity_id', 'spt_type', 'tax_period_year', 'tax_period_month'])
    op.create_index('ix_coretax_spt_status', 'coretax_spt_electronic', ['status'])
    op.create_index('ix_coretax_spt_ntpn', 'coretax_spt_electronic', ['ntpn'])

    # Coretax webhook inbound
    op.execute("""
    CREATE TABLE IF NOT EXISTS coretax_webhook_inbound (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        legal_entity_id UUID NOT NULL,
        webhook_type VARCHAR(50) NOT NULL,
        payload JSONB NOT NULL,
        received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        processed_at TIMESTAMPTZ,
        status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
        error_message TEXT,
        signature_verified BOOLEAN NOT NULL DEFAULT false
    );
    """)
    op.create_index('ix_coretax_webhook_status', 'coretax_webhook_inbound', ['status', 'received_at'])

    # QR code generation function
    op.execute("""
    CREATE OR REPLACE FUNCTION generate_coretax_qr_code(p_faktur_id UUID)
    RETURNS TEXT AS $$
    DECLARE
        faktur_record RECORD;
        qr_content TEXT;
    BEGIN
        SELECT faktur_number, nsfp, dpp_total, ppn_total, approval_code INTO faktur_record
        FROM coretax_faktur_keluaran WHERE id = p_faktur_id;
        IF faktur_record IS NULL THEN RETURN NULL; END IF;
        qr_content := 'FAKTUR:' || faktur_record.faktur_number || ';NSFP:' || faktur_record.nsfp ||
                      ';DPP:' || faktur_record.dpp_total || ';PPN:' || faktur_record.ppn_total ||
                      ';APPROVAL:' || COALESCE(faktur_record.approval_code, '');
        RETURN encode(sha256(qr_content::bytea), 'hex');
    END;
    $$ LANGUAGE plpgsql;
    """)

    op.execute("""
    CREATE OR REPLACE FUNCTION update_faktur_qr_code()
    RETURNS TRIGGER AS $$
    BEGIN
        IF NEW.status = 'APPROVED' AND OLD.status != 'APPROVED' THEN
            NEW.qr_code_url := 'https://coretax.djp.go.id/qr/' || generate_coretax_qr_code(NEW.id);
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_coretax_faktur_qr ON coretax_faktur_keluaran;")
    op.execute("CREATE TRIGGER trg_coretax_faktur_qr BEFORE UPDATE ON coretax_faktur_keluaran FOR EACH ROW EXECUTE FUNCTION update_faktur_qr_code();")

def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_coretax_faktur_qr ON coretax_faktur_keluaran;")
    op.execute("DROP FUNCTION IF EXISTS update_faktur_qr_code();")
    op.execute("DROP FUNCTION IF EXISTS generate_coretax_qr_code(UUID);")
    op.execute("DROP TABLE IF EXISTS coretax_webhook_inbound;")
    op.execute("DROP TABLE IF EXISTS coretax_spt_electronic;")
    op.execute("DROP TABLE IF EXISTS coretax_audit_log;")
    op.drop_index('ix_coretax_faktur_keluaran_sync', table_name='coretax_faktur_keluaran')
    op.drop_index('ix_coretax_faktur_keluaran_qr', table_name='coretax_faktur_keluaran')
    op.drop_column('coretax_faktur_keluaran', 'previous_version_id')
    op.drop_column('coretax_faktur_keluaran', 'is_latest_version')
    op.drop_column('coretax_faktur_keluaran', 'last_sync_at')
    op.drop_column('coretax_faktur_keluaran', 'sync_attempts')
    op.drop_column('coretax_faktur_keluaran', 'validation_token')
    op.drop_column('coretax_faktur_keluaran', 'signature_djp')
    op.drop_column('coretax_faktur_keluaran', 'prepopulated_data')
    op.drop_column('coretax_faktur_keluaran', 'qr_code_url')