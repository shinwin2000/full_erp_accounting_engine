#!/usr/bin/env python3
"""
Module: employee_document_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model SQLAlchemy untuk tabel employee_documents - berkas
               kependudukan/kepesertaan karyawan (KTP, KK, BPJS
               Kesehatan, BPJS Ketenagakerjaan, NPWP, ijazah, dll).

Satu karyawan bisa punya banyak dokumen (beda dari foto profil yang
cuma satu) - lihat catatan lengkap di
migrations/versions/employee_documents_001.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, LargeBinary, String, Text, func
from sqlalchemy.schema import FetchedValue
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base

if TYPE_CHECKING:
    from infrastructure.persistence_orm.employee_table import EmployeeTable

DOCUMENT_TYPES = (
    "ktp", "kk", "bpjs_kesehatan", "bpjs_ketenagakerjaan", "npwp", "ijazah", "other",
)


class EmployeeDocumentTable(Base):
    """Satu baris = satu berkas dokumen milik seorang karyawan."""

    __tablename__ = "employee_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id", ondelete="CASCADE"), nullable=False
    )
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    document_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    document_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    file_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    file_mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Nomor urut sesuai urutan INSERT sungguhan di database (lihat
    # migrations/versions/employee_documents_seq_001.py) - dipakai untuk
    # mengurutkan daftar dokumen, BUKAN `id` (UUID v4 acak, tidak
    # mencerminkan urutan pembuatan) atau `created_at` (bisa kembar kalau
    # dua dokumen diupload sangat berdekatan).
    # FIX: migrasi (employee_documents_seq_001.py) sudah memasang
    # server_default=nextval(...) di level database, TAPI mapping ORM di
    # sini sebelumnya tidak diberi tahu soal itu - akibatnya SQLAlchemy
    # mengira kolom ini tidak punya default sama sekali dan selalu
    # mengirim NULL eksplisit saat INSERT, melanggar NOT NULL constraint
    # ("null value in column upload_seq violates not-null constraint").
    # server_default=FetchedValue() memberi tahu SQLAlchemy: percayakan ke
    # DB (jangan kirim nilai saat INSERT), lalu ambil nilai yang
    # di-generate lewat RETURNING setelahnya.
    upload_seq: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=FetchedValue()
    )

    employee: Mapped[EmployeeTable] = relationship("EmployeeTable", back_populates="documents")

    __table_args__ = (
        CheckConstraint(
            "document_type IN ('ktp', 'kk', 'bpjs_kesehatan', 'bpjs_ketenagakerjaan', "
            "'npwp', 'ijazah', 'other')",
            name="ck_employee_documents_type",
        ),
    )

    def to_dict(self, include_file_data: bool = False) -> dict[str, Any]:
        """include_file_data=False secara default supaya daftar dokumen
        tetap ringan (bytea gambar/PDF bisa besar) - isi file cuma
        diambil lewat endpoint download terpisah."""
        data = {
            "id": str(self.id),
            "employee_id": str(self.employee_id),
            "document_type": self.document_type,
            "document_label": self.document_label,
            "document_number": self.document_number,
            "file_filename": self.file_filename,
            "file_mime_type": self.file_mime_type,
            "notes": self.notes,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_file_data:
            data["file_data"] = self.file_data
        return data


__all__ = ["EmployeeDocumentTable", "DOCUMENT_TYPES"]
