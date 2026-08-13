"""extend_consolidation_group_member

Menu "Grup Konsolidasi" di frontend memanggil /api/v1/consolidation/
consolidation/groups (ConsolidationService), TERPISAH dari jalur
LegalEntityService yang sudah dibenahi migrasi c3d4e5f6a7b8. Investigasi
lanjutan menemukan ConsolidationService tidak pernah didaftarkan ke IoC
container (fixed di service_registry.py) DAN belum punya method
create_group/list_groups/get_group_by_id/update_group/deactivate_group/
add_member/remove_member sama sekali (endpoint router selalu
AttributeError). Menambahkan method2 tsb butuh 3 kolom tambahan di
consolidation_group_member yang belum ada di skema manapun sebelumnya:
consolidation_method, effective_date, notes.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-12 08:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    for ddl in (
        "ALTER TABLE consolidation_group_member ADD COLUMN IF NOT EXISTS "
        "consolidation_method VARCHAR(20) NOT NULL DEFAULT 'full'",
        "ALTER TABLE consolidation_group_member ADD COLUMN IF NOT EXISTS "
        "effective_date DATE",
        "ALTER TABLE consolidation_group_member ADD COLUMN IF NOT EXISTS "
        "notes TEXT",
        "ALTER TABLE consolidation_group ADD COLUMN IF NOT EXISTS "
        "parent_entity_id UUID",
    ):
        bind.execute(text(ddl))
    bind.execute(text("""
        DO $$
        BEGIN
            ALTER TABLE consolidation_group
                ADD CONSTRAINT fk_consolidation_group_parent_entity
                FOREIGN KEY (parent_entity_id) REFERENCES legal_entity(id);
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
    """))


def downgrade() -> None:
    op.execute("ALTER TABLE consolidation_group DROP CONSTRAINT IF EXISTS fk_consolidation_group_parent_entity;")
    op.execute("ALTER TABLE consolidation_group DROP COLUMN IF EXISTS parent_entity_id;")
    op.execute("ALTER TABLE consolidation_group_member DROP COLUMN IF EXISTS consolidation_method;")
    op.execute("ALTER TABLE consolidation_group_member DROP COLUMN IF EXISTS effective_date;")
    op.execute("ALTER TABLE consolidation_group_member DROP COLUMN IF EXISTS notes;")
