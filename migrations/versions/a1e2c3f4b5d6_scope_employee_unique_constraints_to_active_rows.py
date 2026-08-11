"""scope_employee_unique_constraints_to_active_rows

Employee uniqueness (employee_code+legal_entity_id, nik, email, tax_id) was
enforced with plain table-level UniqueConstraints, which apply to ALL rows
including soft-deleted ones (deleted_at IS NOT NULL). Since every read path
in the app treats a soft-deleted employee as "gone" (filters
deleted_at.is_(None)), a deleted employee's code/nik/email/tax_id becomes
permanently unusable even though the app itself considers that employee
removed. This migration replaces the plain unique constraints with partial
unique indexes that only apply to active (non-deleted) rows.

Revision ID: a1e2c3f4b5d6
Revises: ebe26e77bd06
Create Date: 2026-08-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1e2c3f4b5d6'
down_revision: Union[str, None] = 'ebe26e77bd06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the old blanket unique constraints (they include soft-deleted rows).
    op.drop_constraint('uq_employee_code_legal_entity', 'employee', type_='unique')
    op.drop_constraint('uq_employee_nik', 'employee', type_='unique')
    op.drop_constraint('uq_employee_email', 'employee', type_='unique')
    op.drop_constraint('uq_employee_tax_id', 'employee', type_='unique')

    # Recreate them as partial unique indexes scoped to active rows only,
    # so soft-deleted employees no longer permanently reserve their code,
    # nik, email, or tax_id.
    op.create_index(
        'uq_employee_code_legal_entity',
        'employee',
        ['employee_code', 'legal_entity_id'],
        unique=True,
        postgresql_where=sa.text('deleted_at IS NULL'),
    )
    op.create_index(
        'uq_employee_nik',
        'employee',
        ['nik'],
        unique=True,
        postgresql_where=sa.text('deleted_at IS NULL AND nik IS NOT NULL'),
    )
    op.create_index(
        'uq_employee_email',
        'employee',
        ['email'],
        unique=True,
        postgresql_where=sa.text('deleted_at IS NULL AND email IS NOT NULL'),
    )
    op.create_index(
        'uq_employee_tax_id',
        'employee',
        ['tax_id'],
        unique=True,
        postgresql_where=sa.text('deleted_at IS NULL AND tax_id IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_employee_code_legal_entity', table_name='employee')
    op.drop_index('uq_employee_nik', table_name='employee')
    op.drop_index('uq_employee_email', table_name='employee')
    op.drop_index('uq_employee_tax_id', table_name='employee')

    op.create_unique_constraint(
        'uq_employee_code_legal_entity', 'employee', ['employee_code', 'legal_entity_id']
    )
    op.create_unique_constraint('uq_employee_nik', 'employee', ['nik'])
    op.create_unique_constraint('uq_employee_email', 'employee', ['email'])
    op.create_unique_constraint('uq_employee_tax_id', 'employee', ['tax_id'])
