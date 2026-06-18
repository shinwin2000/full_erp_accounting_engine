#!/usr/bin/env python3
"""
Module: aml_suspicious_transaction_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk mencatat transaksi mencurigakan (Suspicious Transaction Report - STR).
               Mendukung deteksi otomatis, review manual, filing to authorities,
               dan audit trail.
Dependencies:
- sqlalchemy, uuid, decimal, datetime
- base_model, LegalEntityMixin, TimestampMixin, SoftDeleteMixin, VersionMixin
Audit: Setiap perubahan status STR dicatat di event store.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
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


class AMLSuspiciousTransactionTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk mencatat transaksi mencurigakan (STR).
    """

    __tablename__ = "aml_suspicious_transaction"
    __table_args__ = (
        CheckConstraint(
            "detection_type IN ('automated_rule', 'manual_report', 'external_alert')",
            name="ck_aml_detection_type",
        ),
        CheckConstraint(
            "status IN ('pending_review', 'under_investigation', 'filed', 'dismissed', 'escalated')",
            name="ck_aml_str_status",
        ),
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high', 'critical')",
            name="ck_aml_str_risk",
        ),
        CheckConstraint("transaction_amount >= 0", name="ck_aml_str_amount_nonneg"),
        Index("idx_aml_str_customer", "customer_id"),
        Index("idx_aml_str_detected_at", "detected_at"),
        Index("idx_aml_str_status", "status"),
        Index("idx_aml_str_risk_level", "risk_level"),
        Index("idx_aml_str_reviewer", "reviewed_by"),
        Index("idx_aml_str_legal_entity", "legal_entity_id")
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Transaction reference
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    transaction_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # journal, payment, invoice, etc.
    transaction_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Customer information
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Transaction details
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    transaction_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Detection metadata
    detection_type: Mapped[str] = mapped_column(String(20), nullable=False)
    detection_rule_id: Mapped[str | None] = mapped_column(String(100), nullable=True)  # rule identifier
    detection_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=True)  # confidence score
    detection_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Risk assessment
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False, default="medium")
    risk_factors: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Status workflow
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_review")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Investigation (if escalated)
    investigation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    investigation_concluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    investigation_findings: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Filing to authorities (e.g., PPATK in Indonesia)
    filed_to_authority: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    filing_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Audit
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    detected_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # system or user
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # PROPERTIES
    # ========================================================================
    @property
    def is_pending(self) -> bool:
        return self.status == "pending_review"

    @property
    def is_under_investigation(self) -> bool:
        return self.status == "under_investigation"

    @property
    def is_filed(self) -> bool:
        return self.status == "filed"

    @property
    def is_dismissed(self) -> bool:
        return self.status == "dismissed"

    @property
    def is_escalated(self) -> bool:
        return self.status == "escalated"

    @property
    def requires_immediate_action(self) -> bool:
        return self.risk_level in ("high", "critical") and self.status == "pending_review"

    # ========================================================================
    # METHODS
    # ========================================================================
    def start_review(self, reviewer_id: uuid.UUID) -> None:
        """Start manual review of suspicious transaction."""
        if self.status != "pending_review":
            raise ValueError(f"Cannot review transaction with status {self.status}")
        self.reviewed_by = reviewer_id
        self.reviewed_at = datetime.utcnow()
        self.increment_version()

    def conclude_review(self, status: str, notes: str, is_filed: bool = False) -> None:
        """Conclude review with final disposition."""
        allowed_statuses = ["dismissed", "escalated", "filed"]
        if status not in allowed_statuses:
            raise ValueError(f"Invalid conclusion status: {status}")
        self.status = status
        self.review_notes = notes
        if is_filed or status == "filed":
            self.filed_to_authority = True
            self.filed_at = datetime.utcnow()
        self.increment_version()

    def escalate_to_investigation(self, investigator_id: uuid.UUID) -> None:
        """Escalate suspicious transaction to full investigation."""
        if self.status != "pending_review":
            raise ValueError(f"Cannot escalate from status {self.status}")
        self.status = "under_investigation"
        self.reviewed_by = investigator_id
        self.reviewed_at = datetime.utcnow()
        self.investigation_started_at = datetime.utcnow()
        self.increment_version()

    def conclude_investigation(self, findings: str, status: str, filing_reference: str | None = None) -> None:
        """Conclude investigation with final outcome."""
        if self.status != "under_investigation":
            raise ValueError(f"Cannot conclude investigation from status {self.status}")
        allowed = ["dismissed", "filed", "escalated"]
        if status not in allowed:
            raise ValueError(f"Invalid conclusion status: {status}")
        self.status = status
        self.investigation_findings = findings
        self.investigation_concluded_at = datetime.utcnow()
        if status == "filed":
            self.filed_to_authority = True
            self.filing_reference = filing_reference
            self.filed_at = datetime.utcnow()
        self.increment_version()

    def file_to_authority(self, filing_reference: str, filed_by: uuid.UUID) -> None:
        """File STR to regulatory authority (e.g., PPATK)."""
        if self.status not in ("under_investigation", "escalated"):
            raise ValueError(f"Cannot file STR from status {self.status}")
        self.status = "filed"
        self.filed_to_authority = True
        self.filing_reference = filing_reference
        self.filed_at = datetime.utcnow()
        self.filed_by = filed_by
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "transaction_id": str(self.transaction_id),
            "transaction_type": self.transaction_type,
            "transaction_number": self.transaction_number,
            "customer_id": str(self.customer_id),
            "customer_name": self.customer_name,
            "transaction_date": self.transaction_date.isoformat(),
            "transaction_amount": float(self.transaction_amount),
            "currency": self.currency,
            "detection_type": self.detection_type,
            "detection_score": float(self.detection_score) if self.detection_score else None,
            "risk_level": self.risk_level,
            "status": self.status,
            "review_notes": self.review_notes,
            "filed_to_authority": self.filed_to_authority,
            "filing_reference": self.filing_reference,
            "detected_at": self.detected_at.isoformat(),
            "legal_entity_id": str(self.legal_entity_id),
            "version": self.version,
        }


__all__ = ["AMLSuspiciousTransactionTable"]
