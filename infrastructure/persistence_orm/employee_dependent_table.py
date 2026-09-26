#!/usr/bin/env python3
"""
Module: employee_dependent_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model SQLAlchemy untuk tabel employee_dependents - data
               tanggungan/keluarga karyawan (pasangan, anak, orang tua,
               lain-lain).

Data ini relevan untuk PTKP (Penghasilan Tidak Kena Pajak) - status PTKP
karyawan (employee.ptkp_status, mis. "K/2") ditentukan oleh status kawin
DAN jumlah tanggungan, jadi tabel ini bukan sekadar catatan HR tapi juga
input untuk perhitungan PPh 21.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base

if TYPE_CHECKING:
    from infrastructure.persistence_orm.employee_table import EmployeeTable


class EmployeeDependentTable(Base):
    """Satu baris = satu anggota keluarga/tanggungan seorang karyawan."""

    __tablename__ = "employee_dependents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id", ondelete="CASCADE"), nullable=False
    )
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # spouse (pasangan) | child (anak) | parent (orang tua) | other (lain-lain)
    relationship_type: Mapped[str] = mapped_column(String(20), nullable=False)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    occupation: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_ptkp_dependent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    employee: Mapped[EmployeeTable] = relationship("EmployeeTable", back_populates="dependents")

    __table_args__ = (
        CheckConstraint(
            "relationship_type IN ('spouse', 'child', 'parent', 'other')",
            name="ck_employee_dependents_relationship_type",
        ),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "employee_id": str(self.employee_id),
            "full_name": self.full_name,
            "relationship_type": self.relationship_type,
            "birth_date": self.birth_date.isoformat() if self.birth_date else None,
            "occupation": self.occupation,
            "is_ptkp_dependent": self.is_ptkp_dependent,
            "notes": self.notes,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


__all__ = ["EmployeeDependentTable"]
