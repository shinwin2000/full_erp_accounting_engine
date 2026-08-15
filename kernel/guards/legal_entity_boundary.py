#!/usr/bin/env python3
"""
Module: legal_entity_boundary.py
Layer: 4 - Kernel / Guards
Responsibility: Menjaga isolasi data antar entitas hukum (tenant).
               Memastikan bahwa operasi hanya mengakses data dari entitas
               hukum yang sesuai dengan konteks user. Mencegah kebocoran
               data antar entitas, baik disengaja maupun tidak.

Dependencies:
- standard library (logging, typing, threading, uuid, datetime, hashlib)
- kernel.context_holder (get_current_legal_entity, get_current_user)
- kernel.guards.guard_exceptions (GuardViolationError, LegalEntityBoundaryError, GuardSeverity)

Audit: Setiap percobaan akses lintas entitas dictat.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_legal_entity, get_current_user
from kernel.guards.guard_exceptions import (
    GuardSeverity,
    LegalEntityBoundaryError,
)

logger = logging.getLogger(__name__)


# === 1. FALLBACK USER REPOSITORY (internal, tidak mengimpor adapters/infrastructure) ===


class _FallbackUserRepository:
    """
    Fallback user repository jika infrastructure belum tersedia.
    Menyimpan data user dan entitas yang diizinkan dalam memory.
    """

    def __init__(self) -> None:
        self._user_entities: dict[str, set[UUID]] = {}
        self._user_roles: dict[str, list[str]] = {}
        self._cross_entity_auths: dict[
            tuple[str, UUID, UUID], bool
        ] = {}  # (user_id, from_entity, to_entity) -> allowed
        self._user_details: dict[str, dict[str, Any]] = {}
        self._entity_owners: dict[UUID, str] = {}  # entity_id -> owner_user_id

    async def get_legal_entities(self, user_id: str) -> list[UUID]:
        """Mendapatkan daftar entitas yang dapat diakses user."""
        return list(self._user_entities.get(user_id, set()))

    async def get_roles(self, user_id: str) -> list[str]:
        """Mendapatkan daftar role user."""
        return self._user_roles.get(user_id, [])

    async def has_cross_entity_access(
        self, user_id: str, from_entity: UUID, to_entity: UUID, operation: str
    ) -> bool:
        """Memeriksa apakah user memiliki akses lintas entitas."""
        # Check specific authorization
        key = (user_id, from_entity, to_entity)
        if key in self._cross_entity_auths:
            return self._cross_entity_auths[key]
        # Check if user is owner of both entities
        return (
            self._entity_owners.get(from_entity) == user_id
            and self._entity_owners.get(to_entity) == user_id
        )

    async def get_user_details(self, user_id: str) -> dict[str, Any] | None:
        """Mendapatkan detail user."""
        return self._user_details.get(user_id)

    async def get_entity_owner(self, entity_id: UUID) -> str | None:
        """Mendapatkan owner suatu entitas."""
        return self._entity_owners.get(entity_id)

    async def get_all_entities(self) -> list[UUID]:
        """Mendapatkan semua entitas yang terdaftar."""
        return list(self._entity_owners.keys())

    def add_user_entity(self, user_id: str, entity_id: UUID) -> None:
        """Menambahkan akses user ke suatu entitas."""
        if user_id not in self._user_entities:
            self._user_entities[user_id] = set()
        self._user_entities[user_id].add(entity_id)

    def set_user_roles(self, user_id: str, roles: list[str]) -> None:
        """Set role user."""
        self._user_roles[user_id] = roles

    def add_cross_entity_auth(self, user_id: str, from_entity: UUID, to_entity: UUID) -> None:
        """Memberikan otorisasi lintas entitas."""
        self._cross_entity_auths[(user_id, from_entity, to_entity)] = True

    def set_entity_owner(self, entity_id: UUID, owner_user_id: str) -> None:
        """Set owner suatu entitas."""
        self._entity_owners[entity_id] = owner_user_id

    def add_user_details(
        self, user_id: str, name: str, email: str = "", department: str = ""
    ) -> None:
        """Menambahkan detail user."""
        self._user_details[user_id] = {
            "user_id": user_id,
            "name": name,
            "email": email,
            "department": department,
            "created_at": datetime.now(UTC),
        }


# === 2. CONSTANTS & ENUMS ===


class EntityAccessOperation(Enum):
    """Jenis operasi akses entitas."""

    READ = "READ"
    WRITE = "WRITE"
    DELETE = "DELETE"
    TRANSFER = "TRANSFER"
    CONSOLIDATE = "CONSOLIDATE"
    REPORT = "REPORT"
    AUDIT = "AUDIT"
    ADMIN = "ADMIN"


class EntityAccessSeverity(Enum):
    """Severity untuk pelanggaran entity boundary."""

    CRITICAL = 80  # Akses ke entitas yang tidak diotorisasi sama sekali
    HIGH = 60  # Akses cross-entity tanpa otorisasi
    MEDIUM = 40  # Akses ke entitas yang bukan primary context
    LOW = 20  # Peringatan akses lintas entitas untuk baca
    INFO = 0


@dataclass
class EntityAccessCheckResult:
    """Hasil pemeriksaan akses entitas."""

    check_id: UUID
    user_id: str
    source_entity_id: UUID | None
    target_entity_id: UUID
    operation: str
    is_allowed: bool
    severity: EntityAccessSeverity
    message: str
    requires_cross_auth: bool = False
    authorized_entities: list[UUID] = field(default_factory=list)
    user_roles: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.check_id}|{self.user_id}|{self.target_entity_id}|{self.operation}|"
            f"{self.is_allowed}|{self.severity.value}|{self.message[:100]}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self) -> None:
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": str(self.check_id),
            "user_id": self.user_id,
            "source_entity_id": str(self.source_entity_id) if self.source_entity_id else None,
            "target_entity_id": str(self.target_entity_id),
            "operation": self.operation,
            "is_allowed": self.is_allowed,
            "severity": self.severity.name,
            "message": self.message,
            "requires_cross_auth": self.requires_cross_auth,
            "authorized_entities": [str(e) for e in self.authorized_entities],
            "user_roles": self.user_roles,
            "timestamp": self.timestamp.isoformat(),
            "hash": self.cryptographic_hash[:16] + "...",
        }


# ============================================================================
# BASE LEGAL ENTITY BOUNDARY GUARD (ABSTRACT)
# ============================================================================

class BaseLegalEntityBoundaryGuard(ABC):
    """Base contract untuk Legal Entity Boundary Guard."""

    @abstractmethod
    def enable(self, enabled: bool = True) -> None:
        """Mengaktifkan atau menonaktifkan guard."""
        pass

    @abstractmethod
    def set_strict_mode(self, enabled: bool) -> None:
        """Set strict mode."""
        pass

    @abstractmethod
    def set_allowed_cross_entity_operations(self, operations: list[str]) -> None:
        """Set daftar operasi yang diizinkan untuk cross-entity (non-strict mode)."""
        pass

    @abstractmethod
    def clear_cache(self) -> None:
        """Clear cache hasil check."""
        pass

    @abstractmethod
    async def check_entity_access(
        self,
        target_entity_id: UUID,
        user_id: str | None = None,
        operation: str = "READ",
        source_entity_id: UUID | None = None,
        use_cache: bool = True,
    ) -> EntityAccessCheckResult:
        """Memeriksa apakah user memiliki akses ke entitas target."""
        pass

    @abstractmethod
    async def check_multi_entity_access(
        self,
        entity_ids: list[UUID],
        user_id: str | None = None,
        operation: str = "READ",
        require_all: bool = True,
        source_entity_id: UUID | None = None,
    ) -> tuple[bool, list[EntityAccessCheckResult]]:
        """Memeriksa akses ke multiple entities."""
        pass

    @abstractmethod
    async def enforce_current_entity(
        self,
        entity_id: UUID | None = None,
        operation: str = "READ",
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> UUID:
        """Memastikan entity_id sesuai context atau mengembalikan entity dari context."""
        pass

    @abstractmethod
    async def enforce_cross_entity_transfer(
        self,
        from_entity_id: UUID,
        to_entity_id: UUID,
        amount: Decimal,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, list[EntityAccessCheckResult]]:
        """Menegakkan aturan untuk transfer antar entitas."""
        pass

    @abstractmethod
    async def enforce_consolidation(
        self,
        parent_entity_id: UUID,
        child_entity_ids: list[UUID],
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, list[EntityAccessCheckResult]]:
        """Menegakkan aturan untuk konsolidasi entitas."""
        pass

    @abstractmethod
    def get_check_history(
        self,
        limit: int = 100,
        only_denied: bool = False,
        user_id: str | None = None,
        entity_id: UUID | None = None,
        operation: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[EntityAccessCheckResult]:
        """Mendapatkan history pemeriksaan akses entitas."""
        pass

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        """Mendapatkan statistik entity boundary guard."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset history dan cache (untuk testing)."""
        pass

    # ==================== CHECKER METHODS ====================

    @abstractmethod
    def check(self, context: dict) -> list[str]:
        """Sync check method untuk compliance checker."""
        pass

    @abstractmethod
    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        pass

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        pass

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseLegalEntityBoundaryGuard:
        """Reconstruct dari dictionary."""
        pass

    @abstractmethod
    def clone(self) -> BaseLegalEntityBoundaryGuard:
        """Clone instance."""
        pass

    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        pass

    @abstractmethod
    def version(self) -> int:
        """Dapatkan versi."""
        pass

    @abstractmethod
    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        pass

    @abstractmethod
    def touch(self, touched_by: str) -> BaseLegalEntityBoundaryGuard:
        """Touch instance (increment version)."""
        pass


