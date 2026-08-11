"""resolve_final_schema_drift

Revision ID: 645713879b2d
Revises: f713e2633e6a
Create Date: 2026-04-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '645713879b2d'
down_revision = 'f713e2633e6a'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Safely create index if it doesn't already exist
    op.create_index('idx_cost_card_product', 'manufacturing_cost_card', ['product_id'], unique=False, if_not_exists=True)

def downgrade() -> None:
    op.drop_index('idx_cost_card_product', table_name='manufacturing_cost_card', if_exists=True)
