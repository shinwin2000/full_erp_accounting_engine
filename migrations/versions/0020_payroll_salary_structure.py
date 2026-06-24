"""create payroll tables: payroll_run, salary_component, salary_structure, payroll_adjustment

Revision ID: 0020
Revises: 0019
Create Date: 2025-01-01 00:00:19.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, NUMERIC, JSONB

revision: str = '0020abcd'
down_revision = '0019abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'payroll_run',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('run_number', sa.String(50), nullable=False),
        sa.Column('period_year', sa.Integer, nullable=False),
        sa.Column('period_month', sa.Integer, nullable=False),
        sa.Column('total_employees', sa.Integer, nullable=False, server_default='0'),
        sa.Column('total_net_salary', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('total_tax', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('total_deductions', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('status', sa.String(20), nullable=False, server_default='calculated'),
        sa.Column('approved_by', UUID(as_uuid=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('paid_by', UUID(as_uuid=True), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('payment_run_id', UUID(as_uuid=True), nullable=True),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_payroll_run_legal_entity', 'payroll_run', ['legal_entity_id'])
    op.create_index('idx_payroll_run_period', 'payroll_run', ['period_year', 'period_month'])
    op.create_index('idx_payroll_run_status', 'payroll_run', ['status'])
    op.create_index('idx_payroll_run_number', 'payroll_run', ['run_number'])
    op.create_unique_constraint('uq_payroll_run_number_legal_entity', 'payroll_run', ['run_number', 'legal_entity_id'])
    op.create_foreign_key('fk_payroll_run_legal_entity', 'payroll_run', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_payroll_run_approved_by', 'payroll_run', 'iam_user', ['approved_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_payroll_run_paid_by', 'payroll_run', 'iam_user', ['paid_by'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_payroll_run_status', 'payroll_run', "status IN ('calculated', 'approved', 'paid', 'cancelled')")
    op.create_check_constraint('ck_payroll_run_employees_nonneg', 'payroll_run', 'total_employees >= 0')
    op.create_check_constraint('ck_payroll_run_net_salary_nonneg', 'payroll_run', 'total_net_salary >= 0')

    op.create_table(
        'payroll_detail',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('payroll_run_id', UUID(as_uuid=True), nullable=False),
        sa.Column('employee_id', UUID(as_uuid=True), nullable=False),
        sa.Column('basic_salary', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('overtime_pay', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('allowances', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('bonus', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('gross_income', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('deductions', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('bpjs_jht_employee', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('bpjs_kesehatan_employee', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('tax_pph21', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('net_salary', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('employer_bpjs', JSONB, nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
    )
    op.create_index('idx_payroll_detail_run', 'payroll_detail', ['payroll_run_id'])
    op.create_index('idx_payroll_detail_employee', 'payroll_detail', ['employee_id'])
    op.create_foreign_key('fk_payroll_detail_run', 'payroll_detail', 'payroll_run', ['payroll_run_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_payroll_detail_employee', 'payroll_detail', 'employee', ['employee_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_payroll_detail_legal_entity', 'payroll_detail', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_payroll_detail_net_nonneg', 'payroll_detail', 'net_salary >= 0')

    op.create_table(
        'salary_structure',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('structure_code', sa.String(50), nullable=False),
        sa.Column('structure_name', sa.String(200), nullable=False),
        sa.Column('effective_date', sa.Date, nullable=False),
        sa.Column('expiry_date', sa.Date, nullable=True),
        sa.Column('is_default', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_salary_structure_code', 'salary_structure', ['structure_code'])
    op.create_index('idx_salary_structure_effective', 'salary_structure', ['effective_date'])
    op.create_index('idx_salary_structure_status', 'salary_structure', ['status'])
    op.create_unique_constraint('uq_salary_structure_code_legal_entity', 'salary_structure', ['structure_code', 'legal_entity_id'])
    op.create_foreign_key('fk_salary_structure_legal_entity', 'salary_structure', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_salary_structure_status', 'salary_structure', "status IN ('active', 'inactive', 'archived')")

    op.create_table(
        'salary_component',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('employee_id', UUID(as_uuid=True), nullable=False),
        sa.Column('payroll_run_id', UUID(as_uuid=True), nullable=False),
        sa.Column('component_name', sa.String(100), nullable=False),
        sa.Column('component_type', sa.String(20), nullable=False),
        sa.Column('calculation_type', sa.String(20), nullable=False, server_default='fixed'),
        sa.Column('amount', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('rate_percentage', NUMERIC(5, 2), nullable=True),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_salary_component_employee', 'salary_component', ['employee_id'])
    op.create_index('idx_salary_component_payroll_run', 'salary_component', ['payroll_run_id'])
    op.create_index('idx_salary_component_type', 'salary_component', ['component_type'])
    op.create_foreign_key('fk_salary_component_employee', 'salary_component', 'employee', ['employee_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_salary_component_payroll_run', 'salary_component', 'payroll_run', ['payroll_run_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_salary_component_legal_entity', 'salary_component', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_salary_component_type', 'salary_component', "component_type IN ('earnings', 'deductions', 'tax', 'benefit')")
    op.create_check_constraint('ck_salary_component_calc', 'salary_component', "calculation_type IN ('fixed', 'percentage', 'formula')")
    op.create_check_constraint('ck_salary_component_amount_nonneg', 'salary_component', 'amount >= 0')

    op.create_table(
        'payroll_adjustment',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('employee_id', UUID(as_uuid=True), nullable=False),
        sa.Column('adjustment_date', sa.Date, nullable=False),
        sa.Column('adjustment_type', sa.String(20), nullable=False),
        sa.Column('amount', NUMERIC(20, 2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('reason', sa.Text, nullable=False),
        sa.Column('approved_by', UUID(as_uuid=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('journal_id', UUID(as_uuid=True), nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_payroll_adjustment_employee', 'payroll_adjustment', ['employee_id'])
    op.create_index('idx_payroll_adjustment_date', 'payroll_adjustment', ['adjustment_date'])
    op.create_index('idx_payroll_adjustment_type', 'payroll_adjustment', ['adjustment_type'])
    op.create_foreign_key('fk_payroll_adjustment_employee', 'payroll_adjustment', 'employee', ['employee_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_payroll_adjustment_approved_by', 'payroll_adjustment', 'iam_user', ['approved_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_payroll_adjustment_legal_entity', 'payroll_adjustment', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_payroll_adjustment_type', 'payroll_adjustment', "adjustment_type IN ('salary_correction', 'bonus_adjustment', 'deduction_correction', 'overpayment_recovery')")
    op.create_check_constraint('ck_payroll_adjustment_amount', 'payroll_adjustment', 'amount != 0')

def downgrade() -> None:
    op.drop_constraint('fk_payroll_adjustment_employee', 'payroll_adjustment', type_='foreignkey')
    op.drop_constraint('fk_payroll_adjustment_approved_by', 'payroll_adjustment', type_='foreignkey')
    op.drop_constraint('fk_payroll_adjustment_legal_entity', 'payroll_adjustment', type_='foreignkey')
    op.drop_constraint('ck_payroll_adjustment_type', 'payroll_adjustment', type_='check')
    op.drop_constraint('ck_payroll_adjustment_amount', 'payroll_adjustment', type_='check')
    op.drop_index('idx_payroll_adjustment_employee', table_name='payroll_adjustment')
    op.drop_index('idx_payroll_adjustment_date', table_name='payroll_adjustment')
    op.drop_index('idx_payroll_adjustment_type', table_name='payroll_adjustment')
    op.drop_table('payroll_adjustment')

    op.drop_constraint('fk_salary_component_employee', 'salary_component', type_='foreignkey')
    op.drop_constraint('fk_salary_component_payroll_run', 'salary_component', type_='foreignkey')
    op.drop_constraint('fk_salary_component_legal_entity', 'salary_component', type_='foreignkey')
    op.drop_constraint('ck_salary_component_type', 'salary_component', type_='check')
    op.drop_constraint('ck_salary_component_calc', 'salary_component', type_='check')
    op.drop_constraint('ck_salary_component_amount_nonneg', 'salary_component', type_='check')
    op.drop_index('idx_salary_component_employee', table_name='salary_component')
    op.drop_index('idx_salary_component_payroll_run', table_name='salary_component')
    op.drop_index('idx_salary_component_type', table_name='salary_component')
    op.drop_table('salary_component')

    op.drop_constraint('fk_salary_structure_legal_entity', 'salary_structure', type_='foreignkey')
    op.drop_constraint('uq_salary_structure_code_legal_entity', 'salary_structure', type_='unique')
    op.drop_constraint('ck_salary_structure_status', 'salary_structure', type_='check')
    op.drop_index('idx_salary_structure_code', table_name='salary_structure')
    op.drop_index('idx_salary_structure_effective', table_name='salary_structure')
    op.drop_index('idx_salary_structure_status', table_name='salary_structure')
    op.drop_table('salary_structure')

    op.drop_constraint('fk_payroll_detail_run', 'payroll_detail', type_='foreignkey')
    op.drop_constraint('fk_payroll_detail_employee', 'payroll_detail', type_='foreignkey')
    op.drop_constraint('fk_payroll_detail_legal_entity', 'payroll_detail', type_='foreignkey')
    op.drop_constraint('ck_payroll_detail_net_nonneg', 'payroll_detail', type_='check')
    op.drop_index('idx_payroll_detail_run', table_name='payroll_detail')
    op.drop_index('idx_payroll_detail_employee', table_name='payroll_detail')
    op.drop_table('payroll_detail')

    op.drop_constraint('fk_payroll_run_legal_entity', 'payroll_run', type_='foreignkey')
    op.drop_constraint('fk_payroll_run_approved_by', 'payroll_run', type_='foreignkey')
    op.drop_constraint('fk_payroll_run_paid_by', 'payroll_run', type_='foreignkey')
    op.drop_constraint('uq_payroll_run_number_legal_entity', 'payroll_run', type_='unique')
    op.drop_constraint('ck_payroll_run_status', 'payroll_run', type_='check')
    op.drop_constraint('ck_payroll_run_employees_nonneg', 'payroll_run', type_='check')
    op.drop_constraint('ck_payroll_run_net_salary_nonneg', 'payroll_run', type_='check')
    op.drop_index('idx_payroll_run_legal_entity', table_name='payroll_run')
    op.drop_index('idx_payroll_run_period', table_name='payroll_run')
    op.drop_index('idx_payroll_run_status', table_name='payroll_run')
    op.drop_index('idx_payroll_run_number', table_name='payroll_run')
    op.drop_table('payroll_run')