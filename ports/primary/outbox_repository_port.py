#!/usr/bin/env python3
"""
Module: outbox_repository_port.py
Layer: Ports / Primary
Responsibility: Port untuk transactional outbox pattern.
"""

from __future__ import annotations

import abc
from datetime import datetime
from typing import Any
from uuid import UUID


class OutboxMessage:
    def __init__(
        self,
        message_id: UUID,
        aggregate_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
        status: str = "PENDING",
    ):
        self.message_id = message_id
        self.aggregate_id = aggregate_id
        self.event_type = event_type
        self.payload = payload
        self.occurred_at = occurred_at
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": str(self.message_id),
            "aggregate_id": str(self.aggregate_id),
            "event_type": self.event_type,
            "payload": self.payload,
            "occurred_at": self.occurred_at.isoformat(),
            "status": self.status,
        }


class OutboxRepositoryPort(abc.ABC):
    @abc.abstractmethod
    async def save(self, message: OutboxMessage) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_pending_messages(self, limit: int = 100) -> list[OutboxMessage]:
        raise NotImplementedError

    @abc.abstractmethod
    async def mark_as_sent(self, message_id: UUID) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def mark_as_failed(self, message_id: UUID, error: str) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def delete_sent_messages_older_than(self, cutoff_date: datetime) -> int:
        raise NotImplementedError


__all__ = ["OutboxMessage", "OutboxRepositoryPort"]
