#!/usr/bin/env python3
"""
Module: legal_entity_branch_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: SQLAlchemy ORM model untuk tabel legal_entity_branch.

Changelog:
    - FIX: tambah kolom parent_entity_id (self-referential, NOT NULL).
    - FIX: tambah kolom deleted_at (soft delete, TIMESTAMP tanpa timezone).
    - FIX: type created_at/updated_at/deleted_at pakai TIMESTAMP (sesuai DB).
    - FIX: index idx_leb_parent pasang di parent_entity_id (sesuai DB).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base

if TYPE_CHECKING:
    from infrastructure.persistence_orm.legal_entity_table import LegalEntityTable


class LegalEntityBranchTable(Base):
    __tablename__ = "legal_entity_branch"  # type: ignore[assignment]
    __table_args__ = (
        # DB punya idx_leb_parent di kolom parent_entity_id
        Index("idx_leb_parent", "parent_entity_id"),
        Index("idx_leb_code", "branch_code"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("legal_entity.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # FIX: parent_entity_id NOT NULL sesuai DB
    parent_entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("legal_entity_branch.id", ondelete="SET NULL"),
        nullable=False,  # DB bilang NOT NULL
    )

    branch_name: Mapped[str] = mapped_column(String(200), nullable=False)
    branch_code: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    manager_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # FIX: pakai TIMESTAMP (tanpa timezone) sesuai DB
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # =========================================================================
    # RELATIONSHIP
    # =========================================================================
    parent_entity: Mapped[LegalEntityTable] = relationship(
        "LegalEntityTable",
        back_populates="branches",
        foreign_keys=[legal_entity_id],
    )

    def to_dict(self) -> dict[str, Any]:  # type: ignore[override]
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "parent_entity_id": str(self.parent_entity_id) if self.parent_entity_id else None,
            "branch_name": self.branch_name,
            "branch_code": self.branch_code,
            "address": self.address,
            "city": self.city,
            "postal_code": self.postal_code,
            "phone": self.phone,
            "email": self.email,
            "manager_name": self.manager_name,
            "status": self.status,
            "is_active": self.is_active,
            "notes": self.notes,
            "created_by": str(self.created_by) if self.created_by else None,
            "version": self.version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


__all__ = ["LegalEntityBranchTable"]
