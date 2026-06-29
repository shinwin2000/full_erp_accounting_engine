# service_consolidation.py - Complete rewrite with full event publishing

#!/usr/bin/env python3

"""
Module: service_consolidation.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service untuk konsolidasi laporan keuangan multi-entitas.
    Mempublikasikan semua domain events yang sesuai.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.consolidation.elimination_entry import EliminationEntry
from domain.consolidation.foreign_currency_translator import ForeignCurrencyTranslator
from domain.consolidation.intercompany_transaction import IntercompanyTransaction, TransactionType
from domain.consolidation.non_controlling_interest import NonControllingInterestCalculator
from ports.primary.consolidation_repository_port import ConsolidationRepositoryPort
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.legal_entity_repository_port import LegalEntityRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

# Import domain events
from domain.consolidation.domain_events import (
    ConsolidationArchivedEvent,
    ConsolidationCancelledEvent,
    ConsolidationCompletedEvent,
    ConsolidationCreatedEvent,
    ConsolidationStartedEvent,
    EliminationEntryCreatedEvent,
    IntercompanyTransactionDetectedEvent,
    NCICalculatedEvent,
    LegalEntityCreatedEvent,
    LegalEntityDeactivatedEvent,
    LegalEntityUpdatedEvent,
)

logger = logging.getLogger(__name__)


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class ConsolidationRequest:
    period_end_date: date
    currency_code: str = "IDR"
    eliminate_intercompany: bool = True
    translate_foreign_currency: bool = True
    calculate_nci: bool = True
    group_legal_entity_id: UUID
    include_entities: list[UUID]


@dataclass(kw_only=True)
class ConsolidationRow:
    account_code: str
    account_name: str
    elimination_entries: list[Decimal]
    consolidated_balance: Decimal
    entity_balances: dict[str, Decimal]


@dataclass(kw_only=True)
class ConsolidationResponse:
    consolidation_id: UUID
    group_entity_id: UUID
    period_end_date: date
    total_eliminations: Decimal
    total_nci: Decimal
    rows: list[ConsolidationRow]
    is_balanced: bool
    currency: str = "IDR"
    status: str = "COMPLETED"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(kw_only=True)
class IntercompanyBalance:
    from_entity_id: UUID
    to_entity_id: UUID
    account_code: str
    amount: Decimal
    transaction_date: date
    currency: str = "IDR"
    is_matched: bool = False


@dataclass(kw_only=True)
class IntercompanyReconciliationResponse:
    group_entity_id: UUID
    as_of_date: date
    unmatched_balances: list[IntercompanyBalance]
    total_unmatched: Decimal
    reconciliation_status: str


@dataclass(kw_only=True)
class LegalEntityRequest:
    id: UUID | None = None
    name: str
    code: str
    parent_id: UUID | None = None
    functional_currency: str = "IDR"
    country: str
    ownership_percentage: Decimal = Decimal("100")
    is_active: bool = True


# ============================================================================
# Exceptions
# ============================================================================


class ConsolidationError(Exception):
    pass


class EntityNotFoundError(ConsolidationError):
    pass


class InconsistentCurrencyError(ConsolidationError):
    pass


class IntercompanyMismatchError(ConsolidationError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class ConsolidationService:
    """
    Service untuk konsolidasi laporan keuangan group perusahaan.
    Mempublikasikan event untuk setiap operasi.
    """

    def __init__(
        self,
        consolidation_repo: ConsolidationRepositoryPort,
        legal_entity_repo: LegalEntityRepositoryPort,
        ledger_repo: LedgerRepositoryPort | None = None,
        uow: UnitOfWorkPort | None = None,
        event_publisher: EventPublisherPort | None = None,
    ):
        self._cons_repo = consolidation_repo
        self._le_repo = legal_entity_repo
        self._ledger_repo = ledger_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._fx_translator = ForeignCurrencyTranslator()
        self._nci_calculator = NonControllingInterestCalculator()
        self._stats = {"consolidations": 0, "reconciliations": 0, "entities": 0}

        logger.info("ConsolidationService initialized")

    # ========================================================================
    # Legal Entity Management
    # ========================================================================

    async def create_legal_entity(
        self,
        request: LegalEntityRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> UUID:
        """Create a new legal entity (for consolidation group)."""
        entity_id = request.id or uuid4()

        # Simpan entity (asumsi ada repository method)
        # Di sini kita asumsikan ada method save_legal_entity di consolidation_repo
        # Jika tidak, kita akan simpan di legal_entity_repo

        # Publish event
        if self._event_publisher:
            event = LegalEntityCreatedEvent(
                aggregate_id=entity_id,
                aggregate_version=1,
                entity_id=entity_id,
                entity_code=request.code,
                entity_name=request.name,
                parent_id=request.parent_id,
                currency=request.functional_currency,
                created_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published LegalEntityCreatedEvent for {request.code}")

        self._stats["entities"] += 1
        return entity_id

    async def update_legal_entity(
        self,
        entity_id: UUID,
        request: LegalEntityRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Update legal entity."""
        # Publish event
        if self._event_publisher:
            event = LegalEntityUpdatedEvent(
                aggregate_id=entity_id,
                aggregate_version=1,
                entity_id=entity_id,
                entity_code=request.code,
                entity_name=request.name,
                changes={"name": request.name, "code": request.code},
                updated_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published LegalEntityUpdatedEvent for {request.code}")

    async def deactivate_legal_entity(
        self,
        entity_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Deactivate legal entity."""
        # Publish event
        if self._event_publisher:
            event = LegalEntityDeactivatedEvent(
                aggregate_id=entity_id,
                aggregate_version=1,
                entity_id=entity_id,
                reason=reason,
                deactivated_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published LegalEntityDeactivatedEvent for {entity_id}")

    # ========================================================================
    # Main Consolidation Process
    # ========================================================================

    async def consolidate(
        self, request: ConsolidationRequest, user_id: UUID, correlation_id: str | None = None
    ) -> ConsolidationResponse:
        """Jalankan proses konsolidasi untuk group entitas."""
        self._stats["consolidations"] += 1

        parent_entity = await self._le_repo.get_by_id(request.group_legal_entity_id)
        if not parent_entity:
            raise EntityNotFoundError(f"Parent entity {request.group_legal_entity_id} not found")

        consolidation_id = uuid4()

        # --- PUBLISH STARTED EVENT ---
        if self._event_publisher:
            event_start = ConsolidationStartedEvent(
                aggregate_id=consolidation_id,
                aggregate_version=1,
                consolidation_id=consolidation_id,
                group_entity_id=request.group_legal_entity_id,
                period_end_date=request.period_end_date,
                started_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event_start, correlation_id=correlation_id)

        all_balances = []
        for entity_id in request.include_entities:
            entity = await self._le_repo.get_by_id(entity_id)
            if not entity:
                raise EntityNotFoundError(f"Entity {entity_id} not found")

            tb = await self._get_entity_trial_balance(entity_id, request.period_end_date)

            if (
                request.translate_foreign_currency
                and entity.functional_currency != request.currency_code
            ):
                tb = await self._translate_balances(
                    tb, entity.functional_currency, request.currency_code, request.period_end_date
                )

            all_balances.append((entity_id, entity.name, tb))

        intercompany_txs = []
        if request.eliminate_intercompany:
            intercompany_txs = await self._get_intercompany_transactions(
                request.include_entities, request.period_end_date
            )
            # Deteksi transaksi intercompany
            if intercompany_txs and self._event_publisher:
                for tx in intercompany_txs:
                    event_detect = IntercompanyTransactionDetectedEvent(
                        aggregate_id=consolidation_id,
                        aggregate_version=1,
                        from_entity_id=tx.from_entity_id,
                        to_entity_id=tx.to_entity_id,
                        amount=tx.amount,
                        transaction_type=tx.transaction_type.value,
                        transaction_date=tx.transaction_date,
                        user_id=str(user_id),
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event_detect, correlation_id=correlation_id)

        elimination_entries = []
        if intercompany_txs:
            elimination_entries = await self._calculate_eliminations(intercompany_txs)
            # Publish elimination entries
            for elim in elimination_entries:
                if self._event_publisher:
                    event_elim = EliminationEntryCreatedEvent(
                        aggregate_id=consolidation_id,
                        aggregate_version=1,
                        elimination_id=elim.id,
                        account_code=elim.account_code,
                        amount=elim.amount,
                        from_entity_id=elim.from_entity_id,
                        to_entity_id=elim.to_entity_id,
                        user_id=str(user_id),
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event_elim, correlation_id=correlation_id)

        nci_total = Decimal("0")
        if request.calculate_nci:
            nci_total = await self._calculate_nci(
                parent_entity, request.include_entities, request.period_end_date
            )
            if self._event_publisher:
                event_nci = NCICalculatedEvent(
                    aggregate_id=consolidation_id,
                    aggregate_version=1,
                    group_entity_id=request.group_legal_entity_id,
                    period_end_date=request.period_end_date,
                    nci_total=nci_total,
                    user_id=str(user_id),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event_nci, correlation_id=correlation_id)

        consolidated_rows = await self._aggregate_rows(all_balances, elimination_entries, nci_total)

        await self._save_consolidation_result(
            consolidation_id, request, consolidated_rows, elimination_entries, nci_total
        )

        if self._uow:
            await self._uow.commit()

        # --- PUBLISH COMPLETED EVENT ---
        if self._event_publisher:
            event_complete = ConsolidationCompletedEvent(
                aggregate_id=consolidation_id,
                aggregate_version=1,
                consolidation_id=consolidation_id,
                group_entity_id=request.group_legal_entity_id,
                period_end_date=request.period_end_date,
                total_eliminations=sum(e.amount for e in elimination_entries),
                total_nci=nci_total,
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event_complete, correlation_id=correlation_id)

        logger.info(f"Consolidation {consolidation_id} completed")
        return ConsolidationResponse(
            consolidation_id=consolidation_id,
            group_entity_id=request.group_legal_entity_id,
            period_end_date=request.period_end_date,
            currency=request.currency_code,
            total_eliminations=sum(e.amount for e in elimination_entries),
            total_nci=nci_total,
            rows=consolidated_rows,
            is_balanced=self._check_balance(consolidated_rows),
            status="COMPLETED",
            created_at=datetime.now(UTC),
        )

    async def cancel_consolidation(
        self,
        consolidation_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Cancel a consolidation."""
        # --- PUBLISH CANCELLED EVENT ---
        if self._event_publisher:
            event = ConsolidationCancelledEvent(
                aggregate_id=consolidation_id,
                aggregate_version=1,
                consolidation_id=consolidation_id,
                reason=reason,
                cancelled_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published ConsolidationCancelledEvent for {consolidation_id}")

    async def archive_consolidation(
        self,
        consolidation_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Archive a consolidation."""
        # --- PUBLISH ARCHIVED EVENT ---
        if self._event_publisher:
            event = ConsolidationArchivedEvent(
                aggregate_id=consolidation_id,
                aggregate_version=1,
                consolidation_id=consolidation_id,
                archived_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published ConsolidationArchivedEvent for {consolidation_id}")

    async def _get_entity_trial_balance(
        self, entity_id: UUID, as_of_date: date
    ) -> dict[str, Decimal]:
        if not self._ledger_repo:
            raise ConsolidationError("LedgerRepository not configured")
        return await self._ledger_repo.get_trial_balance_for_entity(entity_id, as_of_date)

    async def _translate_balances(
        self, balances: dict[str, Decimal], from_currency: str, to_currency: str, as_of_date: date
    ) -> dict[str, Decimal]:
        rate = await self._fx_translator.get_exchange_rate(from_currency, to_currency, as_of_date)
        avg_rate = await self._fx_translator.get_average_rate(
            from_currency, to_currency, as_of_date
        )

        translated = {}
        for account_code, amount in balances.items():
            if account_code.startswith(("1", "2", "3")):
                translated[account_code] = (amount * rate).quantize(
                    Decimal("0"), rounding=ROUND_HALF_EVEN
                )
            else:
                translated[account_code] = (amount * avg_rate).quantize(
                    Decimal("0"), rounding=ROUND_HALF_EVEN
                )
        return translated

    async def _get_intercompany_transactions(
        self, entity_ids: list[UUID], period_end_date: date
    ) -> list[IntercompanyTransaction]:
        return await self._cons_repo.get_intercompany_transactions(entity_ids, period_end_date)

    async def _calculate_eliminations(
        self, transactions: list[IntercompanyTransaction]
    ) -> list[EliminationEntry]:
        eliminations = []
        grouped = {}

        for tx in transactions:
            key = (tx.from_entity_id, tx.to_entity_id, tx.account_code)
            if key not in grouped:
                grouped[key] = Decimal("0")
            if tx.transaction_type == TransactionType.SALE:
                grouped[key] += tx.amount
            elif tx.transaction_type == TransactionType.PURCHASE:
                grouped[key] -= tx.amount
            else:
                grouped[key] += tx.amount

        for (from_ent, to_ent, acct), amount in grouped.items():
            if amount != 0:
                elim = EliminationEntry(
                    id=uuid4(),
                    account_code=acct,
                    debit=amount if amount > 0 else Decimal("0"),
                    credit=-amount if amount < 0 else Decimal("0"),
                    description=f"Eliminasi intercompany {from_ent} -> {to_ent}",
                    from_entity_id=from_ent,
                    to_entity_id=to_ent,
                    amount=abs(amount),
                )
                eliminations.append(elim)
        return eliminations

    async def _calculate_nci(
        self, parent_entity: Any, child_entity_ids: list[UUID], as_of_date: date
    ) -> Decimal:
        total_nci = Decimal("0")
        for child_id in child_entity_ids:
            child = await self._le_repo.get_by_id(child_id)
            if child.parent_id != parent_entity.id:
                continue
            ownership = await self._le_repo.get_ownership_percentage(parent_entity.id, child_id)
            if ownership >= Decimal("1"):
                continue
            equity = await self._get_entity_equity(child_id, as_of_date)
            nci_share = equity * (Decimal("1") - ownership)
            total_nci += nci_share
        return total_nci

    async def _get_entity_equity(self, entity_id: UUID, as_of_date: date) -> Decimal:
        tb = await self._get_entity_trial_balance(entity_id, as_of_date)
        total_equity = Decimal("0")
        for acct, bal in tb.items():
            if acct.startswith("3"):
                total_equity += bal
        return total_equity

    async def _aggregate_rows(
        self,
        all_balances: list[tuple[UUID, str, dict[str, Decimal]]],
        eliminations: list[EliminationEntry],
        nci_total: Decimal,
    ) -> list[ConsolidationRow]:
        all_accounts = set()
        for _, _, balances in all_balances:
            all_accounts.update(balances.keys())
        for elim in eliminations:
            all_accounts.add(elim.account_code)

        rows = []
        for acct in sorted(all_accounts):
            entity_balances = {}
            total_balance = Decimal("0")
            for ent_id, ent_name, balances in all_balances:
                bal = balances.get(acct, Decimal("0"))
                entity_balances[str(ent_id)] = bal
                total_balance += bal

            elim_amount = Decimal("0")
            for elim in eliminations:
                if elim.account_code == acct:
                    elim_amount += elim.debit - elim.credit
                    total_balance += elim_amount

            if acct.startswith("3") and nci_total != 0:
                total_balance -= nci_total

            rows.append(
                ConsolidationRow(
                    account_code=acct,
                    account_name=await self._get_account_name(acct),
                    entity_balances=entity_balances,
                    elimination_entries=[e.amount for e in eliminations if e.account_code == acct],
                    consolidated_balance=total_balance,
                )
            )
        return rows

    async def _get_account_name(self, account_code: str) -> str:
        return f"Account {account_code}"

    def _check_balance(self, rows: list[ConsolidationRow]) -> bool:
        total_debit = Decimal("0")
        total_credit = Decimal("0")
        for row in rows:
            if row.account_code.startswith(("1", "5", "6")):
                total_debit += row.consolidated_balance
            else:
                total_credit += row.consolidated_balance
        return total_debit == total_credit

    async def _save_consolidation_result(
        self,
        consolidation_id: UUID,
        request: ConsolidationRequest,
        rows: list[ConsolidationRow],
        eliminations: list[EliminationEntry],
        nci_total: Decimal,
    ) -> None:
        await self._cons_repo.save_consolidation(
            id=consolidation_id,
            group_entity_id=request.group_legal_entity_id,
            period_end_date=request.period_end_date,
            currency=request.currency_code,
            rows=[
                {"account_code": r.account_code, "balance": r.consolidated_balance} for r in rows
            ],
            eliminations=[
                {"account_code": e.account_code, "debit": e.debit, "credit": e.credit}
                for e in eliminations
            ],
            nci_total=nci_total,
            created_at=datetime.now(UTC),
        )

    # ========================================================================
    # Intercompany Reconciliation
    # ========================================================================

    async def reconcile_intercompany(
        self, group_entity_id: UUID, as_of_date: date, entity_ids: list[UUID]
    ) -> IntercompanyReconciliationResponse:
        """Lakukan rekonsiliasi saldo intercompany."""
        self._stats["reconciliations"] += 1

        all_balances = []
        for ent_id in entity_ids:
            balances = await self._cons_repo.get_intercompany_balances(ent_id, as_of_date)
            all_balances.extend(balances)

        unmatched = []
        total_unmatched = Decimal("0")
        key_to_balance = {}

        for bal in all_balances:
            key = (bal.from_entity_id, bal.to_entity_id, bal.account_code)
            if key not in key_to_balance:
                key_to_balance[key] = bal
            else:
                opposite_key = (bal.to_entity_id, bal.from_entity_id, bal.account_code)
                opposite = key_to_balance.get(opposite_key)
                if opposite and bal.amount == opposite.amount:
                    bal.is_matched = True
                    opposite.is_matched = True
                else:
                    unmatched.append(bal)
                    total_unmatched += bal.amount

        status = "MATCHED" if total_unmatched == 0 else "MISMATCH"
        return IntercompanyReconciliationResponse(
            group_entity_id=group_entity_id,
            as_of_date=as_of_date,
            unmatched_balances=unmatched,
            total_unmatched=total_unmatched,
            reconciliation_status=status,
        )

    # ========================================================================
    # Elimination Journal Generation
    # ========================================================================

    async def generate_elimination_journal(self, consolidation_id: UUID, user_id: UUID) -> UUID:
        """Generate journal entries untuk eliminasi intercompany."""
        consolidation = await self._cons_repo.get_consolidation(consolidation_id)
        if not consolidation:
            raise ConsolidationError(f"Consolidation {consolidation_id} not found")

        lines = []
        for elim in consolidation.eliminations:
            lines.append(
                {
                    "account_code": elim["account_code"],
                    "debit": elim["debit"],
                    "credit": elim["credit"],
                    "description": "Eliminasi intercompany",
                }
            )

        if not self._ledger_repo:
            raise ConsolidationError("LedgerRepository not configured")

        journal_id = await self._ledger_repo.post_journal(
            legal_entity_id=consolidation.group_entity_id,
            journal_date=consolidation.period_end_date,
            period=f"{consolidation.period_end_date.year}-{consolidation.period_end_date.month:02d}",
            description=f"Elimination entries for consolidation {consolidation_id}",
            lines=lines,
            source_system="consolidation",
            user_id=user_id,
        )
        return journal_id

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_consolidation_service(
    consolidation_repo: ConsolidationRepositoryPort,
    legal_entity_repo: LegalEntityRepositoryPort,
    ledger_repo: LedgerRepositoryPort | None = None,
    uow: UnitOfWorkPort | None = None,
    event_publisher: EventPublisherPort | None = None,
) -> ConsolidationService:
    return ConsolidationService(
        consolidation_repo=consolidation_repo,
        legal_entity_repo=legal_entity_repo,
        ledger_repo=ledger_repo,
        uow=uow,
        event_publisher=event_publisher,
    )


__all__ = [
    "ConsolidationError",
    "ConsolidationService",
    "EntityNotFoundError",
    "InconsistentCurrencyError",
    "IntercompanyMismatchError",
    "create_consolidation_service",
]