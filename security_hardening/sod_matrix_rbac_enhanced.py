#!/usr/bin/env python3
"""
Module: sod_matrix_rbac_enhanced.py
Layer: Security Hardening

Responsibility:
    Separation of Duties (SOD) matrix dengan RBAC enhanced.
    Mendeteksi konflik tugas berdasarkan role dan permission.
    Mendukung definisi aturan SOD, pemeriksaan konflik, enforcement,
    dan integrasi dengan sistem RBAC existing.

Metode yang ditambahkan:
- Untuk SoDRule: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk SODMatrix: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk RBACEnforcer: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class SODConflictSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    def display_name(self) -> str:
        names = {
            SODConflictSeverity.LOW: "Rendah",
            SODConflictSeverity.MEDIUM: "Sedang",
            SODConflictSeverity.HIGH: "Tinggi",
            SODConflictSeverity.CRITICAL: "Kritis",
        }
        return names.get(self, self.value)


class PermissionType(Enum):
    JOURNAL_CREATE = "journal.create"
    JOURNAL_APPROVE = "journal.approve"
    JOURNAL_POST = "journal.post"
    JOURNAL_REVERSE = "journal.reverse"
    JOURNAL_VOID = "journal.void"
    PAYMENT_CREATE = "payment.create"
    PAYMENT_APPROVE = "payment.approve"
    PAYMENT_EXECUTE = "payment.execute"
    USER_CREATE = "user.create"
    USER_DELETE = "user.delete"
    USER_ASSIGN_ROLE = "user.assign_role"
    USER_REVOKE_ROLE = "user.revoke_role"
    CONFIG_CHANGE = "config.change"
    CONFIG_VIEW = "config.view"
    AUDIT_VIEW = "audit.view"
    AUDIT_EXPORT = "audit.export"
    INVENTORY_RECEIVE = "inventory.receive"
    INVENTORY_ISSUE = "inventory.issue"
    INVENTORY_ADJUST = "inventory.adjust"
    BANK_RECONCILE = "bank.reconcile"
    BANK_ADJUST = "bank.adjust"
    ACCOUNT_CREATE = "account.create"
    ACCOUNT_MODIFY = "account.modify"
    ACCOUNT_DELETE = "account.delete"
    TAX_SUBMIT = "tax.submit"
    TAX_APPROVE = "tax.approve"
    ANY = "*"

    def display_name(self) -> str:
        names = {
            PermissionType.JOURNAL_CREATE: "Buat Jurnal",
            PermissionType.JOURNAL_APPROVE: "Setujui Jurnal",
            PermissionType.JOURNAL_POST: "Posting Jurnal",
            PermissionType.JOURNAL_REVERSE: "Reverse Jurnal",
            PermissionType.JOURNAL_VOID: "Void Jurnal",
            PermissionType.PAYMENT_CREATE: "Buat Pembayaran",
            PermissionType.PAYMENT_APPROVE: "Setujui Pembayaran",
            PermissionType.PAYMENT_EXECUTE: "Eksekusi Pembayaran",
            PermissionType.USER_CREATE: "Buat User",
            PermissionType.USER_DELETE: "Hapus User",
            PermissionType.USER_ASSIGN_ROLE: "Assign Role",
            PermissionType.USER_REVOKE_ROLE: "Revoke Role",
            PermissionType.CONFIG_CHANGE: "Ubah Konfigurasi",
            PermissionType.CONFIG_VIEW: "Lihat Konfigurasi",
            PermissionType.AUDIT_VIEW: "Lihat Audit",
            PermissionType.AUDIT_EXPORT: "Ekspor Audit",
            PermissionType.INVENTORY_RECEIVE: "Terima Barang",
            PermissionType.INVENTORY_ISSUE: "Keluarkan Barang",
            PermissionType.INVENTORY_ADJUST: "Adjust Stock",
            PermissionType.BANK_RECONCILE: "Rekonsiliasi Bank",
            PermissionType.BANK_ADJUST: "Adjust Bank",
            PermissionType.ACCOUNT_CREATE: "Buat Akun",
            PermissionType.ACCOUNT_MODIFY: "Ubah Akun",
            PermissionType.ACCOUNT_DELETE: "Hapus Akun",
            PermissionType.TAX_SUBMIT: "Kirim SPT",
            PermissionType.TAX_APPROVE: "Setujui SPT",
            PermissionType.ANY: "Semua",
        }
        return names.get(self, self.value)


class RoleType(Enum):
    ACCOUNTANT = "accountant"
    ACCOUNTING_MANAGER = "accounting_manager"
    TREASURY = "treasury"
    CONTROLLER = "controller"
    CFO = "cfo"
    INTERNAL_AUDIT = "internal_audit"
    IT_ADMIN = "it_admin"
    TAX_OFFICER = "tax_officer"
    AP_CLERK = "ap_clerk"
    AR_CLERK = "ar_clerk"
    INVENTORY_CLERK = "inventory_clerk"

    def display_name(self) -> str:
        names = {
            RoleType.ACCOUNTANT: "Akuntan",
            RoleType.ACCOUNTING_MANAGER: "Manajer Akuntansi",
            RoleType.TREASURY: "Treasury",
            RoleType.CONTROLLER: "Controller",
            RoleType.CFO: "CFO",
            RoleType.INTERNAL_AUDIT: "Audit Internal",
            RoleType.IT_ADMIN: "Admin IT",
            RoleType.TAX_OFFICER: "Petugas Pajak",
            RoleType.AP_CLERK: "AP Clerk",
            RoleType.AR_CLERK: "AR Clerk",
            RoleType.INVENTORY_CLERK: "Inventory Clerk",
        }
        return names.get(self, self.value)


# ============================================================================
# Exceptions
# ============================================================================
class SODError(Exception):
    pass


class SODViolationError(SODError):
    def __init__(self, message: str, severity: SODConflictSeverity, rule_id: str | None = None):
        super().__init__(message)
        self.severity = severity
        self.rule_id = rule_id


# ============================================================================
# SoDRule Class (dengan entity dasar)
# ============================================================================
@dataclass(kw_only=True)
class SoDRule:
    permission_a: str
    permission_b: str
    severity: SODConflictSeverity
    description: str
    id: str | None = None
    enabled: bool = True

    # Fields untuk audit
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        if self.id is None:
            self.id = hashlib.md5(f"{self.permission_a}:{self.permission_b}".encode()).hexdigest()[
                :12
            ]
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "id": self.id,
                "permission_a": self.permission_a,
                "permission_b": self.permission_b,
                "severity": self.severity.value,
                "enabled": self.enabled,
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
                "rule_id": self.id,
                "details": details,
            }
        )

    def conflicts_with(self, permissions: set[str]) -> tuple[bool, SODConflictSeverity, str]:
        a_in = self.permission_a in permissions or self.permission_a == PermissionType.ANY.value
        b_in = self.permission_b in permissions or self.permission_b == PermissionType.ANY.value
        if a_in and b_in:
            return True, self.severity, self.description
        return False, self.severity, ""

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.permission_a:
            errors.append("permission_a is required")
        if not self.permission_b:
            errors.append("permission_b is required")
        if not isinstance(self.severity, SODConflictSeverity):
            errors.append("Invalid severity")
        if not self.description:
            errors.append("description is required")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "permission_a": self.permission_a,
            "permission_b": self.permission_b,
            "severity": self.severity.value,
            "description": self.description,
            "enabled": self.enabled,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SoDRule:
        instance = cls(
            permission_a=data["permission_a"],
            permission_b=data["permission_b"],
            severity=SODConflictSeverity(data["severity"]),
            description=data["description"],
            id=data.get("id"),
            enabled=data.get("enabled", True),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> SoDRule:
        new = SoDRule(
            permission_a=self.permission_a,
            permission_b=self.permission_b,
            severity=self.severity,
            description=self.description,
            enabled=self.enabled,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self.id})
        return new

    def snapshot(self) -> dict:
        return {
            "version": self._version,
            "id": self.id,
            "permission_a": self.permission_a,
            "permission_b": self.permission_b,
            "severity": self.severity.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> SoDRule:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# SODMatrix Core (dengan entity dasar)
# ============================================================================
class SODMatrix:
    def __init__(self):
        self._rules: dict[str, SoDRule] = {}
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()
        self._init_default_rules()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "rules_count": len(self._rules),
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

    def _init_default_rules(self) -> None:
        default_rules = [
            SoDRule(
                permission_a=PermissionType.JOURNAL_CREATE.value,
                permission_b=PermissionType.JOURNAL_APPROVE.value,
                severity=SODConflictSeverity.CRITICAL,
                description="User cannot both create and approve a journal entry (four-eyes principle)",
            ),
            SoDRule(
                permission_a=PermissionType.JOURNAL_POST.value,
                permission_b=PermissionType.JOURNAL_REVERSE.value,
                severity=SODConflictSeverity.HIGH,
                description="Journal poster cannot reverse a journal without separate approval",
            ),
            SoDRule(
                permission_a=PermissionType.PAYMENT_CREATE.value,
                permission_b=PermissionType.PAYMENT_APPROVE.value,
                severity=SODConflictSeverity.CRITICAL,
                description="User cannot both initiate and approve a payment",
            ),
            SoDRule(
                permission_a=PermissionType.PAYMENT_APPROVE.value,
                permission_b=PermissionType.PAYMENT_EXECUTE.value,
                severity=SODConflictSeverity.HIGH,
                description="Payment approver cannot execute the payment",
            ),
            SoDRule(
                permission_a=PermissionType.USER_CREATE.value,
                permission_b=PermissionType.USER_ASSIGN_ROLE.value,
                severity=SODConflictSeverity.CRITICAL,
                description="User creator cannot assign roles to users",
            ),
            SoDRule(
                permission_a=PermissionType.CONFIG_CHANGE.value,
                permission_b=PermissionType.AUDIT_VIEW.value,
                severity=SODConflictSeverity.CRITICAL,
                description="Configuration changer should not be able to view audit logs",
            ),
            SoDRule(
                permission_a=PermissionType.INVENTORY_RECEIVE.value,
                permission_b=PermissionType.INVENTORY_ISSUE.value,
                severity=SODConflictSeverity.HIGH,
                description="Same user should not both receive and issue inventory",
            ),
            SoDRule(
                permission_a=PermissionType.INVENTORY_ISSUE.value,
                permission_b=PermissionType.INVENTORY_ADJUST.value,
                severity=SODConflictSeverity.HIGH,
                description="Inventory issuer should not also perform adjustments",
            ),
            SoDRule(
                permission_a=PermissionType.BANK_RECONCILE.value,
                permission_b=PermissionType.BANK_ADJUST.value,
                severity=SODConflictSeverity.HIGH,
                description="Bank reconciler cannot adjust bank balance",
            ),
            SoDRule(
                permission_a=PermissionType.ACCOUNT_CREATE.value,
                permission_b=PermissionType.JOURNAL_CREATE.value,
                severity=SODConflictSeverity.MEDIUM,
                description="Account creation combined with journal creation may lead to unauthorized entries",
            ),
            SoDRule(
                permission_a=PermissionType.TAX_SUBMIT.value,
                permission_b=PermissionType.TAX_APPROVE.value,
                severity=SODConflictSeverity.MEDIUM,
                description="Tax submission and approval should be separated",
            ),
            SoDRule(
                permission_a=PermissionType.ACCOUNT_CREATE.value,
                permission_b=PermissionType.ACCOUNT_DELETE.value,
                severity=SODConflictSeverity.HIGH,
                description="Account creator should not be able to delete accounts",
            ),
            SoDRule(
                permission_a=PermissionType.AUDIT_VIEW.value,
                permission_b=PermissionType.AUDIT_EXPORT.value,
                severity=SODConflictSeverity.LOW,
                description="Audit view and export are allowed together but logged",
            ),
        ]
        for rule in default_rules:
            self.add_rule(rule)

    def add_rule(self, rule: SoDRule) -> None:
        if rule.id in self._rules:
            logger.warning(f"Rule with id {rule.id} already exists, skipping")
            return
        for existing in self._rules.values():
            if (
                existing.permission_a == rule.permission_a
                and existing.permission_b == rule.permission_b
            ) or (
                existing.permission_a == rule.permission_b
                and existing.permission_b == rule.permission_a
            ):
                logger.warning(
                    f"Rule {rule.permission_a} vs {rule.permission_b} already exists, skipping"
                )
                return
        self._rules[rule.id] = rule
        self._record_audit(
            "ADD_RULE", "system", {"rule_id": rule.id, "severity": rule.severity.value}
        )
        logger.debug(
            f"SOD rule added: {rule.permission_a} <-> {rule.permission_b} ({rule.severity.value})"
        )

    def remove_rule(self, rule_id: str) -> bool:
        if rule_id in self._rules:
            del self._rules[rule_id]
            self._record_audit("REMOVE_RULE", "system", {"rule_id": rule_id})
            return True
        return False

    def get_rule(self, rule_id: str) -> SoDRule | None:
        return self._rules.get(rule_id)

    def get_all_rules(self) -> list[SoDRule]:
        return list(self._rules.values())

    def enable_rule(self, rule_id: str, enabled: bool) -> bool:
        rule = self._rules.get(rule_id)
        if rule:
            rule.enabled = enabled
            self._record_audit("ENABLE_RULE", "system", {"rule_id": rule_id, "enabled": enabled})
            return True
        return False

    def check_permissions(self, permissions: set[str]) -> list[tuple[SoDRule, str]]:
        conflicts = []
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            has_conflict, severity, desc = rule.conflicts_with(permissions)
            if has_conflict:
                conflicts.append(
                    (rule, f"User has both '{rule.permission_a}' and '{rule.permission_b}': {desc}")
                )
        return conflicts

    def enforce(
        self, permissions: set[str], raise_on_critical: bool = True, raise_on_high: bool = False
    ) -> list[tuple[SoDRule, str]]:
        conflicts = self.check_permissions(permissions)
        for rule, msg in conflicts:
            if raise_on_critical and rule.severity == SODConflictSeverity.CRITICAL:
                raise SODViolationError(msg, rule.severity, rule.id)
            if raise_on_high and rule.severity == SODConflictSeverity.HIGH:
                raise SODViolationError(msg, rule.severity, rule.id)
        return conflicts

    def is_compliant(self, permissions: set[str]) -> bool:
        return len(self.check_permissions(permissions)) == 0

    def get_conflict_summary(self, permissions: set[str]) -> dict[str, int]:
        conflicts = self.check_permissions(permissions)
        summary = {sev.value: 0 for sev in SODConflictSeverity}
        for rule, _ in conflicts:
            summary[rule.severity.value] += 1
        return summary

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        for rule in self._rules.values():
            res = rule.validate()
            if not res["is_valid"]:
                errors.extend([f"Rule {rule.id}: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict:
        return {
            "rules": [r.to_dict() for r in self._rules.values()],
            "total_rules": len(self._rules),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SODMatrix:
        instance = cls()
        instance._rules.clear()
        for rule_data in data.get("rules", []):
            rule = SoDRule.from_dict(rule_data)
            instance._rules[rule.id] = rule
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> SODMatrix:
        new = SODMatrix()
        new._rules = {rid: rule.clone() for rid, rule in self._rules.items()}
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict:
        return {
            "version": self._version,
            "rules_count": len(self._rules),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> SODMatrix:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._rules.clear()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._init_default_rules()
        self._record_audit("RESET", "system", {})

    def export_to_json(self, file_path: str) -> None:
        with open(file_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)


# ============================================================================
# RBACEnforcer Core (dengan entity dasar)
# ============================================================================
class RBACEnforcer:
    def __init__(self, sod_matrix: SODMatrix | None = None):
        self._sod = sod_matrix or SODMatrix()
        self._role_permissions: dict[str, set[str]] = {}
        self._user_roles: dict[str, set[str]] = {}
        self._role_hierarchy: dict[str, set[str]] = defaultdict(set)
        self._role_children: dict[str, set[str]] = defaultdict(set)
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "roles_count": len(self._role_permissions),
                "users_count": len(self._user_roles),
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

    # ------------------------------------------------------------------------
    # Role Management
    # ------------------------------------------------------------------------
    def define_role(
        self, role_id: str, permissions: set[str], inherits_from: list[str] | None = None
    ) -> None:
        self._role_permissions[role_id] = set(permissions)
        if inherits_from:
            for parent in inherits_from:
                self._role_hierarchy[role_id].add(parent)
                self._role_children[parent].add(role_id)
        self._record_audit(
            "DEFINE_ROLE", "system", {"role_id": role_id, "permissions_count": len(permissions)}
        )
        logger.info(f"Role defined: {role_id} with {len(permissions)} permissions")

    def update_role_permissions(self, role_id: str, permissions: set[str]) -> None:
        if role_id not in self._role_permissions:
            raise ValueError(f"Role {role_id} not defined")
        self._role_permissions[role_id] = set(permissions)
        self._record_audit(
            "UPDATE_ROLE_PERMISSIONS",
            "system",
            {"role_id": role_id, "permissions_count": len(permissions)},
        )
        logger.info(f"Role {role_id} permissions updated")

    def add_permission_to_role(self, role_id: str, permission: str) -> None:
        if role_id not in self._role_permissions:
            self._role_permissions[role_id] = set()
        self._role_permissions[role_id].add(permission)
        self._record_audit(
            "ADD_PERMISSION_TO_ROLE", "system", {"role_id": role_id, "permission": permission}
        )

    def remove_permission_from_role(self, role_id: str, permission: str) -> bool:
        if role_id in self._role_permissions and permission in self._role_permissions[role_id]:
            self._role_permissions[role_id].remove(permission)
            self._record_audit(
                "REMOVE_PERMISSION_FROM_ROLE",
                "system",
                {"role_id": role_id, "permission": permission},
            )
            return True
        return False

    def delete_role(self, role_id: str) -> bool:
        if role_id not in self._role_permissions:
            return False
        if role_id in self._role_hierarchy:
            for parent in self._role_hierarchy[role_id]:
                self._role_children[parent].discard(role_id)
            del self._role_hierarchy[role_id]
        if role_id in self._role_children:
            for child in self._role_children[role_id]:
                if child in self._role_hierarchy:
                    self._role_hierarchy[child].discard(role_id)
            del self._role_children[role_id]
        for user_roles in self._user_roles.values():
            user_roles.discard(role_id)
        del self._role_permissions[role_id]
        self._record_audit("DELETE_ROLE", "system", {"role_id": role_id})
        logger.info(f"Role {role_id} deleted")
        return True

    def get_role_permissions(self, role_id: str) -> set[str]:
        return self._role_permissions.get(role_id, set()).copy()

    def get_effective_permissions_for_role(
        self, role_id: str, visited: set[str] | None = None
    ) -> set[str]:
        if visited is None:
            visited = set()
        if role_id in visited:
            return set()
        visited.add(role_id)
        perms = self.get_role_permissions(role_id)
        for parent in self._role_hierarchy.get(role_id, set()):
            perms.update(self.get_effective_permissions_for_role(parent, visited))
        return perms

    def get_role_hierarchy_tree(self, role_id: str, depth: int = 0) -> dict:
        result = {
            "role": role_id,
            "permissions": list(self.get_role_permissions(role_id)),
            "children": [],
        }
        for child in self._role_children.get(role_id, set()):
            result["children"].append(self.get_role_hierarchy_tree(child, depth + 1))
        return result

    # ------------------------------------------------------------------------
    # User-Role Assignment
    # ------------------------------------------------------------------------
    def assign_role(self, user_id: str, role_id: str) -> None:
        if role_id not in self._role_permissions:
            raise ValueError(f"Role {role_id} not defined")
        if user_id not in self._user_roles:
            self._user_roles[user_id] = set()
        self._user_roles[user_id].add(role_id)
        self._record_audit("ASSIGN_ROLE", user_id, {"role_id": role_id})
        logger.info(f"Role {role_id} assigned to user {user_id}")

    def revoke_role(self, user_id: str, role_id: str) -> bool:
        if user_id in self._user_roles and role_id in self._user_roles[user_id]:
            self._user_roles[user_id].remove(role_id)
            self._record_audit("REVOKE_ROLE", user_id, {"role_id": role_id})
            logger.info(f"Role {role_id} revoked from user {user_id}")
            return True
        return False

    def get_user_roles(self, user_id: str) -> set[str]:
        return self._user_roles.get(user_id, set()).copy()

    def get_user_permissions(self, user_id: str) -> set[str]:
        perms = set()
        for role_id in self.get_user_roles(user_id):
            perms.update(self.get_effective_permissions_for_role(role_id))
        return perms

    def get_users_with_role(self, role_id: str) -> list[str]:
        return [uid for uid, roles in self._user_roles.items() if role_id in roles]

    # ------------------------------------------------------------------------
    # Permission Checks & Enforcement
    # ------------------------------------------------------------------------
    def has_permission(self, user_id: str, required_permission: str) -> bool:
        return required_permission in self.get_user_permissions(user_id)

    def enforce_permission(self, user_id: str, required_permission: str) -> None:
        if not self.has_permission(user_id, required_permission):
            from .security_exceptions import AuthorizationError

            raise AuthorizationError(
                f"User {user_id} missing required permission: {required_permission}"
            )

    def has_any_permission(self, user_id: str, required_permissions: list[str]) -> bool:
        user_perms = self.get_user_permissions(user_id)
        return any(p in user_perms for p in required_permissions)

    def has_all_permissions(self, user_id: str, required_permissions: list[str]) -> bool:
        user_perms = self.get_user_permissions(user_id)
        return all(p in user_perms for p in required_permissions)

    # ------------------------------------------------------------------------
    # SOD Integration
    # ------------------------------------------------------------------------
    def enforce_sod(
        self, user_id: str, raise_on_critical: bool = True, raise_on_high: bool = False
    ) -> list[tuple[SoDRule, str]]:
        perms = self.get_user_permissions(user_id)
        return self._sod.enforce(
            perms, raise_on_critical=raise_on_critical, raise_on_high=raise_on_high
        )

    def is_sod_compliant(self, user_id: str) -> bool:
        perms = self.get_user_permissions(user_id)
        return self._sod.is_compliant(perms)

    def check_sod_conflict(self, user_id: str) -> list[tuple[SoDRule, str]]:
        perms = self.get_user_permissions(user_id)
        return self._sod.check_permissions(perms)

    def get_sod_conflict_summary(self, user_id: str) -> dict[str, int]:
        perms = self.get_user_permissions(user_id)
        return self._sod.get_conflict_summary(perms)

    # ------------------------------------------------------------------------
    # Reporting & Administration
    # ------------------------------------------------------------------------
    def get_all_roles(self) -> list[str]:
        return list(self._role_permissions.keys())

    def get_all_users(self) -> list[str]:
        return list(self._user_roles.keys())

    def generate_report(self) -> dict[str, Any]:
        total_users = len(self._user_roles)
        total_roles = len(self._role_permissions)
        user_compliance = {}
        for uid, roles in self._user_roles.items():
            compliant = self.is_sod_compliant(uid)
            conflicts = self.check_sod_conflict(uid)
            user_compliance[uid] = {
                "roles": list(roles),
                "permission_count": len(self.get_user_permissions(uid)),
                "compliant": compliant,
                "conflict_count": len(conflicts),
                "severities": [c[0].severity.value for c in conflicts],
            }
        return {
            "total_users": total_users,
            "total_roles": total_roles,
            "sod_rules_count": len(self._sod.get_all_rules()),
            "user_compliance": user_compliance,
            "compliant_users": sum(1 for v in user_compliance.values() if v["compliant"]),
            "compliant_percentage": (
                sum(1 for v in user_compliance.values() if v["compliant"]) / max(total_users, 1)
            )
            * 100,
            "version": self._version,
        }

    def export_to_json(self, file_path: str) -> None:
        data = {
            "roles": {role: list(perms) for role, perms in self._role_permissions.items()},
            "role_hierarchy": {
                role: list(parents) for role, parents in self._role_hierarchy.items()
            },
            "user_roles": {user: list(roles) for user, roles in self._user_roles.items()},
            "sod_matrix": self._sod.to_dict(),
            "version": self._version,
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        for role, perms in self._role_permissions.items():
            for p in perms:
                if not isinstance(p, str):
                    errors.append(f"Role {role} has invalid permission type")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "roles": {role: list(perms) for role, perms in self._role_permissions.items()},
            "user_roles": {user: list(roles) for user, roles in self._user_roles.items()},
            "role_hierarchy": {
                role: list(parents) for role, parents in self._role_hierarchy.items()
            },
            "sod_matrix": self._sod.to_dict(),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RBACEnforcer:
        sod = SODMatrix.from_dict(data.get("sod_matrix", {}))
        instance = cls(sod_matrix=sod)
        for role, perms in data.get("roles", {}).items():
            instance._role_permissions[role] = set(perms)
        for role, parents in data.get("role_hierarchy", {}).items():
            instance._role_hierarchy[role] = set(parents)
            for p in parents:
                instance._role_children[p].add(role)
        for user, roles in data.get("user_roles", {}).items():
            instance._user_roles[user] = set(roles)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> RBACEnforcer:
        new = RBACEnforcer(sod_matrix=self._sod.clone())
        new._role_permissions = {k: v.copy() for k, v in self._role_permissions.items()}
        new._user_roles = {k: v.copy() for k, v in self._user_roles.items()}
        new._role_hierarchy = {k: v.copy() for k, v in self._role_hierarchy.items()}
        new._role_children = {k: v.copy() for k, v in self._role_children.items()}
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "roles_count": len(self._role_permissions),
            "users_count": len(self._user_roles),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> RBACEnforcer:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._role_permissions.clear()
        self._user_roles.clear()
        self._role_hierarchy.clear()
        self._role_children.clear()
        self._sod.reset()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._record_audit("RESET", "system", {})


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    sod = SODMatrix()
    rbac = RBACEnforcer(sod_matrix=sod)

    rbac.define_role(
        RoleType.AP_CLERK.value,
        {
            PermissionType.JOURNAL_CREATE.value,
            PermissionType.PAYMENT_CREATE.value,
            PermissionType.INVENTORY_RECEIVE.value,
        },
    )
    rbac.define_role(
        RoleType.AR_CLERK.value,
        {
            PermissionType.JOURNAL_CREATE.value,
            PermissionType.PAYMENT_APPROVE.value,
        },
    )
    rbac.define_role(
        RoleType.ACCOUNTING_MANAGER.value,
        {
            PermissionType.JOURNAL_APPROVE.value,
            PermissionType.PAYMENT_APPROVE.value,
            PermissionType.USER_ASSIGN_ROLE.value,
            PermissionType.AUDIT_VIEW.value,
        },
        inherits_from=[RoleType.AP_CLERK.value, RoleType.AR_CLERK.value],
    )

    user1 = "alice"
    rbac.assign_role(user1, RoleType.AP_CLERK.value)
    rbac.assign_role(user1, RoleType.ACCOUNTING_MANAGER.value)

    user2 = "bob"
    rbac.assign_role(user2, RoleType.AP_CLERK.value)

    print(f"User {user1} permissions: {rbac.get_user_permissions(user1)}")
    print(
        f"User {user1} has journal.create? {rbac.has_permission(user1, PermissionType.JOURNAL_CREATE.value)}"
    )

    conflicts = rbac.check_sod_conflict(user1)
    print(
        f"SOD conflicts for {user1}: {[(c[0].permission_a, c[0].permission_b) for c in conflicts]}"
    )

    try:
        rbac.enforce_sod(user1, raise_on_critical=True)
    except SODViolationError as e:
        print(f"Enforcement error (expected): {e}")

    print(f"User {user1} SOD compliant: {rbac.is_sod_compliant(user1)}")
    print(f"User {user2} SOD compliant: {rbac.is_sod_compliant(user2)}")

    report = rbac.generate_report()
    print("\nRBAC Report:")
    print(json.dumps(report, indent=2))

    rbac.export_to_json("rbac_config.json")
    print("\nConfiguration exported to rbac_config.json")
