#!/usr/bin/env python3
"""
Module: ojk_format_builder.py
Layer: Reports
Responsibility: Membangun laporan keuangan dalam format yang sesuai dengan
               peraturan Otoritas Jasa Keuangan (OJK) untuk perusahaan publik
               dan lembaga keuangan. Format ini mencakup laporan posisi keuangan
               (neraca), laporan laba rugi komprehensif, laporan perubahan ekuitas,
               laporan arus kas, dan catatan atas laporan keuangan.
               Data diambil dari projection yang sudah ada.
Dependencies:
- asyncio, logging, datetime, decimal
- sqlalchemy.ext.asyncio
- projections.ledger.balance_sheet_snapshot
- projections.ledger.income_statement_period
- projections.ledger.cash_flow_indirect
- projections.ledger.equity_statement
- infrastructure.persistence_orm.fiscal_period_table
- infrastructure.telemetry.structured_json_logging
- config.loader_yaml -> DIINJEKSI DARI LUAR (tidak diimpor langsung)
Audit: Laporan OJK dihasilkan untuk kepatuhan regulasi.
       Setiap laporan yang dihasilkan dicatat.

Perbaikan presisi:
    - Semua nilai moneter dikonversi ke string (bukan float) untuk serialisasi.
    - Menghilangkan float() pada nilai moneter untuk memenuhi aturan MNY-003.
"""

from __future__ import annotations

import asyncio
import csv
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiofiles  # type: ignore[import-untyped]
from sqlalchemy import select

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.fiscal_period_table import FiscalPeriodTable
from infrastructure.telemetry.structured_json_logging import get_logger
from projections.ledger.balance_sheet_snapshot import (
    BalanceSheetSnapshot,
    get_balance_sheet_snapshot,
)
from projections.ledger.cash_flow_indirect import CashFlowIndirect, get_cash_flow_projection
from projections.ledger.equity_statement import EquityStatement, get_equity_statement
from projections.ledger.income_statement_period import (
    IncomeStatementPeriod,
    get_income_statement_projection,
)

if TYPE_CHECKING:
    from uuid import UUID

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_CONFIG: dict[str, Any] = {
    "output_dir": "/var/reports/ojk",
    "company_name": "PT ERP Accounting Engine Tbk",
    "company_address": "Jakarta Selatan, DKI Jakarta",
    "company_npwp": "123456789012345",
    "company_industry": "Software",
    "currency": "IDR",
    "include_notes": True,
}

# OJK standard line items for balance sheet (simplified)
OJK_BALANCE_SHEET_LINES = {
    "assets": [
        {"code": "A001", "label": "Kas dan Setara Kas", "source_field": "cash_and_equivalents"},
        {"code": "A002", "label": "Piutang Usaha", "source_field": "accounts_receivable"},
        {"code": "A003", "label": "Persediaan", "source_field": "inventory"},
        {"code": "A004", "label": "Aset Lancar Lainnya", "source_field": "other_current_assets"},
        {"code": "A005", "label": "Total Aset Lancar", "source_field": "current_assets"},
        {"code": "A006", "label": "Aset Tetap", "source_field": "fixed_assets"},
        {"code": "A007", "label": "Aset Tidak Berwujud", "source_field": "intangible_assets"},
        {
            "code": "A008",
            "label": "Aset Tidak Lancar Lainnya",
            "source_field": "other_noncurrent_assets",
        },
        {"code": "A009", "label": "Total Aset Tidak Lancar", "source_field": "non_current_assets"},
        {"code": "A010", "label": "TOTAL ASET", "source_field": "total_assets"},
    ],
    "liabilities": [
        {"code": "L001", "label": "Utang Usaha", "source_field": "accounts_payable"},
        {"code": "L002", "label": "Utang Pajak", "source_field": "tax_payable"},
        {
            "code": "L003",
            "label": "Utang Lancar Lainnya",
            "source_field": "other_current_liabilities",
        },
        {"code": "L004", "label": "Total Utang Lancar", "source_field": "current_liabilities"},
        {"code": "L005", "label": "Utang Jangka Panjang", "source_field": "long_term_debt"},
        {
            "code": "L006",
            "label": "Utang Tidak Lancar Lainnya",
            "source_field": "other_noncurrent_liabilities",
        },
        {
            "code": "L007",
            "label": "Total Utang Tidak Lancar",
            "source_field": "non_current_liabilities",
        },
        {"code": "L008", "label": "TOTAL LIABILITAS", "source_field": "total_liabilities"},
    ],
    "equity": [
        {"code": "E001", "label": "Modal Saham", "source_field": "share_capital"},
        {"code": "E002", "label": "Tambahan Modal Disetor", "source_field": "additional_paid_in"},
        {"code": "E003", "label": "Saldo Laba", "source_field": "retained_earnings"},
        {"code": "E004", "label": "Komponen Ekuitas Lainnya", "source_field": "other_equity"},
        {"code": "E005", "label": "TOTAL EKUITAS", "source_field": "total_equity"},
    ],
}

