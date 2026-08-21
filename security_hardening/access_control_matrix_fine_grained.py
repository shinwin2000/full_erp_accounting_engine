#!/usr/bin/env python3
"""
Module: access_control_matrix_fine_grained.py
Layer: Security Hardening

Responsibility:
    Implementasi matriks kontrol akses fine-grained yang menggabungkan
    RBAC dan ABAC. Mendukung permission inheritance, dynamic attributes,
    policy evaluation, export/import kebijakan, dan audit trail.

Metode yang ditambahkan:
- Untuk Permission, Role, User: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk AccessControlMatrix: semua entity dasar serta get_statistics, reset, dll.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from .security_exceptions import AuthorizationError

logger = logging.getLogger(__name__)


# ============================================================================
# Enums (dengan method display_name)
# ============================================================================
class PermissionType(Enum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    APPROVE = "approve"
    REJECT = "reject"
    EXPORT = "export"
    IMPERSONATE = "impersonate"
    AUDIT = "audit"
    CONFIGURE = "configure"

    def display_name(self) -> str:
        names = {
            PermissionType.CREATE: "Buat",
            PermissionType.READ: "Baca",
            PermissionType.UPDATE: "Ubah",
            PermissionType.DELETE: "Hapus",
            PermissionType.APPROVE: "Setujui",
            PermissionType.REJECT: "Tolak",
            PermissionType.EXPORT: "Ekspor",
            PermissionType.IMPERSONATE: "Impersonasi",
            PermissionType.AUDIT: "Audit",
            PermissionType.CONFIGURE: "Konfigurasi",
        }
        return names.get(self, self.value)


class ResourceType(Enum):
    JOURNAL = "journal"
    ACCOUNT = "account"
    INVOICE = "invoice"
    PAYMENT = "payment"
    USER = "user"
    ROLE = "role"
    REPORT = "report"
    SYSTEM_SETTING = "system_setting"
    AUDIT_LOG = "audit_log"
    TAX_SUBMISSION = "tax_submission"
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    BANK_ACCOUNT = "bank_account"

    def display_name(self) -> str:
        names = {
            ResourceType.JOURNAL: "Jurnal",
            ResourceType.ACCOUNT: "Akun",
            ResourceType.INVOICE: "Faktur",
            ResourceType.PAYMENT: "Pembayaran",
            ResourceType.USER: "Pengguna",
            ResourceType.ROLE: "Peran",
            ResourceType.REPORT: "Laporan",
            ResourceType.SYSTEM_SETTING: "Pengaturan Sistem",
            ResourceType.AUDIT_LOG: "Log Audit",
            ResourceType.TAX_SUBMISSION: "SPT",
            ResourceType.CUSTOMER: "Pelanggan",
            ResourceType.SUPPLIER: "Pemasok",
            ResourceType.BANK_ACCOUNT: "Rekening Bank",
        }
        return names.get(self, self.value)


# ============================================================================
# Permission Class (dengan entity dasar)
# ============================================================================
class Permission:
    def __init__(
        self,
        resource_type: ResourceType,
        permission: PermissionType,
        resource_id: str | UUID | None = None,
        attributes: dict[str, Any] | None = None,
    ):
        self.resource_type = resource_type
        self.permission = permission
        self.resource_id = resource_id
        self.attributes = attributes or {}
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "resource_type": self.resource_type.value,
                "permission": self.permission.value,
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

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors: list[str] = []  # FIX: tambahkan type annotation
        if not isinstance(self.resource_type, ResourceType):
            errors.append("Invalid resource_type")
        if not isinstance(self.permission, PermissionType):
            errors.append("Invalid permission")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict:
        return {
            "resource_type": self.resource_type.value,
            "permission": self.permission.value,
            "resource_id": str(self.resource_id) if self.resource_id else None,
            "attributes": self.attributes,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Permission:
        instance = cls(
            resource_type=ResourceType(data["resource_type"]),
            permission=PermissionType(data["permission"]),
            resource_id=UUID(data["resource_id"]) if data.get("resource_id") else None,
            attributes=data.get("attributes", {}),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> Permission:
        new = Permission(
            resource_type=self.resource_type,
            permission=self.permission,
            resource_id=self.resource_id,
            attributes=self.attributes.copy(),
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": str(id(self))})
        return new

    def snapshot(self) -> dict:
        return {
            "version": self._version,
            "resource_type": self.resource_type.value,
            "permission": self.permission.value,
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> Permission:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# Role Class (dengan entity dasar)
# ============================================================================
class Role:
    def __init__(
        self,
        role_id: UUID,
        name: str,
        permissions: list[Permission],
        parent_role_id: UUID | None = None,
        description: str = "",
    ):
        self.id = role_id
        self.name = name
        self.permissions = permissions
        self.parent_role_id = parent_role_id
        self.description = description
        self.created_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)
        self._hash = self._compute_hash()
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "role_id": str(self.id),
                "name": self.name,
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
                "role_id": str(self.id),
                "details": details,
            }
        )

    def _compute_hash(self) -> str:
        data = {
            "id": str(self.id),
            "name": self.name,
            "permissions_count": len(self.permissions),
            "parent": str(self.parent_role_id) if self.parent_role_id else None,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    def add_permission(self, perm: Permission) -> None:
        self.permissions.append(perm)
        self.updated_at = datetime.now(UTC)
        self._hash = self._compute_hash()
        self._version += 1
        self._record_audit("ADD_PERMISSION", "system", {"permission": perm.permission.value})

    def remove_permission(self, perm: Permission) -> bool:
        for i, p in enumerate(self.permissions):
            if (
                p.resource_type == perm.resource_type
                and p.permission == perm.permission
                and p.resource_id == perm.resource_id
            ):
                del self.permissions[i]
                self.updated_at = datetime.now(UTC)
                self._hash = self._compute_hash()
                self._version += 1
                self._record_audit(
                    "REMOVE_PERMISSION", "system", {"permission": perm.permission.value}
                )
                return True
        return False

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.name:
            errors.append("Role name is required")
        if self.parent_role_id == self.id:
            errors.append("Role cannot be its own parent")
        for p in self.permissions:
            res = p.validate()
            if not res["is_valid"]:
                errors.extend(res["errors"])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "permissions": [p.to_dict() for p in self.permissions],
            "parent_role_id": str(self.parent_role_id) if self.parent_role_id else None,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "hash": self._hash,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Role:
        perms = [Permission.from_dict(p) for p in data.get("permissions", [])]
        instance = cls(
            role_id=UUID(data["id"]),
            name=data["name"],
            permissions=perms,
            parent_role_id=UUID(data["parent_role_id"]) if data.get("parent_role_id") else None,
            description=data.get("description", ""),
        )
        instance.created_at = datetime.fromisoformat(data["created_at"])
        instance.updated_at = datetime.fromisoformat(data["updated_at"])
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> Role:
        new_id = uuid4()
        cloned = Role(
            role_id=new_id,
            name=f"{self.name}_COPY",
            permissions=[p.clone() for p in self.permissions],
            parent_role_id=self.parent_role_id,
            description=f"Cloned from {self.name}",
        )
        cloned._version = self._version + 1
        cloned._record_audit("CLONE", "system", {"source": str(self.id)})
        return cloned

    def snapshot(self) -> dict:
        return {
            "version": self._version,
            "role_id": str(self.id),
            "name": self.name,
            "permissions_count": len(self.permissions),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> Role:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# User Class (dengan entity dasar)
# ============================================================================
class User:
    def __init__(
        self,
        user_id: UUID,
        username: str,
        roles: list[UUID],
        attributes: dict[str, Any] | None = None,
        email: str = "",
    ):
        self.id = user_id
        self.username = username
        self.roles = roles
        self.attributes = attributes or {}
        self.email = email
        self.created_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)
        self._hash = self._compute_hash()
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "user_id": str(self.id),
                "username": self.username,
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
                "user_id": str(self.id),
                "details": details,
            }
        )

    def _compute_hash(self) -> str:
        data = {
            "id": str(self.id),
            "username": self.username,
            "roles": [str(r) for r in self.roles],
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    def assign_role(self, role_id: UUID) -> None:
        if role_id not in self.roles:
            self.roles.append(role_id)
            self.updated_at = datetime.now(UTC)
            self._hash = self._compute_hash()
            self._version += 1
            self._record_audit("ASSIGN_ROLE", "system", {"role_id": str(role_id)})

    def revoke_role(self, role_id: UUID) -> bool:
        if role_id in self.roles:
            self.roles.remove(role_id)
            self.updated_at = datetime.now(UTC)
            self._hash = self._compute_hash()
            self._version += 1
            self._record_audit("REVOKE_ROLE", "system", {"role_id": str(role_id)})
            return True
        return False

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.username:
            errors.append("Username is required")
        if self.email and "@" not in self.email:
            errors.append("Invalid email format")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "username": self.username,
            "roles": [str(r) for r in self.roles],
            "attributes": self.attributes,
            "email": self.email,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "hash": self._hash,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> User:
        instance = cls(
            user_id=UUID(data["id"]),
            username=data["username"],
            roles=[UUID(r) for r in data.get("roles", [])],
            attributes=data.get("attributes", {}),
            email=data.get("email", ""),
        )
        instance.created_at = datetime.fromisoformat(data["created_at"])
        instance.updated_at = datetime.fromisoformat(data["updated_at"])
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> User:
        new_id = uuid4()
        cloned = User(
            user_id=new_id,
            username=f"{self.username}_COPY",
            roles=self.roles.copy(),
            attributes=self.attributes.copy(),
            email=f"copy_{self.email}" if self.email else "",
        )
        cloned._version = self._version + 1
        cloned._record_audit("CLONE", "system", {"source": str(self.id)})
        return cloned

    def snapshot(self) -> dict:
        return {
            "version": self._version,
            "user_id": str(self.id),
            "username": self.username,
            "role_count": len(self.roles),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> User:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# AccessControlMatrix Core (dengan entity dasar lengkap)
# ============================================================================
class AccessControlMatrix:
    def __init__(self):
        self._roles: dict[UUID, Role] = {}
        self._users: dict[UUID, User] = {}
        self._role_hierarchy: dict[UUID, list[UUID]] = {}
        self._history: list[dict] = []
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "roles_count": len(self._roles),
                "users_count": len(self._users),
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

    def _record_history(self, action: str, entity_id: UUID, details: str) -> None:
        self._history.append(
            {
                "action": action,
                "entity_id": str(entity_id),
                "details": details,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        self._record_audit(action, "system", {"entity_id": str(entity_id), "details": details})

    # ------------------------------------------------------------------------
    # Role Management
    # ------------------------------------------------------------------------
    def add_role(
        self,
        name: str,
        permissions: list[Permission],
        parent_role_id: UUID | None = None,
        description: str = "",
    ) -> UUID:
        role_id = uuid4()
        role = Role(role_id, name, permissions, parent_role_id, description)
        self._roles[role_id] = role
        if parent_role_id:
            self._role_hierarchy.setdefault(parent_role_id, []).append(role_id)
        self._record_history("ADD_ROLE", role_id, name)
        logger.info(f"Role added: {name} (id={role_id})")
        return role_id

    def update_role(
        self, role_id: UUID, name: str | None = None, description: str | None = None
    ) -> bool:
        role = self._roles.get(role_id)
        if not role:
            return False
        if name:
            role.name = name
        if description:
            role.description = description
        role.updated_at = datetime.now(UTC)
        role._hash = role._compute_hash()
        role._version += 1
        self._record_history("UPDATE_ROLE", role_id, role.name)
        return True

    def delete_role(self, role_id: UUID) -> bool:
        if role_id not in self._roles:
            return False
        for user in self._users.values():
            if role_id in user.roles:
                user.roles.remove(role_id)
        for _, children in self._role_hierarchy.items():
            if role_id in children:
                children.remove(role_id)
        if role_id in self._role_hierarchy:
            for child in self._role_hierarchy[role_id]:
                if child in self._roles:
                    self._roles[child].parent_role_id = None
            del self._role_hierarchy[role_id]
        del self._roles[role_id]
        self._record_history("DELETE_ROLE", role_id, "")
        logger.info(f"Role deleted: {role_id}")
        return True

    def get_role(self, role_id: UUID) -> Role | None:
        return self._roles.get(role_id)

    def get_role_by_name(self, name: str) -> Role | None:
        for role in self._roles.values():
            if role.name == name:
                return role
        return None

    def list_roles(self) -> list[Role]:
        return list(self._roles.values())

    def add_permission_to_role(self, role_id: UUID, permission: Permission) -> bool:
        role = self._roles.get(role_id)
        if not role:
            return False
        role.add_permission(permission)
        self._record_history(
            "ADD_PERMISSION",
            role_id,
            f"{permission.resource_type.value}:{permission.permission.value}",
        )
        return True

    def remove_permission_from_role(self, role_id: UUID, permission: Permission) -> bool:
        role = self._roles.get(role_id)
        if not role:
            return False
        return role.remove_permission(permission)

    # ------------------------------------------------------------------------
    # User Management
    # ------------------------------------------------------------------------
    def register_user(
        self, user_id: UUID, username: str, email: str = "", attributes: dict | None = None
    ) -> None:
        if user_id in self._users:
            raise ValueError(f"User {user_id} already exists")
        self._users[user_id] = User(user_id, username, [], attributes or {}, email)
        self._record_history("REGISTER_USER", user_id, username)

    def get_user(self, user_id: UUID) -> User | None:
        return self._users.get(user_id)

    def assign_role_to_user(self, user_id: UUID, role_id: UUID) -> bool:
        user = self._users.get(user_id)
        role = self._roles.get(role_id)
        if not user or not role:
            return False
        user.assign_role(role_id)
        self._record_history("ASSIGN_ROLE", user_id, f"role={role_id}")
        return True

    def revoke_role_from_user(self, user_id: UUID, role_id: UUID) -> bool:
        user = self._users.get(user_id)
        if not user:
            return False
        return user.revoke_role(role_id)

    def get_user_roles(self, user_id: UUID) -> list[UUID]:
        user = self._users.get(user_id)
        return user.roles if user else []

    # ------------------------------------------------------------------------
    # Permission Resolution
    # ------------------------------------------------------------------------
    def _get_all_permissions_for_role(
        self, role_id: UUID, visited: set[UUID] | None = None
    ) -> list[Permission]:
        if visited is None:
            visited = set()
        if role_id in visited:
            return []
        visited.add(role_id)
        role = self._roles.get(role_id)
        if not role:
            return []
        perms = role.permissions.copy()
        if role.parent_role_id:
            parent_perms = self._get_all_permissions_for_role(role.parent_role_id, visited)
            perms.extend(parent_perms)
        return perms

    def get_user_permissions(self, user_id: UUID) -> set[tuple[str, str, str | None, frozenset]]:
        user = self._users.get(user_id)
        if not user:
            return set()
        all_perms = set()
        for role_id in user.roles:
            role_perms = self._get_all_permissions_for_role(role_id)
            for p in role_perms:
                key = (
                    p.resource_type.value,
                    p.permission.value,
                    str(p.resource_id) if p.resource_id else None,
                    frozenset(p.attributes.items()),
                )
                all_perms.add(key)
        return all_perms

    def has_permission(
        self,
        user_id: UUID,
        resource_type: ResourceType,
        permission: PermissionType,
        resource_id: str | UUID | None = None,
        context_attributes: dict | None = None,
    ) -> bool:
        user_perms = self.get_user_permissions(user_id)
        context_attrs = context_attributes or {}
        for rt, perm, res_id, perm_attrs in user_perms:
            if rt != resource_type.value or perm != permission.value:
                continue
            if res_id is not None and str(resource_id) != res_id:
                continue
            match = True
            for key, required_value in perm_attrs:
                actual = context_attrs.get(key)
                if actual is None:
                    user = self._users.get(user_id)
                    if user and key in user.attributes:
                        actual = user.attributes[key]
                if actual != required_value:
                    match = False
                    break
            if match:
                return True
        return False

    def enforce(
        self,
        user_id: UUID,
        resource_type: ResourceType,
        permission: PermissionType,
        resource_id: str | UUID | None = None,
        context_attributes: dict | None = None,
    ) -> None:
        if not self.has_permission(
            user_id, resource_type, permission, resource_id, context_attributes
        ):
            raise AuthorizationError(
                f"User {user_id} does not have {permission.value} permission on {resource_type.value}"
                + (f" {resource_id}" if resource_id else "")
            )

    def get_effective_permissions_for_resource(
        self,
        user_id: UUID,
        resource_type: ResourceType,
        resource_id: str | UUID | None = None,
    ) -> list[PermissionType]:
        result = []
        for perm_type in PermissionType:
            if self.has_permission(user_id, resource_type, perm_type, resource_id):
                result.append(perm_type)
        return result

    # ------------------------------------------------------------------------
    # Export/Import
    # ------------------------------------------------------------------------
    def export_policy(self) -> dict:
        return {
            "roles": {str(rid): r.to_dict() for rid, r in self._roles.items()},
            "users": {str(uid): u.to_dict() for uid, u in self._users.items()},
            "history": self._history[-100:],
            "version": self._version,
        }

    def import_policy(self, data: dict) -> None:
        self._roles.clear()
        self._users.clear()
        self._role_hierarchy.clear()
        for rid_str, role_data in data.get("roles", {}).items():
            rid = UUID(rid_str)
            parent = UUID(role_data["parent_role_id"]) if role_data.get("parent_role_id") else None
            permissions = [Permission.from_dict(p) for p in role_data.get("permissions", [])]
            role = Role(
                role_id=rid,
                name=role_data["name"],
                permissions=permissions,
                parent_role_id=parent,
                description=role_data.get("description", ""),
            )
            role.created_at = datetime.fromisoformat(role_data["created_at"])
            role.updated_at = datetime.fromisoformat(role_data["updated_at"])
            role._version = role_data.get("version", 1)
            self._roles[rid] = role
            if parent:
                self._role_hierarchy.setdefault(parent, []).append(rid)
        for uid_str, user_data in data.get("users", {}).items():
            uid = UUID(uid_str)
            roles = [UUID(r) for r in user_data.get("roles", [])]
            user = User(
                user_id=uid,
                username=user_data["username"],
                roles=roles,
                attributes=user_data.get("attributes", {}),
                email=user_data.get("email", ""),
            )
            user.created_at = datetime.fromisoformat(user_data["created_at"])
            user.updated_at = datetime.fromisoformat(user_data["updated_at"])
            user._version = user_data.get("version", 1)
            self._users[uid] = user
        self._version = data.get("version", 1)

    def to_json(self, file_path: str) -> None:
        with open(file_path, "w") as f:
            json.dump(self.export_policy(), f, indent=2, default=str)

    # ------------------------------------------------------------------------
    # Reporting & Stats
    # ------------------------------------------------------------------------
    def generate_report(self) -> dict:
        return {
            "total_roles": len(self._roles),
            "total_users": len(self._users),
            "role_hierarchy_depth": max(len(self._get_role_path(r)) for r in self._roles)
            if self._roles
            else 0,
            "permission_count": sum(len(r.permissions) for r in self._roles.values()),
            "version": self._version,
        }

    def get_statistics(self) -> dict[str, Any]:
        return self.generate_report()

    def _get_role_path(self, role_id: UUID) -> list[UUID]:
        path = []
        # FIX: deklarasikan current sebagai UUID | None
        current: UUID | None = role_id
        while current:
            path.append(current)
            role = self._roles.get(current)
            current = role.parent_role_id if role else None
        return path

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        for role in self._roles.values():
            res = role.validate()
            if not res["is_valid"]:
                errors.extend([f"Role {role.name}: {e}" for e in res["errors"]])
        for user in self._users.values():
            res = user.validate()
            if not res["is_valid"]:
                errors.extend([f"User {user.username}: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "roles": {str(k): v.to_dict() for k, v in self._roles.items()},
            "users": {str(k): v.to_dict() for k, v in self._users.items()},
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AccessControlMatrix:
        instance = cls()
        instance.import_policy(data)
        return instance

    def clone(self) -> AccessControlMatrix:
        new = AccessControlMatrix()
        new.import_policy(self.export_policy())
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "roles_count": len(self._roles),
            "users_count": len(self._users),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AccessControlMatrix:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._roles.clear()
        self._users.clear()
        self._role_hierarchy.clear()
        self._history.clear()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    acm = AccessControlMatrix()
    read_journal = Permission(ResourceType.JOURNAL, PermissionType.READ)
    create_journal = Permission(ResourceType.JOURNAL, PermissionType.CREATE)
    approve_journal = Permission(ResourceType.JOURNAL, PermissionType.APPROVE)

    viewer_role = acm.add_role("Viewer", [read_journal])
    editor_role = acm.add_role("Editor", [read_journal, create_journal], parent_role_id=viewer_role)
    approver_role = acm.add_role(
        "Approver", [read_journal, approve_journal], parent_role_id=editor_role
    )

    user_id = uuid4()
    acm.register_user(user_id, "john_doe", "john@example.com", {"department": "finance"})
    acm.assign_role_to_user(user_id, approver_role)

    print(
        f"User can approve journal: {acm.has_permission(user_id, ResourceType.JOURNAL, PermissionType.APPROVE)}"
    )

    try:
        acm.enforce(user_id, ResourceType.JOURNAL, PermissionType.CREATE)
        print("User can create journal")
    except AuthorizationError as e:
        print(f"Access denied: {e}")

    acm.to_json("access_control_policy.json")
    print("Policy exported")
