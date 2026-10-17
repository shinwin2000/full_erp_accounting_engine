"""sync manufacturing cost card types and add ar_debit_notes

Revision ID: <auto>
Revises: 0055_cost_card_le_constraints
Create Date: 2026-10-17 ...
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'a0f4948ebc11'
down_revision = '0055_cost_card_le_constraints'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'manufacturing_cost_card' in inspector.get_table_names():
        # other_cost: NUMERIC(18,2) -> NUMERIC(20,2)
        op.alter_column(
            'manufacturing_cost_card',
            'other_cost',
            existing_type=sa.Numeric(18, 2),
            type_=sa.Numeric(20, 2),
            existing_nullable=False,
        )
        # unit_of_measure: VARCHAR(10) -> VARCHAR(20)
        op.alter_column(
            'manufacturing_cost_card',
            'unit_of_measure',
            existing_type=sa.String(10),
            type_=sa.String(20),
            existing_nullable=False,
        )

    if 'ar_debit_notes' not in inspector.get_table_names():
        op.create_table(
            'ar_debit_notes',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column('debit_note_number', sa.String(50), nullable=False, unique=True),
            sa.Column(
                'invoice_id',
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey('ar_invoice.id'),
                nullable=False,
            ),
            sa.Column('debit_note_date', sa.DateTime(timezone=True), nullable=False),
            sa.Column('amount', sa.Numeric(20, 2), nullable=False),
            sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
            sa.Column('reason', sa.Text(), nullable=True),
            sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
            sa.Column(
                'created_at',
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'manufacturing_cost_card' in inspector.get_table_names():
        op.alter_column(
            'manufacturing_cost_card',
            'unit_of_measure',
            existing_type=sa.String(20),
            type_=sa.String(10),
            existing_nullable=False,
        )
        op.alter_column(
            'manufacturing_cost_card',
            'other_cost',
            existing_type=sa.Numeric(20, 2),
            type_=sa.Numeric(18, 2),
            existing_nullable=False,
        )

    if 'ar_debit_notes' in inspector.get_table_names():
        op.drop_table('ar_debit_notes')