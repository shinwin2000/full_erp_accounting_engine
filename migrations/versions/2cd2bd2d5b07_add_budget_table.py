"""add budget table

Revision ID: 2cd2bd2d5b07
Revises: approval_extend_001
Create Date: 2026-08-05

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '2cd2bd2d5b07'
down_revision = 'approval_extend_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ========================================================================
    # TABEL: budget (header)
    # ========================================================================
    op.create_table(
        'budget',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),

        # Identifikasi
        sa.Column('budget_code', sa.String(length=50), nullable=False),
        sa.Column('budget_name', sa.String(length=200), nullable=False),
        sa.Column('budget_type', sa.String(length=20), nullable=False, server_default='operational'),
        sa.Column('description', sa.Text(), nullable=True),

        # Period
        sa.Column('fiscal_year', sa.Integer(), nullable=False),
        sa.Column('period', sa.String(length=20), nullable=False, server_default='monthly'),
        # NB: override oleh BudgetTable sendiri jadi String, bukan Integer dari VersionMixin
        sa.Column('version', sa.String(length=20), nullable=False, server_default='1.0'),

        # Tanggal
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('expiry_date', sa.Date(), nullable=True),

        # Status
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('is_locked', sa.Boolean(), nullable=False, server_default=sa.false()),

        # Mata uang
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='IDR'),

        # Metadata
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=True),

        # Audit
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True), nullable=True),

        # Approval
        sa.Column('submitted_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejected_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),

        # TimestampMixin
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),

        # SoftDeleteMixin
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),

        # LegalEntityMixin
        sa.Column('legal_entity_id', postgresql.UUID(as_uuid=True), nullable=False),

        sa.ForeignKeyConstraint(['legal_entity_id'], ['legal_entity.id']),

        sa.UniqueConstraint('budget_code', 'legal_entity_id', name='uq_budget_code_legal_entity'),
        sa.CheckConstraint("budget_code IS NOT NULL AND budget_code != ''", name='ck_budget_code'),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'under_review', 'approved', 'rejected', "
            "'active', 'locked', 'archived', 'expired', 'cancelled', 'closed')",
            name='ck_budget_status',
        ),
        sa.CheckConstraint(
            "budget_type IN ('operational', 'capital', 'cash', 'project', 'department', "
            "'fixed_asset', 'sales', 'production', 'labor')",
            name='ck_budget_type',
        ),
        sa.CheckConstraint("period IN ('monthly', 'quarterly', 'yearly')", name='ck_budget_period'),
    )
    op.create_index('idx_budget_code', 'budget', ['budget_code'])
    op.create_index('idx_budget_legal_entity', 'budget', ['legal_entity_id'])
    op.create_index('idx_budget_fiscal_year', 'budget', ['fiscal_year'])
    op.create_index('idx_budget_status', 'budget', ['status'])
    op.create_index('idx_budget_effective_date', 'budget', ['effective_date'])
    op.create_index('idx_budget_expiry_date', 'budget', ['expiry_date'])

    # ========================================================================
    # TABEL: budget_line
    # ========================================================================
    op.create_table(
        'budget_line',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('budget_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_code', sa.String(length=20), nullable=False),
        sa.Column('amount', sa.Numeric(20, 2), nullable=False, server_default='0'),
        sa.Column('note', sa.Text(), nullable=True),

        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True), nullable=True),

        # VersionMixin (tidak di-override, jadi Integer)
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),

        # TimestampMixin
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),

        sa.ForeignKeyConstraint(['budget_id'], ['budget.id'], ondelete='CASCADE'),

        sa.CheckConstraint('amount >= 0', name='ck_budget_line_amount_nonneg'),
        sa.CheckConstraint(
            "account_code IS NOT NULL AND account_code != ''", name='ck_budget_line_account_code'
        ),
    )
    op.create_index('idx_budget_line_budget', 'budget_line', ['budget_id'])
    op.create_index('idx_budget_line_account', 'budget_line', ['account_id', 'account_code'])

    # ========================================================================
    # TABEL: budget_actual
    # ========================================================================
    op.create_table(
        'budget_actual',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('budget_id', postgresql.UUID(as_uuid=True), nullable=False),

        sa.Column('transaction_date', sa.Date(), nullable=False),
        sa.Column('amount', sa.Numeric(20, 2), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='IDR'),

        sa.Column('source_type', sa.String(length=30), nullable=False),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_number', sa.String(length=50), nullable=True),

        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('reference', sa.String(length=100), nullable=True),

        sa.Column('cost_center', sa.String(length=20), nullable=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=True),

        sa.Column('status', sa.String(length=20), nullable=False, server_default='posted'),
        sa.Column('reversed_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reversed_at', sa.DateTime(timezone=True), nullable=True),

        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),

        # TimestampMixin
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),

        # LegalEntityMixin
        sa.Column('legal_entity_id', postgresql.UUID(as_uuid=True), nullable=False),

        sa.ForeignKeyConstraint(['budget_id'], ['budget.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['legal_entity_id'], ['legal_entity.id']),

        sa.CheckConstraint('amount >= 0', name='ck_budget_actual_nonneg'),
        sa.CheckConstraint(
            "source_type IN ('journal', 'invoice', 'payment', 'purchase_order', 'sales_order', 'manual')",
            name='ck_budget_actual_source',
        ),
    )
    op.create_index('idx_budget_actual_budget', 'budget_actual', ['budget_id'])
    op.create_index('idx_budget_actual_date', 'budget_actual', ['transaction_date'])
    op.create_index('idx_budget_actual_source', 'budget_actual', ['source_type', 'source_id'])
    op.create_index('idx_budget_actual_legal_entity', 'budget_actual', ['legal_entity_id'])


def downgrade() -> None:
    op.drop_table('budget_actual')
    op.drop_table('budget_line')
    op.drop_table('budget')
