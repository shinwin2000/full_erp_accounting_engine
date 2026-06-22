#!/usr/bin/env python3

"""
Module: consolidation_group_report.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk menghasilkan laporan keuangan konsolidasi group perusahaan.
    Mencakup penggabungan laporan keuangan seluruh entitas anak, eliminasi intercompany,
    konversi mata uang asing, perhitungan NCI, dan generate laporan.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from application.commands_cqrs.command_bus_unified import BaseCommand, CommandResult
from application.service_layer.service_consolidation import ConsolidationService
from application.service_layer.service_ledger import LedgerService
from application.service_layer.service_report import ReportService
from application.use_cases.intercompany_elimination import (
    IntercompanyEliminationCommand,
    IntercompanyEliminationUseCase,
)
from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


class ConsolidationReportType(Enum):
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW = "cash_flow"
    EQUITY_STATEMENT = "equity_statement"
    ALL = "all"


class ConsolidationGroupReportCommand(BaseCommand):
    """Command untuk generate laporan konsolidasi group."""

    __slots__ = (
        "currency_code",
        "dry_run",
        "eliminate_intercompany",
        "entity_ids",
        "export_format",
        "group_entity_id",
        "include_nci",
        "period_end_date",
        "report_type",
    )

    def __init__(
        self,
        group_entity_id: UUID,
        period_end_date: date,
        entity_ids: list[UUID],
        report_type: str = "all",
        currency_code: str = "IDR",
        include_nci: bool = True,
        eliminate_intercompany: bool = True,
        export_format: str = "pdf",
        dry_run: bool = False,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="ConsolidationGroupReportCommand",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        self.group_entity_id = group_entity_id
        self.period_end_date = period_end_date
        self.entity_ids = entity_ids
        self.report_type = report_type
        self.currency_code = currency_code
        self.include_nci = include_nci
        self.eliminate_intercompany = eliminate_intercompany
        self.export_format = export_format
        self.dry_run = dry_run

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "group_entity_id": str(self.group_entity_id),
                "period_end_date": self.period_end_date.isoformat(),
                "entity_ids": [str(eid) for eid in self.entity_ids],
                "report_type": self.report_type,
                "currency_code": self.currency_code,
                "include_nci": self.include_nci,
                "eliminate_intercompany": self.eliminate_intercompany,
                "export_format": self.export_format,
                "dry_run": self.dry_run,
            }
        )
        return data


class ConsolidationReportResult:
    def __init__(
        self,
        report_id: UUID,
        report_type: str,
        group_entity_id: UUID,
        period_end_date: date,
        total_assets: Decimal,
        total_liabilities: Decimal,
        total_equity: Decimal,
        total_revenue: Decimal,
        total_net_income: Decimal,
        nci_amount: Decimal | None,
        elimination_summary: dict[str, Any],
        file_paths: list[str],
        generated_at: datetime,
    ):
        self.report_id = report_id
        self.report_type = report_type
        self.group_entity_id = group_entity_id
        self.period_end_date = period_end_date
        self.total_assets = total_assets
        self.total_liabilities = total_liabilities
        self.total_equity = total_equity
        self.total_revenue = total_revenue
        self.total_net_income = total_net_income
        self.nci_amount = nci_amount
        self.elimination_summary = elimination_summary
        self.file_paths = file_paths
        self.generated_at = generated_at


class ConsolidationGroupReportUseCase:
    """
    Use case untuk generate laporan keuangan konsolidasi group.
    """

    def __init__(
        self,
        consolidation_service: ConsolidationService,
        report_service: ReportService,
        ledger_service: LedgerService,
        intercompany_elimination_uc: IntercompanyEliminationUseCase,
        sealed_gate: SealedGate | None = None,
    ):
        self._consolidation_service = consolidation_service
        self._report_service = report_service
        self._ledger_service = ledger_service
        self._intercompany_uc = intercompany_elimination_uc
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: ConsolidationGroupReportCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            group_entity = await self._ledger_service.get_legal_entity(command.group_entity_id)
            if not group_entity:
                raise ValueError(f"Group entity {command.group_entity_id} not found")

            elimination_summary = {}
            if command.eliminate_intercompany and not command.dry_run:
                elim_cmd = IntercompanyEliminationCommand(
                    group_entity_id=command.group_entity_id,
                    period_end_date=command.period_end_date,
                    entity_ids=command.entity_ids,
                    auto_eliminate=True,
                    post_elimination_journal=True,
                    dry_run=False,
                    user_id=command.user_id,
                    correlation_id=command.correlation_id,
                )
                elim_result = await self._intercompany_uc.execute(elim_cmd)
                if elim_result.is_success() and elim_result.data:
                    elimination_summary = elim_result.data

            consolidated_data = await self._consolidation_service.prepare_consolidated_data(
                group_entity_id=command.group_entity_id,
                period_end_date=command.period_end_date,
                entity_ids=command.entity_ids,
                currency_code=command.currency_code,
                include_nci=command.include_nci,
            )

            file_paths = []
            report_id = uuid4()

            if command.report_type in (
                ConsolidationReportType.BALANCE_SHEET.value,
                ConsolidationReportType.ALL.value,
            ):
                bs_report = await self._generate_balance_sheet(consolidated_data, command)
                if not command.dry_run:
                    path = await self._export_report(bs_report, "balance_sheet", command)
                    file_paths.append(path)

            if command.report_type in (
                ConsolidationReportType.INCOME_STATEMENT.value,
                ConsolidationReportType.ALL.value,
            ):
                is_report = await self._generate_income_statement(consolidated_data, command)
                if not command.dry_run:
                    path = await self._export_report(is_report, "income_statement", command)
                    file_paths.append(path)

            if command.report_type in (
                ConsolidationReportType.CASH_FLOW.value,
                ConsolidationReportType.ALL.value,
            ):
                cf_report = await self._generate_cash_flow(consolidated_data, command)
                if not command.dry_run:
                    path = await self._export_report(cf_report, "cash_flow", command)
                    file_paths.append(path)

            if command.report_type in (
                ConsolidationReportType.EQUITY_STATEMENT.value,
                ConsolidationReportType.ALL.value,
            ):
                eq_report = await self._generate_equity_statement(consolidated_data, command)
                if not command.dry_run:
                    path = await self._export_report(eq_report, "equity_statement", command)
                    file_paths.append(path)

            result = ConsolidationReportResult(
                report_id=report_id,
                report_type=command.report_type,
                group_entity_id=command.group_entity_id,
                period_end_date=command.period_end_date,
                total_assets=consolidated_data.get("total_assets", Decimal("0")),
                total_liabilities=consolidated_data.get("total_liabilities", Decimal("0")),
                total_equity=consolidated_data.get("total_equity", Decimal("0")),
                total_revenue=consolidated_data.get("total_revenue", Decimal("0")),
                total_net_income=consolidated_data.get("net_income", Decimal("0")),
                nci_amount=consolidated_data.get("nci", Decimal("0")),
                elimination_summary=elimination_summary,
                file_paths=file_paths,
                generated_at=datetime.utcnow(),
            )

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "report_id": str(result.report_id),
                    "report_type": result.report_type,
                    "period_end_date": result.period_end_date.isoformat(),
                    "total_assets": float(result.total_assets),
                    "total_liabilities": float(result.total_liabilities),
                    "total_equity": float(result.total_equity),
                    "total_revenue": float(result.total_revenue),
                    "total_net_income": float(result.total_net_income),
                    "nci_amount": float(result.nci_amount) if result.nci_amount else None,
                    "file_paths": result.file_paths,
                    "generated_at": result.generated_at.isoformat(),
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"Consolidation group report failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="CONSOLIDATION_REPORT_ERROR"
            )

    async def _generate_balance_sheet(
        self, data: dict[str, Any], command: ConsolidationGroupReportCommand
    ) -> dict[str, Any]:
        return {
            "as_of_date": command.period_end_date,
            "currency": command.currency_code,
            "assets": data.get("assets", {}),
            "liabilities": data.get("liabilities", {}),
            "equity": data.get("equity", {}),
            "total_assets": data.get("total_assets", Decimal("0")),
            "total_liabilities": data.get("total_liabilities", Decimal("0")),
            "total_equity": data.get("total_equity", Decimal("0")),
        }

    async def _generate_income_statement(
        self, data: dict[str, Any], command: ConsolidationGroupReportCommand
    ) -> dict[str, Any]:
        return {
            "period_start": command.period_end_date.replace(day=1),
            "period_end": command.period_end_date,
            "currency": command.currency_code,
            "revenue": data.get("revenue", {}),
            "expenses": data.get("expenses", {}),
            "total_revenue": data.get("total_revenue", Decimal("0")),
            "total_expenses": data.get("total_expenses", Decimal("0")),
            "net_income": data.get("net_income", Decimal("0")),
            "nci": data.get("nci", Decimal("0")),
            "parent_net_income": data.get("net_income", Decimal("0"))
            - data.get("nci", Decimal("0")),
        }

    async def _generate_cash_flow(
        self, data: dict[str, Any], command: ConsolidationGroupReportCommand
    ) -> dict[str, Any]:
        return {
            "period_start": command.period_end_date.replace(day=1),
            "period_end": command.period_end_date,
            "currency": command.currency_code,
            "operating": data.get("cash_flow_operating", Decimal("0")),
            "investing": data.get("cash_flow_investing", Decimal("0")),
            "financing": data.get("cash_flow_financing", Decimal("0")),
            "net_cash_flow": data.get("net_cash_flow", Decimal("0")),
            "beginning_cash": data.get("beginning_cash", Decimal("0")),
            "ending_cash": data.get("ending_cash", Decimal("0")),
        }

    async def _generate_equity_statement(
        self, data: dict[str, Any], command: ConsolidationGroupReportCommand
    ) -> dict[str, Any]:
        return {
            "period_start": command.period_end_date.replace(day=1),
            "period_end": command.period_end_date,
            "currency": command.currency_code,
            "beginning_equity": data.get("beginning_equity", Decimal("0")),
            "net_income": data.get("net_income", Decimal("0")),
            "other_comprehensive_income": data.get("oci", Decimal("0")),
            "dividends": data.get("dividends", Decimal("0")),
            "capital_changes": data.get("capital_changes", Decimal("0")),
            "nci_changes": data.get("nci_changes", Decimal("0")),
            "ending_equity": data.get("total_equity", Decimal("0")),
        }

    async def _export_report(
        self,
        report_data: dict[str, Any],
        report_name: str,
        command: ConsolidationGroupReportCommand,
    ) -> str:
        if command.export_format == "json":
            file_path = f"/tmp/consolidation_{report_name}_{command.group_entity_id}_{command.period_end_date}.json"
            with open(file_path, "w") as f:
                json.dump(report_data, f, indent=2, default=str)
            return file_path
        elif command.export_format == "csv":
            file_path = f"/tmp/consolidation_{report_name}_{command.group_entity_id}_{command.period_end_date}.csv"
            with open(file_path, "w") as f:
                writer = csv.writer(f)
                for key, value in report_data.items():
                    writer.writerow([key, str(value)])
            return file_path
        else:
            # Default to CSV
            return await self._export_report(report_data, report_name, command)

    def get_stats(self) -> dict[str, int]:
        return self._stats


# ============================================================================
# Handler dengan dependency injection (tanpa container)
# ============================================================================


async def consolidation_group_report_handler(
    command: BaseCommand, use_case: ConsolidationGroupReportUseCase
) -> CommandResult:
    if not isinstance(command, ConsolidationGroupReportCommand):
        raise TypeError(f"Expected ConsolidationGroupReportCommand, got {type(command)}")
    return await use_case.execute(command)


__all__ = [
    "ConsolidationGroupReportCommand",
    "ConsolidationGroupReportUseCase",
    "ConsolidationReportResult",
    "ConsolidationReportType",
    "consolidation_group_report_handler",
]
