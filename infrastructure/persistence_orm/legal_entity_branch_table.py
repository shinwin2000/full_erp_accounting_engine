#!/usr/bin/env python3
"""
Module: legal_entity_branch_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: SQLAlchemy ORM model untuk tabel legal_entity_branch.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base


class LegalEntityBranchTable(Base):
    __tablename__ = "legal_entity_branch"
    __table_args__ = (
        Index("idx_leb_parent", "parent_entity_id"),
        Index("idx_leb_code", "branch_code")
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("legal_entity.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_name: Mapped[str] = mapped_column(String(200), nullable=False)
    branch_code: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    manager_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    parent_entity: Mapped[LegalEntityTable] = relationship(
        "LegalEntityTable", back_populates="branches", foreign_keys=[parent_entity_id]
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "parent_entity_id": str(self.parent_entity_id),
            "branch_name": self.branch_name,
            "branch_code": self.branch_code,
            "address": self.address,
            "city": self.city,
            "phone": self.phone,
            "manager_name": self.manager_name,
            "is_active": self.is_active,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


__all__ = ["LegalEntityBranchTable"]
