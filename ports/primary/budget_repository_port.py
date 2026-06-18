#!/usr/bin/env python3
"""
Module: budget_repository_port.py
Layer: Ports / Primary
Responsibility: Port for budget repository.
"""

from __future__ import annotations

import abc
from typing import Protocol
from uuid import UUID

from domain.budget.aggregate_root import Budget


class BudgetRepositoryPort(abc.ABC):
    @abc.abstractmethod
    async def save(self, budget: Budget) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def update(self, budget: Budget) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_id(self, budget_id: UUID) -> Budget | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_name_and_year(
        self, legal_entity_id: UUID, budget_name: str, fiscal_year: int
    ) -> Budget | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_last_budget_number(self, legal_entity_id: UUID) -> str | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_legal_entity(
        self, legal_entity_id: UUID, fiscal_year: int | None = None
    ) -> list[Budget]:
        raise NotImplementedError


class BudgetRepositoryPortProtocol(Protocol):
    async def save(self, budget: Budget) -> None: ...
    async def update(self, budget: Budget) -> None: ...
    async def get_by_id(self, budget_id: UUID) -> Budget | None: ...
    async def get_by_name_and_year(
        self, legal_entity_id: UUID, budget_name: str, fiscal_year: int
    ) -> Budget | None: ...
    async def get_last_budget_number(self, legal_entity_id: UUID) -> str | None: ...
    async def list_by_legal_entity(
        self, legal_entity_id: UUID, fiscal_year: int | None = None
    ) -> list[Budget]: ...


__all__ = [
    "BudgetRepositoryPort",
    "BudgetRepositoryPortProtocol",
]
