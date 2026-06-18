#!/usr/bin/env python3

"""
Module: year_end_closing.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk penutupan tahun buku (year-end closing).
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from application.commands_cqrs.command_bus_unified import Command, CommandResult
from application.service_layer.service_fiscal_period import FiscalPeriodService
from application.service_layer.service_fixed_asset import FixedAssetService
from application.service_layer.service_journal import JournalService
from application.service_layer.service_tax import TaxService
from application.use_cases.period_close import PeriodCloseCommand, PeriodCloseUseCase
from application.use_cases.post_closing_journal import (
    PostClosingJournalCommand,
    PostClosingJournalUseCase,
)
from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


class YearEndClosingCommand(Command):
    """Command untuk year-end closing."""

    __slots__ = (
        "adjust_tax",
        "closing_date",
        "closing_year",
        "dry_run",
        "generate_financial_statements",
        "impairment_test",
        "legal_entity_id",
        "revaluation_assets",
        "reverse_opening_balances",
    )

    def __init__(
        self,
        legal_entity_id: UUID,
        closing_year: int,
        closing_date: date,
        reverse_opening_balances: bool = True,
        adjust_tax: bool = True,
        impairment_test: bool = True,
        revaluation_assets: bool = False,
        generate_financial_statements: bool = True,
        dry_run: bool = False,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="YearEndClosingCommand", user_id=user_id, correlation_id=correlation_id
        )
        self.legal_entity_id = legal_entity_id
        self.closing_year = closing_year
        self.closing_date = closing_date
        self.reverse_opening_balances = reverse_opening_balances
        self.adjust_tax = adjust_tax
        self.impairment_test = impairment_test
        self.revaluation_assets = revaluation_assets
        self.generate_financial_statements = generate_financial_statements
        self.dry_run = dry_run

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "legal_entity_id": str(self.legal_entity_id),
                "closing_year": self.closing_year,
                "closing_date": self.closing_date.isoformat(),
                "reverse_opening_balances": self.reverse_opening_balances,
                "adjust_tax": self.adjust_tax,
                "impairment_test": self.impairment_test,
                "revaluation_assets": self.revaluation_assets,
                "generate_financial_statements": self.generate_financial_statements,
                "dry_run": self.dry_run,
            }
        )
        return data


class YearEndClosingResult:
    def __init__(
        self,
        periods_closed: list[str],
        closing_journal_ids: list[UUID],
        tax_adjustment_journal_id: UUID | None,
        reversal_journal_ids: list[UUID],
        impairment_journal_ids: list[UUID],
        financial_statement_paths: list[str],
        message: str,
    ):
        self.periods_closed = periods_closed
        self.closing_journal_ids = closing_journal_ids
        self.tax_adjustment_journal_id = tax_adjustment_journal_id
        self.reversal_journal_ids = reversal_journal_ids
        self.impairment_journal_ids = impairment_journal_ids
        self.financial_statement_paths = financial_statement_paths
        self.message = message


class YearEndClosingUseCase:
    """
    Use case untuk penutupan tahun buku.
    """

    def __init__(
        self,
        period_close_uc: PeriodCloseUseCase,
        post_closing_uc: PostClosingJournalUseCase,
        fiscal_period_service: FiscalPeriodService,
        tax_service: TaxService,
        fixed_asset_service: FixedAssetService,
        journal_service: JournalService,
        sealed_gate: SealedGate | None = None,
    ):
        self._period_close_uc = period_close_uc
        self._post_closing_uc = post_closing_uc
        self._period_service = fiscal_period_service
        self._tax_service = tax_service
        self._fa_service = fixed_asset_service
        self._journal_service = journal_service
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: YearEndClosingCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            periods = await self._period_service.list_periods(
                command.legal_entity_id, command.closing_year
            )
            if not periods:
                raise ValueError(f"No fiscal periods found for year {command.closing_year}")

            periods_closed = []
            closing_journal_ids = []
            reversal_journal_ids = []
            impairment_journal_ids = []
            tax_journal_id = None
            financial_statements = []

            if command.dry_run:
                return CommandResult.success(
                    command_id=command.command_id,
                    data={"dry_run": True, "message": "Validation passed, year-end closing ready"},
                )

            async def _execute():
                nonlocal tax_journal_id
                for period in periods:
                    if period.status == "CLOSED":
                        periods_closed.append(f"{command.closing_year}-{period.period_month:02d}")
                        continue
                    close_cmd = PeriodCloseCommand(
                        legal_entity_id=command.legal_entity_id,
                        period_year=command.closing_year,
                        period_month=period.period_month,
                        close_date=command.closing_date,
                        run_closing_journals=True,
                        skip_validation_checks=False,
                        force_close=False,
                        user_id=command.user_id,
                        correlation_id=command.correlation_id,
                    )
                    close_result = await self._period_close_uc.execute(close_cmd)
                    if not close_result.is_success():
                        raise ValueError(
                            f"Failed to close period {period.period_month}: {close_result.error}"
                        )
                    periods_closed.append(f"{command.closing_year}-{period.period_month:02d}")
                    if close_result.data and close_result.data.get("closing_journal_id"):
                        closing_journal_ids.append(UUID(close_result.data["closing_journal_id"]))

                year_end_close_cmd = PostClosingJournalCommand(
                    legal_entity_id=command.legal_entity_id,
                    period_year=command.closing_year,
                    period_month=12,
                    closing_date=command.closing_date,
                    include_income_statement_accounts=True,
                    include_withdrawal_accounts=True,
                    user_id=command.user_id,
                    correlation_id=command.correlation_id,
                )
                year_end_result = await self._post_closing_uc.execute(year_end_close_cmd)
                if year_end_result.is_success() and year_end_result.data:
                    closing_journal_ids.append(UUID(year_end_result.data["journal_id"]))

                if command.adjust_tax:
                    estimated_tax = await self._tax_service.calculate_corporate_tax(
                        command.legal_entity_id, command.closing_year
                    )
                    if estimated_tax > 0:
                        tax_journal_id = await self._post_tax_adjustment_journal(
                            command.legal_entity_id,
                            estimated_tax,
                            command.closing_date,
                            command.user_id,
                        )

                if command.impairment_test:
                    assets = await self._fa_service.list_assets(
                        command.legal_entity_id, status="ACTIVE"
                    )
                    for asset in assets:
                        recoverable = await self._fa_service.get_recoverable_amount(asset.id)
                        if asset.net_book_value > recoverable:
                            journal_id = await self._fa_service.record_impairment_loss(
                                asset.id,
                                asset.net_book_value - recoverable,
                                command.closing_date,
                                command.user_id,
                            )
                            impairment_journal_ids.append(journal_id)

                if command.reverse_opening_balances:
                    reversal_ids = await self._create_reversing_entries(
                        command.legal_entity_id,
                        command.closing_year,
                        command.closing_date,
                        command.user_id,
                    )
                    reversal_journal_ids.extend(reversal_ids)

                if command.generate_financial_statements:
                    paths = await self._generate_financial_statements(
                        command.legal_entity_id, command.closing_year, command.closing_date
                    )
                    financial_statements.extend(paths)

                await self._period_service.close_fiscal_year(
                    command.legal_entity_id,
                    command.closing_year,
                    command.closing_date,
                    command.user_id,
                )

                return YearEndClosingResult(
                    periods_closed=periods_closed,
                    closing_journal_ids=closing_journal_ids,
                    tax_adjustment_journal_id=tax_journal_id,
                    reversal_journal_ids=reversal_journal_ids,
                    impairment_journal_ids=impairment_journal_ids,
                    financial_statement_paths=financial_statements,
                    message=f"Year {command.closing_year} closed successfully",
                )

            if self._sealed_gate:
                result = await self._sealed_gate.execute(
                    command_type=command.command_type,
                    command_id=command.command_id,
                    handler=_execute,
                )
            else:
                result = await _execute()

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "periods_closed": result.periods_closed,
                    "closing_journal_ids": [str(jid) for jid in result.closing_journal_ids],
                    "tax_adjustment_journal_id": str(result.tax_adjustment_journal_id)
                    if result.tax_adjustment_journal_id
                    else None,
                    "reversal_journal_ids": [str(jid) for jid in result.reversal_journal_ids],
                    "impairment_journal_ids": [str(jid) for jid in result.impairment_journal_ids],
                    "financial_statement_paths": result.financial_statement_paths,
                    "message": result.message,
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"Year-end closing failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="YEAR_END_CLOSING_ERROR"
            )

    async def _post_tax_adjustment_journal(
        self, legal_entity_id: UUID, tax_amount: Decimal, posting_date: date, user_id: UUID
    ) -> UUID:
        tax_expense_account = "5-5200"
        tax_payable_account = "2-2100"
        lines = [
            {
                "account_code": tax_expense_account,
                "debit": tax_amount,
                "credit": Decimal("0"),
                "description": "Corporate income tax",
            },
            {
                "account_code": tax_payable_account,
                "debit": Decimal("0"),
                "credit": tax_amount,
                "description": "Tax payable",
            },
        ]
        journal_id = await self._journal_service.post_journal(
            legal_entity_id=legal_entity_id,
            journal_date=posting_date,
            period=f"{posting_date.year}-{posting_date.month:02d}",
            description=f"Corporate income tax adjustment for {posting_date.year}",
            lines=lines,
            source_system="year_end_closing",
            user_id=user_id,
            correlation_id=None,
        )
        return journal_id

    async def _create_reversing_entries(
        self, legal_entity_id: UUID, year: int, reversal_date: date, user_id: UUID
    ) -> list[UUID]:
        reversal_ids = []
        accrual_journals = await self._journal_service.find_accrual_journals(legal_entity_id, year)
        for journal in accrual_journals:
            reversal_id = await self._journal_service.reverse_journal(
                original_journal_id=journal.id,
                reason="Year-end reversal",
                user_id=user_id,
                reversal_date=reversal_date,
            )
            reversal_ids.append(reversal_id)
        return reversal_ids

    async def _generate_financial_statements(
        self, legal_entity_id: UUID, year: int, as_of_date: date
    ) -> list[str]:
        from application.service_layer.service_report import ReportService

        report_service = ReportService()
        paths = []
        bs_path = await report_service.export_to_excel(
            {"type": "balance_sheet", "year": year}, f"Balance_Sheet_{year}"
        )
        paths.append(bs_path)
        is_path = await report_service.export_to_excel(
            {"type": "income_statement", "year": year}, f"Income_Statement_{year}"
        )
        paths.append(is_path)
        cf_path = await report_service.export_to_excel(
            {"type": "cash_flow", "year": year}, f"Cash_Flow_{year}"
        )
        paths.append(cf_path)
        return paths

    def get_stats(self) -> dict[str, int]:
        return self._stats


async def year_end_closing_handler(
    command: Command, use_case: YearEndClosingUseCase
) -> CommandResult:
    if not isinstance(command, YearEndClosingCommand):
        raise TypeError(f"Expected YearEndClosingCommand, got {type(command)}")
    return await use_case.execute(command)


__all__ = [
    "YearEndClosingCommand",
    "YearEndClosingResult",
    "YearEndClosingUseCase",
    "year_end_closing_handler",
]
