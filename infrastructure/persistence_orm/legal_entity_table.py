#!/usr/bin/env python3
"""
Module: legal_entity_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel legal_entity (entitas hukum).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class LegalEntityTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin):
    __tablename__ = "legal_entity"
    __table_args__ = (
        CheckConstraint(
            "legal_name IS NOT NULL AND legal_name != ''", name="ck_legal_entity_legal_name"
        ),
        Index("idx_legal_entity_npwp", "npwp"),
        Index("idx_legal_entity_parent", "parent_company_id"),
        Index("idx_legal_entity_consolidation", "consolidation_group_id")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    trade_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    registration_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    npwp: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True)

    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="ID")
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    website: Mapped[str | None] = mapped_column(String(200), nullable=True)

    established_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    fiscal_year_start: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    fiscal_year_end: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    functional_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    tax_office: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tax_office_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    tax_classification: Mapped[str | None] = mapped_column(String(50), nullable=True)
    taxable_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    annual_tax_return_due_date: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_tax_due_date: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_vat_collector: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    vat_collector_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_withholding_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    parent_company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entity.id", use_alter=True, name="fk_legal_entity_parent"), nullable=True
    )
    consolidation_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    extra_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ===== RELATIONSHIPS (semua menggunakan string, tanpa impor langsung) =====
    parent: Mapped[LegalEntityTable | None] = relationship(
        "LegalEntityTable", remote_side=[id], back_populates="children"
    )
    children: Mapped[list[LegalEntityTable]] = relationship(
        "LegalEntityTable", back_populates="parent", cascade="all, delete-orphan"
    )
    branches: Mapped[list[LegalEntityBranchTable]] = relationship(
        "LegalEntityBranchTable", back_populates="parent_entity", cascade="all, delete-orphan"
    )
    accounts: Mapped[list[AccountTable]] = relationship(
        "AccountTable", back_populates="legal_entity", cascade="all, delete-orphan"
    )
    users: Mapped[list[IAMUserTable]] = relationship(
        "IAMUserTable",
        secondary="iam_user_legal_entity",
        viewonly=True,
        lazy="selectin",
    )
    journals: Mapped[list[JournalHeaderTable]] = relationship(
        "JournalHeaderTable", viewonly=True
    )
    user: Mapped[IAMUserTable | None] = relationship(
        "IAMUserTable", back_populates="legal_entity"
    )
    consolidation_members: Mapped[list[ConsolidationGroupMemberTable]] = relationship(
        "ConsolidationGroupMemberTable", back_populates="entity", cascade="all, delete-orphan"
    )
    nsfp_ranges: Mapped[list[CoretaxNSFPTable]] = relationship(
        "CoretaxNSFPTable", back_populates="legal_entity", cascade="all, delete-orphan"
    )
    intangible_assets: Mapped[list[IntangibleAssetTable]] = relationship(
        "IntangibleAssetTable", back_populates="legal_entity", cascade="all, delete-orphan"
    )

    @property
    def is_parent_company(self) -> bool:
        return self.entity_type == "parent_company"

    @property
    def is_subsidiary(self) -> bool:
        return self.entity_type == "subsidiary"

    @property
    def is_branch(self) -> bool:
        return self.entity_type == "branch"

    @property
    def full_address(self) -> str:
        parts = []
        if self.address:
            parts.append(self.address)
        if self.city:
            parts.append(self.city)
        if self.postal_code:
            parts.append(self.postal_code)
        if self.country:
            parts.append(self.country)
        return ", ".join(parts)

    def activate(self) -> None:
        self.is_active = True
        self.status = "active"
        self.increment_version()

    def deactivate(self, reason: str | None = None) -> None:
        self.is_active = False
        self.status = "inactive"
        if reason and self.extra_metadata:
            self.extra_metadata["deactivation_reason"] = reason
        self.increment_version()

    def suspend(self, reason: str | None = None) -> None:
        self.status = "suspended"
        if reason and self.extra_metadata:
            self.extra_metadata["suspension_reason"] = reason
        self.increment_version()

    def liquidate(self, liquidation_date: date) -> None:
        self.status = "liquidated"
        if self.extra_metadata:
            self.extra_metadata["liquidation_date"] = liquidation_date.isoformat()
        self.is_active = False
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "legal_name": self.legal_name,
            "trade_name": self.trade_name,
            "entity_type": self.entity_type,
            "registration_number": self.registration_number,
            "npwp": self.npwp,
            "address": self.address,
            "city": self.city,
            "postal_code": self.postal_code,
            "country": self.country,
            "phone": self.phone,
            "email": self.email,
            "website": self.website,
            "established_date": self.established_date.isoformat() if self.established_date else None,
            "fiscal_year_start": self.fiscal_year_start,
            "fiscal_year_end": self.fiscal_year_end,
            "base_currency": self.base_currency,
            "functional_currency": self.functional_currency,
            "tax_office": self.tax_office,
            "tax_office_code": self.tax_office_code,
            "tax_classification": self.tax_classification,
            "taxable_date": self.taxable_date.isoformat() if self.taxable_date else None,
            "annual_tax_return_due_date": self.annual_tax_return_due_date,
            "monthly_tax_due_date": self.monthly_tax_due_date,
            "is_vat_collector": self.is_vat_collector,
            "vat_collector_number": self.vat_collector_number,
            "is_withholding_agent": self.is_withholding_agent,
            "status": self.status,
            "is_active": self.is_active,
            "parent_company_id": str(self.parent_company_id) if self.parent_company_id else None,
            "consolidation_group_id": str(self.consolidation_group_id) if self.consolidation_group_id else None,
            "logo_url": self.logo_url,
            "extra_metadata": self.extra_metadata,
            "created_by": str(self.created_by) if self.created_by else None,
            "version": self.version,
        }


__all__ = ["LegalEntityTable"]
