#!/usr/bin/env python3
"""
Module: event_base.py
Layer: 6 - Domain
Responsibility: Base classes untuk domain events dan integration events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4


@dataclass
class DomainEvent:
    """
    Base class untuk semua domain events.
    Domain events digunakan untuk komunikasi internal antar aggregate
    dan untuk event sourcing.
    """

    event_id: UUID = field(default_factory=uuid4)
    event_type: str = field(init=False)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1

    def __post_init__(self):
        if not hasattr(self, "event_type") or self.event_type is None:
            object.__setattr__(self, "event_type", self.__class__.__name__)

    def to_dict(self) -> dict[str, Any]:
        """Konversi event ke dictionary untuk serialisasi."""
        result = {}
        for key, value in self.__dict__.items():
            if not key.startswith("_"):
                if isinstance(value, UUID):
                    result[key] = str(value)
                elif isinstance(value, datetime):
                    result[key] = value.isoformat()
                elif isinstance(value, Decimal):
                    result[key] = float(value)
                else:
                    result[key] = value
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainEvent:
        """Rehidrasi event dari dictionary."""
        # Implementasi sederhana, subclass harus override jika perlu
        return cls(**data)


@dataclass
class IntegrationEvent(DomainEvent):
    """
    Base class untuk integration events.
    Integration events digunakan untuk komunikasi antar bounded context
    atau ke external systems (Kafka, webhook, etc).
    """

    correlation_id: str | None = None
    causation_id: str | None = None
    user_id: UUID | None = None
    tenant_id: str | None = None
    source_system: str = "erp_accounting_engine"

    def to_dict(self) -> dict[str, Any]:
        base_dict = super().to_dict()
        base_dict.update(
            {
                "correlation_id": self.correlation_id,
                "causation_id": self.causation_id,
                "user_id": str(self.user_id) if self.user_id else None,
                "tenant_id": self.tenant_id,
                "source_system": self.source_system,
            }
        )
        return base_dict


__all__ = [
    "DomainEvent",
    "IntegrationEvent",
]
