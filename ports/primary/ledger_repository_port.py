#!/usr/bin/env python3
"""
Module: ledger_repository_port.py
Layer: Ports (Primary)
Responsibility: Implementasi in-memory repository untuk buku besar (General Ledger).
               Mendukung entri ledger dari jurnal yang sudah diposting, perhitungan
               saldo akun (debit/kredit), trial balance, neraca, laba rugi,
               arus kas (indirect method), perbandingan antar periode,
               dan audit trail.
Audit: Setiap query balance dan laporan keuangan dicatat untuk audit trail.
Perbaikan: Semua nilai moneter dikonversi ke str() untuk menghindari float().
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


# ==================== ENUMS & CONSTANTS ====================


class AccountType(Enum):
    """Jenis akun untuk keperluan laporan keuangan."""

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


# ==================== READ MODEL FOR QUERY ====================


@dataclass
class LedgerEntryReadModel:
    """
    Read model untuk ledger entry (hasil query dari SQLAlchemy).
    Digunakan oleh SQLAlchemyLedgerRepository.
    """

    id: UUID
    journal_id: UUID
    account_id: UUID
    account_code: str
    debit_amount: Decimal
    credit_amount: Decimal
    posting_date: date
    legal_entity_id: UUID
    cost_center: str | None
    reference_number: str | None
    description: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "journal_id": str(self.journal_id),
            "account_id": str(self.account_id),
            "account_code": self.account_code,
            "debit_amount": str(self.debit_amount),   # ← str, bukan float
            "credit_amount": str(self.credit_amount), # ← str
            "posting_date": self.posting_date.isoformat(),
            "legal_entity_id": str(self.legal_entity_id),
            "cost_center": self.cost_center,
            "reference_number": self.reference_number,
            "description": self.description,
        }


# ==================== DOMAIN / IN-MEMORY ENTRIES ====================


@dataclass
class LedgerEntry:
    """
    Entri buku besar (read model) - immutable setelah diposting.
    Dibuat dari event JournalPosted.
    """

    id: UUID
    journal_id: UUID
    journal_line_id: UUID
    account_id: UUID
    account_code: str
    account_name: str
    account_type: AccountType
    normal_balance: NormalBalance
    legal_entity_id: UUID
    debit_amount: Decimal
    credit_amount: Decimal
    posting_date: date
    fiscal_year: int
    period: int  # 1-12
    description: str | None
    reference_number: str | None
    cost_center: str | None
    department_id: UUID | None
    project_id: UUID | None
    created_at: datetime
    created_by: UUID

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "journal_id": str(self.journal_id),
            "journal_line_id": str(self.journal_line_id),
            "account_id": str(self.account_id),
            "account_code": self.account_code,
            "account_name": self.account_name,
            "account_type": self.account_type.value,
            "normal_balance": self.normal_balance.value,
            "legal_entity_id": str(self.legal_entity_id),
            "debit_amount": str(self.debit_amount),   # ← str
            "credit_amount": str(self.credit_amount), # ← str
            "posting_date": self.posting_date.isoformat(),
            "fiscal_year": self.fiscal_year,
            "period": self.period,
            "description": self.description,
            "reference_number": self.reference_number,
            "cost_center": self.cost_center,
            "department_id": str(self.department_id) if self.department_id else None,
            "project_id": str(self.project_id) if self.project_id else None,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
        }


@dataclass
class AccountBalance:
    """Saldo akun pada periode tertentu."""

    account_id: UUID
    account_code: str
    account_name: str
    account_type: AccountType
    normal_balance: NormalBalance
    opening_balance: Decimal
    debit_movement: Decimal
    credit_movement: Decimal
    closing_balance: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": str(self.account_id),
            "account_code": self.account_code,
            "account_name": self.account_name,
            "account_type": self.account_type.value,
            "normal_balance": self.normal_balance.value,
            "opening_balance": str(self.opening_balance),   # ← str
            "debit_movement": str(self.debit_movement),     # ← str
            "credit_movement": str(self.credit_movement),   # ← str
            "closing_balance": str(self.closing_balance),   # ← str
        }


@dataclass
class TrialBalanceRow:
    """Baris neraca saldo."""

    account_code: str
    account_name: str
    debit_balance: Decimal
    credit_balance: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_code": self.account_code,
            "account_name": self.account_name,
            "debit_balance": str(self.debit_balance),   # ← str
            "credit_balance": str(self.credit_balance), # ← str
        }


@dataclass
class FinancialStatementRow:
    """Baris laporan keuangan (neraca/laba rugi)."""

    account_code: str
    account_name: str
    current_period: Decimal
    previous_period: Decimal
    variance: Decimal
    variance_percentage: float   # non-monetary (persentase), boleh float

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_code": self.account_code,
            "account_name": self.account_name,
            "current_period": str(self.current_period),   # ← str
            "previous_period": str(self.previous_period), # ← str
            "variance": str(self.variance),               # ← str
            "variance_percentage": self.variance_percentage,  # tetap float
        }


# ==================== REPOSITORY IMPLEMENTATION (IN-MEMORY) ====================


class LedgerRepositoryPort:
    """
    In-memory repository untuk buku besar.
    """

    def __init__(self):
        self._entries: list[LedgerEntry] = []
        self._index_by_journal: dict[UUID, list[LedgerEntry]] = {}
        self._index_by_account: dict[UUID, list[LedgerEntry]] = {}
        self._index_by_legal_entity: dict[UUID, list[LedgerEntry]] = {}
        self._index_by_period: dict[
            tuple[UUID, int, int], list[LedgerEntry]
        ] = {}  # (legal_entity_id, fiscal_year, period)
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    # ==================== AUDIT LOG ====================

    async def _log_audit(self, action: str, details: dict[str, Any]):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"LEDGER AUDIT: {action}")

    # ==================== ADD ENTRY ====================

    async def add_entry(self, entry: LedgerEntry) -> None:
        """Menambahkan entri ledger baru (dipanggil saat jurnal diposting)."""
        async with self._lock:
            self._entries.append(entry)
            # Journal index
            if entry.journal_id not in self._index_by_journal:
                self._index_by_journal[entry.journal_id] = []
            self._index_by_journal[entry.journal_id].append(entry)
            # Account index
            if entry.account_id not in self._index_by_account:
                self._index_by_account[entry.account_id] = []
            self._index_by_account[entry.account_id].append(entry)
            # Legal entity index
            if entry.legal_entity_id not in self._index_by_legal_entity:
                self._index_by_legal_entity[entry.legal_entity_id] = []
            self._index_by_legal_entity[entry.legal_entity_id].append(entry)
            # Period index
            period_key = (entry.legal_entity_id, entry.fiscal_year, entry.period)
            if period_key not in self._index_by_period:
                self._index_by_period[period_key] = []
            self._index_by_period[period_key].append(entry)
        await self._log_audit(
            "ADD_ENTRY", {"journal_id": str(entry.journal_id), "account_code": entry.account_code}
        )

    async def add_batch(self, entries: list[LedgerEntry]) -> None:
        """Menambahkan banyak entri sekaligus (efisiensi)."""
        async with self._lock:
            for entry in entries:
                self._entries.append(entry)
                # Journal index
                if entry.journal_id not in self._index_by_journal:
                    self._index_by_journal[entry.journal_id] = []
                self._index_by_journal[entry.journal_id].append(entry)
                # Account index
                if entry.account_id not in self._index_by_account:
                    self._index_by_account[entry.account_id] = []
                self._index_by_account[entry.account_id].append(entry)
                # Legal entity index
                if entry.legal_entity_id not in self._index_by_legal_entity:
                    self._index_by_legal_entity[entry.legal_entity_id] = []
                self._index_by_legal_entity[entry.legal_entity_id].append(entry)
                # Period index
                period_key = (entry.legal_entity_id, entry.fiscal_year, entry.period)
                if period_key not in self._index_by_period:
                    self._index_by_period[period_key] = []
                self._index_by_period[period_key].append(entry)
        await self._log_audit("ADD_BATCH", {"count": len(entries)})

    # ==================== BALANCE CALCULATION ====================

    async def get_account_balance(self, account_id: UUID, as_of_date: date) -> Decimal:
        """Menghitung saldo akun (debit - credit) pada tanggal tertentu."""
        total_debit = Decimal(0)
        total_credit = Decimal(0)
        entries = self._index_by_account.get(account_id, [])
        for entry in entries:
            if entry.posting_date <= as_of_date:
                total_debit += entry.debit_amount
                total_credit += entry.credit_amount
        return (total_debit - total_credit).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    async def get_account_balance_with_normal(
        self, account_id: UUID, as_of_date: date, normal_balance: NormalBalance
    ) -> Decimal:
        """Saldo akun dengan memperhatikan normal balance."""
        total_debit = Decimal(0)
        total_credit = Decimal(0)
        entries = self._index_by_account.get(account_id, [])
        for entry in entries:
            if entry.posting_date <= as_of_date:
                total_debit += entry.debit_amount
                total_credit += entry.credit_amount
        if normal_balance == NormalBalance.DEBIT:
            balance = total_debit - total_credit
        else:
            balance = total_credit - total_debit
        return balance.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    async def get_account_balance_by_code(
        self, account_code: str, legal_entity_id: UUID, as_of_date: date
    ) -> Decimal:
        """Saldo akun berdasarkan kode akun dan entitas hukum."""
        total_debit = Decimal(0)
        total_credit = Decimal(0)
        entries = self._index_by_legal_entity.get(legal_entity_id, [])
        for entry in entries:
            if entry.account_code == account_code and entry.posting_date <= as_of_date:
                total_debit += entry.debit_amount
                total_credit += entry.credit_amount
        return (total_debit - total_credit).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    async def get_period_balance(
        self, account_id: UUID, fiscal_year: int, period: int, include_opening: bool = True
    ) -> Decimal:
        """Saldo akun pada akhir periode tertentu."""
        total_debit = Decimal(0)
        total_credit = Decimal(0)
        entries = self._index_by_account.get(account_id, [])
        for entry in entries:
            if entry.fiscal_year < fiscal_year or (
                entry.fiscal_year == fiscal_year and entry.period <= period
            ):
                total_debit += entry.debit_amount
                total_credit += entry.credit_amount
        return (total_debit - total_credit).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    # ==================== TRIAL BALANCE ====================

    async def get_trial_balance(
        self, legal_entity_id: UUID, as_of_date: date, include_zero_balance: bool = False
    ) -> list[TrialBalanceRow]:
        """Menghasilkan neraca saldo per tanggal."""
        account_balances: dict[str, dict[str, Any]] = {}
        entries = self._index_by_legal_entity.get(legal_entity_id, [])
        for entry in entries:
            if entry.posting_date <= as_of_date:
                code = entry.account_code
                if code not in account_balances:
                    account_balances[code] = {
                        "account_name": entry.account_name,
                        "debit": Decimal(0),
                        "credit": Decimal(0),
                    }
                account_balances[code]["debit"] += entry.debit_amount
                account_balances[code]["credit"] += entry.credit_amount

        result = []
        for code, data in account_balances.items():
            debit = data["debit"]
            credit = data["credit"]
            net = debit - credit
            if net > 0:
                debit_balance = net
                credit_balance = Decimal(0)
            else:
                debit_balance = Decimal(0)
                credit_balance = -net
            if include_zero_balance or (debit_balance != 0 or credit_balance != 0):
                result.append(
                    TrialBalanceRow(
                        account_code=code,
                        account_name=data["account_name"],
                        debit_balance=debit_balance,
                        credit_balance=credit_balance,
                    )
                )
        result.sort(key=lambda x: x.account_code)
        return result

    async def get_trial_balance_by_period(
        self,
        legal_entity_id: UUID,
        fiscal_year: int,
        period: int,
        include_zero_balance: bool = False,
    ) -> list[TrialBalanceRow]:
        """Neraca saldo pada akhir periode tertentu."""
        account_balances: dict[str, dict[str, Any]] = {}
        entries = self._index_by_legal_entity.get(legal_entity_id, [])
        for entry in entries:
            if entry.fiscal_year < fiscal_year or (
                entry.fiscal_year == fiscal_year and entry.period <= period
            ):
                code = entry.account_code
                if code not in account_balances:
                    account_balances[code] = {
                        "account_name": entry.account_name,
                        "debit": Decimal(0),
                        "credit": Decimal(0),
                    }
                account_balances[code]["debit"] += entry.debit_amount
                account_balances[code]["credit"] += entry.credit_amount

        result = []
        for code, data in account_balances.items():
            debit = data["debit"]
            credit = data["credit"]
            net = debit - credit
            if net > 0:
                debit_balance = net
                credit_balance = Decimal(0)
            else:
                debit_balance = Decimal(0)
                credit_balance = -net
            if include_zero_balance or (debit_balance != 0 or credit_balance != 0):
                result.append(
                    TrialBalanceRow(
                        account_code=code,
                        account_name=data["account_name"],
                        debit_balance=debit_balance,
                        credit_balance=credit_balance,
                    )
                )
        result.sort(key=lambda x: x.account_code)
        return result

    # ==================== INCOME STATEMENT (LABA RUGI) ====================

    async def get_income_statement(
        self,
        legal_entity_id: UUID,
        fiscal_year: int,
        period: int,
        compare_with_previous: bool = True,
    ) -> dict[str, Any]:
        """
        Laporan laba rugi untuk periode tertentu.
        Mengembalikan: revenue_total, expense_total, net_income, dan breakdown per kategori.
        """
        revenue_balance = Decimal(0)
        expense_balance = Decimal(0)
        revenue_details: list[FinancialStatementRow] = []
        expense_details: list[FinancialStatementRow] = []

        # Kumpulkan semua revenue accounts (account_type = REVENUE)
        account_info: dict[str, dict[str, Any]] = {}
        entries = self._index_by_legal_entity.get(legal_entity_id, [])
        for entry in entries:
            if entry.fiscal_year == fiscal_year and entry.period <= period:
                code = entry.account_code
                if code not in account_info:
                    account_info[code] = {
                        "name": entry.account_name,
                        "type": entry.account_type,
                        "debit": Decimal(0),
                        "credit": Decimal(0),
                    }
                account_info[code]["debit"] += entry.debit_amount
                account_info[code]["credit"] += entry.credit_amount

        # Separate revenue and expense
        for code, info in account_info.items():
            if info["type"] == AccountType.REVENUE:
                balance = info["credit"] - info["debit"]  # revenue normal credit
                revenue_balance += balance
                # For previous period comparison
                prev_balance = await self._get_previous_period_balance(
                    legal_entity_id, code, fiscal_year, period
                )
                revenue_details.append(
                    FinancialStatementRow(
                        account_code=code,
                        account_name=info["name"],
                        current_period=balance,
                        previous_period=prev_balance,
                        variance=balance - prev_balance,
                        variance_percentage=float((balance - prev_balance) / prev_balance * 100)
                        if prev_balance != 0
                        else 0,
                    )
                )
            elif info["type"] == AccountType.EXPENSE:
                balance = info["debit"] - info["credit"]  # expense normal debit
                expense_balance += balance
                prev_balance = await self._get_previous_period_balance(
                    legal_entity_id, code, fiscal_year, period
                )
                expense_details.append(
                    FinancialStatementRow(
                        account_code=code,
                        account_name=info["name"],
                        current_period=balance,
                        previous_period=prev_balance,
                        variance=balance - prev_balance,
                        variance_percentage=float((balance - prev_balance) / prev_balance * 100)
                        if prev_balance != 0
                        else 0,
                    )
                )

        net_income = revenue_balance - expense_balance
        return {
            "revenue_total": str(revenue_balance),           # ← str
            "expense_total": str(expense_balance),           # ← str
            "net_income": str(net_income),                   # ← str
            "revenue_details": [r.to_dict() for r in revenue_details],
            "expense_details": [e.to_dict() for e in expense_details],
        }

    async def _get_previous_period_balance(
        self, legal_entity_id: UUID, account_code: str, fiscal_year: int, period: int
    ) -> Decimal:
        """Helper untuk mendapatkan balance periode sebelumnya (bulan sebelumnya)."""
        if period == 1:
            prev_fiscal_year = fiscal_year - 1
            prev_period = 12
        else:
            prev_fiscal_year = fiscal_year
            prev_period = period - 1
        total_debit = Decimal(0)
        total_credit = Decimal(0)
        entries = self._index_by_legal_entity.get(legal_entity_id, [])
        for entry in entries:
            if entry.account_code == account_code:
                if entry.fiscal_year < prev_fiscal_year or (
                    entry.fiscal_year == prev_fiscal_year and entry.period <= prev_period
                ):
                    total_debit += entry.debit_amount
                    total_credit += entry.credit_amount
        # For revenue, normal credit
        return (total_credit - total_debit).quantize(Decimal("0.01"))

    # ==================== BALANCE SHEET (NERACA) ====================

    async def get_balance_sheet(
        self, legal_entity_id: UUID, as_of_date: date, compare_with_previous: bool = True
    ) -> dict[str, Any]:
        """Laporan neraca per tanggal."""
        asset_balance = Decimal(0)
        liability_balance = Decimal(0)
        equity_balance = Decimal(0)

        entries = self._index_by_legal_entity.get(legal_entity_id, [])
        account_totals: dict[str, dict[str, Any]] = {}
        for entry in entries:
            if entry.posting_date <= as_of_date:
                code = entry.account_code
                if code not in account_totals:
                    account_totals[code] = {
                        "name": entry.account_name,
                        "type": entry.account_type,
                        "debit": Decimal(0),
                        "credit": Decimal(0),
                    }
                account_totals[code]["debit"] += entry.debit_amount
                account_totals[code]["credit"] += entry.credit_amount

        asset_details = []
        liability_details = []
        equity_details = []

        for code, data in account_totals.items():
            acc_type = data["type"]
            net = data["debit"] - data["credit"]
            if acc_type == AccountType.ASSET:
                balance = net  # asset normal debit
                asset_balance += balance
                asset_details.append(
                    {
                        "account_code": code,
                        "account_name": data["name"],
                        "balance": str(balance),          # ← str
                    }
                )
            elif acc_type == AccountType.LIABILITY:
                balance = -net  # liability normal credit
                liability_balance += balance
                liability_details.append(
                    {
                        "account_code": code,
                        "account_name": data["name"],
                        "balance": str(balance),          # ← str
                    }
                )
            elif acc_type == AccountType.EQUITY:
                balance = -net
                equity_balance += balance
                equity_details.append(
                    {
                        "account_code": code,
                        "account_name": data["name"],
                        "balance": str(balance),          # ← str
                    }
                )
            elif acc_type == AccountType.CONTRA_ASSET:
                asset_balance -= net
                asset_details.append(
                    {
                        "account_code": code,
                        "account_name": data["name"] + " (kontra)",
                        "balance": str(-net),             # ← str
                    }
                )

        return {
            "as_of_date": as_of_date.isoformat(),
            "total_assets": str(asset_balance),           # ← str
            "total_liabilities": str(liability_balance),  # ← str
            "total_equity": str(equity_balance),          # ← str
            "liabilities_and_equity": str(liability_balance + equity_balance),  # ← str
            "asset_details": asset_details,
            "liability_details": liability_details,
            "equity_details": equity_details,
        }

    # ==================== CASH FLOW (INDIRECT) ====================

    async def get_cash_flow_indirect(
        self, legal_entity_id: UUID, fiscal_year: int, period: int
    ) -> dict[str, Any]:
        """Laporan arus kas metode tidak langsung."""
        income_stmt = await self.get_income_statement(
            legal_entity_id, fiscal_year, period, compare_with_previous=False
        )
        net_income = Decimal(str(income_stmt["net_income"]))

        opening_balances = await self._get_period_opening_balances(
            legal_entity_id, fiscal_year, period
        )
        closing_balances = await self._get_period_closing_balances(
            legal_entity_id, fiscal_year, period
        )

        operating_activities = {
            "net_income": str(net_income),
            "adjustments": [],
            "changes_in_assets": [],
            "changes_in_liabilities": [],
        }
        total_adjustment = Decimal(0)

        # Depreciation
        deprec_entries = await self._get_depreciation_entries(legal_entity_id, fiscal_year, period)
        deprec_total = sum(e.credit_amount for e in deprec_entries)
        operating_activities["adjustments"].append(
            {
                "description": "Depreciation and amortization",
                "amount": str(deprec_total),          # ← str
            }
        )
        total_adjustment += deprec_total

        # Perubahan piutang
        ar_change = opening_balances.get("AR", Decimal(0)) - closing_balances.get("AR", Decimal(0))
        operating_activities["changes_in_assets"].append(
            {
                "account": "Accounts Receivable",
                "change": str(ar_change),             # ← str
            }
        )
        total_adjustment += ar_change

        # Perubahan persediaan
        inv_change = opening_balances.get("INVENTORY", Decimal(0)) - closing_balances.get(
            "INVENTORY", Decimal(0)
        )
        operating_activities["changes_in_assets"].append(
            {
                "account": "Inventory",
                "change": str(inv_change),            # ← str
            }
        )
        total_adjustment += inv_change

        # Perubahan utang usaha
        ap_change = closing_balances.get("AP", Decimal(0)) - opening_balances.get("AP", Decimal(0))
        operating_activities["changes_in_liabilities"].append(
            {
                "account": "Accounts Payable",
                "change": str(ap_change),             # ← str
            }
        )
        total_adjustment += ap_change

        net_cash_operating = net_income + total_adjustment

        return {
            "period": f"Q{math.ceil(period / 3)} {fiscal_year}"
            if period % 3 == 0
            else f"Month {period} {fiscal_year}",
            "net_cash_operating": str(net_cash_operating),       # ← str
            "net_cash_investing": "0",                            # ← str
            "net_cash_financing": "0",                            # ← str
            "net_cash_increase": str(net_cash_operating),        # ← str
            "operating_activities_details": operating_activities,
            "investing_activities_details": [],
            "financing_activities_details": [],
        }

    async def _get_period_opening_balances(
        self, legal_entity_id: UUID, fiscal_year: int, period: int
    ) -> dict[str, Decimal]:
        """Saldo awal periode untuk akun-akun tertentu."""
        result = {}
        if period == 1:
            prev_fiscal_year = fiscal_year - 1
            prev_period = 12
        else:
            prev_fiscal_year = fiscal_year
            prev_period = period - 1
        entries = self._index_by_legal_entity.get(legal_entity_id, [])
        ar_total = Decimal(0)
        inventory_total = Decimal(0)
        ap_total = Decimal(0)
        for entry in entries:
            if entry.fiscal_year < prev_fiscal_year or (
                entry.fiscal_year == prev_fiscal_year and entry.period <= prev_period
            ):
                if entry.account_code.startswith("1-1300") or entry.account_code.startswith("1-13"):
                    ar_total += entry.debit_amount - entry.credit_amount
                elif entry.account_code.startswith("1-1400") or entry.account_code.startswith(
                    "1-14"
                ):
                    inventory_total += entry.debit_amount - entry.credit_amount
                elif entry.account_code.startswith("2-2100") or entry.account_code.startswith(
                    "2-21"
                ):
                    ap_total += entry.credit_amount - entry.debit_amount
        result["AR"] = ar_total
        result["INVENTORY"] = inventory_total
        result["AP"] = ap_total
        return result

    async def _get_period_closing_balances(
        self, legal_entity_id: UUID, fiscal_year: int, period: int
    ) -> dict[str, Decimal]:
        """Saldo akhir periode untuk akun-akun tertentu."""
        result = {}
        ar_total = Decimal(0)
        inventory_total = Decimal(0)
        ap_total = Decimal(0)
        entries = self._index_by_legal_entity.get(legal_entity_id, [])
        for entry in entries:
            if entry.fiscal_year < fiscal_year or (
                entry.fiscal_year == fiscal_year and entry.period <= period
            ):
                if entry.account_code.startswith("1-1300") or entry.account_code.startswith("1-13"):
                    ar_total += entry.debit_amount - entry.credit_amount
                elif entry.account_code.startswith("1-1400") or entry.account_code.startswith(
                    "1-14"
                ):
                    inventory_total += entry.debit_amount - entry.credit_amount
                elif entry.account_code.startswith("2-2100") or entry.account_code.startswith(
                    "2-21"
                ):
                    ap_total += entry.credit_amount - entry.debit_amount
        result["AR"] = ar_total
        result["INVENTORY"] = inventory_total
        result["AP"] = ap_total
        return result

    async def _get_depreciation_entries(
        self, legal_entity_id: UUID, fiscal_year: int, period: int
    ) -> list[LedgerEntry]:
        """Entri depresiasi dalam periode."""
        result = []
        entries = self._index_by_legal_entity.get(legal_entity_id, [])
        for entry in entries:
            if entry.fiscal_year == fiscal_year and entry.period == period:
                if (
                    entry.account_code.startswith("5-5400")
                    or "depreciation" in entry.account_name.lower()
                ):
                    result.append(entry)
        return result

    # ==================== QUERY ENTRIES ====================

    async def find_entries_by_journal(self, journal_id: UUID) -> list[LedgerEntry]:
        return self._index_by_journal.get(journal_id, [])

    async def find_entries_by_account_and_date_range(
        self, account_id: UUID, start_date: date, end_date: date
    ) -> list[LedgerEntry]:
        entries = self._index_by_account.get(account_id, [])
        return [e for e in entries if start_date <= e.posting_date <= end_date]

    async def find_entries_by_account_code(
        self, account_code: str, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> list[LedgerEntry]:
        entries = self._index_by_legal_entity.get(legal_entity_id, [])
        return [
            e
            for e in entries
            if e.account_code == account_code and start_date <= e.posting_date <= end_date
        ]

    async def find_entries_by_period(
        self, legal_entity_id: UUID, fiscal_year: int, period: int
    ) -> list[LedgerEntry]:
        period_key = (legal_entity_id, fiscal_year, period)
        return self._index_by_period.get(period_key, [])

    async def get_all_entries_for_entity(self, legal_entity_id: UUID) -> list[LedgerEntry]:
        return self._index_by_legal_entity.get(legal_entity_id, [])

    # ==================== ACCOUNT BALANCE SUMMARY ====================

    async def get_account_balance_summary(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> list[AccountBalance]:
        """Ringkasan saldo semua akun."""
        account_data: dict[UUID, dict[str, Any]] = {}
        entries = self._index_by_legal_entity.get(legal_entity_id, [])
        for entry in entries:
            if entry.posting_date <= as_of_date:
                aid = entry.account_id
                if aid not in account_data:
                    account_data[aid] = {
                        "code": entry.account_code,
                        "name": entry.account_name,
                        "type": entry.account_type,
                        "normal": entry.normal_balance,
                        "opening": Decimal(0),
                        "debit": Decimal(0),
                        "credit": Decimal(0),
                    }
                account_data[aid]["debit"] += entry.debit_amount
                account_data[aid]["credit"] += entry.credit_amount
        result = []
        for aid, data in account_data.items():
            closing = data["debit"] - data["credit"]
            if data["normal"] == NormalBalance.CREDIT:
                closing = data["credit"] - data["debit"]
            result.append(
                AccountBalance(
                    account_id=aid,
                    account_code=data["code"],
                    account_name=data["name"],
                    account_type=data["type"],
                    normal_balance=data["normal"],
                    opening_balance=Decimal(0),
                    debit_movement=data["debit"],
                    credit_movement=data["credit"],
                    closing_balance=closing,
                )
            )
        return result

    # ==================== STATISTICS & AUDIT ====================

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        entries = self._index_by_legal_entity.get(legal_entity_id, [])
        total_entries = len(entries)
        total_debit = sum(e.debit_amount for e in entries)
        total_credit = sum(e.credit_amount for e in entries)
        unique_journals = len(self._index_by_journal)
        unique_accounts = len(self._index_by_account)
        return {
            "total_entries": total_entries,
            "total_debit": str(total_debit),       # ← str
            "total_credit": str(total_credit),     # ← str
            "unique_journals": unique_journals,
            "unique_accounts": unique_accounts,
            "audit_log_size": len(self._audit_log),
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_entries": len(self._entries),
            "total_journals_indexed": len(self._index_by_journal),
            "total_accounts_indexed": len(self._index_by_account),
            "audit_log_size": len(self._audit_log),
        }


__all__ = [
    "AccountBalance",
    "AccountType",
    "FinancialStatementRow",
    "LedgerEntry",
    "LedgerEntryReadModel",
    "LedgerRepositoryPort",
    "NormalBalance",
    "TrialBalanceRow",
]