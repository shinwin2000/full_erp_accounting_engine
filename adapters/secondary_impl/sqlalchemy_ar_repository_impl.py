#!/usr/bin/env python3
"""
Module: sqlalchemy_ar_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk Account Receivable Invoice - LENGKAP.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.shared_value_objects.money_vo import Money
from domain.subledger_ar.aggregate_root import ARInvoiceAggregate
from domain.subledger_ar.credit_note_entity import ARCreditNote
from domain.subledger_ar.debit_note_entity import ARDebitNote
from domain.subledger_ar.invoice_entity import ARInvoiceLine, ARInvoiceStatus
from domain.subledger_ar.payment_entity import ARPayment
from infrastructure.persistence_orm.ar_credit_note_table import ARCreditNoteTable
from infrastructure.persistence_orm.ar_debit_note_table import ARDebitNoteTable
from infrastructure.persistence_orm.ar_invoice_line_table import ARInvoiceLineTable
from infrastructure.persistence_orm.ar_invoice_table import ARInvoiceTable
from infrastructure.persistence_orm.ar_payment_table import ARPaymentTable
from ports.primary.ar_repository_port import ARRepositoryPort

logger = logging.getLogger(__name__)


class ARRepositoryError(Exception):
    pass


class DuplicateInvoiceNumberError(ARRepositoryError):
    pass


class ARInvoiceNotFoundError(ARRepositoryError):
    pass


class InvalidStatusTransitionError(ARRepositoryError):
    pass


class OptimisticLockError(ARRepositoryError):
    pass


class SQLAlchemyARRepository(ARRepositoryPort):
    def __init__(self, session: AsyncSession | None = None, legal_entity_id: UUID | None = None):
        self._session = session
        self._legal_entity_id = legal_entity_id
        self._audit_log: list[dict[str, Any]] = []

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    def _get_legal_entity_id(self) -> UUID:
        if self._legal_entity_id is None:
            raise ValueError("legal_entity_id not set in repository")
        return self._legal_entity_id

    # ========================================================================
    # HELPER MAPPING
    # ========================================================================

    def _to_domain(
        self,
        header: ARInvoiceTable,
        lines: list[ARInvoiceLineTable],
        payments: list[ARPaymentTable] = None,
        credit_notes: list[ARCreditNoteTable] = None,
        debit_notes: list[ARDebitNoteTable] = None,
    ) -> ARInvoiceAggregate:
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
        domain_debit_notes = []
        if debit_notes:
            for note in debit_notes:
                domain_debit_notes.append(
                    ARDebitNote(
                        id=note.id,
                        debit_note_number=note.debit_note_number,
                        debit_note_date=note.debit_note_date,
                        amount=Money(amount=note.amount, currency=note.currency or "IDR"),
                        reason=note.reason,
                        status=note.status,
                    )
                )
        status_map = {
            "draft": ARInvoiceStatus.DRAFT,
            "submitted": ARInvoiceStatus.SUBMITTED,
            "approved": ARInvoiceStatus.APPROVED,
            "partially_paid": ARInvoiceStatus.PARTIALLY_PAID,
            "paid": ARInvoiceStatus.PAID,
            "overdue": ARInvoiceStatus.OVERDUE,
            "cancelled": ARInvoiceStatus.CANCELLED,
            "disputed": ARInvoiceStatus.DISPUTED,
            "written_off": ARInvoiceStatus.WRITTEN_OFF,
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
        if domain_payments:
            aggregate._payments = domain_payments
        if domain_credit_notes:
            aggregate._credit_notes = domain_credit_notes
        if domain_debit_notes:
            aggregate._debit_notes = domain_debit_notes
        return aggregate

    async def _to_orm_header(self, aggregate: ARInvoiceAggregate) -> ARInvoiceTable:
        return ARInvoiceTable(
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
            status=aggregate.status.value if hasattr(aggregate.status, "value") else str(aggregate.status),
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

    async def _to_orm_lines(self, aggregate: ARInvoiceAggregate) -> list[ARInvoiceLineTable]:
        lines = []
        for i, line in enumerate(aggregate.lines):
            lines.append(
                ARInvoiceLineTable(
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
                )
            )
        return lines

    async def _log_audit(self, action: str, invoice_id: UUID, details: dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "invoice_id": str(invoice_id),
            "details": details
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    # ========================================================================
    # CORE CRUD
    # ========================================================================

    async def add(self, invoice: ARInvoiceAggregate) -> None:
        session = await self._get_session()
        try:
            exists = await self.exists_by_invoice_number(invoice.invoice_number, invoice.legal_entity_id)
            if exists:
                raise DuplicateInvoiceNumberError(f"Invoice number {invoice.invoice_number} already exists")
            header = await self._to_orm_header(invoice)
            lines = await self._to_orm_lines(invoice)
            session.add(header)
            for line in lines:
                session.add(line)
            await session.flush()
            await self._log_audit("ADD", invoice.id, {"invoice_number": invoice.invoice_number})
            logger.info("AR Invoice added: %s", invoice.invoice_number)
        except DuplicateInvoiceNumberError:
            raise
        except IntegrityError as e:
            await session.rollback()
            raise ARRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await session.rollback()
            raise ARRepositoryError(f"Failed to add invoice: {e}") from e

    async def get_by_id(self, invoice_id: UUID) -> ARInvoiceAggregate | None:
        session = await self._get_session()
        try:
            stmt = select(ARInvoiceTable).where(ARInvoiceTable.id == invoice_id, ARInvoiceTable.deleted_at.is_(None))
            result = await session.execute(stmt)
            header = result.scalar_one_or_none()
            if not header:
                return None
            lines_stmt = select(ARInvoiceLineTable).where(ARInvoiceLineTable.invoice_id == invoice_id).order_by(ARInvoiceLineTable.line_number)
            lines_result = await session.execute(lines_stmt)
            lines = lines_result.scalars().all()
            payments_stmt = select(ARPaymentTable).where(ARPaymentTable.invoice_id == invoice_id).order_by(ARPaymentTable.payment_date)
            payments_result = await session.execute(payments_stmt)
            payments = payments_result.scalars().all()
            credit_stmt = select(ARCreditNoteTable).where(ARCreditNoteTable.invoice_id == invoice_id)
            credit_result = await session.execute(credit_stmt)
            credit_notes = credit_result.scalars().all()
            debit_stmt = select(ARDebitNoteTable).where(ARDebitNoteTable.invoice_id == invoice_id)
            debit_result = await session.execute(debit_stmt)
            debit_notes = debit_result.scalars().all()
            return self._to_domain(header, lines, payments, credit_notes, debit_notes)
        except Exception as e:
            logger.error("Failed to get AR invoice by id %s: %s", invoice_id, e)
            raise ARRepositoryError(f"Failed to get invoice: {e}") from e

    async def get_by_invoice_number(self, invoice_number: str, legal_entity_id: UUID) -> ARInvoiceAggregate | None:
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
        session = await self._get_session()
        try:
            stmt = select(ARInvoiceTable.version).where(ARInvoiceTable.id == invoice.id)
            result = await session.execute(stmt)
            current_version = result.scalar_one_or_none()
            if current_version is None:
                raise ARInvoiceNotFoundError(f"Invoice {invoice.id} not found")
            if current_version != invoice.version:
                raise OptimisticLockError(f"Version mismatch: expected {invoice.version}, got {current_version}")
            header = await self._to_orm_header(invoice)
            header.version = invoice.version + 1
            header.updated_at = datetime.utcnow()
            await session.merge(header)
            if invoice.lines_changed:
                await session.execute(delete(ARInvoiceLineTable).where(ARInvoiceLineTable.invoice_id == invoice.id))
                lines = await self._to_orm_lines(invoice)
                for line in lines:
                    session.add(line)
            await session.flush()
            await self._log_audit("UPDATE", invoice.id, {"invoice_number": invoice.invoice_number})
            logger.info("AR Invoice updated: %s", invoice.invoice_number)
        except OptimisticLockError:
            raise
        except Exception as e:
            await session.rollback()
            raise ARRepositoryError(f"Failed to update invoice: {e}") from e

    async def delete(self, invoice_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        session = await self._get_session()
        try:
            invoice = await self.get_by_id(invoice_id)
            if not invoice:
                return False
            if permanent:
                await session.execute(delete(ARInvoiceLineTable).where(ARInvoiceLineTable.invoice_id == invoice_id))
                stmt = delete(ARInvoiceTable).where(ARInvoiceTable.id == invoice_id)
                result = await session.execute(stmt)
            else:
                stmt = update(ARInvoiceTable).where(ARInvoiceTable.id == invoice_id).values(
                    deleted_at=datetime.utcnow(),
                    deleted_by=user_id,
                    status=ARInvoiceStatus.CANCELLED.value,
                    updated_at=datetime.utcnow()
                )
                result = await session.execute(stmt)
            await session.flush()
            if result.rowcount > 0:
                await self._log_audit("DELETE", invoice_id, {"permanent": permanent, "user_id": str(user_id)})
                logger.info("Invoice %s deleted by %s", invoice_id, user_id)
            return result.rowcount > 0
        except Exception as e:
            await session.rollback()
            raise ARRepositoryError(f"Failed to delete invoice: {e}") from e

    # ========================================================================
    # STATUS TRANSITIONS
    # ========================================================================

    async def _transition_status(self, invoice_id: UUID, new_status: str, actor: UUID, actor_field: str = None) -> None:
        session = await self._get_session()
        try:
            stmt = select(ARInvoiceTable.version, ARInvoiceTable.status).where(ARInvoiceTable.id == invoice_id, ARInvoiceTable.deleted_at.is_(None))
            result = await session.execute(stmt)
            row = result.first()
            if not row:
                raise ARInvoiceNotFoundError(f"Invoice {invoice_id} not found")
            current_version, current_status = row
            valid_transitions = {
                "draft": ["submitted", "cancelled"],
                "submitted": ["approved", "cancelled"],
                "approved": ["partially_paid", "paid", "overdue", "cancelled"],
                "partially_paid": ["paid", "overdue", "cancelled"],
                "paid": ["cancelled"],
                "overdue": ["partially_paid", "paid", "cancelled"],
                "cancelled": [],
                "disputed": ["draft", "cancelled"],
                "written_off": [],
            }
            if new_status not in valid_transitions.get(current_status, []):
                raise InvalidStatusTransitionError(f"Cannot transition from {current_status} to {new_status}")
            values = {"status": new_status, "version": current_version + 1, "updated_at": datetime.utcnow()}
            if actor_field:
                values[actor_field] = actor
            update_stmt = update(ARInvoiceTable).where(ARInvoiceTable.id == invoice_id, ARInvoiceTable.version == current_version).values(**values)
            result = await session.execute(update_stmt)
            if result.rowcount == 0:
                raise OptimisticLockError(f"Invoice {invoice_id} was modified concurrently")
            await session.flush()
            await self._log_audit(f"STATUS_CHANGE_TO_{new_status.upper()}", invoice_id, {"from": current_status, "to": new_status, "actor": str(actor)})
            logger.info("Invoice %s status changed to %s", invoice_id, new_status)
        except (ARInvoiceNotFoundError, InvalidStatusTransitionError, OptimisticLockError):
            raise
        except Exception as e:
            await session.rollback()
            raise ARRepositoryError(f"Failed to transition invoice: {e}") from e

    async def approve(self, invoice_id: UUID, approved_by: UUID) -> None:
        await self._transition_status(invoice_id, "approved", approved_by, "approved_by")
        session = await self._get_session()
        await session.execute(update(ARInvoiceTable).where(ARInvoiceTable.id == invoice_id).values(approved_at=datetime.utcnow(), approved_by=approved_by))

    async def cancel(self, invoice_id: UUID, reason: str, user_id: UUID) -> None:
        await self._transition_status(invoice_id, "cancelled", user_id, "cancelled_by")
        session = await self._get_session()
        await session.execute(
            update(ARInvoiceTable)
            .where(ARInvoiceTable.id == invoice_id)
            .values(cancellation_reason=reason, cancelled_at=datetime.utcnow(), cancelled_by=user_id)
        )

    async def submit(self, invoice_id: UUID, submitted_by: UUID) -> None:
        await self._transition_status(invoice_id, "submitted", submitted_by, "submitted_by")

    async def reject(self, invoice_id: UUID, rejected_by: UUID) -> None:
        await self._transition_status(invoice_id, "draft", rejected_by, "rejected_by")

    async def dispute(self, invoice_id: UUID, reason: str, user_id: UUID) -> None:
        await self._transition_status(invoice_id, "disputed", user_id)
        session = await self._get_session()
        await session.execute(
            update(ARInvoiceTable)
            .where(ARInvoiceTable.id == invoice_id)
            .values(description=func.concat(ARInvoiceTable.description, " [DISPUTED: ", reason, "]"), disputed_reason=reason)
        )

    async def submit_for_approval(self, invoice_id: UUID, submitted_by: UUID) -> None:
        await self.submit(invoice_id, submitted_by)

    # ========================================================================
    # PAYMENT / CREDIT / DEBIT NOTES
    # ========================================================================

    async def record_payment(self, invoice_id: UUID, amount: Decimal, payment_date: date, user_id: UUID) -> None:
        session = await self._get_session()
        try:
            invoice = await self.get_by_id(invoice_id)
            if not invoice:
                raise ARInvoiceNotFoundError(f"Invoice {invoice_id} not found")
            if invoice.status not in (ARInvoiceStatus.APPROVED, ARInvoiceStatus.PARTIALLY_PAID):
                raise InvalidStatusTransitionError("Invoice not in approvable state for payment")
            payment_id = uuid4()
            payment_number = f"PAY-{payment_date.strftime('%Y%m%d')}-{invoice_id.hex[:6]}"
            payment_table = ARPaymentTable(
                id=payment_id,
                payment_number=payment_number,
                invoice_id=invoice_id,
                payment_date=payment_date,
                amount=amount,
                currency=invoice.total_amount.currency,
                payment_method="TRANSFER",
                reference_number="",
                status="completed",
                created_at=datetime.utcnow(),
                created_by=user_id,
            )
            session.add(payment_table)
            new_paid = invoice.paid_amount.amount + amount
            new_status = "paid" if new_paid >= invoice.total_amount.amount else "partially_paid"
            await session.execute(
                update(ARInvoiceTable)
                .where(ARInvoiceTable.id == invoice_id)
                .values(
                    paid_amount=new_paid,
                    status=new_status,
                    updated_at=datetime.utcnow(),
                    last_payment_date=payment_date,
                    last_payment_amount=amount,
                )
            )
            await session.flush()
            await self._log_audit("PAYMENT", invoice_id, {"payment_id": str(payment_id), "amount": str(amount)})
            logger.info("Payment %s added for invoice %s", payment_number, invoice_id)
        except Exception as e:
            await session.rollback()
            raise ARRepositoryError(f"Failed to record payment: {e}") from e

    async def add_payment(self, payment: ARPayment) -> None:
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
            invoice = await self.get_by_id(payment.invoice_id)
            if invoice:
                new_paid = invoice.paid_amount.amount + payment.amount.amount
                new_status = "paid" if new_paid >= invoice.total_amount.amount else "partially_paid"
                await session.execute(
                    update(ARInvoiceTable)
                    .where(ARInvoiceTable.id == payment.invoice_id)
                    .values(paid_amount=new_paid, status=new_status, updated_at=datetime.utcnow())
                )
                await session.flush()
            await self._log_audit("PAYMENT", payment.invoice_id, {"payment_id": str(payment.id), "amount": str(payment.amount.amount)})
            logger.info("Payment %s added for invoice %s", payment.payment_number, payment.invoice_id)
        except Exception as e:
            await session.rollback()
            raise ARRepositoryError(f"Failed to add payment: {e}") from e

    async def add_credit_note(self, credit_note: ARCreditNote) -> None:
        session = await self._get_session()
        try:
            credit_table = ARCreditNoteTable(
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
            session.add(credit_table)
            await session.flush()
            invoice = await self.get_by_id(credit_note.invoice_id)
            if invoice:
                new_paid = invoice.paid_amount.amount + credit_note.amount.amount
                new_status = "paid" if new_paid >= invoice.total_amount.amount else "partially_paid"
                await session.execute(
                    update(ARInvoiceTable)
                    .where(ARInvoiceTable.id == credit_note.invoice_id)
                    .values(paid_amount=new_paid, status=new_status, updated_at=datetime.utcnow())
                )
                await session.flush()
            await self._log_audit("CREDIT_NOTE", credit_note.invoice_id, {"credit_note_id": str(credit_note.id), "amount": str(credit_note.amount.amount)})
            logger.info("Credit note %s added for invoice %s", credit_note.credit_note_number, credit_note.invoice_id)
        except Exception as e:
            await session.rollback()
            raise ARRepositoryError(f"Failed to add credit note: {e}") from e

    async def add_debit_note(self, debit_note: ARDebitNote) -> None:
        session = await self._get_session()
        try:
            debit_table = ARDebitNoteTable(
                id=debit_note.id,
                debit_note_number=debit_note.debit_note_number,
                invoice_id=debit_note.invoice_id,
                debit_note_date=debit_note.debit_note_date,
                amount=debit_note.amount.amount,
                currency=debit_note.amount.currency,
                reason=debit_note.reason,
                status=debit_note.status,
                created_at=datetime.utcnow(),
                created_by=debit_note.created_by,
            )
            session.add(debit_table)
            await session.flush()
            invoice = await self.get_by_id(debit_note.invoice_id)
            if invoice:
                new_paid = invoice.paid_amount.amount + debit_note.amount.amount
                new_status = "paid" if new_paid >= invoice.total_amount.amount else "partially_paid"
                await session.execute(
                    update(ARInvoiceTable)
                    .where(ARInvoiceTable.id == debit_note.invoice_id)
                    .values(paid_amount=new_paid, status=new_status, updated_at=datetime.utcnow())
                )
                await session.flush()
            await self._log_audit("DEBIT_NOTE", debit_note.invoice_id, {"debit_note_id": str(debit_note.id), "amount": str(debit_note.amount.amount)})
            logger.info("Debit note %s added for invoice %s", debit_note.debit_note_number, debit_note.invoice_id)
        except Exception as e:
            await session.rollback()
            raise ARRepositoryError(f"Failed to add debit note: {e}") from e

    # ========================================================================
    # QUERY METHODS
    # ========================================================================

    async def find_by_customer(self, customer_id: UUID, legal_entity_id: UUID) -> list[ARInvoiceAggregate]:
        session = await self._get_session()
        try:
            stmt = select(ARInvoiceTable).where(
                ARInvoiceTable.customer_id == customer_id,
                ARInvoiceTable.legal_entity_id == legal_entity_id,
                ARInvoiceTable.deleted_at.is_(None),
            ).order_by(ARInvoiceTable.invoice_date.desc())
            result = await session.execute(stmt)
            headers = result.scalars().all()
            invoices = []
            for header in headers:
                invoice = await self.get_by_id(header.id)
                if invoice:
                    invoices.append(invoice)
            return invoices
        except Exception as e:
            raise ARRepositoryError(f"Failed to find invoices by customer: {e}") from e

    async def find_by_status(self, status: str, legal_entity_id: UUID, limit: int = 100, offset: int = 0) -> list[ARInvoiceAggregate]:
        session = await self._get_session()
        try:
            stmt = select(ARInvoiceTable).where(
                ARInvoiceTable.status == status,
                ARInvoiceTable.legal_entity_id == legal_entity_id,
                ARInvoiceTable.deleted_at.is_(None),
            ).order_by(ARInvoiceTable.invoice_date.desc()).limit(limit).offset(offset)
            result = await session.execute(stmt)
            headers = result.scalars().all()
            invoices = []
            for header in headers:
                invoice = await self.get_by_id(header.id)
                if invoice:
                    invoices.append(invoice)
            return invoices
        except Exception as e:
            logger.error("Failed to find invoices by status %s: %s", status, e)
            raise ARRepositoryError(f"Failed to find invoices by status: {e}") from e

    async def find_by_date_range(self, from_date: date, to_date: date, legal_entity_id: UUID) -> list[ARInvoiceAggregate]:
        session = await self._get_session()
        try:
            stmt = select(ARInvoiceTable).where(
                ARInvoiceTable.invoice_date >= from_date,
                ARInvoiceTable.invoice_date <= to_date,
                ARInvoiceTable.legal_entity_id == legal_entity_id,
                ARInvoiceTable.deleted_at.is_(None),
            ).order_by(ARInvoiceTable.invoice_date)
            result = await session.execute(stmt)
            headers = result.scalars().all()
            invoices = []
            for header in headers:
                invoice = await self.get_by_id(header.id)
                if invoice:
                    invoices.append(invoice)
            return invoices
        except Exception as e:
            logger.error("Failed to find invoices by date range: %s", e)
            raise ARRepositoryError(f"Failed to find invoices by date range: {e}") from e

    async def find_overdue_invoices(self, as_of_date: date, legal_entity_id: UUID) -> list[ARInvoiceAggregate]:
        session = await self._get_session()
        try:
            stmt = select(ARInvoiceTable).where(
                ARInvoiceTable.due_date < as_of_date,
                ARInvoiceTable.status.in_(["approved", "partially_paid"]),
                ARInvoiceTable.legal_entity_id == legal_entity_id,
                ARInvoiceTable.deleted_at.is_(None),
            ).order_by(ARInvoiceTable.due_date)
            result = await session.execute(stmt)
            headers = result.scalars().all()
            invoices = []
            for header in headers:
                invoice = await self.get_by_id(header.id)
                if invoice:
                    invoices.append(invoice)
            return invoices
        except Exception as e:
            raise ARRepositoryError(f"Failed to find overdue invoices: {e}") from e

    # ===== NEW: find_invoices_by_customer (sesuai port) =====
    async def find_invoices_by_customer(self, customer_id: UUID, legal_entity_id: UUID | None = None) -> list[ARInvoiceAggregate]:
        """
        Cari semua invoice untuk customer tertentu.
        Method ini adalah implementasi dari kontrak ARRepositoryPort.
        Jika legal_entity_id tidak diberikan, akan menggunakan nilai dari self._get_legal_entity_id().
        """
        if legal_entity_id is None:
            legal_entity_id = self._get_legal_entity_id()
        return await self.find_by_customer(customer_id, legal_entity_id)

    # ===== NEW: get_outstanding_balance =====
    async def get_outstanding_balance(self, customer_id: UUID, as_of_date: date) -> Decimal:
        """Get outstanding balance for a customer as of a specific date."""
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        try:
            stmt = select(func.coalesce(func.sum(ARInvoiceTable.total_amount - ARInvoiceTable.paid_amount), 0)).where(
                ARInvoiceTable.customer_id == customer_id,
                ARInvoiceTable.legal_entity_id == legal_entity_id,
                ARInvoiceTable.due_date <= as_of_date,
                ARInvoiceTable.status.in_(["approved", "partially_paid", "overdue"]),
                ARInvoiceTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            outstanding = result.scalar() or 0
            return Decimal(str(outstanding))
        except Exception as e:
            raise ARRepositoryError(f"Failed to get outstanding balance: {e}") from e

    async def get_dunning_candidates(self, as_of_date: date) -> list[ARInvoiceAggregate]:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        try:
            stmt = select(ARInvoiceTable).where(
                ARInvoiceTable.due_date < as_of_date,
                ARInvoiceTable.status.in_(["approved", "partially_paid", "overdue"]),
                ARInvoiceTable.legal_entity_id == legal_entity_id,
                ARInvoiceTable.deleted_at.is_(None),
            ).order_by(ARInvoiceTable.due_date)
            result = await session.execute(stmt)
            headers = result.scalars().all()
            invoices = []
            for header in headers:
                invoice = await self.get_by_id(header.id)
                if invoice:
                    invoices.append(invoice)
            return invoices
        except Exception as e:
            raise ARRepositoryError(f"Failed to get dunning candidates: {e}") from e

    async def get_aging_buckets(self, legal_entity_id: UUID, as_of_date: date) -> list[dict[str, Any]]:
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
                if bucket_name == "120+ days":
                    conditions.append(ARInvoiceTable.due_date <= as_of_date - timedelta(days=120))
                else:
                    if start:
                        conditions.append(ARInvoiceTable.due_date <= start)
                    if end:
                        conditions.append(ARInvoiceTable.due_date >= end)
                stmt = select(func.coalesce(func.sum(ARInvoiceTable.total_amount - ARInvoiceTable.paid_amount), 0)).where(and_(*conditions))
                result = await session.execute(stmt)
                total = result.scalar() or 0
                results.append({"bucket_name": bucket_name, "total_amount": Decimal(str(total))})
            total_all = sum(r["total_amount"] for r in results)
            for r in results:
                r["percentage"] = float(r["total_amount"] / total_all * 100) if total_all > 0 else 0
            return results
        except Exception as e:
            raise ARRepositoryError(f"Failed to get aging buckets: {e}") from e

    async def get_customer_balance_history(self, customer_id: UUID, start_date: date, end_date: date) -> list[dict[str, Any]]:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        try:
            stmt = select(ARInvoiceTable).where(
                ARInvoiceTable.customer_id == customer_id,
                ARInvoiceTable.legal_entity_id == legal_entity_id,
                ARInvoiceTable.deleted_at.is_(None),
            ).order_by(ARInvoiceTable.invoice_date.desc())
            result = await session.execute(stmt)
            headers = result.scalars().all()
            history = []
            running_balance = Decimal(0)
            filtered = [h for h in headers if start_date <= h.invoice_date <= end_date]
            for header in reversed(filtered):
                running_balance += header.total_amount - header.paid_amount
                history.append({
                    "date": header.invoice_date.isoformat(),
                    "invoice_number": header.invoice_number,
                    "amount": float(header.total_amount),
                    "paid": float(header.paid_amount),
                    "balance": float(running_balance),
                })
            return list(reversed(history))
        except Exception as e:
            raise ARRepositoryError(f"Failed to get customer balance history: {e}") from e

    async def increment_dunning_level(self, invoice_id: UUID, dunning_level: int) -> None:
        session = await self._get_session()
        try:
            await session.execute(
                update(ARInvoiceTable)
                .where(ARInvoiceTable.id == invoice_id)
                .values(dunning_level=dunning_level, updated_at=datetime.utcnow())
            )
            await session.flush()
            await self._log_audit("DUNNING_LEVEL", invoice_id, {"dunning_level": dunning_level})
        except Exception as e:
            raise ARRepositoryError(f"Failed to increment dunning level: {e}") from e

    async def get_total_outstanding_for_customer(self, customer_id: UUID) -> Decimal:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        try:
            stmt = select(func.coalesce(func.sum(ARInvoiceTable.total_amount - ARInvoiceTable.paid_amount), 0)).where(
                ARInvoiceTable.customer_id == customer_id,
                ARInvoiceTable.legal_entity_id == legal_entity_id,
                ARInvoiceTable.status.in_(["approved", "partially_paid", "overdue"]),
                ARInvoiceTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            outstanding = result.scalar() or 0
            return Decimal(str(outstanding))
        except Exception as e:
            raise ARRepositoryError(f"Failed to get total outstanding for customer: {e}") from e

    async def is_credit_limit_exceeded(self, customer_id: UUID, credit_limit: Decimal) -> bool:
        outstanding = await self.get_total_outstanding_for_customer(customer_id)
        return outstanding > credit_limit

    async def write_off(self, invoice_id: UUID, amount: Decimal, reason: str, user_id: UUID) -> None:
        session = await self._get_session()
        try:
            invoice = await self.get_by_id(invoice_id)
            if not invoice:
                raise ARInvoiceNotFoundError(f"Invoice {invoice_id} not found")
            if amount <= 0 or amount > invoice.outstanding_amount.amount:
                raise ValueError("Invalid write-off amount")
            new_paid = invoice.paid_amount.amount + amount
            new_status = "written_off" if new_paid >= invoice.total_amount.amount else "partially_paid"
            await session.execute(
                update(ARInvoiceTable)
                .where(ARInvoiceTable.id == invoice_id)
                .values(
                    paid_amount=new_paid,
                    status=new_status,
                    write_off_amount=amount,
                    write_off_date=datetime.utcnow().date(),
                    write_off_reason=reason,
                    updated_at=datetime.utcnow(),
                    written_off_by=user_id,
                )
            )
            await session.flush()
            await self._log_audit("WRITE_OFF", invoice_id, {"amount": str(amount), "reason": reason, "user_id": str(user_id)})
            logger.info("Invoice %s written off by %s", invoice_id, user_id)
        except Exception as e:
            await session.rollback()
            raise ARRepositoryError(f"Failed to write off invoice: {e}") from e

    # ========================================================================
    # UTILITY METHODS
    # ========================================================================

    async def exists_by_invoice_number(self, invoice_number: str, legal_entity_id: UUID) -> bool:
        session = await self._get_session()
        try:
            stmt = select(func.count()).select_from(ARInvoiceTable).where(
                ARInvoiceTable.invoice_number == invoice_number,
                ARInvoiceTable.legal_entity_id == legal_entity_id,
                ARInvoiceTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            count = result.scalar()
            return count > 0
        except Exception as e:
            raise ARRepositoryError(f"Failed to check invoice number: {e}") from e

    async def get_next_invoice_number(self, prefix: str = "INV", year: int = None) -> str:
        if year is None:
            year = date.today().year
        session = await self._get_session()
        try:
            pattern = func.concat(prefix, '-', year, '-%')
            stmt = select(ARInvoiceTable.invoice_number).where(
                ARInvoiceTable.invoice_number.like(pattern),
                ARInvoiceTable.deleted_at.is_(None)
            ).order_by(ARInvoiceTable.invoice_number.desc()).limit(1)
            result = await session.execute(stmt)
            last_number = result.scalar_one_or_none()
            seq = int(last_number.split("-")[-1]) + 1 if last_number else 1
            return f"{prefix}-{year}-{seq:06d}"
        except Exception as e:
            raise ARRepositoryError(f"Failed to generate invoice number: {e}") from e

    # ========================================================================
    # STATISTICS & AUDIT
    # ========================================================================

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        session = await self._get_session()
        try:
            stmt_total = select(
                func.count().label("total_invoices"),
                func.sum(ARInvoiceTable.total_amount).label("total_amount"),
                func.sum(ARInvoiceTable.total_amount - ARInvoiceTable.paid_amount).label("total_outstanding"),
                func.sum(ARInvoiceTable.paid_amount).label("total_paid"),
            ).where(
                ARInvoiceTable.legal_entity_id == legal_entity_id,
                ARInvoiceTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt_total)
            row = result.first()
            total_invoices = row.total_invoices or 0
            total_amount = row.total_amount or 0
            total_outstanding = row.total_outstanding or 0
            total_paid = row.total_paid or 0

            status_stmt = select(ARInvoiceTable.status, func.count()).where(
                ARInvoiceTable.legal_entity_id == legal_entity_id,
                ARInvoiceTable.deleted_at.is_(None),
            ).group_by(ARInvoiceTable.status)
            status_result = await session.execute(status_stmt)
            status_breakdown = {row[0]: row[1] for row in status_result.all()}

            return {
                "total_invoices": total_invoices,
                "total_amount": float(total_amount),
                "total_paid": float(total_paid),
                "total_outstanding": float(total_outstanding),
                "status_breakdown": status_breakdown,
            }
        except Exception as e:
            raise ARRepositoryError(f"Failed to get statistics: {e}") from e

    async def get_audit_log(self, invoice_id: UUID | None = None, limit: int = 100) -> list[dict[str, Any]]:
        logs = self._audit_log
        if invoice_id:
            logs = [l for l in logs if l.get("invoice_id") == str(invoice_id)]
        return logs[-limit:]

    async def export_to_csv(self, legal_entity_id: UUID, from_date: date | None = None, to_date: date | None = None) -> str:
        if from_date is None:
            from_date = date(1900, 1, 1)
        if to_date is None:
            to_date = date.today()
        invoices = await self.find_by_date_range(from_date, to_date, legal_entity_id)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Invoice Number", "Customer ID", "Invoice Date", "Due Date",
            "Total Amount", "Paid Amount", "Outstanding", "Status", "Currency"
        ])
        for inv in invoices:
            writer.writerow([
                inv.invoice_number,
                str(inv.customer_id),
                inv.invoice_date.isoformat(),
                inv.due_date.isoformat(),
                str(inv.total_amount.amount),
                str(inv.paid_amount.amount),
                str(inv.total_amount.amount - inv.paid_amount.amount),
                inv.status.value if hasattr(inv.status, "value") else str(inv.status),
                inv.total_amount.currency
            ])
        return output.getvalue()

    async def import_from_csv(self, csv_content: str, legal_entity_id: UUID, created_by: UUID) -> int:
        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                invoice_date = date.fromisoformat(row.get("invoice_date", date.today().isoformat()))
                due_date = date.fromisoformat(row.get("due_date", (invoice_date + timedelta(days=30)).isoformat()))
                total_amount = Decimal(row.get("total_amount", "0"))
                customer_id = UUID(row.get("customer_id", str(UUID(int=0))))

                line = ARInvoiceLine(
                    id=UUID(int=0),
                    description=row.get("description", ""),
                    quantity=Decimal(row.get("quantity", "1")),
                    unit_price=Money(amount=total_amount, currency=row.get("currency", "IDR")),
                    tax_rate=Decimal(row.get("tax_rate", "0")),
                    discount_percent=Decimal(row.get("discount_percent", "0")),
                    account_code=row.get("account_code", "400000"),
                    total_amount=Money(amount=total_amount, currency=row.get("currency", "IDR")),
                )
                invoice = ARInvoiceAggregate(
                    id=UUID(int=0),
                    invoice_number=await self.get_next_invoice_number("INV"),
                    customer_id=customer_id,
                    invoice_date=invoice_date,
                    due_date=due_date,
                    lines=[line],
                    total_amount=Money(amount=total_amount, currency=row.get("currency", "IDR")),
                    paid_amount=Money(amount=Decimal(0), currency=row.get("currency", "IDR")),
                    tax_amount=Money(amount=Decimal(0), currency=row.get("currency", "IDR")),
                    discount_amount=Money(amount=Decimal(0), currency=row.get("currency", "IDR")),
                    description=row.get("description", ""),
                    status=ARInvoiceStatus.DRAFT,
                    legal_entity_id=legal_entity_id,
                    created_by=created_by,
                )
                await self.add(invoice)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to import row: {e}")
        return count

    async def health_check(self) -> dict[str, Any]:
        try:
            session = await self._get_session()
            await session.execute(select(1))
            return {"status": "healthy", "repository": "ARRepository"}
        except Exception as e:
            return {"status": "unhealthy", "repository": "ARRepository", "error": str(e)}

    # ========================================================================
    # MISSING METHODS (DIPERLUKAN OLEH KONTRAK ARRepositoryPort)
    # ========================================================================

    async def save_invoice(self, invoice: ARInvoiceAggregate) -> None:
        """
        Simpan invoice (add jika baru, update jika sudah ada).
        """
        existing = await self.get_by_id(invoice.id)
        if existing:
            await self.update(invoice)
        else:
            await self.add(invoice)

    async def find_invoice_by_id(self, invoice_id: UUID) -> ARInvoiceAggregate | None:
        """
        Cari invoice berdasarkan ID (alias untuk get_by_id).
        """
        return await self.get_by_id(invoice_id)


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS
# ============================================================================

SQLAlchemyARRepositoryImpl = SQLAlchemyARRepository

__all__ = [
    "ARInvoiceNotFoundError",
    "ARRepositoryError",
    "DuplicateInvoiceNumberError",
    "InvalidStatusTransitionError",
    "OptimisticLockError",
    "SQLAlchemyARRepository",
    "SQLAlchemyARRepositoryImpl",
]