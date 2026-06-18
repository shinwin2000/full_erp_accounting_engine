"""create projection_ar_aging and projection_ap_aging tables

Revision ID: 0027
Revises: 0026
Create Date: 2026-05-30 13:15:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP

revision: str = '0027'
down_revision = '0026'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'projection_ar_aging',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('customer_id', UUID(as_uuid=True), nullable=False),
        sa.Column('as_of_date', sa.Date(), nullable=False),
        sa.Column('current_amount', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('days_1_30', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('days_31_60', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('days_61_90', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('days_above_90', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('total_outstanding', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('expected_credit_loss', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('last_updated_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('last_updated_by', UUID(as_uuid=True), nullable=False),
    )
    op.create_index('ix_projection_ar_aging_entity_customer', 'projection_ar_aging', ['legal_entity_id', 'customer_id', 'as_of_date'], unique=True)

    op.create_table(
        'projection_ap_aging',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('supplier_id', UUID(as_uuid=True), nullable=False),
        sa.Column('as_of_date', sa.Date(), nullable=False),
        sa.Column('current_amount', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('days_1_30', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('days_31_60', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('days_61_90', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('days_above_90', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('total_outstanding', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('expected_credit_loss', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('last_updated_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('last_updated_by', UUID(as_uuid=True), nullable=False),
    )
    op.create_index('ix_projection_ap_aging_entity_supplier', 'projection_ap_aging', ['legal_entity_id', 'supplier_id', 'as_of_date'], unique=True)

def downgrade() -> None:
    op.drop_table('projection_ap_aging')
    op.drop_table('projection_ar_aging')