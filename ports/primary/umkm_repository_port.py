#!/usr/bin/env python3
"""
Module: umkm_repository_port.py
Layer: Ports / Primary
Responsibility:
    - Mendefinisikan antarmuka (port) untuk repository UMKM.
    - Menyediakan implementasi in-memory untuk testing/fallback.
"""

from __future__ import annotations

import abc
import asyncio
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

# ==================== DOMAIN ENTITIES ====================

class UMKMTransactionEntity:
    """Represents a simplified transaction for UMKM."""

    def __init__(
        self,
        id: UUID,
        legal_entity_id: UUID,
        transaction_date: date,
        description: str,
        amount: Decimal,
        transaction_type: str,  # REVENUE, EXPENSE, TRANSFER
        category: str,          # e.g., SALES, PURCHASE, RENT, SALARY, TAX
        payment_method: str,    # CASH, BANK_TRANSFER, CARD
        reference_number: str | None = None,
        attachment_ids: list[UUID] | None = None,
        created_by: UUID | None = None,
        created_at: datetime | None = None,
    ):
        self.id = id
        self.legal_entity_id = legal_entity_id
        self.transaction_date = transaction_date
        self.description = description
        self.amount = amount
        self.transaction_type = transaction_type
        self.category = category
        self.payment_method = payment_method
        self.reference_number = reference_number
        self.attachment_ids = attachment_ids or []
        self.created_by = created_by
        self.created_at = created_at or datetime.utcnow()


class UMKMRevenueSummary:
    """Monthly revenue summary for UMKM tax reporting."""

    def __init__(
        self,
        id: UUID,
        legal_entity_id: UUID,
        year: int,
        month: int,
        total_revenue: Decimal,
        total_expenses: Decimal,
        net_income: Decimal,
        pph_final_due: Decimal,  # 0.5% of revenue for UMKM
        pph_paid: Decimal,
        status: str,  # DRAFT, SUBMITTED
        submitted_at: datetime | None = None,
    ):
        self.id = id
        self.legal_entity_id = legal_entity_id
        self.year = year
        self.month = month
        self.total_revenue = total_revenue
        self.total_expenses = total_expenses
        self.net_income = net_income
        self.pph_final_due = pph_final_due
        self.pph_paid = pph_paid
        self.status = status
        self.submitted_at = submitted_at


# ==================== PORT (INTERFACE) ====================

class UMKMRepositoryPort(abc.ABC):
    """Port for UMKM data persistence."""

    @abc.abstractmethod
    async def save_transaction(self, transaction: UMKMTransactionEntity) -> None:
        """Save a UMKM transaction."""
        ...

    @abc.abstractmethod
    async def get_transaction(self, transaction_id: UUID) -> UMKMTransactionEntity | None:
        """Get transaction by ID."""
        ...

    @abc.abstractmethod
    async def list_transactions_by_period(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
        transaction_type: str | None = None,
    ) -> list[UMKMTransactionEntity]:
        """List transactions for a period."""
        ...

    @abc.abstractmethod
    async def get_monthly_revenue_summary(
        self, legal_entity_id: UUID, year: int, month: int
    ) -> UMKMRevenueSummary | None:
        """Get monthly revenue summary for tax reporting."""
        ...

    @abc.abstractmethod
    async def save_revenue_summary(self, summary: UMKMRevenueSummary) -> None:
        """Save monthly revenue summary."""
        ...

    @abc.abstractmethod
    async def submit_tax_report(
        self, legal_entity_id: UUID, year: int, month: int, submitted_by: UUID
    ) -> None:
        """Mark monthly tax report as submitted."""
        ...

    @abc.abstractmethod
    async def get_total_revenue_ytd(self, legal_entity_id: UUID, year: int) -> Decimal:
        """Get year-to-date total revenue for UMKM threshold checking."""
        ...


class UMKMRepositoryPortProtocol(Protocol):
    """Protocol for UMKM repository (for duck typing)."""
    async def save_transaction(self, transaction: UMKMTransactionEntity) -> None: ...
    async def get_transaction(self, transaction_id: UUID) -> UMKMTransactionEntity | None: ...
    async def list_transactions_by_period(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
        transaction_type: str | None = None,
    ) -> list[UMKMTransactionEntity]: ...
    async def get_monthly_revenue_summary(
        self, legal_entity_id: UUID, year: int, month: int
    ) -> UMKMRevenueSummary | None: ...
    async def save_revenue_summary(self, summary: UMKMRevenueSummary) -> None: ...
    async def submit_tax_report(
        self, legal_entity_id: UUID, year: int, month: int, submitted_by: UUID
    ) -> None: ...
    async def get_total_revenue_ytd(self, legal_entity_id: UUID, year: int) -> Decimal: ...


# ==================== IMPLEMENTASI IN-MEMORY (FALLBACK/TESTING) ====================

class InMemoryUMKMRepository(UMKMRepositoryPort):
    """
    Implementasi in-memory untuk repository UMKM.
    Kelas ini TIDAK akan didaftarkan oleh container karena mengandung kata "InMemory".
    """

    def __init__(self):
        self._transactions: list[UMKMTransactionEntity] = []
        self._summaries: dict[tuple[UUID, int, int], UMKMRevenueSummary] = {}
        self._lock = asyncio.Lock()

    async def save_transaction(self, transaction: UMKMTransactionEntity) -> None:
        async with self._lock:
            for i, t in enumerate(self._transactions):
                if t.id == transaction.id:
                    self._transactions[i] = transaction
                    return
            self._transactions.append(transaction)

    async def get_transaction(self, transaction_id: UUID) -> UMKMTransactionEntity | None:
        async with self._lock:
            for t in self._transactions:
                if t.id == transaction_id:
                    return t
            return None

    async def list_transactions_by_period(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
        transaction_type: str | None = None,
    ) -> list[UMKMTransactionEntity]:
        async with self._lock:
            result = []
            for t in self._transactions:
                if t.legal_entity_id != legal_entity_id:
                    continue
                if not (from_date <= t.transaction_date <= to_date):
                    continue
                if transaction_type and t.transaction_type != transaction_type:
                    continue
                result.append(t)
            return result

    async def get_monthly_revenue_summary(
        self, legal_entity_id: UUID, year: int, month: int
    ) -> UMKMRevenueSummary | None:
        async with self._lock:
            key = (legal_entity_id, year, month)
            return self._summaries.get(key)

    async def save_revenue_summary(self, summary: UMKMRevenueSummary) -> None:
        async with self._lock:
            key = (summary.legal_entity_id, summary.year, summary.month)
            self._summaries[key] = summary

    async def submit_tax_report(
        self, legal_entity_id: UUID, year: int, month: int, submitted_by: UUID
    ) -> None:
        async with self._lock:
            key = (legal_entity_id, year, month)
            summary = self._summaries.get(key)
            if summary:
                summary.status = "SUBMITTED"
                summary.submitted_at = datetime.utcnow()

    async def get_total_revenue_ytd(self, legal_entity_id: UUID, year: int) -> Decimal:
        async with self._lock:
            total = Decimal(0)
            for t in self._transactions:
                # Gabungkan nested if menjadi satu (SIM102)
                if (
                    t.legal_entity_id == legal_entity_id
                    and t.transaction_date.year == year
                    and t.transaction_type == "REVENUE"
                ):
                    total += t.amount
            return total


# ==================== EXPORTS ====================

__all__ = [
    "InMemoryUMKMRepository",
    "UMKMRepositoryPort",
    "UMKMRepositoryPortProtocol",
    "UMKMRevenueSummary",
    "UMKMTransactionEntity",
]
