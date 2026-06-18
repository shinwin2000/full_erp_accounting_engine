#!/usr/bin/env python3
"""
Module: warehouse_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel warehouse (gudang).
               Tabel ini menyimpan data gudang/lokasi penyimpanan barang,
               termasuk alamat, kapasitas, dan status operasional.
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column, relationship)
- sqlalchemy.dialects.postgresql (UUID, JSONB)
- infrastructure.persistence_orm.base_model (Base, TimestampMixin, SoftDeleteMixin, VersionMixin)
Audit: Setiap perubahan pada warehouse dicatat di event store.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)

if TYPE_CHECKING:
    from infrastructure.persistence_orm.inventory_item_table import InventoryItemTable
    from infrastructure.persistence_orm.inventory_movement_table import InventoryMovementTable
    from infrastructure.persistence_orm.stock_opname_table import StockOpnameTable


# ============================================================================
# WAREHOUSE MODEL
# ============================================================================


class WarehouseTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin):
    """
    Model untuk tabel warehouse.
    Menyimpan data gudang/lokasi penyimpanan.
    """

    __tablename__ = "warehouse"
    __table_args__ = (
        UniqueConstraint("warehouse_code", "legal_entity_id", name="uq_warehouse_code_entity"),
        UniqueConstraint("name", "legal_entity_id", name="uq_warehouse_name_entity"),
        CheckConstraint(
            "warehouse_code IS NOT NULL AND warehouse_code != ''", name="ck_warehouse_code"
        ),
        CheckConstraint("name IS NOT NULL AND name != ''", name="ck_warehouse_name"),
        CheckConstraint(
            "status IN ('active', 'inactive', 'maintenance', 'closed')", name="ck_warehouse_status"
        ),
        Index("idx_warehouse_legal_entity", "legal_entity_id"),
        Index("idx_warehouse_code", "warehouse_code"),
        Index("idx_warehouse_status", "status"),
        Index("idx_warehouse_type", "warehouse_type"),
        Index("idx_warehouse_location", "location_code"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True
    )

    # Basic information
    warehouse_code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    warehouse_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="standard"
    )  # standard, cold_storage, hazardous, bonded
    location_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="ID")
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_person: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Capacity and utilization
    total_capacity: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )  # in cubic meters or pallets
    used_capacity: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    capacity_uom: Mapped[str] = mapped_column(String(10), nullable=False, default="PALLET")

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Operating hours
    operating_hours: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # {"monday": "09:00-17:00", ...}

    # Notes
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    # Extra metadata
    extra_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    # Items in this warehouse (via inventory item table)
    items: Mapped[list[InventoryItemTable]] = relationship(
        "InventoryItemTable", back_populates="warehouse", lazy="selectin"
    )

    # Stock movements from/to this warehouse
    movements_from: Mapped[list[InventoryMovementTable]] = relationship(
        "InventoryMovementTable",
        foreign_keys="InventoryMovementTable.from_warehouse_id",
        back_populates="from_warehouse",
    )
    movements_to: Mapped[list[InventoryMovementTable]] = relationship(
        "InventoryMovementTable",
        foreign_keys="InventoryMovementTable.to_warehouse_id",
        back_populates="to_warehouse",
    )

    # Stock opname records at this warehouse
    stock_opnames: Mapped[list[StockOpnameTable]] = relationship(
        "StockOpnameTable", foreign_keys="StockOpnameTable.warehouse_id"
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_operational(self) -> bool:
        return self.status == "active" and self.is_active

    @property
    def capacity_utilization_percentage(self) -> float:
        if self.total_capacity == 0:
            return 0.0
        return float(self.used_capacity / self.total_capacity * 100)

    @property
    def full_address(self) -> str:
        parts = []
        if self.address:
            parts.append(self.address)
        if self.city:
            parts.append(self.city)
        if self.province:
            parts.append(self.province)
        if self.postal_code:
            parts.append(self.postal_code)
        if self.country:
            parts.append(self.country)
        return ", ".join(parts)

    # ========================================================================
    # METHODS
    # ========================================================================

    def activate(self, user_id: uuid.UUID) -> None:
        self.status = "active"
        self.is_active = True
        self.updated_at = datetime.utcnow()
        self.increment_version()

    def deactivate(self, user_id: uuid.UUID, reason: str | None = None) -> None:
        self.status = "inactive"
        self.is_active = False
        if reason and self.extra_metadata:
            self.extra_metadata["deactivation_reason"] = reason
        self.updated_at = datetime.utcnow()
        self.increment_version()

    def set_maintenance(self, user_id: uuid.UUID, until_date: date | None = None) -> None:
        self.status = "maintenance"
        if self.extra_metadata:
            self.extra_metadata["maintenance_until"] = (
                until_date.isoformat() if until_date else None
            )
            self.extra_metadata["maintenance_by"] = str(user_id)
        self.increment_version()

    def close(self, user_id: uuid.UUID, reason: str) -> None:
        if self.used_capacity > 0:
            raise ValueError("Cannot close warehouse that still has inventory")
        self.status = "closed"
        self.is_active = False
        if self.extra_metadata:
            self.extra_metadata["closure_reason"] = reason
            self.extra_metadata["closed_by"] = str(user_id)
            self.extra_metadata["closed_at"] = datetime.utcnow().isoformat()
        self.increment_version()

    def update_capacity_utilization(self, used_capacity: Decimal) -> None:
        if used_capacity < 0:
            raise ValueError("Used capacity cannot be negative")
        if used_capacity > self.total_capacity:
            raise ValueError(
                f"Used capacity {used_capacity} exceeds total capacity {self.total_capacity}"
            )
        self.used_capacity = used_capacity
        self.increment_version()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "warehouse_code": self.warehouse_code,
            "name": self.name,
            "warehouse_type": self.warehouse_type,
            "location_code": self.location_code,
            "address": self.address,
            "city": self.city,
            "province": self.province,
            "postal_code": self.postal_code,
            "country": self.country,
            "phone": self.phone,
            "email": self.email,
            "contact_person": self.contact_person,
            "total_capacity": str(self.total_capacity),
            "used_capacity": str(self.used_capacity),
            "capacity_uom": self.capacity_uom,
            "capacity_utilization": self.capacity_utilization_percentage,
            "status": self.status,
            "is_active": self.is_active,
            "is_default": self.is_default,
            "operating_hours": self.operating_hours,
            "notes": self.notes,
            "extra_metadata": self.extra_metadata,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "version": self.version,
        }


__all__ = ["Base", "WarehouseTable"]
