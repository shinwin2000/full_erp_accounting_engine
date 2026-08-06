"""approval_request: tambah kolom yang hilang (request_number, status, entity_type, dst)

Root cause: migration approval_extend_001 hanya menulis sebagian kolom untuk
tabel approval_request (7 dari 32 kolom yang di-expect model
ApprovalRequestTable). Migration ini melengkapi sisanya.

PENTING: migration ini men-TRUNCATE approval_request dulu sebelum menambah
kolom NOT NULL. Ini aman HANYA JIKA tabel tidak berisi data yang ingin
dipertahankan (baris yang ada sekarang sudah pasti tidak valid karena tidak
punya status/entity_type/entity_id/approver_id sama sekali -- kolom-kolom
wajib itu belum pernah ada). Cek dulu row count sebelum menjalankan migration
ini kalau ragu.

Revision ID: approval_request_fix_001
Revises: 2cd2bd2d5b07
Create Date: 2026-08-05 16:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "approval_request_fix_001"
down_revision = "2cd2bd2d5b07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 0. Bersihkan baris lama yang tidak lengkap/tidak valid.
    #    Baris yang ada sekarang tidak punya status/entity_type/entity_id/
    #    approver_id sama sekali sehingga tidak mungkin baris yang valid
    #    dari workflow approval yang sebenarnya.
    # ------------------------------------------------------------------
    op.execute("TRUNCATE TABLE approval_request")

    # ------------------------------------------------------------------
    # 1. Kolom identitas request
    # ------------------------------------------------------------------
    op.add_column("approval_request", sa.Column("request_number", sa.String(50), nullable=False))
    op.add_column("approval_request", sa.Column("entity_type", sa.String(30), nullable=False))
    op.add_column(
        "approval_request",
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.add_column("approval_request", sa.Column("entity_snapshot", postgresql.JSONB(), nullable=True))

    # ------------------------------------------------------------------
    # 2. Approver
    # ------------------------------------------------------------------
    op.add_column(
        "approval_request",
        sa.Column("approver_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.add_column("approval_request", sa.Column("approver_name", sa.String(200), nullable=False))
    op.add_column("approval_request", sa.Column("approver_role", sa.String(100), nullable=True))

    # ------------------------------------------------------------------
    # 3. Status & priority & deadline
    # ------------------------------------------------------------------
    op.add_column(
        "approval_request",
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
    )
    op.add_column(
        "approval_request",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column("approval_request", sa.Column("deadline", sa.DateTime(timezone=True), nullable=True))

    # ------------------------------------------------------------------
    # 4. Comments
    # ------------------------------------------------------------------
    op.add_column("approval_request", sa.Column("requester_comments", sa.Text(), nullable=True))
    op.add_column("approval_request", sa.Column("approval_comments", sa.Text(), nullable=True))

    # ------------------------------------------------------------------
    # 5. Action / escalation / cancellation
    # ------------------------------------------------------------------
    op.add_column(
        "approval_request",
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("approval_request", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "approval_request",
        sa.Column("escalated_to", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("approval_request", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "approval_request",
        sa.Column("cancelled_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("approval_request", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("approval_request", sa.Column("cancellation_reason", sa.Text(), nullable=True))

    # ------------------------------------------------------------------
    # 6. Audit
    # ------------------------------------------------------------------
    op.add_column(
        "approval_request",
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.add_column(
        "approval_request",
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # ------------------------------------------------------------------
    # 7. Mixin columns: TimestampMixin, SoftDeleteMixin, VersionMixin,
    #    LegalEntityMixin (pola sama dengan approval_matrix/approval_delegation
    #    yang sudah lengkap)
    # ------------------------------------------------------------------
    op.add_column(
        "approval_request",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column(
        "approval_request",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("approval_request", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "approval_request",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "approval_request",
        sa.Column("legal_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
    )

    # ------------------------------------------------------------------
    # 8. Constraints & indexes sesuai __table_args__ di ApprovalRequestTable
    # ------------------------------------------------------------------
    op.create_unique_constraint(
        "uq_approval_request_number_legal_entity",
        "approval_request",
        ["request_number", "legal_entity_id"],
    )
    op.create_check_constraint(
        "ck_approval_request_number",
        "approval_request",
        "request_number IS NOT NULL AND request_number != ''",
    )
    op.create_check_constraint(
        "ck_approval_entity_type",
        "approval_request",
        "entity_type IN ('journal', 'ap_invoice', 'ar_invoice', 'payment', "
        "'purchase_order', 'sales_order', 'budget', 'master_data')",
    )
    op.create_check_constraint(
        "ck_approval_status",
        "approval_request",
        "status IN ('pending', 'approved', 'rejected', 'cancelled', 'escalated', 'expired')",
    )
    op.create_check_constraint(
        "ck_approval_priority",
        "approval_request",
        "priority IN (1, 2, 3, 4, 5)",
    )

    op.create_index("idx_approval_request_number", "approval_request", ["request_number"])
    op.create_index("idx_approval_entity", "approval_request", ["entity_type", "entity_id"])
    op.create_index("idx_approval_approver", "approval_request", ["approver_id"])
    op.create_index("idx_approval_status", "approval_request", ["status"])
    op.create_index("idx_approval_deadline", "approval_request", ["deadline"])
    op.create_index("idx_approval_legal_entity", "approval_request", ["legal_entity_id"])

    # FK ke legal_entity, mengikuti pola LegalEntityMixin di tabel lain
    op.create_foreign_key(
        "fk_approval_request_legal_entity",
        "approval_request",
        "legal_entity",
        ["legal_entity_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_approval_request_legal_entity", "approval_request", type_="foreignkey")

    op.drop_index("idx_approval_legal_entity", table_name="approval_request")
    op.drop_index("idx_approval_deadline", table_name="approval_request")
    op.drop_index("idx_approval_status", table_name="approval_request")
    op.drop_index("idx_approval_approver", table_name="approval_request")
    op.drop_index("idx_approval_entity", table_name="approval_request")
    op.drop_index("idx_approval_request_number", table_name="approval_request")

    op.drop_constraint("ck_approval_priority", "approval_request", type_="check")
    op.drop_constraint("ck_approval_status", "approval_request", type_="check")
    op.drop_constraint("ck_approval_entity_type", "approval_request", type_="check")
    op.drop_constraint("ck_approval_request_number", "approval_request", type_="check")
    op.drop_constraint("uq_approval_request_number_legal_entity", "approval_request", type_="unique")

    for col in (
        "legal_entity_id",
        "version",
        "deleted_at",
        "updated_at",
        "created_at",
        "created_by",
        "requested_by",
        "cancellation_reason",
        "cancelled_at",
        "cancelled_by",
        "escalated_at",
        "escalated_to",
        "approved_at",
        "approved_by",
        "approval_comments",
        "requester_comments",
        "deadline",
        "priority",
        "status",
        "approver_role",
        "approver_name",
        "approver_id",
        "entity_snapshot",
        "entity_id",
        "entity_type",
        "request_number",
    ):
        op.drop_column("approval_request", col)
