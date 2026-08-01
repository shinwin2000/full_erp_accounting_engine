#!/usr/bin/env python3
"""
Module: sod_enforcer.py
Layer: 4 - Kernel / Guards
Responsibility: Penegakan pemisahan tugas (Segregation of Duties - SoD).
               Memastikan bahwa tidak ada konflik kepentingan dalam proses
               akuntansi. Contoh: user yang membuat transaksi tidak boleh
               menyetujui transaksi yang sama (maker-checker principle).

Dependencies:
- standard library (logging, typing, dataclass, enum, threading, uuid, hashlib)
- kernel.context_holder (get_current_user)
- kernel.guards.guard_exceptions (GuardViolationError, SODEnforcerError, GuardSeverity)

Audit: Setiap pelanggaran SoD dicatat untuk audit compliance.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_user
from kernel.guards.guard_exceptions import (
    GuardSeverity,
    SODEnforcerError,
)

logger = logging.getLogger(__name__)


# === 1. FALLBACK USER REPOSITORY (internal, tidak mengimpor adapters/infrastructure) ===


class _FallbackUserRepository:
    """Fallback user repository jika infrastructure belum tersedia.
    Menyimpan data user, roles, dan permissions dalam memory.
    """

    def __init__(self):
        self._user_roles: dict[str, list[str]] = {
            "maker": ["maker"],
            "checker": ["checker", "maker"],
            "poster": ["poster", "checker", "maker"],
            "auditor": ["auditor"],
            "admin": ["admin"],
            "super_admin": ["super_admin", "admin"],
            "treasury": ["treasury"],
            "ar_clerk": ["ar_clerk"],
            "ap_clerk": ["ap_clerk"],
            "cashier": ["cashier"],
            "cfo": ["cfo"],
            "ceo": ["ceo"],
            "finance_manager": ["finance_manager"],
            "budget_creator": ["budget_creator"],
            "budget_approver": ["budget_approver"],
        }
        self._user_entities: dict[str, list[UUID]] = {}
        # Approval limits stored as Decimal for monetary precision
        self._user_approval_limits: dict[str, dict[str, Decimal]] = {}

    async def get_roles(self, user_id: str) -> list[str]:
        return self._user_roles.get(user_id, ["guest"])

    async def get_legal_entities(self, user_id: str) -> list[UUID]:
        return self._user_entities.get(user_id, [])

    async def get_approval_limit(self, user_id: str, transaction_type: str) -> Decimal | None:
        limits = self._user_approval_limits.get(user_id, {})
        return limits.get(transaction_type)

    async def set_user_roles(self, user_id: str, roles: list[str]) -> None:
        self._user_roles[user_id] = roles

    async def set_user_approval_limit(
        self, user_id: str, transaction_type: str, limit: Decimal
    ) -> None:
        if user_id not in self._user_approval_limits:
            self._user_approval_limits[user_id] = {}
        self._user_approval_limits[user_id][transaction_type] = limit

    def add_user_entity(self, user_id: str, entity_id: UUID) -> None:
        if user_id not in self._user_entities:
            self._user_entities[user_id] = []
        if entity_id not in self._user_entities[user_id]:
            self._user_entities[user_id].append(entity_id)


# === 2. CONSTANTS & ENUMS ===


class SODRuleType(Enum):
    """Jenis aturan SoD."""

    MAKER_CHECKER = auto()
    CONFLICTING_ROLES = auto()
    TRANSACTION_LIMIT = auto()
    DUAL_CONTROL = auto()
    FOUR_EYES = auto()
    TIME_BASED = auto()


class SODSeverity(Enum):
    """Severity pelanggaran SoD."""

    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20


@dataclass
class SODRule:
    """Definisi aturan SoD."""

    rule_id: str
    rule_type: SODRuleType
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True
    severity: SODSeverity = SODSeverity.HIGH
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    modified_at: datetime | None = None
    modified_by: str | None = None
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.rule_id}|{self.rule_type.value}|{self.severity.value}|{self.description[:100]}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type.name,
            "description": self.description,
            "parameters": self.parameters,
            "is_active": self.is_active,
            "severity": self.severity.name,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
        }


@dataclass
class SODViolation:
    """Rekaman pelanggaran SoD."""

    violation_id: UUID
    rule_id: str
    rule_type: SODRuleType
    severity: SODSeverity
    user_id: str
    transaction_id: UUID | None
    legal_entity_id: UUID | None
    message: str
    details: dict[str, Any]
    detected_at: datetime
    is_resolved: bool = False
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_action: str | None = None
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.violation_id}|{self.rule_id}|{self.rule_type.value}|{self.severity.value}|"
            f"{self.user_id}|{self.transaction_id}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def resolve(self, resolved_by: str, action: str) -> SODViolation:
        """Menandai pelanggaran sebagai resolved."""
        return SODViolation(
            violation_id=self.violation_id,
            rule_id=self.rule_id,
            rule_type=self.rule_type,
            severity=self.severity,
            user_id=self.user_id,
            transaction_id=self.transaction_id,
            legal_entity_id=self.legal_entity_id,
            message=self.message,
            details=self.details,
            detected_at=self.detected_at,
            is_resolved=True,
            resolved_at=datetime.now(UTC),
            resolved_by=resolved_by,
            resolution_action=action,
            cryptographic_hash=self.cryptographic_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_id": str(self.violation_id),
            "rule_id": self.rule_id,
            "rule_type": self.rule_type.name,
            "severity": self.severity.name,
            "user_id": self.user_id,
            "transaction_id": str(self.transaction_id) if self.transaction_id else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "message": self.message,
            "detected_at": self.detected_at.isoformat(),
            "is_resolved": self.is_resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
        }


# === 3. DEFAULT SOD RULES ===

DEFAULT_SOD_RULES: list[SODRule] = [
    SODRule(
        rule_id="SOD_001",
        rule_type=SODRuleType.MAKER_CHECKER,
        description="Maker cannot approve own transaction",
        parameters={
            "transaction_types": ["JOURNAL", "PAYMENT", "INVOICE", "PURCHASE_ORDER", "SALES_ORDER"]
        },
        severity=SODSeverity.CRITICAL,
    ),
    SODRule(
        rule_id="SOD_002",
        rule_type=SODRuleType.CONFLICTING_ROLES,
        description="User cannot have both AR and Cashier roles simultaneously",
        parameters={"conflicting_roles": ["ar_clerk", "cashier"]},
        severity=SODSeverity.HIGH,
    ),
    SODRule(
        rule_id="SOD_003",
        rule_type=SODRuleType.CONFLICTING_ROLES,
        description="User cannot have both AP and Treasury roles simultaneously",
        parameters={"conflicting_roles": ["ap_clerk", "treasury"]},
        severity=SODSeverity.HIGH,
    ),
    SODRule(
        rule_id="SOD_004",
        rule_type=SODRuleType.CONFLICTING_ROLES,
        description="User cannot have both Maker and Checker roles simultaneously",
        parameters={"conflicting_roles": ["maker", "checker"]},
        severity=SODSeverity.CRITICAL,
    ),
    SODRule(
        rule_id="SOD_005",
        rule_type=SODRuleType.TRANSACTION_LIMIT,
        description="Transaction above 1B requires CFO approval",
        parameters={"threshold": Decimal("1000000000"), "required_role": "cfo"},
        severity=SODSeverity.CRITICAL,
    ),
    SODRule(
        rule_id="SOD_006",
        rule_type=SODRuleType.TRANSACTION_LIMIT,
        description="Transaction above 5B requires CEO + CFO approval (dual)",
        parameters={"threshold": Decimal("5000000000"), "required_roles": ["ceo", "cfo"]},
        severity=SODSeverity.CRITICAL,
    ),
    SODRule(
        rule_id="SOD_007",
        rule_type=SODRuleType.TRANSACTION_LIMIT,
        description="Transaction above 100M requires Manager approval",
        parameters={"threshold": Decimal("100000000"), "required_role": "finance_manager"},
        severity=SODSeverity.HIGH,
    ),
    SODRule(
        rule_id="SOD_008",
        rule_type=SODRuleType.DUAL_CONTROL,
        description="Period closing requires two approvers",
        parameters={
            "transaction_types": ["PERIOD_CLOSE", "YEAR_END_CLOSE"],
            "required_approvers": 2,
        },
        severity=SODSeverity.CRITICAL,
    ),
    SODRule(
        rule_id="SOD_009",
        rule_type=SODRuleType.DUAL_CONTROL,
        description="Asset disposal requires two approvers",
        parameters={
            "transaction_types": ["ASSET_DISPOSAL", "ASSET_WRITE_OFF"],
            "required_approvers": 2,
        },
        severity=SODSeverity.HIGH,
    ),
    SODRule(
        rule_id="SOD_010",
        rule_type=SODRuleType.DUAL_CONTROL,
        description="Bank reconciliation approval requires two approvers",
        parameters={"transaction_types": ["BANK_RECONCILIATION"], "required_approvers": 2},
        severity=SODSeverity.HIGH,
    ),
    SODRule(
        rule_id="SOD_011",
        rule_type=SODRuleType.CONFLICTING_ROLES,
        description="User cannot have both Budget Creator and Budget Approver roles",
        parameters={"conflicting_roles": ["budget_creator", "budget_approver"]},
        severity=SODSeverity.HIGH,
    ),
    SODRule(
        rule_id="SOD_012",
        rule_type=SODRuleType.MAKER_CHECKER,
        description="Maker cannot reverse own transaction",
        parameters={"transaction_types": ["JOURNAL_REVERSE", "PAYMENT_REVERSAL"]},
        severity=SODSeverity.CRITICAL,
    ),
    SODRule(
        rule_id="SOD_013",
        rule_type=SODRuleType.FOUR_EYES,
        description="Journal posting above 500M requires four eyes principle",
        parameters={
            "transaction_types": ["JOURNAL_POST"],
            "threshold": Decimal("500000000"),
            "required_approvers": 2,
        },
        severity=SODSeverity.HIGH,
    ),
    SODRule(
        rule_id="SOD_014",
        rule_type=SODRuleType.TIME_BASED,
        description="At least 2 hours between create and approve for high-value transactions",
        parameters={
            "transaction_types": ["PAYMENT", "JOURNAL"],
            "threshold": Decimal("100000000"),
            "min_hours": 2,
        },
        severity=SODSeverity.MEDIUM,
    ),
]


# ============================================================================
# BASE SOD ENFORCER (ABSTRACT)
# ============================================================================

class BaseSODEnforcer(ABC):
    """Base contract untuk SOD Enforcer."""

    @abstractmethod
    def enable(self, enabled: bool = True) -> None:
        """Mengaktifkan atau menonaktifkan enforcer."""
        pass

    @abstractmethod
    def set_strict_mode(self, strict: bool = True) -> None:
        """Set strict mode."""
        pass

    @abstractmethod
    def register_rule(self, rule: SODRule) -> None:
        """Mendaftarkan aturan SoD baru."""
        pass

    @abstractmethod
    def get_rule(self, rule_id: str) -> SODRule | None:
        """Mendapatkan aturan SoD berdasarkan ID."""
        pass

    @abstractmethod
    def get_all_rules(self, active_only: bool = True) -> list[SODRule]:
        """Mendapatkan semua aturan SoD."""
        pass

    @abstractmethod
    def update_rule_status(self, rule_id: str, is_active: bool, updated_by: str) -> bool:
        """Mengaktifkan/menonaktifkan aturan SoD."""
        pass

    @abstractmethod
    async def check_maker_checker(
        self,
        creator_user_id: str,
        approver_user_id: str,
        transaction_type: str,
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> tuple[bool, SODViolation | None]:
        """Memeriksa aturan maker-checker."""
        pass

    @abstractmethod
    async def check_conflicting_roles(
        self,
        user_id: str,
        roles: list[str],
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> tuple[bool, list[SODViolation]]:
        """Memeriksa konflik role untuk seorang user."""
        pass

    @abstractmethod
    async def check_transaction_approval_limit(
        self,
        amount: Decimal,
        user_roles: list[str],
        transaction_type: str,
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> tuple[bool, SODViolation | None, list[str]]:
        """Memeriksa batasan approval berdasarkan jumlah transaksi."""
        pass

    @abstractmethod
    async def check_dual_control(
        self,
        transaction_type: str,
        approvers: list[str],
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> tuple[bool, SODViolation | None]:
        """Memeriksa persyaratan dual control."""
        pass

    @abstractmethod
    async def check_time_based(
        self,
        transaction_type: str,
        amount: Decimal,
        created_at: datetime,
        approved_at: datetime,
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> tuple[bool, SODViolation | None]:
        """Memeriksa persyaratan waktu antara pembuatan dan approval."""
        pass

    @abstractmethod
    async def enforce(
        self,
        transaction_type: str,
        amount: Decimal | None = None,
        creator_user_id: str | None = None,
        approver_user_id: str | None = None,
        approvers: list[str] | None = None,
        user_roles: list[str] | None = None,
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        created_at: datetime | None = None,
        approved_at: datetime | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, list[SODViolation]]:
        """Menegakkan semua aturan SoD yang relevan."""
        pass

    @abstractmethod
    def get_violations(
        self,
        limit: int = 100,
        user_id: str | None = None,
        rule_type: SODRuleType | None = None,
        unresolved_only: bool = False,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[SODViolation]:
        """Mendapatkan history pelanggaran SoD."""
        pass

    @abstractmethod
    def resolve_violation(
        self,
        violation_id: UUID,
        resolved_by: str,
        resolution_action: str,
    ) -> SODViolation | None:
        """Menandai pelanggaran sebagai resolved."""
        pass

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        """Mendapatkan statistik SOD enforcer."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset enforcer (untuk testing)."""
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
    def from_dict(cls, data: dict[str, Any]) -> BaseSODEnforcer:
        """Reconstruct dari dictionary."""
        pass

    @abstractmethod
    def clone(self) -> BaseSODEnforcer:
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
    def touch(self, touched_by: str) -> BaseSODEnforcer:
        """Touch instance (increment version)."""
        pass


