"""add budget_revision_history table (fitur Versi Budget)

LATAR BELAKANG:
Tab "Versi Budget" di frontend memanggil GET /budget/budget/versions/{code}
yang sebelumnya tidak pernah ada di backend sama sekali (404 selalu), dan
tidak ada mekanisme penyimpanan riwayat versi budget yang persisten
(`_log_audit()` di repository cuma in-memory, `@audit` decorator di
service_budget.py cuma dummy no-op).

Migrasi ini MURNI ADDITIF -- membuat satu tabel baru, tidak mengubah tabel
`budget` yang sudah ada sama sekali. Setiap create/update budget sekarang
menulis satu snapshot ringkas ke tabel ini (lihat
adapters/secondary_impl/sqlalchemy_budget_repository_impl.py).

Revision ID: b1a2c3d4e5f6
Revises: fix_budget_version_label
Create Date: 2026-09-12 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'b1a2c3d4e5f6'
down_revision = 'fix_budget_version_label'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "budget_revision_history" in inspector.get_table_names():
        # Idempotent -- kalau sudah pernah dibuat (mis. re-run manual), skip.
        return

    op.create_table(
        "budget_revision_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("budget_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("legal_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("budget_code", sa.String(length=50), nullable=False),
        sa.Column("version_label", sa.String(length=20), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_amount", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("change_type", sa.String(length=30), nullable=False),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "idx_budget_revision_history_budget_id",
        "budget_revision_history",
        ["budget_id"],
    )
    op.create_index(
        "idx_budget_revision_history_code_entity",
        "budget_revision_history",
        ["budget_code", "legal_entity_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "budget_revision_history" in inspector.get_table_names():
        op.drop_table("budget_revision_history")
