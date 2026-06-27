# command_result_envelope.py - Hardened version with complete implementation
# Fixed: Added CommandResultEnvelope alias for backward compatibility

#!/usr/bin/env python3

"""
Module: command_result_envelope.py

Layer: 8 - Application / Commands CQRS

Responsibility:
    Envelope untuk hasil eksekusi command. Membungkus hasil sukses (data) atau error.
    Mendukung serialisasi/deserialisasi JSON untuk idempotency cache, serta
    agregasi hasil batch.

Fitur:
    - Status SUCCESS, FAILURE, DUPLICATE, PENDING, PARTIAL
    - Data payload dengan tipe apapun (dict, list, primitives)
    - Error code dan message untuk failure
    - Metadata tambahan (duration, warnings, etc.)
    - Serialisasi ke JSON dan deserialisasi
    - Helper methods untuk success/failure/duplicate creation
    - CommandResultBatch untuk bulk operations
    - Result chaining and composition
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Generic, TypeVar
from uuid import UUID, uuid4

T = TypeVar("T")


# === 1. ENUMS ===


class CommandStatus(Enum):
    """Status hasil eksekusi command."""

    SUCCESS = "success"
    FAILURE = "failure"
    DUPLICATE = "duplicate"
    PENDING = "pending"
    PARTIAL = "partial"

    @classmethod
    def from_string(cls, value: str) -> CommandStatus:
        """Create CommandStatus from string."""
        for status in cls:
            if status.value == value:
                return status
        raise ValueError(f"Unknown status: {value}")

    def is_success_status(self) -> bool:
        """Check if status indicates success."""
        return self in (CommandStatus.SUCCESS, CommandStatus.DUPLICATE, CommandStatus.PARTIAL)


# === 2. COMMAND RESULT ENVELOPE ===


@dataclass(kw_only=True)
class CommandResult(Generic[T]):
    """
    Envelope untuk hasil command.
    Immutable setelah dibuat.
    """

    command_id: UUID
    status: CommandStatus
    data: T | None = None
    error: str | None = None
    error_code: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.UTC))
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.status == CommandStatus.FAILURE and not self.error:
            raise ValueError("Failure status requires error message")
        if self.status == CommandStatus.SUCCESS and self.error:
            raise ValueError("Success status cannot have error")
        if self.status == CommandStatus.PARTIAL and not self.metadata.get("partial_results"):
            self.metadata["partial_results"] = []

    def is_success(self) -> bool:
        """Check if result is successful."""
        return self.status == CommandStatus.SUCCESS

    def is_failure(self) -> bool:
        """Check if result is failure."""
        return self.status == CommandStatus.FAILURE

    def is_duplicate(self) -> bool:
        """Check if result is duplicate."""
        return self.status == CommandStatus.DUPLICATE

    def is_pending(self) -> bool:
        """Check if result is pending."""
        return self.status == CommandStatus.PENDING

    def is_partial(self) -> bool:
        """Check if result is partial success."""
        return self.status == CommandStatus.PARTIAL

    def get_data(self, default: Any = None) -> Any:
        """Ambil data payload, return default jika tidak ada."""
        return self.data if self.data is not None else default

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get metadata value by key."""
        return self.metadata.get(key, default)

    def get_warnings(self) -> list[str]:
        """Get warnings list."""
        return self.warnings.copy()

    def with_metadata(self, key: str, value: Any) -> CommandResult[T]:
        """Return new CommandResult with additional metadata."""
        new_metadata = dict(self.metadata)
        new_metadata[key] = value
        return CommandResult(
            command_id=self.command_id,
            status=self.status,
            data=self.data,
            error=self.error,
            error_code=self.error_code,
            occurred_at=self.occurred_at,
            metadata=new_metadata,
            warnings=self.warnings,
        )

    def with_warning(self, warning: str) -> CommandResult[T]:
        """Return new CommandResult with additional warning."""
        return CommandResult(
            command_id=self.command_id,
            status=self.status,
            data=self.data,
            error=self.error,
            error_code=self.error_code,
            occurred_at=self.occurred_at,
            metadata=self.metadata,
            warnings=self.warnings + [warning],
        )

    def with_data(self, data: T) -> CommandResult[T]:
        """Return new CommandResult with different data."""
        return CommandResult(
            command_id=self.command_id,
            status=self.status,
            data=data,
            error=self.error,
            error_code=self.error_code,
            occurred_at=self.occurred_at,
            metadata=self.metadata,
            warnings=self.warnings,
        )

    @classmethod
    def success(
        cls,
        command_id: UUID,
        data: Any = None,
        occurred_at: datetime | None = None,
        **metadata,
    ) -> CommandResult:
        """Factory method untuk success result."""
        return cls(
            command_id=command_id,
            status=CommandStatus.SUCCESS,
            data=data,
            occurred_at=occurred_at or datetime.now(timezone.UTC),
            metadata=metadata,
        )

    @classmethod
    def failure(
        cls,
        command_id: UUID,
        error: str,
        error_code: str | None = None,
        occurred_at: datetime | None = None,
        **metadata,
    ) -> CommandResult:
        """Factory method untuk failure result."""
        return cls(
            command_id=command_id,
            status=CommandStatus.FAILURE,
            error=error,
            error_code=error_code,
            occurred_at=occurred_at or datetime.now(timezone.UTC),
            metadata=metadata,
        )

    @classmethod
    def duplicate(
        cls,
        command_id: UUID,
        message: str = "Duplicate command (idempotency)",
        error_code: str = "DUPLICATE_COMMAND",
        occurred_at: datetime | None = None,
        **metadata,
    ) -> CommandResult:
        """Factory method untuk duplicate result."""
        return cls(
            command_id=command_id,
            status=CommandStatus.DUPLICATE,
            error=message,
            error_code=error_code,
            occurred_at=occurred_at or datetime.now(timezone.UTC),
            metadata=metadata,
        )

    @classmethod
    def pending(
        cls,
        command_id: UUID,
        message: str = "Command is pending execution",
        occurred_at: datetime | None = None,
        **metadata,
    ) -> CommandResult:
        """Factory method untuk pending result."""
        return cls(
            command_id=command_id,
            status=CommandStatus.PENDING,
            error=message,
            error_code="PENDING",
            occurred_at=occurred_at or datetime.now(timezone.UTC),
            metadata=metadata,
        )

    @classmethod
    def partial(
        cls,
        command_id: UUID,
        partial_results: list[CommandResult],
        message: str = "Partial success",
        occurred_at: datetime | None = None,
        **metadata,
    ) -> CommandResult:
        """Factory method untuk partial success result."""
        return cls(
            command_id=command_id,
            status=CommandStatus.PARTIAL,
            error=message,
            error_code="PARTIAL_SUCCESS",
            occurred_at=occurred_at or datetime.now(timezone.UTC),
            metadata={"partial_results": [r.to_dict() for r in partial_results], **metadata},
        )

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary untuk serialisasi."""
        return {
            "command_id": str(self.command_id),
            "status": self.status.value,
            "data": self._serialize_data(self.data),
            "error": self.error,
            "error_code": self.error_code,
            "occurred_at": self.occurred_at.isoformat(),
            "metadata": self._serialize_data(self.metadata),
            "warnings": self.warnings,
        }

    def to_json(self) -> str:
        """Serialisasi ke JSON string."""
        return json.dumps(self.to_dict(), default=self._json_default)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommandResult:
        """Deserialisasi dari dictionary."""
        return cls(
            command_id=UUID(data["command_id"]),
            status=CommandStatus.from_string(data["status"]),
            data=data.get("data"),
            error=data.get("error"),
            error_code=data.get("error_code"),
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            metadata=data.get("metadata", {}),
            warnings=data.get("warnings", []),
        )

    @classmethod
    def from_json(cls, json_str: str) -> CommandResult:
        """Deserialisasi dari JSON string."""
        return cls.from_dict(json.loads(json_str))

    @staticmethod
    def _serialize_data(data: Any) -> Any:
        """Helper untuk serialisasi data yang mungkin mengandung UUID, datetime, Decimal."""
        if data is None:
            return None
        if isinstance(data, dict):
            return {k: CommandResult._serialize_data(v) for k, v in data.items()}
        if isinstance(data, (list, tuple)):
            return [CommandResult._serialize_data(item) for item in data]
        if isinstance(data, UUID):
            return str(data)
        if isinstance(data, datetime):
            return data.isoformat()
        if isinstance(data, Decimal):
            return float(data)
        if hasattr(data, "to_dict"):
            return data.to_dict()
        if hasattr(data, "__dict__"):
            return {
                k: CommandResult._serialize_data(v)
                for k, v in data.__dict__.items()
                if not k.startswith("_")
            }
        return data

    @staticmethod
    def _json_default(obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    def __repr__(self) -> str:
        return (
            f"CommandResult(command_id={self.command_id}, "
            f"status={self.status.value}, "
            f"error={self.error})"
        )


# === 3. COMMAND RESULT BATCH ===


@dataclass(kw_only=True)
class CommandResultBatch:
    """Kumpulan hasil untuk multiple commands yang dieksekusi dalam batch."""

    results: list[CommandResult] = field(default_factory=list)
    partial_failure_allowed: bool = False
    batch_id: UUID = field(default_factory=uuid4)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.UTC))
    completed_at: datetime | None = None

    def add(self, result: CommandResult) -> None:
        """Add a result to the batch."""
        self.results.append(result)

    def add_all(self, results: list[CommandResult]) -> None:
        """Add multiple results to the batch."""
        self.results.extend(results)

    def complete(self) -> None:
        """Mark batch as completed."""
        self.completed_at = datetime.now(timezone.UTC)

    def all_successful(self) -> bool:
        """Check if all results are successful."""
        return all(r.is_success() for r in self.results)

    def any_failure(self) -> bool:
        """Check if any result is failure."""
        return any(r.is_failure() for r in self.results)

    def any_duplicate(self) -> bool:
        """Check if any result is duplicate."""
        return any(r.is_duplicate() for r in self.results)

    def get_successful(self) -> list[CommandResult]:
        """Get all successful results."""
        return [r for r in self.results if r.is_success()]

    def get_failures(self) -> list[CommandResult]:
        """Get all failure results."""
        return [r for r in self.results if r.is_failure()]

    def get_duplicates(self) -> list[CommandResult]:
        """Get all duplicate results."""
        return [r for r in self.results if r.is_duplicate()]

    def get_partial(self) -> list[CommandResult]:
        """Get all partial results."""
        return [r for r in self.results if r.is_partial()]

    def summary(self) -> dict[str, int]:
        """Get summary statistics."""
        return {
            "total": len(self.results),
            "success": len(self.get_successful()),
            "failure": len(self.get_failures()),
            "duplicate": len(self.get_duplicates()),
            "partial": len(self.get_partial()),
        }

    def is_successful_batch(self) -> bool:
        """Check if batch is successful overall."""
        if self.partial_failure_allowed:
            return not all(r.is_failure() for r in self.results)
        return self.all_successful()

    def get_errors(self) -> list[str]:
        """Get all error messages from failures."""
        errors = []
        for r in self.get_failures():
            if r.error:
                errors.append(f"[{r.command_id}] {r.error}")
        return errors

    def to_dict(self) -> dict[str, Any]:
        """Convert batch to dictionary."""
        return {
            "batch_id": str(self.batch_id),
            "results": [r.to_dict() for r in self.results],
            "partial_failure_allowed": self.partial_failure_allowed,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "summary": self.summary(),
        }

    def to_json(self) -> str:
        """Convert batch to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommandResultBatch:
        """Create batch from dictionary."""
        batch = cls(
            partial_failure_allowed=data.get("partial_failure_allowed", False),
            batch_id=UUID(data["batch_id"]),
            started_at=datetime.fromisoformat(data["started_at"]),
        )
        if data.get("completed_at"):
            batch.completed_at = datetime.fromisoformat(data["completed_at"])
        for r_data in data.get("results", []):
            batch.add(CommandResult.from_dict(r_data))
        return batch

    @classmethod
    def from_json(cls, json_str: str) -> CommandResultBatch:
        """Create batch from JSON string."""
        return cls.from_dict(json.loads(json_str))

    def __repr__(self) -> str:
        return f"CommandResultBatch(batch_id={self.batch_id}, summary={self.summary()})"


