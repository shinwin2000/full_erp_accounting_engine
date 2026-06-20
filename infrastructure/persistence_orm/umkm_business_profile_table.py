#!/usr/bin/env python3
"""
Module: umkm_business_profile_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk profil bisnis UMKM (simplified accounting).
"""

from __future__ import annotations
from uuid import UUID

import uuid
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class UMKMProfileTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "umkm_profile"
    __table_args__ = (
        CheckConstraint(
            "business_type IN ('sole_proprietor', 'partnership', 'individual')",
            name="ck_umkm_business_type",
        ),
        CheckConstraint(
            "tax_method IN ('cash', 'accrual')",
            name="ck_umkm_tax_method",
        ),
        Index("idx_umkm_profile_legal_entity", "legal_entity_id"),
        Index("idx_umkm_profile_business_type", "business_type"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_name: Mapped[str] = mapped_column(String(200), nullable=False)
    business_type: Mapped[str] = mapped_column(String(20), nullable=False, default="individual")
    taxpayer_npwp: Mapped[str | None] = mapped_column(String(20), nullable=True)
    business_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    uses_umkm_tax: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tax_method: Mapped[str] = mapped_column(String(10), nullable=False, default="cash")
    annual_revenue_threshold: Mapped[int | None] = mapped_column(nullable=True)
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "business_name": self.business_name,
            "business_type": self.business_type,
            "taxpayer_npwp": self.taxpayer_npwp,
            "business_address": self.business_address,
            "uses_umkm_tax": self.uses_umkm_tax,
            "tax_method": self.tax_method,
            "annual_revenue_threshold": self.annual_revenue_threshold,
            "extra_metadata": self.extra_metadata,
            "legal_entity_id": str(self.legal_entity_id),
            "created_by": str(self.created_by) if self.created_by else None,
            "updated_by": str(self.updated_by) if self.updated_by else None,
        }


__all__ = ["UMKMProfileTable"]