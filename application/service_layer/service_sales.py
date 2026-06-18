# service_sales.py - Complete rewrite with full implementation

#!/usr/bin/env python3
"""
Module: service_sales.py
Layer: Application / Service Layer
Responsibility: Service untuk sales (penjualan) dengan fitur lengkap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from ports.primary.sales_repository_port import SalesRepositoryPort

    from ports.primary.event_publisher_port import EventPublisherPort
    from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class SalesItem:
    """Item dalam transaksi penjualan."""

    product_id: UUID
    product_code: str
    product_name: str
    quantity: Decimal
    unit_price: Decimal
    discount_percentage: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("11")

    @property
    def subtotal(self) -> Decimal:
        return self.quantity * self.unit_price

    @property
    def discount_amount(self) -> Decimal:
        return self.subtotal * self.discount_percentage / Decimal("100")

    @property
    def net_amount(self) -> Decimal:
        return self.subtotal - self.discount_amount

    @property
    def tax_amount(self) -> Decimal:
        return self.net_amount * self.tax_rate / Decimal("100")

    @property
    def total_amount(self) -> Decimal:
        return self.net_amount + self.tax_amount


@dataclass(kw_only=True)
class SalesTransaction:
    """Transaksi penjualan."""

    id: UUID
    legal_entity_id: UUID
    transaction_number: str
    transaction_date: date
    customer_id: UUID
    customer_name: str
    items: list[SalesItem]
    total_amount: Decimal
    status: str = "DRAFT"
    created_at: datetime = field(default_factory=lambda: datetime.utcnow())
    created_by: UUID | None = None
    updated_at: datetime | None = None


@dataclass(kw_only=True)
class CreateSalesRequest:
    legal_entity_id: UUID
    transaction_date: date
    customer_id: UUID
    customer_name: str
    items: list[dict[str, Any]]
    payment_method: str = "CASH"
    notes: str | None = None


@dataclass(kw_only=True)
class SalesResponse:
    transaction_id: UUID
    transaction_number: str
    transaction_date: date
    customer_id: UUID
    customer_name: str
    total_amount: Decimal
    status: str
    created_at: datetime


# ============================================================================
# Exceptions
# ============================================================================


class SalesServiceError(Exception):
    pass


class SalesTransactionNotFoundError(SalesServiceError):
    pass


class InsufficientStockError(SalesServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class SalesService:
    """
    Service layer untuk operasi sales.
    """

    def __init__(
        self,
        sales_repo: SalesRepositoryPort,
        inventory_repo: Any = None,
        uow: UnitOfWorkPort | None = None,
        event_publisher: EventPublisherPort | None = None,
    ):
        self._sales_repo = sales_repo
        self._inventory_repo = inventory_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._stats = {"transactions_created": 0, "transactions_approved": 0}

        logger.info("SalesService initialized")

    async def create_sales_transaction(
        self, request: CreateSalesRequest, user_id: UUID, correlation_id: str | None = None
    ) -> SalesResponse:
        """Create a new sales transaction."""
        # Validate items
        items = []
        total_amount = Decimal("0")

        for item_data in request.items:
            # Check inventory if inventory repo available
            if self._inventory_repo:
                stock = await self._inventory_repo.get_current_stock(
                    item_data["product_id"], request.legal_entity_id
                )
                if stock < Decimal(str(item_data["quantity"])):
                    raise InsufficientStockError(
                        f"Insufficient stock for product {item_data['product_id']}"
                    )

            sales_item = SalesItem(
                product_id=UUID(item_data["product_id"]),
                product_code=item_data.get("product_code", ""),
                product_name=item_data.get("product_name", ""),
                quantity=Decimal(str(item_data["quantity"])),
                unit_price=Decimal(str(item_data["unit_price"])),
                discount_percentage=Decimal(str(item_data.get("discount_percentage", 0))),
                tax_rate=Decimal(str(item_data.get("tax_rate", 11))),
            )
            items.append(sales_item)
            total_amount += sales_item.total_amount

        # Generate transaction number
        trans_number = await self._generate_transaction_number(request.legal_entity_id)

        transaction = SalesTransaction(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            transaction_number=trans_number,
            transaction_date=request.transaction_date,
            customer_id=request.customer_id,
            customer_name=request.customer_name,
            items=items,
            total_amount=total_amount,
            status="DRAFT",
            created_by=user_id,
            created_at=datetime.utcnow(),
        )

        await self._sales_repo.save_transaction(transaction)
        if self._uow:
            await self._uow.commit()

        self._stats["transactions_created"] += 1

        logger.info(f"Sales transaction {trans_number} created for {request.customer_name}")

        return SalesResponse(
            transaction_id=transaction.id,
            transaction_number=transaction.transaction_number,
            transaction_date=transaction.transaction_date,
            customer_id=transaction.customer_id,
            customer_name=transaction.customer_name,
            total_amount=transaction.total_amount,
            status=transaction.status,
            created_at=transaction.created_at,
        )

    async def get_sales_by_period(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
        status: str | None = None,
    ) -> list[SalesTransaction]:
        """Get sales transactions within a period."""
        logger.info(
            f"Getting sales for legal entity {legal_entity_id} from {from_date} to {to_date}"
        )

        transactions = await self._sales_repo.list_by_period(
            legal_entity_id=legal_entity_id,
            from_date=from_date,
            to_date=to_date,
            status=status,
        )

        return transactions

    async def get_sales_transaction(self, transaction_id: UUID) -> SalesTransaction | None:
        """Get sales transaction by ID."""
        return await self._sales_repo.get_by_id(transaction_id)

    async def approve_sales_transaction(
        self, transaction_id: UUID, approver_id: UUID, correlation_id: str | None = None
    ) -> SalesResponse:
        """Approve a sales transaction."""
        transaction = await self._sales_repo.get_by_id(transaction_id)
        if not transaction:
            raise SalesTransactionNotFoundError(f"Transaction {transaction_id} not found")

        transaction.status = "APPROVED"
        transaction.updated_at = datetime.utcnow()

        await self._sales_repo.save_transaction(transaction)
        if self._uow:
            await self._uow.commit()

        self._stats["transactions_approved"] += 1

        return SalesResponse(
            transaction_id=transaction.id,
            transaction_number=transaction.transaction_number,
            transaction_date=transaction.transaction_date,
            customer_id=transaction.customer_id,
            customer_name=transaction.customer_name,
            total_amount=transaction.total_amount,
            status=transaction.status,
            created_at=transaction.created_at,
        )

    async def cancel_sales_transaction(
        self, transaction_id: UUID, reason: str, user_id: UUID
    ) -> SalesResponse:
        """Cancel a sales transaction."""
        transaction = await self._sales_repo.get_by_id(transaction_id)
        if not transaction:
            raise SalesTransactionNotFoundError(f"Transaction {transaction_id} not found")

        if transaction.status in ("APPROVED", "COMPLETED"):
            raise SalesServiceError("Cannot cancel approved or completed transaction")

        transaction.status = "CANCELLED"
        transaction.updated_at = datetime.utcnow()

        await self._sales_repo.save_transaction(transaction)
        if self._uow:
            await self._uow.commit()

        return SalesResponse(
            transaction_id=transaction.id,
            transaction_number=transaction.transaction_number,
            transaction_date=transaction.transaction_date,
            customer_id=transaction.customer_id,
            customer_name=transaction.customer_name,
            total_amount=transaction.total_amount,
            status=transaction.status,
            created_at=transaction.created_at,
        )

    async def _generate_transaction_number(self, legal_entity_id: UUID) -> str:
        """Generate unique sales transaction number."""
        last = await self._sales_repo.get_last_transaction_number(legal_entity_id)
        if not last:
            return f"INV-{datetime.utcnow().year}-00001"
        seq = int(last.split("-")[-1]) + 1
        return f"INV-{datetime.utcnow().year}-{seq:05d}"

    def get_stats(self) -> dict[str, int]:
        """Get service statistics."""
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_sales_service(
    sales_repo: SalesRepositoryPort,
    inventory_repo: Any = None,
    uow: UnitOfWorkPort | None = None,
    event_publisher: EventPublisherPort | None = None,
) -> SalesService:
    return SalesService(sales_repo, inventory_repo, uow, event_publisher)


__all__ = [
    "SalesItem",
    "SalesService",
    "SalesServiceError",
    "SalesTransaction",
    "SalesTransactionNotFoundError",
    "create_sales_service",
]
