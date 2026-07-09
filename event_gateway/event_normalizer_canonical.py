#!/usr/bin/env python3
"""
Module: event_normalizer_canonical.py
Layer: Event Gateway
Responsibility: Menormalisasi event ke format kanonik.

Metode yang ditambahkan:
- Untuk CanonicalEvent: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk EventNormalizer: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch, reset.

Perbaikan presisi:
    - Menggunakan string (bukan float) untuk representasi nilai moneter (Money.amount, Decimal)
      agar tidak kehilangan presisi dan memenuhi aturan MNY-003.
"""

from __future__ import annotations

import copy
import logging
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from domain.shared_value_objects.money_vo import Money
from event_gateway.event_envelope import EventEnvelope

logger = logging.getLogger(__name__)

SENSITIVE_FIELD_PATTERNS = [
    r"(?i)password",
    r"(?i)secret",
    r"(?i)token",
    r"(?i)api[-_]?key",
    r"(?i)private[-_]?key",
    r"(?i)credit[-_]?card",
    r"(?i)ssn",
    r"(?i)tax[-_]?id",
    r"(?i)npwp",
    r"(?i)bank[-_]?account",
    r"(?i)routing[-_]?number",
]

REQUIRED_METADATA_FIELDS = [
    "event_id",
    "event_type",
    "event_version",
    "aggregate_id",
    "aggregate_type",
    "occurred_at",
    "correlation_id",
    "causation_id",
]


