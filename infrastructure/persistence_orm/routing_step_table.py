#!/usr/bin/env python3
"""
Module: routing_step_table.py
Layer: Infrastructure / Persistence ORM

Responsibility:
    SQLAlchemy ORM table untuk routing step (langkah-langkah dalam routing produksi).
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, TimestampMixin, VersionMixin


class RoutingStepTable(Base, TimestampMixin, VersionMixin):
    """
    ORM table untuk routing step.
    Setiap step adalah bagian dari routing (misal: persiapan, pemotongan, perakitan, pengecekan).
    """

    __tablename__ = "routing_step"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    routing_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("routing.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_sequence: Mapped[int] = mapped_column(nullable=False, comment="Urutan langkah dalam routing")
    operation_code: Mapped[str] = mapped_column(String(30), nullable=False, comment="Kode operasi")
    operation_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="Nama operasi")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    work_center_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
        comment="Work center ID (referensi ke work_center table)"
    )
    setup_time_minutes: Mapped[int] = mapped_column(default=0, comment="Setup time in minutes")
    run_time_minutes: Mapped[int] = mapped_column(default=0, comment="Run time per unit in minutes")
    queue_time_minutes: Mapped[int] = mapped_column(default=0, comment="Queue time in minutes")
    wait_time_minutes: Mapped[int] = mapped_column(default=0, comment="Wait time in minutes")
    move_time_minutes: Mapped[int] = mapped_column(default=0, comment="Move time in minutes")
    total_time_minutes: Mapped[int] = mapped_column(default=0, comment="Total time in minutes")
    labor_cost_rate: Mapped[float | None] = mapped_column(default=0.0, comment="Labor cost rate per hour")
    machine_cost_rate: Mapped[float | None] = mapped_column(default=0.0, comment="Machine cost rate per hour")
    overhead_rate: Mapped[float | None] = mapped_column(default=0.0, comment="Overhead rate percentage")

    # Relationships
    routing: Mapped["RoutingTable"] = relationship("RoutingTable", back_populates="steps")
    # WorkCenter relationship dihapus sementara karena tabel WorkCenter belum didefinisikan

    __table_args__ = (
        UniqueConstraint("routing_id", "step_sequence", name="uq_routing_step_sequence"),
    )

    def __repr__(self) -> str:
        return f"<RoutingStepTable(id={self.id}, step_sequence={self.step_sequence}, operation_code={self.operation_code})>"