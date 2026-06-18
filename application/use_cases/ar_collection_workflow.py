#!/usr/bin/env python3

"""
Module: ar_collection_workflow.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk collection piutang (AR collection). Mencakup identifikasi invoice
    overdue, pembuatan collection plan, pencatatan pembayaran, diskon, reminder,
    dunning process, write-off, dan integrasi dengan cash receipt.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from application.commands_cqrs.command_bus_unified import Command, CommandResult
from application.service_layer.service_ar import ARService
from application.service_layer.service_bank_cash import BankCashService
from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


class ARCollectionWorkflowCommand(Command):
    """Command untuk collection piutang."""

    __slots__ = (
        "action",
        "amount",
        "as_of_date",
        "customer_id",
        "discount_applied",
        "invoice_ids",
        "legal_entity_id",
        "payment_date",
        "send_reminder",
        "write_off_reason",
    )

    def __init__(
        self,
        legal_entity_id: UUID,
        as_of_date: date,
        customer_id: UUID | None = None,
        action: str = "IDENTIFY_OVERDUE",  # IDENTIFY_OVERDUE, RECORD_PAYMENT, SEND_REMINDER, WRITE_OFF
        payment_date: date | None = None,
        amount: Decimal | None = None,
        invoice_ids: list[UUID] | None = None,
        discount_applied: Decimal = Decimal("0"),
        write_off_reason: str | None = None,
        send_reminder: bool = False,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="ARCollectionWorkflowCommand",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        self.legal_entity_id = legal_entity_id
        self.as_of_date = as_of_date
        self.customer_id = customer_id
        self.action = action
        self.payment_date = payment_date
        self.amount = amount
        self.invoice_ids = invoice_ids or []
        self.discount_applied = discount_applied
        self.write_off_reason = write_off_reason
        self.send_reminder = send_reminder

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "legal_entity_id": str(self.legal_entity_id),
                "as_of_date": self.as_of_date.isoformat(),
                "customer_id": str(self.customer_id) if self.customer_id else None,
                "action": self.action,
                "payment_date": self.payment_date.isoformat() if self.payment_date else None,
                "amount": float(self.amount) if self.amount else None,
                "invoice_ids": [str(iid) for iid in self.invoice_ids],
                "discount_applied": float(self.discount_applied),
                "write_off_reason": self.write_off_reason,
                "send_reminder": self.send_reminder,
            }
        )
        return data


class OverdueInvoice:
    def __init__(
        self,
        invoice_id: UUID,
        invoice_number: str,
        customer_id: UUID,
        customer_name: str,
        due_date: date,
        amount: Decimal,
        days_overdue: int,
        aging_bucket: str,
    ):
        self.invoice_id = invoice_id
        self.invoice_number = invoice_number
        self.customer_id = customer_id
        self.customer_name = customer_name
        self.due_date = due_date
        self.amount = amount
        self.days_overdue = days_overdue
        self.aging_bucket = aging_bucket


class CollectionWorkflowResult:
    def __init__(
        self,
        action_performed: str,
        overdue_invoices: list[OverdueInvoice],
        payments_recorded: int,
        total_amount_collected: Decimal,
        reminders_sent: int,
        write_offs: int,
        message: str,
    ):
        self.action_performed = action_performed
        self.overdue_invoices = overdue_invoices
        self.payments_recorded = payments_recorded
        self.total_amount_collected = total_amount_collected
        self.reminders_sent = reminders_sent
        self.write_offs = write_offs
        self.message = message


class ARCollectionWorkflowUseCase:
    """
    Use case untuk collection piutang.
    """

    def __init__(
        self,
        ar_service: ARService,
        bank_cash_service: BankCashService,
        sealed_gate: SealedGate | None = None,
    ):
        self._ar_service = ar_service
        self._bank_service = bank_cash_service
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: ARCollectionWorkflowCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            if command.action == "IDENTIFY_OVERDUE":
                result = await self._identify_overdue_invoices(command)
            elif command.action == "RECORD_PAYMENT":
                result = await self._record_payment(command)
            elif command.action == "SEND_REMINDER":
                result = await self._send_reminders(command)
            elif command.action == "WRITE_OFF":
                result = await self._write_off_invoices(command)
            else:
                raise ValueError(f"Unknown action: {command.action}")

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "action_performed": result.action_performed,
                    "overdue_invoices_count": len(result.overdue_invoices),
                    "payments_recorded": result.payments_recorded,
                    "total_amount_collected": float(result.total_amount_collected),
                    "reminders_sent": result.reminders_sent,
                    "write_offs": result.write_offs,
                    "message": result.message,
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"AR collection workflow failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="AR_COLLECTION_ERROR"
            )

    async def _identify_overdue_invoices(
        self, command: ARCollectionWorkflowCommand
    ) -> CollectionWorkflowResult:
        invoices = await self._ar_service.list_invoices(
            legal_entity_id=command.legal_entity_id,
            customer_id=command.customer_id,
            status="APPROVED",
            limit=10000,
        )

        overdue = []
        for inv in invoices:
            if inv.remaining_amount <= 0:
                continue
            days_overdue = (command.as_of_date - inv.due_date).days
            if days_overdue > 0:
                if days_overdue <= 30:
                    bucket = "1-30 days"
                elif days_overdue <= 60:
                    bucket = "31-60 days"
                elif days_overdue <= 90:
                    bucket = "61-90 days"
                else:
                    bucket = ">90 days"

                overdue.append(
                    OverdueInvoice(
                        invoice_id=inv.id,
                        invoice_number=inv.invoice_number,
                        customer_id=inv.customer_id,
                        customer_name=inv.customer_name,
                        due_date=inv.due_date,
                        amount=inv.remaining_amount,
                        days_overdue=days_overdue,
                        aging_bucket=bucket,
                    )
                )

        return CollectionWorkflowResult(
            action_performed="IDENTIFY_OVERDUE",
            overdue_invoices=overdue,
            payments_recorded=0,
            total_amount_collected=Decimal("0"),
            reminders_sent=0,
            write_offs=0,
            message=f"Found {len(overdue)} overdue invoices totaling {sum(o.amount for o in overdue)}",
        )

    async def _record_payment(
        self, command: ARCollectionWorkflowCommand
    ) -> CollectionWorkflowResult:
        if not command.amount or not command.payment_date:
            raise ValueError("Payment amount and date required")

        if not command.invoice_ids:
            overdue = await self._identify_overdue_invoices(command)
            if not overdue.overdue_invoices:
                raise ValueError("No overdue invoices found for payment allocation")
            command.invoice_ids = [overdue.overdue_invoices[0].invoice_id]

        payment = await self._ar_service.record_payment(
            legal_entity_id=command.legal_entity_id,
            customer_id=command.customer_id,
            payment_date=command.payment_date,
            amount=command.amount,
            invoice_ids=command.invoice_ids,
            discount_applied=command.discount_applied,
            user_id=command.user_id,
            correlation_id=command.correlation_id,
        )

        if payment:
            await self._bank_service.record_deposit(
                legal_entity_id=command.legal_entity_id,
                amount=command.amount,
                deposit_date=command.payment_date,
                reference=f"AR Payment {payment.payment_number}",
                user_id=command.user_id,
            )

        return CollectionWorkflowResult(
            action_performed="RECORD_PAYMENT",
            overdue_invoices=[],
            payments_recorded=1,
            total_amount_collected=command.amount,
            reminders_sent=0,
            write_offs=0,
            message=f"Payment of {command.amount} recorded and applied to {len(command.invoice_ids)} invoices",
        )

    async def _send_reminders(
        self, command: ARCollectionWorkflowCommand
    ) -> CollectionWorkflowResult:
        overdue = await self._identify_overdue_invoices(command)
        if not overdue.overdue_invoices:
            return CollectionWorkflowResult(
                action_performed="SEND_REMINDER",
                overdue_invoices=[],
                payments_recorded=0,
                total_amount_collected=Decimal("0"),
                reminders_sent=0,
                write_offs=0,
                message="No overdue invoices to remind",
            )

        reminders_sent = 0
        for inv in overdue.overdue_invoices:
            if command.send_reminder:
                logger.info(
                    f"Sending reminder to {inv.customer_name} for invoice {inv.invoice_number}"
                )
                reminders_sent += 1

        return CollectionWorkflowResult(
            action_performed="SEND_REMINDER",
            overdue_invoices=overdue.overdue_invoices,
            payments_recorded=0,
            total_amount_collected=Decimal("0"),
            reminders_sent=reminders_sent,
            write_offs=0,
            message=f"Sent {reminders_sent} reminders",
        )

    async def _write_off_invoices(
        self, command: ARCollectionWorkflowCommand
    ) -> CollectionWorkflowResult:
        if not command.write_off_reason:
            raise ValueError("Write off reason required")

        if not command.invoice_ids:
            overdue = await self._identify_overdue_invoices(command)
            long_overdue = [inv for inv in overdue.overdue_invoices if inv.days_overdue >= 180]
            command.invoice_ids = [inv.invoice_id for inv in long_overdue]

        write_offs = 0
        total_amount = Decimal("0")
        for inv_id in command.invoice_ids:
            await self._ar_service.write_off_invoice(
                invoice_id=inv_id,
                reason=command.write_off_reason,
                user_id=command.user_id,
                correlation_id=command.correlation_id,
            )
            write_offs += 1
            inv = await self._ar_service.get_invoice(inv_id)
            total_amount += inv.remaining_amount

        return CollectionWorkflowResult(
            action_performed="WRITE_OFF",
            overdue_invoices=[],
            payments_recorded=0,
            total_amount_collected=Decimal("0"),
            reminders_sent=0,
            write_offs=write_offs,
            message=f"Written off {write_offs} invoices totaling {total_amount}",
        )

    def get_stats(self) -> dict[str, int]:
        return self._stats


# ============================================================================
# Handler dengan dependency injection
# ============================================================================
async def ar_collection_workflow_handler(
    command: Command, use_case: ARCollectionWorkflowUseCase
) -> CommandResult:
    if not isinstance(command, ARCollectionWorkflowCommand):
        raise TypeError(f"Expected ARCollectionWorkflowCommand, got {type(command)}")
    return await use_case.execute(command)


# Buat alias eksplisit agar kompatibel dengan penamaan di lapisan FastAPI Router
ARCollectionWorkflow = ARCollectionWorkflowUseCase
ArCollectionWorkflow = ARCollectionWorkflowUseCase  # Added for test (camelCase Ar)

__all__ = [
    "ARCollectionWorkflow",
    "ARCollectionWorkflowCommand",
    "ARCollectionWorkflowUseCase",
    "ArCollectionWorkflow",
    "CollectionWorkflowResult",
    "OverdueInvoice",
    "ar_collection_workflow_handler",
]
