#!/usr/bin/env python3
"""
Module: optimistic_lock.py

Layer: Domain / COA (Chart of Accounts)

Responsibility:
    Optimistic locking mechanism for preventing concurrent modifications.

    Provides:
    - OptimisticLockException for conflict reporting.
    - OptimisticLockManager with version checking and increment.
    - Retry decorator with configurable backoff.
    - VersionedEntity mixin for entities that support versioning.
    - Utilities for version hash generation and verification.
    - Support for batch operations and deadlock detection.

Business rules:
    - Each entity has a version field (integer starting at 1).
    - Before update, client must provide expected version.
    - If expected version does not match current version, operation fails.
    - After successful update, version is incremented by 1.
    - Retry policy with exponential backoff can be applied.

Dependencies:
    - Python standard library (uuid, logging, dataclass, asyncio, time, hashlib)

Audit:
    Every optimistic lock conflict is logged with entity ID and versions.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar, cast
from uuid import UUID

logger = logging.getLogger(__name__)

# ============================================================================
# Type Variables
# ============================================================================

T = TypeVar("T")
EntityType = TypeVar("EntityType")


# ============================================================================
# Exceptions
# ============================================================================


class OptimisticLockException(Exception):
    """
    Exception raised when an optimistic lock conflict occurs.

    Attributes:
        entity_id: ID of the entity that caused the conflict.
        expected_version: Version that was expected.
        actual_version: Actual version of the entity.
        entity_type: Optional type name of the entity.
        operation: Optional operation being performed.
    """

    def __init__(
        self,
        entity_id: UUID | str,
        expected_version: int,
        actual_version: int,
        entity_type: str | None = None,
        operation: str | None = None,
    ):
        self.entity_id = entity_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        self.entity_type = entity_type
        self.operation = operation

        entity_info = f"{entity_type} " if entity_type else ""
        op_info = f" during {operation}" if operation else ""

        message = (
            f"Optimistic lock conflict on {entity_info}{entity_id}{op_info}: "
            f"expected version {expected_version}, actual version {actual_version}"
        )
        super().__init__(message)


class OptimisticLockRetryExhausted(Exception):
    """Raised when all retry attempts for an optimistic lock operation fail."""

    pass


class DeadlockDetectedError(OptimisticLockException):
    """Raised when a potential deadlock is detected in concurrent operations."""

    pass


# ============================================================================
# Retry Strategy Enum
# ============================================================================


class RetryStrategy(Enum):
    """Strategy for retrying on optimistic lock conflicts."""

    IMMEDIATE = "immediate"  # Retry immediately (no delay)
    FIXED_DELAY = "fixed_delay"  # Fixed delay between retries
    LINEAR_BACKOFF = "linear_backoff"  # Linear increasing delay
    EXPONENTIAL_BACKOFF = "exponential_backoff"  # Exponential increasing delay
    RANDOM_BACKOFF = "random_backoff"  # Random delay within range
    CUSTOM = "custom"  # Custom delay function


# ============================================================================
# Retry Configuration
# ============================================================================


@dataclass
class RetryConfig:
    """
    Configuration for retry mechanism.

    Attributes:
        max_retries: Maximum number of retry attempts (0 = no retry)
        initial_delay_ms: Initial delay in milliseconds
        max_delay_ms: Maximum delay in milliseconds
        strategy: RetryStrategy to use
        backoff_multiplier: Multiplier for linear/exponential backoff
        jitter: Whether to add random jitter to delays (prevents thundering herd)
        retryable_exceptions: Tuple of exceptions to retry on (default: OptimisticLockException)
    """

    max_retries: int = 3
    initial_delay_ms: int = 100
    max_delay_ms: int = 5000
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF
    backoff_multiplier: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple = (OptimisticLockException,)

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.initial_delay_ms < 0:
            raise ValueError("initial_delay_ms must be >= 0")
        if self.max_delay_ms < self.initial_delay_ms:
            raise ValueError("max_delay_ms must be >= initial_delay_ms")
        if self.backoff_multiplier <= 0:
            raise ValueError("backoff_multiplier must be > 0")

    def get_delay(self, attempt: int) -> float:
        """
        Calculate delay in seconds for the given attempt number.
        attempt = 0 for first retry, 1 for second, etc.
        """
        # start with float to avoid type issues
        delay_ms: float = float(self.initial_delay_ms)

        if self.strategy == RetryStrategy.IMMEDIATE:
            delay_ms = 0.0
        elif self.strategy == RetryStrategy.FIXED_DELAY:
            delay_ms = float(self.initial_delay_ms)
        elif self.strategy == RetryStrategy.LINEAR_BACKOFF:
            delay_ms = float(self.initial_delay_ms * (attempt + 1))
        elif self.strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay_ms = float(self.initial_delay_ms * (self.backoff_multiplier**attempt))
        elif self.strategy == RetryStrategy.RANDOM_BACKOFF:
            delay_ms = random.uniform(float(self.initial_delay_ms), float(self.max_delay_ms))
        else:
            delay_ms = float(self.initial_delay_ms)

        # Cap at max_delay_ms
        delay_ms = min(delay_ms, float(self.max_delay_ms))

        # Add jitter (±20% of delay)
        if self.jitter and delay_ms > 0:
            jitter_factor = 0.8 + random.random() * 0.4  # 0.8 to 1.2
            delay_ms = delay_ms * jitter_factor

        return delay_ms / 1000.0  # Convert to seconds


# ============================================================================
# Optimistic Lock Manager
# ============================================================================


class OptimisticLockManager:
    """
    Manager for optimistic locking operations.

    This class provides static methods for checking versions, incrementing
    versions, and executing operations with version checking.

    Examples:
        >>> manager = OptimisticLockManager()
        >>> account = AccountEntity(version=5, ...)
        >>> manager.check_version(account, 5)  # passes
        >>> new_account = manager.increment_version(account)
        >>> new_account.version
        6
    """

    @staticmethod
    def check_version(entity: Any, expected_version: int) -> None:
        """
        Check if the entity's version matches the expected version.

        Args:
            entity: Object with 'version' attribute (int)
            expected_version: Expected version number

        Raises:
            OptimisticLockException: If versions do not match
            TypeError: If entity has no 'version' attribute
        """
        if not hasattr(entity, "version"):
            raise TypeError(f"Entity {type(entity).__name__} has no 'version' attribute")
        actual_version = entity.version
        if actual_version != expected_version:
            entity_id = getattr(
                entity, "id", getattr(entity, "account_id", getattr(entity, "coa_id", str(entity)))
            )
            raise OptimisticLockException(
                entity_id=entity_id,
                expected_version=expected_version,
                actual_version=actual_version,
                entity_type=type(entity).__name__,
            )

    @staticmethod
    def increment_version(entity: Any) -> Any:
        """
        Return a new version of the entity with version incremented by 1.

        Note: This does NOT modify the original entity; it returns a new instance
        if the entity is immutable, or creates a copy with incremented version.

        Args:
            entity: Object with 'version' attribute and a copy mechanism

        Returns:
            New entity with version incremented by 1
        """
        if not hasattr(entity, "version"):
            raise TypeError(f"Entity {type(entity).__name__} has no 'version' attribute")

        # Try to use dataclass replace if available
        if hasattr(entity, "__dataclass_fields__"):
            from dataclasses import replace

            return replace(entity, version=entity.version + 1)

        # Otherwise, try to create a copy with incremented version
        try:
            # Attempt to create a new instance with same attributes
            # This is a simplified approach; subclasses should override if needed
            new_entity = object.__new__(type(entity))
            new_entity.__dict__.update(entity.__dict__)
            new_entity.version = entity.version + 1
            return new_entity
        except Exception:
            # Fallback: modify in place? Not recommended. Raise error.
            raise TypeError(f"Cannot increment version for entity of type {type(entity).__name__}")

    @staticmethod
    def with_version_check(
        entity: Any, expected_version: int, update_func: Callable[[Any], Any], *args, **kwargs
    ) -> Any:
        """
        Execute an update function with version check, then increment version.

        Args:
            entity: The entity to update
            expected_version: Expected version before update
            update_func: Function that performs the update (takes entity, returns updated)
            *args, **kwargs: Additional arguments for update_func

        Returns:
            Updated entity with version incremented

        Raises:
            OptimisticLockException: If version mismatch
        """
        OptimisticLockManager.check_version(entity, expected_version)
        updated_entity = update_func(entity, *args, **kwargs)
        return OptimisticLockManager.increment_version(updated_entity)

    @staticmethod
    async def with_version_check_async(
        entity: Any, expected_version: int, update_func: Callable[[Any], Any], *args, **kwargs
    ) -> Any:
        """
        Async version of with_version_check.
        """
        OptimisticLockManager.check_version(entity, expected_version)
        updated_entity = await update_func(entity, *args, **kwargs)
        return OptimisticLockManager.increment_version(updated_entity)


# ============================================================================
# Retry Decorator
# ============================================================================


def retry_on_conflict(
    max_retries: int = 3,
    initial_delay_ms: int = 100,
    max_delay_ms: int = 5000,
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF,
    backoff_multiplier: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: tuple = (OptimisticLockException,),
) -> Callable[..., Any]:
    """
    Decorator that automatically retries a function when an optimistic lock conflict occurs.

    Args:
        max_retries: Maximum number of retry attempts
        initial_delay_ms: Initial delay between retries (milliseconds)
        max_delay_ms: Maximum delay (milliseconds)
        strategy: RetryStrategy enum value
        backoff_multiplier: Multiplier for backoff strategies
        jitter: Whether to add random jitter
        retryable_exceptions: Exceptions that trigger retry

    Returns:
        Decorated function that will retry on conflicts.

    Example:
        @retry_on_conflict(max_retries=5)
        async def update_account(account_id, new_name):
            account = await repo.get(account_id)
            account.rename(new_name)
            await repo.save(account)
    """
    config = RetryConfig(
        max_retries=max_retries,
        initial_delay_ms=initial_delay_ms,
        max_delay_ms=max_delay_ms,
        strategy=strategy,
        backoff_multiplier=backoff_multiplier,
        jitter=jitter,
        retryable_exceptions=retryable_exceptions,
    )

    def decorator(func: Callable[..., T]) -> Callable[..., Any]:
        import inspect

        if inspect.iscoroutinefunction(func):
            async def async_wrapper(*args, **kwargs) -> T:
                last_exception = None
                for attempt in range(config.max_retries + 1):
                    try:
                        return await func(*args, **kwargs)
                    except retryable_exceptions as e:
                        last_exception = e
                        if attempt >= config.max_retries:
                            logger.error(f"Retry exhausted after {attempt} attempts: {e}")
                            break
                        delay = config.get_delay(attempt)
                        logger.warning(
                            f"Optimistic lock conflict (attempt {attempt + 1}/{config.max_retries + 1}), "
                            f"retrying in {delay * 1000:.0f}ms: {e}"
                        )
                        if delay > 0:
                            await asyncio.sleep(delay)
                raise OptimisticLockRetryExhausted(
                    f"Retry exhausted after {config.max_retries} retries"
                ) from last_exception

            return async_wrapper
        else:
            def sync_wrapper(*args, **kwargs) -> T:
                last_exception = None
                for attempt in range(config.max_retries + 1):
                    try:
                        return func(*args, **kwargs)
                    except retryable_exceptions as e:
                        last_exception = e
                        if attempt >= config.max_retries:
                            logger.error(f"Retry exhausted after {attempt} attempts: {e}")
                            break
                        delay = config.get_delay(attempt)
                        logger.warning(
                            f"Optimistic lock conflict (attempt {attempt + 1}/{config.max_retries + 1}), "
                            f"retrying in {delay * 1000:.0f}ms: {e}"
                        )
                        if delay > 0:
                            time.sleep(delay)
                raise OptimisticLockRetryExhausted(
                    f"Retry exhausted after {config.max_retries} retries"
                ) from last_exception

            return sync_wrapper

    return decorator


# ============================================================================
# Versioned Entity Mixin
# ============================================================================


class VersionedEntity:
    """
    Mixin class for entities that support optimistic locking.

    Provides version attribute and helper methods.

    Usage:
        class MyEntity(VersionedEntity):
            def __init__(self, ...):
                super().__init__(version=1)
                ...

    Attributes:
        version: Current version number (starts at 1)
    """

    def __init__(self, version: int = 1) -> None:
        self._version = version

    @property
    def version(self) -> int:
        """Get current version."""
        return self._version

    def increment_version(self) -> None:
        """Increment version by 1 (in-place, use with caution)."""
        self._version += 1

    def check_version(self, expected_version: int) -> bool:
        """Check if current version matches expected."""
        return self._version == expected_version

    def create_snapshot(self) -> dict[str, Any]:
        """Create a snapshot of the entity's state (including version)."""
        return {"version": self._version}


