"""fix ops C kategori 1

Revision ID: 38dd987a2fc4
Revises: 2c55d6640ec9
Create Date: 2026-10-17 ...
"""
from alembic import op
import sqlalchemy as sa

# GANTI BARIS INI DENGAN NILAI YANG BENAR (Jangan pakai <auto>!)
revision = '38dd987a2fc4'                  # <-- Harus sama dengan nama file
down_revision = 'a0f4948ebc11'            # <-- Harus revision verify_ops_b_final
branch_labels = None
depends_on = None

def upgrade() -> None:
    # 1. Fix budget_revision_history NOT NULL
    op.alter_column('budget_revision_history', 'created_at', nullable=False, existing_type=sa.DateTime())
    op.alter_column('budget_revision_history', 'updated_at', nullable=False, existing_type=sa.DateTime())
    
    # 2. Fix consolidation_group NOT NULL
    op.alter_column('consolidation_group', 'group_code', nullable=False, existing_type=sa.String(50))
    
    # 3. Tambah kolom version di dead_letter_events
    op.add_column('dead_letter_events', sa.Column('version', sa.Integer(), server_default='1', nullable=False))
    
    # 4. Hapus kolom unit_of_measure di purchase_order_line
    op.drop_column('purchase_order_line', 'unit_of_measure')

def downgrade() -> None:
    op.add_column('purchase_order_line', sa.Column('unit_of_measure', sa.String(length=20), nullable=True))
    op.drop_column('dead_letter_events', 'version')
    op.alter_column('consolidation_group', 'group_code', nullable=True, existing_type=sa.String(50))
    op.alter_column('budget_revision_history', 'updated_at', nullable=True, existing_type=sa.DateTime())
    op.alter_column('budget_revision_history', 'created_at', nullable=True, existing_type=sa.DateTime())
