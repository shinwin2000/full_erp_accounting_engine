"""add projection tables

Revision ID: 27d8615ee183
Revises: 64dc0ea60e72
Create Date: 2025-07-06 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '27d8615ee183'
down_revision = '64dc0ea60e72'
depends_on = None


def upgrade() -> None:
    # Tabel projection_checkpoints
    op.create_table(
        'projection_checkpoints',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('projection_name', sa.String(length=255), nullable=False),
        sa.Column('last_processed_event_id', sa.String(length=255), nullable=True),
        sa.Column('last_processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('projection_name', name='uq_projection_checkpoints_name')
    )
    op.create_index('ix_projection_checkpoints_projection_name', 'projection_checkpoints', ['projection_name'])

    # Tabel projection_read_models
    op.create_table(
        'projection_read_models',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('projection_name', sa.String(length=255), nullable=False),
        sa.Column('data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('projection_name', name='uq_projection_read_models_name')
    )
    op.create_index('ix_projection_read_models_projection_name', 'projection_read_models', ['projection_name'])


def downgrade() -> None:
    op.drop_index('ix_projection_read_models_projection_name', table_name='projection_read_models')
    op.drop_table('projection_read_models')
    op.drop_index('ix_projection_checkpoints_projection_name', table_name='projection_checkpoints')
    op.drop_table('projection_checkpoints')