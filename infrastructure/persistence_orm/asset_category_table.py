#!/usr/bin/env python3
"""
Module: asset_category_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: SQLAlchemy ORM model for asset categories used in fixed asset management.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
)


class AssetCategoryTable(Base, TimestampMixin, SoftDeleteMixin, LegalEntityMixin):
    __tablename__ = "asset_categories"
    __table_args__ = (
        CheckConstraint("code IS NOT NULL AND code != ''", name="ck_asset_cat_code"),
        CheckConstraint("name IS NOT NULL AND name != ''", name="ck_asset_cat_name"),
        CheckConstraint("default_useful_life >= 1", name="ck_asset_cat_useful_life"),
        CheckConstraint(
            "default_depreciation_method IN ('straight_line', 'declining_balance', 'sum_of_years_digits', 'units_of_production')",
            name="ck_asset_cat_dep_method",
        ),
        Index("idx_asset_cat_legal_entity", "legal_entity_id"),
        Index("idx_asset_cat_code", "code", unique=True),
        Index("idx_asset_cat_active", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_useful_life: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    default_depreciation_method: Mapped[str] = mapped_column(String(30), nullable=False, default="straight_line")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    @property
    def is_straight_line(self) -> bool:
        return self.default_depreciation_method == "straight_line"

    def activate(self) -> None:
        self.is_active = True
        self.increment_version() if hasattr(self, "increment_version") else None

    def deactivate(self) -> None:
        self.is_active = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "default_useful_life": self.default_useful_life,
            "default_depreciation_method": self.default_depreciation_method,
            "is_active": self.is_active,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat() if hasattr(self, "created_at") else None,
        }


__all__ = ["AssetCategoryTable"]
