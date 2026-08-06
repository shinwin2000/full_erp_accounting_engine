"""journal_header: tambah kolom yang dibutuhkan endpoint list/detail journal

Root cause: router fastapi_journal_router.py (list_journals, dan endpoint
journal lain) mengharapkan ~16 kolom yang tidak pernah ditambahkan ke
journal_header (journal_type, notes, attachment_ids, created_by_name, dst).
Semua kolom baru dibuat NULLABLE atau dengan server_default supaya AMAN
dijalankan di atas data journal yang sudah ada -- TIDAK PERLU TRUNCATE.

Revision ID: journal_header_fix_001
Revises: approval_request_fix_001
Create Date: 2026-08-05 17:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "journal_header_fix_001"
down_revision = "approval_request_fix_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tipe & workflow tambahan
    op.add_column(
        "journal_header",
        sa.Column("journal_type", sa.String(20), nullable=False, server_default="general"),
    )
    op.add_column("journal_header", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column(
        "journal_header",
        sa.Column("attachment_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column("journal_header", sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.false()))

    # Nama-nama actor (denormalized, sama pola dengan requester_name di approval)
    op.add_column("journal_header", sa.Column("created_by_name", sa.String(200), nullable=True))
    op.add_column("journal_header", sa.Column("approved_by_name", sa.String(200), nullable=True))
    op.add_column("journal_header", sa.Column("posted_by_name", sa.String(200), nullable=True))

    # Submit
    op.add_column(
        "journal_header",
        sa.Column("submitted_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("journal_header", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))

    # Reject
    op.add_column(
        "journal_header",
        sa.Column("rejected_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("journal_header", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("journal_header", sa.Column("rejection_reason", sa.Text(), nullable=True))

    # Reversal (reversed_by/at/journal_id sudah ada; reversal_reason belum)
    op.add_column("journal_header", sa.Column("reversal_reason", sa.Text(), nullable=True))

    # Cancel
    op.add_column(
        "journal_header",
        sa.Column("cancelled_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("journal_header", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("journal_header", sa.Column("cancellation_reason", sa.Text(), nullable=True))

    op.create_index("idx_journal_header_journal_type", "journal_header", ["journal_type"])


def downgrade() -> None:
    op.drop_index("idx_journal_header_journal_type", table_name="journal_header")

    for col in (
        "cancellation_reason",
        "cancelled_at",
        "cancelled_by",
        "reversal_reason",
        "rejection_reason",
        "rejected_at",
        "rejected_by",
        "submitted_at",
        "submitted_by",
        "posted_by_name",
        "approved_by_name",
        "created_by_name",
        "is_locked",
        "attachment_ids",
        "notes",
        "journal_type",
    ):
        op.drop_column("journal_header", col)
