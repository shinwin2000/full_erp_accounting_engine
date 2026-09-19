"""Add disposal tracking columns to goodwill table

Sebelum migrasi ini, tabel `goodwill` sama sekali tidak punya kolom untuk
mencatat proceeds/gain-loss saat goodwill dilepas (dispose) - method
GoodwillTable.dispose() cuma mengubah status jadi 'disposed', tidak ada
tempat menyimpan berapa hasil pelepasannya atau untung/rugi terkait.
Ditemukan saat audit modul Goodwill 2026-09-15.

CATATAN: repo ini punya beberapa revision head yang belum di-merge
(lihat `alembic heads`). down_revision di bawah menyambung ke
'645713879b2d' (resolve_final_schema_drift) sebagai head yang paling
plausible terbaru saat migrasi ini ditulis - cek ulang dengan
`alembic heads` sebelum upgrade, dan `alembic merge heads` dulu kalau
memang masih bercabang.

Revision ID: goodwill_disposal_001
Revises: 645713879b2d
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "goodwill_disposal_001"
down_revision = "645713879b2d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("goodwill", sa.Column("disposal_date", sa.Date(), nullable=True))
    op.add_column(
        "goodwill",
        sa.Column("disposal_proceeds", sa.Numeric(20, 2), nullable=True),
    )
    op.add_column(
        "goodwill",
        sa.Column("disposal_gain_loss", sa.Numeric(20, 2), nullable=True),
    )
    op.add_column("goodwill", sa.Column("disposal_reason", sa.Text(), nullable=True))
    op.add_column(
        "goodwill",
        sa.Column(
            "disposed_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("goodwill", "disposed_by")
    op.drop_column("goodwill", "disposal_reason")
    op.drop_column("goodwill", "disposal_gain_loss")
    op.drop_column("goodwill", "disposal_proceeds")
    op.drop_column("goodwill", "disposal_date")
