"""fix_consolidation_group_name_uniqueness_scope

Bug: constraint unique lama (idx_cons_group_name) berlaku ke SEMUA baris,
termasuk grup yang sudah di-nonaktifkan lewat tombol "Hapus" (soft-delete,
cuma set is_active=False, bukan hard delete). Akibatnya nama grup yang
"sudah dihapus" tidak bisa dipakai lagi untuk grup baru - INSERT selalu
UniqueViolationError. Fix: ganti jadi partial unique index yang HANYA
berlaku untuk baris is_active=true DAN belum di-soft-delete
(deleted_at IS NULL) - nama grup yang nonaktif jadi bebas dipakai ulang.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-13 05:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # Nama index constraint bisa jadi idx_cons_group_name (dari ORM Index)
    # atau nama auto-generate lain kalau ternyata dibuat lewat UNIQUE
    # constraint inline - drop dengan IF EXISTS supaya aman dari kondisi
    # manapun.
    bind.execute(text("DROP INDEX IF EXISTS idx_cons_group_name;"))
    bind.execute(text(
        "ALTER TABLE consolidation_group DROP CONSTRAINT IF EXISTS "
        "consolidation_group_group_name_key;"
    ))
    bind.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_cons_group_name_active
        ON consolidation_group (group_name)
        WHERE is_active = true AND deleted_at IS NULL;
    """))


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_cons_group_name_active;")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_cons_group_name "
        "ON consolidation_group (group_name);"
    )
