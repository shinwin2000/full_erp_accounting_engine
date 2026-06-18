# service_journal.py - Complete rewrite with full implementation

#!/usr/bin/env python3

"""
Module: service_journal.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service layer untuk Journal Entry (Jurnal Umum).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from application.dto_objects.journal_request import (
    JournalEntryRequestDTO,
)
from application.dto_objects.journal_response import (
    JournalEntryResponseDTO,
    JournalLineResponseDTO,
    JournalValidationResultDTO,
)
from domain.fiscal_period.aggregate_root import FiscalPeriod, PeriodStatus
from domain.journal.aggregate_root import JournalAggregate
from domain.journal.domain_events import JournalApproved, JournalPosted, JournalReversed
from domain.journal.invariants import JournalInvariantsValidator
from domain.journal.journal_entity import JournalEntry, JournalStatus, JournalType
from domain.journal.journal_line_vo import JournalLine
from domain.journal.state_machine import JournalStateMachine
from domain.shared_value_objects.document_number_vo import DocumentNumber
from ports.primary.account_repository_port import AccountRepositoryPort
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.journal_repository_port import JournalRepositoryPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# Exceptions
# ============================================================================


class JournalServiceError(Exception):
    pass


class JournalNotBalancedError(JournalServiceError):
    pass


class JournalAlreadyPostedError(JournalServiceError):
    pass


class JournalNotFoundError(JournalServiceError):
    pass


class JournalPeriodClosedError(JournalServiceError):
    pass


class JournalApprovalRequiredError(JournalServiceError):
    pass


class JournalReversalNotAllowedError(JournalServiceError):
    pass


class AccountNotFoundError(JournalServiceError):
    pass


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class PostJournalRequest:
    """Request to post a journal entry."""

    legal_entity_id: UUID
    journal_date: date
    period: str
    description: str
    lines: list[dict[str, Any]]
    source_system: str = "manual"
    reference_number: str | None = None
    attachment_ids: list[UUID] | None = None
    user_id: UUID | None = None
    correlation_id: str | None = None


@dataclass(kw_only=True)
class PostJournalResponse:
    """Response after posting journal."""

    journal_id: UUID
    journal_number: str
    status: str
    created_at: datetime


# ============================================================================
# Main Service
# ============================================================================


class JournalService:
    """
    Service untuk mengelola jurnal umum.
    """

    def __init__(
        self,
        journal_repo: JournalRepositoryPort,
        ledger_repo: LedgerRepositoryPort,
        account_repo: AccountRepositoryPort,
        uow: UnitOfWorkPort,
        event_publisher: EventPublisherPort | None = None,
    ):
        if journal_repo is None:
            raise ValueError("journal_repo is required")
        if ledger_repo is None:
            raise ValueError("ledger_repo is required")
        if account_repo is None:
            raise ValueError("account_repo is required")
        if uow is None:
            raise ValueError("uow is required")

        self._journal_repo = journal_repo
        self._ledger_repo = ledger_repo
        self._account_repo = account_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._validator = JournalInvariantsValidator()
        self._state_machine = JournalStateMachine()
        self._stats = {"journals_posted": 0, "journals_approved": 0, "journals_reversed": 0}

        logger.info("JournalService initialized")

    # ==================== CORE POSTING ====================

    async def post_journal_entry(self, request: PostJournalRequest) -> PostJournalResponse:
        """
        Post a journal entry.
        """
        # Validate period
        period = await self._get_and_validate_period(request.period)
        if period.status != PeriodStatus.OPEN:
            raise JournalPeriodClosedError(f"Period {request.period} is {period.status.value}")

        # Validate lines and accounts
        lines = []
        total_debit = Decimal("0")
        total_credit = Decimal("0")

        for line_dto in request.lines:
            account = await self._account_repo.find_by_code(
                request.legal_entity_id, line_dto["account_code"]
            )
            if not account:
                raise AccountNotFoundError(f"Account {line_dto['account_code']} not found")
            if account.status != "ACTIVE":
                raise JournalServiceError(f"Account {line_dto['account_code']} is inactive")

            debit = Decimal(str(line_dto.get("debit", 0)))
            credit = Decimal(str(line_dto.get("credit", 0)))

            total_debit += debit
            total_credit += credit

            lines.append(
                JournalLine(
                    account_id=account.id,
                    account_code=account.account_code,
                    description=line_dto.get("description", ""),
                    debit=debit,
                    credit=credit,
                    cost_center=line_dto.get("cost_center"),
                    department=line_dto.get("department"),
                    tax_code=line_dto.get("tax_code"),
                    project_code=line_dto.get("project_code"),
                )
            )

        if total_debit != total_credit:
            raise JournalNotBalancedError(
                f"Journal not balanced: debit={total_debit}, credit={total_credit}"
            )

        # Generate journal number
        journal_number = await self._generate_journal_number(request.legal_entity_id)

        # Create aggregate
        journal = JournalEntry(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            journal_number=DocumentNumber(journal_number),
            journal_date=request.journal_date,
            period=period,
            description=request.description,
            journal_type=JournalType.MANUAL,
            status=JournalStatus.DRAFT,
            lines=lines,
            created_by=request.user_id,
            created_at=datetime.utcnow(),
            total_debit=total_debit,
            total_credit=total_credit,
            source_system=request.source_system,
            reference_number=request.reference_number,
            attachment_ids=request.attachment_ids or [],
        )

        aggregate = JournalAggregate(journal=journal, version=0)
        aggregate.post(request.user_id)

        # Save
        await self._journal_repo.save(aggregate)
        await self._uow.commit()

        self._stats["journals_posted"] += 1

        # Publish event
        if self._event_publisher:
            event = JournalPosted(
                aggregate_id=journal.id,
                legal_entity_id=journal.legal_entity_id,
                journal_number=journal.journal_number.value,
                total_debit=total_debit,
                total_credit=total_credit,
                user_id=request.user_id,
                occurred_at=datetime.utcnow(),
            )
            await self._event_publisher.publish(event, request.correlation_id)

        logger.info(f"Journal {journal_number} posted")

        return PostJournalResponse(
            journal_id=journal.id,
            journal_number=journal_number,
            status=journal.status.value,
            created_at=journal.created_at,
        )

    async def approve_journal(
        self, journal_id: UUID, approver_id: UUID, correlation_id: str | None = None
    ) -> JournalEntryResponseDTO:
        """Approve a journal (four-eyes principle)."""
        aggregate = await self._journal_repo.get_by_id(journal_id)
        if not aggregate:
            raise JournalNotFoundError(f"Journal {journal_id} not found")

        if aggregate.journal.status != JournalStatus.POSTED:
            raise JournalApprovalRequiredError("Only posted journals can be approved")

        aggregate.approve(approver_id)
        await self._journal_repo.save(aggregate)
        await self._uow.commit()

        self._stats["journals_approved"] += 1

        if self._event_publisher:
            event = JournalApproved(
                aggregate_id=journal_id,
                journal_number=aggregate.journal.journal_number.value,
                approver_id=approver_id,
                occurred_at=datetime.utcnow(),
            )
            await self._event_publisher.publish(event, correlation_id)

        return self._to_response(aggregate.journal)

    async def reverse_journal(
        self,
        journal_id: UUID,
        reversal_date: date,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> JournalEntryResponseDTO:
        """Reverse a journal entry."""
        original_agg = await self._journal_repo.get_by_id(journal_id)
        if not original_agg:
            raise JournalNotFoundError(f"Journal {journal_id} not found")

        if original_agg.journal.status != JournalStatus.POSTED:
            raise JournalReversalNotAllowedError("Only posted journals can be reversed")

        if original_agg.journal.is_reversed:
            raise JournalReversalNotAllowedError("Journal already reversed")

        # Create reversal lines
        reversal_lines = []
        for line in original_agg.journal.lines:
            reversal_lines.append(
                JournalLine(
                    account_id=line.account_id,
                    account_code=line.account_code,
                    description=f"REVERSAL: {line.description} - {reason}",
                    debit=line.credit,
                    credit=line.debit,
                    cost_center=line.cost_center,
                    department=line.department,
                    tax_code=line.tax_code,
                    project_code=line.project_code,
                )
            )

        # Validate period
        period_str = f"{reversal_date.year}-{reversal_date.month:02d}"
        period = await self._get_and_validate_period(period_str)

        # Generate reversal number
        rev_number = await self._generate_journal_number(original_agg.journal.legal_entity_id)

        reversal_journal = JournalEntry(
            id=uuid4(),
            legal_entity_id=original_agg.journal.legal_entity_id,
            journal_number=DocumentNumber(rev_number),
            journal_date=reversal_date,
            period=period,
            description=f"Reversal of {original_agg.journal.journal_number.value}: {reason}",
            journal_type=JournalType.REVERSAL,
            status=JournalStatus.DRAFT,
            lines=reversal_lines,
            created_by=user_id,
            created_at=datetime.utcnow(),
            total_debit=original_agg.journal.total_credit,
            total_credit=original_agg.journal.total_debit,
            source_system=original_agg.journal.source_system,
            reference_number=original_agg.journal.journal_number.value,
            original_journal_id=journal_id,
        )

        agg = JournalAggregate(journal=reversal_journal, version=0)
        agg.post(user_id)

        # Mark original as reversed
        original_agg.mark_reversed(reversal_journal.id, user_id)

        await self._journal_repo.save(original_agg)
        await self._journal_repo.save(agg)
        await self._uow.commit()

        self._stats["journals_reversed"] += 1

        if self._event_publisher:
            event = JournalReversed(
                aggregate_id=journal_id,
                reversal_journal_id=reversal_journal.id,
                reversal_number=rev_number,
                reason=reason,
                user_id=user_id,
                occurred_at=datetime.utcnow(),
            )
            await self._event_publisher.publish(event, correlation_id)

        return self._to_response(reversal_journal)

    # ==================== QUERIES ====================

    async def get_journal(self, journal_id: UUID) -> JournalEntryResponseDTO | None:
        """Get journal by ID."""
        agg = await self._journal_repo.get_by_id(journal_id)
        if not agg:
            return None
        return self._to_response(agg.journal)

    async def list_journals(
        self,
        legal_entity_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
        status: str | None = None,
        journal_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JournalEntryResponseDTO]:
        """List journals with filters."""
        journals = await self._journal_repo.list(
            legal_entity_id=legal_entity_id,
            from_date=from_date,
            to_date=to_date,
            status=status,
            journal_type=journal_type,
            limit=limit,
            offset=offset,
        )
        return [self._to_response(j) for j in journals]

    async def validate_journal(self, request: JournalEntryRequestDTO) -> JournalValidationResultDTO:
        """Validate journal without posting."""
        errors = []
        total_debit = sum(l.debit for l in request.lines)
        total_credit = sum(l.credit for l in request.lines)

        if total_debit != total_credit:
            errors.append(f"Total debit {total_debit} != total credit {total_credit}")

        # Validate period
        try:
            period = await self._get_and_validate_period(request.period)
            if period.status != PeriodStatus.OPEN:
                errors.append(f"Period {request.period} is {period.status.value}")
        except Exception as e:
            errors.append(str(e))

        # Validate accounts
        for line in request.lines:
            account = await self._account_repo.find_by_code(
                request.legal_entity_id, line.account_code
            )
            if not account:
                errors.append(f"Account {line.account_code} not found")
            elif account.status != "ACTIVE":
                errors.append(f"Account {line.account_code} is inactive")

        return JournalValidationResultDTO(
            is_valid=len(errors) == 0,
            errors=errors,
            total_debit=total_debit,
            total_credit=total_credit,
        )

    # ==================== PRIVATE HELPERS ====================

    async def _get_and_validate_period(self, period_str: str) -> FiscalPeriod:
        """Parse period string and return FiscalPeriod object."""
        try:
            if "-" in period_str:
                year, month = map(int, period_str.split("-"))
            else:
                year = int(period_str[:4])
                month = int(period_str[4:6])
            period = await self._journal_repo.get_period(year, month)
            if not period:
                raise JournalPeriodClosedError(f"Period {period_str} not found")
            return period
        except Exception as e:
            raise JournalPeriodClosedError(f"Invalid period format: {period_str}") from e

    async def _generate_journal_number(self, legal_entity_id: UUID) -> str:
        """Generate unique journal number."""
        last = await self._journal_repo.get_last_journal_number(legal_entity_id)
        if not last:
            return f"JNL-{datetime.utcnow().year}-00001"
        parts = last.split("-")
        seq = int(parts[-1]) + 1
        return f"JNL-{datetime.utcnow().year}-{seq:05d}"

    def _to_response(self, journal: JournalEntry) -> JournalEntryResponseDTO:
        lines = [
            JournalLineResponseDTO(
                account_code=line.account_code.value
                if hasattr(line.account_code, "value")
                else str(line.account_code),
                description=line.description,
                debit=line.debit,
                credit=line.credit,
                cost_center=line.cost_center,
                department=line.department,
            )
            for line in journal.lines
        ]
        return JournalEntryResponseDTO(
            id=journal.id,
            journal_number=journal.journal_number.value
            if hasattr(journal.journal_number, "value")
            else str(journal.journal_number),
            journal_date=journal.journal_date,
            period=f"{journal.period.year}-{journal.period.month:02d}",
            description=journal.description,
            lines=lines,
            total_debit=journal.total_debit,
            total_credit=journal.total_credit,
            status=journal.status.value,
            created_at=journal.created_at,
            created_by=journal.created_by,
            approved_at=getattr(journal, "approved_at", None),
            approved_by=getattr(journal, "approved_by", None),
        )

    def get_stats(self) -> dict[str, int]:
        """Get service statistics."""
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_journal_service(
    journal_repo: JournalRepositoryPort,
    ledger_repo: LedgerRepositoryPort,
    account_repo: AccountRepositoryPort,
    uow: UnitOfWorkPort,
    event_publisher: EventPublisherPort | None = None,
) -> JournalService:
    return JournalService(journal_repo, ledger_repo, account_repo, uow, event_publisher)


__all__ = [
    "AccountNotFoundError",
    "JournalAlreadyPostedError",
    "JournalApprovalRequiredError",
    "JournalNotBalancedError",
    "JournalNotFoundError",
    "JournalPeriodClosedError",
    "JournalReversalNotAllowedError",
    "JournalService",
    "JournalServiceError",
    "PostJournalRequest",
    "PostJournalResponse",
    "create_journal_service",
]