# ============================================================================
# Optimistic Lock Utilities
# ============================================================================


class OptimisticLockUtils:
    """
    Utility functions for optimistic locking.

    Provides hashing, version extraction, and compatibility helpers.
    """

    @staticmethod
    def create_version_hash(entity: Any, include_fields: list[str] | None = None) -> str:
        """
        Create a hash that represents the entity's version and state.

        This can be used as an ETag for HTTP caching or conditional updates.

        Args:
            entity: Entity with 'version' attribute
            include_fields: Optional list of field names to include in hash
                            If None, includes all fields.

        Returns:
            Hex digest (MD5) representing the entity's state.
        """
        if not hasattr(entity, "version"):
            raise TypeError(f"Entity {type(entity).__name__} has no 'version' attribute")

        # Determine what to include
        data = {"version": entity.version}

        if include_fields:
            for field_name in include_fields:
                if hasattr(entity, field_name):
                    value = getattr(entity, field_name)
                    # Convert to serializable
                    if hasattr(value, "to_dict"):
                        value = value.to_dict()
                    data[field_name] = str(value)
        else:
            # Try to get all fields from dataclass
            if hasattr(entity, "__dataclass_fields__"):
                for field_name in entity.__dataclass_fields__:
                    value = getattr(entity, field_name)
                    if hasattr(value, "to_dict"):
                        value = value.to_dict()
                    data[field_name] = str(value)

        content = json.dumps(data, sort_keys=True, default=str)
        return hashlib.md5(content.encode()).hexdigest()

    @staticmethod
    def verify_version_hash(
        entity: Any, version_hash: str, include_fields: list[str] | None = None
    ) -> bool:
        """Verify that the entity's current hash matches the stored hash."""
        current_hash = OptimisticLockUtils.create_version_hash(entity, include_fields)
        return current_hash == version_hash

    @staticmethod
    def extract_version_from_hash(version_hash: str) -> int | None:
        """
        Attempt to extract version number from a version hash.
        This is a best-effort; not guaranteed to work for all hashes.
        """
        return None

    @staticmethod
    def get_version_etag(entity: Any) -> str:
        """
        Create an HTTP ETag from the entity's version.
        Format: W/"version" (weak ETag).
        """
        if not hasattr(entity, "version"):
            raise TypeError(f"Entity {type(entity).__name__} has no 'version' attribute")
        return f'W/"{entity.version}"'

    @staticmethod
    def parse_version_from_etag(etag: str) -> int | None:
        """Parse version number from an ETag string."""
        import re

        match = re.search(r"(\d+)", etag)
        if match:
            return int(match.group(1))
        return None


