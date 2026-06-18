#!/usr/bin/env python3
"""
Module: financial_statement_request.py
Layer: 8 - Application / DTO Objects
Responsibility: DTO permintaan laporan keuangan.

Fitur:
- Balance sheet, income statement, cash flow
- DateRange dengan helper methods
- Account filtering
- Comparative periods
- Multiple output formats (JSON, PDF, Excel, CSV, HTML, XBRL)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

# === 1. CONSTANTS & ENUMS ===


class FinancialStatementType(str, Enum):
    """Jenis laporan keuangan."""

    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW = "cash_flow"
    EQUITY_STATEMENT = "equity_statement"
    TRIAL_BALANCE = "trial_balance"
    GENERAL_LEDGER = "general_ledger"
    SUBSIDIARY_LEDGER = "subsidiary_ledger"


class CashFlowMethod(str, Enum):
    """Metode laporan arus kas."""

    DIRECT = "direct"
    INDIRECT = "indirect"


class ComparativeType(str, Enum):
    """Jenis perbandingan."""

    NONE = "none"
    PRIOR_PERIOD = "prior_period"
    PRIOR_YEAR = "prior_year"
    BUDGET = "budget"


# Alias for backward compatibility (used in __init__.py imports)
ComparativePeriod = ComparativeType


class OutputFormat(str, Enum):
    """Format output laporan."""

    JSON = "json"
    PDF = "pdf"
    EXCEL = "excel"
    CSV = "csv"
    HTML = "html"
    XBRL = "xbrl"


class CurrencyType(str, Enum):
    """Jenis mata uang laporan."""

    FUNCTIONAL = "functional"
    PRESENTATION = "presentation"
    BOTH = "both"


# === 2. DATE RANGE DTO ===


@dataclass(kw_only=True)
class DateRange:
    """Rentang tanggal untuk laporan keuangan."""

    start_date: datetime
    end_date: datetime
    period_name: str | None = None

    def __post_init__(self) -> None:
        if self.start_date >= self.end_date:
            raise ValueError(
                f"Start date {self.start_date} must be before end date {self.end_date}"
            )
        if self.start_date.tzinfo is None:
            object.__setattr__(self, "start_date", self.start_date.replace(tzinfo=UTC))
        if self.end_date.tzinfo is None:
            object.__setattr__(self, "end_date", self.end_date.replace(tzinfo=UTC))

    @property
    def duration_days(self) -> int:
        return (self.end_date - self.start_date).days

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "period_name": self.period_name,
            "duration_days": self.duration_days,
        }

    @classmethod
    def from_month(cls, year: int, month: int) -> DateRange:
        """Membuat DateRange untuk satu bulan."""
        start_date = datetime(year, month, 1, tzinfo=UTC)
        if month == 12:
            end_date = datetime(year + 1, 1, 1, tzinfo=UTC)
        else:
            end_date = datetime(year, month + 1, 1, tzinfo=UTC)
        return cls(start_date=start_date, end_date=end_date, period_name=f"{month:02d}/{year}")

    @classmethod
    def from_year(cls, year: int) -> DateRange:
        """Membuat DateRange untuk satu tahun."""
        start_date = datetime(year, 1, 1, tzinfo=UTC)
        end_date = datetime(year + 1, 1, 1, tzinfo=UTC)
        return cls(start_date=start_date, end_date=end_date, period_name=str(year))

    @classmethod
    def from_quarter(cls, year: int, quarter: int) -> DateRange:
        """Membuat DateRange untuk satu kuartal."""
        start_month = (quarter - 1) * 3 + 1
        start_date = datetime(year, start_month, 1, tzinfo=UTC)
        if quarter == 4:
            end_date = datetime(year + 1, 1, 1, tzinfo=UTC)
        else:
            end_date = datetime(year, start_month + 3, 1, tzinfo=UTC)
        return cls(start_date=start_date, end_date=end_date, period_name=f"Q{quarter}/{year}")


# === 3. ACCOUNT FILTER DTO ===


@dataclass(kw_only=True)
class AccountFilter:
    """Filter akun untuk laporan keuangan."""

    account_types: list[str] | None = None
    account_codes: list[str] | None = None
    account_ids: list[UUID] | None = None
    parent_account_id: UUID | None = None
    include_children: bool = True
    exclude_zero_balance: bool = False
    min_balance: Decimal | None = None
    max_balance: Decimal | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_types": self.account_types,
            "account_codes": self.account_codes,
            "account_ids": [str(aid) for aid in self.account_ids] if self.account_ids else None,
            "parent_account_id": str(self.parent_account_id) if self.parent_account_id else None,
            "include_children": self.include_children,
            "exclude_zero_balance": self.exclude_zero_balance,
            "min_balance": str(self.min_balance) if self.min_balance else None,
            "max_balance": str(self.max_balance) if self.max_balance else None,
        }


# === 4. BALANCE SHEET REQUEST DTO ===


@dataclass(kw_only=True)
class BalanceSheetRequest:
    """DTO untuk request laporan neraca."""

    legal_entity_id: UUID
    as_of_date: datetime
    comparative: ComparativeType = ComparativeType.NONE
    comparative_period: DateRange | None = None
    account_filter: AccountFilter | None = None
    include_previous_year: bool = False
    currency_type: CurrencyType = CurrencyType.FUNCTIONAL
    presentation_currency: str = "IDR"
    output_format: OutputFormat = OutputFormat.JSON
    entity_name: str | None = None

    def __post_init__(self) -> None:
        if self.as_of_date.tzinfo is None:
            object.__setattr__(self, "as_of_date", self.as_of_date.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "as_of_date": self.as_of_date.isoformat(),
            "comparative": self.comparative.value,
            "comparative_period": self.comparative_period.to_dict()
            if self.comparative_period
            else None,
            "account_filter": self.account_filter.to_dict() if self.account_filter else None,
            "include_previous_year": self.include_previous_year,
            "currency_type": self.currency_type.value,
            "presentation_currency": self.presentation_currency,
            "output_format": self.output_format.value,
            "entity_name": self.entity_name,
        }


# === 5. INCOME STATEMENT REQUEST DTO ===


@dataclass(kw_only=True)
class IncomeStatementRequest:
    """DTO untuk request laporan laba rugi."""

    legal_entity_id: UUID
    period: DateRange
    comparative: ComparativeType = ComparativeType.PRIOR_PERIOD
    account_filter: AccountFilter | None = None
    show_operating_expenses_detail: bool = True
    show_other_income_expense: bool = True
    currency_type: CurrencyType = CurrencyType.FUNCTIONAL
    presentation_currency: str = "IDR"
    output_format: OutputFormat = OutputFormat.JSON
    entity_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "period": self.period.to_dict(),
            "comparative": self.comparative.value,
            "account_filter": self.account_filter.to_dict() if self.account_filter else None,
            "show_operating_expenses_detail": self.show_operating_expenses_detail,
            "show_other_income_expense": self.show_other_income_expense,
            "currency_type": self.currency_type.value,
            "presentation_currency": self.presentation_currency,
            "output_format": self.output_format.value,
            "entity_name": self.entity_name,
        }


# === 6. CASH FLOW STATEMENT REQUEST DTO ===


@dataclass(kw_only=True)
class CashFlowStatementRequest:
    """DTO untuk request laporan arus kas."""

    legal_entity_id: UUID
    period: DateRange
    method: CashFlowMethod = CashFlowMethod.INDIRECT
    comparative: ComparativeType = ComparativeType.PRIOR_PERIOD
    include_non_cash_transactions: bool = False
    currency_type: CurrencyType = CurrencyType.FUNCTIONAL
    presentation_currency: str = "IDR"
    output_format: OutputFormat = OutputFormat.JSON
    entity_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "period": self.period.to_dict(),
            "method": self.method.value,
            "comparative": self.comparative.value,
            "include_non_cash_transactions": self.include_non_cash_transactions,
            "currency_type": self.currency_type.value,
            "presentation_currency": self.presentation_currency,
            "output_format": self.output_format.value,
            "entity_name": self.entity_name,
        }


# === 7. EQUITY STATEMENT REQUEST DTO ===


@dataclass(kw_only=True)
class EquityStatementRequest:
    """DTO untuk request laporan perubahan ekuitas."""

    legal_entity_id: UUID
    period: DateRange
    comparative: ComparativeType = ComparativeType.PRIOR_PERIOD
    include_capital_changes: bool = True
    include_dividends: bool = True
    include_other_comprehensive_income: bool = True
    currency_type: CurrencyType = CurrencyType.FUNCTIONAL
    presentation_currency: str = "IDR"
    output_format: OutputFormat = OutputFormat.JSON
    entity_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "period": self.period.to_dict(),
            "comparative": self.comparative.value,
            "include_capital_changes": self.include_capital_changes,
            "include_dividends": self.include_dividends,
            "include_other_comprehensive_income": self.include_other_comprehensive_income,
            "currency_type": self.currency_type.value,
            "presentation_currency": self.presentation_currency,
            "output_format": self.output_format.value,
            "entity_name": self.entity_name,
        }


# === 8. TRIAL BALANCE REQUEST DTO ===


@dataclass(kw_only=True)
class TrialBalanceRequest:
    """DTO untuk request neraca saldo."""

    legal_entity_id: UUID
    as_of_date: datetime
    account_filter: AccountFilter | None = None
    include_period_activity: bool = True
    currency_type: CurrencyType = CurrencyType.FUNCTIONAL
    presentation_currency: str = "IDR"
    output_format: OutputFormat = OutputFormat.JSON
    entity_name: str | None = None

    def __post_init__(self) -> None:
        if self.as_of_date.tzinfo is None:
            object.__setattr__(self, "as_of_date", self.as_of_date.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "as_of_date": self.as_of_date.isoformat(),
            "account_filter": self.account_filter.to_dict() if self.account_filter else None,
            "include_period_activity": self.include_period_activity,
            "currency_type": self.currency_type.value,
            "presentation_currency": self.presentation_currency,
            "output_format": self.output_format.value,
            "entity_name": self.entity_name,
        }


# === 9. GENERAL LEDGER REQUEST DTO ===


@dataclass(kw_only=True)
class GeneralLedgerRequest:
    """DTO untuk request buku besar."""

    legal_entity_id: UUID
    period: DateRange
    account_filter: AccountFilter | None = None
    show_beginning_balance: bool = True
    show_ending_balance: bool = True
    show_running_balance: bool = True
    currency_type: CurrencyType = CurrencyType.FUNCTIONAL
    presentation_currency: str = "IDR"
    output_format: OutputFormat = OutputFormat.JSON
    entity_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "period": self.period.to_dict(),
            "account_filter": self.account_filter.to_dict() if self.account_filter else None,
            "show_beginning_balance": self.show_beginning_balance,
            "show_ending_balance": self.show_ending_balance,
            "show_running_balance": self.show_running_balance,
            "currency_type": self.currency_type.value,
            "presentation_currency": self.presentation_currency,
            "output_format": self.output_format.value,
            "entity_name": self.entity_name,
        }


# === 10. SUBSIDIARY LEDGER REQUEST DTO ===


@dataclass(kw_only=True)
class SubsidiaryLedgerRequest:
    """DTO untuk request buku pembantu."""

    legal_entity_id: UUID
    period: DateRange
    ledger_type: str  # "AR", "AP", "FIXED_ASSET", "INVENTORY"
    entity_id: UUID | None = None
    entity_code: str | None = None
    show_beginning_balance: bool = True
    show_ending_balance: bool = True
    output_format: OutputFormat = OutputFormat.JSON

    def __post_init__(self) -> None:
        valid_ledger_types = ["AR", "AP", "FIXED_ASSET", "INVENTORY"]
        if self.ledger_type not in valid_ledger_types:
            raise ValueError(f"ledger_type must be one of {valid_ledger_types}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "period": self.period.to_dict(),
            "ledger_type": self.ledger_type,
            "entity_id": str(self.entity_id) if self.entity_id else None,
            "entity_code": self.entity_code,
            "show_beginning_balance": self.show_beginning_balance,
            "show_ending_balance": self.show_ending_balance,
            "output_format": self.output_format.value,
        }


# === 11. RESPONSE DTOS ===


@dataclass(kw_only=True)
class BalanceSheetDTO:
    """DTO untuk neraca (response)."""

    legal_entity_id: UUID
    as_of_date: date
    assets_current: Decimal
    assets_fixed: Decimal
    assets_intangible: Decimal
    total_assets: Decimal
    liabilities_current: Decimal
    liabilities_long_term: Decimal
    total_liabilities: Decimal
    equity: Decimal
    total_liabilities_equity: Decimal
    is_balanced: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "as_of_date": self.as_of_date.isoformat(),
            "assets_current": str(self.assets_current),
            "assets_fixed": str(self.assets_fixed),
            "assets_intangible": str(self.assets_intangible),
            "total_assets": str(self.total_assets),
            "liabilities_current": str(self.liabilities_current),
            "liabilities_long_term": str(self.liabilities_long_term),
            "total_liabilities": str(self.total_liabilities),
            "equity": str(self.equity),
            "total_liabilities_equity": str(self.total_liabilities_equity),
            "is_balanced": self.is_balanced,
        }


@dataclass(kw_only=True)
class IncomeStatementDTO:
    """DTO untuk laporan laba rugi (response)."""

    legal_entity_id: UUID
    period_start: date
    period_end: date
    revenue: Decimal
    cost_of_goods_sold: Decimal
    gross_profit: Decimal
    operating_expenses: Decimal
    operating_income: Decimal
    other_income: Decimal
    other_expenses: Decimal
    income_before_tax: Decimal
    tax_expense: Decimal
    net_income: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "revenue": str(self.revenue),
            "cost_of_goods_sold": str(self.cost_of_goods_sold),
            "gross_profit": str(self.gross_profit),
            "operating_expenses": str(self.operating_expenses),
            "operating_income": str(self.operating_income),
            "other_income": str(self.other_income),
            "other_expenses": str(self.other_expenses),
            "income_before_tax": str(self.income_before_tax),
            "tax_expense": str(self.tax_expense),
            "net_income": str(self.net_income),
        }


@dataclass(kw_only=True)
class CashFlowDTO:
    """DTO untuk laporan arus kas (response)."""

    legal_entity_id: UUID
    period_start: date
    period_end: date
    operating_activities: Decimal
    investing_activities: Decimal
    financing_activities: Decimal
    net_cash_flow: Decimal
    beginning_cash: Decimal
    ending_cash: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "operating_activities": str(self.operating_activities),
            "investing_activities": str(self.investing_activities),
            "financing_activities": str(self.financing_activities),
            "net_cash_flow": str(self.net_cash_flow),
            "beginning_cash": str(self.beginning_cash),
            "ending_cash": str(self.ending_cash),
        }


@dataclass(kw_only=True)
class TrialBalanceDTO:
    """DTO untuk neraca saldo (response)."""

    legal_entity_id: UUID
    period_end_date: date
    rows: list[dict[str, Any]]
    total_debit_opening: Decimal
    total_credit_opening: Decimal
    total_debit_movement: Decimal
    total_credit_movement: Decimal
    total_debit_closing: Decimal
    total_credit_closing: Decimal
    is_balanced: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "period_end_date": self.period_end_date.isoformat(),
            "rows": self.rows,
            "total_debit_opening": str(self.total_debit_opening),
            "total_credit_opening": str(self.total_credit_opening),
            "total_debit_movement": str(self.total_debit_movement),
            "total_credit_movement": str(self.total_credit_movement),
            "total_debit_closing": str(self.total_debit_closing),
            "total_credit_closing": str(self.total_credit_closing),
            "is_balanced": self.is_balanced,
        }


@dataclass(kw_only=True)
class FinancialStatementResult:
    """Hasil laporan keuangan."""

    statement_type: FinancialStatementType
    legal_entity_id: UUID
    legal_entity_name: str
    period: DateRange
    generated_at: datetime
    data: dict[str, Any]
    total_assets: Decimal | None = None
    total_liabilities: Decimal | None = None
    total_equity: Decimal | None = None
    total_revenue: Decimal | None = None
    total_expenses: Decimal | None = None
    net_income: Decimal | None = None
    output_format: OutputFormat = OutputFormat.JSON
    raw_content: str | bytes | None = None

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None:
            object.__setattr__(self, "generated_at", self.generated_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement_type": self.statement_type.value,
            "legal_entity_id": str(self.legal_entity_id),
            "legal_entity_name": self.legal_entity_name,
            "period": self.period.to_dict(),
            "generated_at": self.generated_at.isoformat(),
            "data": self.data,
            "total_assets": str(self.total_assets) if self.total_assets else None,
            "total_liabilities": str(self.total_liabilities) if self.total_liabilities else None,
            "total_equity": str(self.total_equity) if self.total_equity else None,
            "total_revenue": str(self.total_revenue) if self.total_revenue else None,
            "total_expenses": str(self.total_expenses) if self.total_expenses else None,
            "net_income": str(self.net_income) if self.net_income else None,
            "output_format": self.output_format.value,
        }

    def get_balance_sheet_equation(self) -> bool:
        if (
            self.total_assets is not None
            and self.total_liabilities is not None
            and self.total_equity is not None
        ):
            return abs(self.total_assets - (self.total_liabilities + self.total_equity)) < Decimal(
                "0.01"
            )
        return True


@dataclass(kw_only=True)
class FinancialStatementRequestDTO:
    """DTO generik untuk request laporan keuangan."""

    legal_entity_id: UUID
    statement_type: str
    period_start: date
    period_end: date
    currency_code: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "statement_type": self.statement_type,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "currency_code": self.currency_code,
        }


# === 12. FACTORY ===


class FinancialStatementRequestFactory:
    """Factory untuk membuat Financial Statement Request DTOs."""

    @staticmethod
    def create_balance_sheet_request(
        legal_entity_id: UUID,
        as_of_date: datetime,
        entity_name: str | None = None,
    ) -> BalanceSheetRequest:
        return BalanceSheetRequest(
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
            entity_name=entity_name,
        )

    @staticmethod
    def create_income_statement_request(
        legal_entity_id: UUID,
        year: int,
        month: int,
        entity_name: str | None = None,
    ) -> IncomeStatementRequest:
        period = DateRange.from_month(year, month)
        return IncomeStatementRequest(
            legal_entity_id=legal_entity_id,
            period=period,
            entity_name=entity_name,
        )

    @staticmethod
    def create_yearly_income_statement(
        legal_entity_id: UUID,
        year: int,
        entity_name: str | None = None,
    ) -> IncomeStatementRequest:
        period = DateRange.from_year(year)
        return IncomeStatementRequest(
            legal_entity_id=legal_entity_id,
            period=period,
            comparative=ComparativeType.PRIOR_YEAR,
            entity_name=entity_name,
        )

    @staticmethod
    def create_cash_flow_request(
        legal_entity_id: UUID,
        year: int,
        month: int,
        method: CashFlowMethod = CashFlowMethod.INDIRECT,
        entity_name: str | None = None,
    ) -> CashFlowStatementRequest:
        period = DateRange.from_month(year, month)
        return CashFlowStatementRequest(
            legal_entity_id=legal_entity_id,
            period=period,
            method=method,
            entity_name=entity_name,
        )

    @staticmethod
    def create_trial_balance_request(
        legal_entity_id: UUID,
        as_of_date: datetime,
        entity_name: str | None = None,
    ) -> TrialBalanceRequest:
        return TrialBalanceRequest(
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
            entity_name=entity_name,
        )

    @staticmethod
    def create_general_ledger_request(
        legal_entity_id: UUID,
        year: int,
        month: int,
        account_filter: AccountFilter | None = None,
        entity_name: str | None = None,
    ) -> GeneralLedgerRequest:
        period = DateRange.from_month(year, month)
        return GeneralLedgerRequest(
            legal_entity_id=legal_entity_id,
            period=period,
            account_filter=account_filter,
            entity_name=entity_name,
        )


# === 13. EXPORTS ===

__all__ = [
    # Enums
    "FinancialStatementType",
    "CashFlowMethod",
    "ComparativeType",
    "ComparativePeriod",
    "OutputFormat",
    "CurrencyType",
    # DTOs
    "DateRange",
    "AccountFilter",
    "BalanceSheetRequest",
    "IncomeStatementRequest",
    "CashFlowStatementRequest",
    "EquityStatementRequest",
    "TrialBalanceRequest",
    "GeneralLedgerRequest",
    "SubsidiaryLedgerRequest",
    "FinancialStatementResult",
    "FinancialStatementRequestDTO",
    # Response DTOs
    "BalanceSheetDTO",
    "IncomeStatementDTO",
    "CashFlowDTO",
    "TrialBalanceDTO",
    # Factory
    "FinancialStatementRequestFactory",
]
