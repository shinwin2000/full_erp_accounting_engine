#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Module: post_closing_journal.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk posting jurnal penutup (closing journal) pada akhir periode.
    Dilengkapi dengan idempotensi.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from functools import wraps
from typing import Any
from uuid import UUID

from application.commands_cqrs.command_bus_unified import BaseCommand, CommandResult
from application.dto_objects.journal_request import JournalEntryRequestDTO, JournalLineRequestDTO
from application.service_layer.service_coa import COAService
from application.service_layer.service_fiscal_period import FiscalPeriodService
from application.service_layer.service_journal import JournalService
from domain.fiscal_period.aggregate_root import PeriodStatus
from kernel.sealed_gate import SealedGate
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)

# ============================================================================
# IDEMPOTENCY MANAGER
# ============================================================================

class IdempotencyManager:
    """
    Simple in-memory idempotency manager for this use case module.
    TTL 24 jam.
    """

    def __init__(self):
        self._storage: dict[str, tuple[str, datetime]] = {}
        self._ttl_seconds = 86400

    def _get_key(self, idempotency_key: str, method_name: str) -> str:
        raw = f"{method_name}:{idempotency_key}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_cached_result(self, idempotency_key: str, method_name: str) -> dict[str, Any] | None:
        storage_key = self._get_key(idempotency_key, method_name)
        entry = self._storage.get(storage_key)
        if entry is None:
            return None
        result_json, timestamp = entry
        if (datetime.now(timezone.utc) - timestamp).total_seconds() > self._ttl_seconds:
            del self._storage[storage_key]
            return None
        try:
            return json.loads(result_json)
        except json.JSONDecodeError:
            return None

    def cache_result(self, idempotency_key: str, method_name: str, result: dict[str, Any]) -> None:
        storage_key = self._get_key(idempotency_key, method_name)
        try:
            result_json = json.dumps(result, default=str)
        except TypeError:
            result_json = json.dumps({"result": str(result)}, default=str)
        self._storage[storage_key] = (result_json, datetime.now(timezone.utc))


_idempotency_manager = IdempotencyManager()


def transactional(method):
    @wraps(method)
    async def wrapper(self, *args, **kwargs):
        async with self._uow:
            return await method(self, *args, **kwargs)
    return wrapper


class PostClosingJournalCommand(BaseCommand):
    __slots__ = (
        "closing_date",
        "idempotency_key",
        "include_income_statement_accounts",
        "include_withdrawal_accounts",
        "legal_entity_id",
        "period_month",
        "period_year",
    )

    def __init__(
        self,
        legal_entity_id: UUID,
        period_year: int,
        period_month: int,
        closing_date: date,
        include_income_statement_accounts: bool = True,
        include_withdrawal_accounts: bool = True,
        idempotency_key: str | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="PostClosingJournalCommand",
            user_id=user_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        self.legal_entity_id = legal_entity_id
        self.period_year = period_year
        self.period_month = period_month
        self.closing_date = closing_date
        self.include_income_statement_accounts = include_income_statement_accounts
        self.include_withdrawal_accounts = include_withdrawal_accounts

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "legal_entity_id": str(self.legal_entity_id),
                "period_year": self.period_year,
                "period_month": self.period_month,
                "closing_date": self.closing_date.isoformat(),
                "include_income_statement_accounts": self.include_income_statement_accounts,
                "include_withdrawal_accounts": self.include_withdrawal_accounts,
            }
        )
        return data


