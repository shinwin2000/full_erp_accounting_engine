#!/usr/bin/env python3
"""
Module: consolidation_group_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: SQLAlchemy ORM model untuk tabel consolidation_group.
               Mendefinisikan grup konsolidasi yang mengelompokkan beberapa
               entitas hukum (legal entity) untuk pelaporan keuangan konsolidasi.
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column, relationship)
- infrastructure.persistence_orm.base_model
Audit: Perubahan grup konsolidasi dicatat.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, SoftDeleteMixin, TimestampMixin


class ConsolidationGroupTable(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "consolidation_group"
    __table_args__ = (
        Index("idx_cons_group_name", "group_name", unique=True)
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    # Relationships - gunakan string reference
    members: Mapped[list[ConsolidationGroupMemberTable]] = relationship(
        "ConsolidationGroupMemberTable",
        back_populates="group",
        cascade="all, delete-orphan",
    )

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "group_name": self.group_name,
            "description": self.description,
            "is_active": self.is_active,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


__all__ = ["ConsolidationGroupTable"]
