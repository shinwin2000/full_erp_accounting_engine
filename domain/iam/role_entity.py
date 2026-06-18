#!/usr/bin/env python3
"""
Module: role_entity.py
Layer: Domain / IAM
Responsibility: Entitas peran (role) dengan daftar izin dan semua method entity dasar.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.iam.permission_vo import PermissionVO

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class RoleStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"

    def display_name(self) -> str:
        names = {
            RoleStatus.ACTIVE: "Aktif",
            RoleStatus.INACTIVE: "Tidak Aktif",
            RoleStatus.ARCHIVED: "Diarsipkan",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> RoleStatus | None:
        for s in cls:
            if s.value == value.lower():
                return s
        return None


# ============================================================================
# Custom Exceptions
# ============================================================================


class RoleError(ValueError):
    pass


class InvalidRoleStatusTransitionError(RoleError):
    pass


class DuplicatePermissionError(RoleError):
    pass


class PermissionNotFoundError(RoleError):
    pass


# ============================================================================
# Role Entity
# ============================================================================


@dataclass
class RoleEntity:
    role_id: UUID
    role_name: str
    description: str
    permissions: set[str]
    status: RoleStatus = RoleStatus.ACTIVE
    parent_role_id: UUID | None = None
    is_default: bool = False
    is_system: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        if not self.role_name or len(self.role_name.strip()) < 2:
            raise RoleError("Role name must be at least 2 characters")
        if len(self.role_name) > 50:
            raise RoleError("Role name must not exceed 50 characters")
        if not re.match(r"^[a-zA-Z0-9_]+$", self.role_name):
            raise RoleError("Role name must contain only letters, numbers, and underscores")
        if self.parent_role_id == self.role_id:
            raise RoleError("Role cannot be its own parent")
        if not isinstance(self.status, RoleStatus):
            raise RoleError(f"Invalid status: {self.status}")
        if self.version < 1:
            raise RoleError("Version must be >= 1")
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "role_id": str(self.role_id),
            "role_name": self.role_name,
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "role_id": str(self.role_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> RoleEntity:
        self._record_audit("CREATE", created_by, {"role_name": self.role_name})
        return self

    def update(self, updated_by: str, **kwargs) -> RoleEntity:
        if self.status == RoleStatus.ARCHIVED:
            raise InvalidRoleStatusTransitionError("Cannot update archived role")
        if self.is_system and "role_name" in kwargs:
            raise RoleError("Cannot rename system role")

        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("role_id", "created_at", "created_by", "version"):
                data[key] = value

        new_role = RoleEntity(
            role_id=self.role_id,
            role_name=data.get("role_name", self.role_name),
            description=data.get("description", self.description),
            permissions=set(data.get("permissions", list(self.permissions))),
            status=RoleStatus.from_string(data.get("status", self.status.value)) or self.status,
            parent_role_id=UUID(data["parent_role_id"]) if data.get("parent_role_id") else None,
            is_default=data.get("is_default", self.is_default),
            is_system=self.is_system,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            metadata=data.get("metadata", self.metadata),
        )
        new_role._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_role

    def delete(self, deleted_by: str, reason: str | None = None) -> RoleEntity:
        if self.is_system:
            raise RoleError(f"Cannot delete system role {self.role_name}")
        if self.status == RoleStatus.ARCHIVED:
            return self

        new_role = self._copy()
        new_role.status = RoleStatus.ARCHIVED
        new_role.updated_at = datetime.now(UTC)
        new_role.version = self.version + 1
        new_role._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_role

    def restore(self, restored_by: str) -> RoleEntity:
        if self.status != RoleStatus.ARCHIVED:
            raise InvalidRoleStatusTransitionError(
                f"Cannot restore role in status {self.status.value}"
            )

        new_role = self._copy()
        new_role.status = RoleStatus.ACTIVE
        new_role.updated_at = datetime.now(UTC)
        new_role.version = self.version + 1
        new_role._record_audit("RESTORE", restored_by, {})
        return new_role

    def activate(self, activated_by: str) -> RoleEntity:
        if self.status == RoleStatus.ACTIVE:
            return self
        if self.status == RoleStatus.ARCHIVED:
            raise InvalidRoleStatusTransitionError("Cannot activate archived role")

        new_role = self._copy()
        new_role.status = RoleStatus.ACTIVE
        new_role.updated_at = datetime.now(UTC)
        new_role.version = self.version + 1
        new_role._record_audit("ACTIVATE", activated_by, {})
        return new_role

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> RoleEntity:
        if self.status == RoleStatus.INACTIVE:
            return self
        if self.is_default:
            raise RoleError("Cannot deactivate default role")

        new_role = self._copy()
        new_role.status = RoleStatus.INACTIVE
        new_role.updated_at = datetime.now(UTC)
        new_role.version = self.version + 1
        new_role._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_role

    def lock(self, locked_by: str, reason: str) -> RoleEntity:
        new_role = self._copy()
        new_role.metadata["locked_by"] = locked_by
        new_role.metadata["locked_at"] = datetime.now(UTC).isoformat()
        new_role.metadata["lock_reason"] = reason
        new_role.updated_at = datetime.now(UTC)
        new_role.version = self.version + 1
        new_role._record_audit("LOCK", locked_by, {"reason": reason})
        return new_role

    def unlock(self, unlocked_by: str) -> RoleEntity:
        new_role = self._copy()
        new_role.metadata.pop("locked_by", None)
        new_role.metadata.pop("locked_at", None)
        new_role.metadata.pop("lock_reason", None)
        new_role.updated_at = datetime.now(UTC)
        new_role.version = self.version + 1
        new_role._record_audit("UNLOCK", unlocked_by, {})
        return new_role

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except RoleError as e:
            errors.append(str(e))

        # Validate permissions format
        for perm in self.permissions:
            try:
                PermissionVO.from_string(perm)
            except ValueError as e:
                errors.append(f"Invalid permission format '{perm}': {e}")

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "role_id": str(self.role_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_id": str(self.role_id),
            "role_name": self.role_name,
            "description": self.description,
            "permissions": sorted(list(self.permissions)),
            "status": self.status.value,
            "parent_role_id": str(self.parent_role_id) if self.parent_role_id else None,
            "is_default": self.is_default,
            "is_system": self.is_system,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoleEntity:
        status = RoleStatus.from_string(data.get("status", "active")) or RoleStatus.ACTIVE
        created_at = datetime.fromisoformat(data["created_at"])
        updated_at = datetime.fromisoformat(data["updated_at"])
        return cls(
            role_id=UUID(data["role_id"]),
            role_name=data["role_name"],
            description=data["description"],
            permissions=set(data.get("permissions", [])),
            status=status,
            parent_role_id=UUID(data["parent_role_id"]) if data.get("parent_role_id") else None,
            is_default=data.get("is_default", False),
            is_system=data.get("is_system", False),
            created_at=created_at,
            updated_at=updated_at,
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
            metadata=data.get("metadata", {}),
        )

    def clone(self, new_name: str | None = None) -> RoleEntity:
        new_id = uuid4()
        new_name_str = new_name or f"{self.role_name}_COPY"
        now = datetime.now(UTC)
        cloned = RoleEntity(
            role_id=new_id,
            role_name=new_name_str,
            description=f"Cloned from {self.role_name}",
            permissions=self.permissions.copy(),
            status=RoleStatus.INACTIVE,
            parent_role_id=None,
            is_default=False,
            is_system=False,
            created_at=now,
            updated_at=now,
            created_by=self.created_by,
            version=1,
        )
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.role_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "role_id": str(self.role_id),
            "role_name": self.role_name,
            "status": self.status.value,
            "permission_count": len(self.permissions),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> RoleEntity:
        new_role = self._copy()
        new_role.updated_at = datetime.now(UTC)
        new_role.version = self.version + 1
        new_role._record_audit("TOUCH", touched_by, {})
        return new_role

    # ==================== BUSINESS LOGIC ====================

    @property
    def is_active(self) -> bool:
        return self.status == RoleStatus.ACTIVE

    @property
    def is_inactive(self) -> bool:
        return self.status == RoleStatus.INACTIVE

    @property
    def is_archived(self) -> bool:
        return self.status == RoleStatus.ARCHIVED

    @property
    def permission_count(self) -> int:
        return len(self.permissions)

    def add_permission(self, permission: str, added_by: str) -> RoleEntity:
        if self.status == RoleStatus.ARCHIVED:
            raise InvalidRoleStatusTransitionError("Cannot modify archived role")
        if permission in self.permissions:
            raise DuplicatePermissionError(
                f"Permission '{permission}' already exists in role {self.role_name}"
            )

        new_permissions = set(self.permissions)
        new_permissions.add(permission)

        new_role = self._copy()
        new_role.permissions = new_permissions
        new_role.updated_at = datetime.now(UTC)
        new_role.version = self.version + 1
        new_role._record_audit("ADD_PERMISSION", added_by, {"permission": permission})
        return new_role

    def add_permissions(self, permissions: list[str], added_by: str) -> RoleEntity:
        if self.status == RoleStatus.ARCHIVED:
            raise InvalidRoleStatusTransitionError("Cannot modify archived role")

        new_permissions = set(self.permissions)
        for perm in permissions:
            new_permissions.add(perm)

        new_role = self._copy()
        new_role.permissions = new_permissions
        new_role.updated_at = datetime.now(UTC)
        new_role.version = self.version + 1
        new_role._record_audit("ADD_PERMISSIONS", added_by, {"permissions": permissions})
        return new_role

    def remove_permission(self, permission: str, removed_by: str) -> RoleEntity:
        if self.status == RoleStatus.ARCHIVED:
            raise InvalidRoleStatusTransitionError("Cannot modify archived role")
        if permission not in self.permissions:
            raise PermissionNotFoundError(
                f"Permission '{permission}' not found in role {self.role_name}"
            )

        new_permissions = set(self.permissions)
        new_permissions.discard(permission)

        new_role = self._copy()
        new_role.permissions = new_permissions
        new_role.updated_at = datetime.now(UTC)
        new_role.version = self.version + 1
        new_role._record_audit("REMOVE_PERMISSION", removed_by, {"permission": permission})
        return new_role

    def set_permissions(self, permissions: set[str], updated_by: str) -> RoleEntity:
        if self.status == RoleStatus.ARCHIVED:
            raise InvalidRoleStatusTransitionError("Cannot modify archived role")

        new_role = self._copy()
        new_role.permissions = permissions.copy()
        new_role.updated_at = datetime.now(UTC)
        new_role.version = self.version + 1
        new_role._record_audit(
            "SET_PERMISSIONS", updated_by, {"permission_count": len(permissions)}
        )
        return new_role

    def update_description(self, description: str, updated_by: str) -> RoleEntity:
        if self.status == RoleStatus.ARCHIVED:
            raise InvalidRoleStatusTransitionError("Cannot modify archived role")

        new_role = self._copy()
        new_role.description = description
        new_role.updated_at = datetime.now(UTC)
        new_role.version = self.version + 1
        new_role._record_audit("UPDATE_DESCRIPTION", updated_by, {})
        return new_role

    def set_parent(
        self, parent_role_id: UUID | None, updated_by: str, parent_getter: callable | None = None
    ) -> RoleEntity:
        if self.status == RoleStatus.ARCHIVED:
            raise InvalidRoleStatusTransitionError("Cannot modify archived role")
        if parent_role_id == self.role_id:
            raise RoleError("Role cannot be its own parent")

        # Check for cycle if parent_getter is provided
        if parent_getter and parent_role_id:
            current = parent_role_id
            visited = set()
            while current and current not in visited:
                if current == self.role_id:
                    raise RoleError("Setting this parent would create a cycle")
                visited.add(current)
                parent = parent_getter(current)
                current = parent.role_id if parent else None

        new_role = self._copy()
        new_role.parent_role_id = parent_role_id
        new_role.updated_at = datetime.now(UTC)
        new_role.version = self.version + 1
        new_role._record_audit(
            "SET_PARENT",
            updated_by,
            {"parent_role_id": str(parent_role_id) if parent_role_id else None},
        )
        return new_role

    def has_permission(self, permission: str, role_getter: callable | None = None) -> bool:
        """
        Check if role (including parent) has permission.

        Args:
            permission: Permission string to check
            role_getter: Function to get parent role by ID (for hierarchy)
        """
        if permission in self.permissions:
            return True

        if role_getter and self.parent_role_id:
            parent_role = role_getter(self.parent_role_id)
            if parent_role:
                return parent_role.has_permission(permission, role_getter)
        return False

    def get_all_permissions(self, role_getter: callable | None = None) -> set[str]:
        """
        Get all permissions including inherited from parent roles.

        Args:
            role_getter: Function to get parent role by ID (for hierarchy)
        """
        all_perms = set(self.permissions)

        if role_getter and self.parent_role_id:
            parent_role = role_getter(self.parent_role_id)
            if parent_role:
                all_perms.update(parent_role.get_all_permissions(role_getter))

        return all_perms

    def get_hierarchy(self, role_getter: callable) -> list[RoleEntity]:
        """Get role hierarchy from this role up to root."""
        hierarchy = [self]
        if self.parent_role_id:
            parent = role_getter(self.parent_role_id)
            if parent:
                hierarchy.extend(parent.get_hierarchy(role_getter))
        return hierarchy

    def is_descendant_of(self, ancestor_role_id: UUID, role_getter: callable) -> bool:
        """Check if this role is a descendant of the given ancestor role."""
        if self.parent_role_id == ancestor_role_id:
            return True
        if self.parent_role_id:
            parent = role_getter(self.parent_role_id)
            if parent:
                return parent.is_descendant_of(ancestor_role_id, role_getter)
        return False

    def is_ancestor_of(self, descendant_role_id: UUID, role_getter: callable) -> bool:
        """Check if this role is an ancestor of the given descendant role."""
        descendant = role_getter(descendant_role_id)
        if descendant:
            return descendant.is_descendant_of(self.role_id, role_getter)
        return False

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> RoleEntity:
        return RoleEntity(
            role_id=self.role_id,
            role_name=self.role_name,
            description=self.description,
            permissions=self.permissions.copy(),
            status=self.status,
            parent_role_id=self.parent_role_id,
            is_default=self.is_default,
            is_system=self.is_system,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            version=self.version,
            metadata=self.metadata.copy(),
        )


# ============================================================================
# Repository Implementation
# ============================================================================


class RoleRepository:
    _storage: ClassVar[dict[UUID, RoleEntity]] = {}
    _storage_by_name: ClassVar[dict[str, UUID]] = {}

    @classmethod
    async def get_by_id(cls, role_id: UUID) -> RoleEntity | None:
        return cls._storage.get(role_id)

    @classmethod
    async def get_by_name(cls, role_name: str) -> RoleEntity | None:
        role_id = cls._storage_by_name.get(role_name)
        return cls._storage.get(role_id) if role_id else None

    @classmethod
    async def get_default_role(cls) -> RoleEntity | None:
        for role in cls._storage.values():
            if role.is_default and role.is_active:
                return role
        return None

    @classmethod
    async def get_by_status(cls, status: RoleStatus) -> list[RoleEntity]:
        return [r for r in cls._storage.values() if r.status == status]

    @classmethod
    async def get_active(cls) -> list[RoleEntity]:
        return [r for r in cls._storage.values() if r.is_active]

    @classmethod
    async def get_children(cls, parent_role_id: UUID) -> list[RoleEntity]:
        return [r for r in cls._storage.values() if r.parent_role_id == parent_role_id]

    @classmethod
    async def get_descendants(
        cls, ancestor_role_id: UUID, role_getter: callable | None = None
    ) -> list[RoleEntity]:
        """Get all descendant roles."""
        children = await cls.get_children(ancestor_role_id)
        descendants = []
        for child in children:
            descendants.append(child)
            descendants.extend(await cls.get_descendants(child.role_id))
        return descendants

    @classmethod
    async def get_all(cls) -> list[RoleEntity]:
        return list(cls._storage.values())

    @classmethod
    async def save(cls, role: RoleEntity) -> None:
        cls._storage[role.role_id] = role
        cls._storage_by_name[role.role_name] = role.role_id

    @classmethod
    async def update(cls, role: RoleEntity) -> None:
        await cls.save(role)

    @classmethod
    async def delete(cls, role_id: UUID) -> None:
        role = cls._storage.get(role_id)
        if role:
            cls._storage_by_name.pop(role.role_name, None)
            cls._storage.pop(role_id, None)

    @classmethod
    async def exists(cls, role_id: UUID) -> bool:
        return role_id in cls._storage

    @classmethod
    async def exists_by_name(cls, role_name: str) -> bool:
        return role_name in cls._storage_by_name

    @classmethod
    async def count(cls) -> int:
        return len(cls._storage)

    @classmethod
    async def list(cls, limit: int = 100, offset: int = 0) -> list[RoleEntity]:
        roles = list(cls._storage.values())
        return roles[offset : offset + limit]

    @classmethod
    async def paginate(cls, page: int = 1, per_page: int = 20) -> tuple[list[RoleEntity], int]:
        roles = list(cls._storage.values())
        total = len(roles)
        start = (page - 1) * per_page
        end = start + per_page
        return roles[start:end], total

    @classmethod
    async def search(cls, query: str, fields: list[str] | None = None) -> list[RoleEntity]:
        if fields is None:
            fields = ["role_name", "description"]
        query_lower = query.lower()
        results = []
        for role in cls._storage.values():
            for field in fields:
                value = getattr(role, field, "")
                if value and query_lower in str(value).lower():
                    results.append(role)
                    break
        return results

    @classmethod
    async def clear(cls) -> None:
        cls._storage.clear()
        cls._storage_by_name.clear()


# ============================================================================
# Alias for compatibility
# ============================================================================

Role = RoleEntity


__all__ = [
    "DuplicatePermissionError",
    "InvalidRoleStatusTransitionError",
    "PermissionNotFoundError",
    "Role",
    "RoleEntity",
    "RoleError",
    "RoleRepository",
    "RoleStatus",
]
