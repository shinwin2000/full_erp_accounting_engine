#!/usr/bin/env python3
"""
Adapter: Hash Chain Service
Layer: Adapters (Secondary Implementation)

Adapter untuk layanan hash chain.
Menggunakan lazy import untuk menghindari ketergantungan langsung ke lapisan audit.
"""

from __future__ import annotations

import importlib
import hashlib
import json
from typing import Any, Optional
from uuid import UUID

from ports.primary.hash_chain_service_port import (
    HashChainServicePort,
    ChainType,
    HashChainEntry,
    IntegrityCheckResult,
)

_logger = None


def _get_logger():
    """Lazy import structured logging."""
    global _logger
    if _logger is None:
        mod = importlib.import_module("infrastructure.telemetry.structured_json_logging")
        get_logger = mod.get_logger
        _logger = get_logger(__name__)
    return _logger


def _get_hash_builder():
    """Lazy import HashChainBuilder from audit.hash_chain_builder."""
    mod = importlib.import_module("audit.hash_chain_builder")
    return mod.HashChainBuilder


class HashChainServiceAdapter(HashChainServicePort):
    """
    Adapter yang menggunakan HashChainBuilder untuk membangun dan memverifikasi rantai hash.
    Semua import ke audit dilakukan secara lazy untuk menjaga kepatuhan arsitektur.
    """

    def __init__(self, chain_type: str, chain_id: UUID):
        """
        Inisialisasi adapter dengan konteks rantai.
        """
        self._chain_type = chain_type
        self._chain_id = chain_id
        self._builder = None
        self._monitoring_active = False

    @property
    def builder(self):
        """Lazy initialization of HashChainBuilder."""
        if self._builder is None:
            HashChainBuilder = _get_hash_builder()
            self._builder = HashChainBuilder()
        return self._builder

    # ===== Core methods (dengan chain_type dan chain_id sebagai parameter) =====

    async def append(
        self,
        chain_type: str,
        chain_id: UUID,
        payload: dict,
        payload_type: str,
        payload_ref_id: UUID | None,
        created_by: UUID,
        metadata: dict | None = None,
        sign: bool = True,
        timestamp_token: str | None = None,
    ):
        """Append an entry to the specified chain."""
        return await self.builder.append(
            chain_type,
            chain_id,
            payload,
            payload_type,
            payload_ref_id,
            created_by,
            metadata,
            sign,
            timestamp_token,
        )

    async def verify_chain(
        self,
        chain_type: str,
        chain_id: UUID,
        deep_verify: bool = True,
        check_signatures: bool = True,
    ):
        """Verify the specified chain."""
        return await self.builder.verify_chain(
            chain_type, chain_id, deep_verify, check_signatures
        )

    async def get_last_hash(self, chain_type: str, chain_id: UUID) -> str | None:
        return await self.builder.get_last_hash(chain_type, chain_id)

    async def get_chain_entries(
        self,
        chain_type: str,
        chain_id: UUID,
        limit: int = 1000,
        offset: int = 0,
    ):
        return await self.builder.get_chain_entries(chain_type, chain_id, limit, offset)

    async def health_check(self) -> dict:
        return await self.builder.health_check()

    # ===== Extended methods =====

    async def attach_timestamp_token(
        self,
        chain_type: str,
        chain_id: UUID,
        sequence: int,
        timestamp_token: str,
        user_id: UUID,
    ) -> bool:
        """
        Attach a timestamp token to an existing entry.
        Port signature: attach_timestamp_token(chain_type, chain_id, sequence, timestamp_token, user_id)
        """
        if hasattr(self.builder, "attach_timestamp_token"):
            return await self.builder.attach_timestamp_token(
                chain_type, chain_id, sequence, timestamp_token, user_id
            )
        logger = _get_logger()
        logger.warning("attach_timestamp_token not implemented in builder, stub.")
        return False

    async def build_merkle_root(
        self,
        chain_type: str,
        chain_id: UUID,
        from_sequence: int = 0,
        to_sequence: int | None = None,
    ) -> str | None:
        """Build Merkle root for a range of entries."""
        if hasattr(self.builder, "build_merkle_root"):
            return await self.builder.build_merkle_root(
                chain_type, chain_id, from_sequence, to_sequence
            )
        logger = _get_logger()
        logger.warning("build_merkle_root not implemented in builder, stub.")
        return None

    async def compute_hash(self, data: bytes | str) -> str:
        """
        Compute hash of the given data (only the data, no previous hash).
        Port signature: compute_hash(data) -> str
        """
        if hasattr(self.builder, "compute_hash"):
            return await self.builder.compute_hash(data)
        # Fallback
        if isinstance(data, str):
            data = data.encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    async def compute_payload_hash(self, payload: dict) -> str:
        """
        Compute hash of a payload.
        Port signature: compute_payload_hash(payload) -> str
        """
        if hasattr(self.builder, "compute_payload_hash"):
            return await self.builder.compute_payload_hash(payload)
        # Fallback
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def detect_gaps(self, chain_type: str, chain_id: UUID) -> list[int]:
        """Detect gaps (missing sequence numbers) in the specified chain."""
        if hasattr(self.builder, "detect_gaps"):
            return await self.builder.detect_gaps(chain_type, chain_id)
        logger = _get_logger()
        logger.warning("detect_gaps not implemented in builder, stub.")
        return []

    async def export_chain(
        self,
        chain_type: str,
        chain_id: UUID,
        include_payload: bool = False,
    ) -> str:
        """Export the chain in JSON format."""
        if hasattr(self.builder, "export_chain"):
            return await self.builder.export_chain(
                chain_type, chain_id, "full" if include_payload else "metadata"
            )
        logger = _get_logger()
        logger.warning("export_chain not implemented in builder, stub.")
        return ""

    async def get_chain_length(self, chain_type: str, chain_id: UUID) -> int:
        """Get number of entries in the chain."""
        if hasattr(self.builder, "get_chain_length"):
            return await self.builder.get_chain_length(chain_type, chain_id)
        entries = await self.get_chain_entries(chain_type, chain_id, limit=1)
        return len(entries) if entries else 0

    async def get_entry_by_hash(self, current_hash: str) -> HashChainEntry | None:
        """
        Get an entry by its hash.
        Port signature: get_entry_by_hash(current_hash) -> HashChainEntry | None
        Uses the chain context stored in the adapter.
        """
        if hasattr(self.builder, "get_entry_by_hash"):
            raw = await self.builder.get_entry_by_hash(
                self._chain_type, self._chain_id, current_hash
            )
            if raw and isinstance(raw, dict):
                try:
                    from ports.primary.hash_chain_service_port import HashChainEntry
                    return HashChainEntry(**raw)
                except (ImportError, TypeError):
                    return raw
            return None
        logger = _get_logger()
        logger.warning("get_entry_by_hash not implemented in builder, stub.")
        return None

    async def get_entry_by_sequence(
        self,
        chain_type: str,
        chain_id: UUID,
        sequence: int,
    ) -> HashChainEntry | None:
        """Get an entry by sequence number."""
        if hasattr(self.builder, "get_entry_by_sequence"):
            raw = await self.builder.get_entry_by_sequence(chain_type, chain_id, sequence)
            if raw and isinstance(raw, dict):
                try:
                    from ports.primary.hash_chain_service_port import HashChainEntry
                    return HashChainEntry(**raw)
                except (ImportError, TypeError):
                    return raw
            return None
        logger = _get_logger()
        logger.warning("get_entry_by_sequence not implemented in builder, stub.")
        return None

    async def get_integrity_history(self, limit: int = 50) -> list[IntegrityCheckResult]:
        """
        Get integrity check history for the current chain.
        Port signature: get_integrity_history(limit) -> list[IntegrityCheckResult]
        Uses the chain context stored in the adapter.
        """
        if hasattr(self.builder, "get_integrity_history"):
            raw = await self.builder.get_integrity_history(
                self._chain_type, self._chain_id, limit
            )
            if raw and isinstance(raw, list):
                try:
                    from ports.primary.hash_chain_service_port import IntegrityCheckResult
                    return [
                        IntegrityCheckResult(**item) if isinstance(item, dict) else item
                        for item in raw
                    ]
                except (ImportError, TypeError):
                    return raw
            return raw or []
        logger = _get_logger()
        logger.warning("get_integrity_history not implemented in builder, stub.")
        return []

    async def get_statistics(
        self,
        chain_type: str | None = None,
        chain_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Get statistics for the specified chain or all chains."""
        if hasattr(self.builder, "get_statistics"):
            return await self.builder.get_statistics(chain_type, chain_id)
        # Fallback
        if chain_type is None or chain_id is None:
            return {"total_chains": 0, "total_entries": 0}
        return {
            "chain_type": chain_type,
            "chain_id": str(chain_id),
            "total_entries": await self.get_chain_length(chain_type, chain_id),
        }

    async def import_chain(self, data: str) -> tuple[ChainType, UUID]:
        """
        Import a chain from serialized data.
        Port signature: import_chain(data) -> tuple[ChainType, UUID]
        """
        if hasattr(self.builder, "import_chain"):
            result = await self.builder.import_chain(data)
            if result and isinstance(result, tuple) and len(result) == 2:
                return result
        logger = _get_logger()
        logger.warning("import_chain not implemented in builder, stub.")
        # Fallback: parse from data
        try:
            parsed = json.loads(data)
            chain_type = parsed.get("chain_type", "unknown")
            chain_id = UUID(parsed.get("chain_id", "00000000-0000-0000-0000-000000000000"))
            return chain_type, chain_id
        except (json.JSONDecodeError, ValueError):
            return "unknown", UUID(int=0)

    async def repair_gap(
        self,
        chain_type: str,
        chain_id: UUID,
        gap_start: int,
        gap_end: int,
        repair_data: dict[str, Any],
        reason: str,                           # required (no default)
        created_by: UUID,                      # required (no default)
        metadata: dict | None = None,
        sign: bool = True,
    ) -> HashChainEntry | None:
        """
        Repair a gap in the chain.
        Port signature: repair_gap(chain_type, chain_id, gap_start, gap_end, repair_data,
                                   reason, created_by, metadata, sign) -> HashChainEntry | None
        """
        if hasattr(self.builder, "repair_gap"):
            raw = await self.builder.repair_gap(
                chain_type,
                chain_id,
                gap_start,
                gap_end,
                repair_data,
                reason,
                created_by,
                metadata,
                sign,
            )
            if raw and isinstance(raw, dict):
                try:
                    from ports.primary.hash_chain_service_port import HashChainEntry
                    return HashChainEntry(**raw)
                except (ImportError, TypeError):
                    return raw
            return raw
        logger = _get_logger()
        logger.warning("repair_gap not implemented in builder, stub.")
        return None

    async def sign_hash(self, hash_value: str, key_id: str | None = None) -> str:
        """
        Sign a hash using the specified key ID (optional).
        Port signature: sign_hash(hash_value, key_id=None) -> str
        """
        if hasattr(self.builder, "sign_hash"):
            return await self.builder.sign_hash(hash_value, key_id)
        logger = _get_logger()
        logger.warning("sign_hash not implemented in builder, stub.")
        return hash_value

    async def start_monitoring(self, interval_seconds: int = 3600) -> None:
        """Start monitoring the current chain."""
        if hasattr(self.builder, "start_monitoring"):
            await self.builder.start_monitoring(
                self._chain_type, self._chain_id, interval_seconds
            )
        else:
            self._monitoring_active = True
            logger = _get_logger()
            logger.info(
                f"Monitoring started for chain {self._chain_type}/{self._chain_id} (stub)"
            )

    async def stop_monitoring(self) -> None:
        """Stop monitoring the current chain."""
        if hasattr(self.builder, "stop_monitoring"):
            await self.builder.stop_monitoring(self._chain_type, self._chain_id)
        else:
            self._monitoring_active = False
            logger = _get_logger()
            logger.info(
                f"Monitoring stopped for chain {self._chain_type}/{self._chain_id} (stub)"
            )

    async def verify_all_chains(
        self,
        deep_verify: bool = True,
        check_signatures: bool = True,
    ) -> dict[ChainType, dict[UUID, IntegrityCheckResult]]:
        """
        Verify all chains. Returns a mapping of chain types to a dict of chain IDs to results.
        """
        if hasattr(self.builder, "verify_all_chains"):
            return await self.builder.verify_all_chains(deep_verify, check_signatures)
        logger = _get_logger()
        logger.warning("verify_all_chains not implemented in builder, stub.")
        return {}

    async def verify_signature(self, hash_value: str, signature: str) -> bool:
        """
        Verify a signature.
        Port signature: verify_signature(hash_value, signature) -> bool
        """
        if hasattr(self.builder, "verify_signature"):
            # Builder might expect a cert_fingerprint, but we ignore it per port.
            # We call with the two parameters and let the builder handle internally.
            return await self.builder.verify_signature(hash_value, signature)
        logger = _get_logger()
        logger.warning("verify_signature not implemented in builder, stub.")
        return False


__all__ = ["HashChainServiceAdapter"]