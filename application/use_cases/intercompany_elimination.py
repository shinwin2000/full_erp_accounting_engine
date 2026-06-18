#!/usr/bin/env python3

"""
Module: intercompany_elimination.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk eliminasi transaksi intercompany dalam konsolidasi laporan keuangan.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from application.commands_cqrs.command_bus_unified import Command, CommandResult
from application.service_layer.service_consolidation import ConsolidationService
from application.service_layer.service_journal import JournalService
from application.service_layer.service_ledger import LedgerService
from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


class IntercompanyEliminationCommand(Command):
    """Command untuk eliminasi intercompany."""

    __slots__ = (
        "auto_eliminate",
        "dry_run",
        "entity_ids",
        "group_entity_id",
        "period_end_date",
        "post_elimination_journal",
    )

    def __init__(
        self,
        group_entity_id: UUID,
        period_end_date: date,
        entity_ids: list[UUID],
        auto_eliminate: bool = True,
        post_elimination_journal: bool = True,
        dry_run: bool = False,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="IntercompanyEliminationCommand",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        self.group_entity_id = group_entity_id
        self.period_end_date = period_end_date
        self.entity_ids = entity_ids
        self.auto_eliminate = auto_eliminate
        self.post_elimination_journal = post_elimination_journal
        self.dry_run = dry_run

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "group_entity_id": str(self.group_entity_id),
                "period_end_date": self.period_end_date.isoformat(),
                "entity_ids": [str(eid) for eid in self.entity_ids],
                "auto_eliminate": self.auto_eliminate,
                "post_elimination_journal": self.post_elimination_journal,
                "dry_run": self.dry_run,
            }
        )
        return data


class IntercompanyTransaction:
    def __init__(
        self,
        from_entity_id: UUID,
        to_entity_id: UUID,
        transaction_type: str,
        account_code: str,
        amount: Decimal,
        transaction_date: date,
        reference: str,
    ):
        self.from_entity_id = from_entity_id
        self.to_entity_id = to_entity_id
        self.transaction_type = transaction_type
        self.account_code = account_code
        self.amount = amount
        self.transaction_date = transaction_date
        self.reference = reference


class EliminationEntry:
    def __init__(
        self,
        account_code: str,
        debit: Decimal,
        credit: Decimal,
        description: str,
        from_entity_id: UUID | None = None,
        to_entity_id: UUID | None = None,
    ):
        self.account_code = account_code
        self.debit = debit
        self.credit = credit
        self.description = description
        self.from_entity_id = from_entity_id
        self.to_entity_id = to_entity_id


class IntercompanyEliminationResult:
    def __init__(
        self,
        transactions_identified: list[IntercompanyTransaction],
        elimination_entries: list[EliminationEntry],
        journal_id: UUID | None,
        unmatched_balances: list[dict[str, Any]],
        message: str,
    ):
        self.transactions_identified = transactions_identified
        self.elimination_entries = elimination_entries
        self.journal_id = journal_id
        self.unmatched_balances = unmatched_balances
        self.message = message


class IntercompanyEliminationUseCase:
    """
    Use case untuk eliminasi intercompany.
    """

    def __init__(
        self,
        consolidation_service: ConsolidationService,
        ledger_service: LedgerService,
        journal_service: JournalService,
        sealed_gate: SealedGate | None = None,
    ):
        self._consolidation_service = consolidation_service
        self._ledger_service = ledger_service
        self._journal_service = journal_service
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: IntercompanyEliminationCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            transactions = await self._identify_intercompany_transactions(
                command.entity_ids, command.period_end_date
            )
            elimination_entries = []
            if command.auto_eliminate:
                elimination_entries = self._create_elimination_entries(transactions)
            unmatched = await self._check_unmatched_balances(
                command.entity_ids, command.period_end_date
            )

            if command.dry_run:
                return CommandResult.success(
                    command_id=command.command_id,
                    data={
                        "dry_run": True,
                        "transactions_count": len(transactions),
                        "elimination_entries_count": len(elimination_entries),
                        "unmatched_balances": unmatched,
                    },
                )

            journal_id = None
            if command.post_elimination_journal and elimination_entries:
                journal_id = await self._post_elimination_journal(
                    command.group_entity_id,
                    elimination_entries,
                    command.period_end_date,
                    command.user_id,
                    command.correlation_id,
                )

            result = IntercompanyEliminationResult(
                transactions_identified=transactions,
                elimination_entries=elimination_entries,
                journal_id=journal_id,
                unmatched_balances=unmatched,
                message=f"Eliminated {len(elimination_entries)} entries from {len(transactions)} transactions",
            )

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "transactions_count": len(result.transactions_identified),
                    "elimination_entries_count": len(result.elimination_entries),
                    "journal_id": str(result.journal_id) if result.journal_id else None,
                    "unmatched_balances": result.unmatched_balances,
                    "message": result.message,
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"Intercompany elimination failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id,
                error=str(e),
                error_code="INTERCOMPANY_ELIMINATION_ERROR",
            )

    async def _identify_intercompany_transactions(
        self, entity_ids: list[UUID], as_of_date: date
    ) -> list[IntercompanyTransaction]:
        transactions = []
        for from_ent in entity_ids:
            for to_ent in entity_ids:
                if from_ent == to_ent:
                    continue
                sales = await self._ledger_service.get_intercompany_sales(
                    from_ent, to_ent, as_of_date
                )
                for sale in sales:
                    transactions.append(
                        IntercompanyTransaction(
                            from_entity_id=from_ent,
                            to_entity_id=to_ent,
                            transaction_type="SALES",
                            account_code="4-1000",
                            amount=sale.amount,
                            transaction_date=sale.date,
                            reference=sale.invoice_number,
                        )
                    )
                purchases = await self._ledger_service.get_intercompany_purchases(
                    from_ent, to_ent, as_of_date
                )
                for purchase in purchases:
                    transactions.append(
                        IntercompanyTransaction(
                            from_entity_id=from_ent,
                            to_entity_id=to_ent,
                            transaction_type="PURCHASE",
                            account_code="5-1000",
                            amount=purchase.amount,
                            transaction_date=purchase.date,
                            reference=purchase.invoice_number,
                        )
                    )
        return transactions

    def _create_elimination_entries(
        self, transactions: list[IntercompanyTransaction]
    ) -> list[EliminationEntry]:
        entries = []
        grouped = {}
        for tx in transactions:
            key = (tx.from_entity_id, tx.to_entity_id, tx.account_code)
            if key not in grouped:
                grouped[key] = Decimal("0")
            if tx.transaction_type == "SALES":
                grouped[key] += tx.amount
            elif tx.transaction_type == "PURCHASE":
                grouped[key] -= tx.amount
            else:
                grouped[key] += tx.amount
        for (from_ent, to_ent, acct), net_amount in grouped.items():
            if net_amount != 0:
                if net_amount > 0:
                    entries.append(
                        EliminationEntry(
                            account_code=acct,
                            debit=net_amount,
                            credit=Decimal("0"),
                            description=f"Elimination intercompany sales {from_ent} -> {to_ent}",
                            from_entity_id=from_ent,
                            to_entity_id=to_ent,
                        )
                    )
                else:
                    entries.append(
                        EliminationEntry(
                            account_code=acct,
                            debit=Decimal("0"),
                            credit=-net_amount,
                            description=f"Elimination intercompany purchase {from_ent} -> {to_ent}",
                            from_entity_id=from_ent,
                            to_entity_id=to_ent,
                        )
                    )
        return entries

    async def _check_unmatched_balances(
        self, entity_ids: list[UUID], as_of_date: date
    ) -> list[dict[str, Any]]:
        unmatched = []
        for from_ent in entity_ids:
            for to_ent in entity_ids:
                if from_ent == to_ent:
                    continue
                ar_balance = await self._ledger_service.get_account_balance(
                    from_ent, "1-1100", as_of_date.year, as_of_date.month, as_of_date
                )
                ap_balance = await self._ledger_service.get_account_balance(
                    to_ent, "2-2000", as_of_date.year, as_of_date.month, as_of_date
                )
                if ar_balance != ap_balance:
                    unmatched.append(
                        {
                            "from_entity": str(from_ent),
                            "to_entity": str(to_ent),
                            "ar_balance": float(ar_balance),
                            "ap_balance": float(ap_balance),
                            "difference": float(ar_balance - ap_balance),
                        }
                    )
        return unmatched

    async def _post_elimination_journal(
        self,
        group_entity_id: UUID,
        elimination_entries: list[EliminationEntry],
        journal_date: date,
        user_id: UUID,
        correlation_id: str | None,
    ) -> UUID:
        lines = []
        for entry in elimination_entries:
            lines.append(
                {
                    "account_code": entry.account_code,
                    "debit": entry.debit,
                    "credit": entry.credit,
                    "description": entry.description,
                }
            )
        journal_id = await self._journal_service.post_journal(
            legal_entity_id=group_entity_id,
            journal_date=journal_date,
            period=f"{journal_date.year}-{journal_date.month:02d}",
            description=f"Intercompany elimination for period {journal_date}",
            lines=lines,
            source_system="consolidation",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        return journal_id

    def get_stats(self) -> dict[str, int]:
        return self._stats


async def intercompany_elimination_handler(
    command: Command, use_case: IntercompanyEliminationUseCase
) -> CommandResult:
    if not isinstance(command, IntercompanyEliminationCommand):
        raise TypeError(f"Expected IntercompanyEliminationCommand, got {type(command)}")
    return await use_case.execute(command)


__all__ = [
    "EliminationEntry",
    "IntercompanyEliminationCommand",
    "IntercompanyEliminationResult",
    "IntercompanyEliminationUseCase",
    "IntercompanyTransaction",
    "intercompany_elimination_handler",
]
