"""Add employee photo columns and employee_dependents table

Menambahkan dukungan untuk:
1. Foto profil karyawan - disimpan langsung di database (bytea) alih-alih
   lewat subsistem file storage (MinIO/S3) yang terpisah, karena:
   - MinIO tidak aktif di lingkungan dev saat ini (lihat banner startup
     "MinIO=[X]")
   - Foto profil karyawan berukuran kecil (biasanya di bawah 1MB), jadi
     menyimpan di Postgres sebagai bytea adalah pola yang wajar dan aman
     untuk kasus ini, tanpa menambah ketergantungan infrastruktur baru.
2. Data tanggungan/keluarga karyawan (pasangan, anak, tanggungan lain) -
   tabel baru `employee_dependents`. Ini BUKAN sekadar data pelengkap:
   di Indonesia, status PTKP (`employee.ptkp_status`, mis. "K/2") secara
   langsung ditentukan oleh status kawin DAN jumlah tanggungan - jadi
   data ini relevan untuk validasi/perhitungan pajak penghasilan (PPh 21),
   bukan cuma catatan HR biasa.

Revision ID: employee_family_photo_001
Revises: merge_budget_rev_hist_20260917
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "employee_family_photo_001"
down_revision = "merge_budget_rev_hist_20260917"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Kolom foto di tabel employee
    # ------------------------------------------------------------------
    op.add_column("employee", sa.Column("photo_data", sa.LargeBinary(), nullable=True))
    op.add_column("employee", sa.Column("photo_mime_type", sa.String(100), nullable=True))
    op.add_column("employee", sa.Column("photo_filename", sa.String(255), nullable=True))
    op.add_column(
        "employee",
        sa.Column("photo_updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ------------------------------------------------------------------
    # 2. Tabel employee_dependents (data tanggungan/keluarga)
    # ------------------------------------------------------------------
    op.create_table(
        "employee_dependents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("legal_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        # spouse (pasangan) | child (anak) | parent (orang tua) | other (lain-lain)
        sa.Column("relationship_type", sa.String(20), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("occupation", sa.String(100), nullable=True),
        sa.Column(
            "is_ptkp_dependent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "relationship_type IN ('spouse', 'child', 'parent', 'other')",
            name="ck_employee_dependents_relationship_type",
        ),
    )
    op.create_index(
        "idx_employee_dependents_employee_id",
        "employee_dependents",
        ["employee_id"],
    )
    op.create_index(
        "idx_employee_dependents_legal_entity_id",
        "employee_dependents",
        ["legal_entity_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_employee_dependents_legal_entity_id", table_name="employee_dependents")
    op.drop_index("idx_employee_dependents_employee_id", table_name="employee_dependents")
    op.drop_table("employee_dependents")
    op.drop_column("employee", "photo_updated_at")
    op.drop_column("employee", "photo_filename")
    op.drop_column("employee", "photo_mime_type")
    op.drop_column("employee", "photo_data")
