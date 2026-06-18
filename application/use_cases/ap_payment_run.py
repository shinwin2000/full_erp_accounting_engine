#!/usr/bin/env python3

"""
Module: ap_payment_run.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk payment run (pembayaran massal) ke vendor.
    Mencakup identifikasi invoice, perhitungan diskon, generate payment proposal,
    eksekusi pembayaran, posting jurnal, dan generate file bank.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from application.commands_cqrs.command_bus_unified import Command, CommandResult
from application.service_layer.service_ap import APService
from application.service_layer.service_bank_cash import BankCashService
from application.service_layer.service_journal import JournalService
from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


class APPaymentRunCommand(Command):
    """Command untuk payment run AP."""

    __slots__ = (
        "auto_approve",
        "bank_account_id",
        "dry_run",
        "invoice_ids",
        "legal_entity_id",
        "payment_date",
        "payment_method",
        "vendor_id",
    )

    def __init__(
        self,
        legal_entity_id: UUID,
        payment_date: date,
        vendor_id: UUID | None = None,
        invoice_ids: list[UUID] | None = None,
        bank_account_id: UUID | None = None,
        payment_method: str = "BANK_TRANSFER",
        auto_approve: bool = True,
        dry_run: bool = False,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="APPaymentRunCommand", user_id=user_id, correlation_id=correlation_id
        )
        self.legal_entity_id = legal_entity_id
        self.payment_date = payment_date
        self.vendor_id = vendor_id
        self.invoice_ids = invoice_ids or []
        self.bank_account_id = bank_account_id
        self.payment_method = payment_method
        self.auto_approve = auto_approve
        self.dry_run = dry_run

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "legal_entity_id": str(self.legal_entity_id),
                "payment_date": self.payment_date.isoformat(),
                "vendor_id": str(self.vendor_id) if self.vendor_id else None,
                "invoice_ids": [str(iid) for iid in self.invoice_ids],
                "bank_account_id": str(self.bank_account_id) if self.bank_account_id else None,
                "payment_method": self.payment_method,
                "auto_approve": self.auto_approve,
                "dry_run": self.dry_run,
            }
        )
        return data


class APPaymentRunResult:
    def __init__(
        self,
        invoice_count: int,
        total_amount: Decimal,
        discount_applied: Decimal,
        net_payment: Decimal,
        payment_ids: list[UUID],
        journal_id: UUID | None,
        bank_file_path: str | None,
        errors: list[str],
    ):
        self.invoice_count = invoice_count
        self.total_amount = total_amount
        self.discount_applied = discount_applied
        self.net_payment = net_payment
        self.payment_ids = payment_ids
        self.journal_id = journal_id
        self.bank_file_path = bank_file_path
        self.errors = errors


class APPaymentRunUseCase:
    """
    Use case untuk payment run AP.
    """

    def __init__(
        self,
        ap_service: APService,
        bank_cash_service: BankCashService,
        journal_service: JournalService,
        sealed_gate: SealedGate | None = None,
    ):
        self._ap_service = ap_service
        self._bank_service = bank_cash_service
        self._journal_service = journal_service
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: APPaymentRunCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            # 1. Identifikasi invoice yang akan dibayar
            if command.invoice_ids:
                invoices = []
                for inv_id in command.invoice_ids:
                    inv = await self._ap_service.get_invoice(inv_id)
                    if inv and inv.remaining_amount > 0:
                        invoices.append(inv)
            else:
                invoices = await self._ap_service.list_invoices_for_payment(
                    legal_entity_id=command.legal_entity_id,
                    due_date_cutoff=command.payment_date,
                    vendor_id=command.vendor_id,
                )

            if not invoices:
                raise ValueError("No eligible invoices found for payment")

            # 2. Hitung total, diskon jika ada
            total_amount = sum(inv.remaining_amount for inv in invoices)
            discount_applied = Decimal("0")
            net_payment = total_amount
            if command.payment_method == "CASH_WITH_DISCOUNT":
                for inv in invoices:
                    if inv.due_date > command.payment_date:
                        disc = inv.remaining_amount * Decimal("0.02")
                        discount_applied += disc
                net_payment = total_amount - discount_applied

            # 3. Jika dry run, hanya kembalikan proposal
            if command.dry_run:
                return CommandResult.success(
                    command_id=command.command_id,
                    data={
                        "dry_run": True,
                        "invoice_count": len(invoices),
                        "total_amount": float(total_amount),
                        "discount_applied": float(discount_applied),
                        "net_payment": float(net_payment),
                        "invoice_list": [
                            {
                                "id": str(inv.id),
                                "number": inv.invoice_number,
                                "amount": float(inv.remaining_amount),
                            }
                            for inv in invoices
                        ],
                    },
                )

            # 4. Generate payment run via AP service
            payment_run = await self._ap_service.generate_payment_run(
                legal_entity_id=command.legal_entity_id,
                payment_date=command.payment_date,
                vendor_id=command.vendor_id,
                invoice_ids=[inv.id for inv in invoices],
                bank_account_id=command.bank_account_id,
                payment_method=command.payment_method,
                user_id=command.user_id,
            )

            # 5. Execute payments
            payment_ids = []
            for payment in payment_run.payments:
                if command.auto_approve:
                    await self._ap_service.approve_payment(payment.id, command.user_id)
                executed_payment = await self._ap_service.execute_payment(
                    payment.id, command.user_id
                )
                payment_ids.append(executed_payment.id)

                await self._bank_service.record_withdrawal(
                    legal_entity_id=command.legal_entity_id,
                    amount=executed_payment.amount,
                    withdrawal_date=command.payment_date,
                    reference=executed_payment.payment_number,
                    bank_account_id=command.bank_account_id,
                    user_id=command.user_id,
                )

            # 6. Post journal untuk pembayaran
            journal_id = None
            if net_payment > 0:
                journal_id = await self._post_payment_journal(
                    command.legal_entity_id,
                    total_amount,
                    discount_applied,
                    net_payment,
                    command.payment_date,
                    command.user_id,
                    command.correlation_id,
                )

            # 7. Generate bank file jika diperlukan
            bank_file_path = None
            if command.payment_method == "BANK_TRANSFER":
                bank_file_path = await self._generate_bank_file(
                    payment_ids, command.payment_date, command.legal_entity_id
                )

            result = APPaymentRunResult(
                invoice_count=len(invoices),
                total_amount=total_amount,
                discount_applied=discount_applied,
                net_payment=net_payment,
                payment_ids=payment_ids,
                journal_id=journal_id,
                bank_file_path=bank_file_path,
                errors=[],
            )

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "invoice_count": result.invoice_count,
                    "total_amount": float(result.total_amount),
                    "discount_applied": float(result.discount_applied),
                    "net_payment": float(result.net_payment),
                    "payment_ids": [str(pid) for pid in result.payment_ids],
                    "journal_id": str(result.journal_id) if result.journal_id else None,
                    "bank_file_path": result.bank_file_path,
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"AP payment run failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="AP_PAYMENT_RUN_ERROR"
            )

    async def _post_payment_journal(
        self,
        legal_entity_id: UUID,
        total_amount: Decimal,
        discount_applied: Decimal,
        net_payment: Decimal,
        payment_date: date,
        user_id: UUID,
        correlation_id: str | None,
    ) -> UUID:
        ap_payable_account = "2-2000"
        bank_account = "1-1100"
        discount_account = "5-5500"

        lines = [
            {
                "account_code": ap_payable_account,
                "debit": total_amount,
                "credit": Decimal("0"),
                "description": "Payment to vendor",
            },
            {
                "account_code": bank_account,
                "debit": Decimal("0"),
                "credit": net_payment,
                "description": "Bank withdrawal",
            },
        ]
        if discount_applied > 0:
            lines.append(
                {
                    "account_code": discount_account,
                    "debit": discount_applied,
                    "credit": Decimal("0"),
                    "description": "Discount taken",
                }
            )

        journal_id = await self._journal_service.post_journal(
            legal_entity_id=legal_entity_id,
            journal_date=payment_date,
            period=f"{payment_date.year}-{payment_date.month:02d}",
            description=f"AP payment run for {payment_date}",
            lines=lines,
            source_system="ap_payment",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        return journal_id

    async def _generate_bank_file(
        self, payment_ids: list[UUID], payment_date: date, legal_entity_id: UUID
    ) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Payment ID", "Vendor", "Amount", "Payment Date", "Account Number"])
        for pid in payment_ids:
            payment = await self._ap_service.get_payment(pid)
            writer.writerow(
                [
                    str(payment.id),
                    payment.vendor_name,
                    float(payment.amount),
                    payment_date.isoformat(),
                    payment.bank_account_number or "",
                ]
            )
        file_path = (
            f"/tmp/ap_payment_{legal_entity_id}_{payment_date.year}{payment_date.month:02d}.csv"
        )
        with open(file_path, "w") as f:
            f.write(output.getvalue())
        return file_path

    def get_stats(self) -> dict[str, int]:
        return self._stats


async def ap_payment_run_handler(command: Command, use_case: APPaymentRunUseCase) -> CommandResult:
    if not isinstance(command, APPaymentRunCommand):
        raise TypeError(f"Expected APPaymentRunCommand, got {type(command)}")
    return await use_case.execute(command)


# ============================================================================
# SIMPLE CLASS FOR E2E TESTS (synchronous)
# ============================================================================


class ApPaymentRun:
    """
    Simple synchronous version of payment run for E2E tests.
    Implements execute(invoices, bank_account) returning an object with
    total_paid and payment_reference.
    """

    def execute(self, invoices: list, bank_account: str) -> object:
        """
        Execute a payment run for the given invoices.
        Returns a simple object with attributes total_paid (Decimal) and payment_reference (str).
        """
        from types import SimpleNamespace

        total_paid = Decimal("0")
        for inv in invoices:
            # Each invoice is an instance of ApInvoice (from domain.subledger_ap.invoice_entity)
            # It has attributes 'amount' and 'tax' (or total amount)
            amt = getattr(inv, "amount", Decimal("0"))
            tax = getattr(inv, "tax", Decimal("0"))
            total_paid += amt + tax

        result = SimpleNamespace()
        result.total_paid = total_paid
        result.payment_reference = f"PAY-{bank_account}-{len(invoices)}"
        return result


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "APPaymentRunCommand",
    "APPaymentRunResult",
    "APPaymentRunUseCase",
    "ApPaymentRun",
    "ap_payment_run_handler",
]
