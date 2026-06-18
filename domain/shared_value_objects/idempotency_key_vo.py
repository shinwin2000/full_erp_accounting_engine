#!/usr/bin/env python3
"""
Module: idempotency_key_vo.py

Layer: Domain / Shared Value Objects

Responsibility:
    Value object for idempotency keys. Immutable.
    Ensures that operations can be safely retried without duplicate side effects.
    Used in command buses, API endpoints, and message processing.

Business rules:
    - Key must be unique across the system for a given operation type/scope.
    - Minimum length: 8 characters (after normalization).
    - Keys are case-sensitive and typically UUID-based or derived from request metadata.
    - TTL (time-to-live) can be associated but is not part of the value object.
    - Provides methods for generating deterministic keys from request context.
    - Immutable: once created, cannot be changed.

Dependencies:
    - Python standard library (uuid, hashlib, datetime, dataclass, typing)

Audit:
    Pure value object; no I/O. Caller should log key usage.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

# ============================================================================
# Custom Exceptions
# ============================================================================


class IdempotencyKeyError(ValueError):
    """Base exception for idempotency key validation errors."""

    pass


class InvalidIdempotencyKeyError(IdempotencyKeyError):
    """Raised when key format is invalid."""

    pass


# ============================================================================
# Value Object: IdempotencyKeyVO
# ============================================================================


@dataclass(frozen=True)
class IdempotencyKeyVO:
    """
    Immutable value object for idempotency key.

    Attributes:
        value: The raw key string (normalized, trimmed)
        prefix: Optional namespace prefix (e.g., 'payment', 'journal')
        created_at: Optional timestamp when key was generated
        source: Optional source identifier ('system', 'client', 'internal')

    Examples:
        >>> key1 = IdempotencyKeyVO.generate()
        >>> len(key1.value) >= 32
        True
        >>> key2 = IdempotencyKeyVO.from_request("req-123", "user-456", "post_journal")
        >>> key3 = IdempotencyKeyVO.from_string("abc123")
        >>> key3.validate()
        True
    """

    value: str
    prefix: str | None = None
    created_at: datetime | None = None
    source: str = "system"

    # Class constants
    MIN_LENGTH: int = 8
    MAX_LENGTH: int = 128
    DEFAULT_HASH_ALGO: str = "sha256"

    def __post_init__(self) -> None:
        """Validate idempotency key components."""
        # Validate value
        if not self.value or not isinstance(self.value, str):
            raise InvalidIdempotencyKeyError("Idempotency key must be a non-empty string")
        value_clean = self.value.strip()
        if len(value_clean) < self.MIN_LENGTH:
            raise InvalidIdempotencyKeyError(
                f"Idempotency key must be at least {self.MIN_LENGTH} characters, got {len(value_clean)}"
            )
        if len(value_clean) > self.MAX_LENGTH:
            raise InvalidIdempotencyKeyError(
                f"Idempotency key must not exceed {self.MAX_LENGTH} characters, got {len(value_clean)}"
            )
        # Allow alphanumeric, hyphen, underscore, colon, dot
        import re

        if not re.match(r"^[A-Za-z0-9_\-:.]+$", value_clean):
            raise InvalidIdempotencyKeyError(
                "Idempotency key can only contain alphanumeric, underscore, hyphen, colon, and dot"
            )
        object.__setattr__(self, "value", value_clean)

        # Validate prefix
        if self.prefix is not None:
            prefix_clean = self.prefix.strip()
            if len(prefix_clean) > 50:
                raise IdempotencyKeyError("Prefix must not exceed 50 characters")
            if not re.match(r"^[A-Za-z0-9_\-]+$", prefix_clean):
                raise IdempotencyKeyError(
                    "Prefix can only contain alphanumeric, underscore, and hyphen"
                )
            object.__setattr__(self, "prefix", prefix_clean if prefix_clean else None)

        # Validate created_at
        if self.created_at is not None:
            if self.created_at.tzinfo is None:
                object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

        # Validate source
        if not self.source or not isinstance(self.source, str):
            raise IdempotencyKeyError("Source must be a non-empty string")
        source_clean = self.source.strip().lower()
        if len(source_clean) > 20:
            raise IdempotencyKeyError("Source must not exceed 20 characters")
        object.__setattr__(self, "source", source_clean)

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @classmethod
    def generate(cls, prefix: str | None = None, length: int = 32) -> IdempotencyKeyVO:
        """
        Generate a cryptographically secure random idempotency key.

        Args:
            prefix: Optional namespace prefix (will be prepended)
            length: Desired length of random part (default 32)

        Returns:
            New IdempotencyKeyVO with random value
        """
        if length < 16:
            raise IdempotencyKeyError("Random length must be at least 16 for security")
        random_bytes = secrets.token_bytes(length // 2)  # each byte = 2 hex chars
        random_hex = random_bytes.hex()
        if prefix:
            value = f"{prefix}_{random_hex}"
        else:
            value = random_hex
        return cls(value=value, prefix=prefix, created_at=datetime.now(UTC), source="generated")

    @classmethod
    def from_uuid(cls, prefix: str | None = None) -> IdempotencyKeyVO:
        """
        Generate idempotency key from UUID4.

        Args:
            prefix: Optional namespace prefix

        Returns:
            IdempotencyKeyVO with UUID-based value
        """
        uid = uuid4()
        if prefix:
            value = f"{prefix}_{uid.hex}"
        else:
            value = uid.hex
        return cls(value=value, prefix=prefix, created_at=datetime.now(UTC), source="uuid")

    @classmethod
    def from_string(cls, value: str, source: str = "manual") -> IdempotencyKeyVO:
        """
        Create idempotency key from an existing string.

        Args:
            value: The key string (must meet validation)
            source: Source identifier (e.g., 'client', 'manual')

        Returns:
            IdempotencyKeyVO instance
        """
        return cls(value=value, source=source)

    @classmethod
    def from_request(
        cls, request_id: str, user_id: str, operation: str, prefix: str | None = None
    ) -> IdempotencyKeyVO:
        """
        Generate deterministic idempotency key from request metadata.

        Args:
            request_id: Unique request identifier (e.g., from header)
            user_id: User identifier
            operation: Operation name (e.g., 'post_journal')
            prefix: Optional namespace prefix

        Returns:
            IdempotencyKeyVO with SHA256 hash of combined inputs
        """
        raw = f"{request_id}|{user_id}|{operation}"
        hash_val = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if prefix:
            value = f"{prefix}_{hash_val}"
        else:
            value = hash_val
        return cls(value=value, prefix=prefix, created_at=datetime.now(UTC), source="request")

    @classmethod
    def from_transaction(
        cls, transaction_id: str, sequence: int, prefix: str | None = None
    ) -> IdempotencyKeyVO:
        """
        Generate idempotency key from transaction ID and sequence number.

        Args:
            transaction_id: Transaction identifier
            sequence: Sequence number (e.g., 1, 2, 3)
            prefix: Optional namespace prefix

        Returns:
            IdempotencyKeyVO
        """
        raw = f"{transaction_id}:{sequence}"
        hash_val = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
        if prefix:
            value = f"{prefix}_{hash_val}"
        else:
            value = hash_val
        return cls(value=value, prefix=prefix, created_at=datetime.now(UTC), source="transaction")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IdempotencyKeyVO:
        """Reconstruct from dictionary (e.g., from JSON)."""
        created = None
        if data.get("created_at"):
            created = datetime.fromisoformat(data["created_at"])
        return cls(
            value=data["value"],
            prefix=data.get("prefix"),
            created_at=created,
            source=data.get("source", "system"),
        )

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def short_value(self) -> str:
        """Return first 16 characters of value for display."""
        if len(self.value) <= 16:
            return self.value
        return self.value[:16] + "..."

    @property
    def is_expired(self, ttl_seconds: int = 86400) -> bool:
        """
        Check if key is older than TTL.

        Args:
            ttl_seconds: Time-to-live in seconds (default 24 hours)

        Returns:
            True if created_at is set and age > ttl_seconds
        """
        if self.created_at is None:
            return False
        age = (datetime.now(UTC) - self.created_at).total_seconds()
        return age > ttl_seconds

    @property
    def age_seconds(self) -> float | None:
        """Return age in seconds if created_at is set, else None."""
        if self.created_at is None:
            return None
        return (datetime.now(UTC) - self.created_at).total_seconds()

    # ------------------------------------------------------------------------
    # Business logic
    # ------------------------------------------------------------------------

    def validate(self) -> bool:
        """
        Validate that the key meets all requirements.
        Returns True if valid, False otherwise (does not raise).
        """
        try:
            self.__post_init__()
            return True
        except IdempotencyKeyError:
            return False

    def with_prefix(self, new_prefix: str) -> IdempotencyKeyVO:
        """
        Return a new key with a different prefix.
        The value is modified to include the new prefix.
        """
        if new_prefix == self.prefix:
            return self
        # Remove old prefix if present
        base_value = self.value
        if self.prefix and base_value.startswith(f"{self.prefix}_"):
            base_value = base_value[len(self.prefix) + 1 :]
        new_value = f"{new_prefix}_{base_value}"
        return IdempotencyKeyVO(
            value=new_value,
            prefix=new_prefix,
            created_at=self.created_at,
            source=self.source,
        )

    def without_prefix(self) -> IdempotencyKeyVO:
        """Return a new key with prefix removed."""
        if self.prefix is None:
            return self
        base_value = self.value
        if base_value.startswith(f"{self.prefix}_"):
            base_value = base_value[len(self.prefix) + 1 :]
        return IdempotencyKeyVO(
            value=base_value,
            prefix=None,
            created_at=self.created_at,
            source=self.source,
        )

    def normalize(self) -> IdempotencyKeyVO:
        """
        Return a normalized version (lowercase, trimmed).
        Useful for case-insensitive comparisons.
        """
        return IdempotencyKeyVO(
            value=self.value.lower().strip(),
            prefix=self.prefix.lower() if self.prefix else None,
            created_at=self.created_at,
            source=self.source,
        )

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "value": self.value,
            "short_value": self.short_value,
            "prefix": self.prefix,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "source": self.source,
            "age_seconds": self.age_seconds,
        }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "idempotency_key": self.value,
            "prefix": self.prefix,
            "created_at": self.created_at,
            "source": self.source,
        }

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return self.short_value

    def __repr__(self) -> str:
        return f"IdempotencyKeyVO('{self.short_value}', source={self.source})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IdempotencyKeyVO):
            return False
        return self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)

    def __lt__(self, other: IdempotencyKeyVO) -> bool:
        return self.value < other.value


# ============================================================================
# Helper Functions
# ============================================================================


def generate_idempotency_key_from_parts(
    parts: list[str], prefix: str | None = None
) -> IdempotencyKeyVO:
    """
    Generate deterministic key from a list of string parts.
    Useful for composite keys (e.g., tenant_id + user_id + date).
    """
    combined = "|".join(parts)
    hash_val = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    if prefix:
        value = f"{prefix}_{hash_val}"
    else:
        value = hash_val
    return IdempotencyKeyVO(value=value, prefix=prefix, source="composite")


def is_valid_idempotency_key(value: str) -> bool:
    """Quick validation without creating object (returns bool)."""
    try:
        IdempotencyKeyVO(value)
        return True
    except IdempotencyKeyError:
        return False


def normalize_idempotency_key(value: str) -> str:
    """Normalize a key string (lowercase, strip)."""
    return value.lower().strip()


# ============================================================================
# ALIAS FOR SERVICE LAYER (short name)
# ============================================================================

IdempotencyKey = IdempotencyKeyVO


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "IdempotencyKey",  # alias
    "IdempotencyKeyError",
    "IdempotencyKeyVO",
    "InvalidIdempotencyKeyError",
    "generate_idempotency_key_from_parts",
    "is_valid_idempotency_key",
    "normalize_idempotency_key",
]
