#!/usr/bin/env python3
from __future__ import annotations

"""
Module: authority_matrix.py
Layer: Infrastructure / Security
Responsibility: Matriks otorisasi untuk RBAC. Mendefinisikan permission untuk setiap role.
"""

from kernel.guards.authority_matrix import (
    STANDARD_ROLES,
    AuthorityMatrixGuard,
    get_authority_matrix_guard,
)


class AuthorityMatrix:
    """
    Matriks otorisasi (wrapper) yang kompatibel dengan rbac_enforcer_unified.
    """

    def __init__(self):
        self._guard = get_authority_matrix_guard()

    def has_permission(self, role_name: str, permission: str) -> bool:
        """Memeriksa apakah role memiliki permission."""
        # Menggunakan method yang ada di guard
        # Cek wildcard dll
        if permission == "*:*":
            return True
        # Bagi permission menjadi resource:action
        if ":" in permission:
            resource_str, action_str = permission.split(":", 1)
            # Coba mapping ke enum
            from kernel.guards.authority_matrix import Action, ResourceType

            try:
                resource = ResourceType(resource_str)
            except ValueError:
                resource = resource_str  # fallback ke string
            try:
                action = Action(action_str)
            except ValueError:
                action = action_str
            # Gunakan guard (perlu user_id, tapi kita bisa bypass karena role-based)
            # Untuk sementara, kita asumsikan role memiliki permission jika ada di STANDARD_ROLES
            role = STANDARD_ROLES.get(role_name)
            if role:
                for perm in role.permissions:
                    if perm.resource == resource and perm.action == action:
                        return True
        return False

    def get_permissions_for_role(self, role_name: str) -> list:
        """Mendapatkan daftar permission untuk role."""
        role = STANDARD_ROLES.get(role_name)
        if role:
            return [f"{p.resource.value}:{p.action.value}" for p in role.permissions]
        return []

    def add_permission_to_role(self, role_name: str, permission: str) -> None:
        """Menambahkan permission ke role (untuk dynamic)."""
        # Implementasi sederhana: update STANDARD_ROLES (tidak permanen)
        if role_name not in STANDARD_ROLES:
            from kernel.guards.authority_matrix import (
                Action,
                Permission,
                ResourceType,
                Role,
            )

            new_role = Role(name=role_name, permissions=[], description="Dynamic role")
            STANDARD_ROLES[role_name] = new_role
        if ":" in permission:
            res_str, act_str = permission.split(":", 1)
            try:
                resource = ResourceType(res_str)
            except ValueError:
                resource = res_str
            try:
                action = Action(act_str)
            except ValueError:
                action = act_str
            new_perm = Permission(resource=resource, action=action)
            STANDARD_ROLES[role_name].permissions.append(new_perm)


__all__ = [
    "STANDARD_ROLES",
    "AuthorityMatrix",
    "AuthorityMatrixGuard",
    "get_authority_matrix_guard",
]
