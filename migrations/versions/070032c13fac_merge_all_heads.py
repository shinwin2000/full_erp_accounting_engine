"""merge all heads

Revision ID: 070032c13fac
Revises: 0015invfull, 0047coa, 0047, supp_0047_master_data
Create Date: 2026-08-08 13:36:23.504241

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '070032c13fac'
down_revision = ('0015invfull', '0047coa', '0047', 'supp_0047_master_data')
branch_labels = None
depends_on = None

def upgrade():
    pass

def downgrade():
    pass