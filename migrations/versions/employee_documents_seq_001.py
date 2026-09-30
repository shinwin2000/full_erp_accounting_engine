"""Add upload_seq column to employee_documents for stable insertion order

Sebelumnya daftar dokumen diurutkan pakai `created_at` - tapi kalau dua
dokumen diupload sangat berdekatan (bisa kejadian saat upload cepat
berturut-turut), timestamp-nya bisa sama persis, dan urutan tampil jadi
tidak stabil/tidak terjamin sesuai urutan input.

`id` (UUID v4, acak) TIDAK BISA dipakai untuk ini - UUID v4 sengaja
dibuat acak, bukan urut. Solusi yang benar: sequence Postgres terpisah
yang otomatis naik sesuai urutan INSERT sungguhan di database
(nextval()), lalu dipakai sebagai kunci urut utama saat menampilkan
daftar dokumen - bukan reinterpretasi dari UUID atau timestamp.

Revision ID: employee_documents_seq_001
Revises: employee_documents_001
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "employee_documents_seq_001"
down_revision = "employee_documents_001"
branch_labels = None
depends_on = None

SEQ_NAME = "employee_documents_upload_seq"


def upgrade() -> None:
    op.execute(f"CREATE SEQUENCE {SEQ_NAME}")
    op.add_column(
        "employee_documents",
        sa.Column(
            "upload_seq",
            sa.BigInteger(),
            server_default=sa.text(f"nextval('{SEQ_NAME}')"),
            nullable=False,
        ),
    )
    op.execute(f"ALTER SEQUENCE {SEQ_NAME} OWNED BY employee_documents.upload_seq")

    # Isi ulang baris yang sudah ada (kalau ada) berdasarkan created_at
    # supaya urutannya tetap masuk akal untuk data lama - baris baru
    # setelah ini otomatis dapat nomor lewat nextval() di atas.
    op.execute(
        """
        UPDATE employee_documents
        SET upload_seq = sub.rn
        FROM (
            SELECT id, ROW_NUMBER() OVER (ORDER BY created_at) AS rn
            FROM employee_documents
        ) AS sub
        WHERE employee_documents.id = sub.id
        """
    )
    op.create_index(
        "idx_employee_documents_upload_seq", "employee_documents", ["upload_seq"]
    )


def downgrade() -> None:
    op.drop_index("idx_employee_documents_upload_seq", table_name="employee_documents")
    op.drop_column("employee_documents", "upload_seq")
    op.execute(f"DROP SEQUENCE IF EXISTS {SEQ_NAME}")
