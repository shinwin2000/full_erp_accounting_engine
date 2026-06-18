# saga_orchestrator_base.py - Hardened version with complete implementation

#!/usr/bin/env python3

"""
Module: saga_orchestrator_base.py
Layer: 8 - Application / Sagas
Responsibility:
    Base class untuk saga orchestrator. Menyediakan fungsionalitas umum:
    - Registrasi step dan kompensasi
    - Eksekusi saga dengan urutan step
    - Kompensasi jika terjadi kegagalan
    - Persist state ke saga state store
    - Recovery dari kegagalan
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Generic, TypeVar
from uuid import UUID, uuid4

from application.sagas.saga_exceptions import (
    SagaAlreadyCompletedError,
    SagaCompensationError,
    SagaInvalidStateError,
    SagaNotFoundError,
    SagaStepExecutionError,
)
from ports.primary.saga_state_store_port import SagaStateStorePort

logger = logging.getLogger(__name__)

T = TypeVar("T")


class SagaStatus(str, Enum):
    """Status eksekusi saga."""

    INITIATED = "initiated"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    FAILED = "failed"

    def is_terminal(self) -> bool:
        """Check if status is terminal."""
        return self in (self.COMPLETED, self.COMPENSATED, self.FAILED)

    def can_resume(self) -> bool:
        """Check if saga can be resumed."""
        return self in (self.INITIATED, self.RUNNING, self.COMPENSATING)


@dataclass(kw_only=True)
class SagaContext(Generic[T]):
    """Generic context yang dibawa sepanjang eksekusi saga."""

    saga_id: UUID = field(default_factory=uuid4)
    saga_type: str
    current_step_index: int = -1
    data: T
    status: SagaStatus = SagaStatus.INITIATED
    errors: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def add_error(self, error: str) -> None:
        """Add error message."""
        self.errors.append(error)
        self.updated_at = datetime.now(UTC)

    def set_status(self, status: SagaStatus) -> None:
        """Set status and update timestamp."""
        self.status = status
        self.updated_at = datetime.now(UTC)

    def set_step(self, step_index: int) -> None:
        """Set current step index."""
        self.current_step_index = step_index
        self.updated_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "saga_id": str(self.saga_id),
            "saga_type": self.saga_type,
            "status": self.status.value,
            "current_step_index": self.current_step_index,
            "errors": self.errors,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], deserialize_func: Callable[[dict], T]
    ) -> SagaContext[T]:
        """Create from dictionary with custom deserializer."""
        return cls(
            saga_id=UUID(data["saga_id"]),
            saga_type=data["saga_type"],
            status=SagaStatus(data["status"]),
            current_step_index=data["current_step_index"],
            data=deserialize_func(data.get("data", {})),
            errors=data.get("errors", []),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


class SagaOrchestratorBase(ABC, Generic[T]):
    """
    Base class utama untuk manajemen orchestrator Saga Pattern.
    """

    def __init__(self, state_store: SagaStateStorePort, saga_type: str):
        if state_store is None:
            raise ValueError("state_store is required")
        self._state_store = state_store
        self._saga_type = saga_type
        self._steps: list[Callable[[T], Awaitable[T]]] = []
        self._compensations: list[Callable[[T], Awaitable[T]]] = []
        self._step_names: list[str] = []
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}
        logger.info(f"SagaOrchestratorBase initialized for type: {saga_type}")

    def add_step(
        self,
        step_func: Callable[[T], Awaitable[T]],
        compensation_func: Callable[[T], Awaitable[T]],
        step_name: str | None = None,
    ) -> None:
        """Mendaftarkan pasangan forward step dan compensation logic."""
        self._steps.append(step_func)
        self._compensations.append(compensation_func)
        self._step_names.append(step_name or f"step_{len(self._steps)}")
        logger.debug(f"Registered step {len(self._steps)}: {self._step_names[-1]}")

    async def start(self, initial_data: T) -> SagaContext[T]:
        """Inisialisasi unit transaksi Saga baru ke dalam state store."""
        context = SagaContext[T](
            saga_type=self._saga_type,
            current_step_index=-1,
            data=initial_data,
            status=SagaStatus.INITIATED,
        )
        await self._save(context)
        logger.info(f"Saga {context.saga_id} started with type {self._saga_type}")
        self._stats["executed"] += 1
        return context

    async def run(self, context: SagaContext[T]) -> SagaContext[T]:
        """Menjalankan seluruh rangkaian urutan step bisnis secara sekuensial."""
        if context.status == SagaStatus.COMPLETED:
            raise SagaAlreadyCompletedError(f"Saga {context.saga_id} already completed")

        if not context.status.can_resume():
            raise SagaInvalidStateError(
                f"Saga {context.saga_id} cannot be run from status {context.status.value}"
            )

        context.set_status(SagaStatus.RUNNING)
        await self._save(context)

        start_idx = context.current_step_index + 1 if context.current_step_index >= 0 else 0

        for idx in range(start_idx, len(self._steps)):
            context.set_step(idx)
            await self._save(context)

            try:
                logger.debug(f"Executing step {idx}: {self._step_names[idx]}")
                context.data = await self._steps[idx](context.data)
                logger.debug(f"Saga {context.saga_id} step {idx} completed successfully")
            except Exception as e:
                error_msg = f"Error at step {idx} ({self._step_names[idx]}): {e!s}"
                context.add_error(error_msg)
                await self._save(context)
                logger.error(f"Saga {context.saga_id} step {idx} failed: {e!s}", exc_info=True)

                # Execute compensation in reverse order
                await self._compensate(context, idx)
                context.set_status(SagaStatus.FAILED)
                await self._save(context)
                self._stats["failed"] += 1
                raise SagaStepExecutionError(error_msg) from e

        context.set_status(SagaStatus.COMPLETED)
        await self._save(context)
        self._stats["succeeded"] += 1
        logger.info(f"Saga {context.saga_id} completed successfully")
        return context

    async def _compensate(self, context: SagaContext[T], failed_step_index: int) -> None:
        """Melakukan kompensasi dari checkpoint kegagalan mundur hingga step awal."""
        context.set_status(SagaStatus.COMPENSATING)
        await self._save(context)

        # Compensate steps in reverse order (from failed_step_index - 1 down to 0)
        for idx in range(failed_step_index - 1, -1, -1):
            comp_func = self._compensations[idx]
            try:
                logger.debug(f"Compensating step {idx}: {self._step_names[idx]}")
                context.data = await comp_func(context.data)
                logger.info(f"Saga {context.saga_id} compensated step {idx} successfully")
            except Exception as e:
                error_msg = (
                    f"Compensation critical failure at step {idx} ({self._step_names[idx]}): {e!s}"
                )
                context.add_error(error_msg)
                await self._save(context)
                logger.critical(error_msg, exc_info=True)
                raise SagaCompensationError(error_msg) from e

        context.set_status(SagaStatus.COMPENSATED)
        await self._save(context)

    async def compensate(self, context: SagaContext[T]) -> SagaContext[T]:
        """Trigger kompensasi penuh secara manual/eksternal."""
        if context.status == SagaStatus.COMPENSATED:
            return context

        await self._compensate(context, len(self._steps))
        return context

    async def recover(self, saga_id: UUID) -> SagaContext[T]:
        """Memuat ulang data transaksi terputus dari DB dan melanjutkan koordinasi."""
        data = await self._state_store.load(self._saga_type, saga_id)
        if not data:
            raise SagaNotFoundError(f"Saga {saga_id} with type {self._saga_type} not found")

        context = SagaContext.from_dict(data, self._deserialize_data)

        if context.status == SagaStatus.RUNNING:
            logger.info(f"Recovering running saga {saga_id} from step {context.current_step_index}")
            return await self.run(context)
        elif context.status == SagaStatus.COMPENSATING:
            logger.info(f"Recovering compensating saga {saga_id}")
            return await self.compensate(context)
        else:
            return context

    async def get_status(self, saga_id: UUID) -> SagaStatus | None:
        """Get current status of a saga."""
        data = await self._state_store.load(self._saga_type, saga_id)
        if not data:
            return None
        return SagaStatus(data.get("status", "initiated"))

    async def _save(self, context: SagaContext[T]) -> None:
        """Simpan state saga ke store."""
        dict_payload = context.to_dict()
        dict_payload["data"] = await self._serialize_data(context.data)
        await self._state_store.save(self._saga_type, context.saga_id, dict_payload)

    @abstractmethod
    async def _serialize_data(self, data: T) -> dict[str, Any]:
        """Serialisasi data generic object menuju dict."""
        pass

    @abstractmethod
    async def _deserialize_data(self, data_dict: dict[str, Any]) -> T:
        """Deserialisasi data dari dict kembali ke generic object T."""
        pass

    def get_stats(self) -> dict[str, int]:
        """Get orchestrator statistics."""
        return self._stats.copy()


__all__ = ["SagaContext", "SagaOrchestratorBase", "SagaStatus"]
