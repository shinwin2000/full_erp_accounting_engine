#!/usr/bin/env python3
"""
Module: context_holder.py
Layer: 4 - Kernel / Context Holder
Responsibility: Menyimpan konteks eksekusi (user, entity, request ID).
               Menggunakan ContextVar untuk membawa konteks secara implicit
               melalui async call chain, mendukung nested contexts, dan
               propagasi otomatis ke child tasks.

Metode yang ditambahkan:
- validate(), to_dict(), from_dict(), clone(), snapshot(), version(), audit_trail(), touch()
- push_context(), pop_context(), run_in_context(), run_in_context_async()
- create_child_context(), enrich_with_context(), get_context_snapshot()
- get_current_user_id(), get_current_legal_entity_id(), get_correlation_id()
- get_current_roles(), get_current_permissions()
"""

from __future__ import annotations

import contextvars
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# === 1. VALUE OBJECTS ===
@dataclass
class ExecutionContext:
    user_id: str
    legal_entity_id: UUID
    correlation_id: str | None = None
    command_id: UUID | None = None
    causation_id: UUID | None = None
    tenant_id: str | None = None
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    ip_address: str | None = None
    user_agent: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "legal_entity_id": str(self.legal_entity_id),
            "correlation_id": self.correlation_id,
            "command_id": str(self.command_id) if self.command_id else None,
            "causation_id": str(self.causation_id) if self.causation_id else None,
            "tenant_id": self.tenant_id,
            "roles": self.roles,
            "permissions": self.permissions[:10],
            "ip_address": self.ip_address,
            "user_agent": self.user_agent[:100] if self.user_agent else None,
            "started_at": self.started_at.isoformat(),
        }

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions

    def has_any_permission(self, *permissions: str) -> bool:
        return any(p in self.permissions for p in permissions)

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.user_id:
            errors.append("user_id is required")
        if not self.legal_entity_id:
            errors.append("legal_entity_id is required")
        return {"is_valid": len(errors) == 0, "errors": errors}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionContext:
        return cls(
            user_id=data["user_id"],
            legal_entity_id=UUID(data["legal_entity_id"]),
            correlation_id=data.get("correlation_id"),
            command_id=UUID(data["command_id"]) if data.get("command_id") else None,
            causation_id=UUID(data["causation_id"]) if data.get("causation_id") else None,
            tenant_id=data.get("tenant_id"),
            roles=data.get("roles", []),
            permissions=data.get("permissions", []),
            ip_address=data.get("ip_address"),
            user_agent=data.get("user_agent"),
            started_at=datetime.fromisoformat(data["started_at"])
            if data.get("started_at")
            else datetime.now(UTC),
        )

    def clone(self) -> ExecutionContext:
        return ExecutionContext(
            user_id=self.user_id,
            legal_entity_id=self.legal_entity_id,
            correlation_id=self.correlation_id,
            command_id=self.command_id,
            causation_id=self.causation_id,
            tenant_id=self.tenant_id,
            roles=self.roles.copy(),
            permissions=self.permissions.copy(),
            ip_address=self.ip_address,
            user_agent=self.user_agent,
            started_at=self.started_at,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "legal_entity_id": str(self.legal_entity_id),
            "correlation_id": self.correlation_id,
            "command_id": str(self.command_id) if self.command_id else None,
            "started_at": self.started_at.isoformat(),
        }

    def version(self) -> int:
        return 1  # ExecutionContext is immutable

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> ExecutionContext:
        # Return a new context with updated started_at (or just self)
        return ExecutionContext(
            user_id=self.user_id,
            legal_entity_id=self.legal_entity_id,
            correlation_id=self.correlation_id,
            command_id=self.command_id,
            causation_id=self.causation_id,
            tenant_id=self.tenant_id,
            roles=self.roles,
            permissions=self.permissions,
            ip_address=self.ip_address,
            user_agent=self.user_agent,
            started_at=datetime.now(UTC),
        )


