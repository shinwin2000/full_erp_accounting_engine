"""employee ptkp and type

Revision ID: 0053_employee_ptkp_and_type
Revises: 0052_supplier_history_updated_at
Create Date: 2026-10-13

PERUBAHAN:

1. Perluas CheckConstraint `ck_employee_ptkp` di tabel `employee` supaya
   mendukung status PTKP `KB/0`..`KB/3` (Kawin Kombinasi Penghasilan) —
   sinkron dengan enum PTKPCategory di domain layer. Sebelumnya hanya
   mengizinkan TK/x dan K/x.

   Tanpa migrasi ini, set PTKP ke "KB/2" akan gagal dengan
   CheckConstraintViolationError.

2. Tambah kolom `employee_type` di tabel `employee` — field ini WAJIB
   di domain (EmployeeEntity.employee_type: EmployeeType) tapi TIDAK ADA
   di tabel DB, sehingga data hilang saat disimpan.

   Nilai yang diizinkan: 'permanent', 'contract', 'intern', 'freelance',
   'director', 'commissioner', 'probation'. Default 'permanent' supaya
   data lama tetap valid.

CATATAN PENTING soal panjang revision id:
    Kolom `alembic_version.version_num` di DB ini bertipe VARCHAR(32).
    Revision id di bawah (28 karakter) sengaja dipendekkan supaya muat.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0053_employee_ptkp_and_type"
down_revision = "0052_supplier_history_updated_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Perluas CheckConstraint PTKP
    # ------------------------------------------------------------------
    op.drop_constraint("ck_employee_ptkp", "employee", type_="check")
    op.create_check_constraint(
        "ck_employee_ptkp",
        "employee",
        "ptkp_status IN ("
        "'TK/0', 'TK/1', 'TK/2', 'TK/3', "
        "'K/0', 'K/1', 'K/2', 'K/3', "
        "'KB/0', 'KB/1', 'KB/2', 'KB/3'"
        ")",
    )

    # ------------------------------------------------------------------
    # 2. Tambah kolom employee_type
    # ------------------------------------------------------------------
    op.add_column(
        "employee",
        sa.Column(
            "employee_type",
            sa.String(20),
            nullable=False,
            server_default="permanent",
        ),
    )
    op.create_check_constraint(
        "ck_employee_type",
        "employee",
        "employee_type IN ("
        "'permanent', 'contract', 'intern', 'freelance', "
        "'director', 'commissioner', 'probation'"
        ")",
    )
    op.create_index(
        "idx_employee_type", "employee", ["employee_type"]
    )


def downgrade() -> None:
    op.drop_index("idx_employee_type", table_name="employee")
    op.drop_constraint("ck_employee_type", "employee", type_="check")
    op.drop_column("employee", "employee_type")

    op.drop_constraint("ck_employee_ptkp", "employee", type_="check")
    op.create_check_constraint(
        "ck_employee_ptkp",
        "employee",
        "ptkp_status IN ("
        "'TK/0', 'TK/1', 'TK/2', 'TK/3', "
        "'K/0', 'K/1', 'K/2', 'K/3'"
        ")",
    )
    