"""create project, time_entry, retainer_contract tables

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-30 12:15:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP

revision: str = '0023abcd'
down_revision = '0022abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'project',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('project_code', sa.String(50), nullable=False, unique=True),
        sa.Column('project_name', sa.String(200), nullable=False),
        sa.Column('customer_id', UUID(as_uuid=True), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='DRAFT'),
        sa.Column('budget_total', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('cost_to_date', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('revenue_to_date', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('contract_type', sa.String(30), nullable=False),
        sa.Column('contract_value', sa.Numeric(18, 2), nullable=False),
        sa.Column('currency_code', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('manager_employee_id', UUID(as_uuid=True), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=False),
        sa.Column('updated_by', UUID(as_uuid=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.create_index('ix_project_legal_entity', 'project', ['legal_entity_id'])
    op.create_index('ix_project_customer', 'project', ['customer_id'])
    op.create_index('ix_project_status', 'project', ['status'])

    op.create_table(
        'time_entry',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('employee_id', UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', UUID(as_uuid=True), nullable=False),
        sa.Column('work_date', sa.Date(), nullable=False),
        sa.Column('hours', sa.Numeric(6, 2), nullable=False),
        sa.Column('hourly_rate', sa.Numeric(18, 2), nullable=False),
        sa.Column('total_amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_billed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('billed_invoice_id', UUID(as_uuid=True), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=False),
        sa.Column('updated_by', UUID(as_uuid=True), nullable=False),
    )
    op.create_index('ix_time_entry_employee', 'time_entry', ['employee_id', 'work_date'])
    op.create_index('ix_time_entry_project', 'time_entry', ['project_id'])

    op.create_table(
        'retainer_contract',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('customer_id', UUID(as_uuid=True), nullable=False),
        sa.Column('contract_number', sa.String(50), nullable=False, unique=True),
        sa.Column('monthly_fee', sa.Numeric(18, 2), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='ACTIVE'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=False),
        sa.Column('updated_by', UUID(as_uuid=True), nullable=False),
    )

    op.create_foreign_key('fk_time_entry_project', 'time_entry', 'project', ['project_id'], ['id'])
    op.create_foreign_key('fk_time_entry_employee', 'time_entry', 'employee', ['employee_id'], ['id'])
    op.create_foreign_key('fk_project_customer', 'project', 'customer', ['customer_id'], ['id'])
    op.create_foreign_key('fk_retainer_customer', 'retainer_contract', 'customer', ['customer_id'], ['id'])

def downgrade() -> None:
    op.drop_constraint('fk_time_entry_project', 'time_entry', type_='foreignkey')
    op.drop_constraint('fk_time_entry_employee', 'time_entry', type_='foreignkey')
    op.drop_constraint('fk_project_customer', 'project', type_='foreignkey')
    op.drop_constraint('fk_retainer_customer', 'retainer_contract', type_='foreignkey')
    op.drop_table('retainer_contract')
    op.drop_table('time_entry')
    op.drop_table('project')