class PostClosingJournalUseCase:
    def __init__(
        self,
        journal_service: JournalService,
        fiscal_period_service: FiscalPeriodService,
        coa_service: COAService,
        ledger_repo: LedgerRepositoryPort,
        uow: UnitOfWorkPort,
        sealed_gate: SealedGate | None = None,
    ):
        self._journal_service = journal_service
        self._period_service = fiscal_period_service
        self._coa_service = coa_service
        self._ledger_repo = ledger_repo
        self._uow = uow
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    @transactional
    async def execute(self, command: PostClosingJournalCommand) -> CommandResult:
        self._stats["executed"] += 1
        period_str = f"{command.period_year}-{command.period_month:02d}"

        try:
            # ========== VALIDATION: Period must be OPEN ==========
            period = await self._period_service.get_period(
                command.legal_entity_id, command.period_year, command.period_month
            )
            if not period:
                raise ValueError(f"Period {period_str} does not exist")
            if period.status != PeriodStatus.OPEN.value:
                raise ValueError(
                    f"Cannot post closing journal: period {period_str} is {period.status}. "
                    "Period must be OPEN."
                )

            existing_closing = await self._journal_service.find_closing_journal(
                command.legal_entity_id, command.period_year, command.period_month
            )
            if existing_closing:
                raise ValueError(f"Closing journal already exists for period {period_str}")

            revenue_accounts = await self._coa_service.list_accounts(
                legal_entity_id=command.legal_entity_id, account_type="REVENUE", status="ACTIVE"
            )
            expense_accounts = await self._coa_service.list_accounts(
                legal_entity_id=command.legal_entity_id, account_type="EXPENSE", status="ACTIVE"
            )
            withdrawal_accounts = []
            if command.include_withdrawal_accounts:
                withdrawal_accounts = await self._coa_service.list_accounts(
                    legal_entity_id=command.legal_entity_id, account_type="EQUITY", status="ACTIVE"
                )
                withdrawal_accounts = [
                    acc for acc in withdrawal_accounts
                    if "PRIVE" in acc.name.upper() or "WITHDRAWAL" in acc.name.upper()
                ]

            revenue_balance = Decimal("0")
            for acc in revenue_accounts:
                revenue_balance += await self._ledger_repo.get_account_balance(
                    acc.id, command.period_year, command.period_month, as_of_date=command.closing_date
                )
            expense_balance = Decimal("0")
            for acc in expense_accounts:
                expense_balance += await self._ledger_repo.get_account_balance(
                    acc.id, command.period_year, command.period_month, as_of_date=command.closing_date
                )
            net_income = revenue_balance - expense_balance

            lines = []
            income_summary_account = "3-9999"
            retained_earnings_account = "3-1000"

            if command.include_income_statement_accounts:
                for acc in revenue_accounts:
                    bal = await self._ledger_repo.get_account_balance(
                        acc.id, command.period_year, command.period_month, as_of_date=command.closing_date
                    )
                    if bal != 0:
                        lines.append(JournalLineRequestDTO(
                            account_code=acc.account_code,
                            debit=bal if bal > 0 else Decimal("0"),
                            credit=Decimal("0") if bal > 0 else -bal,
                            description=f"Closing revenue {acc.name}",
                        ))
                        lines.append(JournalLineRequestDTO(
                            account_code=income_summary_account,
                            debit=Decimal("0") if bal > 0 else -bal,
                            credit=bal if bal > 0 else Decimal("0"),
                            description="Close revenue to income summary",
                        ))
                for acc in expense_accounts:
                    bal = await self._ledger_repo.get_account_balance(
                        acc.id, command.period_year, command.period_month, as_of_date=command.closing_date
                    )
                    if bal != 0:
                        lines.append(JournalLineRequestDTO(
                            account_code=acc.account_code,
                            debit=Decimal("0"),
                            credit=bal,
                            description=f"Closing expense {acc.name}",
                        ))
                        lines.append(JournalLineRequestDTO(
                            account_code=income_summary_account,
                            debit=bal,
                            credit=Decimal("0"),
                            description="Close expense to income summary",
                        ))
                if net_income != 0:
                    if net_income > 0:
                        lines.append(JournalLineRequestDTO(
                            account_code=income_summary_account,
                            debit=net_income,
                            credit=Decimal("0"),
                            description="Close income summary (net income)",
                        ))
                        lines.append(JournalLineRequestDTO(
                            account_code=retained_earnings_account,
                            debit=Decimal("0"),
                            credit=net_income,
                            description="Add net income to retained earnings",
                        ))
                    else:
                        loss = -net_income
                        lines.append(JournalLineRequestDTO(
                            account_code=income_summary_account,
                            debit=Decimal("0"),
                            credit=loss,
                            description="Close income summary (net loss)",
                        ))
                        lines.append(JournalLineRequestDTO(
                            account_code=retained_earnings_account,
                            debit=loss,
                            credit=Decimal("0"),
                            description="Record net loss to retained earnings",
                        ))

            if command.include_withdrawal_accounts:
                for acc in withdrawal_accounts:
                    bal = await self._ledger_repo.get_account_balance(
                        acc.id, command.period_year, command.period_month, as_of_date=command.closing_date
                    )
                    if bal != 0:
                        lines.append(JournalLineRequestDTO(
                            account_code=acc.account_code,
                            debit=Decimal("0"),
                            credit=bal,
                            description=f"Closing withdrawal {acc.name}",
                        ))
                        lines.append(JournalLineRequestDTO(
                            account_code=retained_earnings_account,
                            debit=bal,
                            credit=Decimal("0"),
                            description="Close withdrawal to retained earnings",
                        ))

            if not lines:
                raise ValueError("No closing entries needed (all balances zero)")

            request = JournalEntryRequestDTO(
                legal_entity_id=command.legal_entity_id,
                journal_date=command.closing_date,
                period=period_str,
                description=f"Closing entries for period {period_str}",
                lines=lines,
                source_system="closing",
                idempotency_key=command.idempotency_key,
            )

            async def _execute():
                return await self._journal_service.post_closing_journal(
                    request=request,
                    user_id=command.user_id,
                    period_year=command.period_year,
                    period_month=command.period_month,
                    correlation_id=command.correlation_id,
                )

            if self._sealed_gate:
                result = await self._sealed_gate.execute(
                    command_type=command.command_type,
                    command_id=command.command_id,
                    handler=_execute,
                )
            else:
                result = await _execute()

            await self._period_service.close_period(
                command.legal_entity_id, command.period_year, command.period_month, command.user_id
            )

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "journal_id": str(result.id) if result else None,
                    "period": period_str,
                    "net_income": float(net_income),
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"PostClosingJournal use case failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="CLOSING_JOURNAL_ERROR"
            )

    def get_stats(self) -> dict[str, int]:
        return self._stats


