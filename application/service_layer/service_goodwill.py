# service_goodwill.py - Complete rewrite with full event publishing

#!/usr/bin/env python3

"""
Module: service_goodwill.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service for goodwill accounting (PSAK 48 / IFRS 3, IAS 36).
    Mempublikasikan semua domain events yang sesuai.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.goodwill.aggregate_root import Goodwill, GoodwillStatus
from domain.goodwill.domain_events import (
    GoodwillAmortizedEvent,
    GoodwillDisposedEvent,
    GoodwillImpairedEvent,
    GoodwillImpairmentReversedEvent,
    GoodwillRecognizedEvent,
    GoodwillUpdatedEvent,
)
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
class GoodwillUpdateRequest:
    """Request to update goodwill details."""

    description: str | None = None
    cgu_code: str | None = None
    cgu_name: str | None = None


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


@dataclass(kw_only=True)
class GoodwillDisposalRequest:
    """Request to dispose goodwill."""

    goodwill_id: UUID
    disposal_date: date
    reason: str
    proceeds: Decimal = Decimal("0")
    disposed_by: UUID | None = None


# ============================================================================
# Exceptions
# ============================================================================


class GoodwillServiceError(Exception):
    pass


class GoodwillNotFoundError(GoodwillServiceError):
    pass


class InvalidImpairmentTestError(GoodwillServiceError):
    pass


class GoodwillAlreadyDisposedError(GoodwillServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class GoodwillService:
    """
    Service for goodwill accounting and impairment testing.
    Mempublikasikan event untuk setiap operasi.
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
        self._stats = {
            "goodwill_recognized": 0,
            "goodwill_updated": 0,
            "impairments": 0,
            "reversals": 0,
            "amortizations": 0,
            "disposals": 0,
        }

        logger.info("GoodwillService initialized")

    # ========================================================================
    # Goodwill Recognition
    # ========================================================================

    async def recognize_goodwill(
        self,
        request: GoodwillRecognitionRequest,
        correlation_id: str | None = None,
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
            updated_at=None,
            updated_by=None,
            version=1,
        )

        await self._goodwill_repo.save(goodwill)
        if self._uow:
            await self._uow.commit()

        self._stats["goodwill_recognized"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher and goodwill_amount > 0:
            try:
                event = GoodwillRecognizedEvent(
                    aggregate_id=goodwill.id,
                    aggregate_version=goodwill.version,
                    goodwill_id=goodwill.id,
                    goodwill_number=goodwill.goodwill_number,
                    amount=goodwill_amount,
                    acquisition_date=request.acquisition_date,
                    legal_entity_id=request.legal_entity_id,
                    recognized_by=str(request.created_by) if request.created_by else "system",
                    user_id=str(request.created_by) if request.created_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published GoodwillRecognizedEvent for {goodwill_number}")
            except Exception as e:
                logger.warning(f"Failed to publish GoodwillRecognizedEvent: {e}")

        logger.info(f"Goodwill {goodwill_number} recognized: {goodwill_amount}")
        return self._to_response(goodwill)

    async def _generate_goodwill_number(self, legal_entity_id: UUID) -> str:
        """Generate unique goodwill number."""
        last = await self._goodwill_repo.get_last_goodwill_number(legal_entity_id)
        seq = int(last.split("-")[-1]) + 1 if last else 1
        return f"GW-{legal_entity_id.hex[:6]}-{seq:06d}"

    # ========================================================================
    # Goodwill Update
    # ========================================================================

    async def update_goodwill(
        self,
        goodwill_id: UUID,
        request: GoodwillUpdateRequest,
        updated_by: UUID,
        correlation_id: str | None = None,
    ) -> GoodwillResponse:
        """Update goodwill details (description, CGU)."""
        goodwill = await self._goodwill_repo.get_by_id(goodwill_id)
        if not goodwill:
            raise GoodwillNotFoundError(f"Goodwill {goodwill_id} not found")

        if goodwill.status == GoodwillStatus.DISPOSED:
            raise GoodwillAlreadyDisposedError("Cannot update disposed goodwill")

        changes = {}

        if request.description is not None and request.description != goodwill.description:
            changes["description"] = {"old": goodwill.description, "new": request.description}
            goodwill.description = request.description

        if request.cgu_code is not None and request.cgu_code != goodwill.cgu_code:
            changes["cgu_code"] = {"old": goodwill.cgu_code, "new": request.cgu_code}
            goodwill.cgu_code = request.cgu_code

        if request.cgu_name is not None and request.cgu_name != goodwill.cgu_name:
            changes["cgu_name"] = {"old": goodwill.cgu_name, "new": request.cgu_name}
            goodwill.cgu_name = request.cgu_name

        if not changes:
            return self._to_response(goodwill)

        goodwill.updated_at = datetime.now(UTC)
        goodwill.updated_by = updated_by
        goodwill.version += 1

        await self._goodwill_repo.update(goodwill)
        if self._uow:
            await self._uow.commit()

        self._stats["goodwill_updated"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = GoodwillUpdatedEvent(
                    aggregate_id=goodwill.id,
                    aggregate_version=goodwill.version,
                    goodwill_id=goodwill.id,
                    goodwill_number=goodwill.goodwill_number,
                    changes=changes,
                    updated_by=str(updated_by),
                    user_id=str(updated_by),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published GoodwillUpdatedEvent for {goodwill.goodwill_number}")
            except Exception as e:
                logger.warning(f"Failed to publish GoodwillUpdatedEvent: {e}")

        return self._to_response(goodwill)

    # ========================================================================
    # Impairment Testing
    # ========================================================================

    async def test_impairment(
        self,
        request: ImpairmentTestRequest,
        correlation_id: str | None = None,
    ) -> ImpairmentTestResponse:
        """Perform impairment test on goodwill."""
        goodwill = await self._goodwill_repo.get_by_id(request.goodwill_id)
        if not goodwill:
            raise GoodwillNotFoundError(f"Goodwill {request.goodwill_id} not found")

        if goodwill.status not in (GoodwillStatus.ACTIVE, GoodwillStatus.IMPAIRED, GoodwillStatus.PARTIALLY_IMPAIRED):
            raise InvalidImpairmentTestError(
                f"Goodwill is not active (status: {goodwill.status.value})"
            )

        carrying = goodwill.carrying_amount
        recoverable = request.recoverable_amount
        journal_id = None
        old_status = goodwill.status

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
            goodwill.status = (
                GoodwillStatus.PARTIALLY_IMPAIRED
                if new_carrying > 0 and new_carrying < goodwill.amount
                else GoodwillStatus.IMPAIRED
            )
            goodwill.updated_at = datetime.now(UTC)
            goodwill.version += 1

            await self._goodwill_repo.update(goodwill)

            # Post impairment journal to GL
            if self._ledger_repo:
                journal_id = await self._post_impairment_journal(
                    goodwill.legal_entity_id,
                    impairment_loss,
                    request.test_date,
                    request.created_by,
                )
                await self._goodwill_repo.record_impairment_journal(goodwill.id, journal_id)

            if self._uow:
                await self._uow.commit()

            self._stats["impairments"] += 1

            # --- PUBLISH IMPAIRMENT EVENT ---
            if self._event_publisher:
                try:
                    event = GoodwillImpairedEvent(
                        aggregate_id=goodwill.id,
                        aggregate_version=goodwill.version,
                        goodwill_id=goodwill.id,
                        goodwill_number=goodwill.goodwill_number,
                        impairment_loss=impairment_loss,
                        new_carrying_amount=new_carrying,
                        old_carrying_amount=carrying,
                        test_date=request.test_date,
                        impaired_by=str(request.created_by) if request.created_by else "system",
                        user_id=str(request.created_by) if request.created_by else None,
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event)
                    logger.debug(f"Published GoodwillImpairedEvent for {goodwill.goodwill_number}")
                except Exception as e:
                    logger.warning(f"Failed to publish GoodwillImpairedEvent: {e}")

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
        self,
        legal_entity_id: UUID,
        impairment_loss: Decimal,
        test_date: date,
        user_id: UUID | None,
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
        correlation_id: str | None = None,
    ) -> Decimal:
        """Reverse a previous impairment loss."""
        goodwill = await self._goodwill_repo.get_by_id(goodwill_id)
        if not goodwill:
            raise GoodwillNotFoundError(f"Goodwill {goodwill_id} not found")

        if goodwill.status not in (GoodwillStatus.IMPAIRED, GoodwillStatus.PARTIALLY_IMPAIRED):
            raise InvalidImpairmentTestError("Only impaired goodwill can be reversed")

        old_carrying = goodwill.carrying_amount
        new_carrying = old_carrying + reversal_amount
        if new_carrying > goodwill.amount:
            new_carrying = goodwill.amount

        actual_reversal = new_carrying - old_carrying
        old_status = goodwill.status

        goodwill.carrying_amount = new_carrying
        goodwill.impairment_loss_total = max(
            Decimal("0"), (goodwill.impairment_loss_total or Decimal("0")) - actual_reversal
        )
        goodwill.last_reversal_date = reversal_date
        goodwill.last_reversal_amount = actual_reversal
        goodwill.status = (
            GoodwillStatus.ACTIVE
            if new_carrying == goodwill.amount
            else GoodwillStatus.PARTIALLY_IMPAIRED
        )
        goodwill.updated_at = datetime.now(UTC)
        goodwill.updated_by = user_id
        goodwill.version += 1

        await self._goodwill_repo.update(goodwill)
        if self._uow:
            await self._uow.commit()

        self._stats["reversals"] += 1

        # --- PUBLISH REVERSAL EVENT ---
        if self._event_publisher and actual_reversal > 0:
            try:
                event = GoodwillImpairmentReversedEvent(
                    aggregate_id=goodwill.id,
                    aggregate_version=goodwill.version,
                    goodwill_id=goodwill.id,
                    goodwill_number=goodwill.goodwill_number,
                    reversal_amount=actual_reversal,
                    new_carrying_amount=new_carrying,
                    old_carrying_amount=old_carrying,
                    reversal_date=reversal_date,
                    reason=reason,
                    reversed_by=str(user_id),
                    user_id=str(user_id),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published GoodwillImpairmentReversedEvent for {goodwill.goodwill_number}")
            except Exception as e:
                logger.warning(f"Failed to publish GoodwillImpairmentReversedEvent: {e}")

        logger.info(f"Goodwill {goodwill.goodwill_number} impairment reversed by {actual_reversal}")
        return actual_reversal

    # ========================================================================
    # Amortization
    # ========================================================================

    async def amortize_goodwill(
        self,
        goodwill_id: UUID,
        amortization_amount: Decimal,
        period: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> Decimal:
        """Amortize goodwill over its useful life."""
        goodwill = await self._goodwill_repo.get_by_id(goodwill_id)
        if not goodwill:
            raise GoodwillNotFoundError(f"Goodwill {goodwill_id} not found")

        if goodwill.status == GoodwillStatus.DISPOSED:
            raise GoodwillAlreadyDisposedError("Cannot amortize disposed goodwill")

        if goodwill.carrying_amount < amortization_amount:
            raise InvalidImpairmentTestError("Amortization amount exceeds carrying amount")

        old_carrying = goodwill.carrying_amount
        goodwill.carrying_amount -= amortization_amount
        goodwill.accumulated_amortization = (
            goodwill.accumulated_amortization or Decimal("0")
        ) + amortization_amount
        goodwill.last_amortization_date = datetime.strptime(period, "%Y-%m").date()
        goodwill.updated_at = datetime.now(UTC)
        goodwill.updated_by = user_id
        goodwill.version += 1

        if goodwill.carrying_amount == 0:
            goodwill.status = GoodwillStatus.FULLY_AMORTIZED

        await self._goodwill_repo.update(goodwill)
        if self._uow:
            await self._uow.commit()

        self._stats["amortizations"] += 1

        # --- PUBLISH AMORTIZATION EVENT ---
        if self._event_publisher and amortization_amount > 0:
            try:
                event = GoodwillAmortizedEvent(
                    aggregate_id=goodwill.id,
                    aggregate_version=goodwill.version,
                    goodwill_id=goodwill.id,
                    goodwill_number=goodwill.goodwill_number,
                    amortization_amount=amortization_amount,
                    period=period,
                    new_carrying_amount=goodwill.carrying_amount,
                    old_carrying_amount=old_carrying,
                    is_fully_amortized=goodwill.status == GoodwillStatus.FULLY_AMORTIZED,
                    amortized_by=str(user_id),
                    user_id=str(user_id),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published GoodwillAmortizedEvent for {goodwill.goodwill_number}")
            except Exception as e:
                logger.warning(f"Failed to publish GoodwillAmortizedEvent: {e}")

        logger.info(f"Goodwill {goodwill.goodwill_number} amortized by {amortization_amount}")
        return goodwill.carrying_amount

    # ========================================================================
    # Disposal
    # ========================================================================

    async def dispose_goodwill(
        self,
        request: GoodwillDisposalRequest,
        correlation_id: str | None = None,
    ) -> GoodwillResponse:
        """Dispose goodwill (e.g., when CGU is sold)."""
        goodwill = await self._goodwill_repo.get_by_id(request.goodwill_id)
        if not goodwill:
            raise GoodwillNotFoundError(f"Goodwill {request.goodwill_id} not found")

        if goodwill.status == GoodwillStatus.DISPOSED:
            raise GoodwillAlreadyDisposedError("Goodwill already disposed")

        old_carrying = goodwill.carrying_amount
        gain_loss = request.proceeds - old_carrying

        goodwill.status = GoodwillStatus.DISPOSED
        goodwill.disposal_date = request.disposal_date
        goodwill.disposal_reason = request.reason
        goodwill.disposal_proceeds = request.proceeds
        goodwill.disposal_gain_loss = gain_loss
        goodwill.updated_at = datetime.now(UTC)
        goodwill.updated_by = request.disposed_by
        goodwill.version += 1

        await self._goodwill_repo.update(goodwill)
        if self._uow:
            await self._uow.commit()

        self._stats["disposals"] += 1

        # --- PUBLISH DISPOSAL EVENT ---
        if self._event_publisher:
            try:
                event = GoodwillDisposedEvent(
                    aggregate_id=goodwill.id,
                    aggregate_version=goodwill.version,
                    goodwill_id=goodwill.id,
                    goodwill_number=goodwill.goodwill_number,
                    disposal_date=request.disposal_date,
                    disposal_amount=request.proceeds,
                    carrying_amount=old_carrying,
                    gain_loss=gain_loss,
                    reason=request.reason,
                    disposed_by=str(request.disposed_by) if request.disposed_by else "system",
                    user_id=str(request.disposed_by) if request.disposed_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published GoodwillDisposedEvent for {goodwill.goodwill_number}")
            except Exception as e:
                logger.warning(f"Failed to publish GoodwillDisposedEvent: {e}")

        logger.info(f"Goodwill {goodwill.goodwill_number} disposed. Gain/Loss: {gain_loss}")
        return self._to_response(goodwill)

    # ========================================================================
    # Queries
    # ========================================================================

    async def get_goodwill(self, goodwill_id: UUID) -> GoodwillResponse | None:
        """Get goodwill by ID."""
        goodwill = await self._goodwill_repo.get_by_id(goodwill_id)
        if not goodwill:
            return None
        return self._to_response(goodwill)

    async def list_goodwill_by_entity(self, legal_entity_id: UUID) -> list[GoodwillResponse]:
        """List all goodwill for a legal entity."""
        items = await self._goodwill_repo.list_by_legal_entity(legal_entity_id)
        return [self._to_response(g) for g in items]

    async def list_goodwill_by_cgu(self, cgu_code: str) -> list[GoodwillResponse]:
        """List all goodwill for a CGU."""
        items = await self._goodwill_repo.list_by_cgu(cgu_code)
        return [self._to_response(g) for g in items]

    async def get_active_goodwill(self, legal_entity_id: UUID) -> list[GoodwillResponse]:
        """Get active goodwill for a legal entity."""
        items = await self._goodwill_repo.list_active_goodwill(legal_entity_id)
        return [self._to_response(g) for g in items]

    # ========================================================================
    # Private Helpers
    # ========================================================================

    def _to_response(self, goodwill: Goodwill) -> GoodwillResponse:
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
    "GoodwillAlreadyDisposedError",
    "GoodwillDisposalRequest",
    "GoodwillNotFoundError",
    "GoodwillRecognitionRequest",
    "GoodwillResponse",
    "GoodwillService",
    "GoodwillServiceError",
    "GoodwillUpdateRequest",
    "ImpairmentTestRequest",
    "ImpairmentTestResponse",
    "InvalidImpairmentTestError",
    "create_goodwill_service",
]