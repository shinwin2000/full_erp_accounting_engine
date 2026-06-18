#!/usr/bin/env python3

"""
Module: reverse_journal.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk reversal journal (membalik jurnal).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any
from uuid import UUID

from application.commands_cqrs.command_bus_unified import Command, CommandResult
from application.dto_objects.journal_request import JournalEntryRequestDTO, JournalLineRequestDTO
from application.service_layer.service_fiscal_period import FiscalPeriodService
from application.service_layer.service_journal import JournalService
from domain.journal.journal_entity import JournalStatus
from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


class ReverseJournalCommand(Command):
    """Command untuk reversal jurnal."""

    __slots__ = (
        "idempotency_key",
        "include_original_description",
        "original_journal_id",
        "period",
        "reason",
        "reversal_date",
    )

    def __init__(
        self,
        original_journal_id: UUID,
        reversal_date: date,
        reason: str,
        period: str | None = None,
        include_original_description: bool = True,
        idempotency_key: str | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="ReverseJournalCommand",
            user_id=user_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        self.original_journal_id = original_journal_id
        self.reversal_date = reversal_date
        self.reason = reason
        self.period = period
        self.include_original_description = include_original_description

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "original_journal_id": str(self.original_journal_id),
                "reversal_date": self.reversal_date.isoformat(),
                "reason": self.reason,
                "period": self.period,
                "include_original_description": self.include_original_description,
            }
        )
        return data


class ReverseJournalUseCase:
    """
    Use case untuk reversal jurnal.
    """

    def __init__(
        self,
        journal_service: JournalService,
        fiscal_period_service: FiscalPeriodService,
        sealed_gate: SealedGate | None = None,
    ):
        self._journal_service = journal_service
        self._period_service = fiscal_period_service
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: ReverseJournalCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            original_agg = await self._journal_service.get_journal_aggregate(
                command.original_journal_id
            )
            if not original_agg:
                raise ValueError(f"Original journal {command.original_journal_id} not found")

            original = original_agg.journal
            if original.status != JournalStatus.POSTED:
                raise ValueError(f"Cannot reverse journal with status {original.status.value}")
            if original.reversal_journal_id:
                raise ValueError(f"Journal already reversed by {original.reversal_journal_id}")

            period_str = command.period
            if not period_str:
                period_str = f"{original.period.year}-{original.period.month:02d}"
            period_status = await self._period_service.get_period_status(
                original.legal_entity_id, period_str
            )
            if period_status not in ("OPEN", "PRE_CLOSING"):
                raise ValueError(f"Period {period_str} is not open for reversal")

            reversal_lines = []
            for line in original.lines:
                reversal_lines.append(
                    JournalLineRequestDTO(
                        account_code=line.account_code.value
                        if hasattr(line.account_code, "value")
                        else str(line.account_code),
                        debit=line.credit,
                        credit=line.debit,
                        description=f"REVERSAL: {line.description}"
                        if command.include_original_description
                        else line.description,
                        cost_center=line.cost_center,
                        department=line.department,
                        tax_code=line.tax_code,
                        project_code=line.project_code,
                        auxiliary_1=line.auxiliary_1,
                        auxiliary_2=line.auxiliary_2,
                    )
                )

            description = f"Reversal of {original.journal_number.value} - {command.reason}"
            if command.include_original_description and original.description:
                description = f"{description} (Original: {original.description})"

            request = JournalEntryRequestDTO(
                legal_entity_id=original.legal_entity_id,
                journal_date=command.reversal_date,
                period=period_str,
                description=description,
                lines=reversal_lines,
                source_system="reversal",
                idempotency_key=command.idempotency_key,
                reference_number=original.journal_number.value,
                original_journal_id=command.original_journal_id,
            )

            async def _execute():
                result = await self._journal_service.reverse_journal(
                    original_journal_id=command.original_journal_id,
                    request=request,
                    user_id=command.user_id,
                    reason=command.reason,
                    correlation_id=command.correlation_id,
                )
                return result

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
                    "original_journal_id": str(command.original_journal_id),
                    "reversal_journal_id": str(result.id) if result else None,
                    "reversal_number": result.journal_number if result else None,
                    "status": "REVERSED",
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"Reverse journal use case failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="REVERSAL_ERROR"
            )

    def get_stats(self) -> dict[str, int]:
        return self._stats


async def reverse_journal_handler(
    command: Command, use_case: ReverseJournalUseCase
) -> CommandResult:
    if not isinstance(command, ReverseJournalCommand):
        raise TypeError(f"Expected ReverseJournalCommand, got {type(command)}")
    return await use_case.execute(command)


__all__ = ["ReverseJournalCommand", "ReverseJournalUseCase", "reverse_journal_handler"]