class CanonicalEvent:
    __slots__ = (
        "_audit_trail",
        "_snapshots",
        "_version",
        "aggregate_id",
        "aggregate_type",
        "causation_id",
        "correlation_id",
        "event_id",
        "event_type",
        "event_version",
        "metadata",
        "occurred_at",
        "payload",
    )

    # ==================== FIX: Parameter order - required first, then optional ====================
    def __init__(
        self,
        event_id: str,
        event_type: str,
        aggregate_type: str,  # required (moved before optional)
        occurred_at: str,
        correlation_id: str,
        causation_id: str | None,
        payload: dict[str, Any],
        metadata: dict[str, Any],
        event_version: int = 1,  # optional with default
        aggregate_id: str | None = None,  # optional with default
    ):
        self.event_id = event_id
        self.event_type = event_type
        self.event_version = event_version
        self.aggregate_id = aggregate_id
        self.aggregate_type = aggregate_type
        self.occurred_at = occurred_at
        self.correlation_id = correlation_id
        self.causation_id = causation_id
        self.payload = payload
        self.metadata = metadata
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not self.event_id:
            raise ValueError("event_id is required")
        if not self.event_type:
            raise ValueError("event_type is required")
        if not self.aggregate_type:
            raise ValueError("aggregate_type is required")
        if self.event_version < 1:
            raise ValueError("event_version must be >= 1")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "event_id": self.event_id,
                "event_type": self.event_type,
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
                "event_id": self.event_id,
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
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event_version": self.event_version,
            "aggregate_id": self.aggregate_id,
            "aggregate_type": self.aggregate_type,
            "occurred_at": self.occurred_at,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "payload": self.payload,
            "metadata": self.metadata,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CanonicalEvent:
        instance = cls(
            event_id=data["event_id"],
            event_type=data["event_type"],
            aggregate_type=data["aggregate_type"],
            occurred_at=data["occurred_at"],
            correlation_id=data["correlation_id"],
            causation_id=data.get("causation_id"),
            payload=data.get("payload", {}),
            metadata=data.get("metadata", {}),
            event_version=data.get("event_version", 1),
            aggregate_id=data.get("aggregate_id"),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> CanonicalEvent:
        import uuid

        new_id = str(uuid.uuid4())
        cloned = CanonicalEvent(
            event_id=new_id,
            event_type=self.event_type,
            aggregate_type=self.aggregate_type,
            occurred_at=self.occurred_at,
            correlation_id=str(uuid.uuid4()),
            causation_id=self.event_id,
            payload=self.payload.copy(),
            metadata=self.metadata.copy(),
            event_version=self.event_version,
            aggregate_id=self.aggregate_id,
        )
        cloned._version = self._version + 1
        cloned._record_audit("CLONE", "system", {"source": self.event_id})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CanonicalEvent:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


class EventNormalizer:
    def __init__(self):
        self._conversion_counter = 0
        self._field_mappings: dict[str, dict[str, str]] = {}
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "conversion_counter": self._conversion_counter,
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
                "details": details,
            }
        )

    def _to_snake_case(self, name: str) -> str:
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        s2 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1)
        return s2.lower()

    def _normalize_keys(self, obj: Any, convert_to_snake: bool = True) -> Any:
        if isinstance(obj, dict):
            new_dict = {}
            for key, value in obj.items():
                new_key = self._to_snake_case(key) if convert_to_snake else key
                new_dict[new_key] = self._normalize_keys(value, convert_to_snake)
            return new_dict
        elif isinstance(obj, list):
            return [self._normalize_keys(item, convert_to_snake) for item in obj]
        else:
            return obj

    def _convert_value_types(self, value: Any) -> Any:
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Money):
            # Gunakan string untuk amount agar presisi tetap terjaga
            return {"amount": str(value.amount), "currency": value.currency}
        if isinstance(value, Decimal):
            # Konversi Decimal ke string untuk menghindari float
            return str(value)
        if isinstance(value, dict):
            return {k: self._convert_value_types(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._convert_value_types(item) for item in value]
        return value

    def _mask_sensitive_fields(self, obj: Any, depth: int = 0) -> Any:
        if depth > 10:
            return obj
        if isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                is_sensitive = any(re.match(pattern, key) for pattern in SENSITIVE_FIELD_PATTERNS)
                if is_sensitive and value:
                    result[key] = "***REDACTED***"
                else:
                    result[key] = self._mask_sensitive_fields(value, depth + 1)
            return result
        elif isinstance(obj, list):
            return [self._mask_sensitive_fields(item, depth + 1) for item in obj]
        else:
            return obj

    async def normalize(self, envelope: EventEnvelope) -> CanonicalEvent:
        payload = copy.deepcopy(envelope.payload)
        payload = self._normalize_keys(payload)
        payload = self._convert_value_types(payload)
        payload = self._mask_sensitive_fields(payload)

        metadata = copy.deepcopy(envelope.metadata)
        metadata = self._normalize_keys(metadata)
        metadata = self._convert_value_types(metadata)

        canonical = CanonicalEvent(
            event_id=str(envelope.id),
            event_type=envelope.event_type,
            aggregate_type=envelope.aggregate_type,
            occurred_at=envelope.occurred_at.isoformat(),
            correlation_id=envelope.correlation_id,
            causation_id=envelope.causation_id,
            payload=payload,
            metadata=metadata,
            event_version=envelope.event_version,
            aggregate_id=str(envelope.aggregate_id) if envelope.aggregate_id else None,
        )
        self._conversion_counter += 1
        self._record_audit("NORMALIZE", "system", {"event_type": envelope.event_type})
        logger.debug(f"Normalized event {envelope.event_type} (count: {self._conversion_counter})")
        return canonical

    async def normalize_raw_event(
        self, raw_event: dict[str, Any], event_type: str | None = None
    ) -> dict[str, Any]:
        normalized = self._normalize_keys(raw_event)
        normalized = self._convert_value_types(normalized)
        normalized = self._mask_sensitive_fields(normalized)
        if event_type:
            normalized["event_type"] = event_type
        if "occurred_at" not in normalized:
            normalized["occurred_at"] = datetime.now(UTC).isoformat()
        if "correlation_id" not in normalized:
            from uuid import uuid4

            normalized["correlation_id"] = str(uuid4())
        return normalized

    async def add_field_mapping(self, source_format: str, mapping: dict[str, str]) -> None:
        self._field_mappings[source_format] = mapping
        self._record_audit("ADD_FIELD_MAPPING", "system", {"source_format": source_format})
        logger.info(f"Field mapping added for source format: {source_format}")

    async def normalize_from_format(
        self, raw_event: dict[str, Any], source_format: str, event_type: str
    ) -> dict[str, Any]:
        mapping = self._field_mappings.get(source_format, {})
        normalized = {}
        for source_field, canonical_field in mapping.items():
            if source_field in raw_event:
                normalized[canonical_field] = raw_event[source_field]
        for key, value in raw_event.items():
            if key not in mapping:
                normalized[key] = value
        return await self.normalize_raw_event(normalized, event_type)

    async def get_stats(self) -> dict[str, Any]:
        return {
            "total_normalized": self._conversion_counter,
            "field_mappings_count": len(self._field_mappings),
            "sensitive_patterns_count": len(SENSITIVE_FIELD_PATTERNS),
            "version": self._version,
        }

    def reset(self) -> None:
        self._conversion_counter = 0
        self._field_mappings.clear()
        self._version += 1
        self._audit_trail = []
        self._snapshots = []
        self._record_audit("RESET", "system", {})

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversion_counter": self._conversion_counter,
            "field_mappings_count": len(self._field_mappings),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventNormalizer:
        instance = cls()
        instance._conversion_counter = data.get("conversion_counter", 0)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> EventNormalizer:
        new = EventNormalizer()
        new._conversion_counter = self._conversion_counter
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "conversion_counter": self._conversion_counter,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EventNormalizer:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


def is_canonical(event: dict[str, Any]) -> bool:
    return all(field in event for field in REQUIRED_METADATA_FIELDS)


def extract_metadata(event: dict[str, Any]) -> dict[str, Any]:
    return {field: event[field] for field in REQUIRED_METADATA_FIELDS if field in event}


def extract_payload(event: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in event.items() if k not in REQUIRED_METADATA_FIELDS}


__all__ = [
    "CanonicalEvent",
    "EventNormalizer",
    "extract_metadata",
    "extract_payload",
    "is_canonical",
]