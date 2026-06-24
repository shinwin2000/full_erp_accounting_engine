"""Create machine table for manufacturing routing.

Revision ID: 0045
Revises: 0044
Create Date: 2026-06-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0045abcd"
down_revision = "0044abcd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "machine",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("hourly_rate", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_machine_code", "machine", ["code"], unique=True)

    # Also add machine_id FK column to routing_step if missing
    op.execute("""
        ALTER TABLE routing_step
        ADD COLUMN IF NOT EXISTS machine_id UUID REFERENCES machine(id) ON DELETE SET NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE routing_step DROP COLUMN IF EXISTS machine_id")
    op.drop_index("idx_machine_code", "machine")
    op.drop_table("machine")
