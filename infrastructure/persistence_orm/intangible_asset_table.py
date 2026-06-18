#!/usr/bin/env python3
"""
Module: intangible_asset_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Tabel untuk Aset Tidak Berwujud (Intangible Assets)
               Mendukung amortisasi, revaluasi, dan impairment.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, TimestampMixin, UUIDMixin


class IntangibleAssetType(str, enum.Enum):
    PATENT = "PATENT"
    TRADEMARK = "TRADEMARK"
    COPYRIGHT = "COPYRIGHT"
    SOFTWARE = "SOFTWARE"
    LICENSE = "LICENSE"
    GOODWILL = "GOODWILL"
    CUSTOMER_RELATIONSHIP = "CUSTOMER_RELATIONSHIP"
    OTHER = "OTHER"


class AmortizationMethod(str, enum.Enum):
    STRAIGHT_LINE = "STRAIGHT_LINE"
    DECLINING_BALANCE = "DECLINING_BALANCE"
    UNITS_OF_PRODUCTION = "UNITS_OF_PRODUCTION"


class IntangibleAssetTable(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "intangible_asset"
    __table_args__ = (
        CheckConstraint("useful_life_years > 0", name="ck_intangible_useful_life"),
        CheckConstraint("acquisition_cost >= 0", name="ck_intangible_acquisition_cost"),
        CheckConstraint("residual_value >= 0", name="ck_intangible_residual_value"),
        CheckConstraint("accumulated_amortization >= 0", name="ck_intangible_acc_amort"),
        CheckConstraint("carrying_amount >= 0", name="ck_intangible_carrying"),
        Index("ix_intangible_legal_entity", "legal_entity_id"),
        Index("ix_intangible_active", "is_active"),
        Index("ix_intangible_asset_code", "asset_code")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    asset_name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_type: Mapped[IntangibleAssetType] = mapped_column(Enum(IntangibleAssetType), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("legal_entity.id"), nullable=False)
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    acquisition_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    residual_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    useful_life_years: Mapped[int] = mapped_column(nullable=False)
    amortization_method: Mapped[AmortizationMethod] = mapped_column(Enum(AmortizationMethod), default=AmortizationMethod.STRAIGHT_LINE)
    accumulated_amortization: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    last_amortization_date: Mapped[date | None] = mapped_column(Date)
    carrying_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    impairment_loss: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    impairment_date: Mapped[date | None] = mapped_column(Date)
    revaluation_surplus: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    disposed_date: Mapped[date | None] = mapped_column(Date)
    disposal_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    supporting_document_url: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Relationships – all using string references (forward declarations)
    legal_entity: Mapped[LegalEntityTable] = relationship("LegalEntityTable", back_populates="intangible_assets")
    amortization_schedules: Mapped[list[AmortizationScheduleTable]] = relationship(
        "AmortizationScheduleTable", back_populates="asset", cascade="all, delete-orphan"
    )
    revaluations: Mapped[list[IntangibleRevaluationTable]] = relationship(
        "IntangibleRevaluationTable", back_populates="asset", cascade="all, delete-orphan"
    )

    @property
    def net_book_value(self) -> Decimal:
        return self.carrying_amount - self.impairment_loss

    def amortize(self, amount: Decimal, period_date: date) -> None:
        self.accumulated_amortization += amount
        self.carrying_amount = self.acquisition_cost - self.accumulated_amortization - self.impairment_loss
        self.last_amortization_date = period_date

    def impair(self, loss_amount: Decimal, as_of_date: date) -> None:
        if loss_amount > self.carrying_amount:
            loss_amount = self.carrying_amount
        self.impairment_loss = loss_amount
        self.impairment_date = as_of_date
        self.carrying_amount = self.acquisition_cost - self.accumulated_amortization - self.impairment_loss

    def revalue(self, new_carrying_amount: Decimal, surplus: Decimal, revaluation_date: date) -> None:
        self.carrying_amount = new_carrying_amount
        self.revaluation_surplus = surplus

    def dispose(self, disposal_date: date, amount: Decimal) -> None:
        self.is_active = False
        self.disposed_date = disposal_date
        self.disposal_amount = amount

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "asset_type": self.asset_type.value,
            "description": self.description,
            "legal_entity_id": str(self.legal_entity_id),
            "acquisition_date": self.acquisition_date.isoformat(),
            "acquisition_cost": float(self.acquisition_cost),
            "residual_value": float(self.residual_value),
            "useful_life_years": self.useful_life_years,
            "amortization_method": self.amortization_method.value,
            "accumulated_amortization": float(self.accumulated_amortization),
            "last_amortization_date": self.last_amortization_date.isoformat() if self.last_amortization_date else None,
            "carrying_amount": float(self.carrying_amount),
            "impairment_loss": float(self.impairment_loss),
            "impairment_date": self.impairment_date.isoformat() if self.impairment_date else None,
            "revaluation_surplus": float(self.revaluation_surplus),
            "is_active": self.is_active,
            "disposed_date": self.disposed_date.isoformat() if self.disposed_date else None,
            "disposal_amount": float(self.disposal_amount) if self.disposal_amount else None,
            "supporting_document_url": self.supporting_document_url,
        }


__all__ = ["AmortizationMethod", "IntangibleAssetTable", "IntangibleAssetType"]
