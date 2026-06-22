#!/usr/bin/env python3

"""
Module: forex_revaluation.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk revaluasi mata uang asing (foreign exchange revaluation) pada akhir periode.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any
from uuid import UUID

from application.commands_cqrs.command_bus_unified import BaseCommand, CommandResult
from application.service_layer.service_forex import ForexService
from application.service_layer.service_journal import JournalService
from application.service_layer.service_ledger import LedgerService
from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


class ForexRevaluationCommand(BaseCommand):
    """Command untuk revaluasi mata uang asing."""

    __slots__ = (
        "as_of_date",
        "dry_run",
        "functional_currency",
        "include_ar_ap",
        "include_cash_and_bank",
        "include_loans",
        "legal_entity_id",
        "post_to_gl",
        "revaluation_method",
    )

    def __init__(
        self,
        legal_entity_id: UUID,
        as_of_date: date,
        functional_currency: str = "IDR",
        revaluation_method: str = "CURRENT_RATE",
        include_cash_and_bank: bool = True,
        include_ar_ap: bool = True,
        include_loans: bool = True,
        post_to_gl: bool = True,
        dry_run: bool = False,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="ForexRevaluationCommand", user_id=user_id, correlation_id=correlation_id
        )
        self.legal_entity_id = legal_entity_id
        self.as_of_date = as_of_date
        self.functional_currency = functional_currency
        self.revaluation_method = revaluation_method
        self.include_cash_and_bank = include_cash_and_bank
        self.include_ar_ap = include_ar_ap
        self.include_loans = include_loans
        self.post_to_gl = post_to_gl
        self.dry_run = dry_run

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "legal_entity_id": str(self.legal_entity_id),
                "as_of_date": self.as_of_date.isoformat(),
                "functional_currency": self.functional_currency,
                "revaluation_method": self.revaluation_method,
                "include_cash_and_bank": self.include_cash_and_bank,
                "include_ar_ap": self.include_ar_ap,
                "include_loans": self.include_loans,
                "post_to_gl": self.post_to_gl,
                "dry_run": self.dry_run,
            }
        )
        return data


class RevaluationEntry:
    def __init__(
        self,
        account_id: UUID,
        account_code: str,
        currency: str,
        original_amount_fc: Decimal,
        original_amount_idr: Decimal,
        current_rate: Decimal,
        revalued_amount_idr: Decimal,
        gain_loss: Decimal,
        journal_line_type: str,
    ):
        self.account_id = account_id
        self.account_code = account_code
        self.currency = currency
        self.original_amount_fc = original_amount_fc
        self.original_amount_idr = original_amount_idr
        self.current_rate = current_rate
        self.revalued_amount_idr = revalued_amount_idr
        self.gain_loss = gain_loss
        self.journal_line_type = journal_line_type


class ForexRevaluationResult:
    def __init__(
        self,
        entries: list[RevaluationEntry],
        total_gain: Decimal,
        total_loss: Decimal,
        journal_id: UUID | None,
        rates_used: dict[str, Decimal],
        message: str,
    ):
        self.entries = entries
        self.total_gain = total_gain
        self.total_loss = total_loss
        self.journal_id = journal_id
        self.rates_used = rates_used
        self.message = message


class ForexRevaluationUseCase:
    """
    Use case untuk revaluasi mata uang asing.
    """

    def __init__(
        self,
        forex_service: ForexService,
        ledger_service: LedgerService,
        journal_service: JournalService,
        sealed_gate: SealedGate | None = None,
    ):
        self._forex_service = forex_service
        self._ledger_service = ledger_service
        self._journal_service = journal_service
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: ForexRevaluationCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            currencies = ["USD", "EUR", "SGD", "JPY", "CNY"]
            rates = {}
            for curr in currencies:
                rate = await self._forex_service.get_exchange_rate(
                    from_currency=curr,
                    to_currency=command.functional_currency,
                    as_of_date=command.as_of_date,
                )
                if rate:
                    rates[curr] = rate
                else:
                    rates[curr] = Decimal("15000") if curr == "USD" else Decimal("1")

            entries = []
            total_gain = Decimal("0")
            total_loss = Decimal("0")

            if command.include_cash_and_bank:
                bank_accounts = await self._ledger_service.get_bank_accounts_foreign_currency(
                    command.legal_entity_id
                )
                for acc in bank_accounts:
                    reval = await self._revalue_account(
                        acc, rates, command.functional_currency, command.as_of_date
                    )
                    if reval:
                        entries.append(reval)
                        if reval.gain_loss > 0:
                            total_gain += reval.gain_loss
                        else:
                            total_loss += abs(reval.gain_loss)

            if command.include_ar_ap:
                ar_invoices = await self._ledger_service.get_ar_invoices_foreign_currency(
                    command.legal_entity_id, command.as_of_date
                )
                for inv in ar_invoices:
                    reval = await self._revalue_account(
                        inv, rates, command.functional_currency, command.as_of_date
                    )
                    if reval:
                        entries.append(reval)
                        if reval.gain_loss > 0:
                            total_gain += reval.gain_loss
                        else:
                            total_loss += abs(reval.gain_loss)

                ap_invoices = await self._ledger_service.get_ap_invoices_foreign_currency(
                    command.legal_entity_id, command.as_of_date
                )
                for inv in ap_invoices:
                    reval = await self._revalue_account(
                        inv, rates, command.functional_currency, command.as_of_date
                    )
                    if reval:
                        entries.append(reval)
                        if reval.gain_loss > 0:
                            total_gain += reval.gain_loss
                        else:
                            total_loss += abs(reval.gain_loss)

            if command.include_loans:
                loans = await self._ledger_service.get_loans_foreign_currency(
                    command.legal_entity_id, command.as_of_date
                )
                for loan in loans:
                    reval = await self._revalue_account(
                        loan, rates, command.functional_currency, command.as_of_date
                    )
                    if reval:
                        entries.append(reval)
                        if reval.gain_loss > 0:
                            total_gain += reval.gain_loss
                        else:
                            total_loss += abs(reval.gain_loss)

            if command.dry_run:
                return CommandResult.success(
                    command_id=command.command_id,
                    data={
                        "dry_run": True,
                        "entries_count": len(entries),
                        "total_gain": float(total_gain),
                        "total_loss": float(total_loss),
                        "rates_used": {k: float(v) for k, v in rates.items()},
                        "message": "Forex revaluation dry run completed",
                    },
                )

            journal_id = None
            if command.post_to_gl and entries:
                journal_id = await self._post_revaluation_journal(
                    command.legal_entity_id,
                    entries,
                    command.as_of_date,
                    command.user_id,
                    command.correlation_id,
                )

            result = ForexRevaluationResult(
                entries=entries,
                total_gain=total_gain,
                total_loss=total_loss,
                journal_id=journal_id,
                rates_used=rates,
                message=f"Forex revaluation completed with net loss/gain of {total_gain - total_loss}",
            )

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "total_gain": float(result.total_gain),
                    "total_loss": float(result.total_loss),
                    "net_effect": float(result.total_gain - result.total_loss),
                    "journal_id": str(result.journal_id) if result.journal_id else None,
                    "entries_count": len(result.entries),
                    "rates_used": {k: float(v) for k, v in rates.items()},
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"Forex revaluation failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="FOREX_REVALUATION_ERROR"
            )

    async def _revalue_account(
        self,
        account_obj: Any,
        rates: dict[str, Decimal],
        functional_currency: str,
        as_of_date: date,
    ) -> RevaluationEntry | None:
        if account_obj.currency == functional_currency:
            return None
        rate = rates.get(account_obj.currency)
        if not rate:
            return None
        original_fc = account_obj.balance_fc
        original_idr = account_obj.balance_idr
        revalued_idr = (original_fc * rate).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        gain_loss = revalued_idr - original_idr
        journal_line_type = "GAIN" if gain_loss > 0 else "LOSS"
        return RevaluationEntry(
            account_id=account_obj.id,
            account_code=account_obj.account_code,
            currency=account_obj.currency,
            original_amount_fc=original_fc,
            original_amount_idr=original_idr,
            current_rate=rate,
            revalued_amount_idr=revalued_idr,
            gain_loss=gain_loss,
            journal_line_type=journal_line_type,
        )

    async def _post_revaluation_journal(
        self,
        legal_entity_id: UUID,
        entries: list[RevaluationEntry],
        posting_date: date,
        user_id: UUID,
        correlation_id: str | None,
    ) -> UUID:
        gain_account = "4-4000"
        loss_account = "5-5500"
        lines = []
        for entry in entries:
            if entry.gain_loss > 0:
                lines.append(
                    {
                        "account_code": gain_account,
                        "debit": Decimal("0"),
                        "credit": entry.gain_loss,
                        "description": f"Forex gain on {entry.account_code} ({entry.currency})",
                    }
                )
            else:
                lines.append(
                    {
                        "account_code": loss_account,
                        "debit": abs(entry.gain_loss),
                        "credit": Decimal("0"),
                        "description": f"Forex loss on {entry.account_code} ({entry.currency})",
                    }
                )
        if not lines:
            raise ValueError("No revaluation entries to post")
        journal_id = await self._journal_service.post_journal(
            legal_entity_id=legal_entity_id,
            journal_date=posting_date,
            period=f"{posting_date.year}-{posting_date.month:02d}",
            description=f"Foreign currency revaluation as of {posting_date}",
            lines=lines,
            source_system="forex",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        return journal_id

    def get_stats(self) -> dict[str, int]:
        return self._stats


# ============================================================================
# Handler dengan dependency injection
# ============================================================================


async def forex_revaluation_handler(
    command: BaseCommand, use_case: ForexRevaluationUseCase
) -> CommandResult:
    if not isinstance(command, ForexRevaluationCommand):
        raise TypeError(f"Expected ForexRevaluationCommand, got {type(command)}")
    return await use_case.execute(command)


__all__ = [
    "ForexRevaluationCommand",
    "ForexRevaluationResult",
    "ForexRevaluationUseCase",
    "RevaluationEntry",
    "forex_revaluation_handler",
]
