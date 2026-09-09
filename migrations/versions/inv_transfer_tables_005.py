"""create inter_warehouse_transfer and inter_warehouse_transfer_line tables

Revision ID: inv_transfer_tables_005
Revises: inv_opname_line_warehouse_nullable_004
Create Date: 2026-09-08 06:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID

# revision identifiers, used by Alembic.
revision = 'inv_transfer_tables_005'
down_revision = 'inv_opname_wh_null_004'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'inter_warehouse_transfer',
        sa.Column('id', PGUUID(as_uuid=True), primary_key=True),
        sa.Column('legal_entity_id', PGUUID(as_uuid=True), sa.ForeignKey('legal_entity.id'), nullable=False),
        sa.Column('transfer_number', sa.String(50), nullable=False),
        sa.Column('source_warehouse_id', PGUUID(as_uuid=True), sa.ForeignKey('warehouse.id', ondelete='SET NULL'), nullable=True),
        sa.Column('source_warehouse_name', sa.String(200), nullable=False, server_default=''),
        sa.Column('destination_warehouse_id', PGUUID(as_uuid=True), sa.ForeignKey('warehouse.id', ondelete='SET NULL'), nullable=True),
        sa.Column('destination_warehouse_name', sa.String(200), nullable=False, server_default=''),
        sa.Column('transfer_date', sa.Date(), nullable=False),
        sa.Column('priority', sa.String(20), nullable=False, server_default='normal'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('quantity', sa.Numeric(20, 6), nullable=False, server_default='0'),
        sa.Column('unit_cost', sa.Numeric(20, 2), nullable=False, server_default='0'),
        sa.Column('total_value', sa.Numeric(20, 2), nullable=False, server_default='0'),
        sa.Column('reason', sa.String(500), nullable=True),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('requested_by', PGUUID(as_uuid=True), nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', PGUUID(as_uuid=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('shipped_by', PGUUID(as_uuid=True), nullable=True),
        sa.Column('shipped_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('received_by', PGUUID(as_uuid=True), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_by', PGUUID(as_uuid=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', PGUUID(as_uuid=True), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('transfer_number', 'legal_entity_id', name='uq_inter_warehouse_transfer_number_legal_entity'),
    )
    op.create_index(
        'idx_inter_warehouse_transfer_status', 'inter_warehouse_transfer', ['status', 'legal_entity_id']
    )

    op.create_table(
        'inter_warehouse_transfer_line',
        sa.Column('id', PGUUID(as_uuid=True), primary_key=True),
        sa.Column('transfer_id', PGUUID(as_uuid=True), sa.ForeignKey('inter_warehouse_transfer.id', ondelete='CASCADE'), nullable=False),
        sa.Column('item_id', PGUUID(as_uuid=True), nullable=False),
        sa.Column('item_sku', sa.String(64), nullable=False),
        sa.Column('item_name', sa.String(200), nullable=False),
        sa.Column('quantity', sa.Numeric(20, 6), nullable=False),
        sa.Column('unit_cost', sa.Numeric(20, 2), nullable=False, server_default='0'),
        sa.Column('total_value', sa.Numeric(20, 2), nullable=False, server_default='0'),
        sa.Column('batch_number', sa.String(50), nullable=True),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'idx_inter_warehouse_transfer_line_transfer_id', 'inter_warehouse_transfer_line', ['transfer_id']
    )
    op.create_index(
        'idx_inter_warehouse_transfer_line_item_id', 'inter_warehouse_transfer_line', ['item_id']
    )


def downgrade():
    op.drop_index('idx_inter_warehouse_transfer_line_item_id', table_name='inter_warehouse_transfer_line')
    op.drop_index('idx_inter_warehouse_transfer_line_transfer_id', table_name='inter_warehouse_transfer_line')
    op.drop_table('inter_warehouse_transfer_line')
    op.drop_index('idx_inter_warehouse_transfer_status', table_name='inter_warehouse_transfer')
    op.drop_table('inter_warehouse_transfer')
