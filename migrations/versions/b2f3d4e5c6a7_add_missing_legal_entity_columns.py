"""add_missing_legal_entity_columns

LegalEntityService (application layer) was an in-memory stub that never
touched the database, so the `legal_entity` table never grew columns for
several fields the router's schema (LegalEntityCreateSchema /
LegalEntityResponseSchema) has needed for a while: nppp, province, fax,
notes, is_taxable, is_locked (+ lock audit metadata). This migration adds
them so LegalEntityService can be rewired to persist through
infrastructure.persistence_orm.legal_entity_table.LegalEntityTable instead
of an in-memory dict.

Revision ID: b2f3d4e5c6a7
Revises: a1e2c3f4b5d6
Create Date: 2026-08-11 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b2f3d4e5c6a7'
down_revision: Union[str, None] = 'a1e2c3f4b5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('legal_entity', sa.Column('nppp', sa.String(length=20), nullable=True))
    op.add_column('legal_entity', sa.Column('province', sa.String(length=100), nullable=True))
    op.add_column('legal_entity', sa.Column('fax', sa.String(length=20), nullable=True))
    op.add_column('legal_entity', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column(
        'legal_entity',
        sa.Column('is_taxable', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        'legal_entity',
        sa.Column('is_locked', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column('legal_entity', sa.Column('locked_reason', sa.Text(), nullable=True))
    op.add_column(
        'legal_entity',
        sa.Column('locked_by', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        'legal_entity',
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('legal_entity', 'locked_at')
    op.drop_column('legal_entity', 'locked_by')
    op.drop_column('legal_entity', 'locked_reason')
    op.drop_column('legal_entity', 'is_locked')
    op.drop_column('legal_entity', 'is_taxable')
    op.drop_column('legal_entity', 'notes')
    op.drop_column('legal_entity', 'fax')
    op.drop_column('legal_entity', 'province')
    op.drop_column('legal_entity', 'nppp')
