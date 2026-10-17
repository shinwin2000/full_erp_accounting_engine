"""fix ops C kategori 2

Revision ID: 8b8b6dff853b
Revises: 38dd987a2fc4
Create Date: 2026-10-17 ...
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '8b8b6dff853b'
down_revision = '38dd987a2fc4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    # 1. Hapus FK parent_entity_id di consolidation_group (jika ada)
    # Ambil semua constraint di tabel consolidation_group
    existing_fks = [fk['name'] for fk in inspector.get_foreign_keys('consolidation_group')]
    if 'consolidation_group_parent_entity_id_fkey' in existing_fks:
        op.drop_constraint('consolidation_group_parent_entity_id_fkey', 'consolidation_group', type_='foreignkey')
    else:
        print("INFO: FK consolidation_group_parent_entity_id_fkey tidak ditemukan, dilewati.")

    # 2. Hapus FK consolidation_group_id di legal_entity (jika ada)
    existing_fks_le = [fk['name'] for fk in inspector.get_foreign_keys('legal_entity')]
    if 'legal_entity_consolidation_group_id_fkey' in existing_fks_le:
        op.drop_constraint('legal_entity_consolidation_group_id_fkey', 'legal_entity', type_='foreignkey')
    else:
        print("INFO: FK legal_entity_consolidation_group_id_fkey tidak ditemukan, dilewati.")

    # 3. Perbaiki FK parent_entity_id di legal_entity_branch (jika ada)
    existing_fks_leb = [fk['name'] for fk in inspector.get_foreign_keys('legal_entity_branch')]
    if 'legal_entity_branch_parent_entity_id_fkey' in existing_fks_leb:
        op.drop_constraint('legal_entity_branch_parent_entity_id_fkey', 'legal_entity_branch', type_='foreignkey')
    
    # Tambahkan kembali FK di legal_entity_branch dengan ondelete SET NULL
    # (Cek dulu apakah FK dengan ondelete SET NULL sudah ada, jika belum, buat)
    op.create_foreign_key(
        'legal_entity_branch_parent_entity_id_fkey', 
        'legal_entity_branch', 'legal_entity_branch', 
        ['parent_entity_id'], ['id'], 
        ondelete='SET NULL'
    )


def downgrade() -> None:
    # Rollback jika diperlukan
    pass
