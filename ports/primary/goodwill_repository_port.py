#!/usr/bin/env python3
"""
Module: goodwill_repository_port.py
Layer: Ports / Primary
Responsibility: Port for goodwill repository.

FIX (audit 2026-09-15): port ini sebelumnya dideklarasikan memakai
`domain.goodwill.aggregate_root.Goodwill` - sebuah dataclass DDD terpisah
yang field-fieldnya TIDAK PERNAH cocok dengan kolom tabel `goodwill`
sesungguhnya (`infrastructure/persistence_orm/goodwill_table.py`).
Setiap implementasi port ini (get_by_id/save/update) selalu crash
TypeError saat mencoba membangun objek `Goodwill` dari row tabel, karena
nama field keduanya berbeda total (mis. `acquisition_cost` vs
`goodwill_initial`, `is_active` yang tidak ada di aggregate, dst).

Port ini disederhanakan untuk memakai `GoodwillTable` (ORM) langsung
sebagai bentuk data goodwill yang diakui - `GoodwillTable` sendiri sudah
punya method domain yang benar (`record_impairment`, `recover_impairment`,
`dispose`, `approve`) dan cocok 1:1 dengan skema database, jadi tidak ada
lagi lapisan terjemahan yang bisa drift dari kebenaran di database.
"""

from __future__ import annotations

import abc
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from infrastructure.persistence_orm.goodwill_impairment_table import GoodwillImpairmentTable
from infrastructure.persistence_orm.goodwill_table import GoodwillTable


class GoodwillRepositoryPort(abc.ABC):
    @abc.abstractmethod
    async def save_goodwill(self, goodwill: GoodwillTable) -> GoodwillTable:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_goodwill_by_id(self, goodwill_id: UUID) -> GoodwillTable | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_goodwill_by_legal_entity(self, legal_entity_id: UUID) -> list[GoodwillTable]:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_active_goodwill(self, legal_entity_id: UUID) -> list[GoodwillTable]:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_last_goodwill_code(self, legal_entity_id: UUID) -> str | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def save_impairment(self, impairment: GoodwillImpairmentTable) -> GoodwillImpairmentTable:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_impairments_by_goodwill(self, goodwill_id: UUID) -> list[GoodwillImpairmentTable]:
        raise NotImplementedError

    @abc.abstractmethod
    async def update_goodwill_carrying_amount(self, goodwill_id: UUID, new_amount: Decimal) -> None:
        raise NotImplementedError


class GoodwillRepositoryPortProtocol(Protocol):
    async def save_goodwill(self, goodwill: GoodwillTable) -> GoodwillTable: ...
    async def get_goodwill_by_id(self, goodwill_id: UUID) -> GoodwillTable | None: ...
    async def get_goodwill_by_legal_entity(self, legal_entity_id: UUID) -> list[GoodwillTable]: ...
    async def get_active_goodwill(self, legal_entity_id: UUID) -> list[GoodwillTable]: ...
    async def get_last_goodwill_code(self, legal_entity_id: UUID) -> str | None: ...
    async def save_impairment(self, impairment: GoodwillImpairmentTable) -> GoodwillImpairmentTable: ...
    async def get_impairments_by_goodwill(self, goodwill_id: UUID) -> list[GoodwillImpairmentTable]: ...
    async def update_goodwill_carrying_amount(self, goodwill_id: UUID, new_amount: Decimal) -> None: ...


__all__ = [
    "GoodwillRepositoryPort",
    "GoodwillRepositoryPortProtocol",
]
