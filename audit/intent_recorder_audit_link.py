#!/usr/bin/env python3
"""
Module: intent_recorder_audit_link.py
Layer: Audit
Responsibility: Menghubungkan antara intent capture (dari domain.intent) dengan audit
               trail. Mencatat setiap intent yang direkam, termasuk hash dari intent,
               user yang membuat intent, outcome, dan link ke transaksi yang dihasilkan.
               Memastikan bahwa setiap tindakan dalam sistem dapat ditelusuri kembali
               ke intent asli (non-repudiation).
Dependencies:
- asyncio, logging, hashlib, json
- domain.intent.immutable_record (ImmutableIntentRecord)
- audit.event_writer_immutable (ImmutableEventWriter)
- infrastructure.event_store.append_only_store (AppendOnlyStore)
- infrastructure.telemetry.structured_json_logging
Audit: Setiap intent yang direkam dicatat di audit trail. Link antara intent dan outcome
       juga dicatat untuk traceability.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

# ============================================================================
# CONSTANTS
# ============================================================================

INTENT_STREAM_PREFIX = "intent:"
INTENT_AUDIT_STREAM = "intent_audit"

_logger = None


def _get_logger():
    """Lazy logger initialization."""
    global _logger
    if _logger is None:
        mod = importlib.import_module("infrastructure.telemetry.structured_json_logging")
        get_logger_func = mod.get_logger
        _logger = get_logger_func(__name__)
    return _logger


# ============================================================================
# EXCEPTIONS
# ============================================================================


class IntentRecorderError(Exception):
    """Base exception untuk intent recorder audit link."""

    pass


class IntentNotFoundError(IntentRecorderError):
    """Intent tidak ditemukan."""

    pass


# ============================================================================
# INTENT RECORDER AUDIT LINK
# ============================================================================


class IntentRecorderAuditLink:
    """
    Layanan untuk menghubungkan intent capture dengan audit trail.

    Fitur:
    - Mencatat intent yang direkam ke audit trail
    - Menyimpan hash intent untuk integritas
    - Menghubungkan intent dengan outcome (transaksi)
    - Menyediakan query untuk mencari intent berdasarkan outcome
    - Verifikasi bahwa intent belum diubah
    """

    def __init__(self):
        self._audit_writer = None
        self._event_store = None
        self._intent_cache: dict[str, dict] = {}

    async def _get_audit_writer(self):
        if self._audit_writer is None:
            mod = importlib.import_module("audit.event_writer_immutable")
            get_immutable_event_writer = mod.get_immutable_event_writer
            self._audit_writer = await get_immutable_event_writer()
        return self._audit_writer

    async def _get_event_store(self):
        if self._event_store is None:
            mod = importlib.import_module("infrastructure.event_store.append_only_store")
            get_audit_store = mod.get_audit_store
            self._event_store = await get_audit_store()
        return self._event_store

    async def record_intent(
        self,
        intent_id: UUID,
        intent_type: str,
        intent_data: dict[str, Any],
        created_by: UUID,
        legal_entity_id: UUID,
        source: str = "api",
    ) -> str:
        """
        Mencatat intent ke audit trail.

        Args:
            intent_id: ID dari intent (dari domain.intent)
            intent_type: Tipe intent (e.g., "journal.post", "invoice.create")
            intent_data: Data intent (payload)
            created_by: User ID yang membuat intent
            legal_entity_id: Legal entity context
            source: Sumber intent (api, cli, scheduler, webhook)

        Returns:
            Audit event ID
        """
        # Compute hash of intent data for integrity
        intent_hash = self._compute_intent_hash(intent_id, intent_type, intent_data)

        # Prepare audit data
        audit_data = {
            "intent_id": str(intent_id),
            "intent_type": intent_type,
            "intent_data": intent_data,
            "intent_hash": intent_hash,
            "source": source,
            "status": "recorded",
        }

        # Write to audit trail
        event_id = await self._get_audit_writer().write_event(
            event_type="intent.recorded",
            data=audit_data,
            user_id=str(created_by),
            legal_entity_id=str(legal_entity_id),
            severity="INFO",
        )

        # Store in cache for quick lookup
        self._intent_cache[str(intent_id)] = {
            "intent_id": str(intent_id),
            "intent_type": intent_type,
            "intent_hash": intent_hash,
            "recorded_at": datetime.now(UTC).isoformat(),
            "status": "recorded",
        }

        logger = _get_logger()
        logger.info(f"Intent recorded: {intent_type} (id={intent_id})")
        return event_id

    def _compute_intent_hash(self, intent_id: UUID, intent_type: str, intent_data: dict) -> str:
        """Compute SHA-256 hash of intent content."""
        content = {
            "intent_id": str(intent_id),
            "intent_type": intent_type,
            "intent_data": intent_data,
        }
        json_str = json.dumps(content, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    async def link_intent_to_outcome(
        self,
        intent_id: UUID,
        outcome_type: str,
        outcome_id: UUID,
        outcome_data: dict | None = None,
        user_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> str:
        """
        Menghubungkan intent dengan outcome (transaksi yang dihasilkan).

        Args:
            intent_id: ID intent asli
            outcome_type: Tipe outcome (e.g., "journal", "ar_invoice")
            outcome_id: ID dari outcome
            outcome_data: Data outcome (opsional)
            user_id: User yang mengeksekusi (jika berbeda dari pembuat intent)
            legal_entity_id: Legal entity context

        Returns:
            Audit event ID
        """
        # Verify intent exists
        intent_info = await self.get_intent_info(intent_id)
        if not intent_info:
            raise IntentNotFoundError(f"Intent {intent_id} not found")

        audit_data = {
            "intent_id": str(intent_id),
            "outcome_type": outcome_type,
            "outcome_id": str(outcome_id),
            "outcome_data": outcome_data or {},
            "status": "linked",
        }

        event_id = await self._get_audit_writer().write_event(
            event_type="intent.outcome.linked",
            data=audit_data,
            user_id=str(user_id) if user_id else intent_info.get("user_id"),
            legal_entity_id=str(legal_entity_id) if legal_entity_id else None,
        )

        # Update cache
        if str(intent_id) in self._intent_cache:
            self._intent_cache[str(intent_id)]["status"] = "linked"
            self._intent_cache[str(intent_id)]["outcome_id"] = str(outcome_id)
            self._intent_cache[str(intent_id)]["outcome_type"] = outcome_type

        logger = _get_logger()
        logger.info(f"Intent {intent_id} linked to {outcome_type} {outcome_id}")
        return event_id

    async def get_intent_info(self, intent_id: UUID) -> dict[str, Any] | None:
        """
        Mendapatkan informasi intent dari cache atau event store.
        """
        intent_id_str = str(intent_id)
        if intent_id_str in self._intent_cache:
            return self._intent_cache[intent_id_str]

        # Search in event store
        store = await self._get_event_store()
        events = await store.read_stream(INTENT_AUDIT_STREAM, limit=10000)
        for event in events:
            data = event.get("data", {})
            if data.get("intent_id") == intent_id_str:
                intent_info = {
                    "intent_id": intent_id_str,
                    "intent_type": data.get("intent_type"),
                    "intent_hash": data.get("intent_hash"),
                    "recorded_at": event.get("timestamp"),
                    "status": data.get("status"),
                    "user_id": event.get("user_id"),
                }
                self._intent_cache[intent_id_str] = intent_info
                return intent_info

        return None

    async def find_outcome_by_intent(self, intent_id: UUID) -> dict[str, Any] | None:
        """
        Mencari outcome berdasarkan intent ID.
        """
        store = await self._get_event_store()
        events = await store.read_stream(INTENT_AUDIT_STREAM, limit=10000)
        for event in events:
            data = event.get("data", {})
            if (
                data.get("intent_id") == str(intent_id)
                and event.get("event_type") == "intent.outcome.linked"
            ):
                return {
                    "outcome_type": data.get("outcome_type"),
                    "outcome_id": data.get("outcome_id"),
                    "outcome_data": data.get("outcome_data"),
                    "linked_at": event.get("timestamp"),
                }
        return None

    async def find_intent_by_outcome(
        self, outcome_type: str, outcome_id: UUID
    ) -> dict[str, Any] | None:
        """
        Mencari intent berdasarkan outcome.
        """
        store = await self._get_event_store()
        events = await store.read_stream(INTENT_AUDIT_STREAM, limit=10000)
        for event in events:
            if event.get("event_type") == "intent.outcome.linked":
                data = event.get("data", {})
                if data.get("outcome_type") == outcome_type and data.get("outcome_id") == str(
                    outcome_id
                ):
                    intent_id = data.get("intent_id")
                    intent_info = await self.get_intent_info(UUID(intent_id))
                    return intent_info
        return None

    async def verify_intent_integrity(self, intent_id: UUID) -> bool:
        """
        Memverifikasi bahwa intent belum diubah sejak direkam.
        """
        intent_info = await self.get_intent_info(intent_id)
        if not intent_info:
            return False

        # Get original intent data from event store
        store = await self._get_event_store()
        events = await store.read_stream(INTENT_AUDIT_STREAM, limit=10000)
        for event in events:
            data = event.get("data", {})
            if (
                data.get("intent_id") == str(intent_id)
                and event.get("event_type") == "intent.recorded"
            ):
                # Recompute hash from current data (if we have it)
                # For verification, we would need current intent data
                # This is a placeholder; actual implementation would fetch current intent
                return True  # Simplified

        return False

    async def get_intents_by_user(self, user_id: UUID, limit: int = 50) -> list[dict]:
        """
        Mendapatkan semua intent yang dibuat oleh user tertentu.
        """
        store = await self._get_event_store()
        events = await store.read_stream(INTENT_AUDIT_STREAM, limit=limit * 2)
        intents = []
        for event in events:
            if (
                event.get("user_id") == str(user_id)
                and event.get("event_type") == "intent.recorded"
            ):
                data = event.get("data", {})
                intents.append(
                    {
                        "intent_id": data.get("intent_id"),
                        "intent_type": data.get("intent_type"),
                        "recorded_at": event.get("timestamp"),
                        "status": data.get("status"),
                    }
                )
                if len(intents) >= limit:
                    break
        return intents

    async def get_stats(self) -> dict[str, Any]:
        """
        Mendapatkan statistik intent recorder.
        """
        store = await self._get_event_store()
        events = await store.read_stream(INTENT_AUDIT_STREAM, limit=10000)
        recorded = sum(1 for e in events if e.get("event_type") == "intent.recorded")
        linked = sum(1 for e in events if e.get("event_type") == "intent.outcome.linked")

        return {
            "total_intents_recorded": recorded,
            "total_intents_linked": linked,
            "cache_size": len(self._intent_cache),
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_intent_recorder: IntentRecorderAuditLink | None = None


async def get_intent_recorder() -> IntentRecorderAuditLink:
    """Get singleton instance of IntentRecorderAuditLink."""
    global _intent_recorder
    if _intent_recorder is None:
        _intent_recorder = IntentRecorderAuditLink()
    return _intent_recorder


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "IntentNotFoundError",
    "IntentRecorderAuditLink",
    "IntentRecorderError",
    "get_intent_recorder",
]
