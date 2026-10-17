"""fix ops C final

Revision ID: <auto>
Revises: 8b8b6dff853b
Create Date: ...
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '<auto>'
down_revision = '8b8b6dff853b' # Sesuaikan dengan revisi terakhir
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Paksa kolom legal_entity_id menjadi NOT NULL di tabel purchase_order_line
    op.alter_column('purchase_order_line', 'legal_entity_id', nullable=False, existing_type=sa.UUID())

def downgrade() -> None:
    op.alter_column('purchase_order_line', 'legal_entity_id', nullable=True, existing_type=sa.UUID())
    