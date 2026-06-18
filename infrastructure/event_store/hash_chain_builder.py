#!/usr/bin/env python3
"""
Module: hash_chain_builder.py
Layer: Infrastructure (Event Store)
Responsibility: Membangun dan memverifikasi hash chain untuk event store.
               Hash chain adalah rantai kriptografis di mana setiap event
               berisi hash dari event sebelumnya, sehingga membentuk rantai
               yang tidak dapat diputus. Jika ada event yang diubah,
               semua hash setelahnya akan menjadi invalid.
               Builder ini menyediakan fungsi untuk:
               - Membangun hash chain dari list event
               - Memverifikasi integritas hash chain
               - Menemukan titik pemutusan rantai
               - Memperbaiki chain jika diperlukan (dengan audit trail)
Dependencies:
- hashlib, json, logging
- infrastructure.event_store.append_only_store (EventStoreTable)
- infrastructure.telemetry.structured_json_logging
Audit: Setiap verifikasi hash chain dicatat. Pemutusan rantai (tampering)
       akan memicu alert security.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from infrastructure.telemetry.alert_manager_router import trigger_alert

# Internal dependencies
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

GENESIS_HASH = hashlib.sha256(b"EVENT_STORE_GENESIS_2025").hexdigest()
GENESIS_HASH_ALT = (
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"  # SHA256 of empty string
)

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
        broken_at_sequence: int | None = None,
        expected_hash: str | None = None,
        actual_hash: str | None = None,
    ):
        super().__init__(message)
        self.broken_at_sequence = broken_at_sequence
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash


class HashChainValidationError(HashChainError):
    """Error dalam validasi hash chain."""

    pass


# ============================================================================
# HASH CHAIN BUILDER
# ============================================================================


class HashChainBuilder:
    """
    Builder untuk hash chain event store.

    Fitur:
    - Membangun hash chain dari list event
    - Verifikasi integritas rantai
    - Mendeteksi titik pemutusan
    - Generate genesis hash untuk stream baru
    - Mendukung multiple streams
    """

    def __init__(self):
        self._cache: dict[str, str] = {}  # stream_name -> last_hash
        self._verification_history: list[dict] = []

    @staticmethod
    def compute_event_hash(
        event_data: dict[str, Any],
        metadata: dict[str, Any],
        timestamp: datetime,
        previous_hash: str,
    ) -> str:
        """
        Compute SHA-256 hash of an event.

        Args:
            event_data: Event payload
            metadata: Event metadata
            timestamp: Event timestamp
            previous_hash: Hash of previous event in the chain

        Returns:
            Hexadecimal hash string
        """
        content = {
            "data": event_data,
            "metadata": metadata,
            "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp,
            "previous_hash": previous_hash,
        }
        # Sort keys for deterministic JSON
        json_str = json.dumps(content, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    @staticmethod
    def compute_batch_hash(events: list[dict[str, Any]]) -> str:
        """
        Compute combined hash for a batch of events (merkle tree root).
        """
        if not events:
            return GENESIS_HASH

        # Simple approach: concatenate all event hashes
        combined = "".join(event.get("hash", "") for event in events)
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()

    @staticmethod
    def is_genesis_hash(hash_value: str) -> bool:
        """Check if hash is the genesis hash."""
        return hash_value == GENESIS_HASH or hash_value == GENESIS_HASH_ALT

    async def build_chain(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Build hash chain for a list of events.

        Args:
            events: List of event dicts (must have sequence_number order)

        Returns:
            Events with hash fields populated
        """
        if not events:
            return []

        last_hash = GENESIS_HASH

        for i, event in enumerate(events):
            # Set previous hash
            event["previous_hash"] = last_hash

            # Compute hash if not already present
            if "hash" not in event or not event["hash"]:
                timestamp = event.get("timestamp")
                if isinstance(timestamp, str):
                    try:
                        timestamp = datetime.fromisoformat(timestamp)
                    except ValueError:
                        timestamp = datetime.now(UTC)

                event["hash"] = self.compute_event_hash(
                    event.get("data", {}), event.get("metadata", {}), timestamp, last_hash
                )

            last_hash = event["hash"]
            events[i] = event

        return events

    async def verify_chain(
        self, events: list[dict[str, Any]]
    ) -> tuple[bool, int | None, str | None]:
        """
        Verify the integrity of a hash chain.

        Args:
            events: List of events in sequence order

        Returns:
            Tuple of (is_valid, broken_at_sequence, error_message)
        """
        if not events:
            return True, None, None

        last_hash = GENESIS_HASH

        for i, event in enumerate(events):
            sequence = event.get("sequence_number", i + 1)
            event_hash = event.get("hash")
            previous_hash = event.get("previous_hash")

            # Check if previous_hash matches the computed last_hash
            if previous_hash != last_hash:
                error_msg = f"Hash chain broken at sequence {sequence}: expected previous_hash {last_hash[:16]}..., got {previous_hash[:16]}..."
                logger.error(error_msg)

                # Record verification failure
                self._verification_history.append(
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "is_valid": False,
                        "broken_at_sequence": sequence,
                        "error": error_msg,
                    }
                )

                return False, sequence, error_msg

            # Verify event hash is correct (recompute)
            recomputed = self.compute_event_hash(
                event.get("data", {}),
                event.get("metadata", {}),
                event.get("timestamp", datetime.now(UTC)),
                previous_hash,
            )

            if event_hash != recomputed:
                error_msg = f"Hash mismatch at sequence {sequence}: stored {event_hash[:16]}..., computed {recomputed[:16]}..."
                logger.error(error_msg)

                self._verification_history.append(
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "is_valid": False,
                        "broken_at_sequence": sequence,
                        "error": error_msg,
                    }
                )

                return False, sequence, error_msg

            last_hash = event_hash

        # Record successful verification
        self._verification_history.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "is_valid": True,
                "events_checked": len(events),
                "last_hash": last_hash[:16] + "...",
            }
        )

        logger.info(f"Hash chain verified successfully: {len(events)} events")
        return True, None, None

    async def find_broken_link(self, events: list[dict[str, Any]]) -> int | None:
        """
        Find the sequence number where the chain is broken.
        Returns the sequence number of the first invalid event.
        """
        if not events:
            return None

        last_hash = GENESIS_HASH

        for event in events:
            sequence = event.get("sequence_number", 0)
            previous_hash = event.get("previous_hash")

            if previous_hash != last_hash:
                return sequence

            # Recompute hash to verify
            recomputed = self.compute_event_hash(
                event.get("data", {}),
                event.get("metadata", {}),
                event.get("timestamp", datetime.now(UTC)),
                previous_hash,
            )

            if event.get("hash") != recomputed:
                return sequence

            last_hash = event.get("hash")

        return None

    async def repair_chain(
        self, events: list[dict[str, Any]], start_from: int
    ) -> list[dict[str, Any]]:
        """
        Repair a broken hash chain by recomputing hashes from a point.

        Args:
            events: List of events (may have broken chain)
            start_from: Sequence number to start recomputing from

        Returns:
            Events with repaired hashes
        """
        # Find the index to start from
        start_index = -1
        for i, event in enumerate(events):
            if event.get("sequence_number", i + 1) >= start_from:
                start_index = i
                break

        if start_index < 0:
            return events

        # Get last valid hash before start
        if start_index > 0:
            last_hash = events[start_index - 1].get("hash", GENESIS_HASH)
        else:
            last_hash = GENESIS_HASH

        # Recompute hashes from start_index
        for i in range(start_index, len(events)):
            event = events[i]
            event["previous_hash"] = last_hash
            event["hash"] = self.compute_event_hash(
                event.get("data", {}),
                event.get("metadata", {}),
                event.get("timestamp", datetime.now(UTC)),
                last_hash,
            )
            last_hash = event["hash"]
            events[i] = event

        logger.warning(f"Hash chain repaired from sequence {start_from}")

        # Record repair action
        self._verification_history.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": "repair",
                "start_from_sequence": start_from,
                "events_repaired": len(events) - start_index,
            }
        )

        return events

    async def get_last_hash(self, events: list[dict[str, Any]]) -> str:
        """
        Get the last hash in the chain.
        """
        if not events:
            return GENESIS_HASH

        last_hash = events[-1].get("hash")
        if last_hash:
            return last_hash

        # Compute if not present
        await self.build_chain(events)
        return events[-1].get("hash", GENESIS_HASH)

    async def get_chain_stats(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Get statistics about the hash chain.
        """
        if not events:
            return {
                "event_count": 0,
                "first_hash": GENESIS_HASH[:16] + "...",
                "last_hash": GENESIS_HASH[:16] + "...",
                "is_valid": True,
            }

        is_valid, broken_at, _ = await self.verify_chain(events)

        return {
            "event_count": len(events),
            "first_hash": events[0].get("hash", GENESIS_HASH)[:16] + "...",
            "last_hash": events[-1].get("hash", GENESIS_HASH)[:16] + "...",
            "is_valid": is_valid,
            "broken_at_sequence": broken_at if not is_valid else None,
            "genesis_hash": GENESIS_HASH[:16] + "...",
        }

    async def get_verification_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        Get history of chain verifications.
        """
        return self._verification_history[-limit:]

    async def clear_history(self) -> None:
        """Clear verification history."""
        self._verification_history.clear()
        logger.info("Hash chain verification history cleared")

    async def verify_stream(
        self, stream_name: str, events_by_stream: dict[str, list[dict]]
    ) -> dict[str, Any]:
        """
        Verify hash chain for a specific stream.
        """
        events = events_by_stream.get(stream_name, [])
        is_valid, broken_at, error = await self.verify_chain(events)

        if not is_valid and broken_at:
            await trigger_alert(
                title="Hash Chain Integrity Violation",
                message=f"Stream {stream_name} has broken hash chain at sequence {broken_at}: {error}",
                severity="critical",
                source="HashChainBuilder",
            )

        return {
            "stream_name": stream_name,
            "is_valid": is_valid,
            "broken_at_sequence": broken_at if not is_valid else None,
            "event_count": len(events),
        }


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def compute_hash_from_dict(data: dict[str, Any]) -> str:
    """
    Compute SHA-256 hash from a dictionary.
    """
    json_str = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(json_str.encode("utf-8")).hexdigest()


def verify_merkle_root(events: list[dict], expected_root: str) -> bool:
    """
    Verify Merkle tree root for a batch of events.
    """
    computed_root = HashChainBuilder.compute_batch_hash(events)
    return computed_root == expected_root


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_hash_chain_builder: HashChainBuilder | None = None


def get_hash_chain_builder() -> HashChainBuilder:
    """Get singleton instance of HashChainBuilder."""
    global _hash_chain_builder
    if _hash_chain_builder is None:
        _hash_chain_builder = HashChainBuilder()
    return _hash_chain_builder


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "GENESIS_HASH",
    "HashChainBrokenError",
    "HashChainBuilder",
    "HashChainError",
    "HashChainValidationError",
    "compute_hash_from_dict",
    "get_hash_chain_builder",
    "verify_merkle_root",
]
