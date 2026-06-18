#!/usr/bin/env python3
"""
Module: command_handler_registry.py
Layer: 4 - Kernel / Command Handler Registry
Responsibility: Registri handler untuk setiap tipe command.
               Menyediakan mekanisme pendaftaran, pencarian, dan validasi
               handler dengan dukungan dependency injection.

Metode yang ditambahkan:
- validate(), to_dict(), from_dict(), clone(), snapshot(), version(), audit_trail(), touch()
- get_registration_history(), get_statistics(), validate_dependencies()
"""

from __future__ import annotations

import inspect
import logging
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any

logger = logging.getLogger(__name__)

# === 1. FALLBACK UNTUK COMMAND ENVELOPE ===
try:
    from kernel.command_envelope import CommandEnvelope
except ImportError:
    from dataclasses import dataclass
    from datetime import datetime
    from uuid import UUID

    @dataclass
    class CommandEnvelope:
        command_id: UUID
        command_type: str
        command_data: dict[str, Any]
        user_id: str
        legal_entity_id: UUID
        timestamp: datetime
        correlation_id: str | None
        causation_id: UUID | None

        def __post_init__(self):
            if not hasattr(self, "status"):
                self.status = "PENDING"


# === 2. ENUMS & DEFINITIONS ===
class HandlerType(Enum):
    COMMAND = auto()
    QUERY = auto()
    EVENT = auto()
    SAGA = auto()


@dataclass
class HandlerDefinition:
    command_type: str
    handler: Callable
    handler_type: HandlerType
    version: str = "1.0.0"
    description: str = ""
    dependencies: list[str] = field(default_factory=list)
    timeout_seconds: int = 30
    retry_count: int = 3
    requires_approval: bool = False
    approval_roles: list[str] = field(default_factory=list)
    is_async: bool = False

    def __post_init__(self):
        self.is_async = inspect.iscoroutinefunction(self.handler)


class HandlerNotFoundError(Exception):
    def __init__(self, command_type: str):
        self.command_type = command_type
        super().__init__(f"Handler not found for command type: {command_type}")


class HandlerAlreadyExistsError(Exception):
    def __init__(self, command_type: str):
        self.command_type = command_type
        super().__init__(f"Handler already exists for command type: {command_type}")


class HandlerExecutionError(Exception):
    def __init__(self, command_type: str, original_error: Exception):
        self.command_type = command_type
        self.original_error = original_error
        super().__init__(f"Handler execution failed for {command_type}: {original_error}")


