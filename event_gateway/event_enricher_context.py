#!/usr/bin/env python3
"""
Module: event_enricher_context.py
Layer: Event Gateway
Responsibility: Menambahkan metadata kontekstual ke event sebelum diproses.

Metode yang ditambahkan:
- Untuk EnrichmentContext: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk EventContextEnricher: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch, reset, get_stats.
"""

from __future__ import annotations

import logging
import os
import socket
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class EventEnrichmentError(Exception):
    pass


@dataclass(kw_only=True)
class EnrichmentContext:
    correlation_id: str
    causation_id: str | None = None
    user_id: str | None = None
    tenant_id: str | None = None
    legal_entity_id: str | None = None
    source_system: str | None = None
    source_ip: str | None = None
    user_agent: str | None = None
    processed_by: str | None = None
    enrichment_timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    custom_fields: dict[str, Any] = field(default_factory=dict)

    # Fields untuk audit dan versioning
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _version: int = 1

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not self.correlation_id:
            raise ValueError("correlation_id is required")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "correlation_id": self.correlation_id,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "correlation_id": self.correlation_id,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "legal_entity_id": self.legal_entity_id,
            "source_system": self.source_system,
            "source_ip": self.source_ip,
            "user_agent": self.user_agent,
            "processed_by": self.processed_by,
            "enrichment_timestamp": self.enrichment_timestamp.isoformat(),
            "custom_fields": self.custom_fields,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EnrichmentContext:
        instance = cls(
            correlation_id=data["correlation_id"],
            causation_id=data.get("causation_id"),
            user_id=data.get("user_id"),
            tenant_id=data.get("tenant_id"),
            legal_entity_id=data.get("legal_entity_id"),
            source_system=data.get("source_system"),
            source_ip=data.get("source_ip"),
            user_agent=data.get("user_agent"),
            processed_by=data.get("processed_by"),
            enrichment_timestamp=datetime.fromisoformat(data["enrichment_timestamp"]),
            custom_fields=data.get("custom_fields", {}),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> EnrichmentContext:
        new = EnrichmentContext(
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            legal_entity_id=self.legal_entity_id,
            source_system=self.source_system,
            source_ip=self.source_ip,
            user_agent=self.user_agent,
            processed_by=self.processed_by,
            enrichment_timestamp=self.enrichment_timestamp,
            custom_fields=self.custom_fields.copy(),
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "correlation_id": self.correlation_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EnrichmentContext:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


class EventContextEnricher:
    def __init__(self) -> None:
        self._enrichers: list[Callable[[dict[str, Any], EnrichmentContext], EnrichmentContext]] = []
        self._default_service_name = os.getenv("SERVICE_NAME", "accounting-engine")
        self._hostname = socket.gethostname()
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._enrichment_count = 0
        self._take_snapshot()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self._version,
                "enricher_count": len(self._enrichers),
                "enrichment_count": self._enrichment_count,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
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

    def register_enricher(self, func: Callable) -> None:
        self._enrichers.append(func)
        self._record_audit("REGISTER_ENRICHER", "system", {"function": func.__name__})
        logger.info(f"Enricher registered: {func.__name__}")

    def enrich(
        self,
        event: dict[str, Any],
        context: EnrichmentContext | None = None,
        request_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if context is None:
            context = self._build_initial_context(event, request_headers)
        for enricher in self._enrichers:
            try:
                context = enricher(event, context)
            except Exception as e:
                logger.warning(f"Enricher {enricher.__name__} gagal: {e}")
        enriched = event.copy()
        if "metadata" not in enriched:
            enriched["metadata"] = {}
        enriched["metadata"]["correlation_id"] = context.correlation_id
        enriched["metadata"]["causation_id"] = context.causation_id
        enriched["metadata"]["user_id"] = context.user_id
        enriched["metadata"]["tenant_id"] = context.tenant_id
        enriched["metadata"]["legal_entity_id"] = context.legal_entity_id
        enriched["metadata"]["source_system"] = context.source_system or self._default_service_name
        enriched["metadata"]["source_ip"] = context.source_ip
        enriched["metadata"]["user_agent"] = context.user_agent
        enriched["metadata"]["processed_by"] = context.processed_by or self._hostname
        enriched["metadata"]["enrichment_timestamp"] = context.enrichment_timestamp.isoformat()
        enriched["metadata"].update(context.custom_fields)
        enriched["correlation_id"] = context.correlation_id
        self._enrichment_count += 1
        self._record_audit("ENRICH", "system", {"correlation_id": context.correlation_id})
        return enriched

    def _build_initial_context(
        self, event: dict[str, Any], headers: dict[str, str] | None
    ) -> EnrichmentContext:
        correlation_id = (
            event.get("correlation_id")
            or (headers and headers.get("X-Correlation-ID"))
            or event.get("metadata", {}).get("correlation_id")
            or str(uuid.uuid4())
        )
        causation_id = event.get("causation_id") or event.get("metadata", {}).get("causation_id")
        user_id = (
            event.get("user_id")
            or (headers and headers.get("X-User-ID"))
            or event.get("metadata", {}).get("user_id")
        )
        tenant_id = (
            event.get("tenant_id")
            or (headers and headers.get("X-Tenant-ID"))
            or event.get("metadata", {}).get("tenant_id")
        )
        legal_entity_id = (
            event.get("legal_entity_id")
            or (headers and headers.get("X-Legal-Entity-ID"))
            or event.get("metadata", {}).get("legal_entity_id")
        )
        source_system = event.get("source") or event.get("metadata", {}).get("source_system")

        # FIX: perbaiki tipe source_ip dan user_agent agar hanya str | None
        source_ip: str | None = None
        if headers:
            source_ip = headers.get("X-Forwarded-For") or headers.get("X-Real-IP")

        user_agent: str | None = None
        if headers:
            user_agent = headers.get("User-Agent")

        return EnrichmentContext(
            correlation_id=correlation_id,
            causation_id=causation_id,
            user_id=user_id,
            tenant_id=tenant_id,
            legal_entity_id=legal_entity_id,
            source_system=source_system,
            source_ip=source_ip,
            user_agent=user_agent,
        )

    def get_stats(self) -> dict[str, Any]:
        return {
            "enricher_count": len(self._enrichers),
            "enrichment_count": self._enrichment_count,
            "version": self._version,
        }

    def reset(self) -> None:
        self._enrichers.clear()
        self._enrichment_count = 0
        self._version += 1
        self._audit_trail = []
        self._snapshots = []
        self._record_audit("RESET", "system", {})
        logger.info("EventContextEnricher reset")

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self._default_service_name:
            errors.append("default_service_name is required")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "enricher_count": len(self._enrichers),
            "enrichment_count": self._enrichment_count,
            "default_service_name": self._default_service_name,
            "hostname": self._hostname,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventContextEnricher:
        instance = cls()
        instance._version = data.get("version", 1)
        # enrichers cannot be restored from dict
        return instance

    def clone(self) -> EventContextEnricher:
        new = EventContextEnricher()
        new._default_service_name = self._default_service_name
        new._hostname = self._hostname
        new._version = self._version + 1
        # enrichers are not cloned (they are callbacks)
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "enricher_count": len(self._enrichers),
            "enrichment_count": self._enrichment_count,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EventContextEnricher:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# Built-in enrichers
def add_timestamp_enricher(event: dict[str, Any], context: EnrichmentContext) -> EnrichmentContext:
    context.custom_fields["processing_timestamp"] = datetime.now(UTC).isoformat()
    return context


def add_environment_enricher(
    event: dict[str, Any], context: EnrichmentContext
) -> EnrichmentContext:
    context.custom_fields["environment"] = os.getenv("ENV", "production")
    context.custom_fields["region"] = os.getenv("AWS_REGION", "local")
    return context


def add_trace_parent_enricher(
    event: dict[str, Any], context: EnrichmentContext
) -> EnrichmentContext:
    headers = event.get("headers", {})
    traceparent = headers.get("traceparent")
    if traceparent:
        context.custom_fields["traceparent"] = traceparent
    return context


__all__ = [
    "EnrichmentContext",
    "EventContextEnricher",
    "EventEnrichmentError",
    "add_environment_enricher",
    "add_timestamp_enricher",
    "add_trace_parent_enricher",
]
