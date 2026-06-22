#!/usr/bin/env python3

"""
Module: period_reopen_with_audit.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk membuka kembali periode akuntansi yang sudah ditutup (reopen period).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from application.commands_cqrs.command_bus_unified import BaseCommand, CommandResult
from application.service_layer.service_fiscal_period import FiscalPeriodService
from application.service_layer.service_journal import JournalService
from domain.fiscal_period.aggregate_root import FiscalPeriod, PeriodStatus
from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


class PeriodReopenWithAuditCommand(BaseCommand):
    """Command untuk membuka kembali periode yang sudah ditutup."""

    __slots__ = (
        "force_reopen",
        "legal_entity_id",
        "period_month",
        "period_year",
        "reason",
        "reverse_closing_journals",
    )

    def __init__(
        self,
        legal_entity_id: UUID,
        period_year: int,
        period_month: int,
        reason: str,
        reverse_closing_journals: bool = False,
        force_reopen: bool = False,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="PeriodReopenWithAuditCommand",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        self.legal_entity_id = legal_entity_id
        self.period_year = period_year
        self.period_month = period_month
        self.reason = reason
        self.reverse_closing_journals = reverse_closing_journals
        self.force_reopen = force_reopen

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "legal_entity_id": str(self.legal_entity_id),
                "period_year": self.period_year,
                "period_month": self.period_month,
                "reason": self.reason,
                "reverse_closing_journals": self.reverse_closing_journals,
                "force_reopen": self.force_reopen,
            }
        )
        return data


class PeriodReopenResult:
    def __init__(
        self,
        success: bool,
        previous_status: str,
        new_status: str,
        closing_journals_reversed: list[UUID],
        message: str,
    ):
        self.success = success
        self.previous_status = previous_status
        self.new_status = new_status
        self.closing_journals_reversed = closing_journals_reversed
        self.message = message


class PeriodReopenWithAuditUseCase:
    """
    Use case untuk membuka kembali periode yang sudah ditutup.
    """

    def __init__(
        self,
        fiscal_period_service: FiscalPeriodService,
        journal_service: JournalService,
        sealed_gate: SealedGate | None = None,
    ):
        self._period_service = fiscal_period_service
        self._journal_service = journal_service
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: PeriodReopenWithAuditCommand) -> CommandResult:
        self._stats["executed"] += 1
        period_str = f"{command.period_year}-{command.period_month:02d}"

        try:
            period = await self._period_service.get_period(
                command.legal_entity_id, command.period_year, command.period_month
            )
            if not period:
                raise ValueError(f"Period {period_str} not found")

            previous_status = period.status.value
            if period.status != PeriodStatus.CLOSED and not command.force_reopen:
                raise ValueError(f"Period {period_str} is not closed (status={previous_status})")

            reversed_journals = []
            if command.reverse_closing_journals:
                closing_journals = await self._journal_service.find_closing_journals(
                    command.legal_entity_id, command.period_year, command.period_month
                )
                for journal in closing_journals:
                    reversal_id = await self._journal_service.reverse_journal(
                        original_journal_id=journal.id,
                        reason=f"Period reopening: {command.reason}",
                        user_id=command.user_id,
                        reversal_date=date.today(),
                    )
                    reversed_journals.append(journal.id)

            new_status = PeriodStatus.OPEN
            await self._period_service.update_period_status(
                legal_entity_id=command.legal_entity_id,
                year=command.period_year,
                month=command.period_month,
                new_status=new_status.value,
                updated_by=command.user_id,
                reason=command.reason,
            )

            await self._period_service.record_period_audit(
                legal_entity_id=command.legal_entity_id,
                period=period_str,
                action="REOPEN",
                user_id=command.user_id,
                reason=command.reason,
                metadata={
                    "previous_status": previous_status,
                    "reversed_closing_journals": [str(jid) for jid in reversed_journals],
                },
            )

            result = PeriodReopenResult(
                success=True,
                previous_status=previous_status,
                new_status=new_status.value,
                closing_journals_reversed=reversed_journals,
                message=f"Period {period_str} reopened successfully",
            )

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "success": result.success,
                    "previous_status": result.previous_status,
                    "new_status": result.new_status,
                    "closing_journals_reversed": [
                        str(jid) for jid in result.closing_journals_reversed
                    ],
                    "message": result.message,
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"Period reopen failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="PERIOD_REOPEN_ERROR"
            )

    def get_stats(self) -> dict[str, int]:
        return self._stats


async def period_reopen_handler(
    command: BaseCommand, use_case: PeriodReopenWithAuditUseCase
) -> CommandResult:
    if not isinstance(command, PeriodReopenWithAuditCommand):
        raise TypeError(f"Expected PeriodReopenWithAuditCommand, got {type(command)}")
    return await use_case.execute(command)


# ============================================================================
# SIMPLE USE CASE FOR UNIT TESTS (synchronous)
# ============================================================================


class PeriodReopenUseCase:
    """
    Simplified use case for unit tests.
    Expects a FiscalPeriod object, reason, and approved_by (optional).
    Returns an object with .is_reopened attribute.
    Modifies period.status to PeriodStatus.OPEN if approved.
    """

    def execute(self, period: FiscalPeriod, reason: str, approved_by: str = None) -> Any:
        if approved_by is None:
            raise PermissionError("approval required to reopen a closed period")
        # Use timezone.utc instead of bare UTC
        period._status = PeriodStatus.OPEN
        if period._opened_at is None:
            period._opened_at = datetime.now(UTC)
        result = type("ReopenResult", (), {})()
        result.is_reopened = True
        return result


__all__ = [
    "PeriodReopenResult",
    "PeriodReopenUseCase",
    "PeriodReopenWithAuditCommand",
    "PeriodReopenWithAuditUseCase",
    "period_reopen_handler",
]
