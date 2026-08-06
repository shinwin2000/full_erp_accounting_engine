"""sync work order bom foreign key

Revision ID: b39403e62281
Revises: 81de37e7a243
Create Date: 2026-08-05

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b39403e62281'
down_revision = '81de37e7a243'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Menambahkan foreign key dari work_order.bom_id ke bill_of_materials.id
    op.create_foreign_key(
        'fk_work_order_bom_id_bill_of_materials',
        'work_order',
        'bill_of_materials',
        ['bom_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    # Menghapus foreign key jika dilakukan rollback (downgrade)
    op.drop_constraint(
        'fk_work_order_bom_id_bill_of_materials', 
        'work_order', 
        type_='foreignkey'
    )