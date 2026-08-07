#!/usr/bin/env python3
"""
Module: approval_matrix_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk approval matrix — konfigurasi aturan approval
                per entity_type/amount range, dengan daftar rule tersimpan
                sebagai JSONB (bukan baris terpisah seperti ApprovalRuleTable).

Catatan desain:
    Tabel ini SENGAJA dipisah dari ApprovalRuleTable. ApprovalRuleTable
    merepresentasikan satu baris rule routing runtime (approver per level),
    sedangkan ApprovalMatrixTable merepresentasikan objek konfigurasi bernama
    (matrix_code/matrix_name) yang dipakai fastapi_approval_router untuk
    CRUD matrix approval. Kalau ke depan mau digabung, perlu keputusan
    desain terpisah — jangan dipaksakan sekarang.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class ApprovalMatrixTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """Model untuk tabel approval_matrix (konfigurasi matrix approval)."""

    __tablename__ = "approval_matrix"
    __table_args__ = (
        UniqueConstraint(
            "matrix_code", "legal_entity_id", name="uq_approval_matrix_code_legal_entity"
        ),
        CheckConstraint(
            "matrix_code IS NOT NULL AND matrix_code != ''", name="ck_approval_matrix_code"
        ),
        CheckConstraint(
            "entity_type IN ('journal', 'ap_invoice', 'ar_invoice', 'payment', 'purchase_order', 'sales_order', 'budget', 'master_data')",
            name="ck_approval_matrix_entity_type",
        ),
        CheckConstraint("min_amount >= 0", name="ck_approval_matrix_min_amount_nonneg"),
        Index("idx_approval_matrix_entity_type", "entity_type"),
        Index("idx_approval_matrix_legal_entity", "legal_entity_id"),
        Index("idx_approval_matrix_is_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    matrix_code: Mapped[str] = mapped_column(String(50), nullable=False)
    matrix_name: Mapped[str] = mapped_column(String(200), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)

    min_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Daftar rule per level, mis: [{"level": 1, "approver_role": "manager", ...}, ...]
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "matrix_code": self.matrix_code,
            "matrix_name": self.matrix_name,
            "entity_type": self.entity_type,
            "min_amount": float(self.min_amount) if self.min_amount is not None else None,
            "max_amount": float(self.max_amount) if self.max_amount is not None else None,
            "currency": self.currency,
            "rules": self.rules,
            "is_active": self.is_active,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by) if self.created_by else None,
            "created_by_name": self.created_by_name,
            "version": self.version,
            "legal_entity_id": str(self.legal_entity_id),
        }


__all__ = ["ApprovalMatrixTable"]
