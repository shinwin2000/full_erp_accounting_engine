#!/usr/bin/env python3
"""
Module: coretax_nsfp_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Tabel untuk NSFP (Nomor Seri Faktur Pajak) dari Coretax DJP.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base, TimestampMixin, UUIDMixin


class NSFStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    PARTIALLY_USED = "PARTIALLY_USED"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class CoretaxNSFPTable(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "coretax_nsfp"
    __table_args__ = (
        CheckConstraint("start_number > 0", name="ck_nsfp_start_positive"),
        CheckConstraint("end_number >= start_number", name="ck_nsfp_end_ge_start"),
        CheckConstraint(
            "current_number BETWEEN start_number AND end_number",
            name="ck_nsfp_current_in_range",
        ),
        CheckConstraint("used_count >= 0", name="ck_nsfp_used_count"),
        Index("ix_nsfp_legal_status", "legal_entity_id", "status"),
        UniqueConstraint(
            "legal_entity_id", "start_number", name="uq_nsfp_legal_start"
        ),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    start_number: Mapped[int] = mapped_column(Integer, nullable=False)
    end_number: Mapped[int] = mapped_column(Integer, nullable=False)
    current_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[NSFStatus] = mapped_column(
        Enum(NSFStatus), default=NSFStatus.ACTIVE, nullable=False, index=True
    )
    request_id: Mapped[str | None] = mapped_column(String(100))
    approval_code: Mapped[str | None] = mapped_column(String(50))
    issued_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("legal_entity.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(200))

    @property
    def remaining(self) -> int:
        return self.end_number - self.current_number

    @property
    def total_quota(self) -> int:
        return self.end_number - self.start_number + 1

    def is_available(self) -> bool:
        return self.status == NSFStatus.ACTIVE and self.current_number < self.end_number

    def allocate_next_number(self) -> int:
        if not self.is_available():
            raise ValueError(
                f"NSFP range {self.start_number}-{self.end_number} tidak tersedia"
            )
        next_num = self.current_number + 1
        self.current_number = next_num
        self.used_count += 1
        if self.current_number == self.end_number:
            self.status = NSFStatus.EXHAUSTED
        elif self.used_count > 0:
            self.status = NSFStatus.PARTIALLY_USED
        return next_num

    def mark_exhausted(self) -> None:
        self.status = NSFStatus.EXHAUSTED

    def cancel(self, user_id: uuid.UUID, reason: str) -> None:
        self.status = NSFStatus.CANCELLED
        self.cancelled_by = user_id
        self.cancelled_at = datetime.now(UTC)
        self.cancellation_reason = reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "start_number": self.start_number,
            "end_number": self.end_number,
            "current_number": self.current_number,
            "status": self.status.value,
            "request_id": self.request_id,
            "approval_code": self.approval_code,
            "issued_date": self.issued_date.isoformat(),
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "legal_entity_id": str(self.legal_entity_id),
            "used_count": self.used_count,
            "remaining": self.remaining,
            "total_quota": self.total_quota,
            "cancelled_by": str(self.cancelled_by) if self.cancelled_by else None,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "cancellation_reason": self.cancellation_reason,
        }


__all__ = ["CoretaxNSFPTable", "NSFStatus"]
