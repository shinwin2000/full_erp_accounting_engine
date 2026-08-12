"""persist_branch_and_consolidation_group

LegalEntityService kept Branch (self._branches) and ConsolidationGroup
(self._groups) entirely in-memory - data was lost on every restart. Two
earlier, uncoordinated migrations (0040 and 0042, on a different/merged
chain) had already created partial versions of legal_entity_branch and
consolidation_group with inconsistent column sets, so this migration is
written defensively: it creates the tables if missing, and otherwise
ADDs any column the service/domain model needs that isn't there yet.
Nothing is dropped or renamed, so this is safe to run regardless of
which earlier variant (if any) is already live.

After this migration, LegalEntityService.create_branch/list_branches/
get_branch_by_id/update_branch/close_branch and .create_consolidation_
group/list_consolidation_groups/get_consolidation_group_by_id/
update_consolidation_group/deactivate_consolidation_group are rewired to
read/write these tables via AsyncSession instead of dict attributes.

Revision ID: c3d4e5f6a7b8
Revises: b2f3d4e5c6a7
Create Date: 2026-08-12 02:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2f3d4e5c6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # legal_entity_branch
    # ------------------------------------------------------------------
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS legal_entity_branch (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            legal_entity_id UUID NOT NULL,
            branch_code VARCHAR(50),
            branch_name VARCHAR(200) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """))
    for ddl in (
        # Dipastikan legal_entity_id ada jika tabel sudah terlanjur terbuat sebelumnya
        "ALTER TABLE legal_entity_branch ADD COLUMN IF NOT EXISTS legal_entity_id UUID",
        "ALTER TABLE legal_entity_branch ADD COLUMN IF NOT EXISTS branch_code VARCHAR(50)",
        "ALTER TABLE legal_entity_branch ADD COLUMN IF NOT EXISTS branch_name VARCHAR(200)",
        "ALTER TABLE legal_entity_branch ADD COLUMN IF NOT EXISTS address TEXT",
        "ALTER TABLE legal_entity_branch ADD COLUMN IF NOT EXISTS city VARCHAR(100)",
        "ALTER TABLE legal_entity_branch ADD COLUMN IF NOT EXISTS postal_code VARCHAR(20)",
        "ALTER TABLE legal_entity_branch ADD COLUMN IF NOT EXISTS phone VARCHAR(20)",
        "ALTER TABLE legal_entity_branch ADD COLUMN IF NOT EXISTS email VARCHAR(200)",
        "ALTER TABLE legal_entity_branch ADD COLUMN IF NOT EXISTS manager_name VARCHAR(200)",
        "ALTER TABLE legal_entity_branch ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active'",
        "ALTER TABLE legal_entity_branch ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true",
        "ALTER TABLE legal_entity_branch ADD COLUMN IF NOT EXISTS notes TEXT",
        "ALTER TABLE legal_entity_branch ADD COLUMN IF NOT EXISTS created_by UUID",
        "ALTER TABLE legal_entity_branch ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1",
    ):
        bind.execute(text(ddl))

    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_legal_entity_branch_parent "
        "ON legal_entity_branch (legal_entity_id);"
    ))
    bind.execute(text("""
        DO $$
        BEGIN
            ALTER TABLE legal_entity_branch
                ADD CONSTRAINT fk_legal_entity_branch_parent
                FOREIGN KEY (legal_entity_id) REFERENCES legal_entity(id) ON DELETE CASCADE;
        EXCEPTION
            WHEN duplicate_object THEN NULL;
            WHEN invalid_table_definition THEN NULL;
        END $$;
    """))

    # ------------------------------------------------------------------
    # consolidation_group
    # ------------------------------------------------------------------
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS consolidation_group (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            group_code VARCHAR(50) NOT NULL,
            group_name VARCHAR(200) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """))
    for ddl in (
        "ALTER TABLE consolidation_group ADD COLUMN IF NOT EXISTS group_code VARCHAR(50)",
        "ALTER TABLE consolidation_group ADD COLUMN IF NOT EXISTS group_name VARCHAR(200)",
        "ALTER TABLE consolidation_group ADD COLUMN IF NOT EXISTS description TEXT",
        "ALTER TABLE consolidation_group ADD COLUMN IF NOT EXISTS base_currency VARCHAR(3) NOT NULL DEFAULT 'IDR'",
        "ALTER TABLE consolidation_group ADD COLUMN IF NOT EXISTS fiscal_year_start INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE consolidation_group ADD COLUMN IF NOT EXISTS fiscal_year_end INTEGER NOT NULL DEFAULT 12",
        "ALTER TABLE consolidation_group ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true",
        "ALTER TABLE consolidation_group ADD COLUMN IF NOT EXISTS notes TEXT",
        "ALTER TABLE consolidation_group ADD COLUMN IF NOT EXISTS created_by UUID",
        "ALTER TABLE consolidation_group ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1",
    ):
        bind.execute(text(ddl))

    bind.execute(text("""
        DO $$
        BEGIN
            ALTER TABLE consolidation_group
                ADD CONSTRAINT uq_consolidation_group_name UNIQUE (group_name);
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
    """))

    # Ensured consolidation_group_id exists on legal_entity
    bind.execute(text("ALTER TABLE legal_entity ADD COLUMN IF NOT EXISTS consolidation_group_id UUID;"))

    bind.execute(text("""
        DO $$
        BEGIN
            ALTER TABLE legal_entity
                ADD CONSTRAINT fk_legal_entity_consolidation_group
                FOREIGN KEY (consolidation_group_id) REFERENCES consolidation_group(id);
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
    """))


def downgrade() -> None:
    op.execute("ALTER TABLE legal_entity DROP CONSTRAINT IF EXISTS fk_legal_entity_consolidation_group;")
    op.execute("DROP TABLE IF EXISTS legal_entity_branch CASCADE;")
    op.execute("DROP TABLE IF EXISTS consolidation_group CASCADE;")
    