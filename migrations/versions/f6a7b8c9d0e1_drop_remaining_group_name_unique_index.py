"""drop_remaining_group_name_unique_index

Migrasi sebelumnya (e5f6a7b8c9d0) menduga hanya ada 2 kemungkinan nama
constraint unique lama di group_name (idx_cons_group_name dan
consolidation_group_group_name_key) dan men-drop keduanya, lalu membuat
partial unique index idx_cons_group_name_active sebagai gantinya.

Ternyata ada index/constraint unique KETIGA (bahkan KEEMPAT) yang masih
hidup: ix_consolidation_group_group_name (index auto-generate SQLAlchemy
dari kombinasi unique=True + index=True yang dulu ada di kolom
group_name) dan uq_consolidation_group_name (CONSTRAINT unique bernama,
bukan sekadar index - butuh ALTER TABLE ... DROP CONSTRAINT, bukan DROP
INDEX, atau Postgres menolak dengan DependentObjectsStillExistError).
Migrasi ini query pg_constraint + pg_indexes secara dinamis supaya
menangkap constraint/index unique apa pun pada group_name yang masih
tersisa dari riwayat migrasi proyek yang berantakan, tanpa perlu menebak
nama satu-satu lagi. Aman dijalankan ulang (semua IF EXISTS).

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-13 05:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Drop constraint UNIQUE apa pun (bukan index biasa - constraint
    # harus di-drop lewat ALTER TABLE ... DROP CONSTRAINT, DROP INDEX akan
    # gagal dengan DependentObjectsStillExistError kalau index itu backing
    # sebuah constraint). Cari by nama constraint yang menyentuh kolom
    # group_name, drop semuanya kecuali (tidak ada, karena partial index
    # idx_cons_group_name_active dibuat sebagai INDEX langsung, bukan
    # constraint, jadi tidak akan ketemu di query ini).
    result = bind.execute(text("""
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = ANY(con.conkey)
        WHERE rel.relname = 'consolidation_group'
          AND con.contype = 'u'
          AND att.attname = 'group_name';
    """))
    for row in result:
        bind.execute(text(f'ALTER TABLE consolidation_group DROP CONSTRAINT IF EXISTS "{row[0]}";'))

    # 2) Drop index unique unconditional APAPUN pada group_name yang masih
    # tersisa dan TIDAK backing constraint manapun (constraint-backed sudah
    # ditangani di langkah 1 - index-nya otomatis ikut hilang saat
    # constraint-nya di-drop).
    result = bind.execute(text("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'consolidation_group'
          AND indexdef ILIKE '%UNIQUE%'
          AND indexdef ILIKE '%group_name%'
          AND indexname != 'idx_cons_group_name_active';
    """))
    for row in result:
        bind.execute(text(f'DROP INDEX IF EXISTS "{row[0]}";'))


def downgrade() -> None:
    # Tidak ada downgrade yang aman - index yang di-drop di sini namanya
    # dinamis/tidak diketahui pasti. Kalau perlu rollback, buat ulang index
    # unique unconditional secara manual.
    pass
