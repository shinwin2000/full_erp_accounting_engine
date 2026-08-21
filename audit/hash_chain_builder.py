#!/usr/bin/env python3
"""
Module: hash_chain_builder.py
Layer: Audit
Responsibility: Membangun dan memverifikasi hash chain untuk audit trail.
               Setiap record audit di-hash bersama dengan hash record sebelumnya,
               membentuk rantai yang tidak dapat diputus. Jika ada record yang
               diubah, hash record berikutnya akan menjadi invalid.
               Digunakan untuk memastikan integritas audit trail.
Dependencies:
- hashlib, json, logging, datetime
- infrastructure.event_store.append_only_store (opsional)
- infrastructure.telemetry.structured_json_logging
Audit: Hash chain digunakan untuk deteksi tampering audit trail.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from typing import Any

# ============================================================================
# CONSTANTS
# ============================================================================

GENESIS_HASH = hashlib.sha256(b"AUDIT_TRAIL_GENESIS_2025").hexdigest()

_logger = None


def _get_logger():
    """Lazy logger initialization from structured logging."""
    global _logger
    if _logger is None:
        mod = importlib.import_module("infrastructure.telemetry.structured_json_logging")
        get_logger_func = mod.get_logger
        _logger = get_logger_func(__name__)
    return _logger


# ============================================================================
# EXCEPTIONS
# ============================================================================


class HashChainError(Exception):
    """Base exception untuk hash chain."""

    pass


class HashChainBrokenError(HashChainError):
    """Hash chain terputus (tampering detected)."""

    def __init__(
        self,
        message: str,
        broken_at_index: int | None = None,
        expected_hash: str | None = None,
        actual_hash: str | None = None,
    ):
        super().__init__(message)
        self.broken_at_index = broken_at_index
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash


# ============================================================================
# HASH CHAIN BUILDER (AUDIT)
# ============================================================================


class AuditHashChainBuilder:
    """
    Builder untuk hash chain audit trail.

    Fitur:
    - Membangun hash chain dari list audit records
    - Menambahkan hash ke setiap record
    - Memverifikasi integritas rantai
    - Mendeteksi titik pemutusan
    - Mendukung multiple streams (untuk audit per entity)
    """

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}  # stream_name -> last_hash

    @staticmethod
    def compute_record_hash(record: dict[str, Any], previous_hash: str) -> str:
        """
        Compute SHA-256 hash of an audit record.

        Args:
            record: Audit record dictionary (without hash field)
            previous_hash: Hash of previous record in chain

        Returns:
            Hexadecimal hash string
        """
        # Create a copy without hash field
        record_copy = {k: v for k, v in record.items() if k != "hash"}
        # Add previous_hash to the content
        content = {"record": record_copy, "previous_hash": previous_hash}
        json_str = json.dumps(content, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    @staticmethod
    def compute_batch_hash(records: list[dict[str, Any]]) -> str:
        """
        Compute combined hash for a batch of records (merkle tree root).
        """
        if not records:
            return GENESIS_HASH

        hashes = [r.get("hash", "") for r in records if r.get("hash")]
        if not hashes:
            # Compute hashes on the fly
            last_hash = GENESIS_HASH
            for record in records:
                last_hash = AuditHashChainBuilder.compute_record_hash(record, last_hash)
                hashes.append(last_hash)

        # Simple approach: concatenate all hashes
        combined = "".join(hashes)
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()

    async def build_chain(
        self, records: list[dict[str, Any]], stream_name: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Build hash chain for a list of audit records.

        Args:
            records: List of audit record dicts (in chronological order)
            stream_name: Optional stream name for caching last hash

        Returns:
            Records with hash fields populated
        """
        if not records:
            return []

        # Get last hash from cache or use genesis
        if stream_name and stream_name in self._cache:
            last_hash = self._cache[stream_name]
        else:
            last_hash = GENESIS_HASH

        for i, record in enumerate(records):
            # Set previous hash
            record["previous_hash"] = last_hash

            # Compute hash if not already present
            if "hash" not in record or not record["hash"]:
                record["hash"] = self.compute_record_hash(record, last_hash)

            last_hash = record["hash"]
            records[i] = record

        # Update cache
        if stream_name:
            self._cache[stream_name] = last_hash

        return records

    async def verify_chain(
        self, records: list[dict[str, Any]], stream_name: str | None = None
    ) -> tuple[bool, int | None, str | None]:
        """
        Verify the integrity of a hash chain.

        Args:
            records: List of audit records in sequence order
            stream_name: Optional stream name for validation

        Returns:
            Tuple of (is_valid, broken_at_index, error_message)
        """
        if not records:
            return True, None, None

        last_hash = GENESIS_HASH

        for i, record in enumerate(records):
            previous_hash = record.get("previous_hash")
            record_hash = record.get("hash")

            # Check if previous_hash matches the computed last_hash
            if previous_hash != last_hash:
                # Convert to string to ensure safe slicing
                prev_str = str(previous_hash) if previous_hash is not None else "<None>"
                last_str = str(last_hash)
                error_msg = (
                    f"Hash chain broken at index {i}: expected previous_hash {last_str[:16]}..., "
                    f"got {prev_str[:16]}..."
                )
                logger = _get_logger()
                logger.error(error_msg)
                return False, i, error_msg

            # Verify record hash is correct (recompute)
            recomputed = self.compute_record_hash(record, previous_hash)  # type: ignore
            if record_hash != recomputed:
                rec_str = str(record_hash) if record_hash is not None else "<None>"
                rec_computed = str(recomputed)
                error_msg = (
                    f"Hash mismatch at index {i}: stored {rec_str[:16]}..., "
                    f"computed {rec_computed[:16]}..."
                )
                logger = _get_logger()
                logger.error(error_msg)
                return False, i, error_msg

            last_hash = record_hash  # type: ignore

        # Update cache if valid
        if stream_name:
            self._cache[stream_name] = last_hash

        logger = _get_logger()
        logger.info(f"Hash chain verified successfully: {len(records)} records")
        return True, None, None

    async def find_broken_link(self, records: list[dict[str, Any]]) -> int | None:
        """
        Find the index where the chain is broken.

        Returns:
            Index of first invalid record, or None if chain is valid
        """
        if not records:
            return None

        last_hash = GENESIS_HASH

        for i, record in enumerate(records):
            previous_hash = record.get("previous_hash")
            record_hash = record.get("hash")

            if previous_hash != last_hash:
                return i

            recomputed = self.compute_record_hash(record, previous_hash)  # type: ignore
            if record_hash != recomputed:
                return i

            last_hash = record_hash  # type: ignore

        return None

    async def repair_chain(
        self, records: list[dict[str, Any]], start_index: int
    ) -> list[dict[str, Any]]:
        """
        Repair a broken hash chain by recomputing hashes from a point.

        Args:
            records: List of audit records (may have broken chain)
            start_index: Index to start recomputing from

        Returns:
            Records with repaired hashes
        """
        if start_index < 0 or start_index >= len(records):
            return records

        # Get last valid hash before start_index
        if start_index > 0:
            last_hash = records[start_index - 1].get("hash", GENESIS_HASH)
        else:
            last_hash = GENESIS_HASH

        # Recompute hashes from start_index
        for i in range(start_index, len(records)):
            record = records[i]
            record["previous_hash"] = last_hash
            record["hash"] = self.compute_record_hash(record, last_hash)
            last_hash = record["hash"]
            records[i] = record

        logger = _get_logger()
        logger.warning(f"Hash chain repaired from index {start_index}")
        return records

    async def get_last_hash(self, records: list[dict[str, Any]]) -> str:
        """
        Get the last hash in the chain.
        """
        if not records:
            return GENESIS_HASH

        last_hash = records[-1].get("hash")
        if last_hash:
            return last_hash

        # Compute if not present
        await self.build_chain(records)
        return records[-1].get("hash", GENESIS_HASH)

    async def get_chain_stats(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Get statistics about the hash chain.
        """
        if not records:
            return {
                "record_count": 0,
                "first_hash": GENESIS_HASH[:16] + "...",
                "last_hash": GENESIS_HASH[:16] + "...",
                "is_valid": True,
            }

        is_valid, broken_at, _ = await self.verify_chain(records)

        first_hash = records[0].get("hash", GENESIS_HASH)
        last_hash = records[-1].get("hash", GENESIS_HASH)

        return {
            "record_count": len(records),
            "first_hash": str(first_hash)[:16] + "...",
            "last_hash": str(last_hash)[:16] + "...",
            "is_valid": is_valid,
            "broken_at_index": broken_at if not is_valid else None,
        }

    async def clear_cache(self, stream_name: str | None = None) -> None:
        """
        Clear hash cache for a specific stream or all streams.
        """
        if stream_name:
            self._cache.pop(stream_name, None)
        else:
            self._cache.clear()
        logger = _get_logger()
        logger.info("Hash chain cache cleared")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_audit_hash_builder: AuditHashChainBuilder | None = None


def get_audit_hash_builder() -> AuditHashChainBuilder:
    """Get singleton instance of AuditHashChainBuilder."""
    global _audit_hash_builder
    if _audit_hash_builder is None:
        _audit_hash_builder = AuditHashChainBuilder()
    return _audit_hash_builder


# ============================================================================
# EXPORTS
# ============================================================================
HashChainBuilder = AuditHashChainBuilder


__all__ = [
    "GENESIS_HASH",
    "AuditHashChainBuilder",
    "HashChainBrokenError",
    "HashChainBuilder",
    "HashChainError",
    "get_audit_hash_builder",
]
