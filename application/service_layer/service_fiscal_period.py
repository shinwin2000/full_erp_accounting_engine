# service_fiscal_period.py - Complete rewrite with full implementation

#!/usr/bin/env python3

"""
Module: service_fiscal_period.py
Layer: 8 - Application / Service Layer

Responsibility:
    Service layer for managing fiscal periods (accounting periods).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from domain.fiscal_period.aggregate_root import FiscalPeriod, PeriodStatus, PeriodType
from domain.fiscal_period.domain_events import (
    PeriodClosedEvent,
    PeriodLockedEvent,
    PeriodOpenedEvent,
    PeriodReopenedEvent,
)
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.fiscal_period_repository_port import FiscalPeriodRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class CreatePeriodRequest:
    """Request to create a new fiscal period."""

    legal_entity_id: UUID
    year: int
    month: int
    period_type: str = "MONTHLY"
    start_date: date | None = None
    end_date: date | None = None
    created_by: UUID | None = None


@dataclass(kw_only=True)
class PeriodResponse:
    """Response for fiscal period."""

    period_id: UUID
    legal_entity_id: UUID
    period_type: str
    period_number: int
    year: int
    start_date: date
    end_date: date
    status: str
    created_by: str | None
    created_at: datetime
    closed_at: datetime | None = None
    closed_by: str | None = None


@dataclass(kw_only=True)
class ClosePeriodRequest:
    """Request to close a period."""

    legal_entity_id: UUID
    year: int
    month: int
    closed_by: UUID
    closed_at: datetime | None = None


@dataclass(kw_only=True)
class LockPeriodRequest:
    """Request to lock a period."""

    legal_entity_id: UUID
    year: int
    month: int
    locked_by: UUID


@dataclass(kw_only=True)
class ReopenPeriodRequest:
    """Request to reopen a period."""

    legal_entity_id: UUID
    year: int
    month: int
    reopened_by: UUID
    reason: str | None = None


# ============================================================================
# Exceptions
# ============================================================================


class FiscalPeriodServiceError(Exception):
    pass


class PeriodNotFoundError(FiscalPeriodServiceError):
    pass


class PeriodAlreadyExistsError(FiscalPeriodServiceError):
    pass


class PeriodAlreadyClosedError(FiscalPeriodServiceError):
    pass


class PeriodAlreadyOpenError(FiscalPeriodServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class FiscalPeriodService:
    """
    Service for managing fiscal periods.
    """

    def __init__(
        self,
        period_repo: FiscalPeriodRepositoryPort,
        uow: UnitOfWorkPort,
        event_publisher: EventPublisherPort | None = None,
    ):
        if period_repo is None:
            raise ValueError("period_repo is required")
        if uow is None:
            raise ValueError("uow is required")

        self._period_repo = period_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._stats = {"periods_created": 0, "periods_closed": 0, "periods_locked": 0}

        logger.info("FiscalPeriodService initialized")

    async def get_period(self, legal_entity_id: UUID, year: int, month: int) -> FiscalPeriod | None:
        """Get fiscal period by year and month."""
        return await self._period_repo.get_by_year_month(legal_entity_id, year, month)

    async def get_period_by_id(self, period_id: UUID) -> FiscalPeriod | None:
        """Get fiscal period by ID."""
        return await self._period_repo.get_by_id(period_id)

    async def get_current_period(
        self, legal_entity_id: UUID, as_of_date: date | None = None
    ) -> FiscalPeriod | None:
        """Get the current open fiscal period."""
        check_date = as_of_date or date.today()
        periods = await self._period_repo.list_by_year(legal_entity_id, check_date.year)

        for period in periods:
            if (
                period.start_date <= check_date <= period.end_date
                and period.status == PeriodStatus.OPEN
            ):
                return period
        return None

    async def create_period(
        self,
        request: CreatePeriodRequest,
        correlation_id: str | None = None,
    ) -> FiscalPeriod:
        """Create a new fiscal period."""
        existing = await self._period_repo.get_by_year_month(
            request.legal_entity_id, request.year, request.month
        )
        if existing:
            raise PeriodAlreadyExistsError(
                f"Period {request.year}-{request.month:02d} already exists"
            )

        # Calculate start and end dates
        start_date = request.start_date or date(request.year, request.month, 1)
        if request.end_date:
            end_date = request.end_date
        elif request.month == 12:
            end_date = date(request.year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(request.year, request.month + 1, 1) - timedelta(days=1)

        period = FiscalPeriod(
            period_id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            period_type=PeriodType(request.period_type),
            period_number=request.month,
            year=request.year,
            start_date=start_date,
            end_date=end_date,
            status=PeriodStatus.OPEN,
            created_by=str(request.created_by) if request.created_by else "system",
            version=1,
        )

        await self._period_repo.save(period)
        await self._uow.commit()

        self._stats["periods_created"] += 1

        if self._event_publisher:
            event = PeriodOpenedEvent(
                period_id=period.period_id,
                legal_entity_id=request.legal_entity_id,
                period_year=request.year,
                period_month=request.month,
                user_id=str(request.created_by) if request.created_by else "system",
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id)

        logger.info(f"Fiscal period {request.year}-{request.month:02d} created and opened")
        return period

    async def open_period(
        self,
        legal_entity_id: UUID,
        year: int,
        month: int,
        opened_by: UUID,
        correlation_id: str | None = None,
    ) -> FiscalPeriod:
        """Open a period."""
        period = await self._period_repo.get_by_year_month(legal_entity_id, year, month)
        if not period:
            raise PeriodNotFoundError(f"Period {year}-{month:02d} not found")

        if period.status == PeriodStatus.OPEN:
            raise PeriodAlreadyOpenError(f"Period {year}-{month:02d} is already OPEN")

        updated = period.open(str(opened_by))
        await self._period_repo.save(updated)
        await self._uow.commit()

        if self._event_publisher:
            event = PeriodOpenedEvent(
                period_id=period.period_id,
                legal_entity_id=legal_entity_id,
                period_year=year,
                period_month=month,
                user_id=str(opened_by),
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id)

        logger.info(f"Period {year}-{month:02d} opened by {opened_by}")
        return updated

    async def lock_period(
        self,
        legal_entity_id: UUID,
        year: int,
        month: int,
        locked_by: UUID,
        correlation_id: str | None = None,
    ) -> FiscalPeriod:
        """Lock a period."""
        period = await self._period_repo.get_by_year_month(legal_entity_id, year, month)
        if not period:
            raise PeriodNotFoundError(f"Period {year}-{month:02d} not found")

        if period.status != PeriodStatus.OPEN:
            raise FiscalPeriodServiceError(f"Cannot lock period in status {period.status.value}")

        updated = period.lock(str(locked_by))
        await self._period_repo.save(updated)
        await self._uow.commit()

        self._stats["periods_locked"] += 1

        if self._event_publisher:
            event = PeriodLockedEvent(
                period_id=period.period_id,
                legal_entity_id=legal_entity_id,
                period_year=year,
                period_month=month,
                user_id=str(locked_by),
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id)

        logger.info(f"Period {year}-{month:02d} locked by {locked_by}")
        return updated

    async def close_period(
        self,
        request: ClosePeriodRequest,
        correlation_id: str | None = None,
    ) -> FiscalPeriod:
        """Close a period."""
        period = await self._period_repo.get_by_year_month(
            request.legal_entity_id, request.year, request.month
        )
        if not period:
            raise PeriodNotFoundError(f"Period {request.year}-{request.month:02d} not found")

        if period.status == PeriodStatus.CLOSED:
            raise PeriodAlreadyClosedError(
                f"Period {request.year}-{request.month:02d} is already CLOSED"
            )

        # Lock first if open
        if period.status == PeriodStatus.OPEN:
            period = await self.lock_period(
                request.legal_entity_id,
                request.year,
                request.month,
                request.closed_by,
                correlation_id,
            )

        updated = period.close(str(request.closed_by))
        await self._period_repo.save(updated)
        await self._uow.commit()

        self._stats["periods_closed"] += 1

        if self._event_publisher:
            event = PeriodClosedEvent(
                period_id=period.period_id,
                legal_entity_id=request.legal_entity_id,
                period_year=request.year,
                period_month=request.month,
                user_id=str(request.closed_by),
                closed_at=request.closed_at or datetime.now(UTC),
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id)

        logger.info(f"Period {request.year}-{request.month:02d} closed by {request.closed_by}")
        return updated

    async def reopen_period(
        self,
        request: ReopenPeriodRequest,
        correlation_id: str | None = None,
    ) -> FiscalPeriod:
        """
        Reopen a closed period.

        Business rule: Only periods with status CLOSED can be reopened.
        """
        period = await self._period_repo.get_by_year_month(
            request.legal_entity_id, request.year, request.month
        )
        if not period:
            raise PeriodNotFoundError(f"Period {request.year}-{request.month:02d} not found")

        # FIX: Added validation - period must be CLOSED before reopening
        if period.status == PeriodStatus.OPEN:
            raise PeriodAlreadyOpenError(
                f"Period {request.year}-{request.month:02d} is already OPEN"
            )

        # Additional safety: ensure period is CLOSED (not LOCKED or other status)
        if period.status != PeriodStatus.CLOSED:
            raise FiscalPeriodServiceError(
                f"Period {request.year}-{request.month:02d} must be CLOSED to reopen (current: {period.status.value})"
            )

        updated = period.open(str(request.reopened_by))
        await self._period_repo.save(updated)
        await self._uow.commit()

        if self._event_publisher:
            event = PeriodReopenedEvent(
                period_id=period.period_id,
                legal_entity_id=request.legal_entity_id,
                period_year=request.year,
                period_month=request.month,
                user_id=str(request.reopened_by),
                reason=request.reason,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id)

        logger.warning(
            f"Period {request.year}-{request.month:02d} reopened by {request.reopened_by}"
        )
        return updated

    async def validate_period_for_posting(
        self, legal_entity_id: UUID, transaction_date: date
    ) -> bool:
        """Check if the period containing the transaction date is open for posting."""
        period = await self.get_current_period(legal_entity_id, transaction_date)
        if not period:
            return False
        return period.status == PeriodStatus.OPEN

    async def list_periods(
        self,
        legal_entity_id: UUID,
        from_year: int | None = None,
        to_year: int | None = None,
        status: PeriodStatus | None = None,
    ) -> list[FiscalPeriod]:
        """List fiscal periods for a legal entity."""
        return await self._period_repo.list_by_legal_entity(
            legal_entity_id=legal_entity_id, from_year=from_year, to_year=to_year, status=status
        )

    async def get_periods_by_year(self, legal_entity_id: UUID, year: int) -> list[FiscalPeriod]:
        """Get all periods for a specific year."""
        return await self._period_repo.list_by_year(legal_entity_id, year)

    async def get_next_period(
        self, legal_entity_id: UUID, year: int, month: int
    ) -> FiscalPeriod | None:
        """Get the next fiscal period."""
        if month == 12:
            return await self._period_repo.get_by_year_month(legal_entity_id, year + 1, 1)
        else:
            return await self._period_repo.get_by_year_month(legal_entity_id, year, month + 1)

    async def get_previous_period(
        self, legal_entity_id: UUID, year: int, month: int
    ) -> FiscalPeriod | None:
        """Get the previous fiscal period."""
        if month == 1:
            return await self._period_repo.get_by_year_month(legal_entity_id, year - 1, 12)
        else:
            return await self._period_repo.get_by_year_month(legal_entity_id, year, month - 1)

    def _to_response(self, period: FiscalPeriod) -> PeriodResponse:
        return PeriodResponse(
            period_id=period.period_id,
            legal_entity_id=period.legal_entity_id,
            period_type=period.period_type.value,
            period_number=period.period_number,
            year=period.year,
            start_date=period.start_date,
            end_date=period.end_date,
            status=period.status.value,
            created_by=period.created_by,
            created_at=period.created_at,
            closed_at=getattr(period, "closed_at", None),
            closed_by=getattr(period, "closed_by", None),
        )

    def get_stats(self) -> dict[str, int]:
        """Get service statistics."""
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_fiscal_period_service(
    period_repo: FiscalPeriodRepositoryPort,
    uow: UnitOfWorkPort,
    event_publisher: EventPublisherPort | None = None,
) -> FiscalPeriodService:
    return FiscalPeriodService(period_repo, uow, event_publisher)


__all__ = [
    "ClosePeriodRequest",
    "CreatePeriodRequest",
    "FiscalPeriodService",
    "FiscalPeriodServiceError",
    "LockPeriodRequest",
    "PeriodAlreadyClosedError",
    "PeriodAlreadyExistsError",
    "PeriodAlreadyOpenError",
    "PeriodNotFoundError",
    "PeriodResponse",
    "ReopenPeriodRequest",
    "create_fiscal_period_service",
]