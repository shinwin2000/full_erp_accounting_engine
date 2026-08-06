#!/usr/bin/env python3
"""
Module: approval_delegation_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk delegasi wewenang approval — memungkinkan user
                mendelegasikan tugas approval-nya ke user lain untuk
                periode tertentu (mis. saat cuti).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Date, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class ApprovalDelegationTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """Model untuk tabel approval_delegation."""

    __tablename__ = "approval_delegation"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_approval_delegation_dates"),
        Index("idx_approval_delegation_delegator", "delegator_id"),
        Index("idx_approval_delegation_delegate_to", "delegate_to_id"),
        Index("idx_approval_delegation_active", "is_active"),
        Index("idx_approval_delegation_legal_entity", "legal_entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    delegator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    delegator_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    delegate_to_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    delegate_to_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "delegator_id": str(self.delegator_id),
            "delegator_name": self.delegator_name,
            "delegate_to_id": str(self.delegate_to_id),
            "delegate_to_name": self.delegate_to_name,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "reason": self.reason,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by) if self.created_by else None,
            "legal_entity_id": str(self.legal_entity_id),
        }


__all__ = ["ApprovalDelegationTable"]