@dataclass
class ContextSnapshot:
    context: ExecutionContext | None
    timestamp: datetime


# ============================================================================
# BASE CLASS ABSTRAK (CONTRACT)
# ============================================================================
class BaseContextHolder(ABC):
    """
    Base contract for Context Holder.
    Semua method yang wajib diimplementasikan oleh subclass.
    """

    @abstractmethod
    def set_context(self, context: ExecutionContext | None) -> ExecutionContext | None:
        """Set the current execution context."""
        pass

    @abstractmethod
    def get_context(self) -> ExecutionContext | None:
        """Get the current execution context."""
        pass

    @abstractmethod
    def push_context(self, context: ExecutionContext) -> None:
        """Push context to stack."""
        pass

    @abstractmethod
    def pop_context(self) -> ExecutionContext | None:
        """Pop context from stack."""
        pass

    @abstractmethod
    def clear_context(self) -> None:
        """Clear the current context."""
        pass

    @abstractmethod
    def get_current_user_id(self) -> str | None:
        """Get current user ID from context."""
        pass

    @abstractmethod
    def get_current_legal_entity_id(self) -> UUID | None:
        """Get current legal entity ID from context."""
        pass

    @abstractmethod
    def get_correlation_id(self) -> str | None:
        """Get current correlation ID from context."""
        pass

    @abstractmethod
    def get_current_roles(self) -> list[str]:
        """Get current roles from context."""
        pass

    @abstractmethod
    def get_current_permissions(self) -> list[str]:
        """Get current permissions from context."""
        pass

    @abstractmethod
    def create_child_context(
        self, command_id: UUID | None = None, causation_id: UUID | None = None
    ) -> ExecutionContext:
        """Create a child context from current context."""
        pass

    @abstractmethod
    def get_context_snapshot(self) -> dict[str, Any] | None:
        """Get a snapshot of the current context."""
        pass


