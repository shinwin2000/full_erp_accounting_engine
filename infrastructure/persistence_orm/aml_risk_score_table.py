#!/usr/bin/env python3
"""
Module: aml_risk_score_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk menyimpan skor risiko AML pelanggan.
               Mendukung perhitungan risiko periodik, kategori risiko,
               faktor risiko, dan audit trail perubahan.
Dependencies:
- sqlalchemy, uuid, decimal, datetime
- base_model, LegalEntityMixin, TimestampMixin, SoftDeleteMixin, VersionMixin
Audit: Setiap perubahan risiko dicatat di event store.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
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


class AMLRiskScoreTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk AML risk score (skor risiko pelanggan).
    """

    __tablename__ = "aml_risk_score"
    __table_args__ = (
        UniqueConstraint(
            "customer_id", "legal_entity_id", name="uq_aml_risk_customer_legal"
        ),
        CheckConstraint(
            "risk_score BETWEEN 0 AND 100", name="ck_aml_risk_score_range"
        ),
        CheckConstraint(
            "risk_category IN ('low', 'medium', 'high', 'very_high')",
            name="ck_aml_risk_category",
        ),
        CheckConstraint(
            "scoring_model IN ('rule_based', 'ml_model_v1', 'external')",
            name="ck_aml_scoring_model",
        ),
        Index("idx_aml_risk_customer", "customer_id"),
        Index("idx_aml_risk_score", "risk_score"),
        Index("idx_aml_risk_category", "risk_category"),
        Index("idx_aml_risk_calculated_at", "calculated_at"),
        Index("idx_aml_risk_legal_entity", "legal_entity_id")
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Reference to customer (or entity being scored)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    customer_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="individual"  # individual, company
    )

    # Risk score and category
    risk_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=0
    )
    risk_category: Mapped[str] = mapped_column(String(20), nullable=False)

    # Scoring details
    scoring_model: Mapped[str] = mapped_column(String(30), nullable=False, default="rule_based")
    scoring_version: Mapped[str] = mapped_column(String(20), nullable=True)  # e.g., "v2.1"
    risk_factors: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )  # breakdown by factor

    # Additional AML data
    pep_status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pep_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    sanction_list_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sanction_list_details: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Override / manual adjustment
    manual_adjustment: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    adjustment_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    adjusted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    adjusted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Calculation timestamp
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # PROPERTIES
    # ========================================================================
    @property
    def is_high_risk(self) -> bool:
        return self.risk_category in ("high", "very_high")

    @property
    def is_low_risk(self) -> bool:
        return self.risk_category == "low"

    @property
    def effective_risk_score(self) -> Decimal:
        """Risk score including manual adjustment."""
        return self.risk_score + self.manual_adjustment

    @property
    def is_expired(self) -> bool:
        if self.valid_until:
            return datetime.utcnow() > self.valid_until
        return False

    # ========================================================================
    # METHODS
    # ========================================================================
    def update_risk_score(
        self,
        new_score: Decimal,
        new_category: str,
        risk_factors: dict[str, Any] | None = None,
        scoring_model: str | None = None,
    ) -> None:
        """Update risk score with new calculation."""
        if new_score < 0 or new_score > 100:
            raise ValueError("Risk score must be between 0 and 100")
        self.risk_score = new_score
        self.risk_category = new_category
        if risk_factors:
            self.risk_factors = risk_factors
        if scoring_model:
            self.scoring_model = scoring_model
        self.calculated_at = datetime.utcnow()
        self.increment_version()

    def apply_manual_adjustment(self, adjustment: Decimal, reason: str, adjusted_by: uuid.UUID) -> None:
        """Manually adjust risk score."""
        if adjustment < -100 or adjustment > 100:
            raise ValueError("Adjustment must be between -100 and +100")
        self.manual_adjustment = adjustment
        self.adjustment_reason = reason
        self.adjusted_by = adjusted_by
        self.adjusted_at = datetime.utcnow()
        self.increment_version()

    def set_pep_status(self, is_pep: bool, details: str | None = None) -> None:
        """Update PEP (Politically Exposed Person) status."""
        self.pep_status = is_pep
        self.pep_details = details
        self.increment_version()

    def set_sanction_hit(self, has_hit: bool, details: str | None = None) -> None:
        """Update sanction list hit status."""
        self.sanction_list_hit = has_hit
        self.sanction_list_details = details
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "customer_id": str(self.customer_id),
            "customer_type": self.customer_type,
            "risk_score": float(self.risk_score),
            "risk_category": self.risk_category,
            "scoring_model": self.scoring_model,
            "risk_factors": self.risk_factors,
            "pep_status": self.pep_status,
            "sanction_list_hit": self.sanction_list_hit,
            "manual_adjustment": float(self.manual_adjustment),
            "effective_risk_score": float(self.effective_risk_score),
            "calculated_at": self.calculated_at.isoformat(),
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "legal_entity_id": str(self.legal_entity_id),
            "version": self.version,
        }


__all__ = ["AMLRiskScoreTable"]
