"""create iam_session and login_attempt tables

Revision ID: 0004
Revises: 0003
Create Date: 2025-01-01 00:00:03.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = '0004'
down_revision = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'iam_session',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('session_token', sa.String(255), nullable=False, unique=True),
        sa.Column('refresh_token', sa.String(255), nullable=True, unique=True),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('device_id', sa.String(255), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_accessed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('is_revoked', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('revoke_reason', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_iam_session_user', 'iam_session', ['user_id'])
    op.create_index('idx_iam_session_token', 'iam_session', ['session_token'])
    op.create_index('idx_iam_session_refresh', 'iam_session', ['refresh_token'])
    op.create_index('idx_iam_session_expires', 'iam_session', ['expires_at'])
    op.create_index('idx_iam_session_active', 'iam_session', ['is_active'])
    op.create_foreign_key('fk_iam_session_user', 'iam_session', 'iam_user', ['user_id'], ['id'], ondelete='CASCADE')
    op.create_check_constraint('ck_iam_session_status', 'iam_session', "is_active IN (true, false)")

    op.create_table(
        'login_attempt',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('username', sa.String(100), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('success', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('failure_reason', sa.String(255), nullable=True),
        sa.Column('attempted_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('request_id', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_login_attempt_username', 'login_attempt', ['username'])
    op.create_index('idx_login_attempt_ip', 'login_attempt', ['ip_address'])
    op.create_index('idx_login_attempt_timestamp', 'login_attempt', ['attempted_at'])
    op.create_index('idx_login_attempt_success', 'login_attempt', ['success'])
    op.create_index('idx_login_attempt_user', 'login_attempt', ['user_id'])
    op.create_foreign_key('fk_login_attempt_user', 'login_attempt', 'iam_user', ['user_id'], ['id'], ondelete='SET NULL')

def downgrade() -> None:
    op.drop_constraint('fk_iam_session_user', 'iam_session', type_='foreignkey')
    op.drop_constraint('fk_login_attempt_user', 'login_attempt', type_='foreignkey')
    op.drop_index('idx_iam_session_user', table_name='iam_session')
    op.drop_index('idx_iam_session_token', table_name='iam_session')
    op.drop_index('idx_iam_session_refresh', table_name='iam_session')
    op.drop_index('idx_iam_session_expires', table_name='iam_session')
    op.drop_index('idx_iam_session_active', table_name='iam_session')
    op.drop_index('idx_login_attempt_username', table_name='login_attempt')
    op.drop_index('idx_login_attempt_ip', table_name='login_attempt')
    op.drop_index('idx_login_attempt_timestamp', table_name='login_attempt')
    op.drop_index('idx_login_attempt_success', table_name='login_attempt')
    op.drop_index('idx_login_attempt_user', table_name='login_attempt')
    op.drop_constraint('ck_iam_session_status', 'iam_session', type_='check')
    op.drop_table('iam_session')
    op.drop_table('login_attempt')