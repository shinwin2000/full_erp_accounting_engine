#!/usr/bin/env python3

"""
Module: fiscal_reconciliation.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk rekonsiliasi fiskal (penyesuaian antara laporan komersial dan fiskal).
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any
from uuid import UUID

from application.commands_cqrs.command_bus_unified import BaseCommand, CommandResult
from application.service_layer.service_ledger import LedgerService
from application.service_layer.service_report import ReportService
from application.service_layer.service_tax import TaxService
from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


class FiscalReconciliationCommand(BaseCommand):
    """Command untuk rekonsiliasi fiskal."""

    __slots__ = (
        "dry_run",
        "include_corrections",
        "legal_entity_id",
        "post_adjustment_journal",
        "tahun_pajak",
    )

    def __init__(
        self,
        legal_entity_id: UUID,
        tahun_pajak: int,
        include_corrections: bool = True,
        post_adjustment_journal: bool = False,
        dry_run: bool = False,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="FiscalReconciliationCommand",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        self.legal_entity_id = legal_entity_id
        self.tahun_pajak = tahun_pajak
        self.include_corrections = include_corrections
        self.post_adjustment_journal = post_adjustment_journal
        self.dry_run = dry_run

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "legal_entity_id": str(self.legal_entity_id),
                "tahun_pajak": self.tahun_pajak,
                "include_corrections": self.include_corrections,
                "post_adjustment_journal": self.post_adjustment_journal,
                "dry_run": self.dry_run,
            }
        )
        return data


class FiscalCorrection:
    def __init__(self, description: str, amount: Decimal, is_permanent: bool = True):
        self.description = description
        self.amount = amount
        self.is_permanent = is_permanent


class FiscalReconciliationResult:
    def __init__(
        self,
        commercial_net_income: Decimal,
        fiscal_corrections_positive: list[FiscalCorrection],
        fiscal_corrections_negative: list[FiscalCorrection],
        fiscal_net_income: Decimal,
        fiscal_loss_compensation: Decimal,
        taxable_income: Decimal,
        corporate_tax_rate: Decimal,
        corporate_tax_due: Decimal,
        tax_credits: Decimal,
        tax_payable: Decimal,
        adjustment_journal_id: UUID | None,
        report_path: str | None,
    ):
        self.commercial_net_income = commercial_net_income
        self.fiscal_corrections_positive = fiscal_corrections_positive
        self.fiscal_corrections_negative = fiscal_corrections_negative
        self.fiscal_net_income = fiscal_net_income
        self.fiscal_loss_compensation = fiscal_loss_compensation
        self.taxable_income = taxable_income
        self.corporate_tax_rate = corporate_tax_rate
        self.corporate_tax_due = corporate_tax_due
        self.tax_credits = tax_credits
        self.tax_payable = tax_payable
        self.adjustment_journal_id = adjustment_journal_id
        self.report_path = report_path


class FiscalReconciliationUseCase:
    """
    Use case untuk rekonsiliasi fiskal.
    """

    def __init__(
        self,
        tax_service: TaxService,
        ledger_service: LedgerService,
        report_service: ReportService,
        journal_service,  # JournalService - akan diinject
        sealed_gate: SealedGate | None = None,
    ):
        self._tax_service = tax_service
        self._ledger_service = ledger_service
        self._report_service = report_service
        self._journal_service = journal_service
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: FiscalReconciliationCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            commercial_net_income = await self._get_commercial_net_income(
                command.legal_entity_id, command.tahun_pajak
            )
            positive_corrections, negative_corrections = await self._get_fiscal_corrections(
                command.legal_entity_id, command.tahun_pajak
            )
            total_positive = sum(c.amount for c in positive_corrections)
            total_negative = sum(c.amount for c in negative_corrections)
            fiscal_net_income = commercial_net_income + total_positive - total_negative
            loss_compensation = await self._tax_service.get_loss_compensation(
                command.legal_entity_id, command.tahun_pajak
            )
            taxable_income = max(fiscal_net_income - loss_compensation, Decimal("0"))
            corporate_tax_rate = Decimal("0.22")
            corporate_tax_due = (taxable_income * corporate_tax_rate).quantize(
                Decimal("0"), rounding=ROUND_HALF_EVEN
            )
            tax_credits = await self._tax_service.get_tax_credits(
                command.legal_entity_id, command.tahun_pajak
            )
            tax_payable = max(corporate_tax_due - tax_credits, Decimal("0"))

            if command.dry_run:
                return CommandResult.success(
                    command_id=command.command_id,
                    data={
                        "dry_run": True,
                        "commercial_net_income": float(commercial_net_income),
                        "fiscal_net_income": float(fiscal_net_income),
                        "taxable_income": float(taxable_income),
                        "corporate_tax_due": float(corporate_tax_due),
                        "tax_credits": float(tax_credits),
                        "tax_payable": float(tax_payable),
                    },
                )

            adjustment_journal_id = None
            if command.post_adjustment_journal and tax_payable > 0:
                adjustment_journal_id = await self._post_tax_adjustment_journal(
                    command.legal_entity_id,
                    tax_payable,
                    command.tahun_pajak,
                    command.user_id,
                    command.correlation_id,
                )

            report_path = await self._generate_reconciliation_report(
                command.legal_entity_id,
                command.tahun_pajak,
                commercial_net_income,
                fiscal_net_income,
                taxable_income,
                corporate_tax_due,
                tax_credits,
                tax_payable,
                positive_corrections,
                negative_corrections,
            )

            result = FiscalReconciliationResult(
                commercial_net_income=commercial_net_income,
                fiscal_corrections_positive=positive_corrections,
                fiscal_corrections_negative=negative_corrections,
                fiscal_net_income=fiscal_net_income,
                fiscal_loss_compensation=loss_compensation,
                taxable_income=taxable_income,
                corporate_tax_rate=corporate_tax_rate,
                corporate_tax_due=corporate_tax_due,
                tax_credits=tax_credits,
                tax_payable=tax_payable,
                adjustment_journal_id=adjustment_journal_id,
                report_path=report_path,
            )

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "commercial_net_income": float(result.commercial_net_income),
                    "fiscal_net_income": float(result.fiscal_net_income),
                    "taxable_income": float(result.taxable_income),
                    "corporate_tax_due": float(result.corporate_tax_due),
                    "tax_credits": float(result.tax_credits),
                    "tax_payable": float(result.tax_payable),
                    "adjustment_journal_id": str(result.adjustment_journal_id)
                    if result.adjustment_journal_id
                    else None,
                    "report_path": result.report_path,
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"Fiscal reconciliation failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id,
                error=str(e),
                error_code="FISCAL_RECONCILIATION_ERROR",
            )

    async def _get_commercial_net_income(self, legal_entity_id: UUID, tahun: int) -> Decimal:
        period_start = date(tahun, 1, 1)
        period_end = date(tahun, 12, 31)
        income_stmt = await self._report_service.get_income_statement(
            legal_entity_id=legal_entity_id,
            period_start=period_start,
            period_end=period_end,
            compare_with_previous=False,
            currency_code="IDR",
        )
        return getattr(income_stmt, "net_income", Decimal("0"))

    async def _get_fiscal_corrections(
        self, legal_entity_id: UUID, tahun: int
    ) -> tuple[list[FiscalCorrection], list[FiscalCorrection]]:
        positive = []
        negative = []
        entertainment_expense = await self._ledger_service.get_account_balance(
            legal_entity_id, "5-6100", tahun, 12, date(tahun, 12, 31)
        )
        if entertainment_expense > 0:
            non_deductible = entertainment_expense * Decimal("0.5")
            positive.append(
                FiscalCorrection("Entertainment expense (non-deductible 50%)", non_deductible)
            )
        donation = await self._ledger_service.get_account_balance(
            legal_entity_id, "5-6200", tahun, 12, date(tahun, 12, 31)
        )
        if donation > 0:
            positive.append(FiscalCorrection("Donation (non-deductible)", donation))
        tax_exempt_income = await self._ledger_service.get_account_balance(
            legal_entity_id, "4-8000", tahun, 12, date(tahun, 12, 31)
        )
        if tax_exempt_income > 0:
            negative.append(FiscalCorrection("Tax exempt income", tax_exempt_income))
        return positive, negative

    async def _post_tax_adjustment_journal(
        self,
        legal_entity_id: UUID,
        tax_due: Decimal,
        tahun: int,
        user_id: UUID,
        correlation_id: str | None,
    ) -> UUID:
        tax_expense_account = "5-7000"
        tax_payable_account = "2-2100"
        lines = [
            {
                "account_code": tax_expense_account,
                "debit": tax_due,
                "credit": Decimal("0"),
                "description": f"Corporate income tax {tahun}",
            },
            {
                "account_code": tax_payable_account,
                "debit": Decimal("0"),
                "credit": tax_due,
                "description": f"Tax payable {tahun}",
            },
        ]
        journal_id = await self._journal_service.post_journal(
            legal_entity_id=legal_entity_id,
            journal_date=date(tahun, 12, 31),
            period=f"{tahun}-12",
            description=f"Tax adjustment for fiscal year {tahun}",
            lines=lines,
            source_system="fiscal_reconciliation",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        return journal_id

    async def _generate_reconciliation_report(
        self,
        legal_entity_id: UUID,
        tahun: int,
        commercial_income: Decimal,
        fiscal_income: Decimal,
        taxable_income: Decimal,
        tax_due: Decimal,
        tax_credits: Decimal,
        tax_payable: Decimal,
        positive_corrections: list[FiscalCorrection],
        negative_corrections: list[FiscalCorrection],
    ) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Fiscal Reconciliation Report", f"Year {tahun}"])
        writer.writerow([])
        writer.writerow(["Commercial Net Income", float(commercial_income)])
        writer.writerow(["Fiscal Corrections Positive"])
        for c in positive_corrections:
            writer.writerow([f"  {c.description}", float(c.amount)])
        writer.writerow(["Total Positive Corrections", sum(c.amount for c in positive_corrections)])
        writer.writerow(["Fiscal Corrections Negative"])
        for c in negative_corrections:
            writer.writerow([f"  {c.description}", float(c.amount)])
        writer.writerow(["Total Negative Corrections", sum(c.amount for c in negative_corrections)])
        writer.writerow(["Fiscal Net Income", float(fiscal_income)])
        writer.writerow(["Loss Compensation", 0.0])
        writer.writerow(["Taxable Income (PKP)", float(taxable_income)])
        writer.writerow(["Corporate Tax Rate", "22%"])
        writer.writerow(["Corporate Tax Due", float(tax_due)])
        writer.writerow(["Tax Credits", float(tax_credits)])
        writer.writerow(["Tax Payable (Under/Overpayment)", float(tax_payable)])
        file_path = f"/tmp/fiscal_reconciliation_{legal_entity_id}_{tahun}.csv"
        with open(file_path, "w") as f:
            f.write(output.getvalue())
        return file_path

    def get_stats(self) -> dict[str, int]:
        return self._stats


# ============================================================================
# Handler dengan dependency injection
# ============================================================================


async def fiscal_reconciliation_handler(
    command: BaseCommand, use_case: FiscalReconciliationUseCase
) -> CommandResult:
    if not isinstance(command, FiscalReconciliationCommand):
        raise TypeError(f"Expected FiscalReconciliationCommand, got {type(command)}")
    return await use_case.execute(command)


__all__ = [
    "FiscalCorrection",
    "FiscalReconciliationCommand",
    "FiscalReconciliationResult",
    "FiscalReconciliationUseCase",
    "fiscal_reconciliation_handler",
]
