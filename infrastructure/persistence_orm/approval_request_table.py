#!/usr/bin/env python3
"""
Module: approval_request_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk menyimpan permintaan persetujuan (approval requests)
               dalam workflow approval. Mendukung multi-level approval,
               escalation, deadline, dan audit trail.
Dependencies:
- sqlalchemy, uuid, datetime
- base_model, LegalEntityMixin, TimestampMixin, SoftDeleteMixin, VersionMixin
Audit: Setiap perubahan status approval dicatat di event store.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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


class ApprovalRequestTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel approval request (permintaan persetujuan).
    """

    __tablename__ = "approval_request"
    __table_args__ = (
        UniqueConstraint(
            "request_number", "legal_entity_id", name="uq_approval_request_number_legal_entity"
        ),
        CheckConstraint(
            "request_number IS NOT NULL AND request_number != ''", name="ck_approval_request_number"
        ),
        CheckConstraint(
            "entity_type IN ('journal', 'ap_invoice', 'ar_invoice', 'payment', 'purchase_order', 'sales_order', 'budget', 'master_data')",
            name="ck_approval_entity_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled', 'escalated', 'expired')",
            name="ck_approval_status",
        ),
        CheckConstraint(
            "priority IN (1, 2, 3, 4, 5)", name="ck_approval_priority"
        ),
        Index("idx_approval_request_number", "request_number"),
        Index("idx_approval_entity", "entity_type", "entity_id"),
        Index("idx_approval_approver", "approver_id"),
        Index("idx_approval_status", "status"),
        Index("idx_approval_deadline", "deadline"),
        Index("idx_approval_legal_entity", "legal_entity_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Nomor permintaan (human-readable)
    request_number: Mapped[str] = mapped_column(String(50), nullable=False)

    # Entity yang memerlukan persetujuan
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entity_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Data entity snapshot (opsional, untuk audit)
    entity_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Nilai moneter yang diajukan (opsional, tidak semua entity_type punya amount)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Requester (denormalized untuk kemudahan tampilan tanpa join ke IAM)
    requester_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Level approval saat ini (naik saat escalate; dipakai bareng approval_matrix)
    current_level: Mapped[int] = mapped_column(nullable=False, default=1)
    approval_matrix_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Approval metadata
    approver_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approver_name: Mapped[str] = mapped_column(String(200), nullable=False)
    approver_role: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    # Priority (1=highest, 5=lowest)
    priority: Mapped[int] = mapped_column(nullable=False, default=3)

    # Deadline
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Comments and notes
    requester_comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_comments: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Action details
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Escalation / cancellation
    escalated_to: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit
    requested_by: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================
    # (optional) bisa menambahkan relationship ke ApprovalRuleTable jika diperlukan,
    # tapi biasanya tidak langsung karena rule terpisah.

    # ========================================================================
    # PROPERTIES
    # ========================================================================
    @property
    def is_pending(self) -> bool:
        return self.status == "pending"

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    @property
    def is_rejected(self) -> bool:
        return self.status == "rejected"

    @property
    def is_escalated(self) -> bool:
        return self.status == "escalated"

    @property
    def is_expired(self) -> bool:
        return self.status == "expired"

    @property
    def is_overdue(self) -> bool:
        if self.deadline and self.status == "pending":
            return datetime.utcnow() > self.deadline
        return False

    # ========================================================================
    # METHODS
    # ========================================================================
    def approve(self, approved_by: uuid.UUID, comments: str | None = None) -> None:
        """Approve the request."""
        if self.status != "pending":
            raise ValueError(f"Cannot approve request with status {self.status}")
        self.status = "approved"
        self.approved_by = approved_by
        self.approved_at = datetime.utcnow()
        if comments:
            self.approval_comments = comments
        self.increment_version()

    def reject(self, approved_by: uuid.UUID, comments: str) -> None:
        """Reject the request."""
        if self.status != "pending":
            raise ValueError(f"Cannot reject request with status {self.status}")
        self.status = "rejected"
        self.approved_by = approved_by
        self.approved_at = datetime.utcnow()
        self.approval_comments = comments
        self.increment_version()

    def escalate(self, escalated_to: uuid.UUID, reason: str) -> None:
        """Escalate request to a higher authority."""
        if self.status != "pending":
            raise ValueError(f"Cannot escalate request with status {self.status}")
        self.status = "escalated"
        self.escalated_to = escalated_to
        self.escalated_at = datetime.utcnow()
        self.approval_comments = reason
        self.current_level += 1
        self.increment_version()

    def cancel(self, cancelled_by: uuid.UUID, reason: str) -> None:
        """Cancel the request (by requester)."""
        if self.status not in ("pending", "escalated"):
            raise ValueError(f"Cannot cancel request with status {self.status}")
        self.status = "cancelled"
        self.cancelled_by = cancelled_by
        self.cancelled_at = datetime.utcnow()
        self.cancellation_reason = reason
        self.increment_version()

    def expire(self) -> None:
        """Mark request as expired (deadline passed)."""
        if self.status == "pending":
            self.status = "expired"
            self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "request_number": self.request_number,
            "entity_type": self.entity_type,
            "entity_id": str(self.entity_id),
            "entity_reference": self.entity_reference,
            "entity_snapshot": self.entity_snapshot,
            "amount": float(self.amount) if self.amount is not None else None,
            "currency": self.currency,
            "requester_name": self.requester_name,
            "current_level": self.current_level,
            "approval_matrix_id": str(self.approval_matrix_id) if self.approval_matrix_id else None,
            "approver_id": str(self.approver_id),
            "approver_name": self.approver_name,
            "status": self.status,
            "priority": self.priority,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "is_overdue": self.is_overdue,
            "requester_comments": self.requester_comments,
            "approval_comments": self.approval_comments,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "requested_by": str(self.requested_by),
            "legal_entity_id": str(self.legal_entity_id),
            "version": self.version,
        }


__all__ = ["ApprovalRequestTable"]
