#!/usr/bin/env python3
"""
Adapter: Hash Chain Service
Layer: Adapters (Secondary Implementation)

Adapter untuk layanan hash chain menggunakan HashChainBuilder.
"""
from __future__ import annotations

from uuid import UUID

from audit.hash_chain_builder import HashChainBuilder
from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.hash_chain_service_port import HashChainServicePort

logger = get_logger(__name__)

class HashChainServiceAdapter(HashChainServicePort):
    """
    Adapter yang menggunakan HashChainBuilder untuk membangun dan memverifikasi rantai hash.
    """
    def __init__(self):
        self.builder = HashChainBuilder()

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
            chain_type, chain_id, payload, payload_type,
            payload_ref_id, created_by, metadata, sign, timestamp_token
        )

    async def verify_chain(self, chain_type: str, chain_id: UUID, deep_verify: bool = True, check_signatures: bool = True):
        return await self.builder.verify_chain(chain_type, chain_id, deep_verify, check_signatures)

    async def get_last_hash(self, chain_type: str, chain_id: UUID) -> str | None:
        return await self.builder.get_last_hash(chain_type, chain_id)

    async def get_chain_entries(self, chain_type: str, chain_id: UUID, limit: int = 1000, offset: int = 0):
        return await self.builder.get_chain_entries(chain_type, chain_id, limit, offset)

    async def health_check(self) -> dict:
        return await self.builder.health_check()

__all__ = ["HashChainServiceAdapter"]
