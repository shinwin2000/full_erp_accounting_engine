#!/usr/bin/env python3
"""
Module: audit_repository_port.py
Layer: 7 - Ports / Primary
Responsibility: Port for immutable audit log repository.

Defines the contract for storing and retrieving immutable audit events,
hash chains, and forensic data. This port is implemented by adapters
(e.g., SQLAlchemy, PostgreSQL append-only, or event store).

Dependencies:
- Python standard library (abc, UUID, datetime, typing)

Audit: This is a port, no direct audit logging here.
"""

from __future__ import annotations

import abc
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


class AuditEvent:
    """Immutable audit event record."""

    def __init__(
        self,
        event_id: UUID,
        aggregate_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
        causation_id: UUID | None = None,
        version: int = 1,
        hash_chain_previous: str | None = None,
        hash_chain_current: str | None = None,
    ):
        self.event_id = event_id
        self.aggregate_id = aggregate_id
        self.event_type = event_type
        self.payload = payload
        self.occurred_at = occurred_at
        self.user_id = user_id
        self.correlation_id = correlation_id
        self.causation_id = causation_id
        self.version = version
        self.hash_chain_previous = hash_chain_previous
        self.hash_chain_current = hash_chain_current

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "aggregate_id": str(self.aggregate_id),
            "event_type": self.event_type,
            "payload": self.payload,
            "occurred_at": self.occurred_at.isoformat(),
            "user_id": str(self.user_id) if self.user_id else None,
            "correlation_id": self.correlation_id,
            "causation_id": str(self.causation_id) if self.causation_id else None,
            "version": self.version,
            "hash_chain_previous": self.hash_chain_previous,
            "hash_chain_current": self.hash_chain_current,
        }


class AuditRepositoryPort(abc.ABC):
    """
    Port (interface) for audit event repository.
    All methods must be implemented by concrete adapters.
    """

    @abc.abstractmethod
    async def append_event(self, event: AuditEvent) -> None:
        """Append an immutable audit event to the event store."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_events_by_aggregate(
        self, aggregate_id: UUID, from_version: int | None = None, limit: int = 1000
    ) -> list[AuditEvent]:
        """Retrieve all events for a given aggregate, ordered by version."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_events_by_type(
        self,
        event_type: str,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 1000,
    ) -> list[AuditEvent]:
        """Retrieve events by type with optional date range."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_events_by_correlation_id(self, correlation_id: str) -> list[AuditEvent]:
        """Retrieve events belonging to a correlation chain."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_last_event(self, aggregate_id: UUID) -> AuditEvent | None:
        """Get the latest event (highest version) for an aggregate."""
        raise NotImplementedError

    @abc.abstractmethod
    async def verify_hash_chain(self, aggregate_id: UUID) -> bool:
        """Verify the integrity of the hash chain for an aggregate."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_hash_chain_root(self, aggregate_id: UUID) -> str | None:
        """Get the current root hash of the aggregate's event chain."""
        raise NotImplementedError

    @abc.abstractmethod
    async def replay_events(
        self,
        aggregate_id: UUID,
        from_version: int | None = None,
        to_version: int | None = None,
    ) -> list[AuditEvent]:
        """Replay events for event sourcing (returns events in order)."""
        raise NotImplementedError


class AuditRepositoryPortProtocol(Protocol):
    """Protocol version for structural typing."""

    async def append_event(self, event: AuditEvent) -> None: ...
    async def get_events_by_aggregate(
        self, aggregate_id: UUID, from_version: int | None = None, limit: int = 1000
    ) -> list[AuditEvent]: ...
    async def get_events_by_type(
        self,
        event_type: str,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 1000,
    ) -> list[AuditEvent]: ...
    async def get_events_by_correlation_id(self, correlation_id: str) -> list[AuditEvent]: ...
    async def get_last_event(self, aggregate_id: UUID) -> AuditEvent | None: ...
    async def verify_hash_chain(self, aggregate_id: UUID) -> bool: ...
    async def get_hash_chain_root(self, aggregate_id: UUID) -> str | None: ...
    async def replay_events(
        self, aggregate_id: UUID, from_version: int | None = None, to_version: int | None = None
    ) -> list[AuditEvent]: ...


__all__ = [
    "AuditEvent",
    "AuditRepositoryPort",
    "AuditRepositoryPortProtocol",
]
