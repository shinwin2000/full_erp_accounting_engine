"""customer status check refactor

Revision ID: 0049_customer_status_check
Revises: coa_audit_log_001
Create Date: 2026-10-12

Menambah nilai 'blacklisted' dan 'draft' ke CheckConstraint status di
tabel customer. Sebelumnya CheckConstraint hanya mengizinkan:
'active', 'inactive', 'blocked', 'suspended'.

Tanpa migrasi ini, operasi berikut akan gagal dengan
CheckConstraintViolationError:
- set_blacklist(customer_id, True)       -> butuh status 'blacklisted'
- bulk_update_status(..., 'blacklisted') -> butuh status 'blacklisted'
- create customer dengan status 'draft'  -> butuh status 'draft'

Juga menambahkan index idx_customer_is_blacklist untuk mempercepat
query filter is_blacklist=True pada grid customer.

CATATAN PENTING:
    Revision ID DIPENDEKKAN menjadi '0049_customer_status_check'
    (26 karakter) karena kolom `alembic_version.version_num` di
    database ini bertipe VARCHAR(32). Versi awal yang lebih panjang
    ('0049_customer_status_check_refactor' = 35 karakter) gagal
    dengan error 'value too long for type character varying(32)'.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0049_customer_status_check"
down_revision = "coa_audit_log_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Drop CheckConstraint lama
    op.drop_constraint(
        "ck_customer_status",
        "customer",
        type_="check",
    )

    # 2. Buat CheckConstraint baru dengan nilai lengkap
    op.create_check_constraint(
        "ck_customer_status",
        "customer",
        "status IN ('active', 'inactive', 'blocked', 'suspended', "
        "'blacklisted', 'draft')",
    )

    # 3. Tambah index untuk is_blacklist (percepat filter grid)
    op.create_index(
        "idx_customer_is_blacklist",
        "customer",
        ["is_blacklist"],
        unique=False,
    )


def downgrade() -> None:
    # 1. Drop index
    op.drop_index("idx_customer_is_blacklist", table_name="customer")

    # 2. Kembalikan CheckConstraint lama
    op.drop_constraint(
        "ck_customer_status",
        "customer",
        type_="check",
    )
    op.create_check_constraint(
        "ck_customer_status",
        "customer",
        "status IN ('active', 'inactive', 'blocked', 'suspended')",
    )
    