async def post_closing_journal_handler(
    command: BaseCommand,
    use_case: PostClosingJournalUseCase,
    idempotency_key: str | None = None,
) -> CommandResult:
    """
    Handler untuk PostClosingJournalCommand.
    Dilengkapi dengan idempotensi secara eksplisit.
    """
    if not isinstance(command, PostClosingJournalCommand):
        raise TypeError(f"Expected PostClosingJournalCommand, got {type(command)}")

    # Tentukan idempotency key
    key = idempotency_key or getattr(command, "idempotency_key", None)
    method_name = "post_closing_journal_handler"

    # Cek cache jika key ada
    if key is not None:
        cached = _idempotency_manager.get_cached_result(key, method_name)
        if cached is not None:
            logger.info("Idempotency hit for %s key=%s", method_name, key[:8])
            return CommandResult(
                command_id=getattr(command, "command_id", None),
                status=cached.get("status", "duplicate"),
                data=cached.get("data"),
                error=cached.get("error"),
                error_code=cached.get("error_code"),
            )

    # Validasi period status (juga dilakukan di use_case, tapi kita lakukan di sini
    # untuk mencegah penyimpanan hasil jika period tidak valid)
    period = await use_case._period_service.get_period(
        command.legal_entity_id, command.period_year, command.period_month
    )
    period_str = f"{command.period_year}-{command.period_month:02d}"
    if not period:
        raise ValueError(f"Period {period_str} does not exist")
    if period.status != PeriodStatus.OPEN.value:
        raise ValueError(
            f"Cannot post closing journal: period {period_str} is {period.status}. "
            "Period must be OPEN."
        )

    # Eksekusi use case
    result = await use_case.execute(command)

    # Simpan hasil jika key ada
    if key is not None:
        _idempotency_manager.cache_result(
            key,
            method_name,
            {
                "status": result.status,
                "data": result.data,
                "error": result.error,
                "error_code": result.error_code,
            }
        )

    return result


__all__ = ["PostClosingJournalCommand", "PostClosingJournalUseCase", "post_closing_journal_handler"]