OJK_INCOME_STATEMENT_LINES = [
    {"code": "I001", "label": "Pendapatan Usaha", "source_field": "revenue"},
    {"code": "I002", "label": "Beban Pokok Pendapatan", "source_field": "cost_of_sales"},
    {"code": "I003", "label": "Laba Bruto", "source_field": "gross_profit"},
    {"code": "I004", "label": "Beban Usaha", "source_field": "operating_expenses"},
    {"code": "I005", "label": "Laba Usaha", "source_field": "operating_profit"},
    {
        "code": "I006",
        "label": "Pendapatan (Beban) Lain-lain",
        "source_field": "other_income_expenses",
    },
    {"code": "I007", "label": "Laba Sebelum Pajak", "source_field": "profit_before_tax"},
    {"code": "I008", "label": "Beban Pajak Penghasilan", "source_field": "income_tax_expense"},
    {"code": "I009", "label": "Laba Bersih Tahun Berjalan", "source_field": "net_income"},
]

# ============================================================================
# EXCEPTIONS
# ============================================================================


class OJKFormatBuilderError(Exception):
    """Base exception untuk OJK format builder."""

    pass


# ============================================================================
# OJK FORMAT BUILDER
# ============================================================================


class OJKFormatBuilder:
    """
    Builder laporan keuangan format OJK.

    Fitur:
    - Laporan posisi keuangan (neraca) sesuai OJK
    - Laporan laba rugi komprehensif
    - Laporan perubahan ekuitas
    - Laporan arus kas (indirect method)
    - Catatan atas laporan keuangan (optional)
    - Ekspor ke JSON dan CSV
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Inisialisasi OJKFormatBuilder dengan konfigurasi yang diinjeksi.

        Args:
            config: Dictionary konfigurasi (jika None, gunakan DEFAULT_CONFIG)
        """
        self.config = self._prepare_config(config)
        self._output_dir = Path(self.config.get("output_dir", "/var/reports/ojk"))
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._balance_sheet: BalanceSheetSnapshot | None = None
        self._income_statement: IncomeStatementPeriod | None = None
        self._cash_flow: CashFlowIndirect | None = None
        self._equity_statement: EquityStatement | None = None

    def _prepare_config(self, config: dict | None) -> dict:
        """Siapkan konfigurasi dari parameter atau default."""
        if config is not None:
            result: dict[str, Any] = DEFAULT_CONFIG.copy()
            for key, value in config.items():
                # Only merge dicts; for other types, simply assign
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key].update(value)  # type: ignore[attr-defined]
                else:
                    result[key] = value
            return result
        return DEFAULT_CONFIG.copy()

    async def _get_balance_sheet(self) -> BalanceSheetSnapshot:
        if self._balance_sheet is None:
            self._balance_sheet = await get_balance_sheet_snapshot()
        return self._balance_sheet

    async def _get_income_statement(self) -> IncomeStatementPeriod:
        if self._income_statement is None:
            self._income_statement = await get_income_statement_projection()
        return self._income_statement

    async def _get_cash_flow(self) -> CashFlowIndirect:
        if self._cash_flow is None:
            self._cash_flow = await get_cash_flow_projection()
        return self._cash_flow

    async def _get_equity_statement(self) -> EquityStatement:
        if self._equity_statement is None:
            self._equity_statement = await get_equity_statement()
        return self._equity_statement

    async def _get_financial_data(
        self, legal_entity_id: UUID, period_id: UUID, start_date: datetime, end_date: datetime
    ) -> dict[str, Decimal]:
        """
        Mengumpulkan data keuangan yang diperlukan untuk laporan OJK.
        """
        # Balance sheet
        bs = await self._get_balance_sheet()
        bs_data = await bs.get_snapshot(legal_entity_id, period_id)
        if not bs_data:
            raise OJKFormatBuilderError(f"Balance sheet not available for period {period_id}")

        # Income statement
        inc = await self._get_income_statement()
        inc_data = await inc.get_income_statement(legal_entity_id, period_id)

        # Cash flow - perlu start_date, end_date
        cf = await self._get_cash_flow()
        cf_data = await cf.get_cash_flow_statement(
            legal_entity_id, start_date, end_date
        )

        # Equity statement (currently not used in data mapping, but kept for future)
        eq = await self._get_equity_statement()
        _ = await eq.get_equity_statement(
            legal_entity_id, start_date, end_date
        )

        # Build data dictionary (simplified mapping)
        data = {
            "total_assets": Decimal(str(bs_data.get("total_assets", 0))),
            "current_assets": Decimal(str(bs_data.get("current_assets", 0))),
            "non_current_assets": Decimal(str(bs_data.get("non_current_assets", 0))),
            "total_liabilities": Decimal(str(bs_data.get("total_liabilities", 0))),
            "current_liabilities": Decimal(str(bs_data.get("current_liabilities", 0))),
            "non_current_liabilities": Decimal(str(bs_data.get("non_current_liabilities", 0))),
            "total_equity": Decimal(str(bs_data.get("total_equity", 0))),
            "revenue": Decimal(str(inc_data.get("total_revenue", 0))) if inc_data else Decimal(0),
            "cost_of_sales": Decimal(str(inc_data.get("total_cogs", 0))) if inc_data else Decimal(0),
            "gross_profit": Decimal(str(inc_data.get("gross_profit", 0))) if inc_data else Decimal(0),
            "operating_expenses": Decimal(str(inc_data.get("operating_expense", 0))) if inc_data else Decimal(0),
            "operating_profit": Decimal(str(inc_data.get("operating_income", 0))) if inc_data else Decimal(0),
            "net_income": Decimal(str(inc_data.get("net_income", 0))) if inc_data else Decimal(0),
            "operating_cash_flow": Decimal(str(cf_data.get("operating_cash_flow", 0))) if cf_data else Decimal(0),
            "investing_cash_flow": Decimal(str(cf_data.get("investing_cash_flow", 0))) if cf_data else Decimal(0),
            "financing_cash_flow": Decimal(str(cf_data.get("financing_cash_flow", 0))) if cf_data else Decimal(0),
            "net_cash_flow": Decimal(str(cf_data.get("net_cash_flow", 0))) if cf_data else Decimal(0),
        }
        return data

    async def build_balance_sheet(self, legal_entity_id: UUID, period_id: UUID) -> dict:
        """
        Membangun laporan posisi keuangan (neraca) format OJK.
        """
        # Need period dates for cash flow, but we don't have them here, we can fetch them
        async with await get_session_factory() as session:
            period_stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
            period_result = await session.execute(period_stmt)
            period = period_result.scalar_one_or_none()
            if not period:
                raise OJKFormatBuilderError(f"Period {period_id} not found")
            start_date = period.start_date
            end_date = period.end_date

        data = await self._get_financial_data(legal_entity_id, period_id, start_date, end_date)

        assets = []
        for line in OJK_BALANCE_SHEET_LINES["assets"]:
            value = data.get(line["source_field"], Decimal(0))
            assets.append({"code": line["code"], "label": line["label"], "value": str(value)})

        liabilities = []
        for line in OJK_BALANCE_SHEET_LINES["liabilities"]:
            value = data.get(line["source_field"], Decimal(0))
            liabilities.append(
                {"code": line["code"], "label": line["label"], "value": str(value)}
            )

        equity = []
        for line in OJK_BALANCE_SHEET_LINES["equity"]:
            value = data.get(line["source_field"], Decimal(0))
            equity.append({"code": line["code"], "label": line["label"], "value": str(value)})

        return {
            "legal_entity_id": str(legal_entity_id),
            "period_id": str(period_id),
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "assets": assets,
            "liabilities": liabilities,
            "equity": equity,
            "total_assets": assets[-1]["value"] if assets else "0",
            "total_liabilities_equity": str(
                (Decimal(liabilities[-1]["value"]) if liabilities else Decimal(0))
                + (Decimal(equity[-1]["value"]) if equity else Decimal(0))
            ),
            "currency": self.config.get("currency", "IDR"),
        }

    async def build_income_statement(self, legal_entity_id: UUID, period_id: UUID) -> dict:
        """
        Membangun laporan laba rugi format OJK.
        """
        # Same for period dates
        async with await get_session_factory() as session:
            period_stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
            period_result = await session.execute(period_stmt)
            period = period_result.scalar_one_or_none()
            if not period:
                raise OJKFormatBuilderError(f"Period {period_id} not found")
            start_date = period.start_date
            end_date = period.end_date

        data = await self._get_financial_data(legal_entity_id, period_id, start_date, end_date)

        lines = []
        for line in OJK_INCOME_STATEMENT_LINES:
            value = data.get(line["source_field"], Decimal(0))
            lines.append({"code": line["code"], "label": line["label"], "value": str(value)})

        return {
            "legal_entity_id": str(legal_entity_id),
            "period_id": str(period_id),
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "lines": lines,
            "net_income": lines[-1]["value"] if lines else "0",
            "currency": self.config.get("currency", "IDR"),
        }

    async def build_cash_flow_statement(self, legal_entity_id: UUID, period_id: UUID) -> dict:
        """
        Membangun laporan arus kas format OJK (indirect method).
        """
        async with await get_session_factory() as session:
            period_stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
            period_result = await session.execute(period_stmt)
            period = period_result.scalar_one_or_none()
            if not period:
                raise OJKFormatBuilderError(f"Period {period_id} not found")
            start_date = period.start_date
            end_date = period.end_date

        data = await self._get_financial_data(legal_entity_id, period_id, start_date, end_date)

        cash_flow = {
            "operating": data.get("operating_cash_flow", Decimal(0)),
            "investing": data.get("investing_cash_flow", Decimal(0)),
            "financing": data.get("financing_cash_flow", Decimal(0)),
            "net_cash_flow": data.get("net_cash_flow", Decimal(0)),
            "beginning_cash": Decimal(0),  # would need previous period
            "ending_cash": Decimal(0),
        }
        cash_flow["ending_cash"] = cash_flow["beginning_cash"] + cash_flow["net_cash_flow"]

        return {
            "legal_entity_id": str(legal_entity_id),
            "period_id": str(period_id),
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "operating_activities": str(cash_flow["operating"]),
            "investing_activities": str(cash_flow["investing"]),
            "financing_activities": str(cash_flow["financing"]),
            "net_increase_decrease": str(cash_flow["net_cash_flow"]),
            "beginning_cash": str(cash_flow["beginning_cash"]),
            "ending_cash": str(cash_flow["ending_cash"]),
            "currency": self.config.get("currency", "IDR"),
        }

    async def build_full_report(self, legal_entity_id: UUID, period_id: UUID) -> dict:
        """
        Membangun laporan OJK lengkap (semua komponen).
        """
        balance_sheet = await self.build_balance_sheet(legal_entity_id, period_id)
        income_statement = await self.build_income_statement(legal_entity_id, period_id)
        cash_flow = await self.build_cash_flow_statement(legal_entity_id, period_id)

        company_info = {
            "name": self.config.get("company_name", "PT ERP Accounting Engine Tbk"),
            "address": self.config.get("company_address", ""),
            "npwp": self.config.get("company_npwp", ""),
            "industry": self.config.get("company_industry", ""),
            "legal_entity_id": str(legal_entity_id),
        }

        return {
            "company_info": company_info,
            "balance_sheet": balance_sheet,
            "income_statement": income_statement,
            "cash_flow_statement": cash_flow,
            "generated_at": datetime.now(UTC).isoformat(),
        }

    # ========================================================================
    # EXPORT FUNCTIONS — DIPERBAIKI (async file I/O + thread pool)
    # ========================================================================

    async def export_json(self, legal_entity_id: UUID, period_id: UUID) -> Path:
        """
        Mengekspor laporan OJK ke file JSON.
        """
        report = await self.build_full_report(legal_entity_id, period_id)

        # Get period info already included in sub-reports, so we can add it to main
        async with await get_session_factory() as session:
            period_stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
            period_result = await session.execute(period_stmt)
            period = period_result.scalar_one_or_none()
            if period:
                report["period"] = {
                    "name": period.period_name,
                    "start": period.start_date.isoformat(),
                    "end": period.end_date.isoformat(),
                    "year": period.fiscal_year,
                    "month": period.period_number,
                }

        filename = f"ojk_report_{legal_entity_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        output_path = self._output_dir / filename

        # Serialisasi JSON di thread pool (CPU-bound)
        def _dump_json_sync() -> str:
            return json.dumps(report, indent=2, default=str)

        json_content = await asyncio.to_thread(_dump_json_sync)

        # Tulis JSON secara async
        async with aiofiles.open(output_path, "w") as f:
            await f.write(json_content)

        logger.info(f"OJK report exported to {output_path}")
        return output_path

    async def export_csv(self, legal_entity_id: UUID, period_id: UUID) -> Path:
        """
        Mengekspor laporan OJK ke file CSV (multiple sheets via separate files).
        """
        balance_sheet = await self.build_balance_sheet(legal_entity_id, period_id)
        income_stmt = await self.build_income_statement(legal_entity_id, period_id)
        cash_flow = await self.build_cash_flow_statement(legal_entity_id, period_id)

        base_name = f"ojk_report_{legal_entity_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Helper untuk menulis CSV
        async def _write_csv(filename: str, header: list, rows: list[list]) -> None:
            file_path = self._output_dir / filename

            def _write_sync() -> str:
                import io
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(header)
                for row in rows:
                    writer.writerow(row)
                return output.getvalue()

            csv_content = await asyncio.to_thread(_write_sync)
            async with aiofiles.open(file_path, "w", newline="") as f:
                await f.write(csv_content)

        # Balance sheet CSV
        bs_rows = []
        for item in balance_sheet["assets"]:
            bs_rows.append([item["code"], item["label"], item["value"]])
        for item in balance_sheet["liabilities"]:
            bs_rows.append([item["code"], item["label"], item["value"]])
        for item in balance_sheet["equity"]:
            bs_rows.append([item["code"], item["label"], item["value"]])
        await _write_csv(
            f"{base_name}_balance_sheet.csv",
            ["Code", "Account", "Amount"],
            bs_rows
        )

        # Income statement CSV
        is_rows = [
            [item["code"], item["label"], item["value"]]
            for item in income_stmt["lines"]
        ]
        await _write_csv(
            f"{base_name}_income_statement.csv",
            ["Code", "Description", "Amount"],
            is_rows
        )

        # Cash flow CSV
        cf_rows = [
            ["Operating", cash_flow["operating_activities"]],
            ["Investing", cash_flow["investing_activities"]],
            ["Financing", cash_flow["financing_activities"]],
            ["Net Cash Flow", cash_flow["net_increase_decrease"]],
            ["Beginning Cash", cash_flow["beginning_cash"]],
            ["Ending Cash", cash_flow["ending_cash"]],
        ]
        await _write_csv(
            f"{base_name}_cash_flow.csv",
            ["Activity", "Amount"],
            cf_rows
        )

        logger.info(f"OJK CSV reports exported to {self._output_dir}")
        return self._output_dir / f"{base_name}_balance_sheet.csv"


# ============================================================================
# SINGLETON INSTANCE dengan injeksi konfigurasi
# ============================================================================

_ojk_builder: OJKFormatBuilder | None = None
_ojk_config: dict | None = None


def set_ojk_builder_config(config: dict) -> None:
    """Set konfigurasi untuk OJKFormatBuilder (harus dipanggil sebelum get_ojk_builder)."""
    global _ojk_config
    _ojk_config = config


async def get_ojk_builder() -> OJKFormatBuilder:
    """Get singleton instance of OJKFormatBuilder."""
    global _ojk_builder
    if _ojk_builder is None:
        _ojk_builder = OJKFormatBuilder(config=_ojk_config)
    return _ojk_builder


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "OJKFormatBuilder",
    "OJKFormatBuilderError",
    "get_ojk_builder",
    "set_ojk_builder_config",
]
