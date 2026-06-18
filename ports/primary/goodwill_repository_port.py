#!/usr/bin/env python3
"""
Module: goodwill_repository_port.py
Layer: Ports / Primary
Responsibility: Port for goodwill repository.
"""

from __future__ import annotations

import abc
from typing import Protocol
from uuid import UUID

from domain.goodwill.aggregate_root import Goodwill


class GoodwillRepositoryPort(abc.ABC):
    @abc.abstractmethod
    async def save(self, goodwill: Goodwill) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def update(self, goodwill: Goodwill) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_id(self, goodwill_id: UUID) -> Goodwill | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_last_goodwill_number(self, legal_entity_id: UUID) -> str | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_legal_entity(self, legal_entity_id: UUID) -> list[Goodwill]:
        raise NotImplementedError

    @abc.abstractmethod
    async def record_impairment_journal(self, goodwill_id: UUID, journal_id: UUID) -> None:
        raise NotImplementedError


class GoodwillRepositoryPortProtocol(Protocol):
    async def save(self, goodwill: Goodwill) -> None: ...
    async def update(self, goodwill: Goodwill) -> None: ...
    async def get_by_id(self, goodwill_id: UUID) -> Goodwill | None: ...
    async def get_last_goodwill_number(self, legal_entity_id: UUID) -> str | None: ...
    async def list_by_legal_entity(self, legal_entity_id: UUID) -> list[Goodwill]: ...
    async def record_impairment_journal(self, goodwill_id: UUID, journal_id: UUID) -> None: ...


__all__ = [
    "GoodwillRepositoryPort",
    "GoodwillRepositoryPortProtocol",
]
