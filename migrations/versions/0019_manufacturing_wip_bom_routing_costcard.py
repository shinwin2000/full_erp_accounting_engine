"""create manufacturing tables: work_order, bill_of_materials, routing, work_in_process, cost_card

Revision ID: 0019
Revises: 0018
Create Date: 2025-01-01 00:00:18.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, NUMERIC

revision: str = '0019'
down_revision = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'work_order',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('work_order_number', sa.String(50), nullable=False),
        sa.Column('product_id', UUID(as_uuid=True), nullable=False),
        sa.Column('product_name', sa.String(200), nullable=True),
        sa.Column('planned_quantity', NUMERIC(20, 2), nullable=False),
        sa.Column('completed_quantity', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('rejected_quantity', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('bom_id', UUID(as_uuid=True), nullable=True),
        sa.Column('routing_id', UUID(as_uuid=True), nullable=True),
        sa.Column('planned_start_date', sa.Date, nullable=False),
        sa.Column('planned_end_date', sa.Date, nullable=False),
        sa.Column('actual_start_date', sa.Date, nullable=True),
        sa.Column('actual_end_date', sa.Date, nullable=True),
        sa.Column('standard_cost', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('actual_cost', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='planned'),
        sa.Column('cost_center', sa.String(20), nullable=True),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_work_order_number', 'work_order', ['work_order_number'])
    op.create_index('idx_work_order_product', 'work_order', ['product_id'])
    op.create_index('idx_work_order_status', 'work_order', ['status'])
    op.create_index('idx_work_order_legal_entity', 'work_order', ['legal_entity_id'])
    op.create_index('idx_work_order_bom', 'work_order', ['bom_id'])
    op.create_unique_constraint('uq_work_order_number_legal_entity', 'work_order', ['work_order_number', 'legal_entity_id'])
    op.create_foreign_key('fk_work_order_legal_entity', 'work_order', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_work_order_status', 'work_order', "status IN ('planned', 'released', 'in_progress', 'completed', 'cancelled', 'closed')")
    op.create_check_constraint('ck_work_order_planned_positive', 'work_order', 'planned_quantity > 0')
    op.create_check_constraint('ck_work_order_completed_nonneg', 'work_order', 'completed_quantity >= 0')
    op.create_check_constraint('ck_work_order_rejected_nonneg', 'work_order', 'rejected_quantity >= 0')

    op.create_table(
        'bill_of_materials',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('bom_code', sa.String(50), nullable=False),
        sa.Column('bom_name', sa.String(200), nullable=False),
        sa.Column('product_id', UUID(as_uuid=True), nullable=False),
        sa.Column('product_name', sa.String(200), nullable=True),
        sa.Column('bom_version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('effective_date', sa.Date, nullable=False),
        sa.Column('expiry_date', sa.Date, nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('is_default', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_bom_code', 'bill_of_materials', ['bom_code'])
    op.create_index('idx_bom_product', 'bill_of_materials', ['product_id'])
    op.create_index('idx_bom_status', 'bill_of_materials', ['status'])
    op.create_index('idx_bom_legal_entity', 'bill_of_materials', ['legal_entity_id'])
    op.create_unique_constraint('uq_bom_code_legal_entity', 'bill_of_materials', ['bom_code', 'legal_entity_id'])
    op.create_foreign_key('fk_bom_legal_entity', 'bill_of_materials', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_bom_status', 'bill_of_materials', "status IN ('draft', 'active', 'inactive', 'obsolete')")

    op.create_table(
        'bill_of_materials_line',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('bom_id', UUID(as_uuid=True), nullable=False),
        sa.Column('line_number', sa.Integer, nullable=False),
        sa.Column('component_item_id', UUID(as_uuid=True), nullable=False),
        sa.Column('component_code', sa.String(30), nullable=False),
        sa.Column('component_name', sa.String(200), nullable=True),
        sa.Column('quantity', NUMERIC(20, 2), nullable=False),
        sa.Column('scrap_percent', NUMERIC(5, 2), nullable=False, server_default='0'),
        sa.Column('unit_of_measure', sa.String(10), nullable=False, server_default='pcs'),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
    )
    op.create_index('idx_bom_line_bom', 'bill_of_materials_line', ['bom_id'])
    op.create_index('idx_bom_line_component', 'bill_of_materials_line', ['component_item_id'])
    op.create_index('idx_bom_line_number', 'bill_of_materials_line', ['bom_id', 'line_number'])
    op.create_foreign_key('fk_bom_line_bom', 'bill_of_materials_line', 'bill_of_materials', ['bom_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_bom_line_component', 'bill_of_materials_line', 'inventory_item', ['component_item_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_bom_line_legal_entity', 'bill_of_materials_line', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_bom_line_quantity_positive', 'bill_of_materials_line', 'quantity > 0')
    op.create_check_constraint('ck_bom_line_scrap_range', 'bill_of_materials_line', 'scrap_percent BETWEEN 0 AND 100')

    op.create_table(
        'routing',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('routing_code', sa.String(50), nullable=False),
        sa.Column('routing_name', sa.String(200), nullable=False),
        sa.Column('product_id', UUID(as_uuid=True), nullable=False),
        sa.Column('routing_version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('effective_date', sa.Date, nullable=False),
        sa.Column('expiry_date', sa.Date, nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('is_default', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_routing_code', 'routing', ['routing_code'])
    op.create_index('idx_routing_product', 'routing', ['product_id'])
    op.create_index('idx_routing_status', 'routing', ['status'])
    op.create_unique_constraint('uq_routing_code_legal_entity', 'routing', ['routing_code', 'legal_entity_id'])
    op.create_foreign_key('fk_routing_legal_entity', 'routing', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_routing_status', 'routing', "status IN ('draft', 'active', 'inactive', 'obsolete')")

    op.create_table(
        'routing_step',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('routing_id', UUID(as_uuid=True), nullable=False),
        sa.Column('step_number', sa.Integer, nullable=False),
        sa.Column('work_center', sa.String(100), nullable=False),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('setup_time_hours', NUMERIC(10, 2), nullable=False, server_default='0'),
        sa.Column('run_time_hours', NUMERIC(10, 2), nullable=False),
        sa.Column('machine_hours', NUMERIC(10, 2), nullable=False, server_default='0'),
        sa.Column('labor_hours', NUMERIC(10, 2), nullable=False),
        sa.Column('queue_time_hours', NUMERIC(10, 2), nullable=False, server_default='0'),
        sa.Column('move_time_hours', NUMERIC(10, 2), nullable=False, server_default='0'),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
    )
    op.create_index('idx_routing_step_routing', 'routing_step', ['routing_id'])
    op.create_index('idx_routing_step_number', 'routing_step', ['routing_id', 'step_number'])
    op.create_foreign_key('fk_routing_step_routing', 'routing_step', 'routing', ['routing_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_routing_step_legal_entity', 'routing_step', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_routing_step_time_nonneg', 'routing_step', 'setup_time_hours >= 0 AND run_time_hours >= 0 AND machine_hours >= 0 AND labor_hours >= 0')

    op.create_table(
        'work_in_process',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('work_order_id', UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', UUID(as_uuid=True), nullable=False),
        sa.Column('product_name', sa.String(200), nullable=True),
        sa.Column('quantity_started', NUMERIC(20, 2), nullable=False),
        sa.Column('quantity_remaining', NUMERIC(20, 2), nullable=False),
        sa.Column('material_cost', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('labor_cost', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('overhead_cost', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('total_cost', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('start_date', sa.Date, nullable=False),
        sa.Column('expected_completion_date', sa.Date, nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
    )
    op.create_index('idx_wip_work_order', 'work_in_process', ['work_order_id'])
    op.create_index('idx_wip_product', 'work_in_process', ['product_id'])
    op.create_foreign_key('fk_wip_work_order', 'work_in_process', 'work_order', ['work_order_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_wip_legal_entity', 'work_in_process', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_wip_quantity_positive', 'work_in_process', 'quantity_started > 0')
    op.create_check_constraint('ck_wip_quantity_remaining', 'work_in_process', 'quantity_remaining >= 0')
    op.create_check_constraint('ck_wip_quantity_remaining_not_exceed', 'work_in_process', 'quantity_remaining <= quantity_started')

    op.create_table(
        'cost_card',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('cost_card_code', sa.String(50), nullable=False),
        sa.Column('product_id', UUID(as_uuid=True), nullable=False),
        sa.Column('product_name', sa.String(200), nullable=True),
        sa.Column('effective_date', sa.Date, nullable=False),
        sa.Column('expiry_date', sa.Date, nullable=True),
        sa.Column('cost_card_version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('material_cost', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('labor_cost', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('overhead_cost', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('other_cost', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('total_cost', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('quantity_base', NUMERIC(20, 2), nullable=False, server_default='1'),
        sa.Column('unit_of_measure', sa.String(10), nullable=False, server_default='pcs'),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('breakdown', sa.JSON, nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_cost_card_code', 'cost_card', ['cost_card_code'])
    op.create_index('idx_cost_card_product', 'cost_card', ['product_id'])
    op.create_index('idx_cost_card_status', 'cost_card', ['status'])
    op.create_index('idx_cost_card_effective_date', 'cost_card', ['effective_date'])
    op.create_index('idx_cost_card_legal_entity', 'cost_card', ['legal_entity_id'])
    op.create_unique_constraint('uq_cost_card_code_legal_entity', 'cost_card', ['cost_card_code', 'legal_entity_id'])
    op.create_foreign_key('fk_cost_card_legal_entity', 'cost_card', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_cost_card_status', 'cost_card', "status IN ('draft', 'active', 'inactive', 'obsolete')")
    op.create_check_constraint('ck_cost_card_total_nonneg', 'cost_card', 'total_cost >= 0')

    op.create_foreign_key('fk_work_order_bom', 'work_order', 'bill_of_materials', ['bom_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_work_order_routing', 'work_order', 'routing', ['routing_id'], ['id'], ondelete='SET NULL')

def downgrade() -> None:
    op.drop_constraint('fk_work_order_bom', 'work_order', type_='foreignkey')
    op.drop_constraint('fk_work_order_routing', 'work_order', type_='foreignkey')

    op.drop_constraint('fk_cost_card_legal_entity', 'cost_card', type_='foreignkey')
    op.drop_constraint('uq_cost_card_code_legal_entity', 'cost_card', type_='unique')
    op.drop_constraint('ck_cost_card_status', 'cost_card', type_='check')
    op.drop_constraint('ck_cost_card_total_nonneg', 'cost_card', type_='check')
    op.drop_index('idx_cost_card_code', table_name='cost_card')
    op.drop_index('idx_cost_card_product', table_name='cost_card')
    op.drop_index('idx_cost_card_status', table_name='cost_card')
    op.drop_index('idx_cost_card_effective_date', table_name='cost_card')
    op.drop_index('idx_cost_card_legal_entity', table_name='cost_card')
    op.drop_table('cost_card')

    op.drop_constraint('fk_wip_work_order', 'work_in_process', type_='foreignkey')
    op.drop_constraint('fk_wip_legal_entity', 'work_in_process', type_='foreignkey')
    op.drop_constraint('ck_wip_quantity_positive', 'work_in_process', type_='check')
    op.drop_constraint('ck_wip_quantity_remaining', 'work_in_process', type_='check')
    op.drop_constraint('ck_wip_quantity_remaining_not_exceed', 'work_in_process', type_='check')
    op.drop_index('idx_wip_work_order', table_name='work_in_process')
    op.drop_index('idx_wip_product', table_name='work_in_process')
    op.drop_table('work_in_process')

    op.drop_constraint('fk_routing_step_routing', 'routing_step', type_='foreignkey')
    op.drop_constraint('fk_routing_step_legal_entity', 'routing_step', type_='foreignkey')
    op.drop_constraint('ck_routing_step_time_nonneg', 'routing_step', type_='check')
    op.drop_index('idx_routing_step_routing', table_name='routing_step')
    op.drop_index('idx_routing_step_number', table_name='routing_step')
    op.drop_table('routing_step')

    op.drop_constraint('fk_routing_legal_entity', 'routing', type_='foreignkey')
    op.drop_constraint('uq_routing_code_legal_entity', 'routing', type_='unique')
    op.drop_constraint('ck_routing_status', 'routing', type_='check')
    op.drop_index('idx_routing_code', table_name='routing')
    op.drop_index('idx_routing_product', table_name='routing')
    op.drop_index('idx_routing_status', table_name='routing')
    op.drop_table('routing')

    op.drop_constraint('fk_bom_line_bom', 'bill_of_materials_line', type_='foreignkey')
    op.drop_constraint('fk_bom_line_component', 'bill_of_materials_line', type_='foreignkey')
    op.drop_constraint('fk_bom_line_legal_entity', 'bill_of_materials_line', type_='foreignkey')
    op.drop_constraint('ck_bom_line_quantity_positive', 'bill_of_materials_line', type_='check')
    op.drop_constraint('ck_bom_line_scrap_range', 'bill_of_materials_line', type_='check')
    op.drop_index('idx_bom_line_bom', table_name='bill_of_materials_line')
    op.drop_index('idx_bom_line_component', table_name='bill_of_materials_line')
    op.drop_index('idx_bom_line_number', table_name='bill_of_materials_line')
    op.drop_table('bill_of_materials_line')

    op.drop_constraint('fk_bom_legal_entity', 'bill_of_materials', type_='foreignkey')
    op.drop_constraint('uq_bom_code_legal_entity', 'bill_of_materials', type_='unique')
    op.drop_constraint('ck_bom_status', 'bill_of_materials', type_='check')
    op.drop_index('idx_bom_code', table_name='bill_of_materials')
    op.drop_index('idx_bom_product', table_name='bill_of_materials')
    op.drop_index('idx_bom_status', table_name='bill_of_materials')
    op.drop_index('idx_bom_legal_entity', table_name='bill_of_materials')
    op.drop_table('bill_of_materials')

    op.drop_constraint('fk_work_order_legal_entity', 'work_order', type_='foreignkey')
    op.drop_constraint('uq_work_order_number_legal_entity', 'work_order', type_='unique')
    op.drop_constraint('ck_work_order_status', 'work_order', type_='check')
    op.drop_constraint('ck_work_order_planned_positive', 'work_order', type_='check')
    op.drop_constraint('ck_work_order_completed_nonneg', 'work_order', type_='check')
    op.drop_constraint('ck_work_order_rejected_nonneg', 'work_order', type_='check')
    op.drop_index('idx_work_order_number', table_name='work_order')
    op.drop_index('idx_work_order_product', table_name='work_order')
    op.drop_index('idx_work_order_status', table_name='work_order')
    op.drop_index('idx_work_order_legal_entity', table_name='work_order')
    op.drop_index('idx_work_order_bom', table_name='work_order')
    op.drop_table('work_order')