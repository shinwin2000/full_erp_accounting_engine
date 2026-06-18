#!/usr/bin/env python3

"""
Module: aml_screening_transaction.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk screening transaksi terhadap aturan Anti Money Laundering (AML).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from application.commands_cqrs.command_bus_unified import Command, CommandResult
from application.service_layer.service_audit import AuditService
from application.service_layer.service_iam import IAMService
from kernel.sealed_gate import SealedGate
from ports.primary.aml_repository_port import AMLRepositoryPort

logger = logging.getLogger(__name__)


class AMLStatus(Enum):
    PASS = "PASS"
    FLAG = "FLAG"
    BLOCK = "BLOCK"
    REVIEW = "REVIEW"


class SuspicionReason(Enum):
    EXCEEDS_THRESHOLD = "exceeds_threshold"
    SANCTION_LIST_HIT = "sanction_list_hit"
    STRUCTURING = "structuring"
    RAPID_MOVEMENT = "rapid_movement"
    UNUSUAL_PATTERN = "unusual_pattern"
    PEP_RELATED = "pep_related"


class AMLScreeningCommand(Command):
    """Command untuk screening AML transaksi."""

    __slots__ = (
        "additional_data",
        "amount",
        "currency",
        "from_party_id",
        "from_party_type",
        "reference",
        "to_party_id",
        "to_party_type",
        "transaction_date",
        "transaction_id",
        "transaction_type",
    )

    def __init__(
        self,
        transaction_id: UUID,
        transaction_type: str,
        amount: Decimal,
        currency: str,
        from_party_id: UUID,
        from_party_type: str,
        to_party_id: UUID,
        to_party_type: str,
        transaction_date: date,
        reference: str | None = None,
        additional_data: dict[str, Any] | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="AMLScreeningCommand", user_id=user_id, correlation_id=correlation_id
        )
        self.transaction_id = transaction_id
        self.transaction_type = transaction_type
        self.amount = amount
        self.currency = currency
        self.from_party_id = from_party_id
        self.from_party_type = from_party_type
        self.to_party_id = to_party_id
        self.to_party_type = to_party_type
        self.transaction_date = transaction_date
        self.reference = reference
        self.additional_data = additional_data or {}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "transaction_id": str(self.transaction_id),
                "transaction_type": self.transaction_type,
                "amount": float(self.amount),
                "currency": self.currency,
                "from_party_id": str(self.from_party_id),
                "from_party_type": self.from_party_type,
                "to_party_id": str(self.to_party_id),
                "to_party_type": self.to_party_type,
                "transaction_date": self.transaction_date.isoformat(),
                "reference": self.reference,
            }
        )
        return data


class SuspiciousTransactionReport:
    def __init__(
        self,
        report_id: UUID,
        transaction_id: UUID,
        suspicion_reasons: list[SuspicionReason],
        status: AMLStatus,
        amount: Decimal,
        parties: dict[str, Any],
        created_at: datetime,
        reviewed_by: UUID | None = None,
        reviewed_at: datetime | None = None,
    ):
        self.report_id = report_id
        self.transaction_id = transaction_id
        self.suspicion_reasons = suspicion_reasons
        self.status = status
        self.amount = amount
        self.parties = parties
        self.created_at = created_at
        self.reviewed_by = reviewed_by
        self.reviewed_at = reviewed_at


class AMLScreeningResult:
    def __init__(
        self,
        status: AMLStatus,
        suspicion_reasons: list[SuspicionReason],
        str_id: UUID | None = None,
        message: str = "",
    ):
        self.status = status
        self.suspicion_reasons = suspicion_reasons
        self.str_id = str_id
        self.message = message


class AMLScreeningUseCase:
    """Use case untuk screening AML transaksi."""

    DEFAULT_THRESHOLD_IDR = Decimal("100000000")  # 100 juta IDR
    DEFAULT_THRESHOLD_USD = Decimal("10000")  # 10k USD
    STRUCTURING_WINDOW_DAYS = 7
    STRUCTURING_LIMIT = 3

    def __init__(
        self,
        aml_repo: AMLRepositoryPort,
        audit_service: AuditService,
        iam_service: IAMService,
        sealed_gate: SealedGate | None = None,
    ):
        self._aml_repo = aml_repo
        self._audit_service = audit_service
        self._iam_service = iam_service
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: AMLScreeningCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            threshold = self._get_threshold(command.currency)
            suspicion_reasons = []

            if command.amount >= threshold:
                suspicion_reasons.append(SuspicionReason.EXCEEDS_THRESHOLD)

            from_party_blacklisted = await self._check_sanction_list(
                command.from_party_id, command.from_party_type
            )
            to_party_blacklisted = await self._check_sanction_list(
                command.to_party_id, command.to_party_type
            )
            if from_party_blacklisted or to_party_blacklisted:
                suspicion_reasons.append(SuspicionReason.SANCTION_LIST_HIT)

            if await self._check_structuring(command):
                suspicion_reasons.append(SuspicionReason.STRUCTURING)

            if await self._check_rapid_movement(command):
                suspicion_reasons.append(SuspicionReason.RAPID_MOVEMENT)

            if await self._check_pep(command):
                suspicion_reasons.append(SuspicionReason.PEP_RELATED)

            if suspicion_reasons:
                if command.amount >= threshold * Decimal("5"):
                    status = AMLStatus.BLOCK
                else:
                    status = AMLStatus.FLAG
                message = f"Transaction flagged for AML review. Reasons: {[r.value for r in suspicion_reasons]}"
            else:
                status = AMLStatus.PASS
                message = "Transaction passed AML screening"

            str_id = None
            if status in (AMLStatus.FLAG, AMLStatus.BLOCK):
                str_id = await self._create_suspicious_transaction_report(
                    command, suspicion_reasons, status
                )
                await self._notify_compliance_officer(str_id, command, status, suspicion_reasons)

            result = AMLScreeningResult(
                status=status, suspicion_reasons=suspicion_reasons, str_id=str_id, message=message
            )

            await self._audit_service.record_audit(
                action="AML_SCREENING",
                target_id=command.transaction_id,
                details={
                    "status": status.value,
                    "reasons": [r.value for r in suspicion_reasons],
                    "str_id": str(str_id) if str_id else None,
                },
                user_id=command.user_id,
                correlation_id=command.correlation_id,
            )

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "status": result.status.value,
                    "suspicion_reasons": [r.value for r in result.suspicion_reasons],
                    "str_id": str(result.str_id) if result.str_id else None,
                    "message": result.message,
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"AML screening failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="AML_SCREENING_ERROR"
            )

    def _get_threshold(self, currency: str) -> Decimal:
        if currency.upper() == "IDR":
            return self.DEFAULT_THRESHOLD_IDR
        elif currency.upper() == "USD":
            return self.DEFAULT_THRESHOLD_USD
        else:
            return Decimal("50000")

    async def _check_sanction_list(self, party_id: UUID, party_type: str) -> bool:
        return False

    async def _check_structuring(self, command: AMLScreeningCommand) -> bool:
        window_start = command.transaction_date - timedelta(days=self.STRUCTURING_WINDOW_DAYS)
        transactions = await self._aml_repo.get_transactions_by_party(
            party_id=command.from_party_id,
            from_date=window_start,
            to_date=command.transaction_date,
            transaction_type=command.transaction_type,
            exclude_transaction_id=command.transaction_id,
        )
        total_amount = sum(t.amount for t in transactions) + command.amount
        if (
            total_amount >= self._get_threshold(command.currency)
            and len(transactions) >= self.STRUCTURING_LIMIT
        ):
            all_below = all(t.amount < self._get_threshold(command.currency) for t in transactions)
            if all_below:
                return True
        return False

    async def _check_rapid_movement(self, command: AMLScreeningCommand) -> bool:
        inbound_start = command.transaction_date - timedelta(days=3)
        inbound = await self._aml_repo.get_inbound_transactions(
            party_id=command.from_party_id,
            from_date=inbound_start,
            to_date=command.transaction_date,
        )
        if not inbound:
            return False
        total_inbound = sum(t.amount for t in inbound)
        if command.amount >= total_inbound * Decimal("0.8"):
            return True
        return False

    async def _check_pep(self, command: AMLScreeningCommand) -> bool:
        pep_check_from = await self._iam_service.is_pep(command.from_party_id)
        pep_check_to = await self._iam_service.is_pep(command.to_party_id)
        return pep_check_from or pep_check_to

    async def _create_suspicious_transaction_report(
        self, command: AMLScreeningCommand, reasons: list[SuspicionReason], status: AMLStatus
    ) -> UUID:
        report_id = uuid4()
        report = SuspiciousTransactionReport(
            report_id=report_id,
            transaction_id=command.transaction_id,
            suspicion_reasons=reasons,
            status=status,
            amount=command.amount,
            parties={
                "from": {"id": str(command.from_party_id), "type": command.from_party_type},
                "to": {"id": str(command.to_party_id), "type": command.to_party_type},
            },
            created_at=datetime.utcnow(),
        )
        await self._aml_repo.save_str(report)
        logger.warning(f"STR {report_id} created for transaction {command.transaction_id}")
        return report_id

    async def _notify_compliance_officer(
        self,
        str_id: UUID,
        command: AMLScreeningCommand,
        status: AMLStatus,
        reasons: list[SuspicionReason],
    ) -> None:
        logger.info(
            f"NOTIFICATION: STR {str_id} for transaction {command.transaction_id}, status={status.value}, reasons={[r.value for r in reasons]}"
        )

    def get_stats(self) -> dict[str, int]:
        return self._stats


# ============================================================================
# Handler dengan dependency injection (tanpa impor container)
# ============================================================================


async def aml_screening_handler(command: Command, use_case: AMLScreeningUseCase) -> CommandResult:
    if not isinstance(command, AMLScreeningCommand):
        raise TypeError(f"Expected AMLScreeningCommand, got {type(command)}")
    return await use_case.execute(command)


__all__ = [
    "AMLScreeningCommand",
    "AMLScreeningResult",
    "AMLScreeningUseCase",
    "AMLStatus",
    "SuspicionReason",
    "SuspiciousTransactionReport",
    "aml_screening_handler",
]
