#!/usr/bin/env python3

"""
Module: financial_statement_generation.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk menghasilkan laporan keuangan (financial statements).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from application.commands_cqrs.command_bus_unified import Command, CommandResult
from application.service_layer.service_coa import COAService
from application.service_layer.service_consolidation import ConsolidationService
from application.service_layer.service_report import ReportService
from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


class StatementType(Enum):
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW = "cash_flow"
    EQUITY_STATEMENT = "equity_statement"
    TRIAL_BALANCE = "trial_balance"
    GENERAL_LEDGER = "general_ledger"


class ExportFormat(Enum):
    PDF = "pdf"
    EXCEL = "excel"
    CSV = "csv"
    XBRL = "xbrl"
    JSON = "json"


class FinancialStatementGenerationCommand(Command):
    """Command untuk generate laporan keuangan."""

    __slots__ = (
        "as_of_date",
        "comparative_period_end",
        "comparative_period_start",
        "consolidate_entities",
        "currency_code",
        "entity_ids",
        "export_format",
        "include_notes",
        "legal_entity_id",
        "period_end",
        "period_start",
        "send_email_to",
        "statement_type",
    )

    def __init__(
        self,
        legal_entity_id: UUID,
        statement_type: str,
        period_start: date | None = None,
        period_end: date | None = None,
        as_of_date: date | None = None,
        currency_code: str = "IDR",
        comparative_period_start: date | None = None,
        comparative_period_end: date | None = None,
        consolidate_entities: bool = False,
        entity_ids: list[UUID] | None = None,
        export_format: str = "pdf",
        send_email_to: list[str] | None = None,
        include_notes: bool = True,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="FinancialStatementGenerationCommand",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        self.legal_entity_id = legal_entity_id
        self.statement_type = statement_type
        self.period_start = period_start
        self.period_end = period_end
        self.as_of_date = as_of_date
        self.currency_code = currency_code
        self.comparative_period_start = comparative_period_start
        self.comparative_period_end = comparative_period_end
        self.consolidate_entities = consolidate_entities
        self.entity_ids = entity_ids or []
        self.export_format = export_format
        self.send_email_to = send_email_to or []
        self.include_notes = include_notes

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "legal_entity_id": str(self.legal_entity_id),
                "statement_type": self.statement_type,
                "period_start": self.period_start.isoformat() if self.period_start else None,
                "period_end": self.period_end.isoformat() if self.period_end else None,
                "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
                "currency_code": self.currency_code,
                "comparative_period_start": self.comparative_period_start.isoformat()
                if self.comparative_period_start
                else None,
                "comparative_period_end": self.comparative_period_end.isoformat()
                if self.comparative_period_end
                else None,
                "consolidate_entities": self.consolidate_entities,
                "entity_ids": [str(eid) for eid in self.entity_ids],
                "export_format": self.export_format,
                "send_email_to": self.send_email_to,
                "include_notes": self.include_notes,
            }
        )
        return data


class FinancialStatementResult:
    def __init__(
        self,
        statement_id: UUID,
        statement_type: str,
        generated_at: datetime,
        output_path: str | None,
        output_size: int,
        rows_count: int,
        message: str,
    ):
        self.statement_id = statement_id
        self.statement_type = statement_type
        self.generated_at = generated_at
        self.output_path = output_path
        self.output_size = output_size
        self.rows_count = rows_count
        self.message = message


class FinancialStatementGenerationUseCase:
    """
    Use case untuk generate laporan keuangan.
    """

    def __init__(
        self,
        report_service: ReportService,
        coa_service: COAService,
        consolidation_service: ConsolidationService | None = None,
        sealed_gate: SealedGate | None = None,
    ):
        self._report_service = report_service
        self._coa_service = coa_service
        self._consolidation_service = consolidation_service
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: FinancialStatementGenerationCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            if command.statement_type in (
                StatementType.BALANCE_SHEET.value,
                StatementType.TRIAL_BALANCE.value,
            ):
                if not command.as_of_date:
                    raise ValueError("Balance sheet and trial balance require as_of_date")
                period_start = None
                period_end = None
            elif command.statement_type in (
                StatementType.INCOME_STATEMENT.value,
                StatementType.CASH_FLOW.value,
                StatementType.EQUITY_STATEMENT.value,
            ):
                if not command.period_start or not command.period_end:
                    raise ValueError(
                        "Income statement, cash flow, and equity statement require period_start and period_end"
                    )
                period_start = command.period_start
                period_end = command.period_end
            else:
                raise ValueError(f"Unknown statement type: {command.statement_type}")

            if command.consolidate_entities and self._consolidation_service:
                if not command.entity_ids:
                    entities = await self._coa_service.get_child_entities(command.legal_entity_id)
                    command.entity_ids = [e.id for e in entities]
                consolidation_result = await self._consolidation_service.consolidate(
                    group_entity_id=command.legal_entity_id,
                    period_end_date=command.as_of_date or command.period_end,
                    include_entities=command.entity_ids,
                    currency_code=command.currency_code,
                )
                legal_entity_id = None
            else:
                consolidation_result = None
                legal_entity_id = command.legal_entity_id

            data = None
            if command.statement_type == StatementType.BALANCE_SHEET.value:
                data = await self._report_service.get_balance_sheet(
                    legal_entity_id=legal_entity_id,
                    as_of_date=command.as_of_date,
                    comparative_date=command.comparative_period_end,
                    currency_code=command.currency_code,
                )
            elif command.statement_type == StatementType.INCOME_STATEMENT.value:
                data = await self._report_service.get_income_statement(
                    legal_entity_id=legal_entity_id,
                    period_start=period_start,
                    period_end=period_end,
                    compare_with_previous=bool(command.comparative_period_start),
                    currency_code=command.currency_code,
                )
            elif command.statement_type == StatementType.CASH_FLOW.value:
                data = await self._report_service.get_cash_flow(
                    legal_entity_id=legal_entity_id,
                    period_start=period_start,
                    period_end=period_end,
                    method="INDIRECT",
                    currency_code=command.currency_code,
                )
            elif command.statement_type == StatementType.TRIAL_BALANCE.value:
                data = await self._report_service.get_trial_balance(
                    legal_entity_id=legal_entity_id,
                    as_of_date=command.as_of_date,
                    currency_code=command.currency_code,
                )
            elif command.statement_type == StatementType.GENERAL_LEDGER.value:
                if not command.entity_ids:
                    raise ValueError("General ledger requires entity_ids for each account")
                data = await self._report_service.get_general_ledger(
                    legal_entity_id=legal_entity_id,
                    account_code="1-1000",
                    from_date=command.period_start,
                    to_date=command.period_end,
                )
            else:
                raise ValueError(f"Unsupported statement type: {command.statement_type}")

            output_path = None
            output_size = 0
            rows_count = 0
            if command.export_format == ExportFormat.PDF.value:
                output_path = await self._report_service.export_to_pdf(
                    data, f"{command.statement_type}_{command.legal_entity_id}"
                )
                output_size = 1024 * 50
                rows_count = len(getattr(data, "rows", [])) if hasattr(data, "rows") else 0
            elif command.export_format == ExportFormat.EXCEL.value:
                output_path = await self._report_service.export_to_excel(
                    data, f"{command.statement_type}_{command.legal_entity_id}"
                )
                output_size = 1024 * 100
                rows_count = len(getattr(data, "rows", [])) if hasattr(data, "rows") else 0
            elif command.export_format == ExportFormat.CSV.value:
                output_path = await self._report_service.export_to_csv(
                    data, f"{command.statement_type}_{command.legal_entity_id}"
                )
                output_size = 1024 * 30
                rows_count = len(getattr(data, "rows", [])) if hasattr(data, "rows") else 0
            elif command.export_format == ExportFormat.JSON.value:
                if hasattr(data, "__dict__"):
                    json_data = json.dumps(data.__dict__, default=str)
                else:
                    json_data = json.dumps(data, default=str)
                output_path = f"/tmp/{command.statement_type}_{command.legal_entity_id}_{datetime.utcnow().timestamp()}.json"
                with open(output_path, "w") as f:
                    f.write(json_data)
                output_size = len(json_data)
                rows_count = 0
            elif command.export_format == ExportFormat.XBRL.value:
                output_path = await self._report_service.export_to_xbrl(data, command)
                output_size = 1024 * 200

            if command.send_email_to:
                await self._send_report_email(
                    recipients=command.send_email_to,
                    statement_type=command.statement_type,
                    output_path=output_path,
                    report_data=data,
                )

            result = FinancialStatementResult(
                statement_id=uuid4(),
                statement_type=command.statement_type,
                generated_at=datetime.utcnow(),
                output_path=output_path,
                output_size=output_size,
                rows_count=rows_count,
                message=f"Financial statement generated successfully: {command.statement_type}",
            )

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "statement_id": str(result.statement_id),
                    "statement_type": result.statement_type,
                    "generated_at": result.generated_at.isoformat(),
                    "output_path": result.output_path,
                    "output_size": result.output_size,
                    "rows_count": result.rows_count,
                    "message": result.message,
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"Financial statement generation failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="FINANCIAL_STATEMENT_ERROR"
            )

    async def _send_report_email(
        self, recipients: list[str], statement_type: str, output_path: str | None, report_data: Any
    ) -> None:
        logger.info(
            f"Sending email to {recipients} for {statement_type}, attachment: {output_path}"
        )

    def get_stats(self) -> dict[str, int]:
        return self._stats


# ============================================================================
# Handler dengan dependency injection
# ============================================================================


async def financial_statement_generation_handler(
    command: Command, use_case: FinancialStatementGenerationUseCase
) -> CommandResult:
    if not isinstance(command, FinancialStatementGenerationCommand):
        raise TypeError(f"Expected FinancialStatementGenerationCommand, got {type(command)}")
    return await use_case.execute(command)


__all__ = [
    "ExportFormat",
    "FinancialStatementGenerationCommand",
    "FinancialStatementGenerationUseCase",
    "FinancialStatementResult",
    "StatementType",
    "financial_statement_generation_handler",
]
