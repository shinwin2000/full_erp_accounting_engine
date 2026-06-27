#!/usr/bin/env python3
"""
Module: machine_table.py
Layer: Infrastructure / Persistence ORM

Responsibility:
    SQLAlchemy ORM table untuk machine (mesin produksi).
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, TimestampMixin, VersionMixin


class MachineTable(Base, TimestampMixin, VersionMixin):
    __tablename__ = "machine"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    hourly_rate: Mapped[float | None] = mapped_column(nullable=True)

    # Relationships
    steps: Mapped[list[RoutingStepTable]] = relationship("RoutingStepTable", back_populates="machine")

    def __repr__(self) -> str:
        return f"<MachineTable(id={self.id}, code={self.code}, name={self.name})>"
