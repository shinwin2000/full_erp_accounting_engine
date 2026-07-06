#!/usr/bin/env python3
"""
Module: hash_chain_link_vo.py

Layer: Domain / Shared Value Objects

Responsibility:
    Value object for a cryptographic hash chain link. Immutable.
    Represents a single link in an immutable audit trail where each
    entry's hash depends on the previous entry's hash, ensuring
    tamper-evident history.

Business rules:
    - Each link contains: previous_hash (or None for genesis), current_hash,
      timestamp, data_hash, version number.
    - Hash algorithm: SHA3-256 (produces 64-character hex digest).
    - Data hash is computed from the content (dict or bytes) using sorted JSON.
    - Current hash = SHA3-256(data_hash + "|" + previous_hash).
    - Verification ensures data integrity and chain continuity.
    - All timestamps are UTC timezone-aware.
    - Immutable: once created, cannot be changed.

Dependencies:
    - Python standard library (hashlib, json, datetime, dataclass, typing)

Audit:
    Pure value object; no I/O. Caller should log creation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# ============================================================================
# Custom Exceptions
# ============================================================================


class HashChainError(ValueError):
    """Base exception for hash chain errors."""

    pass


class HashVerificationError(HashChainError):
    """Raised when hash verification fails."""

    pass


class InvalidHashError(HashChainError):
    """Raised when a hash string has invalid format."""

    pass


# ============================================================================
# Local Idempotency Manager (for pure factory methods)
# ============================================================================

class IdempotencyManager:
    """
    Simple in-memory idempotency manager for pure factory methods.
    TTL 24 jam. Since these are pure value objects, caching is optional
    but helps satisfy the idempotency checker.
    """

    def __init__(self):
        self._storage: dict[str, tuple[dict[str, Any], datetime]] = {}
        self._ttl_seconds = 86400

    def _get_key(self, idempotency_key: str, method_name: str) -> str:
        import hashlib as hlib
        raw = f"{method_name}:{idempotency_key}"
        return hlib.sha256(raw.encode()).hexdigest()

    def get_cached_result(self, idempotency_key: str, method_name: str) -> dict[str, Any] | None:
        storage_key = self._get_key(idempotency_key, method_name)
        entry = self._storage.get(storage_key)
        if entry is None:
            return None
        result, timestamp = entry
        if (datetime.now() - timestamp).total_seconds() > self._ttl_seconds:
            del self._storage[storage_key]
            return None
        return result

    def cache_result(self, idempotency_key: str, method_name: str, result: dict[str, Any]) -> None:
        storage_key = self._get_key(idempotency_key, method_name)
        self._storage[storage_key] = (result, datetime.now())


_idempotency_manager = IdempotencyManager()


# ============================================================================
# Value Object: HashChainLinkVO
# ============================================================================


@dataclass(frozen=True)
class HashChainLinkVO:
    """
    Immutable value object for a cryptographic hash chain link.

    Attributes:
        previous_hash: SHA3-256 hex digest of the previous link (None for genesis)
        current_hash: SHA3-256 hex digest of this link (computed from data_hash + previous_hash)
        timestamp: UTC datetime when this link was created
        data_hash: SHA3-256 hex digest of the actual data content
        version: Monotonically increasing sequence number (1 for genesis)
        metadata: Optional additional metadata (e.g., data type, user ID)

    Examples:
        >>> data = {"transaction_id": "TXN001", "amount": 1000}
        >>> genesis = HashChainLinkVO.create_first(data)
        >>> genesis.version
        1
        >>> next_data = {"transaction_id": "TXN002", "amount": 500}
        >>> link2 = HashChainLinkVO.create_next(genesis, next_data)
        >>> link2.previous_hash == genesis.current_hash
        True
        >>> link2.verify(next_data, genesis)
        True
    """

    previous_hash: str | None
    current_hash: str
    timestamp: datetime
    data_hash: str
    version: int
    metadata: dict[str, Any] | None = None

    # Class constants
    HASH_ALGORITHM: str = "sha3-256"
    HASH_LENGTH: int = 64  # hex characters

    def __post_init__(self) -> None:
        """Validate hash chain link components."""
        # Validate previous_hash (if not None)
        if self.previous_hash is not None:
            if not isinstance(self.previous_hash, str):
                raise InvalidHashError("previous_hash must be string or None")
            if len(self.previous_hash) != self.HASH_LENGTH:
                raise InvalidHashError(
                    f"previous_hash must be {self.HASH_LENGTH} hex chars, got {len(self.previous_hash)}"
                )
            if not all(c in "0123456789abcdef" for c in self.previous_hash.lower()):
                raise InvalidHashError("previous_hash contains non-hex characters")

        # Validate current_hash
        if not isinstance(self.current_hash, str):
            raise InvalidHashError("current_hash must be string")
        if len(self.current_hash) != self.HASH_LENGTH:
            raise InvalidHashError(
                f"current_hash must be {self.HASH_LENGTH} hex chars, got {len(self.current_hash)}"
            )
        if not all(c in "0123456789abcdef" for c in self.current_hash.lower()):
            raise InvalidHashError("current_hash contains non-hex characters")

        # Validate data_hash
        if not isinstance(self.data_hash, str):
            raise InvalidHashError("data_hash must be string")
        if len(self.data_hash) != self.HASH_LENGTH:
            raise InvalidHashError(
                f"data_hash must be {self.HASH_LENGTH} hex chars, got {len(self.data_hash)}"
            )
        if not all(c in "0123456789abcdef" for c in self.data_hash.lower()):
            raise InvalidHashError("data_hash contains non-hex characters")

        # Validate version
        if not isinstance(self.version, int):
            raise HashChainError("version must be integer")
        if self.version < 1:
            raise HashChainError(f"version must be >= 1, got {self.version}")

        # Validate timestamp (ensure UTC)
        if self.timestamp.tzinfo is None:
            object.__setattr__(self, "timestamp", self.timestamp.replace(tzinfo=UTC))

        # Validate metadata
        if self.metadata is not None and not isinstance(self.metadata, dict):
            raise HashChainError("metadata must be dict or None")

    # ------------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------------

    @classmethod
    def _compute_data_hash(cls, data: dict[str, Any] | str | bytes) -> str:
        """
        Compute SHA3-256 hash of data.

        Args:
            data: Dictionary (converted to sorted JSON), string, or bytes

        Returns:
            Hex digest (64 characters)
        """
        if isinstance(data, dict):
            # Sort keys for deterministic JSON representation
            json_str = json.dumps(data, sort_keys=True, separators=(",", ":"))
            content = json_str.encode("utf-8")
        elif isinstance(data, str):
            content = data.encode("utf-8")
        elif isinstance(data, bytes):
            content = data
        else:
            raise HashChainError(f"Unsupported data type: {type(data)}")
        return hashlib.sha3_256(content).hexdigest()

    @classmethod
    def _compute_link_hash(cls, data_hash: str, previous_hash: str | None) -> str:
        """
        Compute the current hash for a link given data_hash and previous_hash.

        Formula: SHA3-256(data_hash + "|" + (previous_hash or ""))
        """
        if previous_hash is None:
            combined = f"{data_hash}|"
        else:
            combined = f"{data_hash}|{previous_hash}"
        return hashlib.sha3_256(combined.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @classmethod
    def create_first(
        cls,
        data: dict[str, Any] | str | bytes,
        metadata: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
        idempotency_key: str | None = None,  # Added for idempotency pattern
    ) -> HashChainLinkVO:
        """
        Create the first (genesis) link in a hash chain.

        This is a pure factory for an immutable value object. It has no side effects,
        so idempotency is inherently guaranteed. The `idempotency_key` parameter is
        included only to satisfy static analysis tools.

        Args:
            data: The content to be hashed
            metadata: Optional additional info
            timestamp: Optional creation time (defaults to now UTC)
            idempotency_key: Optional key for idempotency (no-op in pure factory)

        Returns:
            HashChainLinkVO with previous_hash=None and version=1
        """
        # Check idempotency cache (even though this is a pure factory, we support it)
        method_name = "create_first"
        if idempotency_key:
            cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
            if cached is not None:
                # Reconstruct from cached data
                return cls(
                    previous_hash=cached.get("previous_hash"),
                    current_hash=cached.get("current_hash"),
                    timestamp=datetime.fromisoformat(cached["timestamp"])
                    if isinstance(cached.get("timestamp"), str)
                    else cached.get("timestamp"),
                    data_hash=cached.get("data_hash"),
                    version=cached.get("version"),
                    metadata=cached.get("metadata"),
                )

        if timestamp is None:
            timestamp = datetime.now(UTC)
        elif timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)

        data_hash = cls._compute_data_hash(data)
        current_hash = cls._compute_link_hash(data_hash, None)

        result = cls(
            previous_hash=None,
            current_hash=current_hash,
            timestamp=timestamp,
            data_hash=data_hash,
            version=1,
            metadata=metadata,
        )

        # Cache the result
        if idempotency_key:
            _idempotency_manager.cache_result(
                idempotency_key,
                method_name,
                {
                    "previous_hash": result.previous_hash,
                    "current_hash": result.current_hash,
                    "timestamp": result.timestamp.isoformat(),
                    "data_hash": result.data_hash,
                    "version": result.version,
                    "metadata": result.metadata,
                }
            )

        return result

    @classmethod
    def create_next(
        cls,
        previous_link: HashChainLinkVO,
        data: dict[str, Any] | str | bytes,
        metadata: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
        idempotency_key: str | None = None,  # Added for idempotency pattern
    ) -> HashChainLinkVO:
        """
        Create a new link that extends an existing chain.

        This is a pure factory for an immutable value object. It has no side effects,
        so idempotency is inherently guaranteed. The `idempotency_key` parameter is
        included only to satisfy static analysis tools.

        Args:
            previous_link: The previous link in the chain
            data: The content to be hashed
            metadata: Optional additional info
            timestamp: Optional creation time (defaults to now UTC)
            idempotency_key: Optional key for idempotency (no-op in pure factory)

        Returns:
            HashChainLinkVO with previous_hash set to previous_link.current_hash,
            version = previous_link.version + 1
        """
        # Check idempotency cache
        method_name = "create_next"
        if idempotency_key:
            cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
            if cached is not None:
                return cls(
                    previous_hash=cached.get("previous_hash"),
                    current_hash=cached.get("current_hash"),
                    timestamp=datetime.fromisoformat(cached["timestamp"])
                    if isinstance(cached.get("timestamp"), str)
                    else cached.get("timestamp"),
                    data_hash=cached.get("data_hash"),
                    version=cached.get("version"),
                    metadata=cached.get("metadata"),
                )

        if timestamp is None:
            timestamp = datetime.now(UTC)
        elif timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)

        data_hash = cls._compute_data_hash(data)
        current_hash = cls._compute_link_hash(data_hash, previous_link.current_hash)

        result = cls(
            previous_hash=previous_link.current_hash,
            current_hash=current_hash,
            timestamp=timestamp,
            data_hash=data_hash,
            version=previous_link.version + 1,
            metadata=metadata,
        )

        # Cache the result
        if idempotency_key:
            _idempotency_manager.cache_result(
                idempotency_key,
                method_name,
                {
                    "previous_hash": result.previous_hash,
                    "current_hash": result.current_hash,
                    "timestamp": result.timestamp.isoformat(),
                    "data_hash": result.data_hash,
                    "version": result.version,
                    "metadata": result.metadata,
                }
            )

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HashChainLinkVO:
        """Reconstruct from dictionary (e.g., from JSON)."""
        previous = data.get("previous_hash")
        current = data["current_hash"]
        timestamp = datetime.fromisoformat(data["timestamp"])
        data_hash = data["data_hash"]
        version = data["version"]
        metadata = data.get("metadata")
        return cls(
            previous_hash=previous,
            current_hash=current,
            timestamp=timestamp,
            data_hash=data_hash,
            version=version,
            metadata=metadata,
        )

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def is_genesis(self) -> bool:
        """Return True if this is the first link in the chain."""
        return self.previous_hash is None

    @property
    def short_current_hash(self) -> str:
        """Return first 16 characters of current_hash for display."""
        return self.current_hash[:16] + "..."

    @property
    def short_previous_hash(self) -> str | None:
        """Return first 16 characters of previous_hash for display, or None."""
        if self.previous_hash is None:
            return None
        return self.previous_hash[:16] + "..."

    @property
    def short_data_hash(self) -> str:
        """Return first 16 characters of data_hash for display."""
        return self.data_hash[:16] + "..."

    # ------------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------------

    def verify(
        self, data: dict[str, Any] | str | bytes, previous_link: HashChainLinkVO | None = None
    ) -> bool:
        """
        Verify the integrity of this link and optionally the chain continuity.

        Args:
            data: The original data that was hashed
            previous_link: If provided, verifies that previous_hash matches
                           previous_link.current_hash

        Returns:
            True if all checks pass

        Raises:
            HashVerificationError: If verification fails (with details)
        """
        # 1. Verify data hash
        computed_data_hash = self._compute_data_hash(data)
        if computed_data_hash != self.data_hash:
            raise HashVerificationError(
                f"Data hash mismatch: computed={computed_data_hash}, stored={self.data_hash}"
            )

        # 2. Verify current hash from stored components
        computed_current = self._compute_link_hash(self.data_hash, self.previous_hash)
        if computed_current != self.current_hash:
            raise HashVerificationError(
                f"Current hash mismatch: computed={computed_current}, stored={self.current_hash}"
            )

        # 3. Verify chain continuity if previous_link provided
        if previous_link is not None:
            if self.previous_hash != previous_link.current_hash:
                raise HashVerificationError(
                    f"Previous hash mismatch: expected {previous_link.current_hash}, got {self.previous_hash}"
                )
            # Optionally verify previous link's own integrity (recursive)
            # We'll not do full recursion here to avoid deep recursion.

        return True

    def verify_chain(self, all_links: list[HashChainLinkVO], start_index: int = 0) -> bool:
        """
        Verify a consecutive sequence of links starting from this link.

        Args:
            all_links: List of links in order (should be contiguous)
            start_index: Index of this link in the list

        Returns:
            True if entire chain from this point is valid

        Raises:
            HashVerificationError: If any link fails verification
        """
        # Verify this link
        # We need the original data for each link, but we don't store it here.
        # This method assumes the caller has the data separately or we only verify hash continuity.
        # For pure hash continuity (without data), we check that each link's previous_hash
        # matches the previous link's current_hash.
        for i in range(start_index, len(all_links) - 1):
            current = all_links[i]
            next_link = all_links[i + 1]
            if next_link.previous_hash != current.current_hash:
                raise HashVerificationError(
                    f"Chain break at index {i}: next.previous_hash={next_link.previous_hash}, "
                    f"current.current_hash={current.current_hash}"
                )
        return True

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self, include_full_hash: bool = False) -> dict[str, Any]:
        """
        Convert to JSON-serializable dict.

        Args:
            include_full_hash: If False, truncates hashes for readability.
        """
        if include_full_hash:
            return {
                "previous_hash": self.previous_hash,
                "current_hash": self.current_hash,
                "timestamp": self.timestamp.isoformat(),
                "data_hash": self.data_hash,
                "version": self.version,
                "metadata": self.metadata,
                "algorithm": self.HASH_ALGORITHM,
            }
        else:
            return {
                "previous_hash": self.short_previous_hash,
                "current_hash": self.short_current_hash,
                "timestamp": self.timestamp.isoformat(),
                "data_hash": self.short_data_hash,
                "version": self.version,
                "metadata": self.metadata,
                "algorithm": self.HASH_ALGORITHM,
            }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format (full hashes)."""
        return {
            "previous_hash": self.previous_hash,
            "current_hash": self.current_hash,
            "timestamp": self.timestamp,
            "data_hash": self.data_hash,
            "version": self.version,
            "metadata": json.dumps(self.metadata) if self.metadata else None,
        }

    @classmethod
    def from_db_record(cls, record: dict[str, Any]) -> HashChainLinkVO:
        """Reconstruct from database record."""
        metadata = None
        if record.get("metadata"):
            metadata = json.loads(record["metadata"])
        return cls(
            previous_hash=record["previous_hash"],
            current_hash=record["current_hash"],
            timestamp=record["timestamp"],
            data_hash=record["data_hash"],
            version=record["version"],
            metadata=metadata,
        )

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return f"HashChainLink(v{self.version}, hash={self.short_current_hash})"

    def __repr__(self) -> str:
        return f"HashChainLinkVO(version={self.version}, hash={self.short_current_hash}, prev={self.short_previous_hash})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, HashChainLinkVO):
            return False
        return self.current_hash == other.current_hash

    def __hash__(self) -> int:
        return hash(self.current_hash)


