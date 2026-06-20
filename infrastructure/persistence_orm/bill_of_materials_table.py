#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: bill_of_materials_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel bill_of_materials (header).
               Tabel ini menyimpan Bill of Materials (BOM) untuk produk manufaktur.
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column, relationship)
- infrastructure.persistence_orm.base_model
Audit: Setiap perubahan BOM dicatat di event store.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class BillOfMaterialsTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel master Bill of Materials (Header).
    """
    __tablename__ = "bill_of_materials"
    __table_args__ = (
        UniqueConstraint("bom_code", "legal_entity_id", name="uq_bom_code_legal_entity"),
        CheckConstraint("bom_code IS NOT NULL", name="ck_bom_code"),
        CheckConstraint("product_id IS NOT NULL", name="ck_bom_product"),
        CheckConstraint(
            "status IN ('draft', 'active', 'inactive', 'obsolete')", name="ck_bom_status"
        ),
        Index("idx_bom_code", "bom_code"),
        Index("idx_bom_product", "product_id"),
        Index("idx_bom_status", "status"),
        Index("idx_bom_legal_entity", "legal_entity_id"),
        {"schema": "public", "extend_existing": True}
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bom_code: Mapped[str] = mapped_column(String(50), nullable=False)
    bom_name: Mapped[str] = mapped_column(String(200), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    # =========================================================================
    # RELATIONSHIP ke BillOfMaterialsLineTable (one-to-many)
    # Menggunakan string reference untuk menghindari import circular.
    # back_populates harus cocok dengan 'bom' di BillOfMaterialsLineTable.
    # =========================================================================
    lines: Mapped[list["BillOfMaterialsLineTable"]] = relationship(
        "BillOfMaterialsLineTable",
        back_populates="bom",
        cascade="all, delete-orphan",
        order_by="BillOfMaterialsLineTable.line_number",
    )

    @property
    def is_active_bom(self) -> bool:
        return self.status == "active"

    @property
    def is_draft(self) -> bool:
        return self.status == "draft"

    def activate(self) -> None:
        if self.status != "draft":
            raise ValueError(f"Cannot activate BOM with status {self.status}")
        self.status = "active"
        self.increment_version()

    def deactivate(self) -> None:
        if self.status == "active":
            self.status = "inactive"
            self.increment_version()

    def mark_obsolete(self) -> None:
        self.status = "obsolete"
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "bom_code": self.bom_code,
            "bom_name": self.bom_name,
            "product_id": str(self.product_id),
            "product_name": self.product_name,
            "version": self.version,
            "effective_date": self.effective_date.isoformat(),
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "status": self.status,
            "is_default": self.is_default,
            "notes": self.notes,
            "legal_entity_id": str(self.legal_entity_id),
        }


__all__ = ["BillOfMaterialsTable"]