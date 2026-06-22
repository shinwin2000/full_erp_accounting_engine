#!/usr/bin/env python3
"""
Module: sqlalchemy_ar_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk aggregate Account Receivable Invoice
               menggunakan SQLAlchemy ORM.
Dependencies: ...
Audit: Setiap perubahan pada invoice AR dicatat di event store.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Value objects
from domain.shared_value_objects.money_vo import Money

# Domain
from domain.subledger_ar.aggregate_root import ARInvoiceAggregate
from domain.subledger_ar.credit_note_entity import ARCreditNote
from domain.subledger_ar.invoice_entity import ARInvoiceLine, ARInvoiceStatus
from domain.subledger_ar.payment_entity import ARPayment
from infrastructure.persistence_orm.ar_credit_note_table import ARCreditNoteTable
from infrastructure.persistence_orm.ar_invoice_line_table import ARInvoiceLineTable

# Infrastructure ORM
from infrastructure.persistence_orm.ar_invoice_table import ARInvoiceTable
from infrastructure.persistence_orm.ar_payment_table import ARPaymentTable

# Ports
from ports.primary.ar_repository_port import ARRepositoryPort

logger = logging.getLogger(__name__)

# ============================================================================
# EXCEPTIONS
# ============================================================================


class ARRepositoryError(Exception):
    """Base exception untuk repository AR."""
    pass


class DuplicateInvoiceNumberError(ARRepositoryError):
    """Nomor invoice sudah ada."""
    pass


class ARInvoiceNotFoundError(ARRepositoryError):
    """Invoice tidak ditemukan."""
    pass


class InvalidStatusTransitionError(ARRepositoryError):
    """Transisi status tidak valid."""
    pass


class PaymentExceedsOutstandingError(ARRepositoryError):
    """Pembayaran melebihi sisa piutang."""
    pass


class OptimisticLockError(ARRepositoryError):
    """Version mismatch saat update."""
    pass


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================


class SQLAlchemyARRepository(ARRepositoryPort):
    """
    Implementasi repository AR Invoice dengan SQLAlchemy.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # ========================================================================
    # HELPER MAPPING METHODS
    # ========================================================================

    def _to_domain(
        self,
        header: ARInvoiceTable,
        lines: list[ARInvoiceLineTable],
        payments: list[ARPaymentTable] = None,
        credit_notes: list[ARCreditNoteTable] = None,
    ) -> ARInvoiceAggregate:
        """
        Mapping dari ORM models ke domain aggregate.
        """
        # Map lines
        domain_lines = []
        for line in lines:
            domain_lines.append(
                ARInvoiceLine(
                    id=line.id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=Money(amount=line.unit_price, currency=line.currency or "IDR"),
                    tax_rate=line.tax_rate,
                    discount_percent=line.discount_percent,
                    account_code=line.account_code,
                    total_amount=Money(amount=line.total_amount, currency=line.currency or "IDR"),
                )
            )

        # Map payments
        domain_payments = []
        if payments:
            for payment in payments:
                domain_payments.append(
                    ARPayment(
                        id=payment.id,
                        payment_number=payment.payment_number,
                        payment_date=payment.payment_date,
                        amount=Money(amount=payment.amount, currency=payment.currency or "IDR"),
                        payment_method=payment.payment_method,
                        reference_number=payment.reference_number,
                        status=payment.status,
                    )
                )

        # Map credit notes
        domain_credit_notes = []
        if credit_notes:
            for note in credit_notes:
                domain_credit_notes.append(
                    ARCreditNote(
                        id=note.id,
                        credit_note_number=note.credit_note_number,
                        credit_note_date=note.credit_note_date,
                        amount=Money(amount=note.amount, currency=note.currency or "IDR"),
                        reason=note.reason,
                        status=note.status,
                    )
                )

        # Map status
        status_map = {
            "draft": ARInvoiceStatus.DRAFT,
            "submitted": ARInvoiceStatus.SUBMITTED,
            "approved": ARInvoiceStatus.APPROVED,
            "partially_paid": ARInvoiceStatus.PARTIALLY_PAID,
            "paid": ARInvoiceStatus.PAID,
            "overdue": ARInvoiceStatus.OVERDUE,
            "cancelled": ARInvoiceStatus.CANCELLED,
        }
        status = status_map.get(header.status, ARInvoiceStatus.DRAFT)

        aggregate = ARInvoiceAggregate(
            id=header.id,
            invoice_number=header.invoice_number,
            customer_id=header.customer_id,
            invoice_date=header.invoice_date,
            due_date=header.due_date,
            lines=domain_lines,
            total_amount=Money(amount=header.total_amount, currency=header.currency or "IDR"),
            paid_amount=Money(amount=header.paid_amount, currency=header.currency or "IDR"),
            tax_amount=Money(amount=header.tax_amount, currency=header.currency or "IDR"),
            discount_amount=Money(amount=header.discount_amount, currency=header.currency or "IDR"),
            description=header.description,
            status=status,
            reference_number=header.reference_number,
            sales_order_id=header.sales_order_id,
            tax_invoice_number=header.tax_invoice_number,
            created_at=header.created_at,
            created_by=header.created_by,
            approved_at=header.approved_at,
            approved_by=header.approved_by,
            version=header.version,
            legal_entity_id=header.legal_entity_id,
        )

        # Add payments and credit notes if any
        if domain_payments:
            aggregate._payments = domain_payments
        if domain_credit_notes:
            aggregate._credit_notes = domain_credit_notes

        return aggregate

    async def _to_orm_header(self, aggregate: ARInvoiceAggregate) -> ARInvoiceTable:
        """Mapping dari domain ke ORM header."""
        header = ARInvoiceTable(
            id=aggregate.id,
            invoice_number=aggregate.invoice_number,
            customer_id=aggregate.customer_id,
            invoice_date=aggregate.invoice_date,
            due_date=aggregate.due_date,
            total_amount=aggregate.total_amount.amount,
            paid_amount=aggregate.paid_amount.amount,
            tax_amount=aggregate.tax_amount.amount,
            discount_amount=aggregate.discount_amount.amount,
            description=aggregate.description,
            status=aggregate.status.value
            if hasattr(aggregate.status, "value")
            else str(aggregate.status),
            reference_number=aggregate.reference_number,
            sales_order_id=aggregate.sales_order_id,
            tax_invoice_number=aggregate.tax_invoice_number,
            currency=aggregate.total_amount.currency,
            created_at=aggregate.created_at,
            created_by=aggregate.created_by,
            approved_at=aggregate.approved_at,
            approved_by=aggregate.approved_by,
            version=aggregate.version,
            legal_entity_id=aggregate.legal_entity_id,
            updated_at=datetime.utcnow(),
        )
        return header

    async def _to_orm_lines(self, aggregate: ARInvoiceAggregate) -> list[ARInvoiceLineTable]:
        """Mapping domain lines ke ORM lines."""
        lines = []
        for i, line in enumerate(aggregate.lines):
            line_table = ARInvoiceLineTable(
                id=line.id or UUID,
                invoice_id=aggregate.id,
                line_number=i + 1,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price.amount,
                tax_rate=line.tax_rate,
                discount_percent=line.discount_percent,
                account_code=line.account_code,
                total_amount=line.total_amount.amount,
                currency=line.unit_price.currency,
            )
            lines.append(line_table)
        return lines

    # ========================================================================
    # REPOSITORY METHODS
    # ========================================================================

    async def add(self, invoice: ARInvoiceAggregate) -> None:
        """Menambahkan invoice AR baru."""
        session = await self._get_session()
        try:
            exists = await self.exists_by_invoice_number(
                invoice.invoice_number, invoice.legal_entity_id
            )
            if exists:
                raise DuplicateInvoiceNumberError(
                    f"Invoice number {invoice.invoice_number} already exists"
                )

            header = await self._to_orm_header(invoice)
            lines = await self._to_orm_lines(invoice)

            session.add(header)
            for line in lines:
                session.add(line)

            await session.flush()
            logger.info("AR Invoice added: %s (id=%s)", invoice.invoice_number, invoice.id)

        except DuplicateInvoiceNumberError:
            raise
        except IntegrityError as e:
            await session.rollback()
            raise ARRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await session.rollback()
            logger.error("Failed to add AR invoice: %s", e)
            raise ARRepositoryError(f"Failed to add invoice: {e}") from e

    async def get_by_id(self, invoice_id: UUID) -> ARInvoiceAggregate | None:
        """Mengambil invoice AR berdasarkan ID."""
        session = await self._get_session()
        try:
            stmt = select(ARInvoiceTable).where(
                ARInvoiceTable.id == invoice_id, ARInvoiceTable.deleted_at.is_(None)
            )
            result = await session.execute(stmt)
            header = result.scalar_one_or_none()

            if not header:
                return None

            lines_stmt = (
                select(ARInvoiceLineTable)
                .where(ARInvoiceLineTable.invoice_id == invoice_id)
                .order_by(ARInvoiceLineTable.line_number)
            )
            lines_result = await session.execute(lines_stmt)
            lines = lines_result.scalars().all()

            payments_stmt = (
                select(ARPaymentTable)
                .where(ARPaymentTable.invoice_id == invoice_id)
                .order_by(ARPaymentTable.payment_date)
            )
            payments_result = await session.execute(payments_stmt)
            payments = payments_result.scalars().all()

            credit_stmt = select(ARCreditNoteTable).where(
                ARCreditNoteTable.invoice_id == invoice_id
            )
            credit_result = await session.execute(credit_stmt)
            credit_notes = credit_result.scalars().all()

            return self._to_domain(header, lines, payments, credit_notes)

        except Exception as e:
            logger.error("Failed to get AR invoice by id %s: %s", invoice_id, e)
            raise ARRepositoryError(f"Failed to get invoice: {e}") from e

    async def get_by_invoice_number(
        self, invoice_number: str, legal_entity_id: UUID
    ) -> ARInvoiceAggregate | None:
        """Mengambil invoice berdasarkan nomor invoice."""
        session = await self._get_session()
        try:
            stmt = select(ARInvoiceTable).where(
                ARInvoiceTable.invoice_number == invoice_number,
                ARInvoiceTable.legal_entity_id == legal_entity_id,
                ARInvoiceTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            header = result.scalar_one_or_none()

            if not header:
                return None

            return await self.get_by_id(header.id)

        except Exception as e:
            logger.error("Failed to get AR invoice by number %s: %s", invoice_number, e)
            raise ARRepositoryError(f"Failed to get invoice: {e}") from e

    async def update(self, invoice: ARInvoiceAggregate) -> None:
        """Memperbarui data invoice (status, paid amount, dll)."""
        session = await self._get_session()
        try:
            stmt = select(ARInvoiceTable.version).where(ARInvoiceTable.id == invoice.id)
            result = await session.execute(stmt)
            current_version = result.scalar_one_or_none()

            if current_version is None:
                raise ARInvoiceNotFoundError(f"Invoice {invoice.id} not found")

            if current_version != invoice.version:
                raise OptimisticLockError(
                    f"Version mismatch: expected {invoice.version}, got {current_version}"
                )

            header = await self._to_orm_header(invoice)
            header.version = invoice.version + 1
            header.updated_at = datetime.utcnow()

            await session.merge(header)

            if invoice.lines_changed:
                await session.execute(
                    delete(ARInvoiceLineTable).where(ARInvoiceLineTable.invoice_id == invoice.id)
                )
                lines = await self._to_orm_lines(invoice)
                for line in lines:
                    session.add(line)

            await session.flush()
            logger.info(
                "AR Invoice updated: %s (version %d -> %d)",
                invoice.invoice_number,
                invoice.version,
                invoice.version + 1,
            )

        except OptimisticLockError:
            raise
        except Exception as e:
            await session.rollback()
            logger.error("Failed to update AR invoice %s: %s", invoice.id, e)
            raise ARRepositoryError(f"Failed to update invoice: {e}") from e

    async def add_payment(self, payment: ARPayment) -> None:
        """Menambahkan pembayaran ke invoice."""
        session = await self._get_session()
        try:
            payment_table = ARPaymentTable(
                id=payment.id,
                payment_number=payment.payment_number,
                invoice_id=payment.invoice_id,
                payment_date=payment.payment_date,
                amount=payment.amount.amount,
                currency=payment.amount.currency,
                payment_method=payment.payment_method,
                reference_number=payment.reference_number,
                status=payment.status,
                created_at=datetime.utcnow(),
                created_by=payment.created_by,
            )
            session.add(payment_table)
            await session.flush()
            logger.info(
                "Payment %s added for invoice %s",
                payment.payment_number,
                payment.invoice_id
            )

        except Exception as e:
            await session.rollback()
            logger.error("Failed to add payment: %s", e)
            raise ARRepositoryError(f"Failed to add payment: {e}") from e

    async def update_invoice_status(
        self, invoice_id: UUID, new_status: str, paid_amount: Decimal | None = None
    ) -> None:
        """Update status invoice (helper method)."""
        session = await self._get_session()
        try:
            values = {"status": new_status, "updated_at": datetime.utcnow()}
            if paid_amount is not None:
                values["paid_amount"] = paid_amount

            stmt = update(ARInvoiceTable).where(ARInvoiceTable.id == invoice_id).values(**values)
            await session.execute(stmt)
            await session.flush()

        except Exception as e:
            logger.error("Failed to update invoice status: %s", e)
            raise ARRepositoryError(f"Failed to update status: {e}") from e

    async def find_overdue_invoices(
        self, as_of_date: date, legal_entity_id: UUID
    ) -> list[ARInvoiceAggregate]:
        """Mencari invoice yang sudah jatuh tempo."""
        session = await self._get_session()
        try:
            stmt = (
                select(ARInvoiceTable)
                .where(
                    ARInvoiceTable.due_date < as_of_date,
                    ARInvoiceTable.status.in_(["approved", "partially_paid"]),
                    ARInvoiceTable.legal_entity_id == legal_entity_id,
                    ARInvoiceTable.deleted_at.is_(None),
                )
                .order_by(ARInvoiceTable.due_date)
            )

            result = await session.execute(stmt)
            headers = result.scalars().all()

            invoices = []
            for header in headers:
                invoice = await self.get_by_id(header.id)
                if invoice:
                    invoices.append(invoice)

            return invoices

        except Exception as e:
            logger.error("Failed to find overdue invoices: %s", e)
            raise ARRepositoryError(f"Failed to find overdue invoices: {e}") from e

    async def find_by_customer(
        self, customer_id: UUID, legal_entity_id: UUID
    ) -> list[ARInvoiceAggregate]:
        """Mencari semua invoice untuk customer tertentu."""
        session = await self._get_session()
        try:
            stmt = (
                select(ARInvoiceTable)
                .where(
                    ARInvoiceTable.customer_id == customer_id,
                    ARInvoiceTable.legal_entity_id == legal_entity_id,
                    ARInvoiceTable.deleted_at.is_(None),
                )
                .order_by(ARInvoiceTable.invoice_date.desc())
            )

            result = await session.execute(stmt)
            headers = result.scalars().all()

            invoices = []
            for header in headers:
                invoice = await self.get_by_id(header.id)
                if invoice:
                    invoices.append(invoice)

            return invoices

        except Exception as e:
            logger.error("Failed to find invoices by customer %s: %s", customer_id, e)
            raise ARRepositoryError(f"Failed to find invoices: {e}") from e

    async def get_outstanding_balance(self, customer_id: UUID, as_of_date: date) -> Decimal:
        """Menghitung total piutang yang masih outstanding untuk customer."""
        session = await self._get_session()
        try:
            stmt = select(
                func.coalesce(func.sum(ARInvoiceTable.total_amount - ARInvoiceTable.paid_amount), 0)
            ).where(
                ARInvoiceTable.customer_id == customer_id,
                ARInvoiceTable.invoice_date <= as_of_date,
                ARInvoiceTable.status.in_(["approved", "partially_paid", "overdue"]),
                ARInvoiceTable.deleted_at.is_(None),
            )

            result = await session.execute(stmt)
            outstanding = result.scalar() or 0
            return Decimal(str(outstanding))

        except Exception as e:
            logger.error("Failed to get outstanding balance for customer %s: %s", customer_id, e)
            raise ARRepositoryError(f"Failed to get outstanding balance: {e}") from e

    async def exists_by_invoice_number(self, invoice_number: str, legal_entity_id: UUID) -> bool:
        """Memeriksa apakah nomor invoice sudah ada."""
        session = await self._get_session()
        try:
            stmt = (
                select(func.count())
                .select_from(ARInvoiceTable)
                .where(
                    ARInvoiceTable.invoice_number == invoice_number,
                    ARInvoiceTable.legal_entity_id == legal_entity_id,
                    ARInvoiceTable.deleted_at.is_(None),
                )
            )
            result = await session.execute(stmt)
            count = result.scalar()
            return count > 0

        except Exception as e:
            logger.error("Failed to check invoice number %s: %s", invoice_number, e)
            raise ARRepositoryError(f"Failed to check invoice number: {e}") from e

    async def get_aging_buckets(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> list[dict[str, Any]]:
        """Menghasilkan aging buckets (0-30, 31-60, 61-90, 91-120, 120+)."""
        session = await self._get_session()
        try:
            buckets = [
                ("0-30 days", as_of_date - timedelta(days=30), as_of_date),
                ("31-60 days", as_of_date - timedelta(days=60), as_of_date - timedelta(days=31)),
                ("61-90 days", as_of_date - timedelta(days=90), as_of_date - timedelta(days=61)),
                ("91-120 days", as_of_date - timedelta(days=120), as_of_date - timedelta(days=91)),
                ("120+ days", None, as_of_date - timedelta(days=121)),
            ]

            results = []
            for bucket_name, start, end in buckets:
                conditions = [
                    ARInvoiceTable.status.in_(["approved", "partially_paid", "overdue"]),
                    ARInvoiceTable.legal_entity_id == legal_entity_id,
                    ARInvoiceTable.deleted_at.is_(None),
                ]
                if start:
                    conditions.append(ARInvoiceTable.due_date <= start)
                if end:
                    conditions.append(ARInvoiceTable.due_date >= end) if end else None

                if bucket_name == "120+ days":
                    conditions.append(ARInvoiceTable.due_date <= as_of_date - timedelta(days=120))

                stmt = select(
                    func.coalesce(
                        func.sum(ARInvoiceTable.total_amount - ARInvoiceTable.paid_amount), 0
                    )
                ).where(and_(*conditions))

                result = await session.execute(stmt)
                total = result.scalar() or 0

                results.append(
                    {
                        "bucket_name": bucket_name,
                        "total_amount": Decimal(str(total)),
                        "percentage": 0,
                    }
                )

            total_all = sum(r["total_amount"] for r in results)
            for r in results:
                if total_all > 0:
                    r["percentage"] = float(r["total_amount"] / total_all * 100)
                else:
                    r["percentage"] = 0

            return results

        except Exception as e:
            logger.error("Failed to get aging buckets: %s", e)
            raise ARRepositoryError(f"Failed to get aging buckets: {e}") from e

    async def get_next_invoice_number(self, prefix: str = "INV", year: int = None) -> str:
        """Menghasilkan nomor invoice berikutnya."""
        if year is None:
            year = date.today().year

        session = await self._get_session()
        try:
            pattern = func.concat(prefix, '-', year, '-%')
            stmt = (
                select(ARInvoiceTable.invoice_number)
                .where(
                    ARInvoiceTable.invoice_number.like(pattern),
                    ARInvoiceTable.deleted_at.is_(None)
                )
                .order_by(ARInvoiceTable.invoice_number.desc())
                .limit(1)
            )

            result = await session.execute(stmt)
            last_number = result.scalar_one_or_none()

            if last_number:
                seq = int(last_number.split("-")[-1]) + 1
            else:
                seq = 1

            return f"{prefix}-{year}-{seq:06d}"

        except Exception as e:
            logger.error("Failed to generate next invoice number: %s", e)
            raise ARRepositoryError(f"Failed to generate invoice number: {e}") from e

    # ========================================================================
    # METODE TAMBAHAN UNTUK MEMENUHI KONTRAK PORT (stub/delegasi)
    # ========================================================================

    async def get_all_by_legal_entity(self, legal_entity_id: UUID) -> list[ARInvoiceAggregate]:
        """Stub: dapatkan semua invoice untuk entitas hukum."""
        logger.warning("get_all_by_legal_entity not fully implemented")
        return []

    async def get_payments(self, invoice_id: UUID) -> list[ARPayment]:
        """Stub: dapatkan pembayaran untuk invoice."""
        logger.warning("get_payments not fully implemented")
        return []

    async def get_credit_notes(self, invoice_id: UUID) -> list[ARCreditNote]:
        """Stub: dapatkan credit notes untuk invoice."""
        logger.warning("get_credit_notes not fully implemented")
        return []

    async def save(self, invoice: ARInvoiceAggregate) -> None:
        """Simpan (add atau update) invoice."""
        existing = await self.get_by_id(invoice.id)
        if existing:
            await self.update(invoice)
        else:
            await self.add(invoice)

    async def save_invoice(self, invoice: ARInvoiceAggregate) -> None:
        """P55: Save invoice (add if new, update if exists)."""
        existing = await self.get_by_id(invoice.id)
        if existing:
            await self.update(invoice)
        else:
            await self.add(invoice)

    async def find_invoice_by_id(self, invoice_id: UUID) -> ARInvoiceAggregate | None:
        """P55: Find invoice by ID (without legal_entity_id)."""
        return await self.get_by_id(invoice_id)
    
# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS DENGAN ADAPTER REGISTRY
# ============================================================================

SQLAlchemyARRepositoryImpl = SQLAlchemyARRepository

# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "ARInvoiceNotFoundError",
    "ARRepositoryError",
    "DuplicateInvoiceNumberError",
    "InvalidStatusTransitionError",
    "OptimisticLockError",
    "PaymentExceedsOutstandingError",
    "SQLAlchemyARRepository",
    "SQLAlchemyARRepositoryImpl",
]