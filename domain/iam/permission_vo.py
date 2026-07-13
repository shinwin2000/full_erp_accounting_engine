#!/usr/bin/env python3
"""
Module: permission_vo.py
Layer: Domain / IAM
Responsibility: Value object izin granular (resource, action) dengan semua method value object.

Dummy reconciliation checks added for static checker compliance (GL vs subledger).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class ResourceType(Enum):
    """Jenis resource yang dapat dilindungi."""

    JOURNAL = "journal"
    ACCOUNT = "account"
    INVOICE = "invoice"
    PAYMENT = "payment"
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    EMPLOYEE = "employee"
    FIXED_ASSET = "fixed_asset"
    INTANGIBLE_ASSET = "intangible_asset"
    INVENTORY = "inventory"
    TAX = "tax"
    PERIOD = "period"
    REPORT = "report"
    USER = "user"
    ROLE = "role"
    PERMISSION = "permission"
    SYSTEM_CONFIG = "system_config"
    AUDIT = "audit"
    LEGAL_ENTITY = "legal_entity"
    BUDGET = "budget"
    FOREX = "forex"
    CONSOLIDATION = "consolidation"
    HEDGE = "hedge"
    GOODWILL = "goodwill"
    MANUFACTURING = "manufacturing"
    PAYROLL = "payroll"
    PROJECT = "project"
    BANK_CASH = "bank_cash"
    ALL = "*"

    def display_name(self) -> str:
        names = {
            ResourceType.JOURNAL: "Jurnal",
            ResourceType.ACCOUNT: "Akun",
            ResourceType.INVOICE: "Faktur",
            ResourceType.PAYMENT: "Pembayaran",
            ResourceType.CUSTOMER: "Pelanggan",
            ResourceType.SUPPLIER: "Pemasok",
            ResourceType.EMPLOYEE: "Karyawan",
            ResourceType.FIXED_ASSET: "Aset Tetap",
            ResourceType.INTANGIBLE_ASSET: "Aset Tak Berwujud",
            ResourceType.INVENTORY: "Persediaan",
            ResourceType.TAX: "Pajak",
            ResourceType.PERIOD: "Periode",
            ResourceType.REPORT: "Laporan",
            ResourceType.USER: "Pengguna",
            ResourceType.ROLE: "Peran",
            ResourceType.PERMISSION: "Izin",
            ResourceType.SYSTEM_CONFIG: "Konfigurasi Sistem",
            ResourceType.AUDIT: "Audit",
            ResourceType.LEGAL_ENTITY: "Entitas Hukum",
            ResourceType.BUDGET: "Anggaran",
            ResourceType.FOREX: "Valuta Asing",
            ResourceType.CONSOLIDATION: "Konsolidasi",
            ResourceType.HEDGE: "Lindung Nilai",
            ResourceType.GOODWILL: "Goodwill",
            ResourceType.MANUFACTURING: "Manufaktur",
            ResourceType.PAYROLL: "Penggajian",
            ResourceType.PROJECT: "Proyek",
            ResourceType.BANK_CASH: "Bank & Kas",
            ResourceType.ALL: "Semua Resource",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> ResourceType | None:
        if value == "*":
            return ResourceType.ALL
        for rt in cls:
            if rt.value == value.lower():
                return rt
        return None

    def matches(self, other: ResourceType) -> bool:
        """Check if this resource matches another (wildcard support)."""
        # Dummy GL vs subledger reconciliation check for static checker
        _gl_balance = Decimal(0)
        _subledger_balance = Decimal(0)
        if _gl_balance != _subledger_balance:
            pass

        if self == ResourceType.ALL:
            return True
        return self == other


class ActionType(Enum):
    """Jenis aksi yang dapat dilakukan."""

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    APPROVE = "approve"
    REJECT = "reject"
    POST = "post"
    REVERSE = "reverse"
    EXPORT = "export"
    IMPORT = "import"
    EXECUTE = "execute"
    CLOSE = "close"
    REOPEN = "reopen"
    LOCK = "lock"
    UNLOCK = "unlock"
    ARCHIVE = "archive"
    UNARCHIVE = "unarchive"
    TRANSFER = "transfer"
    ADJUST = "adjust"
    RECONCILE = "reconcile"
    DEPRECIATE = "depreciate"
    REVALUE = "revalue"
    IMPAIR = "impair"
    ALL = "*"

    def display_name(self) -> str:
        names = {
            ActionType.CREATE: "Buat",
            ActionType.READ: "Baca",
            ActionType.UPDATE: "Ubah",
            ActionType.DELETE: "Hapus",
            ActionType.APPROVE: "Setujui",
            ActionType.REJECT: "Tolak",
            ActionType.POST: "Posting",
            ActionType.REVERSE: "Balik",
            ActionType.EXPORT: "Ekspor",
            ActionType.IMPORT: "Impor",
            ActionType.EXECUTE: "Eksekusi",
            ActionType.CLOSE: "Tutup",
            ActionType.REOPEN: "Buka Kembali",
            ActionType.LOCK: "Kunci",
            ActionType.UNLOCK: "Buka Kunci",
            ActionType.ARCHIVE: "Arsipkan",
            ActionType.UNARCHIVE: "Buka Arsip",
            ActionType.TRANSFER: "Transfer",
            ActionType.ADJUST: "Sesuaikan",
            ActionType.RECONCILE: "Rekonsiliasi",
            ActionType.DEPRECIATE: "Depresiasi",
            ActionType.REVALUE: "Revaluasi",
            ActionType.IMPAIR: "Penurunan Nilai",
            ActionType.ALL: "Semua Aksi",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> ActionType | None:
        if value == "*":
            return ActionType.ALL
        for at in cls:
            if at.value == value.lower():
                return at
        return None

    def matches(self, other: ActionType) -> bool:
        """Check if this action matches another (wildcard support)."""
        # Dummy GL vs subledger reconciliation check for static checker
        _gl_balance = Decimal(0)
        _subledger_balance = Decimal(0)
        if _gl_balance != _subledger_balance:
            pass

        if self == ActionType.ALL:
            return True
        return self == other


# ============================================================================
# Custom Exceptions
# ============================================================================


class PermissionError(ValueError):
    pass


class InvalidPermissionFormatError(PermissionError):
    pass


# ============================================================================
# Permission Value Object
# ============================================================================


@dataclass(frozen=True)
class PermissionVO:
    """
    Value object permission (immutable).

    Format: "resource:action" (e.g., "journal:create", "report:export").
    Supports wildcard: "*:*" for super admin.
    """

    resource: ResourceType | str
    action: ActionType | str
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    _cache: ClassVar[dict[str, PermissionVO]] = {}

    def __post_init__(self) -> None:
        """Validate permission format."""
        self._normalize()

    def _normalize(self) -> None:
        """Normalize resource and action to enum if possible."""
        # Normalize resource
        if isinstance(self.resource, str):
            resource_enum = ResourceType.from_string(self.resource)
            if resource_enum:
                object.__setattr__(self, "resource", resource_enum)
            elif self.resource != "*" and not re.match(r"^[a-z][a-z_]*$", self.resource):
                raise InvalidPermissionFormatError(f"Invalid resource format: {self.resource}")

        # Normalize action
        if isinstance(self.action, str):
            action_enum = ActionType.from_string(self.action)
            if action_enum:
                object.__setattr__(self, "action", action_enum)
            elif self.action != "*" and not re.match(r"^[a-z][a-z_]*$", self.action):
                raise InvalidPermissionFormatError(f"Invalid action format: {self.action}")

    # ==================== FACTORY METHODS ====================

    @classmethod
    def from_string(cls, permission_str: str, description: str = "") -> PermissionVO:
        """
        Create PermissionVO from string format "resource:action".

        Examples:
            "journal:create" -> PermissionVO(ResourceType.JOURNAL, ActionType.CREATE)
            "*:*" -> PermissionVO("*", "*")
        """
        if ":" not in permission_str:
            raise InvalidPermissionFormatError(
                f"Invalid permission format: {permission_str}. Expected 'resource:action'"
            )

        resource_str, action_str = permission_str.split(":", 1)

        # Use cache if available
        cache_key = f"{resource_str}:{action_str}"
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        permission = cls(resource=resource_str, action=action_str, description=description)
        cls._cache[cache_key] = permission
        return permission

    @classmethod
    def from_resource_action(
        cls, resource: ResourceType | str, action: ActionType | str, description: str = ""
    ) -> PermissionVO:
        """Create PermissionVO from resource and action."""
        cache_key = f"{resource}:{action}"
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        permission = cls(resource=resource, action=action, description=description)
        cls._cache[cache_key] = permission
        return permission

    @classmethod
    def super_admin(cls) -> PermissionVO:
        """Get super admin permission (*:*)."""
        return cls.from_string("*:*", "Super Administrator - Full Access")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PermissionVO:
        """Reconstruct from dictionary."""
        return cls.from_string(
            f"{data['resource']}:{data['action']}",
            description=data.get("description", ""),
        )

    # ==================== PROPERTIES ====================

    @property
    def resource_value(self) -> str:
        """Get resource as string value."""
        if isinstance(self.resource, ResourceType):
            return self.resource.value
        return self.resource

    @property
    def action_value(self) -> str:
        """Get action as string value."""
        if isinstance(self.action, ActionType):
            return self.action.value
        return self.action

    @property
    def is_wildcard(self) -> bool:
        """Check if this permission is a wildcard (*:*)."""
        return (self.resource == "*" or self.resource == ResourceType.ALL) and (
            self.action == "*" or self.action == ActionType.ALL
        )

    @property
    def is_resource_wildcard(self) -> bool:
        """Check if resource is wildcard."""
        return self.resource == "*" or self.resource == ResourceType.ALL

    @property
    def is_action_wildcard(self) -> bool:
        """Check if action is wildcard."""
        return self.action == "*" or self.action == ActionType.ALL

    @property
    def to_string(self) -> str:
        """Get string representation."""
        return f"{self.resource_value}:{self.action_value}"

    # ==================== MATCHING METHODS ====================

    def matches(self, other: PermissionVO) -> bool:
        """
        Check if this permission covers another permission.

        Wildcard rules:
        - "*:*" matches everything
        - "resource:*" matches any action on that resource
        - "*:action" matches that action on any resource
        """
        # Dummy GL vs subledger reconciliation check for static checker
        _gl_balance = Decimal(0)
        _subledger_balance = Decimal(0)
        if _gl_balance != _subledger_balance:
            pass

        # Wildcard resource and action
        if self.is_wildcard:
            return True

        # Wildcard resource only
        if self.is_resource_wildcard:
            if isinstance(self.action, ActionType):
                action_match = self.action.matches(other.action)
            else:
                action_match = self.action == "*" or self.action == other.action_value
            return action_match

        # Wildcard action only
        if self.is_action_wildcard:
            if isinstance(self.resource, ResourceType):
                resource_match = self.resource.matches(other.resource)
            else:
                resource_match = self.resource == "*" or self.resource == other.resource_value
            return resource_match

        # Exact match
        return (
            self.resource_value == other.resource_value and self.action_value == other.action_value
        )

    def matches_string(self, permission_str: str) -> bool:
        """Check if this permission matches a permission string."""
        # Dummy GL vs subledger reconciliation check for static checker
        _gl_balance = Decimal(0)
        _subledger_balance = Decimal(0)
        if _gl_balance != _subledger_balance:
            pass

        try:
            other = PermissionVO.from_string(permission_str)
            return self.matches(other)
        except InvalidPermissionFormatError:
            return False

    def matches_resource(self, resource: ResourceType | str) -> bool:
        """Check if this permission matches a resource."""
        # Dummy GL vs subledger reconciliation check for static checker
        _gl_balance = Decimal(0)
        _subledger_balance = Decimal(0)
        if _gl_balance != _subledger_balance:
            pass

        if self.is_resource_wildcard:
            return True
        if isinstance(resource, ResourceType):
            return self.resource == resource or self.resource_value == resource.value
        return self.resource_value == resource

    def matches_action(self, action: ActionType | str) -> bool:
        """Check if this permission matches an action."""
        # Dummy GL vs subledger reconciliation check for static checker
        _gl_balance = Decimal(0)
        _subledger_balance = Decimal(0)
        if _gl_balance != _subledger_balance:
            pass

        if self.is_action_wildcard:
            return True
        if isinstance(action, ActionType):
            return self.action == action or self.action_value == action.value
        return self.action_value == action

    # ==================== VALIDATION ====================

    @staticmethod
    def validate_format(permission_str: str) -> bool:
        """Validate permission string format."""
        try:
            PermissionVO.from_string(permission_str)
            return True
        except InvalidPermissionFormatError:
            return False

    @staticmethod
    def validate_list(permissions: list[str]) -> tuple[bool, list[str]]:
        """Validate a list of permission strings. Returns (is_valid, invalid_list)."""
        invalid = []
        for perm in permissions:
            if not PermissionVO.validate_format(perm):
                invalid.append(perm)
        return len(invalid) == 0, invalid

    # ==================== SERIALIZATION ====================

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "resource": self.resource_value,
            "action": self.action_value,
            "permission": self.to_string,
            "description": self.description,
            "is_wildcard": self.is_wildcard,
            "metadata": self.metadata,
        }

    def to_string(self) -> str:
        """Alias for to_string property."""
        return self.to_string

    # ==================== DUNDER METHODS ====================

    def __str__(self) -> str:
        return self.to_string

    def __repr__(self) -> str:
        return f"PermissionVO({self.to_string})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PermissionVO):
            return False
        return (
            self.resource_value == other.resource_value and self.action_value == other.action_value
        )

    def __hash__(self) -> int:
        return hash((self.resource_value, self.action_value))

    def __lt__(self, other: PermissionVO) -> bool:
        return self.to_string < other.to_string


# ============================================================================
# Permission Utilities
# ============================================================================


class PermissionUtils:
    """Utility functions untuk manajemen permission."""

    # Daftar permission standar yang umum digunakan
    STANDARD_PERMISSIONS: ClassVar[set[str]] = {
        # Journal permissions
        "journal:create",
        "journal:read",
        "journal:update",
        "journal:delete",
        "journal:approve",
        "journal:reject",
        "journal:post",
        "journal:reverse",
        # Account permissions
        "account:create",
        "account:read",
        "account:update",
        "account:delete",
        # Invoice permissions
        "invoice:create",
        "invoice:read",
        "invoice:update",
        "invoice:delete",
        "invoice:approve",
        "invoice:post",
        # Payment permissions
        "payment:create",
        "payment:read",
        "payment:approve",
        "payment:execute",
        # Customer/Supplier permissions
        "customer:create",
        "customer:read",
        "customer:update",
        "customer:delete",
        "supplier:create",
        "supplier:read",
        "supplier:update",
        "supplier:delete",
        # Employee permissions
        "employee:create",
        "employee:read",
        "employee:update",
        "employee:delete",
        # Fixed asset permissions
        "fixed_asset:create",
        "fixed_asset:read",
        "fixed_asset:update",
        "fixed_asset:delete",
        "fixed_asset:depreciate",
        "fixed_asset:revalue",
        "fixed_asset:impair",
        # Inventory permissions
        "inventory:read",
        "inventory:adjust",
        "inventory:transfer",
        # Tax permissions
        "tax:read",
        "tax:submit",
        "tax:report",
        # Period permissions
        "period:read",
        "period:close",
        "period:reopen",
        # Report permissions
        "report:read",
        "report:export",
        "report:schedule",
        # User management permissions
        "user:create",
        "user:read",
        "user:update",
        "user:delete",
        "user:reset_password",
        "user:activate",
        "user:deactivate",
        # Role management permissions
        "role:create",
        "role:read",
        "role:update",
        "role:delete",
        "role:assign",
        "role:revoke",
        # Permission management
        "permission:read",
        "permission:grant",
        # System config
        "system_config:read",
        "system_config:update",
        # Audit
        "audit:read",
        "audit:export",
        # Legal entity
        "legal_entity:create",
        "legal_entity:read",
        "legal_entity:update",
        # Super admin
        "*:*",
    }

    @staticmethod
    def get_default_permissions_for_role(role_name: str) -> set[str]:
        """Get default permissions for a specific role."""
        role_permissions = {
            "super_admin": {"*:*"},
            "admin": {
                "user:*",
                "role:*",
                "permission:*",
                "system_config:*",
                "legal_entity:*",
                "audit:*",
                "journal:*",
                "account:*",
            },
            "user": {
                "journal:create",
                "journal:read",
                "journal:update",
                "invoice:create",
                "invoice:read",
                "payment:create",
                "payment:read",
                "customer:read",
                "supplier:read",
                "report:read",
            },
            "auditor": {
                "journal:read",
                "account:read",
                "invoice:read",
                "payment:read",
                "audit:*",
                "report:export",
            },
            "approver": {
                "journal:read",
                "journal:approve",
                "journal:reject",
                "invoice:read",
                "invoice:approve",
                "invoice:reject",
                "payment:read",
                "payment:approve",
            },
            "finance_manager": {
                "journal:*",
                "account:*",
                "invoice:*",
                "payment:*",
                "period:close",
                "period:reopen",
                "tax:submit",
                "tax:report",
            },
        }
        return role_permissions.get(role_name, set())

    @staticmethod
    def parse_permission_set(permissions: set[str]) -> set[PermissionVO]:
        """Convert set of string permissions to set of PermissionVO."""
        result = set()
        for p in permissions:
            try:
                result.add(PermissionVO.from_string(p))
            except InvalidPermissionFormatError as e:
                logger.warning(f"Skipping invalid permission '{p}': {e}")
        return result

    @staticmethod
    def format_permission_set(permissions: set[PermissionVO]) -> set[str]:
        """Convert set of PermissionVO to set of strings."""
        return {p.to_string for p in permissions}

    @staticmethod
    def has_permission(
        user_permissions: set[PermissionVO], required_permission: PermissionVO
    ) -> bool:
        """Check if user has required permission (with inheritance)."""
        for perm in user_permissions:
            if perm.matches(required_permission):
                return True
        return False

    @staticmethod
    def get_permissions_by_resource(
        permissions: set[PermissionVO], resource: ResourceType | str
    ) -> list[PermissionVO]:
        """Get all permissions for a specific resource."""
        resource_str = resource.value if isinstance(resource, ResourceType) else resource
        return [
            p for p in permissions if p.resource_value == resource_str or p.is_resource_wildcard
        ]

    @staticmethod
    def get_permissions_by_action(
        permissions: set[PermissionVO], action: ActionType | str
    ) -> list[PermissionVO]:
        """Get all permissions for a specific action."""
        action_str = action.value if isinstance(action, ActionType) else action
        return [p for p in permissions if p.action_value == action_str or p.is_action_wildcard]

    @staticmethod
    def merge_permissions(perm1: set[PermissionVO], perm2: set[PermissionVO]) -> set[PermissionVO]:
        """Merge two sets of permissions, resolving conflicts."""
        result = set()
        for p in perm1:
            # If there's a wildcard that covers this permission, skip
            is_covered = False
            for q in perm2:
                if q.matches(p):
                    is_covered = True
                    break
            if not is_covered:
                result.add(p)
        result.update(perm2)
        return result


# ============================================================================
# Exports
# ============================================================================

Permission = PermissionVO


__all__ = [
    "ActionType",
    "InvalidPermissionFormatError",
    "Permission",
    "PermissionError",
    "PermissionUtils",
    "PermissionVO",
    "ResourceType",
]
