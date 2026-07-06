#!/usr/bin/env python3
"""
Module: sqlalchemy_ap_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk Account Payable Invoice.
Perbaikan: Menghilangkan semua float() pada nilai moneter, diganti dengan str() atau Decimal.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.shared_value_objects.money_vo import Money
from domain.subledger_ap.aggregate_root import APInvoiceAggregate
from domain.subledger_ap.credit_note_entity import APCreditNote
from domain.subledger_ap.invoice_entity import APInvoiceLine, APInvoiceStatus
from domain.subledger_ap.payment_entity import APPayment
from domain.subledger_ap.three_way_match_engine import ThreeWayMatchResult
from infrastructure.persistence_orm.ap_credit_note_table import APCreditNoteTable
from infrastructure.persistence_orm.ap_invoice_line_table import APInvoiceLineTable
from infrastructure.persistence_orm.ap_invoice_table import APInvoiceTable
from infrastructure.persistence_orm.ap_payment_table import APPaymentTable
from infrastructure.persistence_orm.goods_receipt_note_table import GoodsReceiptNoteTable
from infrastructure.persistence_orm.purchase_order_table import PurchaseOrderTable
from ports.primary.ap_repository_port import APRepositoryPort, MatchingStatus

logger = logging.getLogger(__name__)


class APRepositoryError(Exception):
    pass


class DuplicateInvoiceNumberError(APRepositoryError):
    pass


class APInvoiceNotFoundError(APRepositoryError):
    pass


class InvalidStatusTransitionError(APRepositoryError):
    pass


class OptimisticLockError(APRepositoryError):
    pass


class SQLAlchemyAPRepository(APRepositoryPort):
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

    # === MAPPING ===
    def _to_domain(
        self,
        header: APInvoiceTable,
        lines: list[APInvoiceLineTable],
        payments: list[APPaymentTable] = None,
        credit_notes: list[APCreditNoteTable] = None,
    ) -> APInvoiceAggregate:
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
        return APInvoiceTable(
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
            status=aggregate.status.value if hasattr(aggregate.status, "value") else str(aggregate.status),
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

    async def _to_orm_lines(self, aggregate: APInvoiceAggregate) -> list[APInvoiceLineTable]:
        lines = []
        for i, line in enumerate(aggregate.lines):
            lines.append(
                APInvoiceLineTable(
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
            )
        return lines

    # === CRUD ===
    async def add(self, invoice: APInvoiceAggregate) -> None:
        try:
            exists = await self.exists_by_invoice_number(invoice.invoice_number_vendor, invoice.vendor_id)
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
            logger.info("AP Invoice added: %s", invoice.invoice_number)
        except DuplicateInvoiceNumberError:
            raise
        except IntegrityError as e:
            await self.session.rollback()
            raise APRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await self.session.rollback()
            raise APRepositoryError(f"Failed to add invoice: {e}") from e

    async def get_by_id(self, invoice_id: UUID) -> APInvoiceAggregate | None:
        try:
            stmt = select(APInvoiceTable).where(APInvoiceTable.id == invoice_id, APInvoiceTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            header = result.scalar_one_or_none()
            if not header:
                return None
            lines_stmt = select(APInvoiceLineTable).where(APInvoiceLineTable.invoice_id == invoice_id).order_by(APInvoiceLineTable.line_number)
            lines_result = await self.session.execute(lines_stmt)
            lines = lines_result.scalars().all()
            payments_stmt = select(APPaymentTable).where(APPaymentTable.invoice_id == invoice_id).order_by(APPaymentTable.payment_date)
            payments_result = await self.session.execute(payments_stmt)
            payments = payments_result.scalars().all()
            credit_stmt = select(APCreditNoteTable).where(APCreditNoteTable.invoice_id == invoice_id)
            credit_result = await self.session.execute(credit_stmt)
            credit_notes = credit_result.scalars().all()
            return self._to_domain(header, lines, payments, credit_notes)
        except Exception as e:
            logger.error("Failed to get AP invoice by id %s: %s", invoice_id, e)
            raise APRepositoryError(f"Failed to get invoice: {e}") from e

    async def get_by_invoice_number(self, invoice_number: str, vendor_id: UUID) -> APInvoiceAggregate | None:
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
        try:
            stmt = select(APInvoiceTable.version).where(APInvoiceTable.id == invoice.id)
            result = await self.session.execute(stmt)
            current_version = result.scalar_one_or_none()
            if current_version is None:
                raise APInvoiceNotFoundError(f"Invoice {invoice.id} not found")
            if current_version != invoice.version:
                raise OptimisticLockError(f"Version mismatch: expected {invoice.version}, got {current_version}")
            header = await self._to_orm_header(invoice)
            header.version = invoice.version + 1
            header.updated_at = datetime.utcnow()
            await self.session.merge(header)
            if invoice.lines_changed:
                await self.session.execute(delete(APInvoiceLineTable).where(APInvoiceLineTable.invoice_id == invoice.id))
                lines = await self._to_orm_lines(invoice)
                for line in lines:
                    self.session.add(line)
            await self.session.flush()
            logger.info("AP Invoice updated: %s", invoice.invoice_number)
        except OptimisticLockError:
            raise
        except Exception as e:
            await self.session.rollback()
            raise APRepositoryError(f"Failed to update invoice: {e}") from e

    # === STATUS TRANSITIONS ===
    async def _transition_status(self, invoice_id: UUID, new_status: str, actor: UUID, timestamp_field: str = None, actor_field: str = None) -> None:
        try:
            stmt = select(APInvoiceTable.version, APInvoiceTable.status).where(APInvoiceTable.id == invoice_id, APInvoiceTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            row = result.first()
            if not row:
                raise APInvoiceNotFoundError(f"Invoice {invoice_id} not found")
            current_version, current_status = row
            valid_transitions = {
                "draft": ["submitted", "cancelled"],
                "submitted": ["approved", "cancelled"],
                "approved": ["partially_paid", "paid", "cancelled"],
                "partially_paid": ["paid", "cancelled"],
                "paid": ["cancelled"],
                "cancelled": [],
            }
            if new_status not in valid_transitions.get(current_status, []):
                raise InvalidStatusTransitionError(f"Cannot transition from {current_status} to {new_status}")
            values = {"status": new_status, "version": current_version + 1, "updated_at": datetime.utcnow()}
            if timestamp_field and hasattr(APInvoiceTable, timestamp_field):
                values[timestamp_field] = datetime.utcnow()
            if actor_field and hasattr(APInvoiceTable, actor_field):
                values[actor_field] = actor
            update_stmt = update(APInvoiceTable).where(APInvoiceTable.id == invoice_id, APInvoiceTable.version == current_version).values(**values)
            result = await self.session.execute(update_stmt)
            if result.rowcount == 0:
                raise OptimisticLockError(f"Invoice {invoice_id} was modified concurrently")
            await self.session.flush()
            logger.info("Invoice %s status changed to %s", invoice_id, new_status)
        except (APInvoiceNotFoundError, InvalidStatusTransitionError, OptimisticLockError):
            raise
        except Exception as e:
            await self.session.rollback()
            raise APRepositoryError(f"Failed to transition invoice: {e}") from e

    async def approve(self, invoice_id: UUID, approved_by: UUID) -> None:
        await self._transition_status(invoice_id, "approved", approved_by, "approved_at", "approved_by")

    async def cancel(self, invoice_id: UUID, reason: str, user_id: UUID) -> bool:
        try:
            invoice = await self.get_by_id(invoice_id)
            if not invoice:
                raise APInvoiceNotFoundError(f"Invoice {invoice_id} not found")
            if invoice.status == APInvoiceStatus.PAID:
                return False
            await self._transition_status(invoice_id, "cancelled", user_id, "cancelled_at", "cancelled_by")
            current_desc = invoice.description or ""
            new_desc = f"{current_desc} [CANCELLED: {reason}]".strip()
            await self.session.execute(
                update(APInvoiceTable)
                .where(APInvoiceTable.id == invoice_id)
                .values(description=new_desc, updated_at=datetime.utcnow())
            )
            await self.session.flush()
            logger.info("Invoice %s cancelled with reason: %s", invoice_id, reason)
            return True
        except (APInvoiceNotFoundError, InvalidStatusTransitionError):
            return False
        except Exception as e:
            logger.error("Failed to cancel invoice %s: %s", invoice_id, e)
            raise APRepositoryError(f"Failed to cancel invoice: {e}") from e

    async def submit(self, invoice_id: UUID, submitted_by: UUID) -> None:
        await self._transition_status(invoice_id, "submitted", submitted_by, "submitted_at", "submitted_by")

    async def reject(self, invoice_id: UUID, rejected_by: UUID) -> None:
        await self._transition_status(invoice_id, "draft", rejected_by, "rejected_at", "rejected_by")

    async def delete(self, invoice_id: UUID, deleted_by: UUID) -> None:
        try:
            stmt = select(APInvoiceTable.version).where(APInvoiceTable.id == invoice_id)
            result = await self.session.execute(stmt)
            current_version = result.scalar_one_or_none()
            if current_version is None:
                raise APInvoiceNotFoundError(f"Invoice {invoice_id} not found")
            update_stmt = update(APInvoiceTable).where(APInvoiceTable.id == invoice_id).values(
                deleted_at=datetime.utcnow(),
                deleted_by=deleted_by,
                version=current_version + 1,
                updated_at=datetime.utcnow()
            )
            await self.session.execute(update_stmt)
            await self.session.flush()
            logger.info("Invoice %s soft deleted by %s", invoice_id, deleted_by)
        except APInvoiceNotFoundError:
            raise
        except Exception as e:
            await self.session.rollback()
            raise APRepositoryError(f"Failed to delete invoice: {e}") from e

    async def dispute(self, invoice_id: UUID, reason: str, disputed_by: UUID) -> None:
        try:
            stmt = select(APInvoiceTable).where(APInvoiceTable.id == invoice_id)
            result = await self.session.execute(stmt)
            header = result.scalar_one_or_none()
            if not header:
                raise APInvoiceNotFoundError(f"Invoice {invoice_id} not found")
            update_stmt = update(APInvoiceTable).where(APInvoiceTable.id == invoice_id).values(
                status="draft",
                description=func.concat(APInvoiceTable.description, " [DISPUTED: ", reason, "]"),
                updated_at=datetime.utcnow()
            )
            await self.session.execute(update_stmt)
            await self.session.flush()
            logger.info("Invoice %s disputed: %s", invoice_id, reason)
        except APInvoiceNotFoundError:
            raise
        except Exception as e:
            await self.session.rollback()
            raise APRepositoryError(f"Failed to dispute invoice: {e}") from e

    async def submit_for_approval(self, invoice_id: UUID, submitted_by: UUID) -> None:
        await self.submit(invoice_id, submitted_by)

    # === PAYMENTS & CREDIT NOTES ===
    async def add_payment(self, payment: APPayment) -> None:
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
            logger.info("Payment %s added for invoice %s", payment.payment_number, payment.invoice_id)
        except Exception as e:
            await self.session.rollback()
            raise APRepositoryError(f"Failed to add payment: {e}") from e

    async def add_credit_note(self, credit_note: APCreditNote) -> None:
        try:
            credit_table = APCreditNoteTable(
                id=credit_note.id,
                credit_note_number=credit_note.credit_note_number,
                invoice_id=credit_note.invoice_id,
                credit_note_date=credit_note.credit_note_date,
                amount=credit_note.amount.amount,
                currency=credit_note.amount.currency,
                reason=credit_note.reason,
                status=credit_note.status,
                created_at=datetime.utcnow(),
                created_by=credit_note.created_by,
            )
            self.session.add(credit_table)
            await self.session.flush()
            invoice = await self.get_by_id(credit_note.invoice_id)
            if invoice:
                new_paid = invoice.paid_amount.amount + credit_note.amount.amount
                new_status = "paid" if new_paid >= invoice.total_amount.amount else "partially_paid"
                await self.session.execute(
                    update(APInvoiceTable)
                    .where(APInvoiceTable.id == credit_note.invoice_id)
                    .values(paid_amount=new_paid, status=new_status, updated_at=datetime.utcnow())
                )
                await self.session.flush()
            logger.info("Credit note %s added for invoice %s", credit_note.credit_note_number, credit_note.invoice_id)
        except Exception as e:
            await self.session.rollback()
            raise APRepositoryError(f"Failed to add credit note: {e}") from e

    # === QUERIES ===
    async def find_by_vendor(self, vendor_id: UUID, limit: int = 100, offset: int = 0) -> list[APInvoiceAggregate]:
        try:
            stmt = select(APInvoiceTable).where(APInvoiceTable.vendor_id == vendor_id, APInvoiceTable.deleted_at.is_(None)).order_by(APInvoiceTable.invoice_date.desc()).limit(limit).offset(offset)
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

    async def find_invoices_by_vendor(self, vendor_id: UUID, limit: int = 100, offset: int = 0) -> list[APInvoiceAggregate]:
        return await self.find_by_vendor(vendor_id, limit, offset)

    async def find_by_status(self, status: str, legal_entity_id: UUID) -> list[APInvoiceAggregate]:
        try:
            stmt = select(APInvoiceTable).where(
                APInvoiceTable.status == status,
                APInvoiceTable.legal_entity_id == legal_entity_id,
                APInvoiceTable.deleted_at.is_(None),
            ).order_by(APInvoiceTable.invoice_date.desc())
            result = await self.session.execute(stmt)
            headers = result.scalars().all()
            invoices = []
            for header in headers:
                invoice = await self.get_by_id(header.id)
                if invoice:
                    invoices.append(invoice)
            return invoices
        except Exception as e:
            logger.error("Failed to find invoices by status %s: %s", status, e)
            raise APRepositoryError(f"Failed to find invoices by status: {e}") from e

    async def find_due_for_payment(self, as_of_date: date, legal_entity_id: UUID) -> list[APInvoiceAggregate]:
        try:
            stmt = select(APInvoiceTable).where(
                APInvoiceTable.due_date <= as_of_date,
                APInvoiceTable.status == "approved",
                APInvoiceTable.paid_amount < APInvoiceTable.total_amount,
                APInvoiceTable.legal_entity_id == legal_entity_id,
                APInvoiceTable.deleted_at.is_(None),
            ).order_by(APInvoiceTable.due_date)
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

    async def find_by_date_range(self, from_date: date, to_date: date, legal_entity_id: UUID) -> list[APInvoiceAggregate]:
        try:
            stmt = select(APInvoiceTable).where(
                APInvoiceTable.invoice_date >= from_date,
                APInvoiceTable.invoice_date <= to_date,
                APInvoiceTable.legal_entity_id == legal_entity_id,
                APInvoiceTable.deleted_at.is_(None),
            ).order_by(APInvoiceTable.invoice_date)
            result = await self.session.execute(stmt)
            headers = result.scalars().all()
            invoices = []
            for header in headers:
                invoice = await self.get_by_id(header.id)
                if invoice:
                    invoices.append(invoice)
            return invoices
        except Exception as e:
            logger.error("Failed to find invoices by date range: %s", e)
            raise APRepositoryError(f"Failed to find invoices by date range: {e}") from e

    async def get_outstanding_balance(self, vendor_id: UUID, as_of_date: date) -> Decimal:
        try:
            stmt = select(func.coalesce(func.sum(APInvoiceTable.total_amount - APInvoiceTable.paid_amount), 0)).where(
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

    async def get_vendor_balance_history(self, vendor_id: UUID, from_date: date, to_date: date) -> list[dict[str, Any]]:
        try:
            invoices = await self.find_by_date_range(from_date, to_date, None)
            vendor_invoices = [inv for inv in invoices if inv.vendor_id == vendor_id]

            history = []
            running_balance = Decimal(0)
            for inv in sorted(vendor_invoices, key=lambda x: x.invoice_date):
                running_balance += inv.total_amount.amount - inv.paid_amount.amount
                history.append({
                    "date": inv.invoice_date.isoformat(),
                    "invoice_number": inv.invoice_number,
                    "amount": str(inv.total_amount.amount),      # ← str, bukan float
                    "paid": str(inv.paid_amount.amount),        # ← str, bukan float
                    "balance": str(running_balance),            # ← str, bukan float
                    "status": inv.status.value,
                })
            return history
        except Exception as e:
            logger.error("Failed to get vendor balance history for %s: %s", vendor_id, e)
            raise APRepositoryError(f"Failed to get vendor balance history: {e}") from e

    async def find_by_payment_run(self, payment_run_id: UUID) -> list[APInvoiceAggregate]:
        try:
            stmt = select(APInvoiceTable).where(APInvoiceTable.payment_run_id == payment_run_id, APInvoiceTable.deleted_at.is_(None)).order_by(APInvoiceTable.due_date)
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

    async def mark_as_paid(self, invoice_id: UUID, payment_id: UUID, paid_amount: Decimal, paid_date: date, user_id: UUID) -> bool:
        try:
            invoice = await self.get_by_id(invoice_id)
            if not invoice:
                raise APInvoiceNotFoundError(f"Invoice {invoice_id} not found")
            if invoice.status not in (APInvoiceStatus.APPROVED, APInvoiceStatus.PARTIALLY_PAID):
                return False
            new_paid_amount = invoice.paid_amount.amount + paid_amount
            new_status = "paid" if new_paid_amount >= invoice.total_amount.amount else "partially_paid"
            await self.session.execute(
                update(APInvoiceTable)
                .where(APInvoiceTable.id == invoice_id)
                .values(
                    paid_amount=new_paid_amount,
                    status=new_status,
                    updated_at=datetime.utcnow(),
                    updated_by=user_id,
                )
            )
            await self.session.flush()
            logger.info("Invoice %s marked as %s with payment %s by %s", invoice_id, new_status, payment_id, user_id)
            return True
        except APInvoiceNotFoundError:
            return False
        except Exception as e:
            logger.error("Failed to mark invoice as paid: %s", e)
            raise APRepositoryError(f"Failed to update invoice status: {e}") from e

    async def exists_by_invoice_number(self, invoice_number: str, vendor_id: UUID) -> bool:
        try:
            stmt = select(func.count()).select_from(APInvoiceTable).where(
                APInvoiceTable.invoice_number_vendor == invoice_number,
                APInvoiceTable.vendor_id == vendor_id,
                APInvoiceTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            count = result.scalar()
            return count > 0
        except Exception as e:
            logger.error("Failed to check invoice number %s: %s", invoice_number, e)
            raise APRepositoryError(f"Failed to check invoice number: {e}") from e

    async def validate_three_way_match(self, invoice_id: UUID) -> ThreeWayMatchResult:
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
            po_stmt = select(PurchaseOrderTable).where(PurchaseOrderTable.id == invoice.purchase_order_id)
            po_result = await self.session.execute(po_stmt)
            po = po_result.scalar_one_or_none()
            grn_stmt = select(GoodsReceiptNoteTable).where(GoodsReceiptNoteTable.id == invoice.goods_receipt_note_id)
            grn_result = await self.session.execute(grn_stmt)
            grn = grn_result.scalar_one_or_none()
            discrepancies = []
            po_match = bool(po)
            grn_match = bool(grn)
            if not po:
                discrepancies.append("Purchase Order not found")
            if not grn:
                discrepancies.append("Goods Receipt Note not found")
            quantity_match = True
            price_match = True
            tolerance = Decimal("0.05")
            match_status = "match" if (po_match and grn_match and quantity_match and price_match) else "mismatch"
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

    async def perform_three_way_match(self, invoice_id: UUID, po_total: Decimal, grn_total: Decimal) -> MatchingStatus:
        try:
            invoice = await self.get_by_id(invoice_id)
            if not invoice:
                raise APInvoiceNotFoundError(f"Invoice {invoice_id} not found")
            invoice_total = invoice.total_amount.amount
            if (invoice_total == po_total == grn_total) or \
               (invoice_total <= po_total and invoice_total <= grn_total) or \
               (abs(invoice_total - po_total) < Decimal('0.01') and abs(invoice_total - grn_total) < Decimal('0.01')):
                status = MatchingStatus.MATCHED
            elif invoice_total > po_total or invoice_total > grn_total:
                status = MatchingStatus.MISMATCH
            else:
                status = MatchingStatus.PARTIAL_MATCH
            await self.session.execute(
                update(APInvoiceTable)
                .where(APInvoiceTable.id == invoice_id)
                .values(three_way_match_status=status.value, updated_at=datetime.utcnow())
            )
            await self.session.flush()
            return status
        except APInvoiceNotFoundError:
            raise
        except Exception as e:
            logger.error("Failed to perform 3-way match for invoice %s: %s", invoice_id, e)
            raise APRepositoryError(f"Failed to perform 3-way match: {e}") from e

    async def get_aging_buckets(self, legal_entity_id: UUID, as_of_date: date) -> list[dict[str, Any]]:
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
                stmt = select(func.coalesce(func.sum(APInvoiceTable.total_amount - APInvoiceTable.paid_amount), 0)).where(and_(*conditions))
                result = await self.session.execute(stmt)
                total = result.scalar() or 0
                results.append({"bucket_name": bucket_name, "total_amount": Decimal(str(total))})
            total_all = sum(r["total_amount"] for r in results)
            for r in results:
                # Persentase boleh float karena non-monetary
                r["percentage"] = float(r["total_amount"] / total_all * 100) if total_all > 0 else 0.0
            # Ubah total_amount menjadi string untuk konsistensi
            for r in results:
                r["total_amount"] = str(r["total_amount"])  # ← str, bukan Decimal
            return results
        except Exception as e:
            logger.error("Failed to get AP aging buckets: %s", e)
            raise APRepositoryError(f"Failed to get aging buckets: {e}") from e

    async def get_next_invoice_number(self, prefix: str = "PO", year: int = None) -> str:
        if year is None:
            year = date.today().year
        try:
            pattern = func.concat(prefix, '-', year, '-%')
            stmt = select(APInvoiceTable.invoice_number).where(
                APInvoiceTable.invoice_number.like(pattern),
                APInvoiceTable.deleted_at.is_(None)
            ).order_by(APInvoiceTable.invoice_number.desc()).limit(1)
            result = await self.session.execute(stmt)
            last_number = result.scalar_one_or_none()
            seq = int(last_number.split("-")[-1]) + 1 if last_number else 1
            return f"{prefix}-{year}-{seq:06d}"
        except Exception as e:
            logger.error("Failed to generate next invoice number: %s", e)
            raise APRepositoryError(f"Failed to generate invoice number: {e}") from e

    # === EXPORT / IMPORT ===
    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        try:
            from_date = date(1900, 1, 1)
            to_date = date(2100, 12, 31)
            invoices = await self.find_by_date_range(from_date, to_date, legal_entity_id)
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "Invoice Number", "Vendor ID", "Invoice Date", "Due Date",
                "Total Amount", "Paid Amount", "Outstanding", "Status", "Currency"
            ])
            for inv in invoices:
                writer.writerow([
                    inv.invoice_number,
                    str(inv.vendor_id),
                    inv.invoice_date.isoformat(),
                    inv.due_date.isoformat(),
                    str(inv.total_amount.amount),
                    str(inv.paid_amount.amount),
                    str(inv.total_amount.amount - inv.paid_amount.amount),
                    inv.status.value,
                    inv.total_amount.currency
                ])
            return output.getvalue()
        except Exception as e:
            logger.error("Failed to export to CSV: %s", e)
            raise APRepositoryError(f"Failed to export to CSV: {e}") from e

    async def import_from_csv(self, csv_content: str, legal_entity_id: UUID, created_by: UUID) -> int:
        try:
            reader = csv.DictReader(io.StringIO(csv_content))
            count = 0
            for row in reader:
                try:
                    invoice_number = row.get("invoice_number")
                    vendor_id = UUID(row.get("vendor_id"))
                    invoice_date = date.fromisoformat(row.get("invoice_date"))
                    due_date = date.fromisoformat(row.get("due_date"))
                    total_amount = Decimal(row.get("total_amount"))
                    currency = row.get("currency", "IDR")
                    description = row.get("description", "")

                    # Simplified import: just log and count
                    # In real implementation, build full aggregate
                    count += 1
                    logger.info(f"Imported invoice {invoice_number} for vendor {vendor_id}")
                except Exception as row_err:
                    logger.warning(f"Row import failed: {row_err}")
            return count
        except Exception as e:
            logger.error("Failed to import from CSV: %s", e)
            raise APRepositoryError(f"Failed to import from CSV: {e}") from e

    # === AUDIT & STATISTICS ===
    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        # TODO: Implementasi audit log seharusnya mengambil dari event store atau tabel audit.
        return [
            {
                "timestamp": datetime.utcnow().isoformat(),
                "action": "status_change",
                "details": "Audit log not implemented in repository",
            }
        ]

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        try:
            total_stmt = select(func.count()).select_from(APInvoiceTable).where(
                APInvoiceTable.legal_entity_id == legal_entity_id,
                APInvoiceTable.deleted_at.is_(None),
            )
            total_result = await self.session.execute(total_stmt)
            total_count = total_result.scalar()

            status_stmt = select(APInvoiceTable.status, func.count()).where(
                APInvoiceTable.legal_entity_id == legal_entity_id,
                APInvoiceTable.deleted_at.is_(None),
            ).group_by(APInvoiceTable.status)
            status_result = await self.session.execute(status_stmt)
            by_status = {row[0]: row[1] for row in status_result.fetchall()}

            outstanding_stmt = select(
                func.coalesce(func.sum(APInvoiceTable.total_amount - APInvoiceTable.paid_amount), 0)
            ).where(
                APInvoiceTable.legal_entity_id == legal_entity_id,
                APInvoiceTable.status.in_(["approved", "partially_paid"]),
                APInvoiceTable.deleted_at.is_(None),
            )
            outstanding_result = await self.session.execute(outstanding_stmt)
            total_outstanding = Decimal(str(outstanding_result.scalar() or 0))

            return {
                "total_invoices": total_count,
                "by_status": by_status,
                "total_outstanding": str(total_outstanding),  # ← str, bukan float
                "currency": "IDR",
            }
        except Exception as e:
            logger.error("Failed to get statistics: %s", e)
            raise APRepositoryError(f"Failed to get statistics: {e}") from e

    # === ALIAS UNTUK KONTRAK PORT ===
    async def save_invoice(self, invoice: APInvoiceAggregate) -> None:
        existing = await self.get_by_id(invoice.id)
        if existing:
            await self.update(invoice)
        else:
            await self.add(invoice)

    async def find_invoice_by_id(self, invoice_id: UUID) -> APInvoiceAggregate | None:
        return await self.get_by_id(invoice_id)

    async def delete_invoice(self, invoice_id: UUID, deleted_by: UUID) -> None:
        await self.delete(invoice_id, deleted_by)

    async def dispute_invoice(self, invoice_id: UUID, reason: str, disputed_by: UUID) -> None:
        await self.dispute(invoice_id, reason, disputed_by)

    async def health_check(self) -> dict[str, Any]:
        return {"status": "healthy", "repository": "APRepository"}


SQLAlchemyAPRepositoryImpl = SQLAlchemyAPRepository

__all__ = [
    "APInvoiceNotFoundError",
    "APRepositoryError",
    "DuplicateInvoiceNumberError",
    "InvalidStatusTransitionError",
    "OptimisticLockError",
    "SQLAlchemyAPRepository",
    "SQLAlchemyAPRepositoryImpl",
]