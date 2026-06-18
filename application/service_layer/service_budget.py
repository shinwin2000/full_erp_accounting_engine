# service_budget.py - Complete rewrite with fixes

#!/usr/bin/env python3

"""
Module: service_budget.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service for budget management and variance analysis.
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

        if self._event_publisher:
            from domain.budget.domain_events import BudgetCreated

            event = BudgetCreated(
                budget_id=budget.id,
                budget_number=budget.budget_number,
                budget_name=budget.budget_name,
                fiscal_year=budget.fiscal_year,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

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

        budget.status = BudgetStatus.APPROVED
        budget.approved_at = datetime.now(UTC)
        budget.approved_by = approver_id

        await self._budget_repo.update(budget)
        if self._uow:
            await self._uow.commit()

        self._stats["budgets_approved"] += 1

        if self._event_publisher:
            from domain.budget.domain_events import BudgetApproved

            event = BudgetApproved(
                budget_id=budget.id,
                budget_number=budget.budget_number,
                approved_by=approver_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        logger.info(f"Budget {budget.budget_number} approved")
        return await self._to_response(budget)

    async def revise_budget(
        self, budget_id: UUID, new_lines: list[dict[str, Any]], revision_reason: str, user_id: UUID
    ) -> BudgetResponse:
        """Revise an existing budget."""
        budget = await self._budget_repo.get_by_id(budget_id)
        if not budget:
            raise BudgetNotFoundError(f"Budget {budget_id} not found")

        if budget.status != BudgetStatus.APPROVED:
            raise BudgetServiceError("Only APPROVED budgets can be revised")

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

        logger.info(f"Budget {budget.budget_number} revised (version {budget.version})")
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
    "create_budget_service",
]