# ============================================================================
# LEGAL ENTITY BOUNDARY GUARD (CONCRETE)
# ============================================================================

class LegalEntityBoundaryGuard(BaseLegalEntityBoundaryGuard):
    """
    Guard untuk menjaga batasan antar entitas hukum.

    Business context: Setiap user hanya boleh mengakses data dari entitas
    hukum yang menjadi wewenangnya. Cross-entity access memerlukan
    otorisasi khusus.
    """

    def __init__(self, user_repository: Any | None = None) -> None:
        self._user_repo = user_repository or _FallbackUserRepository()
        self._check_history: list[EntityAccessCheckResult] = []
        self._max_history: int = 10000
        self._lock = threading.RLock()
        self._strict_mode: bool = True  # Jika True, cross-entity tanpa auth ditolak
        self._allowed_cross_entity_operations: set[str] = {
            "READ",
            "REPORT",
            "AUDIT",
        }  # Operasi yang mungkin diizinkan
        self._enabled: bool = True
        self._cache_ttl_seconds: int = 300  # Cache hasil check selama 5 menit
        self._cache: dict[str, tuple[EntityAccessCheckResult, datetime]] = {}
        # Entity fields
        self._version: int = 1
        self._audit_trail: list[dict[str, Any]] = []

    # ==================== SYNC CHECK METHOD (untuk checker compliance) ====================

    def check(self, context: dict) -> list[str]:
        """
        Sync check method untuk compliance checker.
        Memvalidasi context dan mengembalikan daftar error jika ada.
        """
        errors: list[str] = []
        target_entity_id = context.get("target_entity_id")
        user_id = context.get("user_id")
        operation = context.get("operation", "READ")

        if not target_entity_id:
            errors.append("target_entity_id is required")
        else:
            try:
                UUID(str(target_entity_id))
            except Exception:
                errors.append("target_entity_id must be a valid UUID")

        # SIM102: combine nested if using and
        if user_id is not None and not isinstance(user_id, str):
            errors.append("user_id must be a string")

        if operation:
            try:
                EntityAccessOperation(operation.upper())
            except ValueError:
                errors.append(f"operation '{operation}' is not a valid EntityAccessOperation")
        return errors

    # ==================== ENTITY METHODS (wajib) ====================

    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        errors: list[str] = []
        if self._max_history <= 0:
            errors.append("max_history must be positive")
        if self._cache_ttl_seconds <= 0:
            errors.append("cache_ttl_seconds must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "strict_mode": self._strict_mode,
                "allowed_cross_entity_operations": list(self._allowed_cross_entity_operations),
                "history_count": len(self._check_history),
                "cache_size": len(self._cache),
                "version": self._version,
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LegalEntityBoundaryGuard:
        """Reconstruct dari dictionary."""
        instance = cls()
        instance._enabled = data.get("enabled", True)
        instance._strict_mode = data.get("strict_mode", True)
        instance._max_history = data.get("max_history", 10000)
        instance._cache_ttl_seconds = data.get("cache_ttl_seconds", 300)
        instance._version = data.get("version", 1)
        ops = data.get("allowed_cross_entity_operations", ["READ", "REPORT", "AUDIT"])
        if isinstance(ops, list):
            instance._allowed_cross_entity_operations = set(ops)
        return instance

    def clone(self) -> LegalEntityBoundaryGuard:
        """Clone instance."""
        new_instance = LegalEntityBoundaryGuard()
        new_instance._enabled = self._enabled
        new_instance._strict_mode = self._strict_mode
        new_instance._max_history = self._max_history
        new_instance._cache_ttl_seconds = self._cache_ttl_seconds
        new_instance._allowed_cross_entity_operations = self._allowed_cross_entity_operations.copy()
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        with self._lock:
            return {
                "version": self._version,
                "history_count": len(self._check_history),
                "cache_size": len(self._cache),
                "enabled": self._enabled,
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def version(self) -> int:
        """Dapatkan versi."""
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> LegalEntityBoundaryGuard:
        """Touch instance (increment version)."""
        self._version += 1
        self._audit_trail.append({
            "action": "TOUCH",
            "performed_by": touched_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self._version,
        })
        return self

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append({
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self._version,
            "details": details,
        })

    # ==================== ORIGINAL BUSINESS METHODS ====================

    def enable(self, enabled: bool = True) -> None:
        """Mengaktifkan atau menonaktifkan guard."""
        self._enabled = enabled
        self._record_audit("ENABLE", "system", {"enabled": enabled})
        logger.info(f"Legal entity boundary guard enabled: {enabled}")

    def set_strict_mode(self, enabled: bool) -> None:
        """Set strict mode (default True). Jika False, cross-entity read diizinkan dengan warning."""
        self._strict_mode = enabled
        self._record_audit("SET_STRICT_MODE", "system", {"strict": enabled})
        logger.info(f"Legal entity boundary strict mode set to {enabled}")

    def set_allowed_cross_entity_operations(self, operations: list[str]) -> None:
        """Set daftar operasi yang diizinkan untuk cross-entity (non-strict mode)."""
        self._allowed_cross_entity_operations = set(operations)
        self._record_audit("SET_ALLOWED_CROSS_OPS", "system", {"operations": operations})
        logger.info(f"Allowed cross-entity operations: {operations}")

    def clear_cache(self) -> None:
        """Clear cache hasil check."""
        with self._lock:
            self._cache.clear()
        self._record_audit("CLEAR_CACHE", "system", {})

    def _get_cache_key(self, user_id: str, target_entity_id: UUID, operation: str) -> str:
        return f"{user_id}|{target_entity_id}|{operation}"

    async def get_user_entities(self, user_id: str, use_cache: bool = True) -> list[UUID]:
        """Mendapatkan daftar entitas yang dapat diakses user."""
        # In production would have cache, but fallback langsung
        return await self._user_repo.get_legal_entities(user_id)

    async def check_entity_access(
        self,
        target_entity_id: UUID,
        user_id: str | None = None,
        operation: str = "READ",
        source_entity_id: UUID | None = None,
        use_cache: bool = True,
    ) -> EntityAccessCheckResult:
        """
        Memeriksa apakah user memiliki akses ke entitas target.

        Args:
            target_entity_id: Entitas yang akan diakses
            user_id: User ID (default dari context)
            operation: Jenis operasi (READ, WRITE, DELETE, etc.)
            source_entity_id: Entitas sumber (untuk cross-entity check)
            use_cache: Apakah menggunakan cache

        Returns:
            EntityAccessCheckResult
        """
        if not self._enabled:
            return EntityAccessCheckResult(
                check_id=uuid4(),
                user_id=user_id or "unknown",
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                operation=operation,
                is_allowed=True,
                severity=EntityAccessSeverity.INFO,
                message="Legal entity boundary guard is disabled",
                cryptographic_hash="",
            )

        if user_id is None:
            user_id = get_current_user()
            if user_id is None:
                return EntityAccessCheckResult(
                    check_id=uuid4(),
                    user_id="unknown",
                    source_entity_id=source_entity_id,
                    target_entity_id=target_entity_id,
                    operation=operation,
                    is_allowed=False,
                    severity=EntityAccessSeverity.CRITICAL,
                    message="No user in context",
                    cryptographic_hash="",
                )

        # Check cache
        cache_key = self._get_cache_key(user_id, target_entity_id, operation)
        if use_cache:
            with self._lock:
                if cache_key in self._cache:
                    cached_result, cached_time = self._cache[cache_key]
                    if (datetime.now(UTC) - cached_time).total_seconds() < self._cache_ttl_seconds:
                        return cached_result

        if source_entity_id is None:
            source_entity_id = get_current_legal_entity()

        # Get user's authorized entities
        user_entities = await self.get_user_entities(user_id)
        user_roles = await self._user_repo.get_roles(user_id)

        # Jika target ada dalam daftar entitas user, izinkan
        if target_entity_id in user_entities:
            result = EntityAccessCheckResult(
                check_id=uuid4(),
                user_id=user_id,
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                operation=operation,
                is_allowed=True,
                severity=EntityAccessSeverity.INFO,
                message=f"Access granted to entity {target_entity_id}",
                authorized_entities=user_entities,
                user_roles=user_roles,
                cryptographic_hash="",
            )
        else:
            # Jika tidak, cek cross-entity access
            requires_cross_auth = True
            is_allowed = False
            severity = EntityAccessSeverity.HIGH
            message = f"User {user_id} does not have access to entity {target_entity_id}"

            # Jika ada source_entity dan berbeda, cek cross-entity authorization
            if source_entity_id and source_entity_id != target_entity_id:
                has_cross_auth = await self._user_repo.has_cross_entity_access(
                    user_id, source_entity_id, target_entity_id, operation
                )
                if has_cross_auth:
                    is_allowed = True
                    severity = EntityAccessSeverity.LOW
                    message = f"Cross-entity access from {source_entity_id} to {target_entity_id} authorized for {operation}"
                elif operation in self._allowed_cross_entity_operations and not self._strict_mode:
                    # Non-strict mode: allow read with warning
                    is_allowed = True
                    severity = EntityAccessSeverity.MEDIUM
                    message = f"Cross-entity {operation} from {source_entity_id} to {target_entity_id} allowed in non-strict mode (warning)"
                else:
                    is_allowed = False
                    severity = EntityAccessSeverity.HIGH
                    message = f"Cross-entity {operation} from {source_entity_id} to {target_entity_id} not authorized"
            else:
                # No source context, just deny
                is_allowed = False
                severity = EntityAccessSeverity.HIGH

            result = EntityAccessCheckResult(
                check_id=uuid4(),
                user_id=user_id,
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                operation=operation,
                is_allowed=is_allowed,
                severity=severity,
                message=message,
                requires_cross_auth=requires_cross_auth,
                authorized_entities=user_entities,
                user_roles=user_roles,
                cryptographic_hash="",
            )

        result = EntityAccessCheckResult(
            check_id=result.check_id,
            user_id=result.user_id,
            source_entity_id=result.source_entity_id,
            target_entity_id=result.target_entity_id,
            operation=result.operation,
            is_allowed=result.is_allowed,
            severity=result.severity,
            message=result.message,
            requires_cross_auth=result.requires_cross_auth,
            authorized_entities=result.authorized_entities,
            user_roles=result.user_roles,
            timestamp=result.timestamp,
            cryptographic_hash=result.compute_hash(),
        )

        # Record history
        with self._lock:
            self._check_history.append(result)
            if len(self._check_history) > self._max_history:
                self._check_history = self._check_history[-self._max_history :]
            # Update cache
            if use_cache:
                self._cache[cache_key] = (result, datetime.now(UTC))

        if not is_allowed or severity.value >= EntityAccessSeverity.HIGH.value:
            logger.warning(f"Entity access check: {message}")

        return result

    async def check_multi_entity_access(
        self,
        entity_ids: list[UUID],
        user_id: str | None = None,
        operation: str = "READ",
        require_all: bool = True,
        source_entity_id: UUID | None = None,
    ) -> tuple[bool, list[EntityAccessCheckResult]]:
        """
        Memeriksa akses ke multiple entities.

        Args:
            entity_ids: Daftar entitas yang akan diakses
            user_id: User ID
            operation: Jenis operasi
            require_all: Jika True, semua entity harus diakses; jika False, minimal satu
            source_entity_id: Entitas sumber (untuk cross-entity)

        Returns:
            (is_allowed, list_of_check_results)
        """
        results: list[EntityAccessCheckResult] = []
        all_allowed = True
        any_allowed = False

        for entity_id in entity_ids:
            result = await self.check_entity_access(entity_id, user_id, operation, source_entity_id)
            results.append(result)
            if result.is_allowed:
                any_allowed = True
            else:
                all_allowed = False
                if require_all:
                    break

        final_allowed = all_allowed if require_all else any_allowed
        return final_allowed, results

    async def enforce_current_entity(
        self,
        entity_id: UUID | None = None,
        operation: str = "READ",
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> UUID:
        """
        Memastikan bahwa entity_id yang diberikan sesuai dengan context,
        atau mengembalikan entity dari context.

        Args:
            entity_id: Entity ID yang diusulkan (opsional)
            operation: Operasi yang dilakukan
            user_id: User ID
            raise_on_violation: Raise exception jika tidak valid

        Returns:
            Entity ID yang valid

        Raises:
            LegalEntityBoundaryError: Jika tidak ada entity yang valid
        """
        context_entity = get_current_legal_entity()

        if entity_id is None:
            if context_entity is None:
                if raise_on_violation:
                    raise LegalEntityBoundaryError(
                        message="No legal entity specified and none in context",
                        target_entity_id="unknown",
                        severity=GuardSeverity.CRITICAL,
                    )
                return UUID(int=0)
            return context_entity

        # Jika entity_id diberikan, validasi akses
        result = await self.check_entity_access(entity_id, user_id, operation)
        if not result.is_allowed and raise_on_violation:
            raise LegalEntityBoundaryError(
                message=result.message,
                target_entity_id=str(entity_id),
                severity=GuardSeverity.HIGH
                if result.severity != EntityAccessSeverity.CRITICAL
                else GuardSeverity.CRITICAL,
                details=result.to_dict(),
            )
        return entity_id

    async def enforce_cross_entity_transfer(
        self,
        from_entity_id: UUID,
        to_entity_id: UUID,
        amount: Decimal,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, list[EntityAccessCheckResult]]:
        """
        Menegakkan aturan untuk transfer antar entitas.

        Args:
            from_entity_id: Entitas asal
            to_entity_id: Entitas tujuan
            amount: Jumlah transfer
            user_id: User ID
            raise_on_violation: Raise exception jika violation

        Returns:
            (is_allowed, list_of_check_results)
        """
        results: list[EntityAccessCheckResult] = []

        # Check access to from_entity (WRITE karena akan mengurangi saldo)
        result_from = await self.check_entity_access(from_entity_id, user_id, "WRITE")
        results.append(result_from)

        # Check access to to_entity (WRITE karena akan menambah saldo)
        result_to = await self.check_entity_access(to_entity_id, user_id, "WRITE")
        results.append(result_to)

        is_allowed = result_from.is_allowed and result_to.is_allowed

        if not is_allowed and raise_on_violation:
            raise LegalEntityBoundaryError(
                message=f"Cross-entity transfer from {from_entity_id} to {to_entity_id} not authorized",
                target_entity_id=str(to_entity_id),
                severity=GuardSeverity.HIGH,
                details={
                    "from_result": result_from.to_dict(),
                    "to_result": result_to.to_dict(),
                    "amount": str(amount),
                },
            )

        return is_allowed, results

    async def enforce_consolidation(
        self,
        parent_entity_id: UUID,
        child_entity_ids: list[UUID],
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, list[EntityAccessCheckResult]]:
        """
        Menegakkan aturan untuk konsolidasi entitas (parent mengakses anak).

        Args:
            parent_entity_id: Entitas induk
            child_entity_ids: Daftar entitas anak
            user_id: User ID
            raise_on_violation: Raise exception jika violation

        Returns:
            (is_allowed, list_of_check_results)
        """
        results: list[EntityAccessCheckResult] = []

        # Check access to parent (READ)
        result_parent = await self.check_entity_access(parent_entity_id, user_id, "CONSOLIDATE")
        results.append(result_parent)

        all_allowed = result_parent.is_allowed
        for child_id in child_entity_ids:
            # Check cross-entity access from parent to child for consolidation
            result_child = await self.check_entity_access(
                child_id, user_id, "CONSOLIDATE", source_entity_id=parent_entity_id
            )
            results.append(result_child)
            if not result_child.is_allowed:
                all_allowed = False
                if raise_on_violation:
                    break

        if not all_allowed and raise_on_violation:
            raise LegalEntityBoundaryError(
                message="Consolidation access not authorized for some entities",
                target_entity_id=str(parent_entity_id),
                severity=GuardSeverity.MEDIUM,
                details={"results": [r.to_dict() for r in results]},
            )

        return all_allowed, results

    def get_check_history(
        self,
        limit: int = 100,
        only_denied: bool = False,
        user_id: str | None = None,
        entity_id: UUID | None = None,
        operation: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[EntityAccessCheckResult]:
        """Mendapatkan history pemeriksaan akses entitas."""
        with self._lock:
            results = self._check_history[-limit:]

        if only_denied:
            results = [r for r in results if not r.is_allowed]
        if user_id:
            results = [r for r in results if r.user_id == user_id]
        if entity_id:
            results = [r for r in results if r.target_entity_id == entity_id]
        if operation:
            results = [r for r in results if r.operation == operation]
        if start_date:
            results = [r for r in results if r.timestamp >= start_date]
        if end_date:
            results = [r for r in results if r.timestamp <= end_date]

        return results

    def get_statistics(self) -> dict[str, Any]:
        """Mendapatkan statistik entity boundary guard."""
        with self._lock:
            total = len(self._check_history)
            if total == 0:
                return {
                    "total_checks": 0,
                    "enabled": self._enabled,
                    "strict_mode": self._strict_mode,
                    "version": self._version,
                }

            denied = [r for r in self._check_history if not r.is_allowed]
            denied_count = len(denied)

            by_severity: dict[str, int] = {}
            for sev in EntityAccessSeverity:
                count = len([r for r in denied if r.severity == sev])
                if count > 0:
                    by_severity[sev.name] = count

            by_operation: dict[str, int] = {}
            for r in denied:
                op = r.operation
                by_operation[op] = by_operation.get(op, 0) + 1

            cross_entity_attempts = len(
                [
                    r
                    for r in self._check_history
                    if r.source_entity_id and r.source_entity_id != r.target_entity_id
                ]
            )
            cross_entity_denied = len(
                [
                    r
                    for r in denied
                    if r.source_entity_id and r.source_entity_id != r.target_entity_id
                ]
            )

            return {
                "total_checks": total,
                "denied_count": denied_count,
                "denial_rate": denied_count / total if total > 0 else 0,
                "by_severity": by_severity,
                "by_operation": by_operation,
                "cross_entity_attempts": cross_entity_attempts,
                "cross_entity_denied": cross_entity_denied,
                "strict_mode": self._strict_mode,
                "enabled": self._enabled,
                "allowed_cross_entity_operations": list(self._allowed_cross_entity_operations),
                "cache_size": len(self._cache),
                "version": self._version,
                "latest_check": self._check_history[-1].timestamp.isoformat()
                if self._check_history
                else None,
            }

    def reset(self) -> None:
        """Reset history dan cache (untuk testing)."""
        with self._lock:
            self._check_history = []
            self._cache.clear()
            self._version += 1
            self._audit_trail = []


# === 4. SINGLETON ACCESSOR ===

_legal_entity_boundary_guard_instance: LegalEntityBoundaryGuard | None = None
_lock_instance = threading.Lock()


def get_legal_entity_boundary_guard() -> LegalEntityBoundaryGuard:
    """Mendapatkan instance singleton LegalEntityBoundaryGuard."""
    global _legal_entity_boundary_guard_instance
    if _legal_entity_boundary_guard_instance is None:
        with _lock_instance:
            if _legal_entity_boundary_guard_instance is None:
                _legal_entity_boundary_guard_instance = LegalEntityBoundaryGuard()
    return _legal_entity_boundary_guard_instance


# === 5. EXPORTS ===

__all__ = [
    "EntityAccessCheckResult",
    "EntityAccessOperation",
    "EntityAccessSeverity",
    "LegalEntityBoundaryGuard",
    "get_legal_entity_boundary_guard",
]
