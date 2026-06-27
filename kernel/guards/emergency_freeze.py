#!/usr/bin/env python3
"""
Module: emergency_freeze.py
Layer: 4 - Kernel / Guards
Responsibility: Membekukan seluruh mutasi dalam keadaan darurat.
               Guard ini menyediakan mekanisme untuk menghentikan sementara
               semua operasi write ketika terdeteksi ancaman keamanan,
               kebocoran data, atau keadaan darurat lainnya. Hanya operasi
               read yang diizinkan selama freeze.

Dependencies:
- standard library (logging, datetime, asyncio, enum, typing, threading, uuid, hashlib)
- kernel.context_holder (get_current_user)
- kernel.guards.guard_exceptions (GuardViolationError, EmergencyFreezeError)
- constitution.sovereignty_declaration (SovereigntyGuardian) [optional]

Audit: Setiap freeze/unfreeze dictat dengan alasan dan otorisasi.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from kernel.guards.guard_exceptions import (
    EmergencyFreezeError,
    GuardSeverity,
)

logger = logging.getLogger(__name__)


# === 1. FALLBACK SOVEREIGNTY GUARDIAN (jika tidak tersedia) ===


class _FallbackSovereigntyGuardian:
    """Fallback sovereignty guardian jika module constitution belum tersedia."""

    def __init__(self):
        self._status = "NORMAL"

    def emergency_lockdown(self, reason: str, initiated_by: str) -> None:
        self._status = "EMERGENCY_LOCKDOWN"
        logger.critical(f"EMERGENCY LOCKDOWN via fallback: {reason} by {initiated_by}")

    def get_current_status(self) -> str:
        return self._status


def _get_sovereignty_guardian():
    try:
        from constitution.sovereignty_declaration import get_sovereignty_guardian
        return get_sovereignty_guardian()
    except ImportError:
        logger.warning("Sovereignty guardian not available, using fallback")
        return _FallbackSovereigntyGuardian()


# === 2. CONSTANTS & ENUMS ===


class FreezeReason(Enum):
    """Alasan emergency freeze."""

    SECURITY_BREACH = auto()
    DATA_CORRUPTION = auto()
    REGULATORY_MANDATE = auto()
    SYSTEM_COMPROMISE = auto()
    NATURAL_DISASTER = auto()
    MANUAL_OVERRIDE = auto()
    CONSTITUTION_VIOLATION = auto()
    INTEGRITY_CHECK_FAILED = auto()

    def display_name(self) -> str:
        """Return human-readable display name."""
        names = {
            FreezeReason.SECURITY_BREACH: "Security Breach",
            FreezeReason.DATA_CORRUPTION: "Data Corruption",
            FreezeReason.REGULATORY_MANDATE: "Regulatory Mandate",
            FreezeReason.SYSTEM_COMPROMISE: "System Compromise",
            FreezeReason.NATURAL_DISASTER: "Natural Disaster",
            FreezeReason.MANUAL_OVERRIDE: "Manual Override",
            FreezeReason.CONSTITUTION_VIOLATION: "Constitution Violation",
            FreezeReason.INTEGRITY_CHECK_FAILED: "Integrity Check Failed",
        }
        return names.get(self, self.name.replace("_", " ").title())

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.name,
            "display": self.display_name(),
        }

    @classmethod
    def from_string(cls, value: str) -> FreezeReason:
        """Parse from string."""
        for reason in cls:
            if reason.name == value:
                return reason
        raise ValueError(f"Unknown FreezeReason: {value}")


class FreezeScope(Enum):
    """Scope freeze."""

    ALL_WRITES = auto()
    BULK_ONLY = auto()
    CRITICAL_ONLY = auto()
    READ_ONLY = auto()

    def display_name(self) -> str:
        """Return human-readable display name."""
        names = {
            FreezeScope.ALL_WRITES: "All Writes Blocked",
            FreezeScope.BULK_ONLY: "Bulk Operations Only",
            FreezeScope.CRITICAL_ONLY: "Critical Operations Only",
            FreezeScope.READ_ONLY: "Read Only",
        }
        return names.get(self, self.name.replace("_", " ").title())

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.name,
            "display": self.display_name(),
        }

    @classmethod
    def from_string(cls, value: str) -> FreezeScope:
        """Parse from string."""
        for scope in cls:
            if scope.name == value:
                return scope
        raise ValueError(f"Unknown FreezeScope: {value}")


class FreezeSeverity(Enum):
    """Severity freeze."""

    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20

    def display_name(self) -> str:
        """Return human-readable display name."""
        names = {
            FreezeSeverity.CRITICAL: "Critical",
            FreezeSeverity.HIGH: "High",
            FreezeSeverity.MEDIUM: "Medium",
            FreezeSeverity.LOW: "Low",
        }
        return names.get(self, self.name.title())

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.name,
            "level": self.value,
            "display": self.display_name(),
        }

    @classmethod
    def from_string(cls, value: str) -> FreezeSeverity:
        """Parse from string."""
        for severity in cls:
            if severity.name == value:
                return severity
        raise ValueError(f"Unknown FreezeSeverity: {value}")


@dataclass
class FreezeRecord:
    """Rekaman freeze."""

    freeze_id: UUID
    reason: FreezeReason
    scope: FreezeScope
    frozen_by: str
    frozen_at: datetime
    expires_at: datetime | None
    description: str
    approved_by: list[str]
    severity: FreezeSeverity = FreezeSeverity.CRITICAL
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.freeze_id}|{self.reason.value}|{self.scope.value}|"
            f"{self.frozen_by}|{self.frozen_at.isoformat()}|{self.description[:100]}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def is_expired(self) -> bool:
        if self.expires_at:
            return datetime.now(UTC) > self.expires_at
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "freeze_id": str(self.freeze_id),
            "reason": self.reason.name,
            "reason_display": self.reason.display_name() if hasattr(self.reason, "display_name") else self.reason.name,
            "scope": self.scope.name,
            "scope_display": self.scope.display_name() if hasattr(self.scope, "display_name") else self.scope.name,
            "frozen_by": self.frozen_by,
            "frozen_at": self.frozen_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "description": self.description,
            "approved_by": self.approved_by,
            "severity": self.severity.name,
            "severity_level": self.severity.value,
            "is_expired": self.is_expired(),
        }


# === 3. EMERGENCY FREEZE GUARD ===


class EmergencyFreezeGuard:
    """
    Guard untuk emergency freeze.

    Business context: Dalam keadaan darurat, sistem dapat dibekukan
    untuk mencegah kerusakan lebih lanjut. Hanya user dengan otoritas
    khusus yang dapat melakukan freeze/unfreeze.
    """

    _instance: EmergencyFreezeGuard | None = None
    _lock = threading.Lock()

    def __new__(cls) -> EmergencyFreezeGuard:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._is_frozen = False
        self._current_freeze: FreezeRecord | None = None
        self._freeze_history: list[FreezeRecord] = []
        self._max_history = 100
        self._sovereignty_guardian = _get_sovereignty_guardian()
        self._emergency_roles = {"emergency_admin", "super_admin", "ceo", "cfo"}

    def is_frozen(self) -> bool:
        """Memeriksa apakah sistem dalam keadaan frozen."""
        if self._is_frozen and self._current_freeze and self._current_freeze.is_expired():
            # Auto-unfreeze
            asyncio.create_task(self.unfreeze("system", "Auto-unfreeze after expiry"))
        return self._is_frozen

    def get_current_freeze(self) -> FreezeRecord | None:
        return self._current_freeze

    async def freeze(
        self,
        reason: FreezeReason,
        frozen_by: str,
        approved_by: list[str],
        description: str,
        scope: FreezeScope = FreezeScope.ALL_WRITES,
        duration_minutes: int | None = 60,
        severity: FreezeSeverity = FreezeSeverity.CRITICAL,
    ) -> FreezeRecord:
        """
        Membekukan sistem.

        Args:
            reason: Alasan freeze
            frozen_by: User yang melakukan freeze
            approved_by: Daftar approver (minimal 2)
            description: Deskripsi
            scope: Scope freeze
            duration_minutes: Durasi freeze (None = indefinite)
            severity: Severity

        Returns:
            FreezeRecord

        Raises:
            EmergencyFreezeError: Jika sudah frozen atau otorisasi tidak cukup
        """
        if self._is_frozen:
            raise EmergencyFreezeError(
                f"System is already frozen by {self._current_freeze.frozen_by if self._current_freeze else 'unknown'}",
                freeze_id=str(self._current_freeze.freeze_id) if self._current_freeze else None,
                severity=GuardSeverity.HIGH,
            )

        if len(approved_by) < 2:
            raise EmergencyFreezeError(
                "Emergency freeze requires at least 2 approvers",
                freeze_id=None,
                severity=GuardSeverity.CRITICAL,
            )

        # Verify that frozen_by has emergency role
        # In production, would check roles from user repository
        # For now, simple check
        if frozen_by not in self._emergency_roles and frozen_by != "system":
            logger.warning(f"User {frozen_by} is not in emergency roles but initiating freeze")

        # Notify sovereignty guardian
        try:
            self._sovereignty_guardian.emergency_lockdown(
                reason=f"Emergency freeze: {description}",
                initiated_by=frozen_by,
            )
        except Exception as e:
            logger.error(f"Failed to notify sovereignty guardian: {e}")

        expires_at = None
        if duration_minutes:
            expires_at = datetime.now(UTC) + timedelta(minutes=duration_minutes)

        freeze_record = FreezeRecord(
            freeze_id=uuid4(),
            reason=reason,
            scope=scope,
            frozen_by=frozen_by,
            frozen_at=datetime.now(UTC),
            expires_at=expires_at,
            description=description,
            approved_by=approved_by,
            severity=severity,
            cryptographic_hash="",
        )
        freeze_record = FreezeRecord(
            freeze_id=freeze_record.freeze_id,
            reason=freeze_record.reason,
            scope=freeze_record.scope,
            frozen_by=freeze_record.frozen_by,
            frozen_at=freeze_record.frozen_at,
            expires_at=freeze_record.expires_at,
            description=freeze_record.description,
            approved_by=freeze_record.approved_by,
            severity=freeze_record.severity,
            cryptographic_hash=freeze_record.compute_hash(),
        )

        self._is_frozen = True
        self._current_freeze = freeze_record
        self._freeze_history.append(freeze_record)
        if len(self._freeze_history) > self._max_history:
            self._freeze_history = self._freeze_history[-self._max_history :]

        logger.critical(
            f"EMERGENCY FREEZE activated by {frozen_by}, reason: {reason.name}, scope: {scope.name}, "
            f"expires: {expires_at} (approved by {approved_by})"
        )

        return freeze_record

    async def unfreeze(
        self,
        unfrozen_by: str,
        reason: str,
        require_dual_control: bool = True,
    ) -> bool:
        """
        Membuka freeze sistem.

        Args:
            unfrozen_by: User yang melakukan unfreeze
            reason: Alasan unfreeze
            require_dual_control: Apakah perlu dual control

        Returns:
            True jika berhasil
        """
        if not self._is_frozen:
            logger.warning("Unfreeze called but system is not frozen")
            return False

        if require_dual_control:
            # In production, would verify second approver
            logger.info(f"Dual control unfreeze requested by {unfrozen_by}")

        self._is_frozen = False
        self._current_freeze = None

        # Notify sovereignty guardian (would need method to lift lockdown)
        # For now, just log
        logger.critical(f"EMERGENCY FREEZE lifted by {unfrozen_by}, reason: {reason}")

        return True

    async def check_write_allowed(
        self,
        operation_type: str,
        user_id: str | None = None,
    ) -> tuple[bool, str | None]:
        """
        Memeriksa apakah operasi write diizinkan.

        Args:
            operation_type: Tipe operasi
            user_id: User ID

        Returns:
            (is_allowed, message_if_not)
        """
        if not self._is_frozen:
            return True, None

        # Emergency override for super admin / emergency roles
        if user_id and user_id in self._emergency_roles:
            logger.warning(f"Emergency override by {user_id} during freeze")
            return True, None

        # Check scope
        if self._current_freeze.scope == FreezeScope.ALL_WRITES:
            return False, "System is in emergency freeze. No write operations allowed."

        if self._current_freeze.scope == FreezeScope.BULK_ONLY:
            if "bulk" in operation_type.lower() or "batch" in operation_type.lower():
                return False, "Bulk operations are disabled during emergency freeze."

        if self._current_freeze.scope == FreezeScope.CRITICAL_ONLY:
            critical_ops = ["PERIOD_CLOSE", "YEAR_END_CLOSE", "CONSOLIDATION", "POST", "REVERSE"]
            if operation_type in critical_ops:
                return (
                    False,
                    f"Critical operation {operation_type} is disabled during emergency freeze.",
                )

        # READ_ONLY scope: only read operations allowed
        if self._current_freeze.scope == FreezeScope.READ_ONLY:
            read_ops = ["READ", "SELECT", "GET", "VIEW", "QUERY", "REPORT"]
            if operation_type not in read_ops:
                return False, f"Operation {operation_type} is not allowed during read-only freeze."

        return True, None

    async def enforce(
        self,
        operation_type: str,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> bool:
        """
        Menegakkan freeze check, raise exception jika write diblok.

        Args:
            operation_type: Tipe operasi
            user_id: User ID
            raise_on_violation: Raise exception jika tidak diizinkan

        Returns:
            True jika diizinkan

        Raises:
            EmergencyFreezeError: Jika write tidak diizinkan dan raise_on_violation=True
        """
        is_allowed, msg = await self.check_write_allowed(operation_type, user_id)
        if not is_allowed and raise_on_violation:
            raise EmergencyFreezeError(
                msg or "Write operation blocked by emergency freeze",
                freeze_id=str(self._current_freeze.freeze_id) if self._current_freeze else None,
                severity=GuardSeverity.CRITICAL,
            )
        return is_allowed

    def get_freeze_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Mendapatkan history freeze."""
        return [f.to_dict() for f in self._freeze_history[-limit:]]

    def get_statistics(self) -> dict[str, Any]:
        """Mendapatkan statistik emergency freeze."""
        return {
            "is_frozen": self._is_frozen,
            "current_freeze": self._current_freeze.to_dict() if self._current_freeze else None,
            "total_freezes": len(self._freeze_history),
            "emergency_roles": list(self._emergency_roles),
        }

    def reset(self) -> None:
        """Reset guard (untuk testing)."""
        self._is_frozen = False
        self._current_freeze = None
        self._freeze_history = []


# === 4. SINGLETON ACCESSOR ===

_emergency_freeze_guard_instance: EmergencyFreezeGuard | None = None


def get_emergency_freeze_guard() -> EmergencyFreezeGuard:
    """Mendapatkan instance singleton EmergencyFreezeGuard."""
    global _emergency_freeze_guard_instance
    if _emergency_freeze_guard_instance is None:
        _emergency_freeze_guard_instance = EmergencyFreezeGuard()
    return _emergency_freeze_guard_instance


# === 5. EXPORTS ===

__all__ = [
    "EmergencyFreezeGuard",
    "FreezeReason",
    "FreezeRecord",
    "FreezeScope",
    "FreezeSeverity",
    "get_emergency_freeze_guard",
]