# ============================================================================
# SOD ENFORCER (CONCRETE)
# ============================================================================

class SODEnforcer(BaseSODEnforcer):
    """
    Guard untuk pemisahan tugas (Segregation of Duties).

    Business context: Memastikan kepatuhan terhadap prinsip SoD yang
    merupakan requirement penting untuk audit (SOX, internal control).
    """

    __slots__ = (
        "_audit_trail",
        "_enabled",
        "_lock",
        "_max_history",
        "_rules",
        "_strict_mode",
        "_user_repo",
        "_version",
        "_violations",
    )

    def __init__(self, user_repository: Any | None = None):
        self._user_repo = user_repository or _FallbackUserRepository()
        self._rules: dict[str, SODRule] = {r.rule_id: r for r in DEFAULT_SOD_RULES}
        self._violations: list[SODViolation] = []
        self._max_history = 10000
        self._lock = threading.RLock()
        self._enabled = True
        self._strict_mode = True  # Jika True, semua aturan ditegakkan; jika False, hanya CRITICAL
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []

    # ==================== SYNC CHECK METHOD (untuk checker compliance) ====================

    def check(self, context: dict) -> list[str]:
        """
        Sync check method untuk compliance checker.
        Memvalidasi context dan mengembalikan daftar error jika ada.
        """
        errors = []
        transaction_type = context.get("transaction_type")
        creator_user_id = context.get("creator_user_id")
        approver_user_id = context.get("approver_user_id")

        if not transaction_type:
            errors.append("transaction_type is required")
        if not creator_user_id:
            errors.append("creator_user_id is required")
        if not approver_user_id:
            errors.append("approver_user_id is required")
        elif creator_user_id == approver_user_id:
            errors.append("creator_user_id and approver_user_id cannot be the same (maker-checker violation)")

        amount = context.get("amount")
        if amount is not None:
            try:
                Decimal(str(amount))
            except Exception:
                errors.append("amount must be a valid number")

        return errors

    # ==================== ENTITY METHODS (wajib) ====================

    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        errors = []
        if self._max_history <= 0:
            errors.append("max_history must be positive")
        if not self._rules:
            errors.append("No rules registered")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "strict_mode": self._strict_mode,
                "rules_count": len(self._rules),
                "active_rules": len([r for r in self._rules.values() if r.is_active]),
                "violations_count": len(self._violations),
                "version": self._version,
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SODEnforcer:
        """Reconstruct dari dictionary."""
        instance = cls()
        instance._enabled = data.get("enabled", True)
        instance._strict_mode = data.get("strict_mode", True)
        instance._max_history = data.get("max_history", 10000)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> SODEnforcer:
        """Clone instance."""
        new_instance = SODEnforcer()
        new_instance._enabled = self._enabled
        new_instance._strict_mode = self._strict_mode
        new_instance._max_history = self._max_history
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        with self._lock:
            return {
                "version": self._version,
                "violations_count": len(self._violations),
                "enabled": self._enabled,
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def version(self) -> int:
        """Dapatkan versi."""
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> SODEnforcer:
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
        """Mengaktifkan atau menonaktifkan enforcer."""
        self._enabled = enabled
        self._record_audit("ENABLE", "system", {"enabled": enabled})
        logger.info(f"SOD enforcer enabled: {enabled}")

    def set_strict_mode(self, strict: bool = True) -> None:
        """Set strict mode."""
        self._strict_mode = strict
        self._record_audit("SET_STRICT_MODE", "system", {"strict": strict})
        logger.info(f"SOD enforcer strict mode: {strict}")

    def register_rule(self, rule: SODRule) -> None:
        """Mendaftarkan aturan SoD baru."""
        rule = SODRule(
            rule_id=rule.rule_id,
            rule_type=rule.rule_type,
            description=rule.description,
            parameters=rule.parameters.copy(),
            is_active=rule.is_active,
            severity=rule.severity,
            created_at=rule.created_at,
            created_by=rule.created_by,
            cryptographic_hash="",
        )
        rule = SODRule(**{**rule.__dict__, "cryptographic_hash": rule.compute_hash()})
        with self._lock:
            self._rules[rule.rule_id] = rule
        self._record_audit("REGISTER_RULE", "system", {"rule_id": rule.rule_id})
        logger.info(f"Registered SOD rule: {rule.rule_id}")

    def get_rule(self, rule_id: str) -> SODRule | None:
        """Mendapatkan aturan SoD berdasarkan ID."""
        return self._rules.get(rule_id)

    def get_all_rules(self, active_only: bool = True) -> list[SODRule]:
        """Mendapatkan semua aturan SoD."""
        with self._lock:
            rules = list(self._rules.values())
        if active_only:
            rules = [r for r in rules if r.is_active]
        return rules

    def update_rule_status(self, rule_id: str, is_active: bool, updated_by: str) -> bool:
        """Mengaktifkan/menonaktifkan aturan SoD."""
        with self._lock:
            if rule_id in self._rules:
                old = self._rules[rule_id]
                new_rule = SODRule(
                    rule_id=old.rule_id,
                    rule_type=old.rule_type,
                    description=old.description,
                    parameters=old.parameters.copy(),
                    is_active=is_active,
                    severity=old.severity,
                    created_at=old.created_at,
                    created_by=old.created_by,
                    modified_at=datetime.now(UTC),
                    modified_by=updated_by,
                    cryptographic_hash=old.cryptographic_hash,
                )
                new_rule = SODRule(
                    **{**new_rule.__dict__, "cryptographic_hash": new_rule.compute_hash()}
                )
                self._rules[rule_id] = new_rule
                self._record_audit("UPDATE_RULE", updated_by, {"rule_id": rule_id, "is_active": is_active})
                logger.info(f"SOD rule {rule_id} active status set to {is_active} by {updated_by}")
                return True
        return False

    async def check_maker_checker(
        self,
        creator_user_id: str,
        approver_user_id: str,
        transaction_type: str,
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> tuple[bool, SODViolation | None]:
        """
        Memeriksa aturan maker-checker.

        Returns:
            (is_compliant, violation_if_any)
        """
        if not self._enabled:
            return True, None

        applicable_rules = [
            r
            for r in self._rules.values()
            if r.rule_type == SODRuleType.MAKER_CHECKER
            and r.is_active
            and transaction_type in r.parameters.get("transaction_types", [])
        ]

        for rule in applicable_rules:
            if creator_user_id == approver_user_id:
                violation = self._create_violation(
                    rule_id=rule.rule_id,
                    rule_type=rule.rule_type,
                    severity=rule.severity,
                    user_id=approver_user_id,
                    transaction_id=transaction_id,
                    legal_entity_id=legal_entity_id,
                    message=f"Maker-checker violation: {creator_user_id} cannot approve their own {transaction_type} transaction",
                    details={
                        "creator": creator_user_id,
                        "approver": approver_user_id,
                        "transaction_type": transaction_type,
                    },
                )
                return False, violation
        return True, None

    async def check_conflicting_roles(
        self,
        user_id: str,
        roles: list[str],
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> tuple[bool, list[SODViolation]]:
        """
        Memeriksa konflik role untuk seorang user.

        Returns:
            (is_compliant, list_of_violations)
        """
        if not self._enabled:
            return True, []

        violations = []
        user_roles_set = set(roles)

        for rule in self._rules.values():
            if rule.rule_type == SODRuleType.CONFLICTING_ROLES and rule.is_active:
                conflicting = set(rule.parameters.get("conflicting_roles", []))
                if conflicting.issubset(user_roles_set):
                    violation = self._create_violation(
                        rule_id=rule.rule_id,
                        rule_type=rule.rule_type,
                        severity=rule.severity,
                        user_id=user_id,
                        transaction_id=transaction_id,
                        legal_entity_id=legal_entity_id,
                        message=f"Role conflict: user has conflicting roles {', '.join(conflicting)} per rule {rule.rule_id}",
                        details={"conflicting_roles": list(conflicting), "user_roles": roles},
                    )
                    violations.append(violation)

        return len(violations) == 0, violations

    async def check_transaction_approval_limit(
        self,
        amount: Decimal,
        user_roles: list[str],
        transaction_type: str,
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> tuple[bool, SODViolation | None, list[str]]:
        """
        Memeriksa batasan approval berdasarkan jumlah transaksi.

        Returns:
            (is_allowed, violation_if_any, required_roles)
        """
        if not self._enabled:
            return True, None, []

        applicable_rules = []
        for r in self._rules.values():
            if r.rule_type == SODRuleType.TRANSACTION_LIMIT and r.is_active:
                threshold = r.parameters.get("threshold")
                if threshold is not None:
                    # Ensure threshold is Decimal
                    if not isinstance(threshold, Decimal):
                        threshold = Decimal(str(threshold))
                    if amount >= threshold:
                        applicable_rules.append(r)

        for rule in applicable_rules:
            required_roles = rule.parameters.get("required_roles", [])
            required_role = rule.parameters.get("required_role")
            if required_role:
                required_roles = [required_role]

            if required_roles:
                has_required = any(role in user_roles for role in required_roles)
                if not has_required:
                    threshold_val = rule.parameters.get("threshold")
                    if not isinstance(threshold_val, Decimal):
                        threshold_val = Decimal(str(threshold_val))
                    violation = self._create_violation(
                        rule_id=rule.rule_id,
                        rule_type=rule.rule_type,
                        severity=rule.severity,
                        user_id=",".join(user_roles),
                        transaction_id=transaction_id,
                        legal_entity_id=legal_entity_id,
                        message=f"Transaction amount {amount} exceeds threshold {threshold_val}. Required role(s): {required_roles}",
                        details={
                            "amount": str(amount),
                            "threshold": str(threshold_val),
                            "required_roles": required_roles,
                            "user_roles": user_roles,
                        },
                    )
                    return False, violation, required_roles

        return True, None, []

    async def check_dual_control(
        self,
        transaction_type: str,
        approvers: list[str],
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> tuple[bool, SODViolation | None]:
        """
        Memeriksa persyaratan dual control.

        Returns:
            (is_compliant, violation_if_any)
        """
        if not self._enabled:
            return True, None

        applicable_rules = [
            r
            for r in self._rules.values()
            if r.rule_type in (SODRuleType.DUAL_CONTROL, SODRuleType.FOUR_EYES)
            and r.is_active
            and transaction_type in r.parameters.get("transaction_types", [])
        ]

        for rule in applicable_rules:
            required = rule.parameters.get("required_approvers", 2)
            unique_approvers = set(approvers)
            if len(unique_approvers) < required:
                violation = self._create_violation(
                    rule_id=rule.rule_id,
                    rule_type=rule.rule_type,
                    severity=rule.severity,
                    user_id=",".join(approvers),
                    transaction_id=transaction_id,
                    legal_entity_id=legal_entity_id,
                    message=f"Transaction {transaction_type} requires {required} different approvers (got {len(unique_approvers)})",
                    details={
                        "transaction_type": transaction_type,
                        "required_approvers": required,
                        "provided_approvers": approvers,
                    },
                )
                return False, violation

        return True, None

    async def check_time_based(
        self,
        transaction_type: str,
        amount: Decimal,
        created_at: datetime,
        approved_at: datetime,
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> tuple[bool, SODViolation | None]:
        """
        Memeriksa persyaratan waktu antara pembuatan dan approval.

        Returns:
            (is_compliant, violation_if_any)
        """
        if not self._enabled:
            return True, None

        applicable_rules = []
        for r in self._rules.values():
            # FIX: SIM102 - Gabungkan kondisi nested if menjadi satu
            if (
                r.rule_type == SODRuleType.TIME_BASED
                and r.is_active
                and transaction_type in r.parameters.get("transaction_types", [])
            ):
                threshold = r.parameters.get("threshold", Decimal(0))
                if not isinstance(threshold, Decimal):
                    threshold = Decimal(str(threshold))
                if amount >= threshold:
                    applicable_rules.append(r)

        for rule in applicable_rules:
            min_hours = rule.parameters.get("min_hours", 2)
            time_diff = (approved_at - created_at).total_seconds() / 3600
            if time_diff < min_hours:
                violation = self._create_violation(
                    rule_id=rule.rule_id,
                    rule_type=rule.rule_type,
                    severity=rule.severity,
                    user_id="",
                    transaction_id=transaction_id,
                    legal_entity_id=legal_entity_id,
                    message=f"Transaction approved too quickly: {time_diff:.1f} hours, minimum {min_hours} hours required",
                    details={
                        "transaction_type": transaction_type,
                        "amount": str(amount),
                        "created_at": created_at.isoformat(),
                        "approved_at": approved_at.isoformat(),
                        "hours_diff": time_diff,
                        "min_hours": min_hours,
                    },
                )
                return False, violation

        return True, None

    async def enforce(
        self,
        transaction_type: str,
        amount: Decimal | None = None,
        creator_user_id: str | None = None,
        approver_user_id: str | None = None,
        approvers: list[str] | None = None,
        user_roles: list[str] | None = None,
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        created_at: datetime | None = None,
        approved_at: datetime | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, list[SODViolation]]:
        """
        Menegakkan semua aturan SoD yang relevan.

        Args:
            transaction_type: Tipe transaksi
            amount: Jumlah transaksi (untuk limit check) - Decimal
            creator_user_id: Pembuat transaksi
            approver_user_id: Approver (untuk maker-checker)
            approvers: Daftar approver (untuk dual control)
            user_roles: Role user yang melakukan operasi
            transaction_id: ID transaksi
            legal_entity_id: Entitas hukum
            created_at: Waktu pembuatan transaksi
            approved_at: Waktu approval
            raise_on_violation: Raise exception untuk violation severity CRITICAL

        Returns:
            (is_compliant, list_of_violations)

        Raises:
            SODEnforcerError: Jika violation CRITICAL dan raise_on_violation=True
        """
        if not self._enabled:
            return True, []

        if creator_user_id is None:
            creator_user_id = get_current_user()

        violations = []

        # Get user roles if not provided
        if user_roles is None and creator_user_id:
            user_roles = await self._user_repo.get_roles(creator_user_id)
        user_roles = user_roles or []

        # 1. Maker-checker check
        if creator_user_id and approver_user_id:
            is_ok, violation = await self.check_maker_checker(
                creator_user_id,
                approver_user_id,
                transaction_type,
                transaction_id,
                legal_entity_id,
            )
            if violation:
                self._record_violation(violation)
                violations.append(violation)

        # 2. Conflicting roles check
        if creator_user_id and user_roles:
            is_ok, conflict_violations = await self.check_conflicting_roles(
                creator_user_id,
                user_roles,
                transaction_id,
                legal_entity_id,
            )
            for v in conflict_violations:
                self._record_violation(v)
                violations.append(v)

        # 3. Transaction approval limit
        if amount is not None:
            is_ok, violation, required_roles = await self.check_transaction_approval_limit(
                amount,
                user_roles,
                transaction_type,
                transaction_id,
                legal_entity_id,
            )
            if violation:
                self._record_violation(violation)
                violations.append(violation)

        # 4. Dual control / Four eyes
        if approvers:
            is_ok, violation = await self.check_dual_control(
                transaction_type,
                approvers,
                transaction_id,
                legal_entity_id,
            )
            if violation:
                self._record_violation(violation)
                violations.append(violation)

        # 5. Time-based check
        if created_at and approved_at and amount is not None:
            is_ok, violation = await self.check_time_based(
                transaction_type,
                amount,
                created_at,
                approved_at,
                transaction_id,
                legal_entity_id,
            )
            if violation:
                self._record_violation(violation)
                violations.append(violation)

        # Raise if any CRITICAL violation (or HIGH if strict mode)
        if raise_on_violation:
            # FIX: F841 - Hapus variabel `critical_severity` yang tidak digunakan
            if self._strict_mode:
                critical_violations = [
                    v for v in violations if v.severity in (SODSeverity.CRITICAL, SODSeverity.HIGH)
                ]
            else:
                critical_violations = [v for v in violations if v.severity == SODSeverity.CRITICAL]

            if critical_violations:
                raise SODEnforcerError(
                    message=f"SOD violation(s): {', '.join(v.message for v in critical_violations[:3])}",
                    rule_id=critical_violations[0].rule_id,
                    severity=GuardSeverity.CRITICAL,
                    details={"violations": [v.to_dict() for v in critical_violations]},
                )

        return len(violations) == 0, violations

    def _create_violation(
        self,
        rule_id: str,
        rule_type: SODRuleType,
        severity: SODSeverity,
        user_id: str,
        transaction_id: UUID | None,
        legal_entity_id: UUID | None,
        message: str,
        details: dict[str, Any],
    ) -> SODViolation:
        """Membuat record pelanggaran SoD."""
        violation = SODViolation(
            violation_id=uuid4(),
            rule_id=rule_id,
            rule_type=rule_type,
            severity=severity,
            user_id=user_id,
            transaction_id=transaction_id,
            legal_entity_id=legal_entity_id,
            message=message,
            details=details,
            detected_at=datetime.now(UTC),
            is_resolved=False,
            cryptographic_hash="",
        )
        violation = SODViolation(
            **{**violation.__dict__, "cryptographic_hash": violation.compute_hash()}
        )
        return violation

    def _record_violation(self, violation: SODViolation) -> None:
        """Mencatat pelanggaran ke history."""
        with self._lock:
            self._violations.append(violation)
            if len(self._violations) > self._max_history:
                self._violations = self._violations[-self._max_history :]
            self._record_audit("VIOLATION", violation.user_id, {
                "violation_id": str(violation.violation_id),
                "rule_id": violation.rule_id,
                "severity": violation.severity.name,
            })

    def get_violations(
        self,
        limit: int = 100,
        user_id: str | None = None,
        rule_type: SODRuleType | None = None,
        unresolved_only: bool = False,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[SODViolation]:
        """Mendapatkan history pelanggaran SoD."""
        with self._lock:
            result = self._violations[-limit:]
        if user_id:
            result = [v for v in result if v.user_id == user_id]
        if rule_type:
            result = [v for v in result if v.rule_type == rule_type]
        if unresolved_only:
            result = [v for v in result if not v.is_resolved]
        if start_date:
            result = [v for v in result if v.detected_at >= start_date]
        if end_date:
            result = [v for v in result if v.detected_at <= end_date]
        return result

    def resolve_violation(
        self,
        violation_id: UUID,
        resolved_by: str,
        resolution_action: str,
    ) -> SODViolation | None:
        """Menandai pelanggaran sebagai resolved."""
        with self._lock:
            for i, v in enumerate(self._violations):
                if v.violation_id == violation_id and not v.is_resolved:
                    resolved = v.resolve(resolved_by, resolution_action)
                    self._violations[i] = resolved
                    self._record_audit("RESOLVE_VIOLATION", resolved_by, {
                        "violation_id": str(violation_id),
                        "action": resolution_action,
                    })
                    logger.info(f"SOD violation {violation_id} resolved by {resolved_by}")
                    return resolved
        return None

    def get_statistics(self) -> dict[str, Any]:
        """Mendapatkan statistik SOD enforcer."""
        with self._lock:
            total = len(self._violations)
            if total == 0:
                return {
                    "total_violations": 0,
                    "enabled": self._enabled,
                    "strict_mode": self._strict_mode,
                    "version": self._version,
                }

            by_rule_type: dict[str, int] = {}
            by_severity: dict[str, int] = {}
            unresolved = 0

            for v in self._violations:
                by_rule_type[v.rule_type.name] = by_rule_type.get(v.rule_type.name, 0) + 1
                by_severity[v.severity.name] = by_severity.get(v.severity.name, 0) + 1
                if not v.is_resolved:
                    unresolved += 1

            by_rule = {}
            for v in self._violations:
                by_rule[v.rule_id] = by_rule.get(v.rule_id, 0) + 1

            return {
                "total_violations": total,
                "unresolved_violations": unresolved,
                "by_rule_type": by_rule_type,
                "by_severity": by_severity,
                "by_rule": by_rule,
                "active_rules": len([r for r in self._rules.values() if r.is_active]),
                "enabled": self._enabled,
                "strict_mode": self._strict_mode,
                "version": self._version,
                "latest_violation": self._violations[-1].detected_at.isoformat()
                if self._violations
                else None,
            }

    def reset(self) -> None:
        """Reset enforcer (untuk testing)."""
        with self._lock:
            self._violations = []
            self._rules = {r.rule_id: r for r in DEFAULT_SOD_RULES}
            self._enabled = True
            self._strict_mode = True
            self._version += 1
            self._audit_trail = []


# === 5. SINGLETON ACCESSOR ===

_sod_enforcer_instance: SODEnforcer | None = None
_lock_instance = threading.Lock()


def get_sod_enforcer() -> SODEnforcer:
    """Mendapatkan instance singleton SODEnforcer."""
    global _sod_enforcer_instance
    if _sod_enforcer_instance is None:
        with _lock_instance:
            if _sod_enforcer_instance is None:
                _sod_enforcer_instance = SODEnforcer()
    return _sod_enforcer_instance


# === 6. ALIAS FOR TEST COMPATIBILITY ===
SoDEnforcer = SODEnforcer  # alias with lowercase 'o' for tests

# ========================================================================
# ALIASES FOR CHECKER COMPATIBILITY (P23)
# ========================================================================

# The checker expects 'SodEnforcer' (case-sensitive) or 'enforce_sod' or 'check_segregation'
SodEnforcer = SODEnforcer  # Alias with lowercase 'o' after S
SegregationOfDutiesGuard = SODEnforcer  # <-- ADDED for test_sox_404_controls.py


def enforce_sod(
    transaction_type: str,
    amount: Decimal | None = None,
    creator_user_id: str | None = None,
    approver_user_id: str | None = None,
    approvers: list[str] | None = None,
    user_roles: list[str] | None = None,
    transaction_id: UUID | None = None,
    legal_entity_id: UUID | None = None,
    created_at: datetime | None = None,
    approved_at: datetime | None = None,
    raise_on_violation: bool = True,
) -> tuple[bool, list[SODViolation]]:
    """
    Wrapper function for checker compatibility.
    Delegates to SODEnforcer.enforce().
    """
    enforcer = get_sod_enforcer()
    return enforcer.enforce(
        transaction_type=transaction_type,
        amount=amount,
        creator_user_id=creator_user_id,
        approver_user_id=approver_user_id,
        approvers=approvers,
        user_roles=user_roles,
        transaction_id=transaction_id,
        legal_entity_id=legal_entity_id,
        created_at=created_at,
        approved_at=approved_at,
        raise_on_violation=raise_on_violation,
    )


def check_segregation(
    transaction_type: str,
    creator_user_id: str,
    approver_user_id: str,
    transaction_id: UUID | None = None,
    legal_entity_id: UUID | None = None,
) -> tuple[bool, SODViolation | None]:
    """
    Simplified checker for maker-checker segregation.
    Delegates to SODEnforcer.check_maker_checker().
    """
    enforcer = get_sod_enforcer()
    return enforcer.check_maker_checker(
        creator_user_id=creator_user_id,
        approver_user_id=approver_user_id,
        transaction_type=transaction_type,
        transaction_id=transaction_id,
        legal_entity_id=legal_entity_id,
    )


# === 7. EXPORTS ===

__all__ = [
    "SODEnforcer",
    "SODRule",
    "SODRuleType",
    "SODSeverity",
    "SODViolation",
    "SegregationOfDutiesGuard",
    "SoDEnforcer",
    "SodEnforcer",
    "check_segregation",
    "enforce_sod",
    "get_sod_enforcer",
]
