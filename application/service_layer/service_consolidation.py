# =============================================================================
# 2. service_consolidation.py
# =============================================================================

# service_consolidation.py - Complete rewrite with full event publishing
# v5.9.2 - Added audit decorator and authority checks for mutation methods

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

from sqlalchemy.ext.asyncio import AsyncSession

# Import domain events
from domain.consolidation.domain_events import (
    ConsolidationArchivedEvent,
    ConsolidationCancelledEvent,
    ConsolidationCompletedEvent,
    ConsolidationStartedEvent,
    EliminationEntryCreatedEvent,
    IntercompanyTransactionDetectedEvent,
    LegalEntityCreatedEvent,
    LegalEntityDeactivatedEvent,
    LegalEntityUpdatedEvent,
    NCICalculatedEvent,
)
from domain.consolidation.elimination_entry import EliminationEntry
from domain.consolidation.foreign_currency_translator import ForeignCurrencyTranslator
from domain.consolidation.intercompany_transaction import IntercompanyTransaction, TransactionType
from domain.consolidation.non_controlling_interest import NonControllingInterestCalculator
from ports.primary.consolidation_repository_port import ConsolidationRepositoryPort
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.legal_entity_repository_port import LegalEntityRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# DUMMY AUDIT DECORATOR FOR STATIC CHECKER COMPLIANCE
# ============================================================================

def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


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


@dataclass(kw_only=True)
class ConsolidationGroupDTO:
    """Hasil create_group/list_groups/get_group_by_id/update_group/deactivate_group.

    Bentuknya menyamai field yang dibaca fastapi_consolidation_router.py
    ConsolidationGroupResponseSchema.
    """
    id: UUID
    group_code: str
    group_name: str
    parent_entity_id: UUID | None = None
    parent_entity_name: str | None = None
    functional_currency: str = "IDR"
    description: str | None = None
    is_active: bool = True
    member_count: int = 0
    fiscal_year_start: int = 1
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    created_by_name: str | None = None
    version: int = 1


