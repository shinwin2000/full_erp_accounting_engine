"""approval: tambah kolom request + tabel matrix & delegation

Revision ID: approval_extend_001
Revises: b39403e62281
Create Date: 2026-08-05 13:05:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "approval_extend_001"
down_revision = "b39403e62281"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Tabel approval_request (Diubah dari add_column menjadi create_table)
    # ------------------------------------------------------------------
    op.create_table(
        "approval_request",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_reference", sa.String(100), nullable=True),
        sa.Column("amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="IDR"),
        sa.Column("requester_name", sa.String(200), nullable=True),
        sa.Column("current_level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("approval_matrix_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # ------------------------------------------------------------------
    # 2. Tabel approval_matrix
    # ------------------------------------------------------------------
    op.create_table(
        "approval_matrix",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("matrix_code", sa.String(50), nullable=False),
        sa.Column("matrix_name", sa.String(200), nullable=False),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("min_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("max_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="IDR"),
        sa.Column("rules", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_name", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("legal_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.UniqueConstraint("matrix_code", "legal_entity_id", name="uq_approval_matrix_code_legal_entity"),
        sa.CheckConstraint("min_amount >= 0", name="ck_approval_matrix_min_amount_nonneg"),
        sa.CheckConstraint(
            "entity_type IN ('journal', 'ap_invoice', 'ar_invoice', 'payment', 'purchase_order', 'sales_order', 'budget', 'master_data')",
            name="ck_approval_matrix_entity_type",
        ),
    )
    op.create_index("idx_approval_matrix_entity_type", "approval_matrix", ["entity_type"])
    op.create_index("idx_approval_matrix_legal_entity", "approval_matrix", ["legal_entity_id"])
    op.create_index("idx_approval_matrix_is_active", "approval_matrix", ["is_active"])

    op.create_foreign_key(
        "fk_approval_request_matrix",
        "approval_request",
        "approval_matrix",
        ["approval_matrix_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ------------------------------------------------------------------
    # 3. Tabel approval_delegation
    # ------------------------------------------------------------------
    op.create_table(
        "approval_delegation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("delegator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delegator_name", sa.String(200), nullable=True),
        sa.Column("delegate_to_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delegate_to_name", sa.String(200), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revoked_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("legal_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("end_date >= start_date", name="ck_approval_delegation_dates"),
    )
    op.create_index("idx_approval_delegation_delegator", "approval_delegation", ["delegator_id"])
    op.create_index("idx_approval_delegation_delegate_to", "approval_delegation", ["delegate_to_id"])
    op.create_index("idx_approval_delegation_active", "approval_delegation", ["is_active"])
    op.create_index("idx_approval_delegation_legal_entity", "approval_delegation", ["legal_entity_id"])


def downgrade() -> None:
    op.drop_table("approval_delegation")
    op.drop_constraint("fk_approval_request_matrix", "approval_request", type_="foreignkey")
    op.drop_table("approval_matrix")
    
    # Menghapus tabel seutuhnya di fungsi downgrade, 
    # menggantikan drop_column yang sebelumnya digunakan.
    op.drop_table("approval_request")