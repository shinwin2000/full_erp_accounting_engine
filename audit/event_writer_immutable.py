#!/usr/bin/env python3
"""
Module: event_writer_immutable.py
Layer: Audit
Responsibility: Menulis event audit secara immutable ke event store.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from audit.event_types_catalog import (
    AuditEventType,
    AuditSeverity,
    EventMetadataSchema,
    EventTypeCatalog,
)
from audit.hash_chain_builder import GENESIS_HASH, AuditHashChainBuilder, get_audit_hash_builder

# ============================================================================
# CONSTANTS
# ============================================================================

AUDIT_STREAM_NAME = "audit"
SECURITY_AUDIT_STREAM = "security_audit"

_logger = None


def _get_logger():
    """Lazy logger initialization from structured logging."""
    global _logger
    if _logger is None:
        mod = importlib.import_module("infrastructure.telemetry.structured_json_logging")
        get_logger_func = getattr(mod, "get_logger")
        _logger = get_logger_func(__name__)
    return _logger


def _get_current_correlation_id() -> str | None:
    """Lazy import correlation_id_injector and get current correlation id."""
    try:
        mod = importlib.import_module("infrastructure.telemetry.correlation_id_injector")
        get_correlation_id = getattr(mod, "get_current_correlation_id")
        return get_correlation_id()
    except Exception:
        return None


# ============================================================================
# EXCEPTIONS
# ============================================================================


class ImmutableEventWriterError(Exception):
    pass


class InvalidEventTypeError(ImmutableEventWriterError):
    pass


class MissingRequiredFieldError(ImmutableEventWriterError):
    pass


# ============================================================================
# IMMUTABLE EVENT WRITER
# ============================================================================


class ImmutableEventWriter:
    def __init__(self):
        self._store = None
        self._hash_builder = None
        self._write_count = 0

    async def _get_store(self):
        if self._store is None:
            mod = importlib.import_module("infrastructure.event_store.append_only_store")
            get_audit_store = getattr(mod, "get_audit_store")
            self._store = await get_audit_store()
        return self._store

    async def _get_hash_builder(self) -> AuditHashChainBuilder:
        if self._hash_builder is None:
            self._hash_builder = get_audit_hash_builder()
        return self._hash_builder

    async def _get_last_hash(self, stream_name: str) -> str:
        store = await self._get_store()
        last_event = await store.get_last_event(stream_name)
        if last_event and "hash" in last_event:
            return last_event["hash"]
        return GENESIS_HASH

    def _validate_event(self, event_type: str, data: dict[str, Any]) -> None:
        if not EventTypeCatalog.is_valid_type(event_type):
            raise InvalidEventTypeError(f"Invalid event type: {event_type}")
        schema = EventMetadataSchema.get_schema(event_type)
        required_fields = schema.get("required_fields", [])
        missing = [f for f in required_fields if f not in data]
        if missing:
            raise MissingRequiredFieldError(f"Missing required fields: {missing}")

    def _get_stream_name(self, event_type: str) -> str:
        if (
            event_type.startswith("security.")
            or event_type.startswith("auth.")
            or event_type.startswith("access.")
        ):
            return SECURITY_AUDIT_STREAM
        return AUDIT_STREAM_NAME

    def _build_event_record(
        self,
        event_type: str,
        data: dict[str, Any],
        severity: str,
        user_id: str | None = None,
        legal_entity_id: str | None = None,
        previous_hash: str = GENESIS_HASH,
    ) -> dict[str, Any]:
        event_id = str(uuid.uuid4())
        timestamp = datetime.now(UTC)
        correlation_id = _get_current_correlation_id() or str(uuid.uuid4())
        enriched_data = data.copy()
        if "timestamp" not in enriched_data:
            enriched_data["timestamp"] = timestamp.isoformat()
        if "correlation_id" not in enriched_data:
            enriched_data["correlation_id"] = correlation_id

        record = {
            "id": event_id,
            "event_type": event_type,
            "severity": severity,
            "data": enriched_data,
            "user_id": user_id,
            "legal_entity_id": legal_entity_id,
            "timestamp": timestamp.isoformat(),
            "correlation_id": correlation_id,
            "previous_hash": previous_hash,
            "hash": None,
        }
        record["hash"] = self._compute_hash(record)
        return record

    def _compute_hash(self, record: dict[str, Any]) -> str:
        content = {
            "id": record["id"],
            "event_type": record["event_type"],
            "severity": record["severity"],
            "data": record["data"],
            "user_id": record["user_id"],
            "legal_entity_id": record["legal_entity_id"],
            "timestamp": record["timestamp"],
            "correlation_id": record["correlation_id"],
            "previous_hash": record["previous_hash"],
        }
        json_str = json.dumps(content, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    async def write_event(
        self,
        event_type: str,
        data: dict[str, Any],
        severity: str | None = None,
        user_id: str | None = None,
        legal_entity_id: str | None = None,
    ) -> str:
        self._validate_event(event_type, data)
        if severity is None:
            severity = EventTypeCatalog.get_default_severity(event_type)
        stream_name = self._get_stream_name(event_type)
        last_hash = await self._get_last_hash(stream_name)
        record = self._build_event_record(
            event_type=event_type,
            data=data,
            severity=severity,
            user_id=user_id,
            legal_entity_id=legal_entity_id,
            previous_hash=last_hash,
        )
        store = await self._get_store()
        event_id = await store.append(
            stream_name=stream_name,
            event_data=record,
            event_type="audit.event",
            metadata={"original_event_type": event_type},
        )
        self._write_count += 1
        logger = _get_logger()
        logger.debug(f"Audit event written: {event_type} (id={event_id})")
        if stream_name == SECURITY_AUDIT_STREAM:
            security_logger = logging.getLogger("security")
            security_logger.info(f"Security event: {event_type}", extra={"audit_id": str(event_id)})
        return str(event_id)

    async def write_security_event(
        self,
        event_type: str,
        data: dict[str, Any],
        user_id: str | None = None,
        legal_entity_id: str | None = None,
    ) -> str:
        return await self.write_event(
            event_type,
            data,
            severity=AuditSeverity.WARNING,
            user_id=user_id,
            legal_entity_id=legal_entity_id,
        )

    async def write_critical_event(
        self,
        event_type: str,
        data: dict[str, Any],
        user_id: str | None = None,
        legal_entity_id: str | None = None,
    ) -> str:
        return await self.write_event(
            event_type,
            data,
            severity=AuditSeverity.CRITICAL,
            user_id=user_id,
            legal_entity_id=legal_entity_id,
        )

    async def write_data_change(
        self,
        action: str,
        target_type: str,
        target_id: str,
        old_value: dict | None = None,
        new_value: dict | None = None,
        user_id: str | None = None,
        legal_entity_id: str | None = None,
    ) -> str:
        event_type_map = {
            "CREATE": AuditEventType.DATA_CREATE,
            "UPDATE": AuditEventType.DATA_UPDATE,
            "DELETE": AuditEventType.DATA_DELETE,
        }
        event_type = event_type_map.get(action.upper(), AuditEventType.DATA_CHANGE)
        data = {"target_type": target_type, "target_id": target_id, "action": action.upper()}
        if old_value:
            data["old_value"] = old_value
        if new_value:
            data["new_value"] = new_value
        return await self.write_event(
            event_type, data, user_id=user_id, legal_entity_id=legal_entity_id
        )

    async def write_login_event(
        self,
        username: str,
        success: bool,
        ip_address: str | None = None,
        user_agent: str | None = None,
        user_id: str | None = None,
        legal_entity_id: str | None = None,
    ) -> str:
        event_type = (
            AuditEventType.AUTH_LOGIN_SUCCESS if success else AuditEventType.AUTH_LOGIN_FAILURE
        )
        data = {"username": username, "ip_address": ip_address, "user_agent": user_agent}
        if not success:
            data["reason"] = "Invalid credentials"
        return await self.write_event(
            event_type, data, user_id=user_id, legal_entity_id=legal_entity_id
        )

    async def write_permission_denied(
        self,
        user_id: str,
        resource: str,
        action: str,
        required_permission: str,
        ip_address: str | None = None,
        legal_entity_id: str | None = None,
    ) -> str:
        data = {
            "resource": resource,
            "action": action,
            "required_permission": required_permission,
            "ip_address": ip_address,
        }
        return await self.write_event(
            AuditEventType.ACCESS_PERMISSION_DENIED,
            data,
            user_id=user_id,
            legal_entity_id=legal_entity_id,
            severity=AuditSeverity.WARNING,
        )

    async def write_config_change(
        self,
        config_key: str,
        old_value: Any,
        new_value: Any,
        changed_by: str | None = None,
        legal_entity_id: str | None = None,
    ) -> str:
        data = {
            "config_key": config_key,
            "old_value": str(old_value),
            "new_value": str(new_value),
            "changed_by": changed_by,
        }
        return await self.write_event(
            AuditEventType.CONFIG_CHANGE,
            data,
            user_id=changed_by,
            legal_entity_id=legal_entity_id,
            severity=AuditSeverity.WARNING,
        )

    async def write_period_close(
        self,
        fiscal_year: int,
        period: int,
        status: str,
        closed_by: str | None = None,
        legal_entity_id: str | None = None,
    ) -> str:
        data = {
            "fiscal_year": fiscal_year,
            "period": period,
            "status": status,
            "closed_by": closed_by,
        }
        return await self.write_event(
            AuditEventType.PERIOD_CLOSED, data, user_id=closed_by, legal_entity_id=legal_entity_id
        )

    async def write_journal_posted(
        self,
        journal_id: str,
        voucher_number: str,
        total_amount: Decimal,
        lines_count: int,
        posted_by: str | None = None,
        legal_entity_id: str | None = None,
    ) -> str:
        data = {
            "journal_id": journal_id,
            "voucher_number": voucher_number,
            "total_amount": total_amount,
            "lines_count": lines_count,
        }
        return await self.write_event(
            AuditEventType.JOURNAL_POSTED, data, user_id=posted_by, legal_entity_id=legal_entity_id
        )

    async def get_stats(self) -> dict[str, Any]:
        return {
            "total_events_written": self._write_count,
            "streams": {"audit": AUDIT_STREAM_NAME, "security": SECURITY_AUDIT_STREAM},
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_immutable_event_writer: ImmutableEventWriter | None = None


async def get_immutable_event_writer() -> ImmutableEventWriter:
    global _immutable_event_writer
    if _immutable_event_writer is None:
        _immutable_event_writer = ImmutableEventWriter()
    return _immutable_event_writer


# ============================================================================
# DECORATOR
# ============================================================================

def audit_log(event_type: str):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            writer = await get_immutable_event_writer()
            user_id = kwargs.get("user_id")
            result = await func(*args, **kwargs)
            await writer.write_event(
                event_type=event_type,
                data={
                    "function": func.__name__,
                    "args": str(args)[:200],
                    "kwargs": {k: str(v)[:100] for k, v in kwargs.items()},
                    "result": str(result)[:200] if result else None,
                },
                user_id=user_id,
            )
            return result

        return wrapper

    return decorator


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "ImmutableEventWriter",
    "ImmutableEventWriterError",
    "InvalidEventTypeError",
    "MissingRequiredFieldError",
    "audit_log",
    "get_immutable_event_writer",
]