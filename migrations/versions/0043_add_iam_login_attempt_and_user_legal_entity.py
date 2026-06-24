"""add iam_login_attempt and iam_user_legal_entity tables

Revision ID: 0043
Revises: 0042
Create Date: 2026-06-21 12:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = '0043abcd'
down_revision = '0042abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS iam_login_attempt (
        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        username VARCHAR(100) NOT NULL,
        success BOOLEAN NOT NULL DEFAULT false,
        ip_address VARCHAR(45),
        attempted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_login_attempt_username ON iam_login_attempt (username);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_login_attempt_attempted_at ON iam_login_attempt (attempted_at);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_login_attempt_success ON iam_login_attempt (success);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS iam_user_legal_entity (
        user_id UUID NOT NULL,
        legal_entity_id UUID NOT NULL,
        assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        assigned_by UUID,
        PRIMARY KEY (user_id, legal_entity_id)
    );
    """)

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS iam_user_legal_entity;")
    op.execute("DROP TABLE IF EXISTS iam_login_attempt;")