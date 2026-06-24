"""create legal_entity and related tables

Revision ID: 0001
Revises: 
Create Date: 2025-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '0001abcd'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS projections")

    op.create_table(
        'legal_entity',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('legal_name', sa.String(200), nullable=False),
        sa.Column('trade_name', sa.String(200), nullable=True),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('registration_number', sa.String(50), nullable=True),
        sa.Column('npwp', sa.String(20), nullable=True, unique=True),
        sa.Column('address', sa.Text, nullable=True),
        sa.Column('city', sa.String(100), nullable=True),
        sa.Column('postal_code', sa.String(20), nullable=True),
        sa.Column('country', sa.String(2), nullable=False, server_default='ID'),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('email', sa.String(200), nullable=True),
        sa.Column('website', sa.String(200), nullable=True),
        sa.Column('established_date', sa.Date, nullable=True),
        sa.Column('fiscal_year_start', sa.Integer, nullable=False, server_default='1'),
        sa.Column('fiscal_year_end', sa.Integer, nullable=False, server_default='12'),
        sa.Column('base_currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('functional_currency', sa.String(3), nullable=False, server_default='IDR'),
        sa.Column('tax_office', sa.String(100), nullable=True),
        sa.Column('tax_office_code', sa.String(10), nullable=True),
        sa.Column('tax_classification', sa.String(50), nullable=True),
        sa.Column('taxable_date', sa.Date, nullable=True),
        sa.Column('annual_tax_return_due_date', sa.Integer, nullable=True),
        sa.Column('monthly_tax_due_date', sa.Integer, nullable=True),
        sa.Column('is_vat_collector', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('vat_collector_number', sa.String(50), nullable=True),
        sa.Column('is_withholding_agent', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('parent_company_id', UUID(as_uuid=True), nullable=True),
        sa.Column('consolidation_group_id', UUID(as_uuid=True), nullable=True),
        sa.Column('logo_url', sa.String(500), nullable=True),
        sa.Column('metadata', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['parent_company_id'], ['legal_entity.id'], ),
    )
    op.create_index('idx_legal_entity_npwp', 'legal_entity', ['npwp'])
    op.create_index('idx_legal_entity_parent', 'legal_entity', ['parent_company_id'])
    op.create_index('idx_legal_entity_consolidation', 'legal_entity', ['consolidation_group_id'])

    op.create_table(
        'iam_user',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('username', sa.String(100), nullable=False, unique=True),
        sa.Column('email', sa.String(200), nullable=True, unique=True),
        sa.Column('email_encrypted', sa.Text, nullable=True),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('phone_encrypted', sa.Text, nullable=True),
        sa.Column('full_name', sa.String(200), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('must_change_password', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending_activation'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('is_superuser', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_login_ip', sa.String(45), nullable=True),
        sa.Column('failed_login_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('legal_entity_ids', JSONB, nullable=True),
        sa.Column('metadata', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_iam_user_username', 'iam_user', ['username'])
    op.create_index('idx_iam_user_email', 'iam_user', ['email'])
    op.create_index('idx_iam_user_status', 'iam_user', ['status'])
    op.create_index('idx_iam_user_legal_entity_ids', 'iam_user', ['legal_entity_ids'], postgresql_using='gin')

    op.create_table(
        'iam_role',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(100), nullable=False, unique=True),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('parent_role_id', UUID(as_uuid=True), nullable=True),
        sa.Column('is_system_role', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['parent_role_id'], ['iam_role.id'], ),
    )
    op.create_index('idx_iam_role_name', 'iam_role', ['name'])
    op.create_index('idx_iam_role_parent', 'iam_role', ['parent_role_id'])

    op.create_table(
        'iam_permission',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(100), nullable=False, unique=True),
        sa.Column('resource', sa.String(100), nullable=False),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('is_system', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_iam_permission_resource', 'iam_permission', ['resource'])

    op.create_table(
        'iam_user_role',
        sa.Column('user_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('role_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('assigned_by', UUID(as_uuid=True), nullable=True),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['iam_user.id'], ),
        sa.ForeignKeyConstraint(['role_id'], ['iam_role.id'], ),
    )

    op.create_table(
        'iam_role_permission',
        sa.Column('role_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('permission_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('assigned_by', UUID(as_uuid=True), nullable=True),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['role_id'], ['iam_role.id'], ),
        sa.ForeignKeyConstraint(['permission_id'], ['iam_permission.id'], ),
    )

def downgrade() -> None:
    op.drop_table('iam_role_permission')
    op.drop_table('iam_user_role')
    op.drop_table('iam_permission')
    op.drop_table('iam_role')
    op.drop_table('iam_user')
    op.drop_table('legal_entity')
    op.execute("DROP SCHEMA IF EXISTS projections CASCADE")