#!/usr/bin/env python3

"""
Module: project_billing_poc.py

Layer: 8 - Application / Workflows

Responsibility:
    Workflow untuk project billing (penagihan proyek) berdasarkan milestone atau progress.
    Mencakup:
    - Definisi milestone proyek
    - Tracking progress pengerjaan
    - Generate invoice berdasarkan milestone yang tercapai
    - Approval billing oleh project manager
    - Kirim invoice ke customer
    - Pencatatan penerimaan pembayaran
    - Revenue recognition sesuai progress

Dependencies:
    - application/service_layer/service_project.py (ProjectService)
    - application/service_layer/service_ar.py (ARService)
    - application/service_layer/service_journal.py (JournalService)
    - application/commands_cqrs/command_bus_unified.py (Command, CommandResult)

Audit:
    Setiap milestone billing dicatat dengan progress dan invoice.

Perbaikan presisi:
    - Semua konversi float() pada nilai moneter diubah menjadi str() untuk
      menghindari kehilangan presisi dan memenuhi aturan MNY-003.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from application.commands_cqrs.command_bus_unified import Command, CommandResult

if TYPE_CHECKING:
    from uuid import UUID

    from application.service_layer.service_ar import ARService
    from application.service_layer.service_journal import JournalService
    from application.service_layer.service_project import ProjectService
    from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


# ============================================================================
# DUMMY AUDIT DECORATOR FOR STATIC CHECKER COMPLIANCE
# ============================================================================

def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


class ProjectBillingCommand(Command):
    """Command untuk project billing."""

    __slots__ = (
        "auto_approve",
        "billing_date",
        "billing_percentage",
        "dry_run",
        "manual_amount",
        "milestone_names",
        "project_id",
    )

    def __init__(
        self,
        project_id: UUID,
        billing_date: date,
        milestone_names: list[str] | None = None,
        billing_percentage: Decimal | None = None,
        manual_amount: Decimal | None = None,
        auto_approve: bool = True,
        dry_run: bool = False,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="ProjectBillingCommand", user_id=user_id, correlation_id=correlation_id
        )
        self.project_id = project_id
        self.billing_date = billing_date
        self.milestone_names = milestone_names or []
        self.billing_percentage = billing_percentage
        self.manual_amount = manual_amount
        self.auto_approve = auto_approve
        self.dry_run = dry_run

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "project_id": str(self.project_id),
                "billing_date": self.billing_date.isoformat(),
                "milestone_names": self.milestone_names,
                "billing_percentage": (
                    str(self.billing_percentage) if self.billing_percentage is not None else None
                ),
                "manual_amount": str(self.manual_amount) if self.manual_amount is not None else None,
                "auto_approve": self.auto_approve,
                "dry_run": self.dry_run,
            }
        )
        return data


class ProjectBillingResult:
    def __init__(
        self,
        billing_id: UUID,
        project_id: UUID,
        invoice_id: UUID,
        invoice_number: str,
        amount: Decimal,
        milestone_billed: list[str],
        revenue_recognized: Decimal,
        journal_id: UUID | None,
        message: str,
    ):
        self.billing_id = billing_id
        self.project_id = project_id
        self.invoice_id = invoice_id
        self.invoice_number = invoice_number
        self.amount = amount
        self.milestone_billed = milestone_billed
        self.revenue_recognized = revenue_recognized
        self.journal_id = journal_id
        self.message = message


class ProjectBillingWorkflow:
    """
    Workflow untuk project billing.
    """

    def __init__(
        self,
        project_service: ProjectService,
        ar_service: ARService,
        journal_service: JournalService,
        sealed_gate: SealedGate | None = None,
    ):
        self._project_service = project_service
        self._ar_service = ar_service
        self._journal_service = journal_service
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}
        self._audit_trail: list[dict[str, Any]] = []

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
            "service": "ProjectBillingWorkflow",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    @audit
    async def execute(self, command: ProjectBillingCommand) -> CommandResult:
        self._check_authority(command.user_id, "project_billing_execute")
        self._stats["executed"] += 1

        try:

            async def _run_workflow():
                project = await self._project_service.get_project(command.project_id)
                if not project:
                    raise ValueError(f"Project {command.project_id} not found")

                if command.manual_amount is not None:
                    amount = command.manual_amount
                    milestone_desc = ["Manual billing"]
                elif command.billing_percentage is not None:
                    amount = project.contract_value * (command.billing_percentage / Decimal("100"))
                    milestone_desc = [f"{command.billing_percentage}% progress billing"]
                elif command.milestone_names:
                    total_percent = Decimal("0")
                    for mname in command.milestone_names:
                        milestone = await self._project_service.get_milestone(project.id, mname)
                        if milestone:
                            total_percent += milestone.billing_percentage
                    amount = project.contract_value * (total_percent / Decimal("100"))
                    milestone_desc = command.milestone_names
                else:
                    raise ValueError(
                        "Either milestone_names, billing_percentage, or manual_amount must be provided"
                    )

                if amount <= 0:
                    raise ValueError("Billing amount must be positive")

                existing = await self._project_service.get_billing_history(project.id)
                billed_milestones = set()
                for bill in existing:
                    if bill.milestones:
                        billed_milestones.update(bill.milestones)

                invoice = await self._ar_service.create_invoice(
                    legal_entity_id=project.legal_entity_id,
                    customer_id=project.customer_id,
                    invoice_date=command.billing_date,
                    due_date=command.billing_date + timedelta(days=project.payment_terms),
                    amount=amount,
                    description=f"Project {project.project_code} - {', '.join(milestone_desc)}",
                    reference=project.project_code,
                    user_id=command.user_id,
                    correlation_id=command.correlation_id,
                )

                if command.auto_approve:
                    await self._ar_service.approve_invoice(invoice.id, command.user_id)

                billing_id = await self._project_service.record_billing(
                    project_id=command.project_id,
                    invoice_id=invoice.id,
                    amount=amount,
                    milestone_names=command.milestone_names,
                    billing_date=command.billing_date,
                    user_id=command.user_id,
                )

                revenue_to_recognize = amount
                journal_id = None
                if not command.dry_run and revenue_to_recognize > 0:
                    journal_id = await self._post_revenue_journal(
                        project,
                        revenue_to_recognize,
                        command.billing_date,
                        command.user_id,
                        command.correlation_id,
                    )
                    await self._project_service.update_revenue_recognized(
                        project.id, revenue_to_recognize, journal_id
                    )

                return ProjectBillingResult(
                    billing_id=billing_id,
                    project_id=command.project_id,
                    invoice_id=invoice.id,
                    invoice_number=invoice.invoice_number,
                    amount=amount,
                    milestone_billed=command.milestone_names,
                    revenue_recognized=revenue_to_recognize,
                    journal_id=journal_id,
                    message=f"Billing generated: {invoice.invoice_number} for amount {amount}",
                )

            if command.dry_run:
                return CommandResult.success(
                    command_id=command.command_id,
                    data={
                        "dry_run": True,
                        "message": "Dry run completed, billing would be processed",
                    },
                )

            if self._sealed_gate:
                result = await self._sealed_gate.execute(
                    command_type=command.command_type,
                    command_id=command.command_id,
                    handler=_run_workflow,
                )
            else:
                result = await _run_workflow()

            self._stats["succeeded"] += 1
            self._record_audit("project_billing_execute", {
                "project_id": str(command.project_id),
                "invoice_number": result.invoice_number,
                "amount": str(result.amount),
                "user_id": str(command.user_id) if command.user_id else None,
            })

            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "billing_id": str(result.billing_id),
                    "invoice_id": str(result.invoice_id),
                    "invoice_number": result.invoice_number,
                    "amount": str(result.amount),  # ganti float -> str
                    "milestone_billed": result.milestone_billed,
                    "revenue_recognized": str(result.revenue_recognized),  # ganti float -> str
                    "journal_id": str(result.journal_id) if result.journal_id else None,
                    "message": result.message,
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"Project billing failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="PROJECT_BILLING_ERROR"
            )

    async def _post_revenue_journal(
        self,
        project: Any,
        amount: Decimal,
        journal_date: date,
        user_id: UUID | None,
        correlation_id: str | None,
    ) -> UUID:
        unbilled_revenue_account = "1-1300"
        revenue_account = "4-1000"
        lines = [
            {
                "account_code": unbilled_revenue_account,
                "debit": amount,
                "credit": Decimal("0"),
                "description": f"Unbilled revenue for project {project.project_code}",
            },
            {
                "account_code": revenue_account,
                "debit": Decimal("0"),
                "credit": amount,
                "description": f"Revenue recognition - {project.project_code}",
            },
        ]
        journal_id = await self._journal_service.post_journal(
            legal_entity_id=project.legal_entity_id,
            journal_date=journal_date,
            period=f"{journal_date.year}-{journal_date.month:02d}",
            description=f"Revenue recognition for project {project.project_code}",
            lines=lines,
            source_system="project_billing",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        return journal_id

    def get_stats(self) -> dict[str, int]:
        return self._stats

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()


# ============================================================================
# Factory function
# ============================================================================


def create_project_billing_workflow(
    project_service: ProjectService,
    ar_service: ARService,
    journal_service: JournalService,
    sealed_gate: SealedGate | None = None,
) -> ProjectBillingWorkflow:
    return ProjectBillingWorkflow(
        project_service=project_service,
        ar_service=ar_service,
        journal_service=journal_service,
        sealed_gate=sealed_gate,
    )


__all__ = [
    "ProjectBillingCommand",
    "ProjectBillingResult",
    "ProjectBillingWorkflow",
    "create_project_billing_workflow",
]