# === 3. COMMAND HANDLER REGISTRY ===
class CommandHandlerRegistry:
    _instance: CommandHandlerRegistry | None = None
    _lock: Any = None

    def __new__(cls) -> CommandHandlerRegistry:
        if cls._instance is None:
            import threading

            cls._lock = threading.Lock()
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._handlers: dict[str, HandlerDefinition] = {}
        self._query_handlers: dict[str, HandlerDefinition] = {}
        self._event_handlers: dict[str, list[HandlerDefinition]] = {}
        self._saga_handlers: dict[str, HandlerDefinition] = {}
        self._registration_history: list[dict[str, Any]] = []
        self._max_history = 1000
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._version = 1

    def register(
        self,
        command_type: str,
        handler: Callable,
        handler_type: HandlerType = HandlerType.COMMAND,
        version: str = "1.0.0",
        description: str = "",
        dependencies: list[str] | None = None,
        timeout_seconds: int = 30,
        retry_count: int = 3,
        requires_approval: bool = False,
        approval_roles: list[str] | None = None,
    ) -> None:
        if not callable(handler):
            raise ValueError(f"Handler for {command_type} must be callable")
        if handler_type == HandlerType.COMMAND and command_type in self._handlers:
            raise HandlerAlreadyExistsError(command_type)
        if handler_type == HandlerType.QUERY and command_type in self._query_handlers:
            raise HandlerAlreadyExistsError(command_type)
        if handler_type == HandlerType.SAGA and command_type in self._saga_handlers:
            raise HandlerAlreadyExistsError(command_type)

        definition = HandlerDefinition(
            command_type=command_type,
            handler=weakref.proxy(handler),
            handler_type=handler_type,
            version=version,
            description=description,
            dependencies=dependencies or [],
            timeout_seconds=timeout_seconds,
            retry_count=retry_count,
            requires_approval=requires_approval,
            approval_roles=approval_roles or [],
        )
        if handler_type == HandlerType.COMMAND:
            self._handlers[command_type] = definition
        elif handler_type == HandlerType.QUERY:
            self._query_handlers[command_type] = definition
        elif handler_type == HandlerType.EVENT:
            if command_type not in self._event_handlers:
                self._event_handlers[command_type] = []
            self._event_handlers[command_type].append(definition)
        elif handler_type == HandlerType.SAGA:
            self._saga_handlers[command_type] = definition

        self._record_registration(command_type, handler_type, version)
        logger.info(f"Registered {handler_type.name} handler for: {command_type}")

    def register_command_handler(self, command_type: str, handler: Callable, **kwargs) -> None:
        self.register(command_type, handler, HandlerType.COMMAND, **kwargs)

    def register_query_handler(self, query_type: str, handler: Callable, **kwargs) -> None:
        self.register(query_type, handler, HandlerType.QUERY, **kwargs)

    def register_event_handler(self, event_type: str, handler: Callable, **kwargs) -> None:
        self.register(event_type, handler, HandlerType.EVENT, **kwargs)

    def register_saga_handler(self, saga_type: str, handler: Callable, **kwargs) -> None:
        self.register(saga_type, handler, HandlerType.SAGA, **kwargs)

    def get_handler(self, command_type: str) -> Callable:
        definition = self._handlers.get(command_type)
        if not definition:
            raise HandlerNotFoundError(command_type)
        return definition.handler

    def get_handler_definition(self, command_type: str) -> HandlerDefinition | None:
        return self._handlers.get(command_type)

    def get_query_handler(self, query_type: str) -> Callable | None:
        definition = self._query_handlers.get(query_type)
        return definition.handler if definition else None

    def get_query_handler_definition(self, query_type: str) -> HandlerDefinition | None:
        return self._query_handlers.get(query_type)

    def get_event_handlers(self, event_type: str) -> list[Callable]:
        definitions = self._event_handlers.get(event_type, [])
        return [d.handler for d in definitions]

    def get_event_handler_definitions(self, event_type: str) -> list[HandlerDefinition]:
        return self._event_handlers.get(event_type, [])

    def get_saga_handler(self, saga_type: str) -> Callable | None:
        definition = self._saga_handlers.get(saga_type)
        return definition.handler if definition else None

    def get_saga_handler_definition(self, saga_type: str) -> HandlerDefinition | None:
        return self._saga_handlers.get(saga_type)

    def has_handler(self, command_type: str) -> bool:
        return command_type in self._handlers

    def has_query_handler(self, query_type: str) -> bool:
        return query_type in self._query_handlers

    def has_saga_handler(self, saga_type: str) -> bool:
        return saga_type in self._saga_handlers

    def list_handlers(self, handler_type: HandlerType | None = None) -> list[dict[str, Any]]:
        result = []
        if handler_type is None or handler_type == HandlerType.COMMAND:
            for cmd_type, defn in self._handlers.items():
                result.append(
                    {
                        "command_type": cmd_type,
                        "type": "COMMAND",
                        "version": defn.version,
                        "description": defn.description,
                        "dependencies": defn.dependencies,
                        "requires_approval": defn.requires_approval,
                        "is_async": defn.is_async,
                    }
                )
        if handler_type is None or handler_type == HandlerType.QUERY:
            for qry_type, defn in self._query_handlers.items():
                result.append(
                    {
                        "command_type": qry_type,
                        "type": "QUERY",
                        "version": defn.version,
                        "description": defn.description,
                        "is_async": defn.is_async,
                    }
                )
        if handler_type is None or handler_type == HandlerType.EVENT:
            for evt_type, defns in self._event_handlers.items():
                for defn in defns:
                    result.append(
                        {
                            "command_type": evt_type,
                            "type": "EVENT",
                            "version": defn.version,
                            "description": defn.description,
                            "is_async": defn.is_async,
                        }
                    )
        if handler_type is None or handler_type == HandlerType.SAGA:
            for saga_type, defn in self._saga_handlers.items():
                result.append(
                    {
                        "command_type": saga_type,
                        "type": "SAGA",
                        "version": defn.version,
                        "description": defn.description,
                        "is_async": defn.is_async,
                    }
                )
        return result

    def unregister(
        self, command_type: str, handler_type: HandlerType = HandlerType.COMMAND
    ) -> bool:
        if handler_type == HandlerType.COMMAND:
            if command_type in self._handlers:
                del self._handlers[command_type]
                logger.info(f"Unregistered command handler: {command_type}")
                return True
        elif handler_type == HandlerType.QUERY:
            if command_type in self._query_handlers:
                del self._query_handlers[command_type]
                logger.info(f"Unregistered query handler: {command_type}")
                return True
        elif handler_type == HandlerType.SAGA:
            if command_type in self._saga_handlers:
                del self._saga_handlers[command_type]
                logger.info(f"Unregistered saga handler: {command_type}")
                return True
        elif handler_type == HandlerType.EVENT:
            if command_type in self._event_handlers:
                del self._event_handlers[command_type]
                logger.info(f"Unregistered event handlers for: {command_type}")
                return True
        return False

    def unregister_event_handler(self, event_type: str, handler: Callable) -> bool:
        if event_type in self._event_handlers:
            definitions = self._event_handlers[event_type]
            for i, defn in enumerate(definitions):
                if defn.handler == handler:
                    del definitions[i]
                    logger.info(f"Unregistered event handler for {event_type}")
                    return True
        return False

    def clear(self) -> None:
        self._handlers.clear()
        self._query_handlers.clear()
        self._event_handlers.clear()
        self._saga_handlers.clear()
        self._registration_history.clear()
        self._version += 1

    def _record_registration(
        self, command_type: str, handler_type: HandlerType, version: str
    ) -> None:
        self._registration_history.append(
            {
                "command_type": command_type,
                "handler_type": handler_type.name,
                "version": version,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._registration_history) > self._max_history:
            self._registration_history = self._registration_history[-self._max_history :]

    def get_registration_history(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._registration_history[-limit:]

    def get_statistics(self) -> dict[str, Any]:
        event_subscriptions = sum(len(v) for v in self._event_handlers.values())
        return {
            "command_handlers": len(self._handlers),
            "query_handlers": len(self._query_handlers),
            "event_handler_subscriptions": event_subscriptions,
            "saga_handlers": len(self._saga_handlers),
            "total_handlers": len(self._handlers)
            + len(self._query_handlers)
            + event_subscriptions
            + len(self._saga_handlers),
            "total_registrations": len(self._registration_history),
        }

    def validate_dependencies(self) -> list[str]:
        missing = []
        for cmd_type, defn in self._handlers.items():
            for dep in defn.dependencies:
                if dep not in self._handlers:
                    missing.append(f"{cmd_type} depends on {dep} (not found)")
        return missing

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        for cmd_type, defn in self._handlers.items():
            if not callable(defn.handler):
                errors.append(f"Handler for {cmd_type} is not callable")
        missing_deps = self.validate_dependencies()
        errors.extend(missing_deps)
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_handlers": list(self._handlers.keys()),
            "query_handlers": list(self._query_handlers.keys()),
            "event_handlers": list(self._event_handlers.keys()),
            "saga_handlers": list(self._saga_handlers.keys()),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommandHandlerRegistry:
        instance = cls()
        # Note: handlers cannot be reconstructed from dict, just metadata
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> CommandHandlerRegistry:
        new_instance = CommandHandlerRegistry()
        new_instance._version = self._version + 1
        # Handlers are not cloned (weak references)
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "command_handlers": len(self._handlers),
            "query_handlers": len(self._query_handlers),
            "event_handlers": len(self._event_handlers),
            "saga_handlers": len(self._saga_handlers),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CommandHandlerRegistry:
        self._version += 1
        self._audit_trail.append(
            {
                "action": "TOUCH",
                "performed_by": touched_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
            }
        )
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


# === 4. DECORATORS ===
def command_handler(
    command_type: str,
    version: str = "1.0.0",
    description: str = "",
    dependencies: list[str] | None = None,
    timeout_seconds: int = 30,
    retry_count: int = 3,
    requires_approval: bool = False,
    approval_roles: list[str] | None = None,
):
    def decorator(func: Callable) -> Callable:
        registry = get_handler_registry()
        registry.register(
            command_type=command_type,
            handler=func,
            handler_type=HandlerType.COMMAND,
            version=version,
            description=description,
            dependencies=dependencies,
            timeout_seconds=timeout_seconds,
            retry_count=retry_count,
            requires_approval=requires_approval,
            approval_roles=approval_roles,
        )
        return func

    return decorator


def query_handler(
    query_type: str, version: str = "1.0.0", description: str = "", timeout_seconds: int = 30
):
    def decorator(func: Callable) -> Callable:
        registry = get_handler_registry()
        registry.register(
            command_type=query_type,
            handler=func,
            handler_type=HandlerType.QUERY,
            version=version,
            description=description,
            timeout_seconds=timeout_seconds,
        )
        return func

    return decorator


def event_handler(event_type: str, version: str = "1.0.0", description: str = ""):
    def decorator(func: Callable) -> Callable:
        registry = get_handler_registry()
        registry.register(
            command_type=event_type,
            handler=func,
            handler_type=HandlerType.EVENT,
            version=version,
            description=description,
        )
        return func

    return decorator


def saga_handler(
    saga_type: str,
    version: str = "1.0.0",
    description: str = "",
    timeout_seconds: int = 60,
    retry_count: int = 0,
):
    def decorator(func: Callable) -> Callable:
        registry = get_handler_registry()
        registry.register(
            command_type=saga_type,
            handler=func,
            handler_type=HandlerType.SAGA,
            version=version,
            description=description,
            timeout_seconds=timeout_seconds,
            retry_count=retry_count,
        )
        return func

    return decorator


# === 5. SINGLETON ACCESSOR ===
_handler_registry_instance: CommandHandlerRegistry | None = None


def get_handler_registry() -> CommandHandlerRegistry:
    global _handler_registry_instance
    if _handler_registry_instance is None:
        _handler_registry_instance = CommandHandlerRegistry()
    return _handler_registry_instance


__all__ = [
    "CommandHandlerRegistry",
    "HandlerAlreadyExistsError",
    "HandlerDefinition",
    "HandlerExecutionError",
    "HandlerNotFoundError",
    "HandlerType",
    "command_handler",
    "event_handler",
    "get_handler_registry",
    "query_handler",
    "saga_handler",
]
