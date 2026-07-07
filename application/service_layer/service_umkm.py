# service_umkm.py - Complete rewrite with full event publishing
# v5.9.0 - Refactored event publishing into single _publish_event method to reduce
#          broad-except warnings and improve maintainability.

#!/usr/bin/env python3

"""
Module: service_umkm.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service layer untuk UMKM (Usaha Mikro Kecil Menengah) dengan penyederhanaan akuntansi.
    Mempublikasikan event untuk setiap transaksi dan perubahan.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

# Import domain events
from application.events import (
    TransactionCreatedEvent,
    TransactionDeletedEvent,
    TransactionRecordedEvent,
    TransactionUpdatedEvent,
)

from domain.umkm_simplified.domain_events import TransactionRecorded as DomainTransactionRecorded
from domain.umkm_simplified.simplified_journal_entity import SimplifiedJournal, TransactionType
from domain.umkm_simplified.tax_compliance_helper import TaxComplianceHelper
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.umkm_repository_port import UMKMRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class UMKMTransactionType(str, Enum):
    """Transaction type for UMKM."""

    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


class UMKMPaymentMethod(str, Enum):
    """Payment method for UMKM."""

    CASH = "CASH"
    BANK = "BANK"
    QRIS = "QRIS"
    E_WALLET = "E_WALLET"


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class TransactionRequest:
    """Request for recording transaction."""

    legal_entity_id: UUID
    transaction_date: date
    amount: Decimal
    category: str
    description: str
    transaction_type: str = "INCOME"
    payment_method: str = "CASH"
    reference_number: str | None = None
    customer_name: str | None = None


@dataclass(kw_only=True)
class UpdateTransactionRequest:
    """Request for updating transaction."""

    transaction_id: UUID
    transaction_date: date | None = None
    amount: Decimal | None = None
    category: str | None = None
    description: str | None = None
    transaction_type: str | None = None
    payment_method: str | None = None
    reference_number: str | None = None
    customer_name: str | None = None


@dataclass(kw_only=True)
class TransactionResponse:
    """Response for transaction."""

    transaction_id: UUID
    transaction_date: date
    amount: Decimal
    category: str
    description: str
    transaction_type: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(kw_only=True)
class IncomeStatementSimple:
    """Simple income statement."""

    period_start: date
    period_end: date
    total_income: Decimal
    total_expense: Decimal
    net_profit: Decimal
    tax_due: Decimal
    net_after_tax: Decimal


@dataclass(kw_only=True)
class CashFlowSimple:
    """Simple cash flow statement."""

    period_start: date
    period_end: date
    beginning_cash: Decimal
    cash_in: Decimal
    cash_out: Decimal
    ending_cash: Decimal


@dataclass(kw_only=True)
class TaxSummary:
    """Tax summary."""

    period: str
    gross_revenue: Decimal
    tax_rate: Decimal
    tax_due: Decimal
    is_submitted: bool


# ============================================================================
# Exceptions
# ============================================================================


class UMKMServiceError(Exception):
    pass


class TransactionNotFoundError(UMKMServiceError):
    pass


class InvalidTransactionTypeError(UMKMServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class UMKMService:
    """
    Service untuk UMKM (akuntansi sederhana).
    Mempublikasikan event untuk setiap transaksi.
    """

    def __init__(
        self,
        umkm_repo: UMKMRepositoryPort,
        uow: UnitOfWorkPort | None = None,
        event_publisher: EventPublisherPort | None = None,
    ):
        if umkm_repo is None:
            raise ValueError("umkm_repo is required")

        self._umkm_repo = umkm_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._tax_helper = TaxComplianceHelper()
        self._stats = {"transactions": 0, "transactions_updated": 0, "transactions_deleted": 0, "tax_submissions": 0}

        logger.info("UMKMService initialized")

    # ==================== EVENT PUBLISHING HELPER ====================

    async def _publish_event(self, event: Any, log_context: str, correlation_id: str | None = None) -> None:
        """
        Publish an event safely, catching and logging any exception.
        Preserves the two-argument publish signature (event, correlation_id).
        """
        if not self._event_publisher:
            return
        try:
            await self._event_publisher.publish(event, correlation_id)
            logger.debug(f"Published {event.__class__.__name__} for {log_context}")
        except Exception as e:
            logger.warning(f"Failed to publish {event.__class__.__name__} for {log_context}: {e}")

    # ========================================================================
    # Transaction Recording
    # ========================================================================

    async def record_transaction(
        self,
        request: TransactionRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> TransactionResponse:
        """
        Record a simple transaction (income or expense).
        """
        if request.transaction_type not in ("INCOME", "EXPENSE"):
            raise InvalidTransactionTypeError(f"Invalid type: {request.transaction_type}")

        # Create simplified journal entry
        transaction = SimplifiedJournal(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            transaction_date=request.transaction_date,
            amount=request.amount,
            transaction_type=TransactionType(request.transaction_type),
            category=request.category,
            description=request.description,
            payment_method=request.payment_method,
            reference_number=request.reference_number,
            customer_name=request.customer_name,
            created_by=user_id,
            created_at=datetime.now(UTC),
            updated_at=None,
            updated_by=None,
            version=1,
        )

        await self._umkm_repo.save_transaction(transaction)
        if self._uow:
            await self._uow.commit()

        self._stats["transactions"] += 1

        # --- PUBLISH EVENTS ---
        if self._event_publisher:
            # 1. TransactionCreatedEvent
            event_created = TransactionCreatedEvent(
                aggregate_id=transaction.id,
                aggregate_version=transaction.version,
                transaction_id=transaction.id,
                transaction_type=transaction.transaction_type.value,
                amount=transaction.amount,
                description=transaction.description,
                transaction_date=transaction.transaction_date,
                created_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._publish_event(event_created, f"Transaction {transaction.id} (created)", correlation_id)

            # 2. TransactionRecordedEvent (UMKM specific)
            event_recorded = DomainTransactionRecorded(
                transaction_id=transaction.id,
                amount=transaction.amount,
                transaction_type=transaction.transaction_type.value,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._publish_event(event_recorded, f"Transaction {transaction.id} (recorded)", correlation_id)

        logger.info(f"UMKM transaction recorded: {request.transaction_type} {request.amount}")
        return self._to_response(transaction)

    async def update_transaction(
        self,
        request: UpdateTransactionRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> TransactionResponse:
        """
        Update an existing transaction.
        """
        transaction = await self._umkm_repo.get_transaction(request.transaction_id)
        if not transaction:
            raise TransactionNotFoundError(f"Transaction {request.transaction_id} not found")

        changes = {}

        if request.transaction_date is not None and request.transaction_date != transaction.transaction_date:
            changes["transaction_date"] = {"old": transaction.transaction_date, "new": request.transaction_date}
            transaction.transaction_date = request.transaction_date

        if request.amount is not None and request.amount != transaction.amount:
            changes["amount"] = {"old": transaction.amount, "new": request.amount}
            transaction.amount = request.amount

        if request.category is not None and request.category != transaction.category:
            changes["category"] = {"old": transaction.category, "new": request.category}
            transaction.category = request.category

        if request.description is not None and request.description != transaction.description:
            changes["description"] = {"old": transaction.description, "new": request.description}
            transaction.description = request.description

        if request.transaction_type is not None:
            new_type = TransactionType(request.transaction_type)
            if new_type != transaction.transaction_type:
                changes["transaction_type"] = {"old": transaction.transaction_type.value, "new": new_type.value}
                transaction.transaction_type = new_type

        if request.payment_method is not None and request.payment_method != transaction.payment_method:
            changes["payment_method"] = {"old": transaction.payment_method, "new": request.payment_method}
            transaction.payment_method = request.payment_method

        if request.reference_number is not None and request.reference_number != transaction.reference_number:
            changes["reference_number"] = {"old": transaction.reference_number, "new": request.reference_number}
            transaction.reference_number = request.reference_number

        if request.customer_name is not None and request.customer_name != transaction.customer_name:
            changes["customer_name"] = {"old": transaction.customer_name, "new": request.customer_name}
            transaction.customer_name = request.customer_name

        if not changes:
            return self._to_response(transaction)

        transaction.updated_at = datetime.now(UTC)
        transaction.updated_by = user_id
        transaction.version += 1

        await self._umkm_repo.save_transaction(transaction)
        if self._uow:
            await self._uow.commit()

        self._stats["transactions_updated"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = TransactionUpdatedEvent(
                aggregate_id=transaction.id,
                aggregate_version=transaction.version,
                transaction_id=transaction.id,
                changes=changes,
                updated_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Transaction {transaction.id} (updated)", correlation_id)

        logger.info(f"UMKM transaction updated: {transaction.id}")
        return self._to_response(transaction)

    async def delete_transaction(
        self,
        transaction_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> bool:
        """
        Delete a transaction (soft delete).
        """
        transaction = await self._umkm_repo.get_transaction(transaction_id)
        if not transaction:
            raise TransactionNotFoundError(f"Transaction {transaction_id} not found")

        # Soft delete
        transaction.is_deleted = True
        transaction.deleted_at = datetime.now(UTC)
        transaction.deleted_by = user_id
        transaction.version += 1

        await self._umkm_repo.save_transaction(transaction)
        if self._uow:
            await self._uow.commit()

        self._stats["transactions_deleted"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = TransactionDeletedEvent(
                aggregate_id=transaction.id,
                aggregate_version=transaction.version,
                transaction_id=transaction.id,
                deleted_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Transaction {transaction.id} (deleted)", correlation_id)

        logger.info(f"UMKM transaction deleted: {transaction_id}")
        return True

    async def get_transaction(self, transaction_id: UUID) -> SimplifiedJournal | None:
        """Get transaction by ID."""
        return await self._umkm_repo.get_transaction(transaction_id)

    async def get_transactions(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
        transaction_type: str | None = None,
        limit: int = 100,
    ) -> list[TransactionResponse]:
        """Get list of transactions."""
        txs = await self._umkm_repo.list_transactions(
            legal_entity_id, from_date, to_date, transaction_type, limit
        )

        return [self._to_response(t) for t in txs]

    # ========================================================================
    # Financial Reports (Simple)
    # ========================================================================

    async def get_income_statement(
        self,
        legal_entity_id: UUID,
        period_start: date,
        period_end: date,
    ) -> IncomeStatementSimple:
        """
        Simple income statement (cash basis).
        """
        incomes = await self._umkm_repo.sum_transactions(
            legal_entity_id, period_start, period_end, "INCOME"
        )
        expenses = await self._umkm_repo.sum_transactions(
            legal_entity_id, period_start, period_end, "EXPENSE"
        )

        net_profit = incomes - expenses

        # Calculate UMKM final tax (0.5% of gross revenue)
        tax_due = Decimal("0")
        if incomes > 0:
            tax_rate = await self._tax_helper.get_tax_rate(incomes, period_start.year)
            tax_due = (incomes * tax_rate).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

        net_after_tax = net_profit - tax_due

        return IncomeStatementSimple(
            period_start=period_start,
            period_end=period_end,
            total_income=incomes,
            total_expense=expenses,
            net_profit=net_profit,
            tax_due=tax_due,
            net_after_tax=net_after_tax,
        )

    async def get_cash_flow(
        self,
        legal_entity_id: UUID,
        period_start: date,
        period_end: date,
    ) -> CashFlowSimple:
        """
        Simple cash flow statement.
        """
        # Beginning cash balance (from previous period)
        beginning_cash = await self._umkm_repo.get_cash_balance_as_of(
            legal_entity_id, period_start - timedelta(days=1)
        )
        cash_in = await self._umkm_repo.sum_transactions(
            legal_entity_id, period_start, period_end, "INCOME"
        )
        cash_out = await self._umkm_repo.sum_transactions(
            legal_entity_id, period_start, period_end, "EXPENSE"
        )
        ending_cash = beginning_cash + cash_in - cash_out

        return CashFlowSimple(
            period_start=period_start,
            period_end=period_end,
            beginning_cash=beginning_cash,
            cash_in=cash_in,
            cash_out=cash_out,
            ending_cash=ending_cash,
        )

    # ========================================================================
    # Tax Compliance
    # ========================================================================

    async def calculate_monthly_tax(
        self,
        legal_entity_id: UUID,
        year: int,
        month: int,
    ) -> TaxSummary:
        """
        Calculate UMKM final tax for a month (PPH Final 0.5%).
        """
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        gross_revenue = await self._umkm_repo.sum_transactions(
            legal_entity_id, start_date, end_date, "INCOME"
        )
        tax_rate = Decimal("0.005")  # 0.5%
        tax_due = (gross_revenue * tax_rate).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

        return TaxSummary(
            period=f"{year}-{month:02d}",
            gross_revenue=gross_revenue,
            tax_rate=tax_rate,
            tax_due=tax_due,
            is_submitted=False,
        )

    async def submit_tax_report(
        self,
        legal_entity_id: UUID,
        year: int,
        month: int,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> bool:
        """
        Submit monthly tax report to tax authority.
        """
        tax_summary = await self.calculate_monthly_tax(legal_entity_id, year, month)

        # Submit via tax helper
        success = await self._tax_helper.submit_tax(
            legal_entity_id, tax_summary.period, tax_summary.tax_due
        )

        if success:
            await self._umkm_repo.mark_tax_submitted(legal_entity_id, year, month)
            if self._uow:
                await self._uow.commit()
            self._stats["tax_submissions"] += 1

            # --- PUBLISH EVENT ---
            if self._event_publisher:
                event = TransactionRecordedEvent(
                    aggregate_id=uuid4(),
                    aggregate_version=1,
                    transaction_id=uuid4(),
                    transaction_type="TAX_SUBMISSION",
                    amount=tax_summary.tax_due,
                    description=f"Tax submission for {tax_summary.period}",
                    user_id=str(user_id),
                    occurred_at=datetime.now(UTC),
                )
                await self._publish_event(event, f"Tax submission {tax_summary.period}", correlation_id)

        return success

    # ========================================================================
    # Dashboard
    # ========================================================================

    async def get_dashboard(
        self,
        legal_entity_id: UUID,
        as_of_date: date,
    ) -> dict[str, Any]:
        """
        Dashboard data for business owner.
        """
        # Month-to-date
        month_start = date(as_of_date.year, as_of_date.month, 1)
        month_income = await self._umkm_repo.sum_transactions(
            legal_entity_id, month_start, as_of_date, "INCOME"
        )
        month_expense = await self._umkm_repo.sum_transactions(
            legal_entity_id, month_start, as_of_date, "EXPENSE"
        )
        month_profit = month_income - month_expense

        # Year-to-date
        year_start = date(as_of_date.year, 1, 1)
        ytd_income = await self._umkm_repo.sum_transactions(
            legal_entity_id, year_start, as_of_date, "INCOME"
        )
        ytd_expense = await self._umkm_repo.sum_transactions(
            legal_entity_id, year_start, as_of_date, "EXPENSE"
        )
        ytd_profit = ytd_income - ytd_expense

        # Cash balance
        cash_balance = await self._umkm_repo.get_cash_balance_as_of(legal_entity_id, as_of_date)

        # Recent transactions
        recent = await self.get_transactions(
            legal_entity_id, as_of_date - timedelta(days=30), as_of_date, limit=10
        )

        # Calculate tax for current month
        tax_summary = await self.calculate_monthly_tax(
            legal_entity_id, as_of_date.year, as_of_date.month
        )

        return {
            "as_of_date": as_of_date.isoformat(),
            "month_income": float(month_income),
            "month_expense": float(month_expense),
            "month_profit": float(month_profit),
            "ytd_income": float(ytd_income),
            "ytd_expense": float(ytd_expense),
            "ytd_profit": float(ytd_profit),
            "cash_balance": float(cash_balance),
            "tax_due_for_month": float(tax_summary.tax_due),
            "recent_transactions": [
                {
                    "date": t.transaction_date.isoformat(),
                    "type": t.transaction_type,
                    "amount": float(t.amount),
                    "description": t.description,
                }
                for t in recent
            ],
        }

    # ========================================================================
    # Bulk Import
    # ========================================================================

    async def import_transactions_from_csv(
        self,
        legal_entity_id: UUID,
        csv_content: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> dict[str, int]:
        """
        Bulk import transactions from CSV.
        CSV format: date,amount,type,category,description,payment_method,reference
        """
        reader = csv.DictReader(io.StringIO(csv_content))
        success = 0
        failed = 0

        for row in reader:
            try:
                req = TransactionRequest(
                    legal_entity_id=legal_entity_id,
                    transaction_date=datetime.strptime(row["date"], "%Y-%m-%d").date(),
                    amount=Decimal(row["amount"]),
                    transaction_type=row["type"].upper(),
                    category=row["category"],
                    description=row.get("description", ""),
                    payment_method=row.get("payment_method", "CASH"),
                    reference_number=row.get("reference"),
                )
                await self.record_transaction(req, user_id, correlation_id)
                success += 1
            except Exception as e:
                logger.warning(f"Import failed for row: {e}")
                failed += 1

        return {"success": success, "failed": failed}

    # ========================================================================
    # Category Summary
    # ========================================================================

    async def get_category_summary(
        self,
        legal_entity_id: UUID,
        period_start: date,
        period_end: date,
    ) -> dict[str, dict[str, Decimal]]:
        """
        Get income and expense breakdown by category.
        """
        transactions = await self._umkm_repo.list_transactions(
            legal_entity_id, period_start, period_end, None, 10000
        )

        income_by_category = {}
        expense_by_category = {}

        for tx in transactions:
            if tx.transaction_type == TransactionType.INCOME:
                income_by_category[tx.category] = (
                    income_by_category.get(tx.category, Decimal("0")) + tx.amount
                )
            else:
                expense_by_category[tx.category] = (
                    expense_by_category.get(tx.category, Decimal("0")) + tx.amount
                )

        return {
            "income_by_category": {k: float(v) for k, v in income_by_category.items()},
            "expense_by_category": {k: float(v) for k, v in expense_by_category.items()},
        }

    # ========================================================================
    # Private Helpers
    # ========================================================================

    def _to_response(self, transaction: SimplifiedJournal) -> TransactionResponse:
        return TransactionResponse(
            transaction_id=transaction.id,
            transaction_date=transaction.transaction_date,
            amount=transaction.amount,
            transaction_type=transaction.transaction_type.value,
            category=transaction.category,
            description=transaction.description,
            created_at=transaction.created_at,
        )

    def get_stats(self) -> dict[str, int]:
        """Get service statistics."""
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_umkm_service(
    umkm_repo: UMKMRepositoryPort,
    uow: UnitOfWorkPort | None = None,
    event_publisher: EventPublisherPort | None = None,
) -> UMKMService:
    return UMKMService(umkm_repo, uow, event_publisher)


# Alias for backward compatibility
UMKMSimplifiedService = UMKMService


__all__ = [
    "InvalidTransactionTypeError",
    "TransactionNotFoundError",
    "UMKMService",
    "UMKMServiceError",
    "UMKMSimplifiedService",
    "UpdateTransactionRequest",
    "create_umkm_service",
]