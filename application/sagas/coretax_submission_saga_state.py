# coretax_submission_saga_state.py - Complete implementation

#!/usr/bin/env python3

"""
Module: coretax_submission_saga_state.py

Layer: 8 - Application / Sagas

Responsibility:
    Definisi state untuk Coretax submission saga.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(kw_only=True)
class CoretaxSubmissionSagaState:
    """State untuk Coretax submission saga."""

    saga_id: UUID
    legal_entity_id: UUID
    period_year: int
    period_month: int
    tax_type: str  # PPN, PPH21, PPH23, TAHUNAN
    user_id: UUID | None = None
    correlation_id: str | None = None
    submission_payload: dict[str, Any] = field(default_factory=dict)
    submission_id: UUID | None = None
    approval_code: str | None = None
    pdf_bukti: str | None = None
    status: str = "INITIATED"
    errors: list[str] = field(default_factory=list)
    retry_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def add_error(self, error: str) -> None:
        """Add error message."""
        self.errors.append(error)
        self.updated_at = datetime.utcnow()

    def increment_retry(self) -> None:
        """Increment retry count."""
        self.retry_count += 1
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "saga_id": str(self.saga_id),
            "legal_entity_id": str(self.legal_entity_id),
            "period_year": self.period_year,
            "period_month": self.period_month,
            "tax_type": self.tax_type,
            "user_id": str(self.user_id) if self.user_id else None,
            "correlation_id": self.correlation_id,
            "submission_payload": self.submission_payload,
            "submission_id": str(self.submission_id) if self.submission_id else None,
            "approval_code": self.approval_code,
            "pdf_bukti": self.pdf_bukti,
            "status": self.status,
            "errors": self.errors,
            "retry_count": self.retry_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoretaxSubmissionSagaState:
        """Create from dictionary."""
        return cls(
            saga_id=UUID(data["saga_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            period_year=data["period_year"],
            period_month=data["period_month"],
            tax_type=data["tax_type"],
            user_id=UUID(data["user_id"]) if data.get("user_id") else None,
            correlation_id=data.get("correlation_id"),
            submission_payload=data.get("submission_payload", {}),
            submission_id=UUID(data["submission_id"]) if data.get("submission_id") else None,
            approval_code=data.get("approval_code"),
            pdf_bukti=data.get("pdf_bukti"),
            status=data.get("status", "INITIATED"),
            errors=data.get("errors", []),
            retry_count=data.get("retry_count", 0),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


__all__ = ["CoretaxSubmissionSagaState"]
