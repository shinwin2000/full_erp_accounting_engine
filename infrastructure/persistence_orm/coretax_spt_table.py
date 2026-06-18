#!/usr/bin/env python3
"""
Module: coretax_spt_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Tabel untuk SPT (Surat Pemberitahuan) yang disubmit ke Coretax DJP.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class CoretaxSPTTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin):
    __tablename__ = "coretax_spt"
    __table_args__ = (
        Index("idx_coretax_spt_npwp_tahun_bulan", "npwp", "tahun", "bulan"),
        Index("idx_coretax_spt_status", "status"),
        Index("idx_coretax_spt_legal_entity", "legal_entity_id")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    spt_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    spt_type: Mapped[str] = mapped_column(String(50), nullable=False)
    npwp: Mapped[str] = mapped_column(String(20), nullable=False)
    tahun: Mapped[int] = mapped_column(Integer, nullable=False)
    bulan: Mapped[int | None] = mapped_column(Integer, nullable=True)
    masa_pajak: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    xml_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    coretax_tracking_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approval_date: Mapped[date | None] = mapped_column(Date)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "spt_number": self.spt_number,
            "spt_type": self.spt_type,
            "npwp": self.npwp,
            "tahun": self.tahun,
            "bulan": self.bulan,
            "masa_pajak": self.masa_pajak,
            "status": self.status,
            "xml_content": self.xml_content,
            "coretax_tracking_id": self.coretax_tracking_id,
            "approval_date": self.approval_date.isoformat() if self.approval_date else None,
            "rejection_reason": self.rejection_reason,
            "submitted_by": str(self.submitted_by) if self.submitted_by else None,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }


__all__ = ["CoretaxSPTTable"]
