#!/usr/bin/env python3
"""
Module: account_repository_port.py
Layer: Ports (Primary)

PORT INTERFACE (Abstract Base Class) untuk Chart of Accounts (COA).
Menggunakan AccountAggregate dari domain sebagai aggregate root.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from domain.coa.aggregate_root import AccountAggregate


class AccountRepositoryPort(ABC):
    """
    Port (interface) untuk repository Chart of Accounts.
    """

    @abstractmethod
    async def add(self, account: AccountAggregate) -> None:
        pass

    @abstractmethod
    async def get_by_id(self, account_id: UUID) -> AccountAggregate | None:
        pass

    @abstractmethod
    async def get_by_code(self, account_code: str, legal_entity_id: UUID) -> AccountAggregate | None:
        pass

    @abstractmethod
    async def update(self, account: AccountAggregate) -> None:
        pass

    @abstractmethod
    async def delete(self, account_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        pass

    @abstractmethod
    async def restore(self, account_id: UUID, user_id: UUID) -> bool:
        pass

    @abstractmethod
    async def get_children(self, parent_account_id: UUID, recursive: bool = False) -> list[AccountAggregate]:
        pass

    @abstractmethod
    async def get_root_accounts(self, legal_entity_id: UUID) -> list[AccountAggregate]:
        pass

    @abstractmethod
    async def get_full_hierarchy(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def get_descendants(self, account_id: UUID) -> list[AccountAggregate]:
        pass

    @abstractmethod
    async def get_path(self, account_id: UUID) -> list[AccountAggregate]:
        pass

    @abstractmethod
    async def find_by_type(self, account_type: str, legal_entity_id: UUID) -> list[AccountAggregate]:
        pass

    @abstractmethod
    async def find_by_name_contains(
        self, keyword: str, legal_entity_id: UUID, limit: int = 50
    ) -> list[AccountAggregate]:
        pass

    @abstractmethod
    async def find_active(self, legal_entity_id: UUID) -> list[AccountAggregate]:
        pass

    @abstractmethod
    async def get_all(
        self,
        legal_entity_id: UUID,
        include_inactive: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[AccountAggregate]:
        pass

    @abstractmethod
    async def get_balance_sheet_accounts(self, legal_entity_id: UUID) -> list[AccountAggregate]:
        pass

    @abstractmethod
    async def get_income_statement_accounts(self, legal_entity_id: UUID) -> list[AccountAggregate]:
        pass

    @abstractmethod
    async def is_code_unique(
        self, account_code: str, legal_entity_id: UUID, exclude_id: UUID | None = None
    ) -> bool:
        pass

    @abstractmethod
    async def has_children(self, account_id: UUID) -> bool:
        pass

    @abstractmethod
    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        pass

    @abstractmethod
    async def import_from_csv(self, csv_content: str, legal_entity_id: UUID, user_id: UUID) -> int:
        pass

    @abstractmethod
    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        pass

    @abstractmethod
    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        pass


__all__ = ["AccountRepositoryPort"]