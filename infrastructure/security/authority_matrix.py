#!/usr/bin/env python3
from __future__ import annotations

"""
Module: authority_matrix.py
Layer: Infrastructure / Security
Responsibility: Matriks otorisasi untuk RBAC. Mendefinisikan permission untuk setiap role.

PERBAIKAN (lihat riwayat debugging 403 Forbidden):
- Ditambahkan method `is_allowed()` async, yang sebelumnya TIDAK ADA sama
  sekali padahal dipanggil oleh RBACEnforcer.check_permission() dan
  RBACEnforcer.check_permissions_batch() di infrastructure/security/
  rbac_enforcer_unified.py. Tanpa method ini, setiap kali permission tidak
  ditemukan langsung di cache/DB, kode akan raise AttributeError yang
  akhirnya membuat request gagal (401/403 tergantung layer exception
  handling di middleware).
- `is_allowed()` melakukan resolusi role user secara defensif karena bentuk
  IAMUserRepositoryPort/real repository tidak seragam di seluruh codebase.
"""

import logging

from kernel.guards.authority_matrix import (
    STANDARD_ROLES,
    Action,
    AuthorityMatrixGuard,
    Permission,
    ResourceType,
    Role,
    get_authority_matrix_guard,
)

logger = logging.getLogger(__name__)


class AuthorityMatrix:
    """
    Matriks otorisasi (wrapper) yang kompatibel dengan rbac_enforcer_unified.
    """

    def __init__(self):
        self._guard = get_authority_matrix_guard()

    def has_permission(self, role_name: str, permission: str) -> bool:
        """Memeriksa apakah role memiliki permission."""
        if permission == "*:*":
            return True

        if ":" not in permission:
            return False

        resource_str, action_str = permission.split(":", 1)

        try:
            resource = ResourceType(resource_str)
        except ValueError:
            # Resource tidak dikenal enum -> tidak ada role hardcoded yang
            # bisa cocok dengannya, jadi pasti False. (Sebelumnya di sini
            # fallback ke string mentah lalu dibandingkan dengan enum di
            # bawah -- itu SELALU False karena enum != str, jadi perilaku
            # efektifnya sama, tapi sekarang dibuat eksplisit.)
            logger.debug("has_permission: resource '%s' bukan ResourceType yang dikenal", resource_str)
            return False

        try:
            action = Action(action_str)
        except ValueError:
            logger.debug("has_permission: action '%s' bukan Action yang dikenal", action_str)
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
        user_id,
        resource: str,
        action: str,
        legal_entity_id=None,
    ) -> bool:
        """
        Dipanggil oleh RBACEnforcer sebagai lapisan fallback setelah cek
        permission langsung dari DB (permission_key di tabel role_permissions)
        tidak ditemukan. Meresolusi role user_id lalu mengecek STANDARD_ROLES.

        PENTING: resource di sini adalah string mentah hasil parsing path URL
        (mis. "ap", "bank-cash", "ar") di
        adapters/primary_api/common/fastapi_auth_jwt_middleware.py::_map_path_to_resource().
        Pastikan mapping path -> resource sudah konsisten dengan nilai
        ResourceType enum (lihat perbaikan pada middleware & kernel guard).
        """
        user_repo = getattr(self._guard, "_user_repo", None)
        if user_repo is None:
            logger.warning("is_allowed: tidak ada user repository terpasang, deny by default")
            return False

        role_names: list[str] = []
        try:
            if hasattr(user_repo, "get_roles"):
                role_names = await user_repo.get_roles(str(user_id))
            elif hasattr(user_repo, "get_user_roles"):
                raw_roles = await user_repo.get_user_roles(user_id)
                role_names = [
                    getattr(r, "name", None) or getattr(r, "role_name", None) or str(r)
                    for r in raw_roles
                ]
            else:
                logger.warning(
                    "is_allowed: %s tidak punya get_roles()/get_user_roles(), deny by default",
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
        for role_name in role_names:
            if self.has_permission(role_name, permission):
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
        if role_name not in STANDARD_ROLES:
            new_role = Role(name=role_name, permissions=[], description="Dynamic role")
            STANDARD_ROLES[role_name] = new_role

        if ":" not in permission:
            return

        res_str, act_str = permission.split(":", 1)
        try:
            resource = ResourceType(res_str)
        except ValueError:
            logger.warning(
                "add_permission_to_role: resource '%s' bukan ResourceType, dilewati", res_str
            )
            return
        try:
            action = Action(act_str)
        except ValueError:
            logger.warning(
                "add_permission_to_role: action '%s' bukan Action, dilewati", act_str
            )
            return

        new_perm = Permission(resource=resource, action=action)
        STANDARD_ROLES[role_name].permissions.append(new_perm)


__all__ = [
    "STANDARD_ROLES",
    "AuthorityMatrix",
    "AuthorityMatrixGuard",
    "get_authority_matrix_guard",
]
