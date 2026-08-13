#!/usr/bin/env python3
"""
Module: consolidation_group_member_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: SQLAlchemy ORM model untuk tabel consolidation_group_member.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from infrastructure.persistence_orm.consolidation_group_table import ConsolidationGroupTable


class ConsolidationGroupMemberTable(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "consolidation_group_member"
    __table_args__ = (
        UniqueConstraint("group_id", "entity_id", name="uq_group_entity"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("consolidation_group.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("legal_entity.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ownership_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.00"))
    consolidation_method: Mapped[str] = mapped_column(default="full")
    effective_date: Mapped[Any] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    group: Mapped[ConsolidationGroupTable] = relationship(
        "ConsolidationGroupTable",
        back_populates="members",
        foreign_keys=[group_id],
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "group_id": str(self.group_id),
            "entity_id": str(self.entity_id),
            "ownership_percentage": float(self.ownership_percentage),
            "consolidation_method": self.consolidation_method,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "notes": self.notes,
            "joined_at": self.joined_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


__all__ = ["ConsolidationGroupMemberTable"]
