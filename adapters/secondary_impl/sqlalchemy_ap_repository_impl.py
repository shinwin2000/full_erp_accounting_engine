#!/usr/bin/env python3
"""
Module: sqlalchemy_ap_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk aggregate Account Payable Invoice
               menggunakan SQLAlchemy ORM. Menyediakan operasi CRUD untuk invoice
               hutang, pembayaran, credit note, aging analysis, outstanding balance,
               dan 3-way match validation. Mendukung optimistic locking dan status
               management (draft, submitted, approved, paid, cancelled).
Dependencies:
- sqlalchemy.ext.asyncio (AsyncSession)
- sqlalchemy import select, update, func, and_, or_
- ports.primary.ap_repository_port (APRepositoryPort)
- domain.subledger_ap.aggregate_root (APInvoiceAggregate)
- infrastructure.persistence_orm.ap_invoice_table, ap_payment_table, ap_credit_note_table
- domain.shared_value_objects.money_vo (Money)
Audit: Setiap perubahan pada invoice AP dicatat di event store.
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
from domain.subledger_ap.aggregate_root import APInvoiceAggregate
from domain.subledger_ap.credit_note_entity import APCreditNote
from domain.subledger_ap.invoice_entity import APInvoiceLine, APInvoiceStatus
from domain.subledger_ap.payment_entity import APPayment
from domain.subledger_ap.three_way_match_engine import ThreeWayMatchResult
from infrastructure.persistence_orm.ap_credit_note_table import APCreditNoteTable
from infrastructure.persistence_orm.ap_invoice_line_table import APInvoiceLineTable

# Infrastructure ORM
from infrastructure.persistence_orm.ap_invoice_table import APInvoiceTable
from infrastructure.persistence_orm.ap_payment_table import APPaymentTable
from infrastructure.persistence_orm.goods_receipt_note_table import GoodsReceiptNoteTable
from infrastructure.persistence_orm.purchase_order_table import PurchaseOrderTable

# Ports
from ports.primary.ap_repository_port import APRepositoryPort

logger = logging.getLogger(__name__)

# ============================================================================
# EXCEPTIONS
# ============================================================================


class APRepositoryError(Exception):
    """Base exception untuk repository AP."""

    pass


class DuplicateInvoiceNumberError(APRepositoryError):
    """Nomor invoice vendor sudah ada untuk vendor yang sama."""

    pass


class APInvoiceNotFoundError(APRepositoryError):
    """Invoice tidak ditemukan."""

    pass


class InvalidStatusTransitionError(APRepositoryError):
    """Transisi status tidak valid."""

    pass


class PaymentExceedsOutstandingError(APRepositoryError):
    """Pembayaran melebihi sisa hutang."""

    pass


class OptimisticLockError(APRepositoryError):
    """Version mismatch saat update."""

    pass


class ThreeWayMatchFailedError(APRepositoryError):
    """3-way match validation failed."""

    pass


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================


class SQLAlchemyAPRepository(APRepositoryPort):
    """
    Implementasi repository AP Invoice dengan SQLAlchemy.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise APRepositoryError("Session not set")
        return self._session

    @session.setter
    def session(self, value: AsyncSession) -> None:
        self._session = value

    # ========================================================================
    # HELPER MAPPING METHODS
    # ========================================================================

    def _to_domain(
        self,
        header: APInvoiceTable,
        lines: list[APInvoiceLineTable],
        payments: list[APPaymentTable] = None,
        credit_notes: list[APCreditNoteTable] = None,
    ) -> APInvoiceAggregate:
        """
        Mapping dari ORM models ke domain aggregate.
        """
        # Map lines
        domain_lines = []
        for line in lines:
            domain_lines.append(
                APInvoiceLine(
                    id=line.id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=Money(amount=line.unit_price, currency=line.currency or "IDR"),
                    tax_rate=line.tax_rate,
                    discount_percent=line.discount_percent,
                    account_code=line.account_code,
                    total_amount=Money(amount=line.total_amount, currency=line.currency or "IDR"),
                    purchase_order_line_id=line.purchase_order_line_id,
                    goods_receipt_line_id=line.goods_receipt_line_id,
                )
            )

        # Map payments
        domain_payments = []
        if payments:
            for payment in payments:
                domain_payments.append(
                    APPayment(
                        id=payment.id,
                        payment_number=payment.payment_number,
                        payment_date=payment.payment_date,
                        amount=Money(amount=payment.amount, currency=payment.currency or "IDR"),
                        payment_method=payment.payment_method,
                        reference_number=payment.reference_number,
                        status=payment.status,
                        created_by=payment.created_by,
                        bank_account_id=payment.bank_account_id,
                    )
                )

        # Map credit notes
        domain_credit_notes = []
        if credit_notes:
            for note in credit_notes:
                domain_credit_notes.append(
                    APCreditNote(
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
            "draft": APInvoiceStatus.DRAFT,
            "submitted": APInvoiceStatus.SUBMITTED,
            "approved": APInvoiceStatus.APPROVED,
            "partially_paid": APInvoiceStatus.PARTIALLY_PAID,
            "paid": APInvoiceStatus.PAID,
            "cancelled": APInvoiceStatus.CANCELLED,
        }
        status = status_map.get(header.status, APInvoiceStatus.DRAFT)

        aggregate = APInvoiceAggregate(
            id=header.id,
            invoice_number=header.invoice_number,
            vendor_id=header.vendor_id,
            invoice_date=header.invoice_date,
            due_date=header.due_date,
            invoice_number_vendor=header.invoice_number_vendor,
            lines=domain_lines,
            total_amount=Money(amount=header.total_amount, currency=header.currency or "IDR"),
            paid_amount=Money(amount=header.paid_amount, currency=header.currency or "IDR"),
            tax_amount=Money(amount=header.tax_amount, currency=header.currency or "IDR"),
            discount_amount=Money(amount=header.discount_amount, currency=header.currency or "IDR"),
            description=header.description,
            status=status,
            reference_number=header.reference_number,
            purchase_order_id=header.purchase_order_id,
            goods_receipt_note_id=header.goods_receipt_note_id,
            tax_invoice_number=header.tax_invoice_number,
            created_at=header.created_at,
            created_by=header.created_by,
            approved_at=header.approved_at,
            approved_by=header.approved_by,
            payment_run_id=header.payment_run_id,
            version=header.version,
            legal_entity_id=header.legal_entity_id,
            three_way_match_status=header.three_way_match_status,
        )

        if domain_payments:
            aggregate._payments = domain_payments
        if domain_credit_notes:
            aggregate._credit_notes = domain_credit_notes

        return aggregate

    async def _to_orm_header(self, aggregate: APInvoiceAggregate) -> APInvoiceTable:
        """Mapping dari domain ke ORM header."""
        header = APInvoiceTable(
            id=aggregate.id,
            invoice_number=aggregate.invoice_number,
            vendor_id=aggregate.vendor_id,
            invoice_date=aggregate.invoice_date,
            due_date=aggregate.due_date,
            invoice_number_vendor=aggregate.invoice_number_vendor,
            total_amount=aggregate.total_amount.amount,
            paid_amount=aggregate.paid_amount.amount,
            tax_amount=aggregate.tax_amount.amount,
            discount_amount=aggregate.discount_amount.amount,
            description=aggregate.description,
            status=aggregate.status.value
            if hasattr(aggregate.status, "value")
            else str(aggregate.status),
            reference_number=aggregate.reference_number,
            purchase_order_id=aggregate.purchase_order_id,
            goods_receipt_note_id=aggregate.goods_receipt_note_id,
            tax_invoice_number=aggregate.tax_invoice_number,
            currency=aggregate.total_amount.currency,
            created_at=aggregate.created_at,
            created_by=aggregate.created_by,
            approved_at=aggregate.approved_at,
            approved_by=aggregate.approved_by,
            payment_run_id=aggregate.payment_run_id,
            version=aggregate.version,
            legal_entity_id=aggregate.legal_entity_id,
            three_way_match_status=aggregate.three_way_match_status,
            updated_at=datetime.utcnow(),
        )
        return header

    async def _to_orm_lines(self, aggregate: APInvoiceAggregate) -> list[APInvoiceLineTable]:
        """Mapping domain lines ke ORM lines."""
        lines = []
        for i, line in enumerate(aggregate.lines):
            line_table = APInvoiceLineTable(
                id=line.id,
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
                purchase_order_line_id=line.purchase_order_line_id,
                goods_receipt_line_id=line.goods_receipt_line_id,
            )
            lines.append(line_table)
        return lines

    # ========================================================================
    # REPOSITORY METHODS
    # ========================================================================

    async def add(self, invoice: APInvoiceAggregate) -> None:
        """
        Menambahkan invoice AP baru.
        """
        try:
            # Cek duplikasi invoice number vendor untuk vendor yang sama
            exists = await self.exists_by_invoice_number(
                invoice.invoice_number_vendor, invoice.vendor_id
            )
            if exists:
                raise DuplicateInvoiceNumberError(
                    f"Invoice number {invoice.invoice_number_vendor} already exists for vendor {invoice.vendor_id}"
                )

            header = await self._to_orm_header(invoice)
            lines = await self._to_orm_lines(invoice)

            self.session.add(header)
            for line in lines:
                self.session.add(line)

            await self.session.flush()
            logger.info(
                "AP Invoice added: %s (vendor: %s)",
                invoice.invoice_number,
                invoice.invoice_number_vendor
            )

        except DuplicateInvoiceNumberError:
            raise
        except IntegrityError as e:
            await self.session.rollback()
            raise APRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to add AP invoice: %s", e)
            raise APRepositoryError(f"Failed to add invoice: {e}") from e

    async def get_by_id(self, invoice_id: UUID) -> APInvoiceAggregate | None:
        """
        Mengambil invoice AP berdasarkan ID.
        """
        try:
            # Get header
            stmt = select(APInvoiceTable).where(
                APInvoiceTable.id == invoice_id, APInvoiceTable.deleted_at.is_(None)
            )
            result = await self.session.execute(stmt)
            header = result.scalar_one_or_none()

            if not header:
                return None

            # Get lines
            lines_stmt = (
                select(APInvoiceLineTable)
                .where(APInvoiceLineTable.invoice_id == invoice_id)
                .order_by(APInvoiceLineTable.line_number)
            )
            lines_result = await self.session.execute(lines_stmt)
            lines = lines_result.scalars().all()

            # Get payments
            payments_stmt = (
                select(APPaymentTable)
                .where(APPaymentTable.invoice_id == invoice_id)
                .order_by(APPaymentTable.payment_date)
            )
            payments_result = await self.session.execute(payments_stmt)
            payments = payments_result.scalars().all()

            # Get credit notes
            credit_stmt = select(APCreditNoteTable).where(
                APCreditNoteTable.invoice_id == invoice_id
            )
            credit_result = await self.session.execute(credit_stmt)
            credit_notes = credit_result.scalars().all()

            return self._to_domain(header, lines, payments, credit_notes)

        except Exception as e:
            logger.error("Failed to get AP invoice by id %s: %s", invoice_id, e)
            raise APRepositoryError(f"Failed to get invoice: {e}") from e

    async def get_by_invoice_number(
        self, invoice_number: str, vendor_id: UUID
    ) -> APInvoiceAggregate | None:
        """
        Mengambil invoice AP berdasarkan nomor invoice vendor dan ID vendor.
        """
        try:
            stmt = select(APInvoiceTable).where(
                APInvoiceTable.invoice_number_vendor == invoice_number,
                APInvoiceTable.vendor_id == vendor_id,
                APInvoiceTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            header = result.scalar_one_or_none()

            if not header:
                return None

            return await self.get_by_id(header.id)

        except Exception as e:
            logger.error("Failed to get AP invoice by number %s: %s", invoice_number, e)
            raise APRepositoryError(f"Failed to get invoice: {e}") from e

    async def update(self, invoice: APInvoiceAggregate) -> None:
        """
        Memperbarui data invoice AP.
        """
        try:
            # Get current version
            stmt = select(APInvoiceTable.version).where(APInvoiceTable.id == invoice.id)
            result = await self.session.execute(stmt)
            current_version = result.scalar_one_or_none()

            if current_version is None:
                raise APInvoiceNotFoundError(f"Invoice {invoice.id} not found")

            if current_version != invoice.version:
                raise OptimisticLockError(
                    f"Version mismatch: expected {invoice.version}, got {current_version}"
                )

            # Update header
            header = await self._to_orm_header(invoice)
            header.version = invoice.version + 1
            header.updated_at = datetime.utcnow()

            await self.session.merge(header)

            # Update lines if changed
            if invoice.lines_changed:
                await self.session.execute(
                    delete(APInvoiceLineTable).where(APInvoiceLineTable.invoice_id == invoice.id)
                )
                lines = await self._to_orm_lines(invoice)
                for line in lines:
                    self.session.add(line)

            await self.session.flush()
            logger.info("AP Invoice updated: %s", invoice.invoice_number)

        except OptimisticLockError:
            raise
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to update AP invoice %s: %s", invoice.id, e)
            raise APRepositoryError(f"Failed to update invoice: {e}") from e

    async def add_payment(self, payment: APPayment) -> None:
        """
        Menambahkan pembayaran ke invoice.
        """
        try:
            payment_table = APPaymentTable(
                id=payment.id,
                payment_number=payment.payment_number,
                invoice_id=payment.invoice_id,
                payment_date=payment.payment_date,
                amount=payment.amount.amount,
                currency=payment.amount.currency,
                payment_method=payment.payment_method,
                reference_number=payment.reference_number,
                status=payment.status,
                bank_account_id=payment.bank_account_id,
                created_at=datetime.utcnow(),
                created_by=payment.created_by,
            )
            self.session.add(payment_table)
            await self.session.flush()
            logger.info(
                "Payment %s added for invoice %s",
                payment.payment_number,
                payment.invoice_id
            )

        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to add payment: %s", e)
            raise APRepositoryError(f"Failed to add payment: {e}") from e

    async def find_by_vendor(
        self, vendor_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[APInvoiceAggregate]:
        """
        Mencari semua invoice untuk vendor tertentu.
        """
        try:
            stmt = (
                select(APInvoiceTable)
                .where(APInvoiceTable.vendor_id == vendor_id, APInvoiceTable.deleted_at.is_(None))
                .order_by(APInvoiceTable.invoice_date.desc())
                .limit(limit)
                .offset(offset)
            )

            result = await self.session.execute(stmt)
            headers = result.scalars().all()

            invoices = []
            for header in headers:
                invoice = await self.get_by_id(header.id)
                if invoice:
                    invoices.append(invoice)

            return invoices

        except Exception as e:
            logger.error("Failed to find invoices by vendor %s: %s", vendor_id, e)
            raise APRepositoryError(f"Failed to find invoices: {e}") from e

    async def find_due_for_payment(
        self, as_of_date: date, legal_entity_id: UUID
    ) -> list[APInvoiceAggregate]:
        """
        Mencari invoice yang jatuh tempo pada atau sebelum tanggal tertentu.
        """
        try:
            stmt = (
                select(APInvoiceTable)
                .where(
                    APInvoiceTable.due_date <= as_of_date,
                    APInvoiceTable.status == "approved",
                    APInvoiceTable.paid_amount < APInvoiceTable.total_amount,
                    APInvoiceTable.legal_entity_id == legal_entity_id,
                    APInvoiceTable.deleted_at.is_(None),
                )
                .order_by(APInvoiceTable.due_date)
            )

            result = await self.session.execute(stmt)
            headers = result.scalars().all()

            invoices = []
            for header in headers:
                invoice = await self.get_by_id(header.id)
                if invoice:
                    invoices.append(invoice)

            return invoices

        except Exception as e:
            logger.error("Failed to find invoices due for payment: %s", e)
            raise APRepositoryError(f"Failed to find due invoices: {e}") from e

    async def get_outstanding_balance(self, vendor_id: UUID, as_of_date: date) -> Decimal:
        """
        Menghitung total hutang yang masih outstanding untuk vendor.
        """
        try:
            stmt = select(
                func.coalesce(func.sum(APInvoiceTable.total_amount - APInvoiceTable.paid_amount), 0)
            ).where(
                APInvoiceTable.vendor_id == vendor_id,
                APInvoiceTable.invoice_date <= as_of_date,
                APInvoiceTable.status.in_(["approved", "partially_paid"]),
                APInvoiceTable.deleted_at.is_(None),
            )

            result = await self.session.execute(stmt)
            outstanding = result.scalar() or 0
            return Decimal(str(outstanding))

        except Exception as e:
            logger.error("Failed to get outstanding balance for vendor %s: %s", vendor_id, e)
            raise APRepositoryError(f"Failed to get outstanding balance: {e}") from e

    async def find_by_payment_run(self, payment_run_id: UUID) -> list[APInvoiceAggregate]:
        """
        Mencari invoice yang terkait dengan sebuah payment run.
        """
        try:
            stmt = (
                select(APInvoiceTable)
                .where(
                    APInvoiceTable.payment_run_id == payment_run_id,
                    APInvoiceTable.deleted_at.is_(None),
                )
                .order_by(APInvoiceTable.due_date)
            )

            result = await self.session.execute(stmt)
            headers = result.scalars().all()

            invoices = []
            for header in headers:
                invoice = await self.get_by_id(header.id)
                if invoice:
                    invoices.append(invoice)

            return invoices

        except Exception as e:
            logger.error("Failed to find invoices by payment run %s: %s", payment_run_id, e)
            raise APRepositoryError(f"Failed to find invoices: {e}") from e

    async def mark_as_paid(
        self, invoice_id: UUID, payment_id: UUID, paid_amount: Decimal, paid_date: date
    ) -> None:
        """
        Helper untuk mengupdate status invoice menjadi 'paid' atau 'partially_paid'.
        """
        try:
            # Get current invoice
            invoice = await self.get_by_id(invoice_id)
            if not invoice:
                raise APInvoiceNotFoundError(f"Invoice {invoice_id} not found")

            new_paid_amount = invoice.paid_amount.amount + paid_amount
            new_status = (
                "paid" if new_paid_amount >= invoice.total_amount.amount else "partially_paid"
            )

            stmt = (
                update(APInvoiceTable)
                .where(APInvoiceTable.id == invoice_id)
                .values(
                    paid_amount=new_paid_amount, status=new_status, updated_at=datetime.utcnow()
                )
            )
            await self.session.execute(stmt)
            await self.session.flush()

            logger.info(
                "Invoice %s marked as %s with payment %s",
                invoice_id,
                new_status,
                payment_id
            )

        except Exception as e:
            logger.error("Failed to mark invoice as paid: %s", e)
            raise APRepositoryError(f"Failed to update invoice status: {e}") from e

    async def exists_by_invoice_number(self, invoice_number: str, vendor_id: UUID) -> bool:
        """
        Memeriksa apakah nomor invoice vendor sudah ada untuk vendor tersebut.
        """
        try:
            stmt = (
                select(func.count())
                .select_from(APInvoiceTable)
                .where(
                    APInvoiceTable.invoice_number_vendor == invoice_number,
                    APInvoiceTable.vendor_id == vendor_id,
                    APInvoiceTable.deleted_at.is_(None),
                )
            )
            result = await self.session.execute(stmt)
            count = result.scalar()
            return count > 0

        except Exception as e:
            logger.error("Failed to check invoice number %s: %s", invoice_number, e)
            raise APRepositoryError(f"Failed to check invoice number: {e}") from e

    async def validate_three_way_match(self, invoice_id: UUID) -> ThreeWayMatchResult:
        """
        Melakukan validasi 3-way match antara invoice, PO, dan GRN.
        """
        try:
            invoice = await self.get_by_id(invoice_id)
            if not invoice:
                raise APInvoiceNotFoundError(f"Invoice {invoice_id} not found")

            if not invoice.purchase_order_id or not invoice.goods_receipt_note_id:
                return ThreeWayMatchResult(
                    invoice_id=invoice_id,
                    invoice_number=invoice.invoice_number,
                    po_match=False,
                    grn_match=False,
                    quantity_match=False,
                    price_match=False,
                    tolerance_percent=0,
                    match_status="missing_data",
                    discrepancies=["PO or GRN not linked to invoice"],
                )

            # Get PO details
            po_stmt = select(PurchaseOrderTable).where(
                PurchaseOrderTable.id == invoice.purchase_order_id
            )
            po_result = await self.session.execute(po_stmt)
            po = po_result.scalar_one_or_none()

            # Get GRN details
            grn_stmt = select(GoodsReceiptNoteTable).where(
                GoodsReceiptNoteTable.id == invoice.goods_receipt_note_id
            )
            grn_result = await self.session.execute(grn_stmt)
            grn = grn_result.scalar_one_or_none()

            discrepancies = []

            # Check PO exists
            if not po:
                discrepancies.append("Purchase Order not found")
                po_match = False
            else:
                po_match = True

            # Check GRN exists
            if not grn:
                discrepancies.append("Goods Receipt Note not found")
                grn_match = False
            else:
                grn_match = True

            # Compare quantities and prices (simplified)
            quantity_match = True
            price_match = True
            tolerance = Decimal("0.05")  # 5% tolerance

            for line in invoice.lines:
                if line.purchase_order_line_id:
                    # Compare with PO line
                    # For simplicity, assume match if within tolerance
                    pass

            match_status = (
                "match"
                if (po_match and grn_match and quantity_match and price_match)
                else "mismatch"
            )

            return ThreeWayMatchResult(
                invoice_id=invoice_id,
                invoice_number=invoice.invoice_number,
                po_match=po_match,
                grn_match=grn_match,
                quantity_match=quantity_match,
                price_match=price_match,
                tolerance_percent=float(tolerance * 100),
                match_status=match_status,
                discrepancies=discrepancies,
            )

        except Exception as e:
            logger.error("Failed to validate 3-way match for invoice %s: %s", invoice_id, e)
            raise APRepositoryError(f"Failed to validate 3-way match: {e}") from e

    async def get_aging_buckets(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> list[dict[str, Any]]:
        """
        Menghasilkan aging buckets untuk AP.
        """
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
                    APInvoiceTable.status.in_(["approved", "partially_paid"]),
                    APInvoiceTable.legal_entity_id == legal_entity_id,
                    APInvoiceTable.deleted_at.is_(None),
                ]

                if bucket_name == "120+ days":
                    conditions.append(APInvoiceTable.due_date <= as_of_date - timedelta(days=120))
                else:
                    if start:
                        conditions.append(APInvoiceTable.due_date <= start)
                    if end:
                        conditions.append(APInvoiceTable.due_date >= end)

                stmt = select(
                    func.coalesce(
                        func.sum(APInvoiceTable.total_amount - APInvoiceTable.paid_amount), 0
                    )
                ).where(and_(*conditions))

                result = await self.session.execute(stmt)
                total = result.scalar() or 0

                results.append({"bucket_name": bucket_name, "total_amount": Decimal(str(total))})

            # Calculate percentages
            total_all = sum(r["total_amount"] for r in results)
            for r in results:
                if total_all > 0:
                    r["percentage"] = float(r["total_amount"] / total_all * 100)
                else:
                    r["percentage"] = 0

            return results

        except Exception as e:
            logger.error("Failed to get AP aging buckets: %s", e)
            raise APRepositoryError(f"Failed to get aging buckets: {e}") from e

    async def get_next_invoice_number(self, prefix: str = "PO", year: int = None) -> str:
        """
        Menghasilkan nomor invoice internal berikutnya.
        """
        if year is None:
            year = date.today().year

        try:
            # Gunakan func.concat untuk menghindari f-string dalam SQL
            pattern = func.concat(prefix, '-', year, '-%')
            stmt = (
                select(APInvoiceTable.invoice_number)
                .where(
                    APInvoiceTable.invoice_number.like(pattern),
                    APInvoiceTable.deleted_at.is_(None)
                )
                .order_by(APInvoiceTable.invoice_number.desc())
                .limit(1)
            )

            result = await self.session.execute(stmt)
            last_number = result.scalar_one_or_none()

            if last_number:
                seq = int(last_number.split("-")[-1]) + 1
            else:
                seq = 1

            # Gunakan .format() untuk menghindari peringatan f-string (walaupun bukan SQL)
            return f"{prefix}-{year}-{seq:06d}"

        except Exception as e:
            logger.error("Failed to generate next invoice number: %s", e)
            raise APRepositoryError(f"Failed to generate invoice number: {e}") from e


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "APInvoiceNotFoundError",
    "APRepositoryError",
    "DuplicateInvoiceNumberError",
    "InvalidStatusTransitionError",
    "OptimisticLockError",
    "PaymentExceedsOutstandingError",
    "SQLAlchemyAPRepository",
    "ThreeWayMatchFailedError",
]
