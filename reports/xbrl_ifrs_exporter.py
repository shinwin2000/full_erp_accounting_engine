#!/usr/bin/env python3
"""
Module: xbrl_ifrs_exporter.py
Layer: Reports
Responsibility: Mengekspor laporan keuangan dalam format XBRL (eXtensible Business
               Reporting Language) sesuai dengan standar IFRS. Digunakan untuk
               pelaporan ke OJK, BEI, atau otoritas pajak. Memetakan data dari
               ledger ke taksonomi IFRS dan menghasilkan file XBRL instance (.xbrl)
               beserta taxonomy references.
Dependencies:
- xml.etree.ElementTree, datetime, decimal
- infrastructure.persistence_orm.ledger_entry_table
- projections.ledger.balance_sheet_snapshot
- projections.ledger.income_statement_period
- config.loader_yaml -> DIINJEKSI DARI LUAR (tidak diimpor langsung)
- infrastructure.telemetry.structured_json_logging
Audit: Setiap ekspor XBRL dicatat. File XBRL disimpan sebagai bukti pelaporan.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.telemetry.structured_json_logging import get_logger
from projections.ledger.balance_sheet_snapshot import (
    BalanceSheetSnapshot,
    get_balance_sheet_snapshot,
)
from projections.ledger.cash_flow_indirect import CashFlowIndirect, get_cash_flow_projection
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
    "output_dir": "/var/reports/xbrl",
    "taxonomy_url": "https://xbrl.ifrs.org/taxonomy/2024/ifrs-full",
    "company_identifier_scheme": "http://www.oecd.org/documentation/lei",
    "period_type": "duration",  # or "instant"
}

# Namespaces for XBRL
XBRL_NAMESPACES = {
    "xbrli": "http://www.xbrl.org/2003/instance",
    "link": "http://www.xbrl.org/2003/linkbase",
    "xlink": "http://www.w3.org/1999/xlink",
    "iso4217": "http://www.xbrl.org/2003/iso4217",
    "ifrs-full": "http://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full",
    "ifrs-full_cor": "http://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full-cor",
    "dei": "http://xbrl.sec.gov/dei/2023",
}

# Mapping from internal report items to IFRS taxonomy concepts
IFRS_MAPPING = {
    "total_assets": "ifrs-full:Assets",
    "current_assets": "ifrs-full:CurrentAssets",
    "non_current_assets": "ifrs-full:NoncurrentAssets",
    "total_liabilities": "ifrs-full:Liabilities",
    "current_liabilities": "ifrs-full:CurrentLiabilities",
    "non_current_liabilities": "ifrs-full:NoncurrentLiabilities",
    "total_equity": "ifrs-full:Equity",
    "revenue": "ifrs-full:Revenue",
    "cost_of_sales": "ifrs-full:CostOfSales",
    "gross_profit": "ifrs-full:GrossProfit",
    "operating_expenses": "ifrs-full:OperatingExpenses",
    "operating_profit": "ifrs-full:OperatingProfitLoss",
    "finance_costs": "ifrs-full:FinanceCosts",
    "profit_before_tax": "ifrs-full:ProfitLossBeforeTax",
    "income_tax_expense": "ifrs-full:IncomeTaxExpenseContinuingOperations",
    "net_income": "ifrs-full:ProfitLoss",
    "ebitda": "ifrs-full:Ebitda",
    "cash_flow_operating": "ifrs-full:CashFlowsFromUsedInOperatingActivities",
    "cash_flow_investing": "ifrs-full:CashFlowsFromUsedInInvestingActivities",
    "cash_flow_financing": "ifrs-full:CashFlowsFromUsedInFinancingActivities",
    "net_cash_flow": "ifrs-full:IncreaseDecreaseInCashAndCashEquivalents",
    "cash_and_cash_equivalents": "ifrs-full:CashAndCashEquivalents",
}

# ============================================================================
# EXCEPTIONS
# ============================================================================


class XBRLExportError(Exception):
    """Base exception untuk XBRL exporter."""

    pass


# ============================================================================
# XBRL EXPORTER
# ============================================================================


class XBRLIFRSExporter:
    """
    Exporter untuk laporan keuangan dalam format XBRL sesuai IFRS.

    Fitur:
    - Generate XBRL instance document
    - Mapping data ke taksonomi IFRS
    - Support context (period, entity, segment)
    - Multi-currency support (ISO 4217)
    - Validasi terhadap taxonomy
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = self._prepare_config(config)
        self._output_dir = Path(self.config.get("output_dir", "/var/reports/xbrl"))
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._taxonomy_url = self.config.get(
            "taxonomy_url", "https://xbrl.ifrs.org/taxonomy/2024/ifrs-full"
        )
        self._company_identifier_scheme = self.config.get(
            "company_identifier_scheme", "http://www.oecd.org/documentation/lei"
        )
        self._balance_sheet: BalanceSheetSnapshot | None = None
        self._income_statement: IncomeStatementPeriod | None = None
        self._cash_flow: CashFlowIndirect | None = None

    def _prepare_config(self, config: dict | None) -> dict:
        if config is not None:
            result: dict[str, Any] = DEFAULT_CONFIG.copy()
            for key, value in config.items():
                # Only update if key exists and both are dicts
                if key in result and isinstance(value, dict) and isinstance(result[key], dict):
                    cast(dict, result[key]).update(value)
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

    async def collect_financial_data(
        self, legal_entity_id: UUID, period_id: UUID
    ) -> dict[str, Decimal]:
        """
        Mengumpulkan data keuangan untuk ekspor XBRL.
        """
        # Get balance sheet snapshot
        balance_sheet = await self._get_balance_sheet()
        bs = await balance_sheet.get_snapshot(legal_entity_id, period_id)
        if not bs:
            raise XBRLExportError(f"Balance sheet not available for period {period_id}")

        # Get income statement
        income_stmt = await self._get_income_statement()
        inc = await income_stmt.get_income_statement(legal_entity_id, period_id)

        # Get cash flow
        cash_flow = await self._get_cash_flow()
        cf = await cash_flow.compute_full_cash_flow(
            legal_entity_id,
            date.fromisoformat(bs["as_of_date"]),
            date.fromisoformat(bs["as_of_date"]),
        )

        data = {
            "total_assets": Decimal(str(bs["total_assets"])),
            "total_liabilities": Decimal(str(bs["total_liabilities"])),
            "total_equity": Decimal(str(bs["total_equity"])),
        }

        if inc:
            data.update(
                {
                    "revenue": Decimal(str(inc["total_revenue"])),
                    "net_income": Decimal(str(inc["net_income"])),
                }
            )

        if cf:
            data.update(
                {
                    "cash_flow_operating": Decimal(str(cf.get("operating_cash_flow", 0))),
                    "cash_flow_investing": Decimal(str(cf.get("investing_cash_flow", 0))),
                    "cash_flow_financing": Decimal(str(cf.get("financing_cash_flow", 0))),
                    "net_cash_flow": Decimal(str(cf.get("net_cash_flow", 0))),
                }
            )

        return data

    def _create_xbrl_instance(
        self,
        entity_id: str,
        period_start: date,
        period_end: date,
        data: dict[str, Decimal],
        currency: str = "IDR",
    ) -> ET.Element:
        """
        Membuat root element XBRL instance.
        """
        root = ET.Element("xbrli:xbrl", XBRL_NAMESPACES)

        # Context for the period (duration)
        context_id = "C1"
        context = ET.SubElement(root, "xbrli:context", {"id": context_id})
        entity = ET.SubElement(context, "xbrli:entity")
        identifier = ET.SubElement(
            entity, "xbrli:identifier", {"scheme": self._company_identifier_scheme}
        )
        identifier.text = entity_id
        ET.SubElement(entity, "xbrli:segment")
        # Add segment if needed (e.g., business unit)

        period_elem = ET.SubElement(context, "xbrli:period")
        start_date = ET.SubElement(period_elem, "xbrli:startDate")
        start_date.text = period_start.isoformat()
        end_date = ET.SubElement(period_elem, "xbrli:endDate")
        end_date.text = period_end.isoformat()

        # Instant context for balance sheet (as of period end)
        context_instant_id = "C2"
        context_instant = ET.SubElement(root, "xbrli:context", {"id": context_instant_id})
        entity_inst = ET.SubElement(context_instant, "xbrli:entity")
        ident_inst = ET.SubElement(
            entity_inst, "xbrli:identifier", {"scheme": self._company_identifier_scheme}
        )
        ident_inst.text = entity_id
        period_inst = ET.SubElement(context_instant, "xbrli:period")
        instant = ET.SubElement(period_inst, "xbrli:instant")
        instant.text = period_end.isoformat()

        # Unit for currency
        unit_id = "U1"
        unit = ET.SubElement(root, "xbrli:unit", {"id": unit_id})
        measure = ET.SubElement(unit, "xbrli:measure")
        measure.text = f"iso4217:{currency}"

        # Add facts
        for internal_name, concept in IFRS_MAPPING.items():
            if internal_name in data:
                value = data[internal_name]
                # Determine which context to use based on whether it's balance sheet (instant) or income/cash (duration)
                # For simplicity, we use duration context for income/cash, instant for balance sheet
                if internal_name in [
                    "total_assets",
                    "total_liabilities",
                    "total_equity",
                    "cash_and_cash_equivalents",
                ]:
                    fact_context = context_instant_id
                else:
                    fact_context = context_id

                fact = ET.SubElement(
                    root,
                    concept,
                    {
                        "contextRef": fact_context,
                        "unitRef": unit_id,
                        "decimals": "0",
                        "precision": "inf",
                    },
                )
                fact.text = str(int(value))  # XBRL biasanya integer untuk mata uang
                fact.set("xsi:nil", "false")

        return root

    async def export_xbrl(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        entity_identifier: str,
        currency: str = "IDR",
        output_filename: str | None = None,
    ) -> Path:
        """
        Mengekspor laporan keuangan ke file XBRL.

        Args:
            legal_entity_id: Legal entity ID
            period_id: Period ID (FiscalPeriod)
            entity_identifier: Entity identifier (e.g., LEI code or NPWP)
            currency: Currency code (ISO 4217)
            output_filename: Custom filename

        Returns:
            Path to generated XBRL file
        """
        # Get period info
        from sqlalchemy import select

        from infrastructure.persistence_orm.fiscal_period_table import FiscalPeriodTable

        async with await get_session_factory() as session:
            period_stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
            period_result = await session.execute(period_stmt)
            period = period_result.scalar_one_or_none()
            if not period:
                raise XBRLExportError(f"Period {period_id} not found")

        # Collect financial data
        data = await self.collect_financial_data(legal_entity_id, period_id)

        # Create XBRL instance
        root = self._create_xbrl_instance(
            entity_id=entity_identifier,
            period_start=period.start_date,
            period_end=period.end_date,
            currency=currency,
            data=data,
        )

        # Write to file
        if output_filename is None:
            output_filename = f"xbrl_{legal_entity_id}_{period.fiscal_year}_{period.period_number:02d}_{datetime.now().strftime('%Y%m%d')}.xbrl"
        output_path = self._output_dir / output_filename

        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        tree.write(str(output_path), encoding="utf-8", xml_declaration=True)

        logger.info(f"XBRL report exported to {output_path}")
        return output_path

    async def validate_xbrl(self, xbrl_path: Path) -> bool:
        """
        Validasi file XBRL terhadap taksonomi (sederhana: check XML well-formed).
        """
        try:
            tree = ET.parse(xbrl_path)
            root = tree.getroot()
            # Check if it contains at least one fact
            has_fact = False
            for elem in root:
                if elem.tag in [
                    f"{{{XBRL_NAMESPACES['ifrs-full']}}}{name}" for name in IFRS_MAPPING.values()
                ]:
                    has_fact = True
                    break
            if not has_fact:
                logger.warning(f"XBRL file {xbrl_path} contains no facts")
                return False
            return True
        except ET.ParseError as e:
            logger.error(f"XBRL validation failed: {e}")
            return False


# ============================================================================
# SINGLETON INSTANCE dengan injeksi konfigurasi
# ============================================================================

_xbrl_exporter: XBRLIFRSExporter | None = None
_xbrl_config: dict | None = None


def set_xbrl_exporter_config(config: dict) -> None:
    """Set konfigurasi untuk XBRLIFRSExporter (harus dipanggil sebelum get_xbrl_exporter)."""
    global _xbrl_config
    _xbrl_config = config


async def get_xbrl_exporter() -> XBRLIFRSExporter:
    """Get singleton instance of XBRLIFRSExporter."""
    global _xbrl_exporter
    if _xbrl_exporter is None:
        _xbrl_exporter = XBRLIFRSExporter(config=_xbrl_config)
    return _xbrl_exporter


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "XBRLExportError",
    "XBRLIFRSExporter",
    "get_xbrl_exporter",
    "set_xbrl_exporter_config",
]
