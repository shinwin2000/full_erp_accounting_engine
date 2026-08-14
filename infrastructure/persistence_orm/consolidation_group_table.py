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
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from infrastructure.persistence_orm.consolidation_group_member_table import (
        ConsolidationGroupMemberTable,
    )


class ConsolidationGroupTable(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "consolidation_group"
    __table_args__ = (
        # Partial unique index: nama grup hanya wajib unik di antara yang
        # masih aktif & belum di-soft-delete. Grup yang dinonaktifkan lewat
        # tombol "Hapus" (is_active=False) tidak lagi memblokir nama yang
        # sama dipakai grup baru. Lihat migrasi
        # e5f6a7b8c9d0_fix_consolidation_group_name_uniqueness.py.
        Index(
            "idx_cons_group_name_active",
            "group_name",
            unique=True,
            postgresql_where=text("is_active = true AND deleted_at IS NULL"),
        ),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_code: Mapped[str] = mapped_column(String(50), nullable=False)
    group_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    fiscal_year_start: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    fiscal_year_end: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # =========================================================================
    # RELATIONSHIPS � menggunakan string reference
    # =========================================================================
    members: Mapped[list[ConsolidationGroupMemberTable]] = relationship(
        "ConsolidationGroupMemberTable",
        back_populates="group",
        cascade="all, delete-orphan",
    )

    # =========================================================================
    # METHODS
    # =========================================================================
    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "group_code": self.group_code,
            "group_name": self.group_name,
            "description": self.description,
            "parent_entity_id": str(self.parent_entity_id) if self.parent_entity_id else None,
            "base_currency": self.base_currency,
            "fiscal_year_start": self.fiscal_year_start,
            "fiscal_year_end": self.fiscal_year_end,
            "is_active": self.is_active,
            "notes": self.notes,
            "created_by": str(self.created_by) if self.created_by else None,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


__all__ = ["ConsolidationGroupTable"]
