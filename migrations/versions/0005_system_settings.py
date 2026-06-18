"""create system_setting table

Revision ID: 0005
Revises: 0004
Create Date: 2025-01-01 00:00:04.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = '0005'
down_revision = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'system_setting',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('key', sa.String(200), nullable=False),
        sa.Column('value', sa.Text, nullable=False, server_default=''),
        sa.Column('data_type', sa.String(20), nullable=False, server_default='string'),
        sa.Column('description', sa.String(1000), nullable=True),
        sa.Column('category', sa.String(50), nullable=False, server_default='general'),
        sa.Column('scope', sa.String(20), nullable=False, server_default='global'),
        sa.Column('legal_entity_id', UUID(as_uuid=True), nullable=True),
        sa.Column('validation_regex', sa.String(500), nullable=True),
        sa.Column('min_value', sa.String(100), nullable=True),
        sa.Column('max_value', sa.String(100), nullable=True),
        sa.Column('allowed_values', JSONB, nullable=True),
        sa.Column('default_value', sa.Text, nullable=True),
        sa.Column('is_readonly', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('is_encrypted', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_by', UUID(as_uuid=True), nullable=True),
        sa.Column('updated_by', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_system_setting_key', 'system_setting', ['key'])
    op.create_index('idx_system_setting_category', 'system_setting', ['category'])
    op.create_index('idx_system_setting_scope', 'system_setting', ['scope'])
    op.create_index('idx_system_setting_legal_entity', 'system_setting', ['legal_entity_id'])
    op.create_index('idx_system_setting_status', 'system_setting', ['is_active'])
    op.create_unique_constraint('uq_system_setting_key_legal_entity', 'system_setting', ['key', 'legal_entity_id'])
    op.create_foreign_key('fk_system_setting_legal_entity', 'system_setting', 'legal_entity', ['legal_entity_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_system_setting_data_type', 'system_setting', "data_type IN ('string', 'integer', 'float', 'boolean', 'json', 'decimal')")
    op.create_check_constraint('ck_system_setting_category', 'system_setting', "category IN ('general', 'accounting', 'tax', 'security', 'audit', 'integration', 'performance')")
    op.create_check_constraint('ck_system_setting_scope', 'system_setting', "scope IN ('global', 'legal_entity')")

def downgrade() -> None:
    op.drop_constraint('fk_system_setting_legal_entity', 'system_setting', type_='foreignkey')
    op.drop_constraint('uq_system_setting_key_legal_entity', 'system_setting', type_='unique')
    op.drop_constraint('ck_system_setting_data_type', 'system_setting', type_='check')
    op.drop_constraint('ck_system_setting_category', 'system_setting', type_='check')
    op.drop_constraint('ck_system_setting_scope', 'system_setting', type_='check')
    op.drop_index('idx_system_setting_key', table_name='system_setting')
    op.drop_index('idx_system_setting_category', table_name='system_setting')
    op.drop_index('idx_system_setting_scope', table_name='system_setting')
    op.drop_index('idx_system_setting_legal_entity', table_name='system_setting')
    op.drop_index('idx_system_setting_status', table_name='system_setting')
    op.drop_table('system_setting')