#!/usr/bin/env python3
"""
Module: optimistic_lock.py
Layer: 6 - Domain / Journal
Responsibility: Penguncian optimistik untuk perubahan jurnal.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import UUID

from domain.journal.journal_entity import JournalStatus

logger = logging.getLogger(__name__)

T = TypeVar("T")


class OptimisticLockException(Exception):
    def __init__(
        self, entity_id: UUID, entity_type: str, expected_version: int, actual_version: int
    ):
        self.entity_id = entity_id
        self.entity_type = entity_type
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            f"Optimistic lock conflict on {entity_type} {entity_id}: "
            f"expected version {expected_version}, but actual version is {actual_version}"
        )


class OptimisticLockManager:
    @staticmethod
    def check_version(entity: Any, expected_version: int) -> None:
        actual_version = getattr(entity, "version", getattr(entity, "_version", 1))
        if actual_version != expected_version:
            raise OptimisticLockException(
                getattr(entity, "id", getattr(entity, "journal_id", UUID(int=0))),
                type(entity).__name__,
                expected_version,
                actual_version,
            )

    @staticmethod
    def check_posted_immutability(entity: Any, operation: str) -> None:
        status = getattr(entity, "status", None)
        if status == JournalStatus.POSTED:
            allowed_operations = ["reverse", "archive", "read", "view"]
            if operation not in allowed_operations:
                raise ValueError(
                    f"Cannot perform '{operation}' on posted journal. "
                    f"Allowed operations: {allowed_operations}"
                )

    @staticmethod
    def with_version_check(
        entity: Any,
        expected_version: int,
        update_func: Callable[[Any], Any],
    ) -> Any:
        OptimisticLockManager.check_version(entity, expected_version)
        updated = update_func(entity)
        return OptimisticLockManager.increment_version(updated)

    @staticmethod
    def increment_version(entity: Any) -> Any:
        if hasattr(entity, "_version"):
            entity._version += 1
        elif hasattr(entity, "version"):
            entity.version += 1
        return entity

    @staticmethod
    def retry_on_conflict(
        max_retries: int = 3,
        retry_delay_ms: int = 100,
        backoff_multiplier: float = 2.0,
    ):
        def decorator(func):
            async def wrapper(*args, **kwargs):
                last_exception = None
                current_delay = retry_delay_ms / 1000

                for attempt in range(max_retries):
                    try:
                        return await func(*args, **kwargs)
                    except OptimisticLockException as e:
                        last_exception = e
                        logger.warning(
                            f"Optimistic lock conflict (attempt {attempt + 1}/{max_retries}): {e}"
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(current_delay)
                            current_delay *= backoff_multiplier

                raise last_exception

            return wrapper

        return decorator

    @staticmethod
    def retry_on_conflict_sync(
        max_retries: int = 3,
        retry_delay_ms: int = 100,
        backoff_multiplier: float = 2.0,
    ):
        import time

        def decorator(func):
            def wrapper(*args, **kwargs):
                last_exception = None
                current_delay = retry_delay_ms / 1000

                for attempt in range(max_retries):
                    try:
                        return func(*args, **kwargs)
                    except OptimisticLockException as e:
                        last_exception = e
                        logger.warning(
                            f"Optimistic lock conflict (attempt {attempt + 1}/{max_retries}): {e}"
                        )
                        if attempt < max_retries - 1:
                            time.sleep(current_delay)
                            current_delay *= backoff_multiplier

                raise last_exception

            return wrapper

        return decorator


class VersionedJournalMixin:
    def __init__(self, version: int = 1):
        self._version = version
        self._version_history: list[dict] = []

    @property
    def version(self) -> int:
        return self._version

    def increment_version(self) -> None:
        self._version_history.append(
            {
                "old_version": self._version,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        self._version += 1

    def check_version(self, expected_version: int) -> bool:
        return self._version == expected_version

    def get_version_history(self) -> list[dict]:
        return self._version_history.copy()

    def create_version_hash(self, journal_id: UUID, updated_at: datetime) -> str:
        content = f"{journal_id}:{self._version}:{updated_at.isoformat()}"
        return hashlib.sha256(content.encode()).hexdigest()

    def to_version_dict(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "version_history": self._version_history,
        }


__all__ = [
    "OptimisticLockException",
    "OptimisticLockManager",
    "VersionedJournalMixin",
]
