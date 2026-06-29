# service_retainer.py - Complete service for Retainer Contracts

#!/usr/bin/env python3

"""
Module: service_retainer.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service untuk mengelola Retainer Contracts.
    Mempublikasikan RetainerContractActivatedEvent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from ports.primary.event_publisher_port import EventPublisherPort

# Import domain events
from application.events import RetainerContractActivatedEvent

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class RetainerStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


# ============================================================================
# Domain Models
# ============================================================================


@dataclass(kw_only=True)
class RetainerContract:
    id: UUID = field(default_factory=uuid4)
    legal_entity_id: UUID
    customer_id: UUID
    contract_number: str
    description: str
    start_date: date
    end_date: date | None = None
    monthly_fee: Decimal
    total_amount: Decimal
    remaining_balance: Decimal
    status: RetainerStatus = RetainerStatus.DRAFT
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1


# ============================================================================
# Exceptions
# ============================================================================


class RetainerServiceError(Exception):
    pass


class RetainerNotFoundError(RetainerServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class RetainerService:
    """
    Service untuk mengelola Retainer Contracts.
    """

    def __init__(self, event_publisher: EventPublisherPort | None = None):
        self._contracts: dict[UUID, RetainerContract] = {}
        self._event_publisher = event_publisher
        self._stats = {"contracts_created": 0, "contracts_activated": 0}

        logger.info("RetainerService initialized")

    async def create_retainer_contract(
        self,
        legal_entity_id: UUID,
        customer_id: UUID,
        contract_number: str,
        description: str,
        start_date: date,
        monthly_fee: Decimal,
        end_date: date | None = None,
        created_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> RetainerContract:
        """Create a new retainer contract."""
        if end_date and start_date > end_date:
            raise RetainerServiceError("Start date must be before end date")

        # Calculate total amount (12 months)
        total_amount = monthly_fee * 12

        contract = RetainerContract(
            legal_entity_id=legal_entity_id,
            customer_id=customer_id,
            contract_number=contract_number,
            description=description,
            start_date=start_date,
            end_date=end_date,
            monthly_fee=monthly_fee,
            total_amount=total_amount,
            remaining_balance=total_amount,
            status=RetainerStatus.DRAFT,
            created_by=created_by,
            version=1,
        )

        self._contracts[contract.id] = contract
        self._stats["contracts_created"] += 1

        logger.info(f"Retainer contract created: {contract_number}")
        return contract

    async def activate_retainer_contract(
        self,
        contract_id: UUID,
        activated_by: UUID,
        correlation_id: str | None = None,
    ) -> RetainerContract:
        """Activate a retainer contract."""
        contract = self._contracts.get(contract_id)
        if not contract:
            raise RetainerNotFoundError(f"Contract {contract_id} not found")

        if contract.status != RetainerStatus.DRAFT:
            raise RetainerServiceError(f"Contract status is {contract.status.value}")

        contract.status = RetainerStatus.ACTIVE
        contract.updated_at = datetime.now(UTC)
        contract.version += 1
        self._contracts[contract_id] = contract
        self._stats["contracts_activated"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = RetainerContractActivatedEvent(
                    aggregate_id=contract.id,
                    aggregate_version=contract.version,
                    contract_id=contract.id,
                    contract_number=contract.contract_number,
                    customer_id=contract.customer_id,
                    start_date=contract.start_date,
                    monthly_fee=contract.monthly_fee,
                    activated_by=str(activated_by),
                    user_id=str(activated_by),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id)
                logger.debug(f"Published RetainerContractActivatedEvent for {contract.contract_number}")
            except Exception as e:
                logger.warning(f"Failed to publish RetainerContractActivatedEvent: {e}")

        logger.info(f"Retainer contract activated: {contract.contract_number}")
        return contract

    async def cancel_retainer_contract(
        self,
        contract_id: UUID,
        reason: str,
        cancelled_by: UUID,
        correlation_id: str | None = None,
    ) -> RetainerContract:
        """Cancel a retainer contract."""
        contract = self._contracts.get(contract_id)
        if not contract:
            raise RetainerNotFoundError(f"Contract {contract_id} not found")

        if contract.status in (RetainerStatus.CANCELLED, RetainerStatus.EXPIRED):
            raise RetainerServiceError(f"Contract already {contract.status.value}")

        contract.status = RetainerStatus.CANCELLED
        contract.updated_at = datetime.now(UTC)
        contract.version += 1
        self._contracts[contract_id] = contract

        return contract

    async def suspend_retainer_contract(
        self,
        contract_id: UUID,
        reason: str,
        suspended_by: UUID,
        correlation_id: str | None = None,
    ) -> RetainerContract:
        """Suspend a retainer contract."""
        contract = self._contracts.get(contract_id)
        if not contract:
            raise RetainerNotFoundError(f"Contract {contract_id} not found")

        if contract.status != RetainerStatus.ACTIVE:
            raise RetainerServiceError(f"Only active contracts can be suspended")

        contract.status = RetainerStatus.SUSPENDED
        contract.updated_at = datetime.now(UTC)
        contract.version += 1
        self._contracts[contract_id] = contract

        return contract

    async def get_contract(self, contract_id: UUID) -> RetainerContract | None:
        return self._contracts.get(contract_id)

    async def list_contracts(
        self,
        legal_entity_id: UUID,
        status: str | None = None,
    ) -> list[RetainerContract]:
        result = [c for c in self._contracts.values() if c.legal_entity_id == legal_entity_id]
        if status:
            result = [c for c in result if c.status.value == status]
        return result

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_retainer_service(
    event_publisher: EventPublisherPort | None = None,
) -> RetainerService:
    return RetainerService(event_publisher=event_publisher)


__all__ = [
    "RetainerContract",
    "RetainerNotFoundError",
    "RetainerService",
    "RetainerServiceError",
    "RetainerStatus",
    "create_retainer_service",
]