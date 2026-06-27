# infrastructure/persistence_orm/manufacturing_routing_table.py
"""
Module: manufacturing_routing_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: ORM model untuk Manufacturing Routing (RoutingTable).
Routing adalah urutan langkah produksi untuk membuat suatu produk.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, TimestampMixin, VersionMixin


class RoutingTable(Base, TimestampMixin, VersionMixin):
    """
    ORM table untuk manufacturing routing.
    """

    __tablename__ = "routing"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    routing_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    routing_name: Mapped[str] = mapped_column(String(200), nullable=False)
    product_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    is_default: Mapped[bool] = mapped_column(default=False)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    # Relationships
    steps: Mapped[list[RoutingStepTable]] = relationship(
        "RoutingStepTable",
        back_populates="routing",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RoutingStepTable.step_sequence",
    )

    def __repr__(self) -> str:
        return f"<RoutingTable(id={self.id}, routing_code={self.routing_code})>"
