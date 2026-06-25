#!/usr/bin/env python3
"""
Adapter: Hash Chain Service
Layer: Adapters (Secondary Implementation)

Adapter untuk layanan hash chain.
Menggunakan lazy import untuk menghindari ketergantungan langsung ke lapisan audit.
"""
from __future__ import annotations

import importlib
from typing import Any, Dict, List, Optional
from uuid import UUID

from ports.primary.hash_chain_service_port import HashChainServicePort

_logger = None


def _get_logger():
    """Lazy import structured logging."""
    global _logger
    if _logger is None:
        mod = importlib.import_module("infrastructure.telemetry.structured_json_logging")
        get_logger = getattr(mod, "get_logger")
        _logger = get_logger(__name__)
    return _logger


def _get_hash_builder():
    """Lazy import HashChainBuilder from audit.hash_chain_builder."""
    mod = importlib.import_module("audit.hash_chain_builder")
    return getattr(mod, "HashChainBuilder")


class HashChainServiceAdapter(HashChainServicePort):
    """
    Adapter yang menggunakan HashChainBuilder untuk membangun dan memverifikasi rantai hash.
    Semua import ke audit dilakukan secara lazy untuk menjaga kepatuhan arsitektur.
    """

    def __init__(self):
        self._builder = None

    @property
    def builder(self):
        """Lazy initialization of HashChainBuilder."""
        if self._builder is None:
            HashChainBuilder = _get_hash_builder()
            self._builder = HashChainBuilder()
        return self._builder

    # ===== Core methods =====

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

    # ===== Extended methods (new) =====

    async def attach_timestamp_token(
        self, chain_type: str, chain_id: UUID, entry_id: UUID, timestamp_token: str
    ) -> bool:
        if hasattr(self.builder, "attach_timestamp_token"):
            return await self.builder.attach_timestamp_token(
                chain_type, chain_id, entry_id, timestamp_token
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
        if hasattr(self.builder, "build_merkle_root"):
            return await self.builder.build_merkle_root(
                chain_type, chain_id, from_sequence, to_sequence
            )
        logger = _get_logger()
        logger.warning("build_merkle_root not implemented in builder, stub.")
        return None

    async def compute_hash(self, data: bytes | str, algorithm: str = "sha256") -> str:
        if hasattr(self.builder, "compute_hash"):
            return await self.builder.compute_hash(data, algorithm)
        import hashlib

        if isinstance(data, str):
            data = data.encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    async def compute_payload_hash(
        self, payload: dict, payload_type: str, algorithm: str = "sha256"
    ) -> str:
        if hasattr(self.builder, "compute_payload_hash"):
            return await self.builder.compute_payload_hash(payload, payload_type, algorithm)
        import json
        import hashlib

        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def detect_gaps(self, chain_type: str, chain_id: UUID) -> List[Dict[str, Any]]:
        if hasattr(self.builder, "detect_gaps"):
            return await self.builder.detect_gaps(chain_type, chain_id)
        logger = _get_logger()
        logger.warning("detect_gaps not implemented in builder, stub.")
        return []

    async def export_chain(
        self, chain_type: str, chain_id: UUID, format: str = "json"
    ) -> str:
        if hasattr(self.builder, "export_chain"):
            return await self.builder.export_chain(chain_type, chain_id, format)
        logger = _get_logger()
        logger.warning("export_chain not implemented in builder, stub.")
        return ""

    async def get_chain_length(self, chain_type: str, chain_id: UUID) -> int:
        if hasattr(self.builder, "get_chain_length"):
            return await self.builder.get_chain_length(chain_type, chain_id)
        entries = await self.get_chain_entries(chain_type, chain_id, limit=1)
        return len(entries) if entries else 0

    async def get_entry_by_hash(
        self, chain_type: str, chain_id: UUID, entry_hash: str
    ) -> Optional[Dict[str, Any]]:
        if hasattr(self.builder, "get_entry_by_hash"):
            return await self.builder.get_entry_by_hash(chain_type, chain_id, entry_hash)
        logger = _get_logger()
        logger.warning("get_entry_by_hash not implemented in builder, stub.")
        return None

    async def get_entry_by_sequence(
        self, chain_type: str, chain_id: UUID, sequence: int
    ) -> Optional[Dict[str, Any]]:
        if hasattr(self.builder, "get_entry_by_sequence"):
            return await self.builder.get_entry_by_sequence(chain_type, chain_id, sequence)
        logger = _get_logger()
        logger.warning("get_entry_by_sequence not implemented in builder, stub.")
        return None

    async def get_integrity_history(
        self, chain_type: str, chain_id: UUID, limit: int = 100
    ) -> List[Dict[str, Any]]:
        if hasattr(self.builder, "get_integrity_history"):
            return await self.builder.get_integrity_history(chain_type, chain_id, limit)
        logger = _get_logger()
        logger.warning("get_integrity_history not implemented in builder, stub.")
        return []

    async def get_statistics(
        self, chain_type: str | None = None, chain_id: UUID | None = None
    ) -> Dict[str, Any]:
        if hasattr(self.builder, "get_statistics"):
            return await self.builder.get_statistics(chain_type, chain_id)
        stats = {"total_chains": 0, "total_entries": 0}
        if chain_type and chain_id:
            stats["total_chains"] = 1
            stats["total_entries"] = await self.get_chain_length(chain_type, chain_id)
        return stats

    async def import_chain(
        self,
        chain_type: str,
        chain_id: UUID,
        data: str,
        format: str = "json",
        overwrite: bool = False,
    ) -> bool:
        if hasattr(self.builder, "import_chain"):
            return await self.builder.import_chain(
                chain_type, chain_id, data, format, overwrite
            )
        logger = _get_logger()
        logger.warning("import_chain not implemented in builder, stub.")
        return False

    async def repair_gap(
        self,
        chain_type: str,
        chain_id: UUID,
        gap_start: int,
        gap_end: int,
        repair_data: Dict[str, Any],
    ) -> bool:
        if hasattr(self.builder, "repair_gap"):
            return await self.builder.repair_gap(
                chain_type, chain_id, gap_start, gap_end, repair_data
            )
        logger = _get_logger()
        logger.warning("repair_gap not implemented in builder, stub.")
        return False

    async def sign_hash(
        self, hash_value: str, private_key: str | None = None
    ) -> str:
        if hasattr(self.builder, "sign_hash"):
            return await self.builder.sign_hash(hash_value, private_key)
        logger = _get_logger()
        logger.warning("sign_hash not implemented in builder, stub.")
        return hash_value

    async def start_monitoring(
        self, chain_type: str, chain_id: UUID, interval_seconds: int = 60
    ) -> None:
        if hasattr(self.builder, "start_monitoring"):
            await self.builder.start_monitoring(chain_type, chain_id, interval_seconds)
        else:
            logger = _get_logger()
            logger.info("start_monitoring not implemented in builder, stub.")

    async def stop_monitoring(self, chain_type: str, chain_id: UUID) -> None:
        if hasattr(self.builder, "stop_monitoring"):
            await self.builder.stop_monitoring(chain_type, chain_id)
        else:
            logger = _get_logger()
            logger.info("stop_monitoring not implemented in builder, stub.")

    async def verify_all_chains(
        self, deep_verify: bool = True, check_signatures: bool = True
    ) -> Dict[str, Any]:
        if hasattr(self.builder, "verify_all_chains"):
            return await self.builder.verify_all_chains(deep_verify, check_signatures)
        logger = _get_logger()
        logger.warning("verify_all_chains not implemented in builder, stub.")
        return {"status": "not implemented", "chains_checked": 0}

    async def verify_signature(
        self, hash_value: str, signature: str, public_key: str | None = None
    ) -> bool:
        if hasattr(self.builder, "verify_signature"):
            return await self.builder.verify_signature(hash_value, signature, public_key)
        logger = _get_logger()
        logger.warning("verify_signature not implemented in builder, stub.")
        return False


__all__ = ["HashChainServiceAdapter"]