# === 4. RESULT HELPER FUNCTIONS ===


def combine_results(results: list[CommandResult], allow_partial: bool = False) -> CommandResult:
    """
    Combine multiple command results into a single result.

    Args:
        results: List of command results to combine
        allow_partial: If True, return PARTIAL status when some succeed

    Returns:
        Combined CommandResult
    """
    if not results:
        return CommandResult.success(
            command_id=uuid4(),
            data={"results": []},
            message="No results to combine",
        )

    command_id = results[0].command_id
    successes = [r for r in results if r.is_success()]
    failures = [r for r in results if r.is_failure()]

    if not failures:
        return CommandResult.success(
            command_id=command_id,
            data={"results": [r.data for r in successes]},
            combined_count=len(successes),
        )

    if not successes and not allow_partial:
        return CommandResult.failure(
            command_id=command_id,
            error=f"All {len(failures)} commands failed",
            error_code="ALL_FAILED",
            failures=[r.to_dict() for r in failures],
        )

    if successes and failures and allow_partial:
        return CommandResult.partial(
            command_id=command_id,
            partial_results=successes,
            message=f"{len(successes)} succeeded, {len(failures)} failed",
            failures=[r.to_dict() for r in failures],
        )

    return CommandResult.failure(
        command_id=command_id,
        error="Unknown combination state",
        error_code="UNKNOWN",
    )


def result_from_exception(
    command_id: UUID,
    exception: Exception,
    error_code: str | None = None,
) -> CommandResult:
    """Create a failure result from an exception."""
    return CommandResult.failure(
        command_id=command_id,
        error=str(exception),
        error_code=error_code or type(exception).__name__,
        exception_type=type(exception).__name__,
    )


# === 5. BACKWARD COMPATIBILITY ALIASES ===

# Alias for routers expecting CommandResultEnvelope
CommandResultEnvelope = CommandResult


# === 6. EXPORTS ===

__all__ = [
    "CommandResult",
    "CommandResultBatch",
    "CommandResultEnvelope",
    "CommandStatus",
    "combine_results",
    "result_from_exception",
]
