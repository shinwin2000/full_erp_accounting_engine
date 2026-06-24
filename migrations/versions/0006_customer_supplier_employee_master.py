"""create customer, supplier, employee master tables

Revision ID: 0006
Revises: 0005
Create Date: 2025-01-01 00:00:05.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, NUMERIC

revision: str = '0006abcd'
down_revision = '0005abcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # customer table
    op.create_table(
        'customer',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('customer_code', sa.String(30), nullable=False),
        sa.Column('customer_name', sa.String(200), nullable=False),
        sa.Column('customer_type', sa.String(20), nullable=False, server_default='company'),
        sa.Column('tax_id', sa.String(20), nullable=True, unique=True),
        sa.Column('tax_id_encrypted', sa.Text, nullable=True),
        sa.Column('tax_status', sa.String(20), nullable=False, server_default='pkp'),
        sa.Column('registration_number', sa.String(50), nullable=True),
        sa.Column('address', sa.Text, nullable=True),
        sa.Column('shipping_address', sa.Text, nullable=True),
        sa.Column('city', sa.String(100), nullable=True),
        sa.Column('postal_code', sa.String(20), nullable=True),
        sa.Column('country', sa.String(2), nullable=False, server_default='ID'),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('email', sa.String(200), nullable=True),
        sa.Column('website', sa.String(200), nullable=True),
        sa.Column('contact_person', sa.String(100), nullable=True),
        sa.Column('contact_phone', sa.String(20), nullable=True),
        sa.Column('contact_email', sa.String(200), nullable=True),
        sa.Column('credit_limit', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('used_credit', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('payment_term_days', sa.Integer, nullable=False, server_default='30'),
        sa.Column('discount_percent', NUMERIC(5, 2), nullable=False, server_default='0'),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('price_group', sa.String(50), nullable=True),
        sa.Column('sales_person_id', UUID(as_uuid=True), nullable=True),
        sa.Column('bank_name', sa.String(100), nullable=True),
        sa.Column('bank_account_number', sa.String(50), nullable=True),
        sa.Column('bank_account_name', sa.String(100), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('blocked_reason', sa.Text, nullable=True),
        sa.Column('first_purchase_date', sa.Date, nullable=True),
        sa.Column('last_purchase_date', sa.Date, nullable=True),
        sa.Column('credit_check_date', sa.Date, nullable=True),
        sa.Column('metadata', JSONB, nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_customer_customer_code', 'customer', ['customer_code'])
    op.create_index('idx_customer_name', 'customer', ['customer_name'])
    op.create_index('idx_customer_tax_id', 'customer', ['tax_id'])
    op.create_index('idx_customer_status', 'customer', ['status'])
    op.create_index('idx_customer_legal_entity', 'customer', ['legal_entity_id'])
    op.create_index('idx_customer_category', 'customer', ['category'])
    op.create_index('idx_customer_sales_person', 'customer', ['sales_person_id'])
    op.create_unique_constraint('uq_customer_code_legal_entity', 'customer', ['customer_code', 'legal_entity_id'])
    op.create_foreign_key('fk_customer_legal_entity', 'customer', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_customer_type', 'customer', "customer_type IN ('individual', 'company', 'government', 'non_profit')")
    op.create_check_constraint('ck_customer_status', 'customer', "status IN ('active', 'inactive', 'blocked', 'suspended')")
    op.create_check_constraint('ck_customer_tax_status', 'customer', "tax_status IN ('pkp', 'non_pkp')")

    # supplier table
    op.create_table(
        'supplier',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('supplier_code', sa.String(30), nullable=False),
        sa.Column('supplier_name', sa.String(200), nullable=False),
        sa.Column('supplier_type', sa.String(20), nullable=False, server_default='company'),
        sa.Column('tax_id', sa.String(20), nullable=True, unique=True),
        sa.Column('tax_id_encrypted', sa.Text, nullable=True),
        sa.Column('tax_status', sa.String(20), nullable=False, server_default='pkp'),
        sa.Column('registration_number', sa.String(50), nullable=True),
        sa.Column('withholding_category', sa.String(20), nullable=False, server_default='none'),
        sa.Column('withholding_rate', NUMERIC(5, 2), nullable=False, server_default='0'),
        sa.Column('has_npwp', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('address', sa.Text, nullable=True),
        sa.Column('city', sa.String(100), nullable=True),
        sa.Column('postal_code', sa.String(20), nullable=True),
        sa.Column('country', sa.String(2), nullable=False, server_default='ID'),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('fax', sa.String(20), nullable=True),
        sa.Column('email', sa.String(200), nullable=True),
        sa.Column('website', sa.String(200), nullable=True),
        sa.Column('contact_person', sa.String(100), nullable=True),
        sa.Column('contact_phone', sa.String(20), nullable=True),
        sa.Column('contact_email', sa.String(200), nullable=True),
        sa.Column('payment_term_days', sa.Integer, nullable=False, server_default='30'),
        sa.Column('discount_percent', NUMERIC(5, 2), nullable=False, server_default='0'),
        sa.Column('bank_name', sa.String(100), nullable=True),
        sa.Column('bank_account_number', sa.String(50), nullable=True),
        sa.Column('bank_account_name', sa.String(100), nullable=True),
        sa.Column('lead_time_days', sa.Integer, nullable=False, server_default='7'),
        sa.Column('quality_rating', NUMERIC(3, 2), nullable=True, default=0),
        sa.Column('on_time_delivery_rate', NUMERIC(5, 2), nullable=True, default=0),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('procurement_category', sa.String(50), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('blocked_reason', sa.Text, nullable=True),
        sa.Column('first_purchase_date', sa.Date, nullable=True),
        sa.Column('last_purchase_date', sa.Date, nullable=True),
        sa.Column('last_audit_date', sa.Date, nullable=True),
        sa.Column('metadata', JSONB, nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_supplier_supplier_code', 'supplier', ['supplier_code'])
    op.create_index('idx_supplier_name', 'supplier', ['supplier_name'])
    op.create_index('idx_supplier_tax_id', 'supplier', ['tax_id'])
    op.create_index('idx_supplier_status', 'supplier', ['status'])
    op.create_index('idx_supplier_legal_entity', 'supplier', ['legal_entity_id'])
    op.create_index('idx_supplier_category', 'supplier', ['category'])
    op.create_index('idx_supplier_withholding', 'supplier', ['withholding_category'])
    op.create_unique_constraint('uq_supplier_code_legal_entity', 'supplier', ['supplier_code', 'legal_entity_id'])
    op.create_foreign_key('fk_supplier_legal_entity', 'supplier', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_supplier_type', 'supplier', "supplier_type IN ('individual', 'company', 'government', 'non_profit')")
    op.create_check_constraint('ck_supplier_status', 'supplier', "status IN ('active', 'inactive', 'blocked', 'suspended')")
    op.create_check_constraint('ck_supplier_withholding', 'supplier', "withholding_category IN ('none', 'pph23', 'pph26', 'both')")

    # employee table
    op.create_table(
        'employee',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('employee_code', sa.String(30), nullable=False),
        sa.Column('nik', sa.String(30), nullable=True, unique=True),
        sa.Column('full_name', sa.String(200), nullable=False),
        sa.Column('preferred_name', sa.String(100), nullable=True),
        sa.Column('gender', sa.String(1), nullable=True),
        sa.Column('birth_place', sa.String(100), nullable=True),
        sa.Column('birth_date', sa.Date, nullable=True),
        sa.Column('marital_status', sa.String(20), nullable=False, server_default='single'),
        sa.Column('religion', sa.String(50), nullable=True),
        sa.Column('address', sa.Text, nullable=True),
        sa.Column('city', sa.String(100), nullable=True),
        sa.Column('postal_code', sa.String(20), nullable=True),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('mobile', sa.String(20), nullable=True),
        sa.Column('email', sa.String(200), nullable=True),
        sa.Column('email_encrypted', sa.Text, nullable=True),
        sa.Column('tax_id', sa.String(20), nullable=True, unique=True),
        sa.Column('tax_id_encrypted', sa.Text, nullable=True),
        sa.Column('ptkp_status', sa.String(10), nullable=False, server_default='TK/0'),
        sa.Column('join_date', sa.Date, nullable=True),
        sa.Column('resignation_date', sa.Date, nullable=True),
        sa.Column('employment_status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('department', sa.String(100), nullable=True),
        sa.Column('division', sa.String(100), nullable=True),
        sa.Column('position', sa.String(100), nullable=True),
        sa.Column('job_level', sa.String(50), nullable=True),
        sa.Column('cost_center', sa.String(20), nullable=True),
        sa.Column('manager_id', UUID(as_uuid=True), nullable=True),
        sa.Column('basic_salary', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('allowances', NUMERIC(20, 2), nullable=False, server_default='0'),
        sa.Column('overtime_rate_multiplier', NUMERIC(3, 1), nullable=False, server_default='1.5'),
        sa.Column('bpjs_ketenagakerjaan_number', sa.String(30), nullable=True),
        sa.Column('bpjs_kesehatan_number', sa.String(30), nullable=True),
        sa.Column('bpjs_jht_rate_employee', NUMERIC(5, 2), nullable=False, server_default='2.0'),
        sa.Column('bpjs_jht_rate_employer', NUMERIC(5, 2), nullable=False, server_default='3.7'),
        sa.Column('bpjs_jkk_rate', NUMERIC(5, 2), nullable=False, server_default='0.24'),
        sa.Column('bpjs_jkm_rate', NUMERIC(5, 2), nullable=False, server_default='0.30'),
        sa.Column('bpjs_kesehatan_rate_employee', NUMERIC(5, 2), nullable=False, server_default='1.0'),
        sa.Column('bpjs_kesehatan_rate_employer', NUMERIC(5, 2), nullable=False, server_default='4.0'),
        sa.Column('bank_name', sa.String(100), nullable=True),
        sa.Column('bank_account_number', sa.String(50), nullable=True),
        sa.Column('bank_account_number_encrypted', sa.Text, nullable=True),
        sa.Column('bank_account_name', sa.String(100), nullable=True),
        sa.Column('annual_leave_balance', NUMERIC(10, 2), nullable=False, server_default='12'),
        sa.Column('sick_leave_balance', NUMERIC(10, 2), nullable=False, server_default='14'),
        sa.Column('special_leave_balance', NUMERIC(10, 2), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('metadata', JSONB, nullable=True),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_employee_employee_code', 'employee', ['employee_code'])
    op.create_index('idx_employee_nik', 'employee', ['nik'])
    op.create_index('idx_employee_email', 'employee', ['email'])
    op.create_index('idx_employee_tax_id', 'employee', ['tax_id'])
    op.create_index('idx_employee_status', 'employee', ['employment_status'])
    op.create_index('idx_employee_legal_entity', 'employee', ['legal_entity_id'])
    op.create_index('idx_employee_department', 'employee', ['department'])
    op.create_index('idx_employee_position', 'employee', ['position'])
    op.create_index('idx_employee_ptkp_status', 'employee', ['ptkp_status'])
    op.create_unique_constraint('uq_employee_code_legal_entity', 'employee', ['employee_code', 'legal_entity_id'])
    op.create_foreign_key('fk_employee_legal_entity', 'employee', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_employee_manager', 'employee', 'employee', ['manager_id'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_employee_status', 'employee', "employment_status IN ('active', 'inactive', 'resigned', 'terminated', 'on_leave')")
    op.create_check_constraint('ck_employee_gender', 'employee', "gender IN ('M', 'F', 'O')")
    op.create_check_constraint('ck_employee_marital_status', 'employee', "marital_status IN ('single', 'married', 'divorced', 'widowed')")
    op.create_check_constraint('ck_employee_ptkp', 'employee', "ptkp_status IN ('TK/0', 'TK/1', 'TK/2', 'TK/3', 'K/0', 'K/1', 'K/2', 'K/3')")

def downgrade() -> None:
    op.drop_constraint('fk_employee_legal_entity', 'employee', type_='foreignkey')
    op.drop_constraint('fk_employee_manager', 'employee', type_='foreignkey')
    op.drop_constraint('uq_employee_code_legal_entity', 'employee', type_='unique')
    op.drop_constraint('ck_employee_status', 'employee', type_='check')
    op.drop_constraint('ck_employee_gender', 'employee', type_='check')
    op.drop_constraint('ck_employee_marital_status', 'employee', type_='check')
    op.drop_constraint('ck_employee_ptkp', 'employee', type_='check')
    op.drop_index('idx_employee_employee_code', table_name='employee')
    op.drop_index('idx_employee_nik', table_name='employee')
    op.drop_index('idx_employee_email', table_name='employee')
    op.drop_index('idx_employee_tax_id', table_name='employee')
    op.drop_index('idx_employee_status', table_name='employee')
    op.drop_index('idx_employee_legal_entity', table_name='employee')
    op.drop_index('idx_employee_department', table_name='employee')
    op.drop_index('idx_employee_position', table_name='employee')
    op.drop_index('idx_employee_ptkp_status', table_name='employee')
    op.drop_table('employee')

    op.drop_constraint('fk_supplier_legal_entity', 'supplier', type_='foreignkey')
    op.drop_constraint('uq_supplier_code_legal_entity', 'supplier', type_='unique')
    op.drop_constraint('ck_supplier_type', 'supplier', type_='check')
    op.drop_constraint('ck_supplier_status', 'supplier', type_='check')
    op.drop_constraint('ck_supplier_withholding', 'supplier', type_='check')
    op.drop_index('idx_supplier_supplier_code', table_name='supplier')
    op.drop_index('idx_supplier_name', table_name='supplier')
    op.drop_index('idx_supplier_tax_id', table_name='supplier')
    op.drop_index('idx_supplier_status', table_name='supplier')
    op.drop_index('idx_supplier_legal_entity', table_name='supplier')
    op.drop_index('idx_supplier_category', table_name='supplier')
    op.drop_index('idx_supplier_withholding', table_name='supplier')
    op.drop_table('supplier')

    op.drop_constraint('fk_customer_legal_entity', 'customer', type_='foreignkey')
    op.drop_constraint('uq_customer_code_legal_entity', 'customer', type_='unique')
    op.drop_constraint('ck_customer_type', 'customer', type_='check')
    op.drop_constraint('ck_customer_status', 'customer', type_='check')
    op.drop_constraint('ck_customer_tax_status', 'customer', type_='check')
    op.drop_index('idx_customer_customer_code', table_name='customer')
    op.drop_index('idx_customer_name', table_name='customer')
    op.drop_index('idx_customer_tax_id', table_name='customer')
    op.drop_index('idx_customer_status', table_name='customer')
    op.drop_index('idx_customer_legal_entity', table_name='customer')
    op.drop_index('idx_customer_category', table_name='customer')
    op.drop_index('idx_customer_sales_person', table_name='customer')
    op.drop_table('customer')