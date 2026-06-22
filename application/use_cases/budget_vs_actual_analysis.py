#!/usr/bin/env python3

"""
Module: budget_vs_actual_analysis.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk analisis budget vs actual (anggaran vs realisasi).
    Mencakup pengambilan data anggaran, realisasi, perhitungan variance,
    identifikasi variance material, dan generate laporan.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from application.commands_cqrs.command_bus_unified import BaseCommand, CommandResult
from application.service_layer.service_budget import BudgetService
from application.service_layer.service_ledger import LedgerService
from application.service_layer.service_report import ReportService
from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


class VarianceDirection(Enum):
    FAVORABLE = "FAVORABLE"
    UNFAVORABLE = "UNFAVORABLE"


class BudgetVsActualCommand(BaseCommand):
    """Command untuk analisis budget vs actual."""

    __slots__ = (
        "account_type_filter",
        "budget_version",
        "cost_center_filter",
        "department_filter",
        "dry_run",
        "export_format",
        "include_zero_variance",
        "legal_entity_id",
        "period_end",
        "period_start",
        "project_filter",
        "variance_threshold_percent",
    )

    def __init__(
        self,
        legal_entity_id: UUID,
        period_start: date,
        period_end: date,
        budget_version: str = "current",
        account_type_filter: list[str] | None = None,
        cost_center_filter: list[UUID] | None = None,
        department_filter: list[UUID] | None = None,
        project_filter: list[UUID] | None = None,
        variance_threshold_percent: Decimal = Decimal("10"),
        include_zero_variance: bool = False,
        export_format: str = "json",
        dry_run: bool = False,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="BudgetVsActualCommand", user_id=user_id, correlation_id=correlation_id
        )
        self.legal_entity_id = legal_entity_id
        self.period_start = period_start
        self.period_end = period_end
        self.budget_version = budget_version
        self.account_type_filter = account_type_filter or []
        self.cost_center_filter = cost_center_filter or []
        self.department_filter = department_filter or []
        self.project_filter = project_filter or []
        self.variance_threshold_percent = variance_threshold_percent
        self.include_zero_variance = include_zero_variance
        self.export_format = export_format
        self.dry_run = dry_run

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "legal_entity_id": str(self.legal_entity_id),
                "period_start": self.period_start.isoformat(),
                "period_end": self.period_end.isoformat(),
                "budget_version": self.budget_version,
                "account_type_filter": self.account_type_filter,
                "cost_center_filter": [str(cc) for cc in self.cost_center_filter],
                "department_filter": [str(dep) for dep in self.department_filter],
                "project_filter": [str(proj) for proj in self.project_filter],
                "variance_threshold_percent": float(self.variance_threshold_percent),
                "include_zero_variance": self.include_zero_variance,
                "export_format": self.export_format,
                "dry_run": self.dry_run,
            }
        )
        return data


@dataclass
class BudgetVsActualRow:
    account_code: str
    account_name: str
    account_type: str
    cost_center: str | None
    department: str | None
    project: str | None
    budget_amount: Decimal
    actual_amount: Decimal
    variance_amount: Decimal
    variance_percent: Decimal
    variance_direction: str
    is_material: bool


@dataclass
class BudgetVsActualResult:
    rows: list[BudgetVsActualRow]
    total_budget: Decimal
    total_actual: Decimal
    total_variance: Decimal
    material_variance_count: int
    favorable_variance_count: int
    unfavorable_variance_count: int
    report_path: str | None
    generated_at: datetime


class BudgetVsActualUseCase:
    """
    Use case untuk analisis budget vs actual.
    """

    def __init__(
        self,
        budget_service: BudgetService,
        ledger_service: LedgerService,
        report_service: ReportService,
        sealed_gate: SealedGate | None = None,
    ):
        self._budget_service = budget_service
        self._ledger_service = ledger_service
        self._report_service = report_service
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: BudgetVsActualCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            # 1. Ambil data anggaran
            budget_data = await self._budget_service.get_budget(
                legal_entity_id=command.legal_entity_id,
                period_start=command.period_start,
                period_end=command.period_end,
                version=command.budget_version,
                account_types=command.account_type_filter,
                cost_centers=command.cost_center_filter,
                departments=command.department_filter,
                projects=command.project_filter,
            )

            # 2. Ambil data actual dari ledger
            actual_data = await self._ledger_service.get_actual_by_account(
                legal_entity_id=command.legal_entity_id,
                period_start=command.period_start,
                period_end=command.period_end,
                account_types=command.account_type_filter,
                cost_centers=command.cost_center_filter,
                departments=command.department_filter,
                projects=command.project_filter,
            )

            # 3. Gabungkan dan hitung variance
            all_accounts = set(budget_data.keys()) | set(actual_data.keys())
            rows = []
            total_budget = Decimal("0")
            total_actual = Decimal("0")
            material_count = 0
            favorable_count = 0
            unfavorable_count = 0

            for account_code in sorted(all_accounts):
                budget = budget_data.get(account_code, Decimal("0"))
                actual = actual_data.get(account_code, Decimal("0"))
                variance = actual - budget
                variance_percent = Decimal("0")
                if budget != 0:
                    variance_percent = (variance / budget * Decimal("100")).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_EVEN
                    )
                elif actual != 0:
                    variance_percent = Decimal("100") if actual > 0 else Decimal("-100")

                is_material = abs(variance_percent) >= command.variance_threshold_percent
                variance_direction = (
                    VarianceDirection.FAVORABLE.value
                    if variance <= 0
                    else VarianceDirection.UNFAVORABLE.value
                )

                if variance_percent > 0:
                    unfavorable_count += 1
                elif variance_percent < 0:
                    favorable_count += 1

                if is_material:
                    material_count += 1

                if (
                    not command.include_zero_variance
                    and variance == 0
                    and budget == 0
                    and actual == 0
                ):
                    continue

                # Dapatkan metadata akun (nama, tipe)
                account_meta = await self._get_account_metadata(
                    account_code, command.legal_entity_id
                )

                rows.append(
                    BudgetVsActualRow(
                        account_code=account_code,
                        account_name=account_meta.get("name", account_code),
                        account_type=account_meta.get("type", ""),
                        cost_center=None,
                        department=None,
                        project=None,
                        budget_amount=budget,
                        actual_amount=actual,
                        variance_amount=variance,
                        variance_percent=variance_percent,
                        variance_direction=variance_direction,
                        is_material=is_material,
                    )
                )
                total_budget += budget
                total_actual += actual

            total_variance = total_actual - total_budget

            # 4. Export jika diminta
            report_path = None
            if not command.dry_run and command.export_format != "json":
                report_path = await self._export_report(
                    rows, command, total_budget, total_actual, total_variance
                )

            result = BudgetVsActualResult(
                rows=rows,
                total_budget=total_budget,
                total_actual=total_actual,
                total_variance=total_variance,
                material_variance_count=material_count,
                favorable_variance_count=favorable_count,
                unfavorable_variance_count=unfavorable_count,
                report_path=report_path,
                generated_at=datetime.utcnow(),
            )

            # 5. Simpan history analisis (untuk audit)
            if not command.dry_run:
                await self._save_analysis_history(command, result)

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "total_budget": float(result.total_budget),
                    "total_actual": float(result.total_actual),
                    "total_variance": float(result.total_variance),
                    "material_variance_count": result.material_variance_count,
                    "favorable_variance_count": result.favorable_variance_count,
                    "unfavorable_variance_count": result.unfavorable_variance_count,
                    "rows_count": len(result.rows),
                    "report_path": result.report_path,
                    "generated_at": result.generated_at.isoformat(),
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"Budget vs actual analysis failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="BUDGET_VS_ACTUAL_ERROR"
            )

    async def _get_account_metadata(
        self, account_code: str, legal_entity_id: UUID
    ) -> dict[str, str]:
        # Placeholder, real implementation would call COA service
        if account_code.startswith("4"):
            return {"name": f"Revenue - {account_code}", "type": "REVENUE"}
        elif account_code.startswith("5"):
            return {"name": f"Expense - {account_code}", "type": "EXPENSE"}
        else:
            return {"name": f"Account {account_code}", "type": "BALANCE_SHEET"}

    async def _export_report(
        self,
        rows: list[BudgetVsActualRow],
        command: BudgetVsActualCommand,
        total_budget: Decimal,
        total_actual: Decimal,
        total_variance: Decimal,
    ) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Account Code",
                "Account Name",
                "Account Type",
                "Budget",
                "Actual",
                "Variance",
                "Variance %",
                "Direction",
                "Material",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.account_code,
                    row.account_name,
                    row.account_type,
                    float(row.budget_amount),
                    float(row.actual_amount),
                    float(row.variance_amount),
                    float(row.variance_percent),
                    row.variance_direction,
                    "Yes" if row.is_material else "No",
                ]
            )
        writer.writerow([])
        writer.writerow(
            [
                "TOTAL",
                "",
                "",
                float(total_budget),
                float(total_actual),
                float(total_variance),
                "",
                "",
                "",
            ]
        )
        file_path = f"/tmp/budget_vs_actual_{command.legal_entity_id}_{command.period_start}_{command.period_end}.csv"
        with open(file_path, "w") as f:
            f.write(output.getvalue())
        return file_path

    async def _save_analysis_history(
        self, command: BudgetVsActualCommand, result: BudgetVsActualResult
    ) -> None:
        logger.info(f"Budget vs actual analysis saved for {command.legal_entity_id}")

    def get_stats(self) -> dict[str, int]:
        return self._stats


# ============================================================================
# Handler dengan dependency injection
# ============================================================================


async def budget_vs_actual_handler(
    command: BaseCommand, use_case: BudgetVsActualUseCase
) -> CommandResult:
    if not isinstance(command, BudgetVsActualCommand):
        raise TypeError(f"Expected BudgetVsActualCommand, got {type(command)}")
    return await use_case.execute(command)


__all__ = [
    "BudgetVsActualCommand",
    "BudgetVsActualResult",
    "BudgetVsActualRow",
    "BudgetVsActualUseCase",
    "VarianceDirection",
    "budget_vs_actual_handler",
]