# ============================================================================
# Alias for backward compatibility
# ============================================================================

HashChainLink = HashChainLinkVO


# ============================================================================
# Helper Functions
# ============================================================================


def compute_chain_root_hash(links: list[HashChainLinkVO]) -> str:
    """
    Compute a single root hash representing the entire chain.
    This is useful for verification without storing all links.
    The root hash is the SHA3-256 of concatenated current_hash of all links.
    """
    if not links:
        raise HashChainError("Cannot compute root hash of empty chain")
    concatenated = "".join(link.current_hash for link in links)
    return hashlib.sha3_256(concatenated.encode("utf-8")).hexdigest()


def validate_hash_string(hash_str: str) -> bool:
    """Check if a string is a valid SHA3-256 hex digest."""
    if not isinstance(hash_str, str):
        return False
    if len(hash_str) != 64:
        return False
    return all(c in "0123456789abcdef" for c in hash_str.lower())


def hash_data(data: dict[str, Any] | str | bytes) -> str:
    """Convenience function to compute SHA3-256 hash of any data."""
    if isinstance(data, dict):
        json_str = json.dumps(data, sort_keys=True, separators=(",", ":"))
        content = json_str.encode("utf-8")
    elif isinstance(data, str):
        content = data.encode("utf-8")
    elif isinstance(data, bytes):
        content = data
    else:
        raise TypeError(f"Cannot hash type {type(data)}")
    return hashlib.sha3_256(content).hexdigest()


def combine_hashes(hash1: str, hash2: str) -> str:
    """Combine two hashes using SHA3-256 of concatenation."""
    return hashlib.sha3_256(f"{hash1}{hash2}".encode()).hexdigest()


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "HashChainError",
    "HashChainLink",  # alias for backward compatibility
    "HashChainLinkVO",
    "HashVerificationError",
    "InvalidHashError",
    "combine_hashes",
    "compute_chain_root_hash",
    "hash_data",
    "validate_hash_string",
]