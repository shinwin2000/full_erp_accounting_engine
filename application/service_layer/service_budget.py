# service_budget.py - Complete rewrite with full event publishing

#!/usr/bin/env python3

"""
Module: service_budget.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service for budget management and variance analysis.
    Mempublikasikan semua domain events yang sesuai.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.budget.aggregate_root import Budget, BudgetLineItem, BudgetStatus
from domain.budget.variance_calculator import VarianceCalculator
from ports.primary.budget_repository_port import BudgetRepositoryPort
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

# Import domain events
from domain.budget.domain_events import (
    BudgetApprovedEvent,
    BudgetArchivedEvent,
    BudgetCancelledEvent,
    BudgetClosedEvent,
    BudgetCreatedEvent,
    BudgetLineAddedEvent,
    BudgetLineAdjustedEvent,
    BudgetLineRemovedEvent,
    BudgetRejectedEvent,
    BudgetRevisedEvent,
    BudgetStatusChangedEvent,
)

logger = logging.getLogger(__name__)


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class BudgetRequest:
    legal_entity_id: UUID
    budget_name: str
    fiscal_year: int
    lines: list[dict[str, Any]]
    period_type: str
    description: str | None = None


@dataclass(kw_only=True)
class BudgetResponse:
    budget_id: UUID
    budget_number: str
    legal_entity_id: UUID
    budget_name: str
    fiscal_year: int
    period_type: str
    total_amount: Decimal
    description: str | None
    status: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(kw_only=True)
class VarianceAnalysisRequest:
    legal_entity_id: UUID
    budget_id: UUID
    period_start: date
    period_end: date
    include_details: bool = True


@dataclass(kw_only=True)
class VarianceItem:
    account_code: str
    account_name: str
    budget_amount: Decimal
    actual_amount: Decimal
    variance: Decimal
    variance_percentage: float
    variance_type: str


@dataclass(kw_only=True)
class VarianceAnalysisResponse:
    budget_id: UUID
    budget_name: str
    period_start: date
    period_end: date
    total_budget: Decimal
    total_actual: Decimal
    total_variance: Decimal
    variance_percentage: float
    items: list[VarianceItem]
    analysis_date: datetime


@dataclass(kw_only=True)
class BudgetLineRequest:
    account_code: str
    amount: Decimal
    period: str | None = None
    description: str | None = None


# ============================================================================
# Exceptions
# ============================================================================


class BudgetServiceError(Exception):
    pass


class BudgetNotFoundError(BudgetServiceError):
    pass


class BudgetAlreadyExistsError(BudgetServiceError):
    pass


class BudgetPeriodClosedError(BudgetServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class BudgetService:
    """
    Service for budget management and variance analysis.
    """

    def __init__(
        self,
        budget_repo: BudgetRepositoryPort,
        ledger_repo: LedgerRepositoryPort | None = None,
        uow: UnitOfWorkPort | None = None,
        event_publisher: EventPublisherPort | None = None,
    ):
        self._budget_repo = budget_repo
        self._ledger_repo = ledger_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._variance_calculator = VarianceCalculator()
        self._stats = {"budgets_created": 0, "budgets_approved": 0, "variance_analyses": 0}

        logger.info("BudgetService initialized")

    # ========================================================================
    # Budget Management
    # ========================================================================

    async def create_budget(
        self, request: BudgetRequest, user_id: UUID, correlation_id: str | None = None
    ) -> BudgetResponse:
        """Create a new budget."""
        existing = await self._budget_repo.get_by_name_and_year(
            request.legal_entity_id, request.budget_name, request.fiscal_year
        )
        if existing:
            raise BudgetAlreadyExistsError(
                f"Budget '{request.budget_name}' for year {request.fiscal_year} already exists"
            )

        budget_number = await self._generate_budget_number(request.legal_entity_id)

        budget = Budget(
            id=uuid4(),
            budget_number=budget_number,
            legal_entity_id=request.legal_entity_id,
            budget_name=request.budget_name,
            fiscal_year=request.fiscal_year,
            period_type=request.period_type,
            status=BudgetStatus.DRAFT,
            lines=[
                BudgetLineItem(
                    account_code=line["account_code"],
                    period=line.get("period"),
                    amount=Decimal(str(line["amount"])),
                    description=line.get("description", ""),
                )
                for line in request.lines
            ],
            description=request.description,
            created_by=user_id,
            created_at=datetime.now(UTC),
        )

        await self._budget_repo.save(budget)
        if self._uow:
            await self._uow.commit()

        self._stats["budgets_created"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BudgetCreatedEvent(
                aggregate_id=budget.id,
                aggregate_version=1,
                budget_id=budget.id,
                budget_number=budget.budget_number,
                budget_name=budget.budget_name,
                fiscal_year=budget.fiscal_year,
                created_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published BudgetCreatedEvent for {budget.budget_number}")

        logger.info(f"Budget {budget_number} created: {request.budget_name}")
        return await self._to_response(budget)

    async def _generate_budget_number(self, legal_entity_id: UUID) -> str:
        last = await self._budget_repo.get_last_budget_number(legal_entity_id)
        seq = int(last.split("-")[-1]) + 1 if last else 1
        return f"BUD-{legal_entity_id.hex[:6]}-{seq:06d}"

    async def approve_budget(
        self, budget_id: UUID, approver_id: UUID, correlation_id: str | None = None
    ) -> BudgetResponse:
        """Approve a budget."""
        budget = await self._budget_repo.get_by_id(budget_id)
        if not budget:
            raise BudgetNotFoundError(f"Budget {budget_id} not found")

        if budget.status != BudgetStatus.DRAFT:
            raise BudgetServiceError("Only DRAFT budgets can be approved")

        old_status = budget.status
        budget.status = BudgetStatus.APPROVED
        budget.approved_at = datetime.now(UTC)
        budget.approved_by = approver_id

        await self._budget_repo.update(budget)
        if self._uow:
            await self._uow.commit()

        self._stats["budgets_approved"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BudgetApprovedEvent(
                aggregate_id=budget.id,
                aggregate_version=budget.version,
                budget_id=budget.id,
                budget_number=budget.budget_number,
                approved_by=str(approver_id),
                old_status=old_status.value,
                new_status=budget.status.value,
                user_id=str(approver_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published BudgetApprovedEvent for {budget.budget_number}")

        logger.info(f"Budget {budget.budget_number} approved")
        return await self._to_response(budget)

    async def reject_budget(
        self, budget_id: UUID, reason: str, user_id: UUID, correlation_id: str | None = None
    ) -> BudgetResponse:
        """Reject a budget."""
        budget = await self._budget_repo.get_by_id(budget_id)
        if not budget:
            raise BudgetNotFoundError(f"Budget {budget_id} not found")

        if budget.status != BudgetStatus.DRAFT:
            raise BudgetServiceError("Only DRAFT budgets can be rejected")

        budget.status = BudgetStatus.REJECTED
        budget.rejection_reason = reason
        budget.rejected_at = datetime.now(UTC)
        budget.rejected_by = user_id

        await self._budget_repo.update(budget)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BudgetRejectedEvent(
                aggregate_id=budget.id,
                aggregate_version=budget.version,
                budget_id=budget.id,
                budget_number=budget.budget_number,
                reason=reason,
                rejected_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published BudgetRejectedEvent for {budget.budget_number}")

        return await self._to_response(budget)

    async def revise_budget(
        self,
        budget_id: UUID,
        new_lines: list[dict[str, Any]],
        revision_reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> BudgetResponse:
        """Revise an existing budget."""
        budget = await self._budget_repo.get_by_id(budget_id)
        if not budget:
            raise BudgetNotFoundError(f"Budget {budget_id} not found")

        if budget.status not in (BudgetStatus.APPROVED, BudgetStatus.DRAFT):
            raise BudgetServiceError(f"Budget in status {budget.status.value} cannot be revised")

        old_version = budget.version
        budget.version += 1
        budget.revision_reason = revision_reason
        budget.revised_by = user_id
        budget.revised_at = datetime.now(UTC)
        budget.lines = [
            BudgetLineItem(
                account_code=line["account_code"],
                period=line.get("period"),
                amount=Decimal(str(line["amount"])),
                description=line.get("description", ""),
            )
            for line in new_lines
        ]

        await self._budget_repo.update(budget)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BudgetRevisedEvent(
                aggregate_id=budget.id,
                aggregate_version=budget.version,
                budget_id=budget.id,
                budget_number=budget.budget_number,
                old_version=old_version,
                new_version=budget.version,
                revision_reason=revision_reason,
                revised_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published BudgetRevisedEvent for {budget.budget_number}")

        logger.info(f"Budget {budget.budget_number} revised (version {budget.version})")
        return await self._to_response(budget)

    async def close_budget(
        self, budget_id: UUID, user_id: UUID, correlation_id: str | None = None
    ) -> BudgetResponse:
        """Close a budget (end of period)."""
        budget = await self._budget_repo.get_by_id(budget_id)
        if not budget:
            raise BudgetNotFoundError(f"Budget {budget_id} not found")

        if budget.status != BudgetStatus.APPROVED:
            raise BudgetServiceError("Only APPROVED budgets can be closed")

        budget.status = BudgetStatus.CLOSED
        budget.closed_at = datetime.now(UTC)
        budget.closed_by = user_id

        await self._budget_repo.update(budget)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BudgetClosedEvent(
                aggregate_id=budget.id,
                aggregate_version=budget.version,
                budget_id=budget.id,
                budget_number=budget.budget_number,
                closed_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published BudgetClosedEvent for {budget.budget_number}")

        return await self._to_response(budget)

    async def cancel_budget(
        self, budget_id: UUID, reason: str, user_id: UUID, correlation_id: str | None = None
    ) -> BudgetResponse:
        """Cancel a budget."""
        budget = await self._budget_repo.get_by_id(budget_id)
        if not budget:
            raise BudgetNotFoundError(f"Budget {budget_id} not found")

        if budget.status == BudgetStatus.CLOSED:
            raise BudgetServiceError("Cannot cancel a closed budget")

        budget.status = BudgetStatus.CANCELLED
        budget.cancellation_reason = reason
        budget.cancelled_at = datetime.now(UTC)
        budget.cancelled_by = user_id

        await self._budget_repo.update(budget)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BudgetCancelledEvent(
                aggregate_id=budget.id,
                aggregate_version=budget.version,
                budget_id=budget.id,
                budget_number=budget.budget_number,
                reason=reason,
                cancelled_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published BudgetCancelledEvent for {budget.budget_number}")

        return await self._to_response(budget)

    async def archive_budget(
        self, budget_id: UUID, user_id: UUID, correlation_id: str | None = None
    ) -> BudgetResponse:
        """Archive a budget."""
        budget = await self._budget_repo.get_by_id(budget_id)
        if not budget:
            raise BudgetNotFoundError(f"Budget {budget_id} not found")

        budget.is_archived = True
        budget.archived_at = datetime.now(UTC)
        budget.archived_by = user_id

        await self._budget_repo.update(budget)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BudgetArchivedEvent(
                aggregate_id=budget.id,
                aggregate_version=budget.version,
                budget_id=budget.id,
                budget_number=budget.budget_number,
                archived_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published BudgetArchivedEvent for {budget.budget_number}")

        return await self._to_response(budget)

    async def add_budget_line(
        self,
        budget_id: UUID,
        line: BudgetLineRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> BudgetResponse:
        """Add a line item to an existing budget."""
        budget = await self._budget_repo.get_by_id(budget_id)
        if not budget:
            raise BudgetNotFoundError(f"Budget {budget_id} not found")

        if budget.status not in (BudgetStatus.DRAFT, BudgetStatus.APPROVED):
            raise BudgetServiceError(f"Cannot add line to budget in status {budget.status.value}")

        new_line = BudgetLineItem(
            account_code=line.account_code,
            period=line.period,
            amount=line.amount,
            description=line.description,
        )
        budget.lines.append(new_line)

        await self._budget_repo.update(budget)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BudgetLineAddedEvent(
                aggregate_id=budget.id,
                aggregate_version=budget.version,
                budget_id=budget.id,
                budget_number=budget.budget_number,
                account_code=line.account_code,
                amount=line.amount,
                added_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published BudgetLineAddedEvent for {budget.budget_number}")

        return await self._to_response(budget)

    async def update_budget_line(
        self,
        budget_id: UUID,
        line_index: int,
        new_amount: Decimal,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> BudgetResponse:
        """Update a budget line amount."""
        budget = await self._budget_repo.get_by_id(budget_id)
        if not budget:
            raise BudgetNotFoundError(f"Budget {budget_id} not found")

        if budget.status not in (BudgetStatus.DRAFT, BudgetStatus.APPROVED):
            raise BudgetServiceError(f"Cannot update line in budget status {budget.status.value}")

        if line_index < 0 or line_index >= len(budget.lines):
            raise BudgetServiceError("Invalid line index")

        old_amount = budget.lines[line_index].amount
        budget.lines[line_index].amount = new_amount

        await self._budget_repo.update(budget)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BudgetLineAdjustedEvent(
                aggregate_id=budget.id,
                aggregate_version=budget.version,
                budget_id=budget.id,
                budget_number=budget.budget_number,
                account_code=budget.lines[line_index].account_code,
                old_amount=old_amount,
                new_amount=new_amount,
                adjusted_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published BudgetLineAdjustedEvent for {budget.budget_number}")

        return await self._to_response(budget)

    async def remove_budget_line(
        self,
        budget_id: UUID,
        line_index: int,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> BudgetResponse:
        """Remove a line from a budget."""
        budget = await self._budget_repo.get_by_id(budget_id)
        if not budget:
            raise BudgetNotFoundError(f"Budget {budget_id} not found")

        if budget.status not in (BudgetStatus.DRAFT, BudgetStatus.APPROVED):
            raise BudgetServiceError(f"Cannot remove line from budget status {budget.status.value}")

        if line_index < 0 or line_index >= len(budget.lines):
            raise BudgetServiceError("Invalid line index")

        removed_line = budget.lines.pop(line_index)

        await self._budget_repo.update(budget)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BudgetLineRemovedEvent(
                aggregate_id=budget.id,
                aggregate_version=budget.version,
                budget_id=budget.id,
                budget_number=budget.budget_number,
                account_code=removed_line.account_code,
                amount=removed_line.amount,
                removed_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published BudgetLineRemovedEvent for {budget.budget_number}")

        return await self._to_response(budget)

    async def change_budget_status(
        self,
        budget_id: UUID,
        new_status: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> BudgetResponse:
        """Change budget status (generic)."""
        budget = await self._budget_repo.get_by_id(budget_id)
        if not budget:
            raise BudgetNotFoundError(f"Budget {budget_id} not found")

        old_status = budget.status
        new_status_enum = BudgetStatus(new_status)

        if old_status == new_status_enum:
            return await self._to_response(budget)

        budget.status = new_status_enum
        budget.updated_at = datetime.now(UTC)
        budget.updated_by = user_id

        await self._budget_repo.update(budget)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BudgetStatusChangedEvent(
                aggregate_id=budget.id,
                aggregate_version=budget.version,
                budget_id=budget.id,
                budget_number=budget.budget_number,
                old_status=old_status.value,
                new_status=new_status_enum.value,
                changed_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published BudgetStatusChangedEvent for {budget.budget_number}")

        return await self._to_response(budget)

    # ========================================================================
    # Variance Analysis
    # ========================================================================

    async def analyze_variance(
        self, request: VarianceAnalysisRequest, user_id: UUID
    ) -> VarianceAnalysisResponse:
        """Perform budget vs actual variance analysis."""
        self._stats["variance_analyses"] += 1

        budget = await self._budget_repo.get_by_id(request.budget_id)
        if not budget:
            raise BudgetNotFoundError(f"Budget {request.budget_id} not found")

        if budget.status != BudgetStatus.APPROVED:
            raise BudgetServiceError("Only APPROVED budgets can be analyzed")

        if not self._ledger_repo:
            raise BudgetServiceError("LedgerRepository not configured")

        actuals = await self._ledger_repo.get_actual_balances(
            legal_entity_id=request.legal_entity_id,
            from_date=request.period_start,
            to_date=request.period_end,
            account_codes=[line.account_code for line in budget.lines],
        )

        items = []
        total_budget = Decimal("0")
        total_actual = Decimal("0")
        total_variance = Decimal("0")

        for line in budget.lines:
            actual = actuals.get(line.account_code, Decimal("0"))
            variance, variance_type = self._variance_calculator.calculate(
                budget_amount=line.amount, actual_amount=actual, account_code=line.account_code
            )
            variance_pct = self._variance_calculator.percentage_variance(line.amount, actual)

            items.append(
                VarianceItem(
                    account_code=line.account_code,
                    account_name=await self._get_account_name(line.account_code),
                    budget_amount=line.amount,
                    actual_amount=actual,
                    variance=variance,
                    variance_percentage=variance_pct,
                    variance_type=variance_type,
                )
            )
            total_budget += line.amount
            total_actual += actual
            total_variance += variance

        total_variance_pct = self._variance_calculator.percentage_variance(
            total_budget, total_actual
        )

        return VarianceAnalysisResponse(
            budget_id=budget.id,
            budget_name=budget.budget_name,
            period_start=request.period_start,
            period_end=request.period_end,
            total_budget=total_budget,
            total_actual=total_actual,
            total_variance=total_variance,
            variance_percentage=total_variance_pct,
            items=items,
            analysis_date=datetime.now(UTC),
        )

    async def _get_account_name(self, account_code: str) -> str:
        return f"Account {account_code}"

    async def _to_response(self, budget: Budget) -> BudgetResponse:
        return BudgetResponse(
            budget_id=budget.id,
            budget_number=budget.budget_number,
            legal_entity_id=budget.legal_entity_id,
            budget_name=budget.budget_name,
            fiscal_year=budget.fiscal_year,
            period_type=budget.period_type,
            status=budget.status.value,
            total_amount=budget.total_amount,
            description=budget.description,
            created_at=budget.created_at,
        )

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_budget_service(
    budget_repo: BudgetRepositoryPort,
    ledger_repo: LedgerRepositoryPort | None = None,
    uow: UnitOfWorkPort | None = None,
    event_publisher: EventPublisherPort | None = None,
) -> BudgetService:
    return BudgetService(budget_repo, ledger_repo, uow, event_publisher)


__all__ = [
    "BudgetAlreadyExistsError",
    "BudgetNotFoundError",
    "BudgetPeriodClosedError",
    "BudgetRequest",
    "BudgetResponse",
    "BudgetService",
    "BudgetServiceError",
    "VarianceAnalysisRequest",
    "VarianceAnalysisResponse",
    "VarianceItem",
    "BudgetLineRequest",
    "create_budget_service",
]