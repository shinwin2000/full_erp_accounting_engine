#!/usr/bin/env python3
"""
Module: iam_repository_port.py
Layer: Ports (Primary)
Responsibility: Implementasi in-memory repository untuk IAM aggregate.
               Menyediakan penyimpanan sementara untuk IAM (user, role, permission)
               dengan dukungan query dan audit log.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from domain.iam.aggregate_root import IAM, IAMStatus
from domain.iam.role_entity import RoleEntity
from domain.iam.user_entity import UserEntity, UserStatus

logger = logging.getLogger(__name__)


class IAMRepositoryPort:
    """
    Repository untuk IAM aggregate.
    Implementasi in-memory dengan dukungan audit dan query.
    """

    def __init__(self):
        self._storage: IAM | None = None
        self._audit_log: list[dict] = []
        self._user_index_by_username: dict[str, UUID] = {}
        self._user_index_by_email: dict[str, UUID] = {}
        self._role_index_by_name: dict[str, UUID] = {}

    async def get(self) -> IAM | None:
        """Mendapatkan aggregate IAM. Jika belum ada, membuat default."""
        if self._storage is None:
            # Inisialisasi IAM default jika belum ada
            self._storage = IAM(
                iam_id=UUID("00000000-0000-0000-0000-000000000001"),
                status=IAMStatus.ACTIVE,
            )
            self._rebuild_indices()
            logger.info("Created default IAM aggregate")
        return self._storage

    async def save(self, iam: IAM) -> None:
        """Menyimpan aggregate IAM."""
        self._storage = iam
        self._rebuild_indices()
        self._audit_log.append(
            {
                "action": "SAVE_IAM",
                "timestamp": datetime.now(UTC).isoformat(),
                "user_count": len(iam.users),
                "role_count": len(iam.roles),
                "version": iam.version,
            }
        )
        logger.info(f"IAM saved with {len(iam.users)} users, {len(iam.roles)} roles")

    def _rebuild_indices(self) -> None:
        """Membangun ulang indeks untuk pencarian cepat."""
        if self._storage is None:
            return
        self._user_index_by_username.clear()
        self._user_index_by_email.clear()
        self._role_index_by_name.clear()
        for user_id, user in self._storage.users.items():
            self._user_index_by_username[user.username] = user_id
            if user.email:
                self._user_index_by_email[user.email] = user_id
        for role_id, role in self._storage.roles.items():
            self._role_index_by_name[role.role_name] = role_id

    # ========================================================================
    # User Queries
    # ========================================================================

    async def get_user_by_id(self, user_id: UUID) -> UserEntity | None:
        """Mendapatkan user berdasarkan ID."""
        iam = await self.get()
        return iam.users.get(user_id)

    async def get_user_by_username(self, username: str) -> UserEntity | None:
        """Mendapatkan user berdasarkan username."""
        iam = await self.get()
        user_id = self._user_index_by_username.get(username)
        if user_id:
            return iam.users.get(user_id)
        return None

    async def get_user_by_email(self, email: str) -> UserEntity | None:
        """Mendapatkan user berdasarkan email."""
        iam = await self.get()
        user_id = self._user_index_by_email.get(email)
        if user_id:
            return iam.users.get(user_id)
        return None

    async def list_users(
        self,
        legal_entity_id: UUID | None = None,
        status: UserStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserEntity]:
        """Mendaftar user dengan filter."""
        iam = await self.get()
        users = list(iam.users.values())
        if legal_entity_id:
            users = [u for u in users if u.legal_entity_id == legal_entity_id]
        if status:
            users = [u for u in users if u.status == status]
        users.sort(key=lambda u: u.created_at, reverse=True)
        return users[offset : offset + limit]

    # ========================================================================
    # Role Queries
    # ========================================================================

    async def get_role_by_id(self, role_id: UUID) -> RoleEntity | None:
        """Mendapatkan role berdasarkan ID."""
        iam = await self.get()
        return iam.roles.get(role_id)

    async def get_role_by_name(self, role_name: str) -> RoleEntity | None:
        """Mendapatkan role berdasarkan nama."""
        iam = await self.get()
        role_id = self._role_index_by_name.get(role_name)
        if role_id:
            return iam.roles.get(role_id)
        return None

    async def list_roles(self, limit: int = 100, offset: int = 0) -> list[RoleEntity]:
        """Mendaftar semua role."""
        iam = await self.get()
        roles = list(iam.roles.values())
        roles.sort(key=lambda r: r.created_at)
        return roles[offset : offset + limit]

    # ========================================================================
    # Permission Queries
    # ========================================================================

    async def get_all_permissions(self) -> set[str]:
        """Mendapatkan semua permission yang terdaftar di sistem."""
        iam = await self.get()
        perms = set()
        for role in iam.roles.values():
            for perm in role.permissions:
                perms.add(perm.name)
        return perms

    # ========================================================================
    # User & Role Mutations (delegated to IAM aggregate, but here for completeness)
    # ========================================================================

    async def add_user(self, user: UserEntity) -> None:
        """Menambahkan user ke IAM."""
        iam = await self.get()
        iam.add_user(user)
        await self.save(iam)

    async def update_user(self, user: UserEntity) -> None:
        """Memperbarui user."""
        iam = await self.get()
        iam.update_user(user)
        await self.save(iam)

    async def delete_user(self, user_id: UUID) -> None:
        """Menghapus user."""
        iam = await self.get()
        iam.delete_user(user_id)
        await self.save(iam)

    async def add_role(self, role: RoleEntity) -> None:
        """Menambahkan role ke IAM."""
        iam = await self.get()
        iam.add_role(role)
        await self.save(iam)

    async def update_role(self, role: RoleEntity) -> None:
        """Memperbarui role."""
        iam = await self.get()
        iam.update_role(role)
        await self.save(iam)

    async def delete_role(self, role_id: UUID) -> None:
        """Menghapus role."""
        iam = await self.get()
        iam.delete_role(role_id)
        await self.save(iam)

    async def assign_role_to_user(self, user_id: UUID, role_id: UUID) -> None:
        """Menetapkan role ke user."""
        iam = await self.get()
        iam.assign_role_to_user(user_id, role_id)
        await self.save(iam)

    async def revoke_role_from_user(self, user_id: UUID, role_id: UUID) -> None:
        """Mencabut role dari user."""
        iam = await self.get()
        iam.remove_role_from_user(user_id, role_id)
        await self.save(iam)

    # ========================================================================
    # Audit
    # ========================================================================

    async def get_audit_log(self, limit: int = 100) -> list[dict]:
        """Mendapatkan audit log operasi repository."""
        return self._audit_log[-limit:]


__all__ = ["IAMRepositoryPort"]