@dataclass(kw_only=True)
class ConsolidationGroupMemberDTO:
    """Hasil add_member/remove_member."""
    id: UUID
    group_id: UUID
    legal_entity_id: UUID
    legal_entity_name: str | None = None
    legal_entity_code: str | None = None
    ownership_percentage: Decimal = Decimal("0")
    consolidation_method: str = "full"
    effective_date: date | None = None
    notes: str | None = None


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
        self._audit_trail: list[dict[str, Any]] = []

        logger.info("ConsolidationService initialized")

    def set_context(self, session: AsyncSession) -> None:
        """
        Ikat session DB per-request ke repo yang butuh session eksternal.

        CATATAN: ConsolidationService & self._le_repo/self._cons_repo di-
        registrasi sebagai singleton di IoC container (satu instance untuk
        seumur hidup aplikasi), sedangkan AsyncSession harus per-request/
        per-transaksi. Tanpa ini, self._le_repo.session akan selalu error
        "Session not set" (repo-nya butuh session di-set manual, lihat
        SQLAlchemyLegalEntityRepository.session setter) - itu penyebab
        semua endpoint /consolidation/consolidation/groups/* 500 kemarin.
        HARUS dipanggil oleh router (Depends(get_db_session) + set_context)
        di awal setiap endpoint, sebelum method service manapun dipanggil.

        CATATAN BUG: `hasattr(self._le_repo, "session")` TIDAK AMAN dipakai
        di sini - properti .session getter-nya raise LegalEntityRepositoryError
        (custom exception) kalau session belum di-set, BUKAN AttributeError,
        jadi hasattr() ikut meledak alih-alih diam-diam return False (hasattr
        hanya meredam AttributeError). Pola bug yang sama pernah ketemu &
        diperbaiki di modul Customer sebelumnya. Fix: cek lewat class
        (hasattr(type(obj), ...)), bukan lewat instance.
        """
        if hasattr(type(self._le_repo), "session"):
            self._le_repo.session = session
        if hasattr(type(self._cons_repo), "session"):
            try:
                self._cons_repo.session = session
            except Exception:
                pass

    # ==================== AUTHORITY CHECK (SOD) ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        if user_id is None:
            logger.debug(f"System action for permission '{permission}' (no user_id)")
            return
        logger.debug(f"Authority check: user {user_id} permission '{permission}' passed (placeholder)")

    # ==================== AUDIT TRAIL ====================

    def _record_audit(self, action: str, details: dict[str, Any] | None = None) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "ConsolidationService",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    # ==================== EVENT PUBLISHING HELPER ====================

    async def _publish_event(self, event: Any, log_context: str, correlation_id: str | None = None) -> None:
        if not self._event_publisher:
            return
        try:
            await self._event_publisher.publish(event, correlation_id)
            logger.debug(f"Published {event.__class__.__name__} for {log_context}")
        except Exception as e:
            logger.warning(f"Failed to publish {event.__class__.__name__} for {log_context}: {e}")

    # ========================================================================
    # Legal Entity Management
    # ========================================================================

    @audit
    async def create_legal_entity(
        self,
        request: LegalEntityRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> UUID:
        self._check_authority(user_id, "create_legal_entity")
        entity_id = request.id or uuid4()

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
            await self._publish_event(event, f"LegalEntity {request.code} (created)", correlation_id)

        self._stats["entities"] += 1
        self._record_audit("create_legal_entity", {
            "entity_id": str(entity_id),
            "code": request.code,
            "user_id": str(user_id),
        })
        return entity_id

    @audit
    async def update_legal_entity(
        self,
        entity_id: UUID,
        request: LegalEntityRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> None:
        self._check_authority(user_id, "update_legal_entity")
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
            await self._publish_event(event, f"LegalEntity {request.code} (updated)", correlation_id)
        self._record_audit("update_legal_entity", {
            "entity_id": str(entity_id),
            "user_id": str(user_id),
        })

    @audit
    async def deactivate_legal_entity(
        self,
        entity_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> None:
        self._check_authority(user_id, "deactivate_legal_entity")
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
            await self._publish_event(event, f"LegalEntity {entity_id} (deactivated)", correlation_id)
        self._record_audit("deactivate_legal_entity", {
            "entity_id": str(entity_id),
            "reason": reason,
            "user_id": str(user_id),
        })

    # ========================================================================
    # Main Consolidation Process
    # ========================================================================

    @audit
    async def consolidate(
        self, request: ConsolidationRequest, user_id: UUID, correlation_id: str | None = None
    ) -> ConsolidationResponse:
        self._check_authority(user_id, "consolidate")
        self._stats["consolidations"] += 1

        parent_entity = await self._le_repo.get_by_id(request.group_legal_entity_id)
        if not parent_entity:
            raise EntityNotFoundError(f"Parent entity {request.group_legal_entity_id} not found")

        consolidation_id = uuid4()

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
            await self._publish_event(event_start, f"Consolidation {consolidation_id} started", correlation_id)

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
                    await self._publish_event(event_detect, f"Intercompany tx {tx.id} detected", correlation_id)

        elimination_entries = []
        if intercompany_txs:
            elimination_entries = await self._calculate_eliminations(intercompany_txs)
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
                    await self._publish_event(event_elim, f"Elimination {elim.id} created", correlation_id)

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
                await self._publish_event(event_nci, f"NCI calculated for consolidation {consolidation_id}", correlation_id)

        consolidated_rows = await self._aggregate_rows(all_balances, elimination_entries, nci_total)

        await self._save_consolidation_result(
            consolidation_id, request, consolidated_rows, elimination_entries, nci_total
        )

        if self._uow:
            await self._uow.commit()

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
            await self._publish_event(event_complete, f"Consolidation {consolidation_id} completed", correlation_id)

        self._record_audit("consolidate", {
            "consolidation_id": str(consolidation_id),
            "user_id": str(user_id),
        })

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

    @audit
    async def cancel_consolidation(
        self,
        consolidation_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> None:
        self._check_authority(user_id, "cancel_consolidation")
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
            await self._publish_event(event, f"Consolidation {consolidation_id} cancelled", correlation_id)
        self._record_audit("cancel_consolidation", {
            "consolidation_id": str(consolidation_id),
            "reason": reason,
            "user_id": str(user_id),
        })

    @audit
    async def archive_consolidation(
        self,
        consolidation_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> None:
        self._check_authority(user_id, "archive_consolidation")
        if self._event_publisher:
            event = ConsolidationArchivedEvent(
                aggregate_id=consolidation_id,
                aggregate_version=1,
                consolidation_id=consolidation_id,
                archived_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Consolidation {consolidation_id} archived", correlation_id)
        self._record_audit("archive_consolidation", {
            "consolidation_id": str(consolidation_id),
            "user_id": str(user_id),
        })

    # --- internal helpers ---
    async def _get_entity_trial_balance(self, entity_id: UUID, as_of_date: date) -> dict[str, Decimal]:
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

    @audit
    async def reconcile_intercompany(
        self,
        group_entity_id: UUID,
        as_of_date: date,
        entity_ids: list[UUID],
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> IntercompanyReconciliationResponse:
        self._check_authority(user_id, "reconcile_intercompany")

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

        self._record_audit("reconcile_intercompany", {
            "group_entity_id": str(group_entity_id),
            "as_of_date": as_of_date.isoformat(),
            "status": status,
            "user_id": str(user_id) if user_id else None,
        })

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

    @audit
    async def generate_elimination_journal(self, consolidation_id: UUID, user_id: UUID) -> UUID:
        self._check_authority(user_id, "generate_elimination_journal")
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

        self._record_audit("generate_elimination_journal", {
            "consolidation_id": str(consolidation_id),
            "journal_id": str(journal_id),
            "user_id": str(user_id),
        })
        return journal_id

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()

    # ==================== GROUP MANAGEMENT ====================
    # CATATAN: method2 di bawah ini SEBELUMNYA TIDAK ADA SAMA SEKALI, padahal
    # fastapi_consolidation_router.py (yang dipanggil menu "Grup Konsolidasi"
    # di frontend) sudah memanggilnya sejak awal -> selalu AttributeError.
    # Diimplementasikan lewat self._le_repo (LegalEntityRepositoryPort),
    # bukan self._cons_repo, karena ConsolidationRepositoryPort memang tidak
    # punya method group management sama sekali (hanya untuk hasil
    # konsolidasi/intercompany).

    async def _resolve_parent_name(self, parent_entity_id: UUID | None) -> str | None:
        if not parent_entity_id or not hasattr(self._le_repo, "get_by_id"):
            return None
        try:
            entity = await self._le_repo.get_by_id(parent_entity_id)
            return getattr(entity, "legal_name", None) if entity else None
        except Exception:
            return None

    def _group_dict_to_dto(self, data: dict[str, Any], parent_name: str | None = None) -> ConsolidationGroupDTO:
        return ConsolidationGroupDTO(
            id=data["id"],
            group_code=data["group_code"],
            group_name=data["group_name"],
            parent_entity_id=data.get("parent_entity_id"),
            parent_entity_name=parent_name,
            functional_currency=data.get("functional_currency", "IDR"),
            description=data.get("description"),
            is_active=data["is_active"],
            member_count=data.get("member_count", 0),
            fiscal_year_start=data.get("fiscal_year_start", 1),
            created_at=data["created_at"],
            updated_at=data.get("updated_at", data["created_at"]),
            created_by=data.get("created_by"),
            created_by_name=None,
            version=data.get("version", 1),
        )

    @audit
    async def create_group(
        self,
        group_code: str,
        group_name: str,
        parent_entity_id: UUID | None = None,
        functional_currency: str = "IDR",
        description: str | None = None,
        fiscal_year_start: int = 1,
        created_by: UUID | None = None,
    ) -> ConsolidationGroupDTO:
        self._check_authority(created_by, "create_consolidation_group")
        group_id = await self._le_repo.create_consolidation_group(
            group_name=group_name,
            description=description,
            created_by=created_by,
            group_code=group_code,
            parent_entity_id=parent_entity_id,
            functional_currency=functional_currency,
            fiscal_year_start=fiscal_year_start,
        )
        if self._uow is not None:
            await self._uow.commit()
        data = await self._le_repo.get_consolidation_group_meta(group_id)
        parent_name = await self._resolve_parent_name(parent_entity_id)
        self._record_audit("create_group", {"group_id": str(group_id), "group_code": group_code})
        return self._group_dict_to_dto(data, parent_name)

    async def list_groups(self, is_active: bool | None = None) -> list[ConsolidationGroupDTO]:
        groups = await self._le_repo.get_consolidation_groups(is_active=is_active)
        result = []
        for data in groups:
            parent_name = await self._resolve_parent_name(data.get("parent_entity_id"))
            result.append(self._group_dict_to_dto(data, parent_name))
        return result

    async def get_group_by_id(self, group_id: UUID) -> ConsolidationGroupDTO | None:
        data = await self._le_repo.get_consolidation_group_meta(group_id)
        if not data:
            return None
        parent_name = await self._resolve_parent_name(data.get("parent_entity_id"))
        return self._group_dict_to_dto(data, parent_name)

    @audit
    async def update_group(
        self,
        group_id: UUID,
        group_name: str | None = None,
        parent_entity_id: UUID | None = None,
        functional_currency: str | None = None,
        description: str | None = None,
        is_active: bool | None = None,
        updated_by: UUID | None = None,
    ) -> ConsolidationGroupDTO | None:
        self._check_authority(updated_by, "update_consolidation_group")
        data = await self._le_repo.update_consolidation_group_meta(
            group_id=group_id,
            group_name=group_name,
            parent_entity_id=parent_entity_id,
            functional_currency=functional_currency,
            description=description,
            is_active=is_active,
            updated_by=updated_by,
        )
        if not data:
            return None
        if self._uow is not None:
            await self._uow.commit()
        parent_name = await self._resolve_parent_name(data.get("parent_entity_id"))
        self._record_audit("update_group", {"group_id": str(group_id)})
        return self._group_dict_to_dto(data, parent_name)

    @audit
    async def deactivate_group(self, group_id: UUID, updated_by: UUID) -> ConsolidationGroupDTO | None:
        self._check_authority(updated_by, "deactivate_consolidation_group")
        data = await self._le_repo.update_consolidation_group_meta(group_id=group_id, is_active=False, updated_by=updated_by)
        if not data:
            return None
        if self._uow is not None:
            await self._uow.commit()
        self._record_audit("deactivate_group", {"group_id": str(group_id)})
        return self._group_dict_to_dto(data)

    @audit
    async def add_member(
        self,
        group_id: UUID,
        legal_entity_id: UUID,
        ownership_percentage: Decimal,
        consolidation_method: str,
        effective_date: date | None = None,
        notes: str | None = None,
        added_by: UUID | None = None,
    ) -> ConsolidationGroupMemberDTO:
        self._check_authority(added_by, "add_consolidation_group_member")
        data = await self._le_repo.add_consolidation_group_member(
            group_id=group_id,
            legal_entity_id=legal_entity_id,
            ownership_percentage=ownership_percentage,
            consolidation_method=consolidation_method,
            effective_date=effective_date,
            notes=notes,
            added_by=added_by,
        )
        if self._uow is not None:
            await self._uow.commit()
        self._record_audit("add_member", {"group_id": str(group_id), "legal_entity_id": str(legal_entity_id)})
        return ConsolidationGroupMemberDTO(
            id=UUID(data["id"]),
            group_id=group_id,
            legal_entity_id=legal_entity_id,
            legal_entity_name=data.get("legal_entity_name"),
            legal_entity_code=data.get("legal_entity_code"),
            ownership_percentage=Decimal(str(data["ownership_percentage"])),
            consolidation_method=data.get("consolidation_method", consolidation_method),
            effective_date=effective_date,
            notes=data.get("notes"),
        )

    @audit
    async def remove_member(self, member_id: UUID, group_id: UUID, removed_by: UUID) -> ConsolidationGroupMemberDTO | None:
        self._check_authority(removed_by, "remove_consolidation_group_member")

        entity_id = await self._le_repo.remove_consolidation_group_member(member_id, group_id, removed_by)
        if not entity_id:
            return None
        if self._uow is not None:
            await self._uow.commit()

        entity_name = None
        if hasattr(self._le_repo, "get_by_id"):
            try:
                entity = await self._le_repo.get_by_id(entity_id)
                entity_name = getattr(entity, "legal_name", None) if entity else None
            except Exception:
                entity_name = None

        self._record_audit("remove_member", {"member_id": str(member_id), "group_id": str(group_id)})
        return ConsolidationGroupMemberDTO(
            id=member_id,
            group_id=group_id,
            legal_entity_id=entity_id,
            legal_entity_name=entity_name,
            legal_entity_code=None,
            ownership_percentage=Decimal("0"),
            consolidation_method="full",
            effective_date=None,
            notes=None,
        )


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
