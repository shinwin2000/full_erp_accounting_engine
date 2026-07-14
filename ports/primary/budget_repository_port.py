#!/usr/bin/env python3
"""
Module: budget_repository_port.py
Layer: Ports / Primary
Responsibility:
    - Mendefinisikan antarmuka (port) untuk repository budget.
    - Mendefinisikan entitas BudgetEntity dengan tipe moneter Decimal.
    - Menyediakan Protocol untuk structural typing.

Changelog:
    - v2.0.0: Pisahkan implementasi InMemory ke adapters/; gunakan Decimal untuk moneter.
    - v1.0.0: Port awal dengan float (sekarang ditinggalkan).
"""

from __future__ import annotations

import abc
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

# ==================== DOMAIN ENTITY (PORT-LEVEL) ====================

class BudgetEntity:
    """
    Representasi entitas Budget di level port.
    Semua nilai moneter menggunakan Decimal untuk presisi akuntansi.
    """

    def __init__(
        self,
        id: UUID,
        legal_entity_id: UUID,
        budget_number: str,
        budget_name: str,
        fiscal_year: int,
        status: str,  # DRAFT, ACTIVE, CLOSED
        total_amount: Decimal,
        used_amount: Decimal = Decimal("0"),
        created_by: UUID | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        notes: str | None = None,
        items: list[dict] | None = None,
    ) -> None:
        self.id = id
        self.legal_entity_id = legal_entity_id
        self.budget_number = budget_number
        self.budget_name = budget_name
        self.fiscal_year = fiscal_year
        self.status = status
        self.total_amount = total_amount
        self.used_amount = used_amount
        self.created_by = created_by
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()
        self.notes = notes
        self.items = items or []


# ==================== PORT (INTERFACE) ====================

class BudgetRepositoryPort(abc.ABC):
    """Port untuk penyimpanan data budget."""

    @abc.abstractmethod
    async def save(self, budget: BudgetEntity) -> None:
        """Simpan budget baru."""
        raise NotImplementedError

    @abc.abstractmethod
    async def update(self, budget: BudgetEntity) -> None:
        """Perbarui budget yang sudah ada."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_id(self, budget_id: UUID) -> BudgetEntity | None:
        """Ambil budget berdasarkan ID."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_name_and_year(
        self, legal_entity_id: UUID, budget_name: str, fiscal_year: int
    ) -> BudgetEntity | None:
        """Ambil budget berdasarkan nama dan tahun fiskal."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_last_budget_number(self, legal_entity_id: UUID) -> str | None:
        """Dapatkan nomor budget terakhir yang digunakan untuk entitas legal."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_legal_entity(
        self, legal_entity_id: UUID, fiscal_year: int | None = None
    ) -> list[BudgetEntity]:
        """Daftar budget untuk entitas legal, opsional difilter tahun fiskal."""
        raise NotImplementedError


class BudgetRepositoryPortProtocol(Protocol):
    """Protokol untuk structural typing (duck typing)."""

    async def save(self, budget: BudgetEntity) -> None:
        ...

    async def update(self, budget: BudgetEntity) -> None:
        ...

    async def get_by_id(self, budget_id: UUID) -> BudgetEntity | None:
        ...

    async def get_by_name_and_year(
        self, legal_entity_id: UUID, budget_name: str, fiscal_year: int
    ) -> BudgetEntity | None:
        ...

    async def get_last_budget_number(self, legal_entity_id: UUID) -> str | None:
        ...

    async def list_by_legal_entity(
        self, legal_entity_id: UUID, fiscal_year: int | None = None
    ) -> list[BudgetEntity]:
        ...


# ==================== EKSPOR ====================

__all__ = [
    "BudgetEntity",
    "BudgetRepositoryPort",
    "BudgetRepositoryPortProtocol",
]