# === 2. CONTEXT HOLDER ===
class ContextHolder(BaseContextHolder):
    _instance: ContextHolder | None = None
    _lock: Any = None

    def __new__(cls) -> ContextHolder:
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
        self._current_context: contextvars.ContextVar[ExecutionContext | None] = (
            contextvars.ContextVar("execution_context", default=None)
        )
        self._context_stack: contextvars.ContextVar[list[ContextSnapshot]] = contextvars.ContextVar(
            "context_stack", default=[]
        )
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._version = 1

    def set_context(self, context: ExecutionContext | None) -> ExecutionContext | None:
        previous = self._current_context.get(None)
        self._current_context.set(context)
        if context:
            logger.debug(f"Context set: user={context.user_id}, entity={context.legal_entity_id}")
        else:
            logger.debug("Context cleared")
        return previous

    def get_context(self) -> ExecutionContext | None:
        return self._current_context.get(None)

    def get_current_user_id(self) -> str | None:
        ctx = self.get_context()
        return ctx.user_id if ctx else None

    def get_current_legal_entity_id(self) -> UUID | None:
        ctx = self.get_context()
        return ctx.legal_entity_id if ctx else None

    def get_correlation_id(self) -> str | None:
        ctx = self.get_context()
        return ctx.correlation_id if ctx else None

    def get_current_roles(self) -> list[str]:
        ctx = self.get_context()
        return ctx.roles if ctx else []

    def get_current_permissions(self) -> list[str]:
        ctx = self.get_context()
        return ctx.permissions if ctx else []

    def push_context(self, context: ExecutionContext) -> None:
        stack = list(self._context_stack.get([]))
        current = self.get_context()
        if current:
            stack.append(ContextSnapshot(context=current, timestamp=datetime.now(UTC)))
        self._context_stack.set(stack)
        self.set_context(context)

    def pop_context(self) -> ExecutionContext | None:
        stack = list(self._context_stack.get([]))
        if stack:
            snapshot = stack.pop()
            self._context_stack.set(stack)
            self.set_context(snapshot.context)
            return snapshot.context
        else:
            self.set_context(None)
            return None

    def run_in_context(self, context: ExecutionContext, func: callable, *args, **kwargs) -> Any:
        self.push_context(context)
        try:
            return func(*args, **kwargs)
        finally:
            self.pop_context()

    async def run_in_context_async(self, context: ExecutionContext, coro, *args, **kwargs) -> Any:
        self.push_context(context)
        try:
            return await coro(*args, **kwargs)
        finally:
            self.pop_context()

    def clear_context(self) -> None:
        self.set_context(None)

    def has_context(self) -> bool:
        return self.get_context() is not None

    def enrich_with_context(self, data: dict[str, Any]) -> dict[str, Any]:
        ctx = self.get_context()
        if not ctx:
            return data
        enriched = data.copy()
        enriched.setdefault("_context", {})
        enriched["_context"].update(
            {
                "user_id": ctx.user_id,
                "legal_entity_id": str(ctx.legal_entity_id),
                "correlation_id": ctx.correlation_id,
                "command_id": str(ctx.command_id) if ctx.command_id else None,
            }
        )
        return enriched

    def create_child_context(
        self, command_id: UUID | None = None, causation_id: UUID | None = None
    ) -> ExecutionContext:
        current = self.get_context()
        if not current:
            raise RuntimeError("No current context to create child from")
        return ExecutionContext(
            user_id=current.user_id,
            legal_entity_id=current.legal_entity_id,
            correlation_id=current.correlation_id,
            command_id=command_id or uuid4(),
            causation_id=causation_id or current.command_id,
            tenant_id=current.tenant_id,
            roles=current.roles.copy(),
            permissions=current.permissions.copy(),
            ip_address=current.ip_address,
            user_agent=current.user_agent,
            started_at=current.started_at,
        )

    def get_context_snapshot(self) -> dict[str, Any] | None:
        ctx = self.get_context()
        if ctx:
            return ctx.to_dict()
        return None

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        ctx = self.get_context()
        if ctx:
            res = ctx.validate()
            if not res["is_valid"]:
                errors.extend(res["errors"])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        ctx = self.get_context()
        return {
            "has_context": ctx is not None,
            "context": ctx.to_dict() if ctx else None,
            "stack_depth": len(self._context_stack.get([])),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextHolder:
        instance = cls()
        if data.get("context"):
            ctx = ExecutionContext.from_dict(data["context"])
            instance.set_context(ctx)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> ContextHolder:
        new_instance = ContextHolder()
        current = self.get_context()
        if current:
            new_instance.set_context(current.clone())
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "has_context": self.get_context() is not None,
            "stack_depth": len(self._context_stack.get([])),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ContextHolder:
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

    def reset(self) -> None:
        self.set_context(None)
        self._context_stack.set([])
        self._audit_trail = []
        self._snapshots = []
        self._version = 1


# === 3. SINGLETON ACCESSOR ===
_context_holder_instance: ContextHolder | None = None


def get_context_holder() -> ContextHolder:
    global _context_holder_instance
    if _context_holder_instance is None:
        _context_holder_instance = ContextHolder()
    return _context_holder_instance


# === 4. CONVENIENCE FUNCTIONS ===
def get_current_user() -> str | None:
    return get_context_holder().get_current_user_id()


def get_current_legal_entity() -> UUID | None:
    return get_context_holder().get_current_legal_entity_id()


def get_correlation_id() -> str | None:
    return get_context_holder().get_correlation_id()


def get_current_roles() -> list[str]:
    return get_context_holder().get_current_roles()


def get_current_permissions() -> list[str]:
    return get_context_holder().get_current_permissions()


def enrich_with_context(data: dict[str, Any]) -> dict[str, Any]:
    return get_context_holder().enrich_with_context(data)


__all__ = [
    "ContextHolder",
    "ContextSnapshot",
    "ExecutionContext",
    "enrich_with_context",
    "get_context_holder",
    "get_correlation_id",
    "get_current_legal_entity",
    "get_current_permissions",
    "get_current_roles",
    "get_current_user",
]
