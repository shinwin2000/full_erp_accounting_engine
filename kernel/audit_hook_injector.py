#!/usr/bin/env python3
"""
Module: audit_hook_injector.py
Layer: 4 - Kernel / Audit Hook Injector
Responsibility: Menyuntikkan hook audit ke setiap transaksi.
               Mencatat semua operasi sebelum dan sesudah eksekusi,
               termasuk data state before/after, user identity, timestamp,
               dan hasil eksekusi. Hook ini memastikan audit trail lengkap.

Metode yang ditambahkan:
- validate(), to_dict(), from_dict(), clone(), snapshot(), version(), audit_trail(), touch()
- get_statistics(), reset(), shutdown()
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from kernel.command_envelope import CommandEnvelope

logger = logging.getLogger(__name__)

# ============================================================================
# FALLBACK EVENT STORE (IN-MEMORY)
# ============================================================================


class _FallbackAuditEvent:
    def __init__(
        self, event_id, aggregate_id, event_type, version, data, metadata, user_id, timestamp
    ):
        self.event_id = event_id
        self.aggregate_id = aggregate_id
        self.event_type = event_type
        self.version = version
        self.data = data
        self.metadata = metadata
        self.user_id = user_id
        self.timestamp = timestamp
        self.signature = None

    def compute_hash(self):
        content = f"{self.event_id}|{self.aggregate_id}|{self.event_type}|{self.version}"
        return hashlib.sha3_256(content.encode()).hexdigest()


class _FallbackEventStore:
    def __init__(self):
        self._events: list[_FallbackAuditEvent] = []

    async def append(self, event: _FallbackAuditEvent) -> None:
        self._events.append(event)

    async def get_events(self, limit: int = 100) -> list[_FallbackAuditEvent]:
        return self._events[-limit:]


def _get_event_store():
    return _FallbackEventStore()


def _get_digital_signer():
    class _FallbackSigner:
        def sign(self, data: str) -> str:
            return f"sig_{hashlib.md5(data.encode()).hexdigest()}"

    return _FallbackSigner()


# ============================================================================
# ENUMS
# ============================================================================


class AuditEventType(Enum):
    COMMAND_RECEIVED = auto()
    COMMAND_VALIDATION_START = auto()
    COMMAND_VALIDATION_END = auto()
    COMMAND_EXECUTION_START = auto()
    COMMAND_EXECUTION_END = auto()
    COMMAND_SUCCESS = auto()
    COMMAND_FAILURE = auto()
    COMMAND_REJECTED = auto()
    STATE_BEFORE = auto()
    STATE_AFTER = auto()
    DATA_ACCESS = auto()
    SECURITY_EVENT = auto()


class AuditSeverity(Enum):
    DEBUG = 0
    INFO = 10
    WARNING = 20
    ERROR = 30
    CRITICAL = 40
    ALERT = 50


@dataclass
class AuditContext:
    command_id: UUID
    command_type: str
    user_id: str
    legal_entity_id: UUID
    correlation_id: str
    timestamp: datetime
    events: list[dict[str, Any]] = field(default_factory=list)


# ============================================================================
# BASE AUDIT HOOK INJECTOR (CONTRACT)
# ============================================================================


class BaseAuditHookInjector(ABC):
    """
    Base class for AuditHookInjector.
    Defines the contract that all audit hook injectors must implement.
    """

    @abstractmethod
    def start_context(self, envelope: CommandEnvelope) -> AuditContext:
        """Start a new audit context for a command envelope."""
        pass

    @abstractmethod
    def before_execution(self, envelope: CommandEnvelope) -> None:
        """Hook before command execution."""
        pass

    @abstractmethod
    def after_execution(self, envelope: CommandEnvelope, result: Any) -> None:
        """Hook after command execution (success)."""
        pass

    @abstractmethod
    def on_error(self, envelope: CommandEnvelope, error: Exception) -> None:
        """Hook when command execution fails."""
        pass

    @abstractmethod
    async def flush_all(self) -> None:
        """Flush all pending audit events."""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Gracefully shutdown the audit hook injector."""
        pass

    # Optional methods (non-abstract, can be overridden)
    def validate(self) -> dict[str, Any]:
        """Validate internal state."""
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseAuditHookInjector:
        """Create instance from dictionary."""
        return cls()

    def clone(self) -> BaseAuditHookInjector:
        """Create a clone of this instance."""
        return self

    def snapshot(self) -> dict[str, Any]:
        """Return a snapshot of current state."""
        return {}

    def version(self) -> int:
        """Return version number."""
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return audit trail entries."""
        return []

    def touch(self, touched_by: str) -> BaseAuditHookInjector:
        """Touch the instance (increment version)."""
        return self

    def get_statistics(self) -> dict[str, Any]:
        """Return statistics."""
        return {}

    def reset(self) -> None:
        """Reset internal state."""
        pass


# ============================================================================
# AUDIT HOOK INJECTOR — LAZY WORKER
# ============================================================================


class AuditHookInjector(BaseAuditHookInjector):
    _instance: AuditHookInjector | None = None
    _lock = asyncio.Lock()

    def __new__(cls) -> AuditHookInjector:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, custom_logger=None) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._event_store = _get_event_store()
        self._digital_signer = _get_digital_signer()
        self._active_contexts: dict[UUID, AuditContext] = {}
        self._async_queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._custom_logger = custom_logger
        self._shutting_down = False
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._version = 1
        logger.info("AuditHookInjector initialized (worker lazy)")

    def _ensure_worker(self) -> None:
        """Start background worker only if there is a running event loop and worker not already running."""
        if self._worker_task is not None and not self._worker_task.done():
            return
        if self._shutting_down:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running event loop, skip worker creation
            logger.debug("No running event loop, audit worker not started")
            return

        async def worker():
            while not self._shutting_down:
                try:
                    context = await self._async_queue.get()
                    await self._flush_context(context)
                    self._async_queue.task_done()
                except asyncio.CancelledError:
                    # Worker cancellation is expected during shutdown; log and exit cleanly
                    logger.debug("Audit worker cancelled, exiting")
                    break
                except Exception as e:
                    logger.error(f"Audit worker error: {e}")

        self._worker_task = loop.create_task(worker())
        logger.debug("Audit worker started")

    async def _flush_context(self, context: AuditContext) -> None:
        for event in context.events:
            audit_event = _FallbackAuditEvent(
                event_id=UUID(event["event_id"]),
                aggregate_id=context.command_id,
                event_type=f"AUDIT_{event['event_type']}",
                version=1,
                data={
                    "command_type": context.command_type,
                    "user_id": context.user_id,
                    "legal_entity_id": str(context.legal_entity_id),
                    "correlation_id": context.correlation_id,
                    "event_data": event["data"],
                    "severity": event["severity"],
                },
                metadata={"timestamp": event["timestamp"], "source": "audit_hook_injector"},
                user_id=context.user_id,
                timestamp=datetime.fromisoformat(event["timestamp"]),
            )
            signature = self._digital_signer.sign(audit_event.compute_hash())
            audit_event.signature = signature
            await self._event_store.append(audit_event)

    def start_context(self, envelope: CommandEnvelope) -> AuditContext:
        self._ensure_worker()
        context = AuditContext(
            command_id=envelope.command_id,
            command_type=envelope.command_type,
            user_id=envelope.user_id,
            legal_entity_id=envelope.legal_entity_id,
            correlation_id=envelope.correlation_id or str(uuid4()),
            timestamp=envelope.timestamp,
        )
        context.events.append(
            {
                "event_id": str(uuid4()),
                "event_type": AuditEventType.COMMAND_RECEIVED.name,
                "severity": AuditSeverity.INFO.name,
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {
                    "command_type": envelope.command_type,
                    "idempotency_key": envelope.idempotency_key,
                    "correlation_id": envelope.correlation_id,
                    "causation_id": str(envelope.causation_id) if envelope.causation_id else None,
                },
            }
        )
        self._active_contexts[envelope.command_id] = context
        return context

    def before_execution(self, envelope: CommandEnvelope) -> None:
        self._ensure_worker()
        context = self._active_contexts.get(envelope.command_id)
        if not context:
            context = self.start_context(envelope)
        context.events.append(
            {
                "event_id": str(uuid4()),
                "event_type": AuditEventType.COMMAND_EXECUTION_START.name,
                "severity": AuditSeverity.DEBUG.name,
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {"timestamp": datetime.now(UTC).isoformat()},
            }
        )

    def after_execution(self, envelope: CommandEnvelope, result: Any) -> None:
        self._ensure_worker()
        context = self._active_contexts.get(envelope.command_id)
        if not context:
            return
        context.events.append(
            {
                "event_id": str(uuid4()),
                "event_type": AuditEventType.COMMAND_EXECUTION_END.name,
                "severity": AuditSeverity.DEBUG.name,
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {
                    "status": "SUCCESS",
                    "execution_time_ms": envelope.execution_time_ms,
                    "result_summary": self._summarize_result(result),
                },
            }
        )
        context.events.append(
            {
                "event_id": str(uuid4()),
                "event_type": AuditEventType.COMMAND_SUCCESS.name,
                "severity": AuditSeverity.INFO.name,
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {
                    "execution_time_ms": envelope.execution_time_ms,
                    "result": self._safe_serialize(result)[:1000],
                },
            }
        )
        try:
            self._async_queue.put_nowait(context)
        except asyncio.QueueFull:
            logger.warning("Audit queue full, dropping context")
        self._active_contexts.pop(envelope.command_id, None)

    def on_error(self, envelope: CommandEnvelope, error: Exception) -> None:
        self._ensure_worker()
        context = self._active_contexts.get(envelope.command_id)
        if not context:
            return
        context.events.append(
            {
                "event_id": str(uuid4()),
                "event_type": AuditEventType.COMMAND_FAILURE.name,
                "severity": AuditSeverity.ERROR.name,
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {
                    "error_type": type(error).__name__,
                    "error_message": str(error)[:500],
                    "execution_time_ms": envelope.execution_time_ms,
                },
            }
        )
        try:
            self._async_queue.put_nowait(context)
        except asyncio.QueueFull:
            logger.warning("Audit queue full, dropping error context")
        self._active_contexts.pop(envelope.command_id, None)

    def record_state_before(
        self, command_id: UUID, aggregate_id: UUID, aggregate_type: str, state: dict[str, Any]
    ) -> None:
        self._ensure_worker()
        context = self._active_contexts.get(command_id)
        if not context:
            return
        context.events.append(
            {
                "event_id": str(uuid4()),
                "event_type": AuditEventType.STATE_BEFORE.name,
                "severity": AuditSeverity.DEBUG.name,
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {
                    "aggregate_id": str(aggregate_id),
                    "aggregate_type": aggregate_type,
                    "state": self._safe_serialize(state, max_depth=3),
                },
            }
        )

    def record_state_after(
        self,
        command_id: UUID,
        aggregate_id: UUID,
        aggregate_type: str,
        state: dict[str, Any],
        changes: dict[str, Any],
    ) -> None:
        self._ensure_worker()
        context = self._active_contexts.get(command_id)
        if not context:
            return
        context.events.append(
            {
                "event_id": str(uuid4()),
                "event_type": AuditEventType.STATE_AFTER.name,
                "severity": AuditSeverity.DEBUG.name,
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {
                    "aggregate_id": str(aggregate_id),
                    "aggregate_type": aggregate_type,
                    "state": self._safe_serialize(state, max_depth=3),
                    "changes": self._safe_serialize(changes),
                },
            }
        )

    def record_data_access(
        self, command_id: UUID, query_type: str, query_params: dict[str, Any], result_count: int
    ) -> None:
        self._ensure_worker()
        context = self._active_contexts.get(command_id)
        if context:
            context.events.append(
                {
                    "event_id": str(uuid4()),
                    "event_type": AuditEventType.DATA_ACCESS.name,
                    "severity": AuditSeverity.DEBUG.name,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "data": {
                        "query_type": query_type,
                        "query_params": self._safe_serialize(query_params),
                        "result_count": result_count,
                    },
                }
            )

    def record_security_event(
        self,
        command_id: UUID,
        event_type: str,
        details: dict[str, Any],
        severity: AuditSeverity = AuditSeverity.WARNING,
    ) -> None:
        self._ensure_worker()
        context = self._active_contexts.get(command_id)
        if context:
            context.events.append(
                {
                    "event_id": str(uuid4()),
                    "event_type": AuditEventType.SECURITY_EVENT.name,
                    "severity": severity.name,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "data": {
                        "security_event_type": event_type,
                        "details": self._safe_serialize(details),
                    },
                }
            )
        else:
            temp_context = AuditContext(
                command_id=command_id,
                command_type="SECURITY",
                user_id="unknown",
                legal_entity_id=UUID(int=0),
                correlation_id=str(uuid4()),
                timestamp=datetime.now(UTC),
            )
            temp_context.events.append(
                {
                    "event_id": str(uuid4()),
                    "event_type": AuditEventType.SECURITY_EVENT.name,
                    "severity": severity.name,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "data": {
                        "security_event_type": event_type,
                        "details": self._safe_serialize(details),
                    },
                }
            )
            try:
                self._async_queue.put_nowait(temp_context)
            except asyncio.QueueFull:
                logger.warning("Audit queue full, dropping security event")

    def _summarize_result(self, result: Any) -> str:
        if result is None:
            return "None"
        if isinstance(result, dict):
            keys = list(result.keys())[:5]
            return f"Dict with keys: {keys}"
        if isinstance(result, list):
            return f"List with {len(result)} items"
        if hasattr(result, "__dict__"):
            return f"Object of type {type(result).__name__}"
        return str(result)[:100]

    def _safe_serialize(self, obj: Any, max_depth: int = 2, current_depth: int = 0) -> Any:
        if current_depth >= max_depth:
            return f"<max depth {max_depth}>"
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, dict):
            result = {}
            for k, v in list(obj.items())[:20]:
                result[str(k)] = self._safe_serialize(v, max_depth, current_depth + 1)
            if len(obj) > 20:
                result["..."] = f"and {len(obj) - 20} more keys"
            return result
        if isinstance(obj, (list, tuple)):
            result = []
            for item in list(obj)[:10]:
                result.append(self._safe_serialize(item, max_depth, current_depth + 1))
            if len(obj) > 10:
                result.append(f"... and {len(obj) - 10} more items")
            return result
        if hasattr(obj, "__dict__"):
            return self._safe_serialize(obj.__dict__, max_depth, current_depth + 1)
        return f"<{type(obj).__name__}>"

    async def flush_all(self) -> None:
        await self._async_queue.join()

    async def shutdown(self) -> None:
        """Gracefully shutdown the audit worker and flush remaining events."""
        if self._shutting_down:
            return
        self._shutting_down = True

        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                # Worker task cancellation is expected during shutdown; log and continue
                logger.debug("Worker task cancelled during shutdown")
            self._worker_task = None

        # Process remaining items in queue
        while not self._async_queue.empty():
            try:
                context = self._async_queue.get_nowait()
                await self._flush_context(context)
                self._async_queue.task_done()
            except asyncio.QueueEmpty:
                # Queue became empty while processing; exit the loop
                logger.debug("Queue empty during shutdown")
                break
            except Exception as e:
                logger.error(f"Error flushing queue item during shutdown: {e}")

        # Flush active contexts that were never queued
        for context in list(self._active_contexts.values()):
            await self._flush_context(context)
        self._active_contexts.clear()

        logger.info("AuditHookInjector shutdown complete")

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self._worker_task is None or self._worker_task.done():
            errors.append("Worker task is not running")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_contexts": len(self._active_contexts),
            "queue_size": self._async_queue.qsize(),
            "worker_running": self._worker_task is not None and not self._worker_task.done(),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditHookInjector:
        instance = cls()
        return instance

    def clone(self) -> AuditHookInjector:
        new_instance = AuditHookInjector()
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "active_contexts": len(self._active_contexts),
            "queue_size": self._async_queue.qsize(),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AuditHookInjector:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

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

    # ==================== METODA TAMBAHAN ====================
    def get_statistics(self) -> dict[str, Any]:
        return {
            "active_contexts": len(self._active_contexts),
            "queue_size": self._async_queue.qsize(),
            "total_events_processed": len(self._audit_trail),
            "version": self._version,
        }

    def reset(self) -> None:
        self._active_contexts.clear()
        self._audit_trail = []
        self._snapshots = []
        self._version = 1
        logger.debug("AuditHookInjector reset")

    # ==================== INJECTOR SPECIFIC ====================
    def inject(self, obj: Any) -> None:
        self._ensure_worker()
        for attr_name in dir(obj):
            attr = getattr(obj, attr_name)
            if callable(attr) and hasattr(attr, "_audit_action"):
                action = attr._audit_action
                original = attr

                def make_wrapper(orig, act):
                    def wrapper(*args, **kwargs):
                        log_entry = {
                            "action": act,
                            "timestamp": datetime.now(UTC).isoformat(),
                        }
                        if len(args) > 1:
                            for i, arg in enumerate(args[1:], start=1):
                                try:
                                    log_entry[f"arg_{i}"] = str(arg)[:200]
                                except Exception:
                                    log_entry[f"arg_{i}"] = "<unprintable>"
                        for k, v in kwargs.items():
                            try:
                                log_entry[k] = str(v)[:200]
                            except Exception:
                                log_entry[k] = "<unprintable>"
                        if self._custom_logger:
                            self._custom_logger.log(log_entry)
                        else:
                            logger.info(f"AUDIT: {act} - {log_entry}")
                        return orig(*args, **kwargs)

                    return wrapper

                wrapped = make_wrapper(original, action)
                setattr(obj, attr_name, wrapped)


# ============================================================================
# DECORATOR
# ============================================================================
def audit(action: str):
    def decorator(func):
        func._audit_action = action
        return func

    return decorator


# ============================================================================
# SINGLETON ACCESSOR
# ============================================================================
_audit_hook_injector_instance: AuditHookInjector | None = None


def get_audit_hook_injector() -> AuditHookInjector:
    global _audit_hook_injector_instance
    if _audit_hook_injector_instance is None:
        _audit_hook_injector_instance = AuditHookInjector()
    return _audit_hook_injector_instance


__all__ = [
    "AuditContext",
    "AuditEventType",
    "AuditHookInjector",
    "AuditSeverity",
    "BaseAuditHookInjector",
    "audit",
    "get_audit_hook_injector",
]