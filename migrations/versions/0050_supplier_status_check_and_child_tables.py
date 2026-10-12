"""supplier status check and child tables

Revision ID: 0050_supplier_status_and_children
Revises: 0049_customer_status_check
Create Date: 2026-10-12

PERUBAHAN:

1. Perluas CheckConstraint `ck_supplier_status` di tabel `supplier` supaya
   mendukung nilai 'blacklisted' dan 'draft' — sinkron dengan enum
   `SupplierStatus` di domain layer. Sebelumnya hanya mengizinkan:
   'active', 'inactive', 'blocked', 'suspended'.

   Tanpa migrasi ini, operasi berikut akan gagal dengan
   CheckConstraintViolationError:
   - set status = 'blacklisted' (via repo/service)
   - set status = 'draft' (untuk supplier yang belum diaktifkan)

2. Buat tabel anak baru untuk Supplier:
   - `supplier_attachments` : dokumen pendukung (NPWP, SIUP, KTP, kontrak)
   - `supplier_notes`       : catatan internal berhistori

   Mengikuti pola tabel anak Customer (customer_attachments,
   customer_notes) supaya modul Supplier setara dengan Customer dalam
   hal detail yang bisa disimpan per-supplier.

CATATAN PENTING soal panjang revision id:
    Kolom `alembic_version.version_num` di DB ini bertipe VARCHAR(32).
    Revision id di bawah (32 karakter) sengaja dibuat pas batas supaya
    tidak overflow. JANGAN diperpanjang tanpa mengubah skema dulu.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID


# revision identifiers, used by Alembic.
# Panjang 32 karakter: "0050_supplier_status_and_children"
revision = "0050_supplier_status_and_child"
down_revision = "0049_customer_status_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Perluas CheckConstraint status
    # ------------------------------------------------------------------
    op.drop_constraint("ck_supplier_status", "supplier", type_="check")
    op.create_check_constraint(
        "ck_supplier_status",
        "supplier",
        "status IN ('active', 'inactive', 'blocked', 'suspended', "
        "'blacklisted', 'draft')",
    )

    # ------------------------------------------------------------------
    # 2. Tabel supplier_attachments
    # ------------------------------------------------------------------
    op.create_table(
        "supplier_attachments",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "supplier_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("supplier.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_type", sa.String(30), nullable=False, server_default="other"),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("uploaded_by", PGUUID(as_uuid=True), nullable=True),
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
            onupdate=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_supplier_attachment_supplier_id",
        "supplier_attachments",
        ["supplier_id"],
    )

    # ------------------------------------------------------------------
    # 3. Tabel supplier_notes
    # ------------------------------------------------------------------
    op.create_table(
        "supplier_notes",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "supplier_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("supplier.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_by", PGUUID(as_uuid=True), nullable=True),
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
            onupdate=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_supplier_note_supplier_id",
        "supplier_notes",
        ["supplier_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_supplier_note_supplier_id", table_name="supplier_notes")
    op.drop_table("supplier_notes")

    op.drop_index(
        "idx_supplier_attachment_supplier_id", table_name="supplier_attachments"
    )
    op.drop_table("supplier_attachments")

    op.drop_constraint("ck_supplier_status", "supplier", type_="check")
    op.create_check_constraint(
        "ck_supplier_status",
        "supplier",
        "status IN ('active', 'inactive', 'blocked', 'suspended')",
    )
