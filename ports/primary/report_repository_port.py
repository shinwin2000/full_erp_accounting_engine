#!/usr/bin/env python3
"""
Module: report_repository_port.py
Layer: Ports (Primary)
Responsibility: Mendefinisikan interface repository untuk read models pelaporan keuangan.
               Setiap repository sesuai dengan jenis laporan (trial balance, laba rugi,
               neraca, arus kas, buku besar, aging report).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID


# === DTOs for trial balance ===
@dataclass
class TrialBalanceRowDTO:
    account_code: str
    account_name: str
    account_type: str
    opening_debit: Decimal
    opening_credit: Decimal
    movement_debit: Decimal
    movement_credit: Decimal
    closing_debit: Decimal
    closing_credit: Decimal


# === DTOs for balance sheet ===
@dataclass
class BalanceSheetLineDTO:
    """Single line in a balance sheet report."""
    account_code: str
    account_name: str
    account_type: str          # asset, liability, equity
    balance: Decimal           # saldo akun pada tanggal tertentu
    parent_group: str | None = None
    level: int = 0


@dataclass
class BalanceSheetDataDTO:
    asset_rows: list[Any]      # akan diisi dengan BalanceSheetLineDTO
    liability_rows: list[Any]
    equity_rows: list[Any]
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal


# === DTOs for income statement ===
@dataclass
class IncomeStatementLineDTO:
    """Single line in an income statement."""
    account_code: str
    account_name: str
    amount: Decimal
    is_revenue: bool = False
    is_expense: bool = False
    is_cogs: bool = False
    is_other_income: bool = False
    is_other_expense: bool = False


@dataclass
class IncomeStatementDataDTO:
    revenue_rows: list[Any]      # IncomeStatementLineDTO
    cogs_rows: list[Any]
    expense_rows: list[Any]
    other_income_rows: list[Any]
    other_expense_rows: list[Any]
    total_revenue: Decimal
    total_cogs: Decimal
    gross_profit: Decimal
    total_operating_expenses: Decimal
    operating_income: Decimal
    total_other_income: Decimal
    total_other_expense: Decimal
    income_before_tax: Decimal
    tax_expense: Decimal
    net_income: Decimal


# === DTOs for cash flow ===
@dataclass
class CashFlowLineDTO:
    """Single line in a cash flow statement."""
    category: str               # operating, investing, financing
    description: str
    amount: Decimal
    is_inflow: bool = True


@dataclass
class CashFlowDataDTO:
    operating_cash_flows: list[Any]   # CashFlowLineDTO
    investing_cash_flows: list[Any]
    financing_cash_flows: list[Any]
    net_operating_cash_flow: Decimal
    net_investing_cash_flow: Decimal
    net_financing_cash_flow: Decimal
    net_cash_flow: Decimal
    beginning_cash_balance: Decimal
    ending_cash_balance: Decimal


# === DTOs for general ledger ===
@dataclass
class GeneralLedgerEntryDTO:
    journal_date: date
    journal_number: str
    description: str
    debit: Decimal
    credit: Decimal
    running_balance: Decimal
    reference: str | None = None


@dataclass
class GeneralLedgerDataDTO:
    account_code: str
    account_name: str
    from_date: date
    to_date: date
    opening_balance: Decimal
    entries: list[GeneralLedgerEntryDTO]
    closing_balance: Decimal


# ============================================================================
# REPOSITORY INTERFACES
# ============================================================================

class TrialBalanceRepositoryPort(ABC):
    @abstractmethod
    async def get_trial_balance(
        self,
        legal_entity_id: UUID,
        as_of_date: date,
        account_type_filter: list[str] | None = None,
        cost_center_id: UUID | None = None,
        include_zero_balance: bool = False,
        currency_code: str = "IDR",
    ) -> list[TrialBalanceRowDTO]:
        pass


class BalanceSheetRepositoryPort(ABC):
    @abstractmethod
    async def get_balance_sheet(
        self, legal_entity_id: UUID, as_of_date: date, currency_code: str = "IDR"
    ) -> BalanceSheetDataDTO:
        pass


class IncomeStatementRepositoryPort(ABC):
    @abstractmethod
    async def get_income_statement(
        self,
        legal_entity_id: UUID,
        period_start: date,
        period_end: date,
        show_percent_of_revenue: bool = False,
        currency_code: str = "IDR",
    ) -> IncomeStatementDataDTO:
        pass


class CashFlowRepositoryPort(ABC):
    @abstractmethod
    async def get_cash_flow(
        self,
        legal_entity_id: UUID,
        period_start: date,
        period_end: date,
        method: str = "INDIRECT",
        currency_code: str = "IDR",
    ) -> CashFlowDataDTO:
        pass


class GeneralLedgerRepositoryPort(ABC):
    @abstractmethod
    async def get_ledger(
        self,
        legal_entity_id: UUID,
        account_code: str,
        from_date: date,
        to_date: date,
        include_journal_details: bool = True,
    ) -> GeneralLedgerDataDTO:
        pass


class AgingReportRepositoryPort(ABC):
    @abstractmethod
    async def get_ar_aging(
        self, legal_entity_id: UUID, as_of_date: date, customer_id: UUID | None = None
    ) -> dict[str, Any]:
        pass

    @abstractmethod
    async def get_ap_aging(
        self, legal_entity_id: UUID, as_of_date: date, vendor_id: UUID | None = None
    ) -> dict[str, Any]:
        pass


# ============================================================================
# HAPUS InventoryValuationRepositoryPort � sudah ada di
# inventory_valuation_repository_port.py
# ============================================================================


# ============================================================================
# GENERIC REPORT REPOSITORY PORT (for app_factory dependency)
# ============================================================================

class ReportRepositoryPort(ABC):
    """
    Generic repository port for reports.
    This is a placeholder to satisfy the import in app_factory.py.
    In a real implementation, this could be a facade that delegates to specific
    report repositories.
    """

    @abstractmethod
    async def generate_report(self, report_type: str, params: dict[str, Any]) -> Any:
        pass

    @abstractmethod
    async def get_report_data(self, report_id: UUID) -> dict[str, Any]:
        pass

    # ==================== GENERATED REPORT (metadata laporan tersimpan) ====
    # Catatan: sengaja TIDAK @abstractmethod (default NotImplementedError)
    # supaya implementasi port lain (kalau ada di masa depan) tidak wajib
    # mengimplementasikan semuanya - pola yang sama dipakai di
    # UMKMRepositoryPort untuk method jurnal.

    async def create_generated_report(self, report: Any) -> Any:
        raise NotImplementedError

    async def get_generated_report_by_id(self, report_id: UUID, legal_entity_id: UUID) -> Any:
        raise NotImplementedError

    async def list_generated_reports(
        self,
        legal_entity_id: UUID,
        report_type: str | None = None,
        status: str | None = None,
        start_date: Any = None,
        end_date: Any = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Any], int]:
        raise NotImplementedError

    async def soft_delete_generated_report(
        self, report_id: UUID, legal_entity_id: UUID, deleted_by: UUID
    ) -> Any:
        raise NotImplementedError

    async def update_generated_report(self, report_id: UUID, legal_entity_id: UUID, **fields) -> Any:
        raise NotImplementedError

    # ==================== SCHEDULED REPORT (jadwal laporan otomatis) =======

    async def create_scheduled_report(self, entry: Any) -> Any:
        raise NotImplementedError

    async def get_scheduled_report_by_id(self, schedule_id: UUID, legal_entity_id: UUID) -> Any:
        raise NotImplementedError

    async def list_scheduled_reports(
        self, legal_entity_id: UUID, is_active: bool | None = None, report_type: str | None = None
    ) -> list[Any]:
        raise NotImplementedError

    async def update_scheduled_report(self, schedule_id: UUID, legal_entity_id: UUID, **fields) -> Any:
        raise NotImplementedError

    async def delete_scheduled_report(self, schedule_id: UUID, legal_entity_id: UUID) -> Any:
        raise NotImplementedError


# ============================================================================
# ALIAS FOR COMPATIBILITY (fix ImportError for `import report_repository_port`)
# ============================================================================

# Menyediakan alias huruf kecil untuk import `from ports.primary.report_repository_port import report_repository_port`
report_repository_port = ReportRepositoryPort


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "AgingReportRepositoryPort",
    "BalanceSheetDataDTO",
    "BalanceSheetLineDTO",
    "BalanceSheetRepositoryPort",
    "CashFlowDataDTO",
    "CashFlowLineDTO",
    "CashFlowRepositoryPort",
    "GeneralLedgerDataDTO",
    "GeneralLedgerEntryDTO",
    "GeneralLedgerRepositoryPort",
    "IncomeStatementDataDTO",
    "IncomeStatementLineDTO",
    "IncomeStatementRepositoryPort",
    # "InventoryValuationRepositoryPort",  # Dihapus � sudah ada di file terpisah
    "ReportRepositoryPort",
    "TrialBalanceRepositoryPort",
    "TrialBalanceRowDTO",
    "report_repository_port",
]
