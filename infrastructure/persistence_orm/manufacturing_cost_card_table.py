#!/usr/bin/env python3
"""
Module: manufacturing_cost_card_table.py
Layer: Infrastructure - Persistence ORM
Responsibility: ORM table untuk manufacturing cost card.

Changelog v6.5:
    - FIX: tambah kolom legal_entity_id (nullable).
    - FIX: tambah __table_args__: UniqueConstraint, Index.
    - FIX: perlebar unit_of_measure ke String(20).
    - FIX: gunakan server_default agar sinkron dengan migrasi 0054/0055.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ManufacturingCostCardTable(Base):
    __tablename__ = "manufacturing_cost_card"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    cost_card_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True,
        comment="LEGACY: menyimpan work_order_id, bukan cost_card_id",
    )
    product_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("inventory_item.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    product_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    period: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    material_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    labor_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    overhead_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    other_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    quantity_base: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("1"), server_default=text("1"),
    )
    unit_of_measure: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pcs", server_default=text("'pcs'"),
    )
    quantity_produced: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default=text("0"),
    )
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default=text("0"),
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", server_default=text("'open'"), index=True,
    )
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    legal_entity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now,
        server_default=text("now()"),
    )

    __table_args__ = (
        UniqueConstraint(
            "product_id", "period", "legal_entity_id",
            name="uq_mfg_cost_card_product_period_le",
        ),
        Index(
            "ix_mfg_cost_card_le_product_period",
            "legal_entity_id", "product_id", "period",
        ),
        Index("ix_mfg_cost_card_status_period", "status", "period"),
    )

    def __repr__(self) -> str:
        return (
            f"<ManufacturingCostCardTable(id={self.id}, "
            f"product_id={self.product_id}, period={self.period!r}, "
            f"total={self.total_cost}, qb={self.quantity_base}, "
            f"unit={self.unit_cost}, status={self.status!r})>"
        )


__all__ = ["ManufacturingCostCardTable"]
