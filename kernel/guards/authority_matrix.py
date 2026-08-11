#!/usr/bin/env python3
"""
Module: authority_matrix.py
Layer: 4 - Kernel / Guards
Responsibility: Matriks otorisasi: siapa boleh melakukan apa pada entitas mana.
               Menyediakan mekanisme fine-grained authorization berdasarkan
               role, permission, dan resource. Mendukung hierarchical roles
               dan dynamic permission evaluation.
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from kernel.context_holder import get_current_legal_entity, get_current_user
from kernel.guards.guard_exceptions import (
    AuthorityMatrixError,
    GuardSeverity,
)

logger = logging.getLogger(__name__)


# ============================================================================
# FALLBACK USER REPOSITORY (in-memory, no infrastructure)
# ============================================================================


class _FallbackUserRepository:
    """In-memory user repository untuk fallback."""

    def __init__(self):
        self._user_roles: dict[str, list[str]] = {
            "admin": ["admin"],
            "maker": ["maker"],
            "checker": ["checker", "maker"],
            "auditor": ["auditor"],
            "system": ["system"],
        }
        self._user_entities: dict[str, list[UUID]] = {}

    async def get_roles(self, user_id: str) -> list[str]:
        return self._user_roles.get(user_id, ["guest"])

    async def get_legal_entities(self, user_id: str) -> list[UUID]:
        return self._user_entities.get(user_id, [])

    def set_user_roles(self, user_id: str, roles: list[str]):
        self._user_roles[user_id] = roles


def _get_user_repository():
    # Selalu gunakan fallback in-memory untuk isolasi kernel
    logger.info("Using in-memory fallback for user repository (no infrastructure)")
    return _FallbackUserRepository()


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class ResourceType(Enum):
    JOURNAL = "journal"
    ACCOUNT = "account"
    INVOICE = "invoice"
    PAYMENT = "payment"
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    EMPLOYEE = "employee"
    FIXED_ASSET = "fixed_asset"
    INVENTORY = "inventory"
    TAX = "tax"
    PERIOD = "period"
    REPORT = "report"
    USER = "user"
    ROLE = "role"
    SYSTEM_CONFIG = "system_config"
    BUDGET = "budget"
    APPROVAL = "approval"
    AUDIT = "audit"
    # --- Ditambahkan agar cocok dengan semua router yang terdaftar di app.main ---
    AP = "ap"
    AR = "ar"
    BANK_CASH = "bank_cash"
    COA = "coa"
    HEDGE = "hedge"
    CURRENCY_EXCHANGE = "currency_exchange"
    IAM = "iam"
    GOODWILL = "goodwill"
    DOCUMENT = "document"
    FOREX = "forex"
    LEGAL_ENTITY = "legal_entity"
    INTANGIBLE_ASSET = "intangible_asset"
    PROJECT = "project"
    PURCHASE_SALES = "purchase_sales"
    MAINTENANCE = "maintenance"
    UMKM = "umkm"
    SETTINGS = "settings"
    LEDGER = "ledger"
    CONSOLIDATION = "consolidation"
    MANUFACTURING = "manufacturing"
    PAYROLL = "payroll"
    CAPITAL = "capital"
    FISCAL_PERIOD = "fiscal_period"


class Action(Enum):
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
    CLOSE = "close"
    REOPEN = "reopen"
    EXECUTE = "execute"
    DELEGATE = "delegate"
    AUDIT = "audit"


class PermissionScope(Enum):
    SELF = "self"
    ENTITY = "entity"
    ALL = "all"
    LEGAL_ENTITY = "legal_entity"


class PermissionEffect(Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass
class Permission:
    resource: ResourceType
    action: Action
    scope: PermissionScope = PermissionScope.ENTITY
    effect: PermissionEffect = PermissionEffect.ALLOW
    conditions: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource.value,
            "action": self.action.value,
            "scope": self.scope.value,
            "effect": self.effect.value,
            "conditions": self.conditions,
        }


@dataclass
class Role:
    name: str
    permissions: list[Permission]
    parent_role: str | None = None
    description: str = ""
    is_system_role: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "permissions": [p.to_dict() for p in self.permissions],
            "parent_role": self.parent_role,
            "description": self.description,
            "is_system_role": self.is_system_role,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
        }


# ============================================================================
# STANDARD ROLES
# ============================================================================

STANDARD_ROLES: dict[str, Role] = {
    "maker": Role(
        name="maker",
        permissions=[
            Permission(ResourceType.JOURNAL, Action.CREATE, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.JOURNAL, Action.READ, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.INVOICE, Action.CREATE, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.INVOICE, Action.READ, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.PAYMENT, Action.CREATE, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.CUSTOMER, Action.READ, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.SUPPLIER, Action.READ, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.EMPLOYEE, Action.READ, PermissionScope.LEGAL_ENTITY),
        ],
        description="Can create but not approve transactions",
    ),
    "checker": Role(
        name="checker",
        permissions=[
            Permission(ResourceType.JOURNAL, Action.READ, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.JOURNAL, Action.APPROVE, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.JOURNAL, Action.REJECT, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.INVOICE, Action.READ, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.INVOICE, Action.APPROVE, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.PAYMENT, Action.APPROVE, PermissionScope.LEGAL_ENTITY),
        ],
        parent_role="maker",
        description="Can approve/reject transactions",
    ),
    "poster": Role(
        name="poster",
        permissions=[
            Permission(ResourceType.JOURNAL, Action.POST, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.JOURNAL, Action.READ, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.PERIOD, Action.CLOSE, PermissionScope.LEGAL_ENTITY),
        ],
        parent_role="checker",
        description="Can post journals and close periods",
    ),
    "auditor": Role(
        name="auditor",
        permissions=[
            Permission(ResourceType.JOURNAL, Action.READ, PermissionScope.ALL),
            Permission(ResourceType.ACCOUNT, Action.READ, PermissionScope.ALL),
            Permission(ResourceType.INVOICE, Action.READ, PermissionScope.ALL),
            Permission(ResourceType.PAYMENT, Action.READ, PermissionScope.ALL),
            Permission(ResourceType.REPORT, Action.EXPORT, PermissionScope.ALL),
            Permission(ResourceType.SYSTEM_CONFIG, Action.READ, PermissionScope.ALL),
            Permission(ResourceType.AUDIT, Action.AUDIT, PermissionScope.ALL),
        ],
        description="Read-only access for audit across all entities",
    ),
    "admin": Role(
        name="admin",
        permissions=[
            Permission(ResourceType.USER, Action.CREATE, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.USER, Action.READ, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.USER, Action.UPDATE, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.USER, Action.DELETE, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.ROLE, Action.CREATE, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.ROLE, Action.READ, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.ROLE, Action.UPDATE, PermissionScope.LEGAL_ENTITY),
            Permission(ResourceType.SYSTEM_CONFIG, Action.UPDATE, PermissionScope.LEGAL_ENTITY),
        ],
        description="System administrator for the legal entity",
    ),
    "super_admin": Role(
        name="super_admin",
        permissions=[
            Permission(ResourceType.SYSTEM_CONFIG, Action.EXECUTE, PermissionScope.ALL),
            Permission(ResourceType.PERIOD, Action.REOPEN, PermissionScope.ALL),
            Permission(ResourceType.USER, Action.DELEGATE, PermissionScope.ALL),
            Permission(ResourceType.ROLE, Action.DELEGATE, PermissionScope.ALL),
        ],
        parent_role="admin",
        description="Super administrator with override capabilities across all entities",
    ),
    "guest": Role(
        name="guest",
        permissions=[
            Permission(ResourceType.REPORT, Action.READ, PermissionScope.SELF),
        ],
        description="Default role for unauthenticated users",
    ),
}


# ============================================================================
# EXTENSI OTOMATIS: admin & super_admin mendapat CRUD penuh untuk semua
# resource domain bisnis yang baru ditambahkan (ap, ar, bank_cash, ledger, dst)
# Ini untuk menghindari 403 tak terduga saat router baru ditambahkan tapi
# STANDARD_ROLES belum dimutakhirkan manual.
# ============================================================================

_BUSINESS_RESOURCE_TYPES: list[ResourceType] = [
    ResourceType.AP,
    ResourceType.AR,
    ResourceType.BANK_CASH,
    ResourceType.COA,
    ResourceType.HEDGE,
    ResourceType.CURRENCY_EXCHANGE,
    ResourceType.IAM,
    ResourceType.GOODWILL,
    ResourceType.DOCUMENT,
    ResourceType.FOREX,
    ResourceType.LEGAL_ENTITY,
    ResourceType.INTANGIBLE_ASSET,
    ResourceType.PROJECT,
    ResourceType.PURCHASE_SALES,
    ResourceType.MAINTENANCE,
    ResourceType.UMKM,
    ResourceType.SETTINGS,
    ResourceType.LEDGER,
    ResourceType.CONSOLIDATION,
    ResourceType.MANUFACTURING,
    ResourceType.PAYROLL,
    ResourceType.CAPITAL,
    ResourceType.FISCAL_PERIOD,
]

_ADMIN_DEFAULT_ACTIONS: list[Action] = [
    Action.CREATE,
    Action.READ,
    Action.UPDATE,
    Action.DELETE,
    Action.EXPORT,
]

for _res in _BUSINESS_RESOURCE_TYPES:
    for _act in _ADMIN_DEFAULT_ACTIONS:
        STANDARD_ROLES["admin"].permissions.append(
            Permission(_res, _act, PermissionScope.LEGAL_ENTITY)
        )
    # super_admin mewarisi admin (parent_role="admin") jadi otomatis ikut dapat,
    # tidak perlu ditambahkan manual di sini.

del _res, _act


# ============================================================================
# BASE AUTHORITY MATRIX GUARD (ABSTRACT)
# ============================================================================

class BaseAuthorityMatrixGuard(ABC):
    """Base contract untuk Authority Matrix Guard."""

    @abstractmethod
    def register_role(self, role: Role) -> None:
        """Register a new role."""
        pass

    @abstractmethod
    def get_role(self, role_name: str) -> Role | None:
        """Get role by name."""
        pass

    @abstractmethod
    def get_all_roles(self) -> list[Role]:
        """Get all registered roles."""
        pass

    @abstractmethod
    async def has_permission(
        self,
        user_id: str,
        resource: ResourceType,
        action: Action,
        target_entity_id: UUID | None = None,
        context: dict | None = None,
    ) -> bool:
        """Check if user has permission."""
        pass

    @abstractmethod
    async def enforce(
        self,
        resource: ResourceType,
        action: Action,
        user_id: str | None = None,
        target_entity_id: UUID | None = None,
        context: dict | None = None,
        raise_on_violation: bool = True,
    ) -> bool:
        """Enforce permission, raise exception if violation."""
        pass

    @abstractmethod
    async def get_user_permissions(
        self, user_id: str, resource: ResourceType | None = None
    ) -> list[dict[str, str]]:
        """Get all permissions for a user."""
        pass

    @abstractmethod
    def get_authorization_history(
        self, limit: int = 100, user_id: str | None = None, only_denied: bool = False
    ) -> list[dict[str, Any]]:
        """Get authorization history."""
        pass

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        """Get statistics."""
        pass

    @abstractmethod
    def invalidate_cache(self, role_name: str | None = None) -> None:
        """Invalidate permission cache."""
        pass

    # ==================== EXTRA METHODS FOR CHECKER ====================

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
    def from_dict(cls, data: dict[str, Any]) -> BaseAuthorityMatrixGuard:
        """Reconstruct dari dictionary."""
        pass

    @abstractmethod
    def clone(self) -> BaseAuthorityMatrixGuard:
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
    def touch(self, touched_by: str) -> BaseAuthorityMatrixGuard:
        """Touch instance (increment version)."""
        pass


# ============================================================================
# AUTHORITY MATRIX GUARD (CONCRETE)
# ============================================================================


class AuthorityMatrixGuard(BaseAuthorityMatrixGuard):
    def __init__(self, user_repository: Any | None = None):
        self._user_repo = user_repository or _get_user_repository()
        self._roles: dict[str, Role] = STANDARD_ROLES.copy()
        self._permission_cache: dict[
            str, set[tuple[ResourceType, Action, PermissionScope, dict | None]]
        ] = {}
        self._cache_lock = threading.RLock()
        self._authorization_history: list[dict[str, Any]] = []
        self._max_history = 10000
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []

    # ==================== SYNC CHECK METHOD (untuk checker compliance) ====================

    def check(self, context: dict) -> list[str]:
        """
        Sync check method untuk compliance checker.
        Memvalidasi context dan mengembalikan daftar error jika ada.
        """
        errors = []
        user_id = context.get("user_id")
        resource = context.get("resource")
        action = context.get("action")

        if not user_id:
            errors.append("user_id is required")
        if not resource:
            errors.append("resource is required")
        if not action:
            errors.append("action is required")

        # Validasi resource enum
        if resource:
            try:
                ResourceType(resource)
            except ValueError:
                errors.append(f"Invalid resource type: {resource}")

        # Validasi action enum
        if action:
            try:
                Action(action)
            except ValueError:
                errors.append(f"Invalid action: {action}")

        return errors

    # ==================== ENTITY METHODS (wajib) ====================

    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        errors = []
        if self._max_history <= 0:
            errors.append("max_history must be positive")
        if not self._roles:
            errors.append("No roles registered")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        return {
            "roles": list(self._roles.keys()),
            "roles_count": len(self._roles),
            "max_history": self._max_history,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuthorityMatrixGuard:
        """Reconstruct dari dictionary."""
        instance = cls()
        instance._max_history = data.get("max_history", 10000)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> AuthorityMatrixGuard:
        """Clone instance."""
        new_instance = AuthorityMatrixGuard()
        new_instance._max_history = self._max_history
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        with self._cache_lock:
            return {
                "version": self._version,
                "roles_count": len(self._roles),
                "cache_size": len(self._permission_cache),
                "history_size": len(self._authorization_history),
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def version(self) -> int:
        """Dapatkan versi."""
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AuthorityMatrixGuard:
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

    def register_role(self, role: Role) -> None:
        self._roles[role.name] = role
        with self._cache_lock:
            self._permission_cache.pop(role.name, None)
        self._record_audit("REGISTER_ROLE", "system", {"role": role.name})
        logger.info(f"Registered role: {role.name}")

    def get_role(self, role_name: str) -> Role | None:
        return self._roles.get(role_name)

    def get_all_roles(self) -> list[Role]:
        return list(self._roles.values())

    def _get_all_permissions_for_role(self, role_name: str) -> set[tuple]:
        cache_key = role_name
        with self._cache_lock:
            if cache_key in self._permission_cache:
                return self._permission_cache[cache_key]

        permissions = set()
        role = self._roles.get(role_name)
        if not role:
            return permissions

        for perm in role.permissions:
            permissions.add((perm.resource, perm.action, perm.scope, perm.conditions))

        if role.parent_role:
            permissions.update(self._get_all_permissions_for_role(role.parent_role))

        with self._cache_lock:
            self._permission_cache[cache_key] = permissions
        return permissions

    async def has_permission(
        self,
        user_id: str,
        resource: ResourceType,
        action: Action,
        target_entity_id: UUID | None = None,
        context: dict | None = None,
    ) -> bool:
        user_roles = await self._user_repo.get_roles(user_id)
        if not user_roles:
            user_roles = ["guest"]

        current_entity = get_current_legal_entity()
        context = context or {}

        all_permissions = set()
        for role_name in user_roles:
            all_permissions.update(self._get_all_permissions_for_role(role_name))

        # Check ALLOW (DENY would be handled similarly if we stored effect)
        for perm_resource, perm_action, perm_scope, perm_conditions in all_permissions:
            if perm_resource != resource or perm_action != action:
                continue
            if perm_conditions and not self._check_conditions(perm_conditions, context):
                continue

            # Scope validation - FIX: SIM102 - gabungkan nested if untuk LEGAL_ENTITY
            if perm_scope == PermissionScope.SELF:
                if target_entity_id and current_entity and target_entity_id != current_entity:
                    continue
            elif perm_scope == PermissionScope.LEGAL_ENTITY and current_entity is None:
                continue
            return True

        return False

    def _check_conditions(self, conditions: dict, context: dict) -> bool:
        if not conditions:
            return True
        for key, expected in conditions.items():
            actual = context.get(key)
            if actual is None:
                return False
            if isinstance(expected, dict):
                op = expected.get("operator")
                value = expected.get("value")
                if (
                    (op == "lte" and actual <= value)
                    or (op == "gte" and actual >= value)
                    or (op == "eq" and actual == value)
                    or (op == "in" and actual in value)
                ):
                    continue
                else:
                    return False
            elif actual != expected:
                return False
        return True

    async def enforce(
        self,
        resource: ResourceType,
        action: Action,
        user_id: str | None = None,
        target_entity_id: UUID | None = None,
        context: dict | None = None,
        raise_on_violation: bool = True,
    ) -> bool:
        if user_id is None:
            user_id = get_current_user()
            if user_id is None:
                user_id = "guest"

        has_perm = await self.has_permission(user_id, resource, action, target_entity_id, context)

        self._record_authorization(user_id, resource, action, target_entity_id, context, has_perm)

        if not has_perm and raise_on_violation:
            error_msg = (
                f"User {user_id} does not have {action.value} permission on {resource.value}"
            )
            if target_entity_id:
                error_msg += f" for entity {target_entity_id}"
            logger.warning(error_msg)
            raise AuthorityMatrixError(
                message=error_msg,
                resource=resource.value,
                action=action.value,
                severity=GuardSeverity.HIGH,
                details={
                    "user_id": user_id,
                    "resource": resource.value,
                    "action": action.value,
                    "target_entity": str(target_entity_id) if target_entity_id else None,
                },
            )
        return has_perm

    def _record_authorization(self, user_id, resource, action, target_entity_id, context, granted):
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "user_id": user_id,
            "resource": resource.value,
            "action": action.value,
            "target_entity_id": str(target_entity_id) if target_entity_id else None,
            "context": {k: str(v)[:100] for k, v in (context or {}).items()},
            "granted": granted,
        }
        self._authorization_history.append(record)
        if len(self._authorization_history) > self._max_history:
            self._authorization_history = self._authorization_history[-self._max_history :]

    async def get_user_permissions(
        self, user_id: str, resource: ResourceType | None = None
    ) -> list[dict[str, str]]:
        user_roles = await self._user_repo.get_roles(user_id)
        if not user_roles:
            user_roles = ["guest"]

        all_permissions = set()
        for role_name in user_roles:
            all_permissions.update(self._get_all_permissions_for_role(role_name))

        result = []
        for res, act, scope, _ in all_permissions:
            if resource and res != resource:
                continue
            result.append(
                {
                    "resource": res.value,
                    "action": act.value,
                    "scope": scope.value,
                }
            )
        return result

    def get_authorization_history(self, limit=100, user_id=None, only_denied=False):
        result = self._authorization_history[-limit:]
        if user_id:
            result = [r for r in result if r["user_id"] == user_id]
        if only_denied:
            result = [r for r in result if not r["granted"]]
        return result

    def get_statistics(self):
        total = len(self._authorization_history)
        if total == 0:
            return {"total_authorizations": 0, "version": self._version}
        granted = len([r for r in self._authorization_history if r["granted"]])
        denied = total - granted
        by_resource = {}
        for r in self._authorization_history:
            res = r["resource"]
            by_resource[res] = by_resource.get(res, 0) + 1
        return {
            "total_authorizations": total,
            "granted_count": granted,
            "denied_count": denied,
            "grant_rate": granted / total if total > 0 else 0,
            "by_resource": by_resource,
            "registered_roles": len(self._roles),
            "version": self._version,
        }

    def invalidate_cache(self, role_name: str | None = None):
        with self._cache_lock:
            if role_name:
                self._permission_cache.pop(role_name, None)
            else:
                self._permission_cache.clear()

    def reset(self):
        self._roles = STANDARD_ROLES.copy()
        self._permission_cache.clear()
        self._authorization_history = []
        self._version += 1
        self._audit_trail = []


# ============================================================================
# AUTHORITY MATRIX (SEDERHANA) untuk kompatibilitas dengan fastapi_auth_jwt_middleware
# ============================================================================


class AuthorityMatrix:
    """
    Wrapper sederhana untuk AuthorityMatrixGuard yang menyediakan method
    has_permission(role_name, permission_string) dan get_permissions_for_role.
    """

    def __init__(self):
        self._guard = get_authority_matrix_guard()
        self._session_maker = None  # akan di-inject dari luar

    def set_session_maker(self, session_maker: Any) -> None:
        """
        Set session factory (callable yang mengembalikan session) untuk digunakan
        saat mengambil role dari database. Harus dipanggil sekali di bootstrap
        dengan session_maker dari infrastructure.
        """
        self._session_maker = session_maker
        logger.info("AuthorityMatrix.session_maker has been set.")

    def has_permission(self, role_name: str, permission: str) -> bool:
        if ":" not in permission:
            return False
        resource_str, action_str = permission.split(":", 1)
        try:
            resource = ResourceType(resource_str)
        except ValueError:
            return False
        try:
            action = Action(action_str)
        except ValueError:
            return False
        role = STANDARD_ROLES.get(role_name)
        if not role:
            return False
        for perm in role.permissions:
            if perm.resource == resource and perm.action == action:
                return True
        if role.parent_role:
            return self.has_permission(role.parent_role, permission)
        return False

    async def is_allowed(
        self,
        user_id: Any,
        resource: str,
        action: str,
        legal_entity_id: Any | None = None,
    ) -> bool:
        """
        Method ini yang dipanggil oleh RBACEnforcer.check_permission() sebagai
        lapisan fallback setelah pengecekan permission langsung dari DB gagal.

        PERBAIKAN: Sekarang tidak lagi mengimpor dari infrastructure, melainkan
        menggunakan session_maker yang harus diset sebelumnya melalui
        set_session_maker() di bootstrap.
        """
        user_repo = getattr(self._guard, "_user_repo", None)
        if user_repo is None:
            logger.warning("is_allowed: tidak ada user repository terpasang, deny by default")
            return False

        role_names: list[str] = []
        try:
            if hasattr(user_repo, "get_user_roles") and hasattr(user_repo, "set_session"):
                # Repo bergaya SQLAlchemyIAMUserRepository: butuh session per-panggilan.
                if self._session_maker is None:
                    logger.error(
                        "is_allowed: session_maker belum diset. "
                        "Panggil AuthorityMatrix.set_session_maker() di bootstrap."
                    )
                    return False
                db_session = self._session_maker()
                try:
                    user_repo.set_session(db_session)
                    raw_roles = await user_repo.get_user_roles(user_id)
                    role_names = [
                        getattr(r, "role_name", None) or getattr(r, "name", None) or str(r)
                        for r in raw_roles
                    ]
                finally:
                    await db_session.close()
            elif hasattr(user_repo, "get_roles"):
                # Kontrak _FallbackUserRepository lama (in-memory, tanpa session).
                role_names = await user_repo.get_roles(str(user_id))
            else:
                logger.warning(
                    "is_allowed: %s tidak punya get_user_roles()/get_roles(), deny by default",
                    type(user_repo).__name__,
                )
                return False
        except Exception as e:
            logger.warning(
                "is_allowed: gagal resolve role untuk user %s: %s", user_id, type(e).__name__
            )
            return False

        if not role_names:
            role_names = ["guest"]

        permission = f"{resource}:{action}"
        # FIX: SIM110 - gunakan any() sebagai ganti for loop
        return any(self.has_permission(role_name, permission) for role_name in role_names)

    def get_permissions_for_role(self, role_name: str) -> list[str]:
        role = STANDARD_ROLES.get(role_name)
        if not role:
            return []
        perms = []
        for perm in role.permissions:
            perms.append(f"{perm.resource.value}:{perm.action.value}")
        return perms

    def add_permission_to_role(self, role_name: str, permission: str) -> None:
        if role_name not in STANDARD_ROLES:
            new_role = Role(name=role_name, permissions=[], description="Dynamic role")
            STANDARD_ROLES[role_name] = new_role
        if ":" in permission:
            res_str, act_str = permission.split(":", 1)
            try:
                resource = ResourceType(res_str)
            except ValueError:
                return
            try:
                action = Action(act_str)
            except ValueError:
                return
            new_perm = Permission(resource=resource, action=action)
            STANDARD_ROLES[role_name].permissions.append(new_perm)


# ============================================================================
# SINGLETON ACCESSOR
# ============================================================================

_authority_matrix_guard_instance: AuthorityMatrixGuard | None = None
_lock_instance = threading.Lock()


def get_authority_matrix_guard() -> AuthorityMatrixGuard:
    global _authority_matrix_guard_instance
    if _authority_matrix_guard_instance is None:
        with _lock_instance:
            if _authority_matrix_guard_instance is None:
                _authority_matrix_guard_instance = AuthorityMatrixGuard()
    return _authority_matrix_guard_instance


def set_authority_matrix_user_repository(user_repository: Any) -> None:
    """
    Inject user repository ASLI (mis. SQLAlchemyIAMUserRepository) ke singleton
    guard, menggantikan _FallbackUserRepository in-memory.

    WAJIB dipanggil sekali saat startup aplikasi (di service_registry / bootstrap),
    setelah IAMUserRepositoryPort berhasil di-resolve dari IoC container.
    Tanpa ini, guard akan selalu memakai fallback in-memory yang tidak tahu
    role user yang sesungguhnya tersimpan di database, sehingga semua
    authorization check akan gagal (403) walau user sudah berhasil login.

    Contoh pemakaian (di bootstrap/dependency_container/service_registry.py):

        from kernel.guards.authority_matrix import set_authority_matrix_user_repository
        set_authority_matrix_user_repository(resolved_iam_user_repository)
    """
    global _authority_matrix_guard_instance
    with _lock_instance:
        _authority_matrix_guard_instance = AuthorityMatrixGuard(user_repository=user_repository)
        logger.info(
            "AuthorityMatrixGuard re-wired dengan user repository asli: %s",
            type(user_repository).__name__,
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "STANDARD_ROLES",
    "Action",
    "AuthorityMatrix",
    "AuthorityMatrixGuard",
    "Permission",
    "PermissionEffect",
    "PermissionScope",
    "ResourceType",
    "Role",
    "get_authority_matrix_guard",
]
