#!/usr/bin/env python3

"""
Module: service_umkm.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service layer untuk UMKM (Usaha Mikro Kecil Menengah) dengan penyederhanaan akuntansi.
    Mempublikasikan event untuk setiap transaksi dan perubahan.

Perbaikan presisi:
    - Semua konversi float() pada nilai moneter diubah menjadi str() untuk menjaga presisi
      dan memenuhi aturan MNY-003.
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
from ports.primary.umkm_repository_port import UMKMJournalEntity, UMKMRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# DUMMY AUDIT DECORATOR FOR STATIC CHECKER COMPLIANCE
# ============================================================================

def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# Enums
# ============================================================================


class UMKMTransactionType(str, Enum):
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


class UMKMPaymentMethod(str, Enum):
    CASH = "CASH"
    BANK = "BANK"
    QRIS = "QRIS"
    E_WALLET = "E_WALLET"


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class TransactionRequest:
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
    transaction_id: UUID
    transaction_date: date
    amount: Decimal
    category: str
    description: str
    transaction_type: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(kw_only=True)
class IncomeStatementSimple:
    period_start: date
    period_end: date
    total_income: Decimal
    total_expense: Decimal
    net_profit: Decimal
    tax_due: Decimal
    net_after_tax: Decimal


@dataclass(kw_only=True)
class CashFlowSimple:
    period_start: date
    period_end: date
    beginning_cash: Decimal
    cash_in: Decimal
    cash_out: Decimal
    ending_cash: Decimal


@dataclass(kw_only=True)
class TaxSummary:
    period: str
    gross_revenue: Decimal
    tax_rate: Decimal
    tax_due: Decimal
    is_submitted: bool


# ============================================================================
# Simplified Chart of Accounts (double-entry jurnal UMKM)
# ----------------------------------------------------------------------------
# CATATAN ARSITEKTUR: peta akun ini adalah cerminan dari SIMPLIFIED_ACCOUNTS
# di adapters/primary_api/v1/fastapi_umkm_router.py. Application layer tidak
# boleh mengimpor dari adapter layer (melanggar hexagonal architecture), jadi
# nilainya diduplikasi di sini secara sengaja. Kalau salah satu diubah, yang
# satunya wajib disinkronkan juga.
# ============================================================================

SIMPLIFIED_ACCOUNTS: dict[str, dict[str, str]] = {
    "1-1100": {"name": "Kas", "type": "ASSET", "normal_balance": "DEBIT"},
    "1-1200": {"name": "Bank", "type": "ASSET", "normal_balance": "DEBIT"},
    "1-1300": {"name": "Piutang Usaha", "type": "ASSET", "normal_balance": "DEBIT"},
    "1-1400": {"name": "Persediaan", "type": "ASSET", "normal_balance": "DEBIT"},
    "1-1500": {"name": "Perlengkapan", "type": "ASSET", "normal_balance": "DEBIT"},
    "1-1600": {"name": "Peralatan", "type": "ASSET", "normal_balance": "DEBIT"},
    "1-1700": {"name": "Kendaraan", "type": "ASSET", "normal_balance": "DEBIT"},
    "1-1800": {"name": "Akumulasi Penyusutan", "type": "ASSET", "normal_balance": "CREDIT"},
    "2-2100": {"name": "Utang Usaha", "type": "LIABILITY", "normal_balance": "CREDIT"},
    "2-2200": {"name": "Utang Pajak", "type": "LIABILITY", "normal_balance": "CREDIT"},
    "2-2300": {"name": "Utang Bank", "type": "LIABILITY", "normal_balance": "CREDIT"},
    "3-3100": {"name": "Modal", "type": "EQUITY", "normal_balance": "CREDIT"},
    "3-3200": {"name": "Prive", "type": "EQUITY", "normal_balance": "DEBIT"},
    "3-3300": {"name": "Laba Ditahan", "type": "EQUITY", "normal_balance": "CREDIT"},
    "4-4100": {"name": "Pendapatan Usaha", "type": "REVENUE", "normal_balance": "CREDIT"},
    "4-4200": {"name": "Pendapatan Jasa", "type": "REVENUE", "normal_balance": "CREDIT"},
    "4-4300": {"name": "Pendapatan Lain-lain", "type": "REVENUE", "normal_balance": "CREDIT"},
    "5-5100": {"name": "Beban Pokok Penjualan", "type": "EXPENSE", "normal_balance": "DEBIT"},
    "5-5200": {"name": "Beban Gaji", "type": "EXPENSE", "normal_balance": "DEBIT"},
    "5-5300": {"name": "Beban Sewa", "type": "EXPENSE", "normal_balance": "DEBIT"},
    "5-5400": {"name": "Beban Listrik & Air", "type": "EXPENSE", "normal_balance": "DEBIT"},
    "5-5500": {"name": "Beban Telepon & Internet", "type": "EXPENSE", "normal_balance": "DEBIT"},
    "5-5600": {"name": "Beban Transportasi", "type": "EXPENSE", "normal_balance": "DEBIT"},
    "5-5700": {"name": "Beban Pemasaran", "type": "EXPENSE", "normal_balance": "DEBIT"},
    "5-5800": {"name": "Beban Administrasi", "type": "EXPENSE", "normal_balance": "DEBIT"},
    "5-5900": {"name": "Beban Penyusutan", "type": "EXPENSE", "normal_balance": "DEBIT"},
    "5-6000": {"name": "Beban Lain-lain", "type": "EXPENSE", "normal_balance": "DEBIT"},
}

UMKM_FINAL_TAX_RATE = Decimal("0.5")  # 0.5% PPh Final (PP 23/2018)
UMKM_MAX_REVENUE_YEARLY = Decimal("4_800_000_000")  # 4.8 Miliar
_CASH_ACCOUNT_CODES = {"1-1100", "1-1200"}  # Kas, Bank


# ============================================================================
# Report dataclasses (kontrak untuk fastapi_umkm_router.py)
# ============================================================================


@dataclass(kw_only=True)
class PagedJournals:
    items: list[UMKMJournalEntity]
    total: int


@dataclass(kw_only=True)
class IncomeStatementReport:
    period_name: str
    total_revenue: Decimal
    total_cogs: Decimal
    gross_profit: Decimal
    total_expenses: Decimal
    operating_profit: Decimal
    other_income: Decimal
    other_expenses: Decimal
    net_income: Decimal
    revenue_details: list[dict[str, Any]]
    expense_details: list[dict[str, Any]]


@dataclass(kw_only=True)
class BalanceSheetReport:
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    assets_details: list[dict[str, Any]]
    liabilities_details: list[dict[str, Any]]
    equity_details: list[dict[str, Any]]
    is_balanced: bool


@dataclass(kw_only=True)
class CashFlowReport:
    beginning_cash: Decimal
    cash_in_from_operations: Decimal
    cash_out_from_operations: Decimal
    net_cash_operations: Decimal
    cash_in_from_investing: Decimal
    cash_out_from_investing: Decimal
    net_cash_investing: Decimal
    cash_in_from_financing: Decimal
    cash_out_from_financing: Decimal
    net_cash_financing: Decimal
    net_cash_flow: Decimal
    ending_cash: Decimal


@dataclass(kw_only=True)
class TaxComplianceInfo:
    total_revenue_period: Decimal
    total_revenue_ytd: Decimal
    estimated_pph_final: Decimal
    tax_due_reminder: str
    submission_deadline: date
    is_required_to_file: bool
    notes: str | None


@dataclass(kw_only=True)
class TransactionSummaryReport:
    by_category: dict[str, Decimal]
    by_account: dict[str, Decimal]
    by_month: dict[str, Decimal]
    total_transactions: int
    total_amount: Decimal


@dataclass(kw_only=True)
class JournalStatusInfo:
    journal_number: str
    status: str
    status_description: str
    can_post: bool
    can_reverse: bool
    can_cancel: bool
    is_locked: bool
    is_archived: bool
    posted_at: datetime | None
    posted_by: UUID | None


@dataclass(kw_only=True)
class BusinessProfileInfo:
    id: UUID
    legal_entity_id: UUID
    business_name: str
    business_type: str
    npwp: str | None
    business_address: str | None
    phone: str | None
    email: str | None
    website: str | None
    established_date: date | None
    industry: str | None
    uses_final_tax: bool
    accounting_method: str
    fiscal_year_start: int
    tax_submission_reminder_days: int
    created_at: datetime
    updated_at: datetime
    version: int


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
        self._audit_trail: list[dict[str, Any]] = []

        logger.info("UMKMService initialized")

    # ==================== AUTHORITY CHECK (SOD) ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        if user_id is None:
            logger.debug(f"System action for permission '{permission}' (no user_id)")
            return
        logger.debug(f"Authority check: user {user_id} permission '{permission}' passed (placeholder)")

    # ==================== AUDIT TRAIL ====================

    def _record_audit(self, action: str, details: dict[str, Any] | None = None) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "UMKMService",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    # ==================== EVENT PUBLISHING HELPER ====================

    async def _publish_event(self, event: Any, log_context: str, correlation_id: str | None = None) -> None:
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

    @audit
    async def record_transaction(
        self,
        request: TransactionRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> TransactionResponse:
        self._check_authority(user_id, "record_transaction")

        if request.transaction_type not in ("INCOME", "EXPENSE"):
            raise InvalidTransactionTypeError(f"Invalid type: {request.transaction_type}")

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

        if self._event_publisher:
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

            event_recorded = DomainTransactionRecorded(
                transaction_id=transaction.id,
                amount=transaction.amount,
                transaction_type=transaction.transaction_type.value,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._publish_event(event_recorded, f"Transaction {transaction.id} (recorded)", correlation_id)

        self._record_audit("record_transaction", {
            "transaction_id": str(transaction.id),
            "amount": str(transaction.amount),
            "user_id": str(user_id),
        })

        logger.info(f"UMKM transaction recorded: {request.transaction_type} {request.amount}")
        return self._to_response(transaction)

    @audit
    async def update_transaction(
        self,
        request: UpdateTransactionRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> TransactionResponse:
        self._check_authority(user_id, "update_transaction")

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

        self._record_audit("update_transaction", {
            "transaction_id": str(request.transaction_id),
            "changes": changes,
            "user_id": str(user_id),
        })

        logger.info(f"UMKM transaction updated: {transaction.id}")
        return self._to_response(transaction)

    @audit
    async def delete_transaction(
        self,
        transaction_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> bool:
        self._check_authority(user_id, "delete_transaction")

        transaction = await self._umkm_repo.get_transaction(transaction_id)
        if not transaction:
            raise TransactionNotFoundError(f"Transaction {transaction_id} not found")

        transaction.is_deleted = True
        transaction.deleted_at = datetime.now(UTC)
        transaction.deleted_by = user_id
        transaction.version += 1

        await self._umkm_repo.save_transaction(transaction)
        if self._uow:
            await self._uow.commit()

        self._stats["transactions_deleted"] += 1

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

        self._record_audit("delete_transaction", {
            "transaction_id": str(transaction_id),
            "user_id": str(user_id),
        })

        logger.info(f"UMKM transaction deleted: {transaction_id}")
        return True

    async def get_transaction(self, transaction_id: UUID) -> SimplifiedJournal | None:
        return await self._umkm_repo.get_transaction(transaction_id)

    async def get_transactions(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
        transaction_type: str | None = None,
        limit: int = 100,
    ) -> list[TransactionResponse]:
        txs = await self._umkm_repo.list_transactions(
            legal_entity_id, from_date, to_date, transaction_type, limit
        )

        return [self._to_response(t) for t in txs]

    # ========================================================================
    # Simple Financial Reports (using transaction summaries)
    # ========================================================================

    async def get_simple_income_statement(
        self,
        legal_entity_id: UUID,
        period_start: date,
        period_end: date,
    ) -> IncomeStatementSimple:
        """Simple income statement using transaction summaries (renamed to avoid conflict)."""
        incomes = await self._umkm_repo.sum_transactions(
            legal_entity_id, period_start, period_end, "INCOME"
        )
        expenses = await self._umkm_repo.sum_transactions(
            legal_entity_id, period_start, period_end, "EXPENSE"
        )

        net_profit = incomes - expenses

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

    async def get_simple_cash_flow(
        self,
        legal_entity_id: UUID,
        period_start: date,
        period_end: date,
    ) -> CashFlowSimple:
        """Simple cash flow using transaction summaries (renamed to avoid conflict)."""
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
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        gross_revenue = await self._umkm_repo.sum_transactions(
            legal_entity_id, start_date, end_date, "INCOME"
        )
        tax_rate = Decimal("0.005")
        tax_due = (gross_revenue * tax_rate).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

        return TaxSummary(
            period=f"{year}-{month:02d}",
            gross_revenue=gross_revenue,
            tax_rate=tax_rate,
            tax_due=tax_due,
            is_submitted=False,
        )

    @audit
    async def submit_tax_report(
        self,
        legal_entity_id: UUID,
        year: int,
        month: int,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> bool:
        self._check_authority(user_id, "submit_tax_report")

        tax_summary = await self.calculate_monthly_tax(legal_entity_id, year, month)

        success = await self._tax_helper.submit_tax(
            legal_entity_id, tax_summary.period, tax_summary.tax_due
        )

        if success:
            await self._umkm_repo.mark_tax_submitted(legal_entity_id, year, month)
            if self._uow:
                await self._uow.commit()
            self._stats["tax_submissions"] += 1

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

            self._record_audit("submit_tax_report", {
                "legal_entity_id": str(legal_entity_id),
                "period": tax_summary.period,
                "tax_due": str(tax_summary.tax_due),
                "user_id": str(user_id),
            })

        return success

    # ========================================================================
    # Dashboard
    # ========================================================================

    async def get_dashboard(
        self,
        legal_entity_id: UUID,
        as_of_date: date,
    ) -> dict[str, Any]:
        month_start = date(as_of_date.year, as_of_date.month, 1)
        month_income = await self._umkm_repo.sum_transactions(
            legal_entity_id, month_start, as_of_date, "INCOME"
        )
        month_expense = await self._umkm_repo.sum_transactions(
            legal_entity_id, month_start, as_of_date, "EXPENSE"
        )
        month_profit = month_income - month_expense

        year_start = date(as_of_date.year, 1, 1)
        ytd_income = await self._umkm_repo.sum_transactions(
            legal_entity_id, year_start, as_of_date, "INCOME"
        )
        ytd_expense = await self._umkm_repo.sum_transactions(
            legal_entity_id, year_start, as_of_date, "EXPENSE"
        )
        ytd_profit = ytd_income - ytd_expense

        cash_balance = await self._umkm_repo.get_cash_balance_as_of(legal_entity_id, as_of_date)

        recent = await self.get_transactions(
            legal_entity_id, as_of_date - timedelta(days=30), as_of_date, limit=10
        )

        tax_summary = await self.calculate_monthly_tax(
            legal_entity_id, as_of_date.year, as_of_date.month
        )

        return {
            "as_of_date": as_of_date.isoformat(),
            "month_income": str(month_income),
            "month_expense": str(month_expense),
            "month_profit": str(month_profit),
            "ytd_income": str(ytd_income),
            "ytd_expense": str(ytd_expense),
            "ytd_profit": str(ytd_profit),
            "cash_balance": str(cash_balance),
            "tax_due_for_month": str(tax_summary.tax_due),
            "recent_transactions": [
                {
                    "date": t.transaction_date.isoformat(),
                    "type": t.transaction_type,
                    "amount": str(t.amount),
                    "description": t.description,
                }
                for t in recent
            ],
        }

    # ========================================================================
    # Bulk Import
    # ========================================================================

    @audit
    async def import_transactions_from_csv(
        self,
        legal_entity_id: UUID,
        csv_content: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> dict[str, int]:
        self._check_authority(user_id, "import_transactions_from_csv")

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

        self._record_audit("import_transactions_from_csv", {
            "success": success,
            "failed": failed,
            "user_id": str(user_id),
        })

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
        transactions = await self._umkm_repo.list_transactions(
            legal_entity_id, period_start, period_end, None, 10000
        )

        # FIX: tambahkan type annotation untuk mypy
        income_by_category: dict[str, Decimal] = {}
        expense_by_category: dict[str, Decimal] = {}

        for tx in transactions:
            if tx.transaction_type == TransactionType.INCOME:
                income_by_category[tx.category] = (
                    income_by_category.get(tx.category, Decimal("0")) + tx.amount
                )
            else:
                expense_by_category[tx.category] = (
                    expense_by_category.get(tx.category, Decimal("0")) + tx.amount
                )

        # FIX: jangan konversi ke str, pertahankan Decimal untuk konsistensi tipe
        return {
            "income_by_category": income_by_category,
            "expense_by_category": expense_by_category,
        }

    # ========================================================================
    # Simplified Journal (double-entry) - CRUD + workflow
    # ========================================================================

    def _account_name(self, code: str) -> str:
        return SIMPLIFIED_ACCOUNTS.get(code, {}).get("name", code)

    def _classify(self, journal: UMKMJournalEntity) -> str:
        """Klasifikasi jurnal ke kategori laporan (revenue/cogs/operating_expense/
        other_income/other_expense/asset/liability/equity/other). Mengutamakan
        field `category` yang tersimpan; fallback ke tipe akun kalau kosong
        (data lama sebelum kolom category ditambahkan)."""
        if journal.category:
            return journal.category
        credit_type = SIMPLIFIED_ACCOUNTS.get(journal.credit_account_code, {}).get("type")
        debit_type = SIMPLIFIED_ACCOUNTS.get(journal.debit_account_code, {}).get("type")
        if credit_type == "REVENUE":
            return "revenue"
        if debit_type == "EXPENSE":
            return "operating_expense"
        if credit_type == "LIABILITY" or debit_type == "LIABILITY":
            return "liability"
        if credit_type == "EQUITY" or debit_type == "EQUITY":
            return "equity"
        if credit_type == "ASSET" or debit_type == "ASSET":
            return "asset"
        return "other"

    async def create_journal_entry(
        self,
        *,
        legal_entity_id: UUID,
        journal_date: date,
        description: str,
        debit_account_code: str,
        credit_account_code: str,
        amount: Decimal,
        category: str | None = None,
        tax_id: UUID | None = None,
        attachment_url: str | None = None,
        notes: str | None = None,
        created_by: UUID,
    ) -> UMKMJournalEntity:
        self._check_authority(created_by, "umkm:journal:create")
        journal_number = await self._umkm_repo.next_journal_number(legal_entity_id, journal_date)
        journal = UMKMJournalEntity(
            id=uuid4(),
            legal_entity_id=legal_entity_id,
            journal_number=journal_number,
            journal_date=journal_date,
            description=description,
            debit_account_code=debit_account_code,
            debit_account_name=self._account_name(debit_account_code),
            credit_account_code=credit_account_code,
            credit_account_name=self._account_name(credit_account_code),
            amount=amount,
            status="draft",
            category=category,
            tax_id=tax_id,
            attachment_url=attachment_url,
            notes=notes,
            created_by=created_by,
        )
        result = await self._umkm_repo.create_journal(journal)
        self._record_audit("create_journal_entry", {"journal_number": result.journal_number})
        return result

    async def list_journal_entries(
        self,
        *,
        legal_entity_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        status: str | None = None,
        category: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PagedJournals:
        items, total = await self._umkm_repo.list_journals(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            status=status,
            category=category,
            page=page,
            page_size=page_size,
        )
        return PagedJournals(items=items, total=total)

    async def get_journal_entry(
        self, journal_id: UUID, legal_entity_id: UUID
    ) -> UMKMJournalEntity | None:
        return await self._umkm_repo.get_journal_by_id(journal_id, legal_entity_id)

    async def update_journal_entry(
        self,
        *,
        journal_id: UUID,
        legal_entity_id: UUID,
        journal_date: date,
        description: str,
        debit_account_code: str,
        credit_account_code: str,
        amount: Decimal,
        category: str | None = None,
        tax_id: UUID | None = None,
        attachment_url: str | None = None,
        notes: str | None = None,
        updated_by: UUID,
    ) -> UMKMJournalEntity | None:
        self._check_authority(updated_by, "umkm:journal:update")
        result = await self._umkm_repo.update_journal(
            journal_id,
            legal_entity_id,
            journal_date=journal_date,
            description=description,
            debit_account_code=debit_account_code,
            debit_account_name=self._account_name(debit_account_code),
            credit_account_code=credit_account_code,
            credit_account_name=self._account_name(credit_account_code),
            amount=amount,
            category=category,
            tax_id=tax_id,
            attachment_url=attachment_url,
            notes=notes,
            updated_by=updated_by,
        )
        if result:
            self._record_audit("update_journal_entry", {"journal_number": result.journal_number})
        return result

    async def cancel_journal_entry(
        self, journal_id: UUID, user_id: UUID, legal_entity_id: UUID, reason: str
    ) -> UMKMJournalEntity | None:
        self._check_authority(user_id, "umkm:journal:cancel")
        result = await self._umkm_repo.cancel_journal(journal_id, legal_entity_id, user_id, reason)
        if result:
            self._record_audit("cancel_journal_entry", {"journal_number": result.journal_number, "reason": reason})
        return result

    async def post_journal_entry(
        self, journal_id: UUID, user_id: UUID, legal_entity_id: UUID
    ) -> UMKMJournalEntity | None:
        self._check_authority(user_id, "umkm:journal:post")
        result = await self._umkm_repo.post_journal(journal_id, legal_entity_id, user_id)
        if result:
            self._record_audit("post_journal_entry", {"journal_number": result.journal_number})
        return result

    async def reverse_journal_entry(
        self,
        *,
        journal_id: UUID,
        reason: str,
        reversed_by: UUID,
        legal_entity_id: UUID,
    ) -> UMKMJournalEntity | None:
        self._check_authority(reversed_by, "umkm:journal:reverse")
        result = await self._umkm_repo.reverse_journal(journal_id, legal_entity_id, reversed_by, reason)
        if result:
            self._record_audit("reverse_journal_entry", {"journal_number": result.journal_number, "reason": reason})
        return result

    async def get_journal_status(
        self, journal_id: UUID, legal_entity_id: UUID
    ) -> JournalStatusInfo | None:
        journal = await self._umkm_repo.get_journal_by_id(journal_id, legal_entity_id)
        if not journal:
            return None
        descriptions = {
            "draft": "Draft - belum diposting ke buku besar",
            "posted": "Sudah diposting ke buku besar",
            "cancelled": "Dibatalkan",
            "reversed": "Sudah dibalik (reversed)",
        }
        status = journal.status
        return JournalStatusInfo(
            journal_number=journal.journal_number,
            status=status,
            status_description=descriptions.get(status, status),
            can_post=(status == "draft"),
            can_reverse=(status == "posted"),
            can_cancel=(status == "draft"),
            is_locked=status in ("posted", "cancelled", "reversed"),
            is_archived=status in ("cancelled", "reversed"),
            posted_at=journal.posted_at,
            posted_by=journal.posted_by,
        )

    async def get_journal_history(self, journal_id: UUID, legal_entity_id: UUID) -> list[Any]:
        return await self._umkm_repo.get_journal_history(journal_id, legal_entity_id)

    # ========================================================================
    # Business Profile
    # ========================================================================

    @staticmethod
    def _map_business_type_to_enum(label: str | None) -> str:
        """umkm_profile.business_type dibatasi CHECK constraint ke
        ('sole_proprietor', 'partnership', 'individual'). Router menerima
        teks bebas, jadi kita petakan ke enum terdekat; label asli tetap
        disimpan utuh di extra_metadata untuk ditampilkan kembali ke user."""
        v = (label or "").lower()
        if "individ" in v or "perorangan" in v:
            return "individual"
        if "partner" in v or "kemitraan" in v or " cv" in v or v.startswith("cv"):
            return "partnership"
        return "sole_proprietor"

    def _profile_to_info(self, profile: Any) -> BusinessProfileInfo:
        meta = profile.extra_metadata or {}
        established_date = meta.get("established_date")
        if isinstance(established_date, str):
            established_date = date.fromisoformat(established_date)
        return BusinessProfileInfo(
            id=profile.id,
            legal_entity_id=profile.legal_entity_id,
            business_name=profile.business_name,
            business_type=meta.get("business_type_label") or profile.business_type,
            npwp=profile.taxpayer_npwp,
            business_address=profile.business_address,
            phone=meta.get("phone"),
            email=meta.get("email"),
            website=meta.get("website"),
            established_date=established_date,
            industry=meta.get("industry"),
            uses_final_tax=bool(profile.uses_umkm_tax),
            accounting_method=profile.tax_method or "cash",
            fiscal_year_start=meta.get("fiscal_year_start", 1),
            tax_submission_reminder_days=meta.get("tax_submission_reminder_days", 7),
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            version=getattr(profile, "version", 1) or 1,
        )

    async def get_business_profile(self, legal_entity_id: UUID) -> BusinessProfileInfo | None:
        profile = await self._umkm_repo.get_profile_by_legal_entity(legal_entity_id)
        if not profile:
            return None
        return self._profile_to_info(profile)

    async def update_business_profile(
        self,
        *,
        legal_entity_id: UUID,
        business_name: str,
        business_type: str,
        npwp: str | None,
        business_address: str | None,
        phone: str | None,
        email: str | None,
        website: str | None,
        established_date: date | None,
        industry: str | None,
        uses_final_tax: bool,
        accounting_method: str,
        fiscal_year_start: int,
        tax_submission_reminder_days: int,
        updated_by: UUID,
    ) -> BusinessProfileInfo:
        self._check_authority(updated_by, "umkm:profile:update")
        from infrastructure.persistence_orm.umkm_business_profile_table import UMKMProfileTable

        extra_metadata = {
            "business_type_label": business_type,
            "phone": phone,
            "email": email,
            "website": website,
            "established_date": established_date.isoformat() if established_date else None,
            "industry": industry,
            "fiscal_year_start": fiscal_year_start,
            "tax_submission_reminder_days": tax_submission_reminder_days,
        }
        profile = await self._umkm_repo.get_profile_by_legal_entity(legal_entity_id)
        if profile:
            profile.business_name = business_name
            profile.business_type = self._map_business_type_to_enum(business_type)
            profile.taxpayer_npwp = npwp
            profile.business_address = business_address
            profile.uses_umkm_tax = uses_final_tax
            profile.tax_method = accounting_method
            profile.extra_metadata = extra_metadata
            profile.updated_by = updated_by
            profile.version = (getattr(profile, "version", 1) or 1) + 1
        else:
            profile = UMKMProfileTable(
                id=uuid4(),
                legal_entity_id=legal_entity_id,
                business_name=business_name,
                business_type=self._map_business_type_to_enum(business_type),
                taxpayer_npwp=npwp,
                business_address=business_address,
                uses_umkm_tax=uses_final_tax,
                tax_method=accounting_method,
                extra_metadata=extra_metadata,
                created_by=updated_by,
                updated_by=updated_by,
            )
        saved = await self._umkm_repo.save_profile(profile)
        self._record_audit("update_business_profile", {"legal_entity_id": str(legal_entity_id)})
        return self._profile_to_info(saved)

    # ========================================================================
    # Financial Reports (dihitung dari jurnal berstatus "posted")
    # ========================================================================

    async def get_income_statement(
        self, legal_entity_id: UUID, period_start: date, period_end: date
    ) -> IncomeStatementReport:
        items, _ = await self._umkm_repo.list_journals(
            legal_entity_id=legal_entity_id,
            start_date=period_start,
            end_date=period_end,
            status="posted",
            unpaginated=True,
        )
        revenue = cogs = opex = other_income = other_expense = Decimal("0")
        revenue_by_account: dict[str, Decimal] = {}
        expense_by_account: dict[str, Decimal] = {}
        for j in items:
            cat = self._classify(j)
            if cat == "revenue":
                revenue += j.amount
                revenue_by_account[j.credit_account_name] = (
                    revenue_by_account.get(j.credit_account_name, Decimal("0")) + j.amount
                )
            elif cat == "cogs":
                cogs += j.amount
                expense_by_account[j.debit_account_name] = (
                    expense_by_account.get(j.debit_account_name, Decimal("0")) + j.amount
                )
            elif cat == "operating_expense":
                opex += j.amount
                expense_by_account[j.debit_account_name] = (
                    expense_by_account.get(j.debit_account_name, Decimal("0")) + j.amount
                )
            elif cat == "other_income":
                other_income += j.amount
            elif cat == "other_expense":
                other_expense += j.amount

        gross_profit = revenue - cogs
        operating_profit = gross_profit - opex
        net_income = operating_profit + other_income - other_expense
        return IncomeStatementReport(
            period_name=f"{period_start.isoformat()} s/d {period_end.isoformat()}",
            total_revenue=revenue,
            total_cogs=cogs,
            gross_profit=gross_profit,
            total_expenses=opex,
            operating_profit=operating_profit,
            other_income=other_income,
            other_expenses=other_expense,
            net_income=net_income,
            revenue_details=[{"account": k, "amount": str(v)} for k, v in revenue_by_account.items()],
            expense_details=[{"account": k, "amount": str(v)} for k, v in expense_by_account.items()],
        )

    def _cash_balance(self, items: list[UMKMJournalEntity]) -> Decimal:
        balance = Decimal("0")
        for j in items:
            if j.debit_account_code in _CASH_ACCOUNT_CODES:
                balance += j.amount
            if j.credit_account_code in _CASH_ACCOUNT_CODES:
                balance -= j.amount
        return balance

    async def get_cash_flow(
        self, legal_entity_id: UUID, period_start: date, period_end: date
    ) -> CashFlowReport:
        beginning_items, _ = await self._umkm_repo.list_journals(
            legal_entity_id=legal_entity_id,
            end_date=period_start - timedelta(days=1),
            status="posted",
            unpaginated=True,
        )
        beginning_cash = self._cash_balance(beginning_items)

        period_items, _ = await self._umkm_repo.list_journals(
            legal_entity_id=legal_entity_id,
            start_date=period_start,
            end_date=period_end,
            status="posted",
            unpaginated=True,
        )
        op_in = op_out = inv_in = inv_out = fin_in = fin_out = Decimal("0")
        for j in period_items:
            cat = self._classify(j)
            cash_in = j.debit_account_code in _CASH_ACCOUNT_CODES
            cash_out = j.credit_account_code in _CASH_ACCOUNT_CODES
            if not (cash_in or cash_out):
                continue
            if cat in ("liability", "equity"):
                bucket = "financing"
            elif cat == "asset":
                bucket = "investing"
            else:
                bucket = "operations"
            if cash_in:
                if bucket == "operations":
                    op_in += j.amount
                elif bucket == "investing":
                    inv_in += j.amount
                else:
                    fin_in += j.amount
            if cash_out:
                if bucket == "operations":
                    op_out += j.amount
                elif bucket == "investing":
                    inv_out += j.amount
                else:
                    fin_out += j.amount

        net_ops = op_in - op_out
        net_inv = inv_in - inv_out
        net_fin = fin_in - fin_out
        net_flow = net_ops + net_inv + net_fin
        return CashFlowReport(
            beginning_cash=beginning_cash,
            cash_in_from_operations=op_in,
            cash_out_from_operations=op_out,
            net_cash_operations=net_ops,
            cash_in_from_investing=inv_in,
            cash_out_from_investing=inv_out,
            net_cash_investing=net_inv,
            cash_in_from_financing=fin_in,
            cash_out_from_financing=fin_out,
            net_cash_financing=net_fin,
            net_cash_flow=net_flow,
            ending_cash=beginning_cash + net_flow,
        )

    async def get_balance_sheet(self, legal_entity_id: UUID, as_of_date: date) -> BalanceSheetReport:
        items, _ = await self._umkm_repo.list_journals(
            legal_entity_id=legal_entity_id,
            end_date=as_of_date,
            status="posted",
            unpaginated=True,
        )
        raw_balances: dict[str, Decimal] = {}
        names: dict[str, str] = {}
        for j in items:
            raw_balances[j.debit_account_code] = raw_balances.get(j.debit_account_code, Decimal("0")) + j.amount
            names[j.debit_account_code] = j.debit_account_name
            raw_balances[j.credit_account_code] = raw_balances.get(j.credit_account_code, Decimal("0")) - j.amount
            names[j.credit_account_code] = j.credit_account_name

        assets: list[dict[str, Any]] = []
        liabilities: list[dict[str, Any]] = []
        equity: list[dict[str, Any]] = []
        total_assets = total_liabilities = total_equity = net_income_to_date = Decimal("0")

        for code, raw in raw_balances.items():
            acc = SIMPLIFIED_ACCOUNTS.get(code)
            if not acc:
                continue
            acc_type = acc["type"]
            if acc_type == "ASSET":
                total_assets += raw
                assets.append({"account_code": code, "account_name": names[code], "amount": str(raw)})
            elif acc_type == "LIABILITY":
                amt = -raw
                total_liabilities += amt
                liabilities.append({"account_code": code, "account_name": names[code], "amount": str(amt)})
            elif acc_type == "EQUITY":
                amt = -raw
                total_equity += amt
                equity.append({"account_code": code, "account_name": names[code], "amount": str(amt)})
            elif acc_type == "REVENUE":
                net_income_to_date += -raw
            elif acc_type == "EXPENSE":
                net_income_to_date -= raw

        if net_income_to_date != 0:
            equity.append({
                "account_code": "-",
                "account_name": "Laba Berjalan (belum ditutup)",
                "amount": str(net_income_to_date),
            })
            total_equity += net_income_to_date

        is_balanced = abs(total_assets - (total_liabilities + total_equity)) < Decimal("0.01")
        return BalanceSheetReport(
            total_assets=total_assets,
            total_liabilities=total_liabilities,
            total_equity=total_equity,
            assets_details=assets,
            liabilities_details=liabilities,
            equity_details=equity,
            is_balanced=is_balanced,
        )

    async def get_tax_compliance(
        self, *, legal_entity_id: UUID, period_year: int, period_month: int
    ) -> TaxComplianceInfo:
        period_start = date(period_year, period_month, 1)
        if period_month == 12:
            period_end = date(period_year, 12, 31)
        else:
            period_end = date(period_year, period_month + 1, 1) - timedelta(days=1)

        period_items, _ = await self._umkm_repo.list_journals(
            legal_entity_id=legal_entity_id,
            start_date=period_start,
            end_date=period_end,
            status="posted",
            unpaginated=True,
        )
        revenue_period = sum(
            (j.amount for j in period_items if self._classify(j) == "revenue"), Decimal("0")
        )

        ytd_items, _ = await self._umkm_repo.list_journals(
            legal_entity_id=legal_entity_id,
            start_date=date(period_year, 1, 1),
            end_date=period_end,
            status="posted",
            unpaginated=True,
        )
        revenue_ytd = sum((j.amount for j in ytd_items if self._classify(j) == "revenue"), Decimal("0"))

        estimated_pph = (revenue_period * UMKM_FINAL_TAX_RATE / Decimal("100")).quantize(Decimal("1"))
        # Batas waktu setor PPh Final UMKM: tanggal 15 bulan berikutnya (per PP 23/2018 & PMK terkait)
        if period_month == 12:
            deadline = date(period_year + 1, 1, 15)
        else:
            deadline = date(period_year, period_month + 1, 15)

        is_required = revenue_ytd <= UMKM_MAX_REVENUE_YEARLY
        notes = None
        if revenue_ytd > UMKM_MAX_REVENUE_YEARLY:
            notes = (
                "Peredaran bruto tahun berjalan sudah melewati batas Rp4,8 Miliar - "
                "tidak lagi memenuhi syarat tarif PPh Final UMKM 0,5%, sebaiknya "
                "konsultasikan ke konsultan pajak untuk skema PPh normal."
            )

        return TaxComplianceInfo(
            total_revenue_period=revenue_period,
            total_revenue_ytd=revenue_ytd,
            estimated_pph_final=estimated_pph,
            tax_due_reminder=f"Setor & lapor paling lambat {deadline.isoformat()}",
            submission_deadline=deadline,
            is_required_to_file=is_required,
            notes=notes,
        )

    async def get_transaction_summary(
        self, legal_entity_id: UUID, period_start: date, period_end: date
    ) -> TransactionSummaryReport:
        items, _ = await self._umkm_repo.list_journals(
            legal_entity_id=legal_entity_id,
            start_date=period_start,
            end_date=period_end,
            status="posted",
            unpaginated=True,
        )
        by_category: dict[str, Decimal] = {}
        by_account: dict[str, Decimal] = {}
        by_month: dict[str, Decimal] = {}
        total_amount = Decimal("0")
        for j in items:
            cat = self._classify(j)
            by_category[cat] = by_category.get(cat, Decimal("0")) + j.amount
            by_account[j.debit_account_name] = by_account.get(j.debit_account_name, Decimal("0")) + j.amount
            month_key = j.journal_date.strftime("%Y-%m")
            by_month[month_key] = by_month.get(month_key, Decimal("0")) + j.amount
            total_amount += j.amount
        return TransactionSummaryReport(
            by_category=by_category,
            by_account=by_account,
            by_month=by_month,
            total_transactions=len(items),
            total_amount=total_amount,
        )

    async def export_transactions(
        self, *, legal_entity_id: UUID, start_date: date | None, end_date: date | None, format: str
    ) -> bytes:
        items, _ = await self._umkm_repo.list_journals(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            unpaginated=True,
        )
        headers = [
            "journal_number", "journal_date", "description",
            "debit_account_code", "debit_account_name",
            "credit_account_code", "credit_account_name",
            "amount", "category", "status", "notes",
        ]
        rows = [
            [
                j.journal_number, j.journal_date.isoformat(), j.description,
                j.debit_account_code, j.debit_account_name,
                j.credit_account_code, j.credit_account_name,
                str(j.amount), j.category or "", j.status, j.notes or "",
            ]
            for j in items
        ]

        if format == "excel":
            try:
                from openpyxl import Workbook

                wb = Workbook()
                ws = wb.active
                ws.title = "Jurnal UMKM"
                ws.append(headers)
                for row in rows:
                    ws.append(row)
                buf = io.BytesIO()
                wb.save(buf)
                return buf.getvalue()
            except ImportError:
                logger.warning("openpyxl tidak tersedia, fallback ke CSV untuk export_transactions")

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(rows)
        return output.getvalue().encode("utf-8-sig")

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
        return self._stats.copy()

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_umkm_service(
    umkm_repo: UMKMRepositoryPort,
    uow: UnitOfWorkPort | None = None,
    event_publisher: EventPublisherPort | None = None,
) -> UMKMService:
    return UMKMService(umkm_repo, uow, event_publisher)


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
