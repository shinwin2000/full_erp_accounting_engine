#!/usr/bin/env python3
"""
Module: fixed_asset_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel fixed_asset.
               Tabel ini menyimpan data master aset tetap (fixed assets),
               termasuk kode aset, nama, kategori, tanggal perolehan, biaya perolehan,
               nilai residu, metode depresiasi, masa manfaat, akumulasi depresiasi,
               dan status aset. Digunakan oleh modul Fixed Asset Management.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class FixedAssetTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel fixed_asset.
    """

    __tablename__ = "fixed_asset"
    __table_args__ = (
        UniqueConstraint("asset_code", "legal_entity_id", name="uq_fixed_asset_code_legal_entity"),
        CheckConstraint("asset_code IS NOT NULL AND asset_code != ''", name="ck_fixed_asset_code"),
        CheckConstraint("asset_name IS NOT NULL AND asset_name != ''", name="ck_fixed_asset_name"),
        CheckConstraint(
            "asset_category IS NOT NULL AND asset_category != ''", name="ck_fixed_asset_category"
        ),
        CheckConstraint(
            "depreciation_method IN ('straight_line', 'declining_balance', 'sum_of_years', 'units_of_production')",
            name="ck_fixed_asset_depreciation_method",
        ),
        CheckConstraint(
            "status IN ('active', 'fully_depreciated', 'disposed', 'impaired')",
            name="ck_fixed_asset_status",
        ),
        CheckConstraint("acquisition_cost >= 0", name="ck_fixed_asset_cost_nonneg"),
        CheckConstraint("residual_value >= 0", name="ck_fixed_asset_residual_nonneg"),
        CheckConstraint(
            "residual_value <= acquisition_cost", name="ck_fixed_asset_residual_not_exceed"
        ),
        CheckConstraint("useful_life_years > 0", name="ck_fixed_asset_life_positive"),
        CheckConstraint(
            "depreciation_rate >= 0 AND depreciation_rate <= 100", name="ck_fixed_asset_rate_range"
        ),
        CheckConstraint("accumulated_depreciation >= 0", name="ck_fixed_asset_accum_dep_nonneg"),
        Index("idx_fixed_asset_code", "asset_code"),
        Index("idx_fixed_asset_category", "asset_category"),
        Index("idx_fixed_asset_status", "status"),
        Index("idx_fixed_asset_legal_entity", "legal_entity_id"),
        Index("idx_fixed_asset_acquisition_date", "acquisition_date"),
        Index("idx_fixed_asset_supplier", "supplier_id"),
        Index("idx_fixed_asset_is_active", "is_active")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Asset identification
    asset_code: Mapped[str] = mapped_column(String(30), nullable=False)
    asset_name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_category: Mapped[str] = mapped_column(String(50), nullable=False)

    # Acquisition
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    acquisition_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    residual_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Depreciation
    useful_life_years: Mapped[int] = mapped_column(Integer, nullable=False)
    depreciation_method: Mapped[str] = mapped_column(
        String(25), nullable=False, default="straight_line"
    )
    depreciation_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    # Current state
    accumulated_depreciation: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    last_depreciation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    current_period_depreciation: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )

    # Location and responsibility
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    responsible_party: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Reference to purchase
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplier.id"), nullable=True
    )
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Serial number
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Revaluation frequency
    revaluation_frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="never")

    # Notes
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    depreciation_schedule: Mapped[list[DepreciationScheduleTable]] = relationship(
        "DepreciationScheduleTable", back_populates="asset", cascade="all, delete-orphan"
    )

    revaluations: Mapped[list[RevaluationTable]] = relationship(
        "RevaluationTable", back_populates="asset", cascade="all, delete-orphan"
    )

    disposals: Mapped[list[DisposalTable]] = relationship(
        "DisposalTable", back_populates="asset", cascade="all, delete-orphan"
    )

    impairment_tests: Mapped[list[ImpairmentTestTable]] = relationship(
        "ImpairmentTestTable", back_populates="asset", cascade="all, delete-orphan"
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def net_book_value(self) -> Decimal:
        return max(Decimal(0), self.acquisition_cost - self.accumulated_depreciation)

    @property
    def is_fully_depreciated(self) -> bool:
        return self.net_book_value <= self.residual_value

    @property
    def depreciation_percentage(self) -> Decimal:
        if self.useful_life_years > 0:
            return Decimal(100) / Decimal(self.useful_life_years)
        return Decimal(0)

    @property
    def remaining_useful_life_years(self) -> Decimal:
        if self.depreciation_percentage == 0:
            return Decimal(0)
        annual_depreciation = self.acquisition_cost * (self.depreciation_percentage / 100)
        if annual_depreciation == 0:
            return Decimal(0)
        remaining_value = self.net_book_value - self.residual_value
        return remaining_value / annual_depreciation

    @property
    def is_active_asset(self) -> bool:
        return self.status == "active" and self.is_active

    # ========================================================================
    # METHODS
    # ========================================================================

    def record_depreciation(self, amount: Decimal, period_date: date) -> None:
        self.accumulated_depreciation += amount
        self.current_period_depreciation = amount
        self.last_depreciation_date = period_date
        if self.is_fully_depreciated:
            self.status = "fully_depreciated"
        self.increment_version()

    def revalue(self, new_acquisition_cost: Decimal, new_accumulated_depreciation: Decimal) -> None:
        self.acquisition_cost = new_acquisition_cost
        self.accumulated_depreciation = new_accumulated_depreciation
        self.increment_version()

    def dispose(self, disposal_date: date) -> None:
        self.status = "disposed"
        self.is_active = False
        self.increment_version()

    def impair(self, impairment_loss: Decimal) -> None:
        self.acquisition_cost -= impairment_loss
        self.status = "impaired"
        self.increment_version()

    def activate(self) -> None:
        self.status = "active"
        self.is_active = True
        self.increment_version()

    def can_depreciate(self, as_of_date: date) -> bool:
        if self.status not in ("active", "impaired"):
            return False
        if self.is_fully_depreciated:
            return False
        if self.last_depreciation_date and self.last_depreciation_date >= as_of_date:
            return False
        return True


__all__ = ["FixedAssetTable"]
