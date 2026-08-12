#!/usr/bin/env python3
"""
Module: command_envelope.py
Layer: 4 - Kernel / Command Envelope
Responsibility: Definisi CommandEnvelope dan CommandStatus untuk menghindari
               circular import antara sealed_gate dan audit_hook_injector.

Metode yang ditambahkan:
- validate(), to_dict(), from_dict(), clone(), snapshot(), version(), audit_trail(), touch()
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any, Generic, TypeVar
from uuid import UUID, uuid4

T = TypeVar("T")


class CommandStatus(Enum):
    PENDING = auto()
    VALIDATING = auto()
    EXECUTING = auto()
    COMMITTING = auto()
    SUCCESS = auto()
    FAILED = auto()
    REJECTED = auto()
    RETRYING = auto()


@dataclass
class CommandResult(Generic[T]):
    success: bool
    data: T | None = None
    error: str | None = None

    @classmethod
    def of_success(cls, data: T | None = None) -> CommandResult[T]:
        """Create a success result."""
        return cls(success=True, data=data)

    @classmethod
    def failure(cls, error: str) -> CommandResult[Any]:
        """Create a failure result."""
        return cls(success=False, error=error)

    @property
    def is_success(self) -> bool:
        return self.success

    @property
    def is_failure(self) -> bool:
        return not self.success

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self.success and self.error is not None:
            errors.append("Success result cannot have error")
        if not self.success and self.error is None:
            errors.append("Failure result must have error message")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommandResult[Any]:
        return cls(
            success=data["success"],
            data=data.get("data"),
            error=data.get("error"),
        )

    def clone(self) -> CommandResult[T]:
        return CommandResult(
            success=self.success,
            data=self.data,
            error=self.error,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "has_data": self.data is not None,
            "has_error": self.error is not None,
        }

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return []

    def touch(self, touched_by: str) -> CommandResult[T]:
        return self.clone()


@dataclass
class CommandEnvelope:
    command_id: UUID
    command_type: str
    command_data: dict[str, Any]
    idempotency_key: str | None
    user_id: str
    legal_entity_id: UUID
    timestamp: datetime
    correlation_id: str | None
    causation_id: UUID | None
    status: CommandStatus = CommandStatus.PENDING
    result: Any | None = None
    error: str | None = None
    execution_time_ms: float = 0.0
    retry_count: int = 0
    command: Any = None

    @classmethod
    def create(
        cls,
        command_type: str,
        command_data: dict[str, Any],
        user_id: str,
        legal_entity_id: UUID,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        causation_id: UUID | None = None,
        command: Any = None,
    ) -> CommandEnvelope:
        return cls(
            command_id=uuid4(),
            command_type=command_type,
            command_data=command_data,
            idempotency_key=idempotency_key,
            user_id=user_id,
            legal_entity_id=legal_entity_id,
            timestamp=datetime.now(UTC),
            correlation_id=correlation_id or str(uuid4()),
            causation_id=causation_id,
            command=command,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": str(self.command_id),
            "command_type": self.command_type,
            "user_id": self.user_id,
            "legal_entity_id": str(self.legal_entity_id),
            "status": self.status.name,
            "execution_time_ms": self.execution_time_ms,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "causation_id": str(self.causation_id) if self.causation_id else None,
            "idempotency_key": self.idempotency_key,
            "error": self.error,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommandEnvelope:
        return cls(
            command_id=UUID(data["command_id"]),
            command_type=data["command_type"],
            command_data=data.get("command_data", {}),
            idempotency_key=data.get("idempotency_key"),
            user_id=data["user_id"],
            legal_entity_id=UUID(data["legal_entity_id"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            correlation_id=data.get("correlation_id"),
            causation_id=UUID(data["causation_id"]) if data.get("causation_id") else None,
            status=CommandStatus[data.get("status", "PENDING")],
            result=data.get("result"),
            error=data.get("error"),
            execution_time_ms=data.get("execution_time_ms", 0.0),
            retry_count=data.get("retry_count", 0),
            command=data.get("command"),
        )

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.command_type:
            errors.append("command_type is required")
        if not self.user_id:
            errors.append("user_id is required")
        if not self.legal_entity_id:
            errors.append("legal_entity_id is required")
        if self.status == CommandStatus.SUCCESS and self.error:
            errors.append("Success status cannot have error")
        if self.status == CommandStatus.FAILED and not self.error:
            errors.append("Failed status must have error")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def clone(self) -> CommandEnvelope:
        new_id = uuid4()
        return CommandEnvelope(
            command_id=new_id,
            command_type=self.command_type,
            command_data=self.command_data.copy(),
            idempotency_key=self.idempotency_key,
            user_id=self.user_id,
            legal_entity_id=self.legal_entity_id,
            timestamp=datetime.now(UTC),
            correlation_id=self.correlation_id,
            causation_id=self.command_id,
            status=CommandStatus.PENDING,
            result=None,
            error=None,
            execution_time_ms=0.0,
            retry_count=0,
            command=self.command,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "command_id": str(self.command_id),
            "command_type": self.command_type,
            "status": self.status.name,
            "execution_time_ms": self.execution_time_ms,
            "timestamp": self.timestamp.isoformat(),
        }

    def version(self) -> int:
        return 1  # CommandEnvelope is immutable after creation

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> CommandEnvelope:
        # Create a new envelope with updated timestamp (simulate touch)
        return CommandEnvelope(
            command_id=self.command_id,
            command_type=self.command_type,
            command_data=self.command_data.copy(),
            idempotency_key=self.idempotency_key,
            user_id=self.user_id,
            legal_entity_id=self.legal_entity_id,
            timestamp=datetime.now(UTC),
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
            status=self.status,
            result=self.result,
            error=self.error,
            execution_time_ms=self.execution_time_ms,
            retry_count=self.retry_count,
            command=self.command,
        )


__all__ = [
    "CommandEnvelope",
    "CommandResult",
    "CommandStatus",
]
