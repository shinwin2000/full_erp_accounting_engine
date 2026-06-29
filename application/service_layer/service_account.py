# service_account.py - Complete service for Account merging and splitting

#!/usr/bin/env python3

"""
Module: service_account.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service untuk operasi akun (merge, split).
    Mempublikasikan AccountMergedEvent dan AccountSplitEvent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ports.primary.event_publisher_port import EventPublisherPort

# Import domain events
from application.events import AccountMergedEvent, AccountSplitEvent

logger = logging.getLogger(__name__)


# ============================================================================
# Domain Models
# ============================================================================


@dataclass(kw_only=True)
class AccountMergeRequest:
    """Request to merge two accounts."""

    source_account_id: UUID
    target_account_id: UUID
    merge_date: datetime
    reason: str
    merged_by: UUID


@dataclass(kw_only=True)
class AccountSplitRequest:
    """Request to split an account."""

    source_account_id: UUID
    target_account_ids: list[UUID]
    split_date: datetime
    reason: str
    split_by: UUID


# ============================================================================
# Exceptions
# ============================================================================


class AccountServiceError(Exception):
    pass


class AccountNotFoundError(AccountServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class AccountService:
    """
    Service untuk operasi akun (merge dan split).
    Mempublikasikan AccountMergedEvent dan AccountSplitEvent.
    """

    def __init__(self, event_publisher: EventPublisherPort | None = None):
        self._event_publisher = event_publisher
        self._stats = {"merges": 0, "splits": 0}

        logger.info("AccountService initialized")

    async def merge_accounts(
        self,
        request: AccountMergeRequest,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Merge two accounts.
        Source account will be merged into target account.
        """
        # Validate accounts exist (simplified)
        if request.source_account_id == request.target_account_id:
            raise AccountServiceError("Cannot merge an account with itself")

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = AccountMergedEvent(
                    aggregate_id=request.source_account_id,
                    aggregate_version=1,
                    source_account_id=request.source_account_id,
                    target_account_id=request.target_account_id,
                    merge_date=request.merge_date,
                    reason=request.reason,
                    merged_by=str(request.merged_by),
                    user_id=str(request.merged_by),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id)
                logger.debug(f"Published AccountMergedEvent for {request.source_account_id} -> {request.target_account_id}")
            except Exception as e:
                logger.warning(f"Failed to publish AccountMergedEvent: {e}")

        self._stats["merges"] += 1
        return {
            "source_account_id": str(request.source_account_id),
            "target_account_id": str(request.target_account_id),
            "merge_date": request.merge_date.isoformat(),
            "reason": request.reason,
        }

    async def split_account(
        self,
        request: AccountSplitRequest,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Split an account into multiple target accounts.
        """
        if len(request.target_account_ids) < 2:
            raise AccountServiceError("At least 2 target accounts required for split")

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = AccountSplitEvent(
                    aggregate_id=request.source_account_id,
                    aggregate_version=1,
                    source_account_id=request.source_account_id,
                    target_account_ids=request.target_account_ids,
                    split_date=request.split_date,
                    reason=request.reason,
                    split_by=str(request.split_by),
                    user_id=str(request.split_by),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id)
                logger.debug(f"Published AccountSplitEvent for {request.source_account_id}")
            except Exception as e:
                logger.warning(f"Failed to publish AccountSplitEvent: {e}")

        self._stats["splits"] += 1
        return {
            "source_account_id": str(request.source_account_id),
            "target_account_ids": [str(a) for a in request.target_account_ids],
            "split_date": request.split_date.isoformat(),
            "reason": request.reason,
        }

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_account_service(
    event_publisher: EventPublisherPort | None = None,
) -> AccountService:
    return AccountService(event_publisher=event_publisher)


__all__ = [
    "AccountMergeRequest",
    "AccountService",
    "AccountServiceError",
    "AccountSplitRequest",
    "create_account_service",
]