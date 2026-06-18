#!/usr/bin/env python3
"""
Module: segregation_of_duties_enforcer.py
Layer: 4 - Kernel / Immutable Laws
Responsibility: Hukum: Segregation of Duties (SoD) tidak boleh dilanggar.
               Memastikan bahwa tidak ada konflik kepentingan dalam proses
               akuntansi, terutama untuk transaksi material. Satu orang tidak
               boleh memiliki kemampuan untuk membuat, menyetujui, dan
               mengeksekusi transaksi yang sama.

Dependencies:
- standard library (hashlib, json, logging, dataclass, datetime, decimal, enum, typing, uuid, threading)
- kernel.context_holder (get_current_user)
- kernel.immutable_laws.law_violation_exceptions (ImmutableLawViolationError, SegregationOfDutiesViolation)

Audit: Setiap pelanggaran SoD dictat.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_user
from kernel.immutable_laws.law_violation_exceptions import (
    LawViolationSeverity,
    SegregationOfDutiesViolation,
)

logger = logging.getLogger(__name__)


# === 1. FALLBACK REPOSITORIES (internal, tidak mengimpor adapters/infrastructure) ===


class _FallbackUserRepository:
    """Fallback user repository dengan in-memory storage."""

    def __init__(self):
        self._user_roles: dict[
            tuple[UUID, str], list[str]
        ] = {}  # (legal_entity_id, user_id) -> roles
        self._user_entities: dict[str, list[UUID]] = {}
        self._user_approval_limits: dict[tuple[UUID, str], dict[str, Decimal]] = {}

    async def get_roles(self, user_id: str, legal_entity_id: UUID) -> list[str]:
        key = (legal_entity_id, user_id)
        return self._user_roles.get(key, ["guest"])

    async def get_legal_entities(self, user_id: str) -> list[UUID]:
        return self._user_entities.get(user_id, [])

    async def get_users_by_role(self, role: str, legal_entity_id: UUID) -> list[str]:
        result = []
        for (le_id, uid), roles in self._user_roles.items():
            if le_id == legal_entity_id and role in roles:
                result.append(uid)
        return result

    async def get_approval_limit(
        self, user_id: str, legal_entity_id: UUID, transaction_type: str
    ) -> Decimal | None:
        key = (legal_entity_id, user_id)
        limits = self._user_approval_limits.get(key, {})
        return limits.get(transaction_type)

    async def set_approval_limit(
        self, user_id: str, legal_entity_id: UUID, transaction_type: str, limit: Decimal
    ) -> None:
        key = (legal_entity_id, user_id)
        if key not in self._user_approval_limits:
            self._user_approval_limits[key] = {}
        self._user_approval_limits[key][transaction_type] = limit

    async def assign_role(self, user_id: str, legal_entity_id: UUID, role: str) -> None:
        key = (legal_entity_id, user_id)
        if key not in self._user_roles:
            self._user_roles[key] = []
        if role not in self._user_roles[key]:
            self._user_roles[key].append(role)

    async def revoke_role(self, user_id: str, legal_entity_id: UUID, role: str) -> None:
        key = (legal_entity_id, user_id)
        if key in self._user_roles and role in self._user_roles[key]:
            self._user_roles[key].remove(role)

    def clear(self) -> None:
        self._user_roles.clear()
        self._user_entities.clear()
        self._user_approval_limits.clear()


class _FallbackApprovalRepository:
    """Fallback approval repository dengan in-memory storage."""

    def __init__(self):
        self._approvals: dict[UUID, list[dict[str, Any]]] = {}

    async def get_by_transaction(
        self, transaction_id: UUID, legal_entity_id: UUID
    ) -> list[dict[str, Any]]:
        return self._approvals.get(transaction_id, [])

    async def get_by_transaction_and_approver(
        self,
        transaction_id: UUID,
        approver_id: str,
        legal_entity_id: UUID,
    ) -> dict[str, Any] | None:
        approvals = self._approvals.get(transaction_id, [])
        for a in approvals:
            if a.get("approver_id") == approver_id:
                return a
        return None

    async def add_approval(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        approver_id: str,
        approval_level: int,
        notes: str | None,
        approved_at: datetime,
    ) -> bool:
        if transaction_id not in self._approvals:
            self._approvals[transaction_id] = []
        self._approvals[transaction_id].append(
            {
                "transaction_id": transaction_id,
                "legal_entity_id": legal_entity_id,
                "approver_id": approver_id,
                "approval_level": approval_level,
                "notes": notes,
                "approved_at": approved_at,
                "status": "APPROVED",
            }
        )
        return True

    def clear(self) -> None:
        self._approvals.clear()


# === 2. CONSTANTS & ENUMS ===


class SODRuleType(Enum):
    MAKER_CHECKER = "maker_checker"
    CONFLICTING_ROLES = "conflicting_roles"
    TRANSACTION_LIMIT = "transaction_limit"
    DUAL_CONTROL = "dual_control"


class SODViolationSeverity(Enum):
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20


@dataclass
class SODRule:
    rule_id: str
    rule_type: SODRuleType
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True
    severity: SODViolationSeverity = SODViolationSeverity.HIGH
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.rule_id}|{self.rule_type.value}|{self.description}|"
            f"{json.dumps(self.parameters, sort_keys=True)}|{self.is_active}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type.value,
            "description": self.description[:100],
            "parameters": self.parameters,
            "is_active": self.is_active,
            "severity": self.severity.name,
        }


@dataclass
class SODViolationRecord:
    violation_id: UUID
    rule_id: str
    rule_type: SODRuleType
    severity: SODViolationSeverity
    user_id: str
    transaction_id: UUID | None
    legal_entity_id: UUID
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
            f"{self.violation_id}|{self.rule_id}|{self.rule_type.value}|"
            f"{self.severity.value}|{self.user_id}|{self.transaction_id}|"
            f"{self.detected_at.isoformat()}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def resolve(self, resolved_by: str, action: str) -> SODViolationRecord:
        return SODViolationRecord(
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
            "rule_type": self.rule_type.value,
            "severity": self.severity.name,
            "user_id": self.user_id,
            "transaction_id": str(self.transaction_id) if self.transaction_id else None,
            "legal_entity_id": str(self.legal_entity_id),
            "message": self.message[:200],
            "detected_at": self.detected_at.isoformat(),
            "is_resolved": self.is_resolved,
        }


# === 3. DEFAULT SOD RULES ===

DEFAULT_SOD_RULES: list[SODRule] = [
    SODRule(
        rule_id="SOD_001",
        rule_type=SODRuleType.MAKER_CHECKER,
        description="Maker cannot approve own transaction",
        parameters={"transaction_types": ["JOURNAL", "PAYMENT", "INVOICE", "PURCHASE_ORDER"]},
        severity=SODViolationSeverity.CRITICAL,
    ),
    SODRule(
        rule_id="SOD_002",
        rule_type=SODRuleType.CONFLICTING_ROLES,
        description="User cannot have both AR and Cashier roles simultaneously",
        parameters={"conflicting_roles": ["ar_clerk", "cashier"]},
        severity=SODViolationSeverity.HIGH,
    ),
    SODRule(
        rule_id="SOD_003",
        rule_type=SODRuleType.CONFLICTING_ROLES,
        description="User cannot have both AP and Treasury roles simultaneously",
        parameters={"conflicting_roles": ["ap_clerk", "treasury"]},
        severity=SODViolationSeverity.HIGH,
    ),
    SODRule(
        rule_id="SOD_004",
        rule_type=SODRuleType.CONFLICTING_ROLES,
        description="User cannot have both Maker and Checker roles simultaneously",
        parameters={"conflicting_roles": ["maker", "checker"]},
        severity=SODViolationSeverity.CRITICAL,
    ),
    SODRule(
        rule_id="SOD_005",
        rule_type=SODRuleType.TRANSACTION_LIMIT,
        description="Transaction above 1B requires CFO approval",
        parameters={"threshold": 1000000000, "required_role": "cfo"},
        severity=SODViolationSeverity.CRITICAL,
    ),
    SODRule(
        rule_id="SOD_006",
        rule_type=SODRuleType.TRANSACTION_LIMIT,
        description="Transaction above 5B requires CEO + CFO approval (dual)",
        parameters={"threshold": 5000000000, "required_roles": ["ceo", "cfo"]},
        severity=SODViolationSeverity.CRITICAL,
    ),
    SODRule(
        rule_id="SOD_007",
        rule_type=SODRuleType.TRANSACTION_LIMIT,
        description="Transaction above 100M requires Manager approval",
        parameters={"threshold": 100000000, "required_role": "finance_manager"},
        severity=SODViolationSeverity.HIGH,
    ),
    SODRule(
        rule_id="SOD_008",
        rule_type=SODRuleType.DUAL_CONTROL,
        description="Period closing requires two approvers",
        parameters={
            "transaction_types": ["PERIOD_CLOSE", "YEAR_END_CLOSE"],
            "required_approvers": 2,
        },
        severity=SODViolationSeverity.CRITICAL,
    ),
    SODRule(
        rule_id="SOD_009",
        rule_type=SODRuleType.DUAL_CONTROL,
        description="Asset disposal requires two approvers",
        parameters={
            "transaction_types": ["ASSET_DISPOSAL", "ASSET_WRITE_OFF"],
            "required_approvers": 2,
        },
        severity=SODViolationSeverity.HIGH,
    ),
    SODRule(
        rule_id="SOD_010",
        rule_type=SODRuleType.DUAL_CONTROL,
        description="Bank reconciliation approval requires two approvers",
        parameters={"transaction_types": ["BANK_RECONCILIATION"], "required_approvers": 2},
        severity=SODViolationSeverity.HIGH,
    ),
    SODRule(
        rule_id="SOD_011",
        rule_type=SODRuleType.CONFLICTING_ROLES,
        description="User cannot have both Budget Creator and Budget Approver roles",
        parameters={"conflicting_roles": ["budget_creator", "budget_approver"]},
        severity=SODViolationSeverity.HIGH,
    ),
    SODRule(
        rule_id="SOD_012",
        rule_type=SODRuleType.MAKER_CHECKER,
        description="Maker cannot reverse own transaction",
        parameters={"transaction_types": ["JOURNAL_REVERSE", "PAYMENT_REVERSAL"]},
        severity=SODViolationSeverity.CRITICAL,
    ),
]


# === 4. SEGREGATION OF DUTIES ENFORCER ===


class SegregationOfDutiesEnforcer:
    """
    Enforcer untuk hukum pemisahan tugas (SoD).

    Business context: Mencegah fraud dengan memastikan tidak ada satu orang
    yang memiliki kontrol penuh atas suatu transaksi dari awal hingga akhir.
    """

    ROLE_CONFLICTS = {
        "maker": ["checker", "approver", "poster"],
        "checker": ["maker", "poster"],
        "poster": ["maker", "checker"],
        "cashier": ["ar_clerk", "ap_clerk"],
        "ar_clerk": ["cashier", "treasury"],
        "ap_clerk": ["cashier", "treasury"],
        "treasury": ["ar_clerk", "ap_clerk"],
        "budget_creator": ["budget_approver"],
        "budget_approver": ["budget_creator"],
    }

    def __init__(
        self,
        user_repository: Any | None = None,
        approval_repository: Any | None = None,
    ):
        self._user_repo = user_repository or _FallbackUserRepository()
        self._approval_repo = approval_repository or _FallbackApprovalRepository()
        self._rules: dict[str, SODRule] = {r.rule_id: r for r in DEFAULT_SOD_RULES}
        self._violations: list[SODViolationRecord] = []
        self._max_history = 10000
        self._lock = threading.RLock()
        self._enabled = True
        self._strict_mode = True

    def enable(self, enabled: bool = True) -> None:
        self._enabled = enabled
        logger.info(f"Segregation of duties enforcer enabled: {enabled}")

    def set_strict_mode(self, strict: bool = True) -> None:
        self._strict_mode = strict
        logger.info(f"Segregation of duties enforcer strict mode: {strict}")

    def register_rule(self, rule: SODRule) -> None:
        with self._lock:
            self._rules[rule.rule_id] = rule
        logger.info(f"Registered SOD rule: {rule.rule_id}")

    def get_rule(self, rule_id: str) -> SODRule | None:
        return self._rules.get(rule_id)

    def get_all_rules(self, active_only: bool = True) -> list[SODRule]:
        with self._lock:
            rules = list(self._rules.values())
        if active_only:
            rules = [r for r in rules if r.is_active]
        return rules

    def update_rule_status(self, rule_id: str, is_active: bool, updated_by: str) -> bool:
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
                    cryptographic_hash="",
                )
                new_rule.cryptographic_hash = new_rule.compute_hash()
                self._rules[rule_id] = new_rule
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
    ) -> tuple[bool, SODViolationRecord | None]:
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
                    rule=rule,
                    user_id=approver_user_id,
                    transaction_id=transaction_id,
                    legal_entity_id=legal_entity_id or UUID(int=0),
                    message=(
                        f"Maker-checker violation: {creator_user_id} cannot approve their own "
                        f"{transaction_type} transaction"
                    ),
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
    ) -> tuple[bool, list[SODViolationRecord]]:
        if not self._enabled:
            return True, []

        violations = []
        user_roles_set = set(roles)

        for rule in self._rules.values():
            if rule.rule_type == SODRuleType.CONFLICTING_ROLES and rule.is_active:
                conflicting = set(rule.parameters.get("conflicting_roles", []))
                if conflicting.issubset(user_roles_set):
                    violation = self._create_violation(
                        rule=rule,
                        user_id=user_id,
                        transaction_id=transaction_id,
                        legal_entity_id=legal_entity_id or UUID(int=0),
                        message=(
                            f"Role conflict: user has conflicting roles {', '.join(conflicting)} "
                            f"per rule {rule.rule_id}"
                        ),
                        details={
                            "conflicting_roles": list(conflicting),
                            "user_roles": roles,
                        },
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
    ) -> tuple[bool, SODViolationRecord | None, list[str]]:
        if not self._enabled:
            return True, None, []

        applicable_rules = [
            r
            for r in self._rules.values()
            if r.rule_type == SODRuleType.TRANSACTION_LIMIT
            and r.is_active
            and amount >= r.parameters.get("threshold", float("inf"))
        ]

        for rule in applicable_rules:
            required_roles = rule.parameters.get("required_roles", [])
            required_role = rule.parameters.get("required_role")
            if required_role:
                required_roles = [required_role]

            if required_roles:
                has_required = any(role in user_roles for role in required_roles)
                if not has_required:
                    violation = self._create_violation(
                        rule=rule,
                        user_id=",".join(user_roles),
                        transaction_id=transaction_id,
                        legal_entity_id=legal_entity_id or UUID(int=0),
                        message=(
                            f"Transaction amount {amount} exceeds threshold {rule.parameters['threshold']}. "
                            f"Required role(s): {required_roles}"
                        ),
                        details={
                            "amount": str(amount),
                            "threshold": rule.parameters["threshold"],
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
    ) -> tuple[bool, SODViolationRecord | None]:
        if not self._enabled:
            return True, None

        applicable_rules = [
            r
            for r in self._rules.values()
            if r.rule_type == SODRuleType.DUAL_CONTROL
            and r.is_active
            and transaction_type in r.parameters.get("transaction_types", [])
        ]

        for rule in applicable_rules:
            required = rule.parameters.get("required_approvers", 2)
            unique_approvers = set(approvers)
            if len(unique_approvers) < required:
                violation = self._create_violation(
                    rule=rule,
                    user_id=",".join(approvers),
                    transaction_id=transaction_id,
                    legal_entity_id=legal_entity_id or UUID(int=0),
                    message=(
                        f"Transaction {transaction_type} requires {required} different approvers "
                        f"(got {len(unique_approvers)})"
                    ),
                    details={
                        "transaction_type": transaction_type,
                        "required_approvers": required,
                        "provided_approvers": approvers,
                    },
                )
                return False, violation
        return True, None

    async def check_role_assignment(
        self,
        user_id: str,
        new_roles: list[str],
        legal_entity_id: UUID,
    ) -> tuple[bool, list[str]]:
        existing_roles = await self._user_repo.get_roles(user_id, legal_entity_id)
        all_roles = set(existing_roles) | set(new_roles)
        conflicts = []
        for role in all_roles:
            conflicting = self.ROLE_CONFLICTS.get(role, [])
            for conf in conflicting:
                if conf in all_roles:
                    conflicts.append(f"Role '{role}' conflicts with '{conf}'")
        return len(conflicts) == 0, conflicts

    def _create_violation(
        self,
        rule: SODRule,
        user_id: str,
        transaction_id: UUID | None,
        legal_entity_id: UUID,
        message: str,
        details: dict[str, Any],
    ) -> SODViolationRecord:
        violation = SODViolationRecord(
            violation_id=uuid4(),
            rule_id=rule.rule_id,
            rule_type=rule.rule_type,
            severity=rule.severity,
            user_id=user_id,
            transaction_id=transaction_id,
            legal_entity_id=legal_entity_id,
            message=message,
            details=details,
            detected_at=datetime.now(UTC),
            is_resolved=False,
            cryptographic_hash="",
        )
        violation.cryptographic_hash = violation.compute_hash()
        return violation

    def _record_violation(self, violation: SODViolationRecord) -> None:
        with self._lock:
            self._violations.append(violation)
            if len(self._violations) > self._max_history:
                self._violations = self._violations[-self._max_history :]

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
        raise_on_violation: bool = True,
    ) -> tuple[bool, list[SODViolationRecord]]:
        if not self._enabled:
            return True, []

        if legal_entity_id is None:
            legal_entity_id = UUID(int=0)

        if creator_user_id is None:
            creator_user_id = get_current_user() or "unknown"

        violations = []

        if user_roles is None and creator_user_id:
            user_roles = await self._user_repo.get_roles(creator_user_id, legal_entity_id)
        user_roles = user_roles or []

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

        if raise_on_violation:
            critical_violations = [
                v for v in violations if v.severity == SODViolationSeverity.CRITICAL
            ]
            if critical_violations:
                first = critical_violations[0]
                raise SegregationOfDutiesViolation(
                    message=first.message,
                    user_id=first.user_id,
                    conflicting_roles=first.details.get("conflicting_roles", []),
                    severity=LawViolationSeverity.CRITICAL,
                    details={"violations": [v.to_dict() for v in critical_violations]},
                )

        return len(violations) == 0, violations

    async def get_sod_status(
        self,
        user_id: str,
        legal_entity_id: UUID,
    ) -> dict[str, Any]:
        roles = await self._user_repo.get_roles(user_id, legal_entity_id)
        is_allowed, conflicts = await self.check_role_assignment(user_id, [], legal_entity_id)
        return {
            "user_id": user_id,
            "legal_entity_id": str(legal_entity_id),
            "roles": roles,
            "has_conflict": not is_allowed,
            "conflicts": conflicts,
            "role_conflict_matrix": {role: self.ROLE_CONFLICTS.get(role, []) for role in roles},
        }

    def get_violations(
        self,
        limit: int = 100,
        user_id: str | None = None,
        rule_id: str | None = None,
        unresolved_only: bool = False,
    ) -> list[SODViolationRecord]:
        with self._lock:
            result = self._violations[-limit:]
        if user_id:
            result = [v for v in result if v.user_id == user_id]
        if rule_id:
            result = [v for v in result if v.rule_id == rule_id]
        if unresolved_only:
            result = [v for v in result if not v.is_resolved]
        return result

    def resolve_violation(
        self,
        violation_id: UUID,
        resolved_by: str,
        resolution_action: str,
    ) -> SODViolationRecord | None:
        with self._lock:
            for i, v in enumerate(self._violations):
                if v.violation_id == violation_id and not v.is_resolved:
                    resolved = v.resolve(resolved_by, resolution_action)
                    self._violations[i] = resolved
                    logger.info(f"SOD violation {violation_id} resolved by {resolved_by}")
                    return resolved
        return None

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._violations)
            if total == 0:
                return {
                    "total_violations": 0,
                    "enabled": self._enabled,
                    "strict_mode": self._strict_mode,
                }

            by_rule_type = {}
            by_severity = {}
            unresolved = 0

            for v in self._violations:
                by_rule_type[v.rule_type.value] = by_rule_type.get(v.rule_type.value, 0) + 1
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
                "latest_violation": self._violations[-1].detected_at.isoformat()
                if self._violations
                else None,
            }

    def reset(self) -> None:
        with self._lock:
            self._violations = []
            self._rules = {r.rule_id: r for r in DEFAULT_SOD_RULES}
            self._enabled = True
            self._strict_mode = True
            if hasattr(self._user_repo, "clear"):
                self._user_repo.clear()
            if hasattr(self._approval_repo, "clear"):
                self._approval_repo.clear()


# === 5. SINGLETON ACCESSOR ===

_segregation_of_duties_enforcer_instance: SegregationOfDutiesEnforcer | None = None
_lock_instance = threading.Lock()


def get_segregation_of_duties_enforcer() -> SegregationOfDutiesEnforcer:
    global _segregation_of_duties_enforcer_instance
    if _segregation_of_duties_enforcer_instance is None:
        with _lock_instance:
            if _segregation_of_duties_enforcer_instance is None:
                _segregation_of_duties_enforcer_instance = SegregationOfDutiesEnforcer()
    return _segregation_of_duties_enforcer_instance


# === 6. EXPORTS ===

__all__ = [
    "SODRule",
    "SODRuleType",
    "SODViolationRecord",
    "SODViolationSeverity",
    "SegregationOfDutiesEnforcer",
    "get_segregation_of_duties_enforcer",
]
