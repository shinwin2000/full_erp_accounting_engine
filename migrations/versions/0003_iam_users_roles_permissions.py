"""add constraints and indexes for IAM tables

Revision ID: 0003
Revises: 0002
Create Date: 2025-01-01 00:00:02.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

def upgrade():
    # ========================================================================
    # Add check constraints (using DO block to avoid IF NOT EXISTS syntax issues)
    # ========================================================================
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_iam_user_status') THEN
            EXECUTE 'ALTER TABLE iam_user ADD CONSTRAINT ck_iam_user_status CHECK (status IN (''active'', ''inactive'', ''locked'', ''suspended'', ''pending_activation''))';
        END IF;
    END;
    $$;
    """)

    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_iam_role_status') THEN
            EXECUTE 'ALTER TABLE iam_role ADD CONSTRAINT ck_iam_role_status CHECK (status IN (''active'', ''inactive''))';
        END IF;
    END;
    $$;
    """)

    # ========================================================================
    # Add unique constraint for permission (resource, action)
    # ========================================================================
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_iam_permission_resource_action') THEN
            EXECUTE 'ALTER TABLE iam_permission ADD CONSTRAINT uq_iam_permission_resource_action UNIQUE (resource, action)';
        END IF;
    END;
    $$;
    """)

    # ========================================================================
    # Add indexes (CREATE INDEX IF NOT EXISTS is safe from PG 9.5+)
    # ========================================================================
    op.execute("CREATE INDEX IF NOT EXISTS idx_iam_user_legal_entity_ids ON iam_user USING gin (legal_entity_ids)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_iam_role_status ON iam_role (status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_iam_permission_name ON iam_permission (name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_iam_permission_action ON iam_permission (action)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_iam_user_role_user ON iam_user_role (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_iam_user_role_role ON iam_user_role (role_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_iam_role_permission_role ON iam_role_permission (role_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_iam_role_permission_permission ON iam_role_permission (permission_id)")

    # ========================================================================
    # Add foreign key constraints (using DO block for existence check)
    # ========================================================================
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_iam_user_role_user') THEN
            EXECUTE 'ALTER TABLE iam_user_role ADD CONSTRAINT fk_iam_user_role_user FOREIGN KEY (user_id) REFERENCES iam_user(id) ON DELETE CASCADE';
        END IF;
    END;
    $$;
    """)

    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_iam_user_role_role') THEN
            EXECUTE 'ALTER TABLE iam_user_role ADD CONSTRAINT fk_iam_user_role_role FOREIGN KEY (role_id) REFERENCES iam_role(id) ON DELETE CASCADE';
        END IF;
    END;
    $$;
    """)

    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_iam_role_permission_role') THEN
            EXECUTE 'ALTER TABLE iam_role_permission ADD CONSTRAINT fk_iam_role_permission_role FOREIGN KEY (role_id) REFERENCES iam_role(id) ON DELETE CASCADE';
        END IF;
    END;
    $$;
    """)

    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_iam_role_permission_perm') THEN
            EXECUTE 'ALTER TABLE iam_role_permission ADD CONSTRAINT fk_iam_role_permission_perm FOREIGN KEY (permission_id) REFERENCES iam_permission(id) ON DELETE CASCADE';
        END IF;
    END;
    $$;
    """)

def downgrade():
    # Drop foreign keys
    op.execute("ALTER TABLE iam_role_permission DROP CONSTRAINT IF EXISTS fk_iam_role_permission_perm")
    op.execute("ALTER TABLE iam_role_permission DROP CONSTRAINT IF EXISTS fk_iam_role_permission_role")
    op.execute("ALTER TABLE iam_user_role DROP CONSTRAINT IF EXISTS fk_iam_user_role_role")
    op.execute("ALTER TABLE iam_user_role DROP CONSTRAINT IF EXISTS fk_iam_user_role_user")

    # Drop indexes
    op.execute("DROP INDEX IF EXISTS idx_iam_role_permission_permission")
    op.execute("DROP INDEX IF EXISTS idx_iam_role_permission_role")
    op.execute("DROP INDEX IF EXISTS idx_iam_user_role_role")
    op.execute("DROP INDEX IF EXISTS idx_iam_user_role_user")
    op.execute("DROP INDEX IF EXISTS idx_iam_permission_action")
    op.execute("DROP INDEX IF EXISTS idx_iam_permission_name")
    op.execute("DROP INDEX IF EXISTS idx_iam_role_status")
    op.execute("DROP INDEX IF EXISTS idx_iam_user_legal_entity_ids")

    # Drop constraints
    op.execute("ALTER TABLE iam_permission DROP CONSTRAINT IF EXISTS uq_iam_permission_resource_action")
    op.execute("ALTER TABLE iam_role DROP CONSTRAINT IF EXISTS ck_iam_role_status")
    op.execute("ALTER TABLE iam_user DROP CONSTRAINT IF EXISTS ck_iam_user_status")