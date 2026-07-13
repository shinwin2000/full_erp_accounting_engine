#!/usr/bin/env python3
"""
Module: iam_repository_port.py
Layer: Ports (Primary)
Responsibility: Port interface untuk IAM aggregate repository.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

# Import domain entities (sesuai dengan yang digunakan di implementasi)
from domain.iam.aggregate_root import IAM, IAMStatus
from domain.iam.role_entity import RoleEntity
from domain.iam.user_entity import UserEntity, UserStatus


class IAMRepositoryPort(ABC):
    """Port interface untuk IAM aggregate repository."""

    @abstractmethod
    async def get(self) -> IAM | None:
        """Mendapatkan aggregate IAM."""
        pass

    @abstractmethod
    async def save(self, iam: IAM) -> None:
        """Menyimpan aggregate IAM."""
        pass

    # ---------- User ----------
    @abstractmethod
    async def get_user_by_id(self, user_id: UUID) -> UserEntity | None:
        pass

    @abstractmethod
    async def get_user_by_username(self, username: str) -> UserEntity | None:
        pass

    @abstractmethod
    async def get_user_by_email(self, email: str) -> UserEntity | None:
        pass

    @abstractmethod
    async def list_users(
        self,
        legal_entity_id: UUID | None = None,
        status: UserStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserEntity]:
        pass

    @abstractmethod
    async def add_user(self, user: UserEntity) -> None:
        pass

    @abstractmethod
    async def update_user(self, user: UserEntity) -> None:
        pass

    @abstractmethod
    async def delete_user(self, user_id: UUID) -> None:
        pass

    # ---------- Role ----------
    @abstractmethod
    async def get_role_by_id(self, role_id: UUID) -> RoleEntity | None:
        pass

    @abstractmethod
    async def get_role_by_name(self, role_name: str) -> RoleEntity | None:
        pass

    @abstractmethod
    async def list_roles(self, limit: int = 100, offset: int = 0) -> list[RoleEntity]:
        pass

    @abstractmethod
    async def add_role(self, role: RoleEntity) -> None:
        pass

    @abstractmethod
    async def update_role(self, role: RoleEntity) -> None:
        pass

    @abstractmethod
    async def delete_role(self, role_id: UUID) -> None:
        pass

    # ---------- Role Assignment ----------
    @abstractmethod
    async def assign_role_to_user(self, user_id: UUID, role_id: UUID) -> None:
        pass

    @abstractmethod
    async def revoke_role_from_user(self, user_id: UUID, role_id: UUID) -> None:
        pass

    # ---------- Permissions ----------
    @abstractmethod
    async def get_all_permissions(self) -> set[str]:
        pass

    # ---------- Audit ----------
    @abstractmethod
    async def get_audit_log(self, limit: int = 100) -> list[dict]:
        pass


__all__ = ["IAM", "IAMRepositoryPort", "IAMStatus", "RoleEntity", "UserEntity", "UserStatus"]
