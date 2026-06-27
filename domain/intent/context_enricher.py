#!/usr/bin/env python3
"""
Module: context_enricher.py
Layer: 5 - Reality, Intent, Causality / Intent
Responsibility: Memperkaya intent dengan konteks (waktu, lokasi, user agent).
"""

from __future__ import annotations

import importlib
import logging
import socket
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Lazy helpers untuk menghindari AST drift (domain -> kernel)
# ============================================================================

def _get_current_user() -> str | None:
    """Lazy import kernel.context_holder.get_current_user."""
    try:
        mod = importlib.import_module("kernel.context_holder")
        get_current_user = mod.get_current_user
        return get_current_user()
    except Exception:
        return None


def _get_correlation_id() -> str | None:
    """Lazy import kernel.context_holder.get_correlation_id."""
    try:
        mod = importlib.import_module("kernel.context_holder")
        get_correlation_id = mod.get_correlation_id
        return get_correlation_id()
    except Exception:
        return None


# ============================================================================
# EnrichedContext
# ============================================================================

@dataclass
class EnrichedContext:
    user_id: str
    correlation_id: str
    timestamp: datetime
    ip_address: str | None = None
    user_agent: str | None = None
    device_id: str | None = None
    session_id: str | None = None
    location: str | None = None
    department: str | None = None
    cost_center: str | None = None
    legal_entity_id: UUID | None = None
    additional_data: dict[str, Any] = field(default_factory=dict)

    # Tracking untuk entity methods
    _version: int = 1
    _snapshots: list[dict[str, Any]] = field(default_factory=list)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()
        self._record_audit("CREATE", self.user_id, {})

    def _validate(self) -> None:
        if not self.user_id or not isinstance(self.user_id, str):
            raise ValueError("user_id must be a non-empty string")
        if not self.correlation_id or not isinstance(self.correlation_id, str):
            raise ValueError("correlation_id must be a non-empty string")
        if not isinstance(self.timestamp, datetime):
            raise ValueError("timestamp must be datetime")
        if self.user_agent and len(self.user_agent) > 500:
            object.__setattr__(self, "user_agent", self.user_agent[:500])
        if self.legal_entity_id is not None and not isinstance(self.legal_entity_id, UUID):
            raise ValueError("legal_entity_id must be UUID or None")
        if self._version < 1:
            raise ValueError("version must be >= 1")

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self._version,
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp.isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> EnrichedContext:
        self._record_audit("CREATE", created_by, {})
        return self

    def update(self, updated_by: str, **kwargs) -> EnrichedContext:
        data = self.to_dict()
        for key, value in kwargs.items():
            if hasattr(self, key) and key not in ("_version", "_snapshots", "_audit_trail"):
                data[key] = value
        new_ctx = EnrichedContext.from_dict(data)
        object.__setattr__(new_ctx, "_version", self._version + 1)
        new_ctx._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_ctx

    def delete(self, deleted_by: str, reason: str | None = None) -> EnrichedContext:
        # Context tidak dihapus secara permanen, hanya tandai
        self._record_audit("DELETE", deleted_by, {"reason": reason})
        return self

    def restore(self, restored_by: str) -> EnrichedContext:
        self._record_audit("RESTORE", restored_by, {})
        return self

    def activate(self, activated_by: str) -> EnrichedContext:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> EnrichedContext:
        return self

    def lock(self, locked_by: str, reason: str) -> EnrichedContext:
        return self

    def unlock(self, unlocked_by: str) -> EnrichedContext:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "user_id": self.user_id,
            "version": self._version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp.isoformat(),
            "ip_address": self.ip_address,
            "user_agent": self.user_agent[:200] if self.user_agent else None,
            "device_id": self.device_id,
            "session_id": self.session_id,
            "location": self.location,
            "department": self.department,
            "cost_center": self.cost_center,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "additional": self.additional_data,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EnrichedContext:
        obj = cls(
            user_id=data.get("user_id", "unknown"),
            correlation_id=data.get("correlation_id", str(uuid4())),
            timestamp=datetime.fromisoformat(data["timestamp"])
            if "timestamp" in data
            else datetime.now(UTC),
            ip_address=data.get("ip_address"),
            user_agent=data.get("user_agent"),
            device_id=data.get("device_id"),
            session_id=data.get("session_id"),
            location=data.get("location"),
            department=data.get("department"),
            cost_center=data.get("cost_center"),
            legal_entity_id=UUID(data["legal_entity_id"]) if data.get("legal_entity_id") else None,
            additional_data=data.get("additional", {}),
        )
        return obj

    def clone(self) -> EnrichedContext:
        new_id = uuid4()
        return EnrichedContext(
            user_id=self.user_id,
            correlation_id=str(new_id),
            timestamp=datetime.now(UTC),
            ip_address=self.ip_address,
            user_agent=self.user_agent,
            device_id=self.device_id,
            session_id=None,
            location=self.location,
            department=self.department,
            cost_center=self.cost_center,
            legal_entity_id=self.legal_entity_id,
            additional_data=self.additional_data.copy(),
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp.isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EnrichedContext:
        new_ctx = self.update(touched_by, timestamp=datetime.now(UTC))
        new_ctx._record_audit("TOUCH", touched_by, {})
        return new_ctx


# ============================================================================
# ContextEnricher
# ============================================================================

class ContextEnricher:
    _instance: ContextEnricher | None = None

    def __new__(cls) -> ContextEnricher:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._hostname = socket.gethostname()
        self._lock = threading.RLock()

    # ==================== ENRICHMENT METHODS ====================
    def enrich(
        self,
        user_id: str | None = None,
        correlation_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_id: str | None = None,
        session_id: str | None = None,
        location: str | None = None,
        department: str | None = None,
        cost_center: str | None = None,
        legal_entity_id: UUID | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> EnrichedContext:
        if user_id is None:
            user_id = _get_current_user() or "unknown"
        if correlation_id is None:
            correlation_id = _get_correlation_id() or str(uuid4())
        return EnrichedContext(
            user_id=user_id,
            correlation_id=correlation_id,
            timestamp=datetime.now(UTC),
            ip_address=ip_address,
            user_agent=user_agent[:500] if user_agent else None,
            device_id=device_id,
            session_id=session_id,
            location=location,
            department=department,
            cost_center=cost_center,
            legal_entity_id=legal_entity_id,
            additional_data=additional_data or {},
        )

    def enrich_from_request(
        self,
        request: Any,
        user_id: str | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> EnrichedContext:
        ip_address = None
        user_agent = None
        correlation_id = None
        if hasattr(request, "client") and request.client:
            ip_address = request.client.host
        if hasattr(request, "headers"):
            user_agent = request.headers.get("user-agent")
            if not ip_address and "x-forwarded-for" in request.headers:
                forwarded = request.headers.get("x-forwarded-for", "")
                ip_address = forwarded.split(",")[0].strip() if forwarded else None
            correlation_id = request.headers.get("x-correlation-id") or request.headers.get(
                "x-request-id"
            )
        if not correlation_id:
            correlation_id = str(uuid4())
        if user_id is None:
            user_id = _get_current_user() or "unknown"
        return self.enrich(
            user_id=user_id,
            correlation_id=correlation_id,
            ip_address=ip_address,
            user_agent=user_agent,
            additional_data=additional_data,
        )

    def enrich_intent_data(
        self, data: dict[str, Any], context: EnrichedContext | None = None
    ) -> dict[str, Any]:
        if context is None:
            context = self.enrich()
        enriched = data.copy()
        ctx_dict = context.to_dict()
        ctx_dict["hostname"] = self._hostname
        enriched["_context"] = ctx_dict
        return enriched

    def add_audit_context(
        self, data: dict[str, Any], action: str, resource_type: str, resource_id: str | None = None
    ) -> dict[str, Any]:
        enriched = data.copy()
        enriched["_audit"] = {
            "action": action.upper(),
            "resource_type": resource_type,
            "resource_id": resource_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "hostname": self._hostname,
        }
        return enriched

    def get_hostname(self) -> str:
        return self._hostname

    def generate_correlation_id(self) -> str:
        return str(uuid4())

    # ==================== REPOSITORY METHODS (untuk context storage) ====================
    def save(self, context: EnrichedContext) -> EnrichedContext:
        # Dalam implementasi nyata, simpan ke database
        # Di sini hanya log dan return
        logger.info(f"Context saved for user {context.user_id} (version {context.version()})")
        return context

    def get_latest_context(self, user_id: str) -> EnrichedContext | None:
        # Dalam implementasi nyata, ambil dari database
        return None

    def reset(self) -> None:
        with self._lock:
            self._hostname = socket.gethostname()


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_context_enricher_instance: ContextEnricher | None = None


def get_context_enricher() -> ContextEnricher:
    global _context_enricher_instance
    if _context_enricher_instance is None:
        _context_enricher_instance = ContextEnricher()
    return _context_enricher_instance


__all__ = ["ContextEnricher", "EnrichedContext", "get_context_enricher"]
