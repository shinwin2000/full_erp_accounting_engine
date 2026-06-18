#!/usr/bin/env python3
"""
Module: saga_state_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel saga_state.
               Tabel ini menyimpan state dari saga (distributed transaction)
               untuk memungkinkan recovery dan kompensasi jika terjadi kegagalan.
               Setiap saga memiliki state yang disimpan secara persisten.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base, SoftDeleteMixin, TimestampMixin


class SagaStateTable(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "saga_state"
    __table_args__ = (
        UniqueConstraint("saga_id", name="uq_saga_state_saga_id"),
        UniqueConstraint("saga_type", "correlation_id", name="uq_saga_type_correlation"),
        CheckConstraint("saga_id IS NOT NULL", name="ck_saga_state_saga_id"),
        CheckConstraint("saga_type IS NOT NULL AND saga_type != ''", name="ck_saga_state_type"),
        CheckConstraint(
            "status IN ('initiated', 'running', 'completed', 'compensating', 'compensated', 'failed')",
            name="ck_saga_state_status",
        ),
        Index("idx_saga_state_type", "saga_type"),
        Index("idx_saga_state_status", "status"),
        Index("idx_saga_state_correlation", "correlation_id"),
        Index("idx_saga_state_created_at", "created_at")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    saga_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )  # unique identifier for this saga instance
    saga_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # e.g., "procurement", "payroll", "coretax_submission"
    correlation_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # business correlation ID

    # Saga state as JSON
    state_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Current step
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    step_history: Mapped[list | None] = mapped_column(
        JSONB, nullable=True
    )  # [{step, status, timestamp, error}]

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="initiated")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Retry
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timeouts
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3600
    )  # 1 hour default

    # Legal entity
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_completed(self) -> bool:
        return self.status == "completed"

    @property
    def is_failed(self) -> bool:
        return self.status == "failed"

    @property
    def is_compensating(self) -> bool:
        return self.status == "compensating"

    @property
    def is_compensated(self) -> bool:
        return self.status == "compensated"

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    @property
    def is_initiated(self) -> bool:
        return self.status == "initiated"

    @property
    def is_timeout(self) -> bool:
        from datetime import timedelta

        if self.status in ("completed", "compensated", "failed"):
            return False
        timeout_time = self.started_at + timedelta(seconds=self.timeout_seconds)
        return datetime.utcnow() > timeout_time

    @property
    def progress_percent(self) -> float:
        if self.total_steps == 0:
            return 0.0
        return (self.current_step / self.total_steps) * 100

    # ========================================================================
    # METHODS
    # ========================================================================

    def start(self) -> None:
        if self.status != "initiated":
            raise ValueError(f"Cannot start saga with status {self.status}")
        self.status = "running"
        self.started_at = datetime.utcnow()

    def complete_step(self, step: int, result: dict | None = None) -> None:
        if self.status != "running":
            raise ValueError(f"Cannot complete step with status {self.status}")
        if step != self.current_step + 1:
            raise ValueError(f"Expected step {self.current_step + 1}, got {step}")
        self.current_step = step
        if self.step_history is None:
            self.step_history = []
        self.step_history.append(
            {
                "step": step,
                "status": "completed",
                "timestamp": datetime.utcnow().isoformat(),
                "result": result,
            }
        )
        if self.current_step >= self.total_steps:
            self.complete()

    def fail_step(self, step: int, error: str, should_compensate: bool = True) -> None:
        if self.status not in ("running", "compensating"):
            raise ValueError(f"Cannot fail step with status {self.status}")
        if self.step_history is None:
            self.step_history = []
        self.step_history.append(
            {
                "step": step,
                "status": "failed",
                "timestamp": datetime.utcnow().isoformat(),
                "error": error,
            }
        )
        self.error_message = error
        if should_compensate and not self.is_compensating:
            self.status = "compensating"
        else:
            self.status = "failed"

    def complete(self) -> None:
        self.status = "completed"
        self.completed_at = datetime.utcnow()

    def compensate(self) -> None:
        if self.status not in ("failed", "compensating"):
            raise ValueError(f"Cannot compensate saga with status {self.status}")
        self.status = "compensating"

    def compensated(self) -> None:
        self.status = "compensated"
        self.completed_at = datetime.utcnow()

    def schedule_retry(self) -> None:
        if self.retry_count >= self.max_retries:
            self.status = "failed"
            return
        self.retry_count += 1
        from datetime import timedelta

        delay = min(2**self.retry_count, 300)  # exponential backoff up to 5 minutes
        self.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
        self.status = "initiated"
        self.current_step = 0

    def reset(self) -> None:
        self.status = "initiated"
        self.current_step = 0
        self.retry_count = 0
        self.error_message = None
        self.next_retry_at = None
        self.step_history = []
        self.started_at = datetime.utcnow()


__all__ = ["SagaStateTable"]
