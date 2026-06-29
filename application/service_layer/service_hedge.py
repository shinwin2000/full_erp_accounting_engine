# service_hedge.py - Complete rewrite with full event publishing

#!/usr/bin/env python3

"""
Module: service_hedge.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service for hedge accounting (IFRS 9 / PSAK 71).
    Mempublikasikan semua domain events yang sesuai.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from domain.hedge.aggregate_root import HedgeRelationship, HedgeStatus, HedgeType
from domain.hedge.hedge_effectiveness_tester import HedgeEffectivenessTester
from domain.hedge.hedged_item import HedgedItemType
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.hedge_repository_port import HedgeRepositoryPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

# Import domain events
from domain.hedge.domain_events import (
    HedgeAmountReclassifiedEvent,
    HedgeCancelledEvent,
    HedgeDesignatedEvent,
    HedgeDiscontinuedEvent,
    HedgeEffectivenessTestedEvent,
    HedgeFairValueAdjustedEvent,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class HedgeTypeEnum(str, Enum):
    """Type of hedge relationship."""

    FAIR_VALUE = "FAIR_VALUE"
    CASH_FLOW = "CASH_FLOW"
    NET_INVESTMENT = "NET_INVESTMENT"


class HedgeStatusEnum(str, Enum):
    """Status of hedge relationship."""

    DESIGNATED = "DESIGNATED"
    ACTIVE = "ACTIVE"
    INEFFECTIVE = "INEFFECTIVE"
    DISCONTINUED = "DISCONTINUED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"  # Added


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class HedgeDesignationRequest:
    """Request to designate a hedge relationship."""

    legal_entity_id: UUID
    hedge_instrument_id: UUID
    hedged_item_id: UUID
    designation_date: date
    description: str
    hedge_type: str
    risk_components: list[str] = field(default_factory=list)
    effectiveness_threshold_lower: Decimal = Decimal("0.80")
    effectiveness_threshold_upper: Decimal = Decimal("1.25")


@dataclass(kw_only=True)
class HedgeDesignationResponse:
    """Response for hedge designation."""

    hedge_id: UUID
    hedge_number: str
    legal_entity_id: UUID
    hedge_type: str
    designation_date: date
    description: str
    status: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(kw_only=True)
class EffectivenessTestRequest:
    """Request for effectiveness test."""

    hedge_id: UUID
    test_date: date
    data_points: list[tuple[date, Decimal, Decimal]]
    prospective: bool = True


@dataclass(kw_only=True)
class EffectivenessTestResponse:
    """Response for effectiveness test."""

    hedge_id: UUID
    test_date: date
    is_effective: bool
    ratio: Decimal
    variance: Decimal
    message: str
    test_type: str


@dataclass(kw_only=True)
class HedgeJournalRequest:
    """Request for hedge journal entry."""

    hedge_id: UUID
    period_end_date: date
    description: str
    fair_value_change_hedge: Decimal
    fair_value_change_hedged: Decimal
    user_id: UUID


@dataclass(kw_only=True)
class HedgeJournalResponse:
    """Response for hedge journal entry."""

    journal_id: UUID
    hedge_id: UUID
    period_end_date: date
    debit_account: str
    credit_account: str
    amount: Decimal
    description: str


@dataclass(kw_only=True)
class ReclassificationRequest:
    """Request to reclassify amount from hedge reserve to P/L."""

    hedge_id: UUID
    reclassification_date: date
    amount: Decimal
    description: str
    user_id: UUID


# ============================================================================
# Exceptions
# ============================================================================


class HedgeServiceError(Exception):
    pass


class HedgeNotFoundError(HedgeServiceError):
    pass


class HedgeEffectivenessError(HedgeServiceError):
    pass


class HedgeDesignationError(HedgeServiceError):
    pass


class HedgeCancellationError(HedgeServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class HedgeService:
    """
    Service untuk hedge accounting sesuai IFRS 9 / PSAK 71.
    Mempublikasikan event untuk setiap operasi.
    """

    def __init__(
        self,
        hedge_repo: HedgeRepositoryPort,
        ledger_repo: LedgerRepositoryPort | None = None,
        uow: UnitOfWorkPort | None = None,
        event_publisher: EventPublisherPort | None = None,
    ):
        if hedge_repo is None:
            raise ValueError("hedge_repo is required")

        self._hedge_repo = hedge_repo
        self._ledger_repo = ledger_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._effectiveness_tester = HedgeEffectivenessTester()
        self._stats = {
            "hedges_designated": 0,
            "tests_performed": 0,
            "journals_posted": 0,
            "hedges_cancelled": 0,
            "hedges_discontinued": 0,
            "reclassifications": 0,
        }

        logger.info("HedgeService initialized")

    # ========================================================================
    # Hedge Designation
    # ========================================================================

    async def designate_hedge(
        self, request: HedgeDesignationRequest, user_id: UUID, correlation_id: str | None = None
    ) -> HedgeDesignationResponse:
        """Designate a hedging relationship."""
        # Validate hedge type
        try:
            hedge_type = HedgeType(request.hedge_type.upper())
        except ValueError:
            raise HedgeDesignationError(f"Invalid hedge type: {request.hedge_type}")

        # Get instrument and hedged item
        instrument = await self._hedge_repo.get_hedge_instrument(request.hedge_instrument_id)
        if not instrument:
            raise HedgeDesignationError(f"Hedge instrument {request.hedge_instrument_id} not found")

        hedged_item = await self._hedge_repo.get_hedged_item(request.hedged_item_id)
        if not hedged_item:
            raise HedgeDesignationError(f"Hedged item {request.hedged_item_id} not found")

        # Generate hedge number
        hedge_number = await self._generate_hedge_number(request.legal_entity_id)

        # Create hedge relationship
        hedge = HedgeRelationship(
            id=uuid4(),
            hedge_number=hedge_number,
            legal_entity_id=request.legal_entity_id,
            hedge_type=hedge_type,
            status=HedgeStatus.DESIGNATED,
            designation_date=request.designation_date,
            description=request.description,
            hedge_instrument_id=instrument.id,
            hedged_item_id=hedged_item.id,
            risk_components=request.risk_components,
            effectiveness_threshold_lower=request.effectiveness_threshold_lower,
            effectiveness_threshold_upper=request.effectiveness_threshold_upper,
            created_by=user_id,
            created_at=datetime.utcnow(),
        )

        await self._hedge_repo.save_hedge(hedge)
        if self._uow:
            await self._uow.commit()

        self._stats["hedges_designated"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = HedgeDesignatedEvent(
                aggregate_id=hedge.id,
                aggregate_version=1,
                hedge_id=hedge.id,
                hedge_number=hedge.hedge_number,
                legal_entity_id=hedge.legal_entity_id,
                hedge_type=hedge.hedge_type.value,
                user_id=user_id,
                correlation_id=correlation_id,
                occurred_at=datetime.utcnow(),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published HedgeDesignatedEvent for {hedge.hedge_number}")

        logger.info(f"Hedge {hedge_number} designated successfully")

        return HedgeDesignationResponse(
            hedge_id=hedge.id,
            hedge_number=hedge.hedge_number,
            legal_entity_id=hedge.legal_entity_id,
            hedge_type=hedge.hedge_type.value,
            designation_date=hedge.designation_date,
            description=hedge.description,
            status=hedge.status.value,
            created_at=hedge.created_at,
        )

    async def _generate_hedge_number(self, legal_entity_id: UUID) -> str:
        """Generate unique hedge number."""
        last = await self._hedge_repo.get_last_hedge_number(legal_entity_id)
        seq = int(last.split("-")[-1]) + 1 if last else 1
        return f"HEDGE-{legal_entity_id.hex[:6]}-{seq:06d}"

    # ========================================================================
    # Effectiveness Testing
    # ========================================================================

    async def test_effectiveness(
        self,
        request: EffectivenessTestRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> EffectivenessTestResponse:
        """Test hedge effectiveness."""
        hedge = await self._hedge_repo.get_hedge_by_id(request.hedge_id)
        if not hedge:
            raise HedgeNotFoundError(f"Hedge {request.hedge_id} not found")

        if hedge.status not in (HedgeStatus.DESIGNATED, HedgeStatus.ACTIVE):
            raise HedgeEffectivenessError(f"Hedge {hedge.hedge_number} is not active for testing")

        self._stats["tests_performed"] += 1

        # Run effectiveness test
        if request.prospective:
            (
                is_effective,
                ratio,
                variance,
                message,
            ) = await self._effectiveness_tester.prospective_test(
                hedge=hedge, as_of_date=request.test_date, data_points=request.data_points
            )
            test_type = "PROSPECTIVE"
        else:
            (
                is_effective,
                ratio,
                variance,
                message,
            ) = await self._effectiveness_tester.retrospective_test(
                hedge=hedge, as_of_date=request.test_date, data_points=request.data_points
            )
            test_type = "RETROSPECTIVE"

        # Save test result
        test_result = {
            "hedge_id": hedge.id,
            "test_date": request.test_date,
            "test_type": test_type,
            "is_effective": is_effective,
            "ratio": ratio,
            "variance": variance,
            "message": message,
            "data_points_count": len(request.data_points),
        }
        await self._hedge_repo.save_effectiveness_test(test_result, user_id)

        # Update hedge status if retrospective test fails
        if not request.prospective and not is_effective:
            hedge.status = HedgeStatus.INEFFECTIVE
            await self._hedge_repo.save_hedge(hedge)

        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = HedgeEffectivenessTestedEvent(
                aggregate_id=hedge.id,
                aggregate_version=hedge.version,
                hedge_id=hedge.id,
                hedge_number=hedge.hedge_number,
                test_date=request.test_date,
                test_type=test_type,
                is_effective=is_effective,
                ratio=ratio,
                variance=variance,
                user_id=user_id,
                correlation_id=correlation_id,
                occurred_at=datetime.utcnow(),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(
                f"Published HedgeEffectivenessTestedEvent for {hedge.hedge_number}: {'Effective' if is_effective else 'Ineffective'}"
            )

        logger.info(
            f"Effectiveness test for hedge {hedge.hedge_number}: {test_type} - {'Effective' if is_effective else 'Ineffective'}"
        )

        return EffectivenessTestResponse(
            hedge_id=hedge.id,
            test_date=request.test_date,
            test_type=test_type,
            is_effective=is_effective,
            ratio=ratio,
            variance=variance,
            message=message,
        )

    # ========================================================================
    # Hedge Adjustment and Journal Entries
    # ========================================================================

    async def record_fair_value_change(
        self,
        request: HedgeJournalRequest,
        correlation_id: str | None = None,
    ) -> list[HedgeJournalResponse]:
        """Record fair value changes of hedge instrument and hedged item."""
        hedge = await self._hedge_repo.get_hedge_by_id(request.hedge_id)
        if not hedge:
            raise HedgeNotFoundError(f"Hedge {request.hedge_id} not found")

        if hedge.status not in (HedgeStatus.ACTIVE, HedgeStatus.DESIGNATED):
            raise HedgeServiceError(f"Hedge {hedge.hedge_number} is not active")

        # Calculate ineffectiveness
        ineffectiveness = abs(request.fair_value_change_hedge - request.fair_value_change_hedged)

        # Determine accounts based on hedge type
        if hedge.hedge_type == HedgeType.FAIR_VALUE:
            debit_account = self._get_hedged_item_account(hedge)
            credit_account = (
                "P/L_HEDGE_INEFFECTIVENESS" if ineffectiveness > 0 else "EQUITY_HEDGE_RESERVE"
            )
            amount = request.fair_value_change_hedge
        elif hedge.hedge_type == HedgeType.CASH_FLOW:
            debit_account = "ASSET_HEDGE_RESERVE"
            credit_account = (
                "DERIVATIVE_ASSET"
                if request.fair_value_change_hedge > 0
                else "DERIVATIVE_LIABILITY"
            )
            amount = request.fair_value_change_hedge
        else:
            raise HedgeServiceError(f"Unsupported hedge type: {hedge.hedge_type.value}")

        # Post journal to ledger
        journal_id = None
        if self._ledger_repo:
            lines = [
                {
                    "account_code": debit_account,
                    "debit": amount if amount > 0 else Decimal("0"),
                    "credit": Decimal("0") if amount > 0 else -amount,
                    "description": request.description,
                },
                {
                    "account_code": credit_account,
                    "debit": Decimal("0") if amount > 0 else -amount,
                    "credit": amount if amount > 0 else Decimal("0"),
                    "description": request.description,
                },
            ]
            journal_id = await self._ledger_repo.post_journal(
                legal_entity_id=hedge.legal_entity_id,
                journal_date=request.period_end_date,
                period=f"{request.period_end_date.year}-{request.period_end_date.month:02d}",
                description=f"Hedge adjustment: {request.description}",
                lines=lines,
                source_system="hedge_accounting",
                user_id=request.user_id,
            )
            self._stats["journals_posted"] += 1

        # Save adjustment record
        adjustment = {
            "hedge_id": hedge.id,
            "adjustment_date": request.period_end_date,
            "change_in_hedge_instrument": request.fair_value_change_hedge,
            "change_in_hedged_item": request.fair_value_change_hedged,
            "ineffectiveness": ineffectiveness,
            "journal_id": journal_id,
            "description": request.description,
        }
        await self._hedge_repo.save_hedge_adjustment(adjustment, request.user_id)

        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = HedgeFairValueAdjustedEvent(
                aggregate_id=hedge.id,
                aggregate_version=hedge.version,
                hedge_id=hedge.id,
                hedge_number=hedge.hedge_number,
                adjustment_amount=request.fair_value_change_hedge,
                ineffectiveness=ineffectiveness,
                user_id=request.user_id,
                correlation_id=correlation_id,
                occurred_at=datetime.utcnow(),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published HedgeFairValueAdjustedEvent for {hedge.hedge_number}")

        return [
            HedgeJournalResponse(
                journal_id=journal_id or uuid4(),
                hedge_id=hedge.id,
                period_end_date=request.period_end_date,
                debit_account=debit_account,
                credit_account=credit_account,
                amount=amount,
                description=request.description,
            )
        ]

    def _get_hedged_item_account(self, hedge: HedgeRelationship) -> str:
        """Determine the appropriate account for the hedged item."""
        if hedge.hedged_item_type == HedgedItemType.INVENTORY:
            return "INVENTORY_HEDGE_ADJUSTMENT"
        elif hedge.hedged_item_type == HedgedItemType.FIXED_ASSET:
            return "PPE_HEDGE_ADJUSTMENT"
        elif hedge.hedged_item_type == HedgedItemType.LOAN:
            return "LOAN_HEDGE_ADJUSTMENT"
        else:
            return "OTHER_HEDGED_ITEM_ADJUSTMENT"

    # ========================================================================
    # Hedge Discontinuation
    # ========================================================================

    async def discontinue_hedge(
        self,
        hedge_id: UUID,
        discontinuation_date: date,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Discontinue a hedging relationship."""
        hedge = await self._hedge_repo.get_hedge_by_id(hedge_id)
        if not hedge:
            raise HedgeNotFoundError(f"Hedge {hedge_id} not found")

        hedge.status = HedgeStatus.DISCONTINUED
        hedge.discontinued_date = discontinuation_date
        hedge.discontinued_reason = reason

        await self._hedge_repo.save_hedge(hedge)
        if self._uow:
            await self._uow.commit()

        self._stats["hedges_discontinued"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = HedgeDiscontinuedEvent(
                aggregate_id=hedge.id,
                aggregate_version=hedge.version,
                hedge_id=hedge.id,
                hedge_number=hedge.hedge_number,
                discontinuation_date=discontinuation_date,
                reason=reason,
                user_id=user_id,
                correlation_id=correlation_id,
                occurred_at=datetime.utcnow(),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published HedgeDiscontinuedEvent for {hedge.hedge_number}")

        logger.info(f"Hedge {hedge.hedge_number} discontinued on {discontinuation_date}")

    # ========================================================================
    # Hedge Cancellation
    # ========================================================================

    async def cancel_hedge(
        self,
        hedge_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Cancel a hedge relationship (voluntary termination)."""
        hedge = await self._hedge_repo.get_hedge_by_id(hedge_id)
        if not hedge:
            raise HedgeNotFoundError(f"Hedge {hedge_id} not found")

        if hedge.status == HedgeStatus.CANCELLED:
            raise HedgeCancellationError(f"Hedge {hedge.hedge_number} is already cancelled")

        if hedge.status == HedgeStatus.DISCONTINUED:
            raise HedgeCancellationError(
                f"Hedge {hedge.hedge_number} is discontinued and cannot be cancelled"
            )

        hedge.status = HedgeStatus.CANCELLED
        hedge.cancelled_date = datetime.utcnow().date()
        hedge.cancelled_reason = reason

        await self._hedge_repo.save_hedge(hedge)
        if self._uow:
            await self._uow.commit()

        self._stats["hedges_cancelled"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = HedgeCancelledEvent(
                aggregate_id=hedge.id,
                aggregate_version=hedge.version,
                hedge_id=hedge.id,
                hedge_number=hedge.hedge_number,
                reason=reason,
                user_id=user_id,
                correlation_id=correlation_id,
                occurred_at=datetime.utcnow(),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published HedgeCancelledEvent for {hedge.hedge_number}")

        logger.info(f"Hedge {hedge.hedge_number} cancelled: {reason}")

    # ========================================================================
    # Reclassification
    # ========================================================================

    async def reclassify_amount(
        self,
        request: ReclassificationRequest,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Reclassify amount from hedge reserve to P/L (cash flow hedge)."""
        hedge = await self._hedge_repo.get_hedge_by_id(request.hedge_id)
        if not hedge:
            raise HedgeNotFoundError(f"Hedge {request.hedge_id} not found")

        if hedge.hedge_type != HedgeType.CASH_FLOW:
            raise HedgeServiceError("Reclassification only applies to cash flow hedges")

        if hedge.status not in (HedgeStatus.ACTIVE, HedgeStatus.DISCONTINUED):
            raise HedgeServiceError(
                f"Hedge {hedge.hedge_number} is not eligible for reclassification"
            )

        # Post reclassification journal
        journal_id = None
        if self._ledger_repo:
            lines = [
                {
                    "account_code": "EQUITY_HEDGE_RESERVE",
                    "debit": request.amount,
                    "credit": Decimal("0"),
                    "description": request.description,
                },
                {
                    "account_code": "P/L_HEDGE_RECLASSIFICATION",
                    "debit": Decimal("0"),
                    "credit": request.amount,
                    "description": request.description,
                },
            ]
            journal_id = await self._ledger_repo.post_journal(
                legal_entity_id=hedge.legal_entity_id,
                journal_date=request.reclassification_date,
                period=f"{request.reclassification_date.year}-{request.reclassification_date.month:02d}",
                description=f"Hedge reclassification: {request.description}",
                lines=lines,
                source_system="hedge_accounting",
                user_id=request.user_id,
            )
            self._stats["journals_posted"] += 1

        # Save reclassification record
        reclass_record = {
            "hedge_id": hedge.id,
            "reclassification_date": request.reclassification_date,
            "amount": request.amount,
            "description": request.description,
            "journal_id": journal_id,
        }
        await self._hedge_repo.save_reclassification(reclass_record, request.user_id)

        if self._uow:
            await self._uow.commit()

        self._stats["reclassifications"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = HedgeAmountReclassifiedEvent(
                aggregate_id=hedge.id,
                aggregate_version=hedge.version,
                hedge_id=hedge.id,
                hedge_number=hedge.hedge_number,
                amount=request.amount,
                reclassification_date=request.reclassification_date,
                description=request.description,
                user_id=request.user_id,
                correlation_id=correlation_id,
                occurred_at=datetime.utcnow(),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published HedgeAmountReclassifiedEvent for {hedge.hedge_number}")

        return {
            "hedge_id": hedge.id,
            "hedge_number": hedge.hedge_number,
            "reclassification_date": request.reclassification_date,
            "amount": request.amount,
            "journal_id": journal_id,
            "description": request.description,
        }

    # ========================================================================
    # Queries
    # ========================================================================

    async def get_hedge(self, hedge_id: UUID) -> HedgeDesignationResponse | None:
        """Get hedge by ID."""
        hedge = await self._hedge_repo.get_hedge_by_id(hedge_id)
        if not hedge:
            return None

        return HedgeDesignationResponse(
            hedge_id=hedge.id,
            hedge_number=hedge.hedge_number,
            legal_entity_id=hedge.legal_entity_id,
            hedge_type=hedge.hedge_type.value,
            designation_date=hedge.designation_date,
            description=hedge.description,
            status=hedge.status.value,
            created_at=hedge.created_at,
        )

    async def list_active_hedges(self, legal_entity_id: UUID) -> list[HedgeDesignationResponse]:
        """List active hedges for a legal entity."""
        hedges = await self._hedge_repo.list_hedges_by_entity(
            legal_entity_id, status=HedgeStatus.ACTIVE
        )
        return [
            HedgeDesignationResponse(
                hedge_id=h.id,
                hedge_number=h.hedge_number,
                legal_entity_id=h.legal_entity_id,
                hedge_type=h.hedge_type.value,
                designation_date=h.designation_date,
                description=h.description,
                status=h.status.value,
                created_at=h.created_at,
            )
            for h in hedges
        ]

    def get_stats(self) -> dict[str, int]:
        """Get service statistics."""
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_hedge_service(
    hedge_repo: HedgeRepositoryPort,
    ledger_repo: LedgerRepositoryPort | None = None,
    uow: UnitOfWorkPort | None = None,
    event_publisher: EventPublisherPort | None = None,
) -> HedgeService:
    return HedgeService(hedge_repo, ledger_repo, uow, event_publisher)


__all__ = [
    "EffectivenessTestRequest",
    "EffectivenessTestResponse",
    "HedgeDesignationError",
    "HedgeDesignationRequest",
    "HedgeDesignationResponse",
    "HedgeEffectivenessError",
    "HedgeJournalRequest",
    "HedgeJournalResponse",
    "HedgeNotFoundError",
    "HedgeService",
    "HedgeServiceError",
    "HedgeStatusEnum",
    "HedgeTypeEnum",
    "ReclassificationRequest",
    "create_hedge_service",
]