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
# AUTHORITY MATRIX GUARD
# ============================================================================


class AuthorityMatrixGuard:
    def __init__(self, user_repository: Any | None = None):
        self._user_repo = user_repository or _get_user_repository()
        self._roles: dict[str, Role] = STANDARD_ROLES.copy()
        self._permission_cache: dict[
            str, set[tuple[ResourceType, Action, PermissionScope, dict | None]]
        ] = {}
        self._cache_lock = threading.RLock()
        self._authorization_history: list[dict[str, Any]] = []
        self._max_history = 10000

    def register_role(self, role: Role) -> None:
        self._roles[role.name] = role
        with self._cache_lock:
            self._permission_cache.pop(role.name, None)
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

            if perm_scope == PermissionScope.SELF:
                if target_entity_id and current_entity and target_entity_id != current_entity:
                    continue
            elif perm_scope == PermissionScope.LEGAL_ENTITY:
                if current_entity is None:
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
            return {"total_authorizations": 0}
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
