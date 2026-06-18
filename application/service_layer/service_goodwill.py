# service_goodwill.py - Complete rewrite with full implementation

#!/usr/bin/env python3

"""
Module: service_goodwill.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service for goodwill accounting (PSAK 48 / IFRS 3, IAS 36).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from domain.goodwill.aggregate_root import Goodwill, GoodwillStatus
from domain.goodwill.impairment_tester import GoodwillImpairmentTester
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.goodwill_repository_port import GoodwillRepositoryPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class GoodwillRecognitionRequest:
    """Request to recognize goodwill."""

    legal_entity_id: UUID
    acquisition_date: date
    acquisition_cost: Decimal
    fair_value_of_identifiable_net_assets: Decimal
    description: str
    cgu_code: str
    cgu_name: str
    created_by: UUID | None = None


@dataclass(kw_only=True)
class GoodwillResponse:
    """Response for goodwill."""

    goodwill_id: UUID
    goodwill_number: str
    legal_entity_id: UUID
    amount: Decimal
    carrying_amount: Decimal
    acquisition_date: date
    cgu_code: str
    description: str
    status: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(kw_only=True)
class ImpairmentTestRequest:
    """Request to test goodwill impairment."""

    goodwill_id: UUID
    test_date: date
    recoverable_amount: Decimal
    method: str = "VALUE_IN_USE"
    discount_rate: Decimal | None = None
    growth_rate: Decimal | None = None
    created_by: UUID | None = None


@dataclass(kw_only=True)
class ImpairmentTestResponse:
    """Response for impairment test."""

    goodwill_id: UUID
    test_date: date
    carrying_amount: Decimal
    recoverable_amount: Decimal
    impairment_loss: Decimal
    new_carrying_amount: Decimal
    is_impaired: bool
    journal_id: UUID | None = None


# ============================================================================
# Exceptions
# ============================================================================


class GoodwillServiceError(Exception):
    pass


class GoodwillNotFoundError(GoodwillServiceError):
    pass


class InvalidImpairmentTestError(GoodwillServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class GoodwillService:
    """
    Service for goodwill accounting and impairment testing.
    """

    def __init__(
        self,
        goodwill_repo: GoodwillRepositoryPort,
        ledger_repo: LedgerRepositoryPort | None = None,
        uow: UnitOfWorkPort | None = None,
        event_publisher: EventPublisherPort | None = None,
    ):
        if goodwill_repo is None:
            raise ValueError("goodwill_repo is required")

        self._goodwill_repo = goodwill_repo
        self._ledger_repo = ledger_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._impairment_tester = GoodwillImpairmentTester()
        self._stats = {"goodwill_recognized": 0, "impairments": 0, "reversals": 0}

        logger.info("GoodwillService initialized")

    # ========================================================================
    # Goodwill Recognition
    # ========================================================================

    async def recognize_goodwill(
        self, request: GoodwillRecognitionRequest, correlation_id: str | None = None
    ) -> GoodwillResponse:
        """Recognize goodwill from a business combination."""
        # Calculate goodwill amount
        goodwill_amount = request.acquisition_cost - request.fair_value_of_identifiable_net_assets

        if goodwill_amount < 0:
            logger.warning(f"Negative goodwill of {goodwill_amount} recognized as gain")
            goodwill_amount = Decimal("0")

        # Generate goodwill number
        goodwill_number = await self._generate_goodwill_number(request.legal_entity_id)

        # Create goodwill entity
        goodwill = Goodwill(
            id=uuid4(),
            goodwill_number=goodwill_number,
            legal_entity_id=request.legal_entity_id,
            amount=goodwill_amount,
            carrying_amount=goodwill_amount,
            status=GoodwillStatus.ACTIVE,
            acquisition_date=request.acquisition_date,
            description=request.description,
            cgu_code=request.cgu_code,
            cgu_name=request.cgu_name,
            created_by=request.created_by,
            created_at=datetime.now(UTC),
        )

        await self._goodwill_repo.save(goodwill)
        if self._uow:
            await self._uow.commit()

        self._stats["goodwill_recognized"] += 1

        # Publish event
        if self._event_publisher and goodwill_amount > 0:
            from domain.goodwill.domain_events import GoodwillRecognized

            event = GoodwillRecognized(
                goodwill_id=goodwill.id,
                goodwill_number=goodwill.goodwill_number,
                amount=goodwill_amount,
                acquisition_date=request.acquisition_date,
                user_id=request.created_by,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id)

        logger.info(f"Goodwill {goodwill_number} recognized: {goodwill_amount}")

        return GoodwillResponse(
            goodwill_id=goodwill.id,
            goodwill_number=goodwill.goodwill_number,
            legal_entity_id=goodwill.legal_entity_id,
            amount=goodwill.amount,
            carrying_amount=goodwill.carrying_amount,
            status=goodwill.status.value,
            acquisition_date=goodwill.acquisition_date,
            cgu_code=goodwill.cgu_code,
            description=goodwill.description,
            created_at=goodwill.created_at,
        )

    async def _generate_goodwill_number(self, legal_entity_id: UUID) -> str:
        """Generate unique goodwill number."""
        last = await self._goodwill_repo.get_last_goodwill_number(legal_entity_id)
        seq = int(last.split("-")[-1]) + 1 if last else 1
        return f"GW-{legal_entity_id.hex[:6]}-{seq:06d}"

    # ========================================================================
    # Impairment Testing
    # ========================================================================

    async def test_impairment(
        self, request: ImpairmentTestRequest, correlation_id: str | None = None
    ) -> ImpairmentTestResponse:
        """Perform impairment test on goodwill."""
        goodwill = await self._goodwill_repo.get_by_id(request.goodwill_id)
        if not goodwill:
            raise GoodwillNotFoundError(f"Goodwill {request.goodwill_id} not found")

        if goodwill.status != GoodwillStatus.ACTIVE:
            raise InvalidImpairmentTestError(
                f"Goodwill is not active (status: {goodwill.status.value})"
            )

        carrying = goodwill.carrying_amount
        recoverable = request.recoverable_amount
        journal_id = None

        if recoverable < carrying:
            impairment_loss = carrying - recoverable
            new_carrying = recoverable
            is_impaired = True

            # Update goodwill
            goodwill.carrying_amount = new_carrying
            goodwill.impairment_loss_total = (
                goodwill.impairment_loss_total or Decimal("0")
            ) + impairment_loss
            goodwill.last_impairment_date = request.test_date
            goodwill.last_impairment_amount = impairment_loss
            goodwill.status = GoodwillStatus.IMPAIRED

            await self._goodwill_repo.update(goodwill)

            # Post impairment journal to GL
            if self._ledger_repo:
                journal_id = await self._post_impairment_journal(
                    goodwill.legal_entity_id, impairment_loss, request.test_date, request.created_by
                )
                await self._goodwill_repo.record_impairment_journal(goodwill.id, journal_id)

            if self._uow:
                await self._uow.commit()

            # Publish event
            if self._event_publisher:
                from domain.goodwill.domain_events import GoodwillImpaired

                event = GoodwillImpaired(
                    goodwill_id=goodwill.id,
                    goodwill_number=goodwill.goodwill_number,
                    impairment_loss=impairment_loss,
                    new_carrying_amount=new_carrying,
                    user_id=request.created_by,
                    occurred_at=datetime.now(UTC),
                )
                await self._event_publisher.publish(event, correlation_id)

            self._stats["impairments"] += 1
            logger.warning(f"Goodwill {goodwill.goodwill_number} impaired: loss {impairment_loss}")
        else:
            impairment_loss = Decimal("0")
            new_carrying = carrying
            is_impaired = False
            logger.info(f"Goodwill {goodwill.goodwill_number} not impaired")

        return ImpairmentTestResponse(
            goodwill_id=goodwill.id,
            test_date=request.test_date,
            carrying_amount=carrying,
            recoverable_amount=recoverable,
            impairment_loss=impairment_loss,
            new_carrying_amount=new_carrying,
            is_impaired=is_impaired,
            journal_id=journal_id,
        )

    async def _post_impairment_journal(
        self, legal_entity_id: UUID, impairment_loss: Decimal, test_date: date, user_id: UUID | None
    ) -> UUID:
        """Post impairment loss journal entry."""
        expense_account = "5-7100"  # Impairment loss - Goodwill
        goodwill_account = "1-1700"  # Goodwill asset account

        lines = [
            {
                "account_code": expense_account,
                "debit": impairment_loss,
                "credit": Decimal("0"),
                "description": "Goodwill impairment loss",
            },
            {
                "account_code": goodwill_account,
                "debit": Decimal("0"),
                "credit": impairment_loss,
                "description": "Write-down of goodwill",
            },
        ]

        journal_id = await self._ledger_repo.post_journal(
            legal_entity_id=legal_entity_id,
            journal_date=test_date,
            period=f"{test_date.year}-{test_date.month:02d}",
            description=f"Goodwill impairment test as of {test_date}",
            lines=lines,
            source_system="goodwill_impairment",
            user_id=user_id,
        )
        return journal_id

    # ========================================================================
    # Reversal of Impairment
    # ========================================================================

    async def reverse_impairment(
        self,
        goodwill_id: UUID,
        reversal_date: date,
        reversal_amount: Decimal,
        reason: str,
        user_id: UUID,
    ) -> Decimal:
        """Reverse a previous impairment loss."""
        goodwill = await self._goodwill_repo.get_by_id(goodwill_id)
        if not goodwill:
            raise GoodwillNotFoundError(f"Goodwill {goodwill_id} not found")

        if goodwill.status != GoodwillStatus.IMPAIRED:
            raise InvalidImpairmentTestError("Only impaired goodwill can be reversed")

        new_carrying = goodwill.carrying_amount + reversal_amount
        if new_carrying > goodwill.amount:
            new_carrying = goodwill.amount

        actual_reversal = new_carrying - goodwill.carrying_amount

        goodwill.carrying_amount = new_carrying
        goodwill.impairment_loss_total -= actual_reversal
        goodwill.last_reversal_date = reversal_date
        goodwill.last_reversal_amount = actual_reversal
        goodwill.status = (
            GoodwillStatus.ACTIVE
            if new_carrying == goodwill.amount
            else GoodwillStatus.PARTIALLY_IMPAIRED
        )

        await self._goodwill_repo.update(goodwill)
        if self._uow:
            await self._uow.commit()

        self._stats["reversals"] += 1
        logger.info(f"Goodwill {goodwill.goodwill_number} impairment reversed by {actual_reversal}")

        return actual_reversal

    # ========================================================================
    # Amortization
    # ========================================================================

    async def amortize_goodwill(
        self, goodwill_id: UUID, amortization_amount: Decimal, period: str, user_id: UUID
    ) -> Decimal:
        """Amortize goodwill over its useful life."""
        goodwill = await self._goodwill_repo.get_by_id(goodwill_id)
        if not goodwill:
            raise GoodwillNotFoundError(f"Goodwill {goodwill_id} not found")

        if goodwill.carrying_amount < amortization_amount:
            raise InvalidImpairmentTestError("Amortization amount exceeds carrying amount")

        goodwill.carrying_amount -= amortization_amount
        goodwill.accumulated_amortization = (
            goodwill.accumulated_amortization or Decimal("0")
        ) + amortization_amount
        goodwill.last_amortization_date = datetime.strptime(period, "%Y-%m").date()

        if goodwill.carrying_amount == 0:
            goodwill.status = GoodwillStatus.FULLY_AMORTIZED

        await self._goodwill_repo.update(goodwill)
        if self._uow:
            await self._uow.commit()

        logger.info(f"Goodwill {goodwill.goodwill_number} amortized by {amortization_amount}")
        return goodwill.carrying_amount

    # ========================================================================
    # Queries
    # ========================================================================

    async def get_goodwill(self, goodwill_id: UUID) -> GoodwillResponse | None:
        """Get goodwill by ID."""
        goodwill = await self._goodwill_repo.get_by_id(goodwill_id)
        if not goodwill:
            return None

        return GoodwillResponse(
            goodwill_id=goodwill.id,
            goodwill_number=goodwill.goodwill_number,
            legal_entity_id=goodwill.legal_entity_id,
            amount=goodwill.amount,
            carrying_amount=goodwill.carrying_amount,
            status=goodwill.status.value,
            acquisition_date=goodwill.acquisition_date,
            cgu_code=goodwill.cgu_code,
            description=goodwill.description,
            created_at=goodwill.created_at,
        )

    async def list_goodwill_by_entity(self, legal_entity_id: UUID) -> list[GoodwillResponse]:
        """List all goodwill for a legal entity."""
        items = await self._goodwill_repo.list_by_legal_entity(legal_entity_id)
        return [
            GoodwillResponse(
                goodwill_id=g.id,
                goodwill_number=g.goodwill_number,
                legal_entity_id=g.legal_entity_id,
                amount=g.amount,
                carrying_amount=g.carrying_amount,
                status=g.status.value,
                acquisition_date=g.acquisition_date,
                cgu_code=g.cgu_code,
                description=g.description,
                created_at=g.created_at,
            )
            for g in items
        ]

    def get_stats(self) -> dict[str, int]:
        """Get service statistics."""
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_goodwill_service(
    goodwill_repo: GoodwillRepositoryPort,
    ledger_repo: LedgerRepositoryPort | None = None,
    uow: UnitOfWorkPort | None = None,
    event_publisher: EventPublisherPort | None = None,
) -> GoodwillService:
    return GoodwillService(goodwill_repo, ledger_repo, uow, event_publisher)


__all__ = [
    "GoodwillNotFoundError",
    "GoodwillRecognitionRequest",
    "GoodwillResponse",
    "GoodwillService",
    "GoodwillServiceError",
    "ImpairmentTestRequest",
    "ImpairmentTestResponse",
    "InvalidImpairmentTestError",
    "create_goodwill_service",
]
