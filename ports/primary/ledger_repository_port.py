#!/usr/bin/env python3
"""
Module: ledger_repository_port.py
Layer: Ports (Primary)
Responsibility: Port interface untuk General Ledger (buku besar).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
from uuid import UUID


class AccountType(Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"
    CONTRA_ASSET = "contra_asset"
    CONTRA_LIABILITY = "contra_liability"
    CONTRA_EQUITY = "contra_equity"
    CONTRA_REVENUE = "contra_revenue"
    CONTRA_EXPENSE = "contra_expense"


class NormalBalance(Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class LedgerEntry:
    """Entri buku besar (read model)."""
    def __init__(
        self,
        id: UUID,
        journal_id: UUID,
        journal_line_id: UUID,
        account_id: UUID,
        account_code: str,
        account_name: str,
        account_type: AccountType,
        normal_balance: NormalBalance,
        legal_entity_id: UUID,
        debit_amount: Decimal,
        credit_amount: Decimal,
        posting_date: date,
        fiscal_year: int,
        period: int,
        description: str | None = None,
        reference_number: str | None = None,
        cost_center: str | None = None,
        department_id: UUID | None = None,
        project_id: UUID | None = None,
        created_at: Optional[datetime] = None,
        created_by: UUID | None = None,
    ):
        self.id = id
        self.journal_id = journal_id
        self.journal_line_id = journal_line_id
        self.account_id = account_id
        self.account_code = account_code
        self.account_name = account_name
        self.account_type = account_type
        self.normal_balance = normal_balance
        self.legal_entity_id = legal_entity_id
        self.debit_amount = debit_amount
        self.credit_amount = credit_amount
        self.posting_date = posting_date
        self.fiscal_year = fiscal_year
        self.period = period
        self.description = description
        self.reference_number = reference_number
        self.cost_center = cost_center
        self.department_id = department_id
        self.project_id = project_id
        self.created_at = created_at or datetime.now()
        self.created_by = created_by or UUID(int=0)


class AccountBalance:
    """Saldo akun."""
    def __init__(
        self,
        account_id: UUID,
        account_code: str,
        account_name: str,
        account_type: AccountType,
        normal_balance: NormalBalance,
        opening_balance: Decimal,
        debit_movement: Decimal,
        credit_movement: Decimal,
        closing_balance: Decimal,
    ):
        self.account_id = account_id
        self.account_code = account_code
        self.account_name = account_name
        self.account_type = account_type
        self.normal_balance = normal_balance
        self.opening_balance = opening_balance
        self.debit_movement = debit_movement
        self.credit_movement = credit_movement
        self.closing_balance = closing_balance


class TrialBalanceRow:
    """Baris neraca saldo."""
    def __init__(self, account_code: str, account_name: str, debit_balance: Decimal, credit_balance: Decimal):
        self.account_code = account_code
        self.account_name = account_name
        self.debit_balance = debit_balance
        self.credit_balance = credit_balance


class FinancialStatementRow:
    """Baris laporan keuangan."""
    def __init__(
        self,
        account_code: str,
        account_name: str,
        current_period: Decimal,
        previous_period: Decimal,
        variance: Decimal,
        variance_percentage: float,
    ):
        self.account_code = account_code
        self.account_name = account_name
        self.current_period = current_period
        self.previous_period = previous_period
        self.variance = variance
        self.variance_percentage = variance_percentage


class LedgerRepositoryPort(ABC):
    """
    Port interface untuk repository General Ledger.
    """

    # ---------- Entry Management ----------
    @abstractmethod
    async def add_entry(self, entry: LedgerEntry) -> None:
        """Tambah satu entri ledger."""
        pass

    @abstractmethod
    async def add_batch(self, entries: list[LedgerEntry]) -> None:
        """Tambah banyak entri ledger (batch)."""
        pass

    # ---------- Balance ----------
    @abstractmethod
    async def get_account_balance(self, account_id: UUID, as_of_date: date) -> Decimal:
        """Saldo akun (debit - credit) per tanggal."""
        pass

    @abstractmethod
    async def get_account_balance_by_code(
        self, account_code: str, legal_entity_id: UUID, as_of_date: date
    ) -> Decimal:
        """Saldo akun berdasarkan kode dan legal entity."""
        pass

    @abstractmethod
    async def get_balance(self, account_id: UUID, as_of_date: date) -> Decimal:
        """Alias untuk get_account_balance."""
        pass

    @abstractmethod
    async def get_period_balance(
        self, account_id: UUID, fiscal_year: int, period: int, include_opening: bool = True
    ) -> Decimal:
        """Saldo akun pada akhir periode tertentu."""
        pass

    @abstractmethod
    async def get_account_balance_with_normal(
        self, account_id: UUID, as_of_date: date, normal_balance: NormalBalance
    ) -> Decimal:
        """Saldo akun dengan memperhatikan normal balance."""
        pass

    # ---------- Trial Balance ----------
    @abstractmethod
    async def get_trial_balance(
        self, legal_entity_id: UUID, as_of_date: date, include_zero_balance: bool = False
    ) -> list[TrialBalanceRow]:
        """Neraca saldo per tanggal."""
        pass

    @abstractmethod
    async def get_trial_balance_by_period(
        self,
        legal_entity_id: UUID,
        fiscal_year: int,
        period: int,
        include_zero_balance: bool = False,
    ) -> list[TrialBalanceRow]:
        """Neraca saldo pada akhir periode."""
        pass

    # ---------- Financial Statements ----------
    @abstractmethod
    async def get_income_statement(
        self,
        legal_entity_id: UUID,
        fiscal_year: int,
        period: int,
        compare_with_previous: bool = True,
    ) -> dict[str, Any]:
        """Laporan laba rugi."""
        pass

    @abstractmethod
    async def get_balance_sheet(
        self,
        legal_entity_id: UUID,
        as_of_date: date,
        compare_with_previous: bool = True,
    ) -> dict[str, Any]:
        """Laporan neraca."""
        pass

    @abstractmethod
    async def get_cash_flow_indirect(
        self, legal_entity_id: UUID, fiscal_year: int, period: int
    ) -> dict[str, Any]:
        """Laporan arus kas metode tidak langsung."""
        pass

    # ---------- Account Balance Summary ----------
    @abstractmethod
    async def get_account_balance_summary(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> list[AccountBalance]:
        """Ringkasan saldo semua akun."""
        pass

    # ---------- Query Entries ----------
    @abstractmethod
    async def find_entries_by_journal(self, journal_id: UUID) -> list[LedgerEntry]:
        """Cari entri berdasarkan journal_id."""
        pass

    @abstractmethod
    async def find_entries_by_account(
        self, account_id: UUID, start_date: date, end_date: date
    ) -> list[LedgerEntry]:
        """Cari entri berdasarkan account_id dalam rentang tanggal."""
        pass

    @abstractmethod
    async def find_entries_by_account_and_date_range(
        self, account_id: UUID, start_date: date, end_date: date
    ) -> list[LedgerEntry]:
        """Alias untuk find_entries_by_account."""
        pass

    @abstractmethod
    async def find_entries_by_account_code(
        self, account_code: str, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> list[LedgerEntry]:
        """Cari entri berdasarkan kode akun."""
        pass

    @abstractmethod
    async def find_entries_by_period(
        self, legal_entity_id: UUID, fiscal_year: int, period: int
    ) -> list[LedgerEntry]:
        """Cari entri berdasarkan periode."""
        pass

    @abstractmethod
    async def get_all_entries_for_entity(self, legal_entity_id: UUID) -> list[LedgerEntry]:
        """Ambil semua entri untuk legal entity."""
        pass

    # ---------- Statistics & Audit ----------
    @abstractmethod
    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        """Statistik ledger."""
        pass

    @abstractmethod
    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Audit log (tanpa filter)."""
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Health check repository."""
        pass


__all__ = [
    "AccountBalance",
    "AccountType",
    "FinancialStatementRow",
    "LedgerEntry",
    "LedgerRepositoryPort",
    "NormalBalance",
    "TrialBalanceRow",
]