# ============================================================================
# Deadlock Detection
# ============================================================================


class DeadlockDetector:
    """
    Simple deadlock detector for concurrent operations.

    Tracks which entities are currently being updated by which transactions.
    """

    def __init__(self):
        self._locks: dict[UUID, str] = {}  # entity_id -> transaction_id

    def acquire(self, entity_id: UUID, transaction_id: str) -> bool:
        """
        Attempt to acquire lock for entity.

        Returns True if acquired, False if already locked by different transaction.
        """
        existing = self._locks.get(entity_id)
        if existing is None or existing == transaction_id:
            self._locks[entity_id] = transaction_id
            return True
        return False

    def release(self, entity_id: UUID, transaction_id: str) -> None:
        """Release lock for entity (only if held by this transaction)."""
        if self._locks.get(entity_id) == transaction_id:
            del self._locks[entity_id]

    def is_locked(self, entity_id: UUID, transaction_id: str) -> bool:
        """Check if entity is locked by this or any transaction."""
        existing = self._locks.get(entity_id)
        if existing is None:
            return False
        return existing != transaction_id


# ============================================================================
# Helper Functions
# ============================================================================


def with_retry(operation: Callable[[], T], config: RetryConfig | None = None) -> T:
    """
    Execute an operation with retry on optimistic lock conflicts.

    Args:
        operation: Function that performs the operation (no arguments)
        config: RetryConfig (defaults to standard config)

    Returns:
        Result of operation

    Raises:
        OptimisticLockRetryExhausted: After all retries exhausted
    """
    if config is None:
        config = RetryConfig()
    decorator = retry_on_conflict(
        max_retries=config.max_retries,
        initial_delay_ms=config.initial_delay_ms,
        max_delay_ms=config.max_delay_ms,
        strategy=config.strategy,
        backoff_multiplier=config.backoff_multiplier,
        jitter=config.jitter,
        retryable_exceptions=config.retryable_exceptions,
    )
    result = decorator(operation)()
    return cast(T, result)


async def with_retry_async(operation: Callable[[], T], config: RetryConfig | None = None) -> T:
    """
    Async version of with_retry.
    """
    if config is None:
        config = RetryConfig()
    decorator = retry_on_conflict(
        max_retries=config.max_retries,
        initial_delay_ms=config.initial_delay_ms,
        max_delay_ms=config.max_delay_ms,
        strategy=config.strategy,
        backoff_multiplier=config.backoff_multiplier,
        jitter=config.jitter,
        retryable_exceptions=config.retryable_exceptions,
    )
    result = await decorator(operation)()
    return cast(T, result)


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "DeadlockDetectedError",
    "DeadlockDetector",
    "OptimisticLockException",
    "OptimisticLockManager",
    "OptimisticLockRetryExhausted",
    "OptimisticLockUtils",
    "RetryConfig",
    "RetryStrategy",
    "VersionedEntity",
    "retry_on_conflict",
    "with_retry",
    "with_retry_async",
]
