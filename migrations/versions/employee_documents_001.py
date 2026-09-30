"""Add employee_documents table (KTP, KK, BPJS, dan dokumen lain)

Berbeda dari foto profil (satu foto per karyawan, kolom di tabel employee
langsung), dokumen kependudukan/kepesertaan bisa lebih dari satu jenis
per karyawan (KTP, KK, BPJS Kesehatan, BPJS Ketenagakerjaan, NPWP,
ijazah, dll) - jadi disimpan sebagai tabel tersendiri (satu baris = satu
dokumen), sama seperti employee_dependents.

File disimpan sebagai bytea langsung di database, konsisten dengan
pendekatan foto profil (lihat employee_family_photo_001.py) - MinIO
tidak aktif di lingkungan dev saat ini, dan dokumen scan KTP/KK/BPJS
berukuran kecil (umumnya di bawah 5MB), jadi bytea Postgres tetap wajar
untuk kasus ini.

Revision ID: employee_documents_001
Revises: employee_family_photo_001
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "employee_documents_001"
down_revision = "employee_family_photo_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "employee_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("legal_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        # ktp | kk | bpjs_kesehatan | bpjs_ketenagakerjaan | npwp | ijazah | other
        sa.Column("document_type", sa.String(30), nullable=False),
        # Label bebas - wajib diisi kalau document_type='other' (mis. "SIM
        # A", "Kartu Vaksin"), opsional untuk tipe baku lainnya.
        sa.Column("document_label", sa.String(100), nullable=True),
        # Nomor dokumen (NIK di KTP, No. KK, No. BPJS, No. NPWP, dst) -
        # opsional, bebas format karena bervariasi per jenis dokumen.
        sa.Column("document_number", sa.String(50), nullable=True),
        sa.Column("file_data", sa.LargeBinary(), nullable=False),
        sa.Column("file_mime_type", sa.String(100), nullable=False),
        sa.Column("file_filename", sa.String(255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "document_type IN ('ktp', 'kk', 'bpjs_kesehatan', 'bpjs_ketenagakerjaan', "
            "'npwp', 'ijazah', 'other')",
            name="ck_employee_documents_type",
        ),
    )
    op.create_index(
        "idx_employee_documents_employee_id", "employee_documents", ["employee_id"]
    )
    op.create_index(
        "idx_employee_documents_legal_entity_id", "employee_documents", ["legal_entity_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_employee_documents_legal_entity_id", table_name="employee_documents")
    op.drop_index("idx_employee_documents_employee_id", table_name="employee_documents")
    op.drop_table("employee_documents")
