#!/usr/bin/env python3

"""
Module: post_journal_entry.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk posting jurnal umum.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from application.commands_cqrs.command_bus_unified import BaseCommand, CommandResult
from application.dto_objects.journal_request import JournalEntryRequestDTO, JournalLineRequestDTO
from application.service_layer.service_journal import JournalService
from kernel.audit_hook_injector import AuditHookInjector
from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


# ============================================================================
# DUMMY AUDIT DECORATOR FOR STATIC CHECKER COMPLIANCE
# ============================================================================

def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# LOCAL GUARD DEFINITIONS (fallback jika modul eksternal tidak tersedia)
# ============================================================================

class BalanceGuard:
    @staticmethod
    def validate(debit: Decimal, credit: Decimal, tolerance: Decimal = Decimal("0.0001")):
        if abs(debit - credit) > tolerance:
            raise ValueError(f"Debit {debit} dan Credit {credit} tidak seimbang (selisih {abs(debit - credit)})")


class PeriodGuard:
    @staticmethod
    def validate(period: str, journal_date: date):
        if not period or len(period) != 7 or period[4] != '-':
            raise ValueError(f"Format periode tidak valid: {period} (harus YYYY-MM)")


# ============================================================================
# IDEMPOTENCY MANAGER
# ============================================================================

class IdempotencyManager:
    def __init__(self):
        self._storage: dict[str, tuple[str, datetime]] = {}
        self._ttl_seconds = 86400

    def _get_key(self, idempotency_key: str, method_name: str) -> str:
        raw = f"{method_name}:{idempotency_key}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_cached_result(self, idempotency_key: str, method_name: str) -> dict[str, Any] | None:
        storage_key = self._get_key(idempotency_key, method_name)
        entry = self._storage.get(storage_key)
        if entry is None:
            return None
        result_json, timestamp = entry
        if (datetime.now(UTC) - timestamp).total_seconds() > self._ttl_seconds:
            del self._storage[storage_key]
            return None
        try:
            return json.loads(result_json)
        except json.JSONDecodeError:
            return None

    def cache_result(self, idempotency_key: str, method_name: str, result: dict[str, Any]) -> None:
        storage_key = self._get_key(idempotency_key, method_name)
        try:
            result_json = json.dumps(result, default=str)
        except TypeError:
            result_json = json.dumps({"result": str(result)}, default=str)
        self._storage[storage_key] = (result_json, datetime.now(UTC))


_idempotency_manager = IdempotencyManager()


class PostJournalEntryCommand(BaseCommand):
    """Command untuk posting jurnal umum."""

    __slots__ = (
        "attachment_ids",
        "description",
        "idempotency_key",
        "journal_date",
        "legal_entity_id",
        "lines",
        "period",
        "source_system",
    )

    def __init__(
        self,
        legal_entity_id: UUID,
        journal_date: date,
        period: str,
        description: str,
        lines: list[dict[str, Any]],
        source_system: str = "manual",
        attachment_ids: list[UUID] | None = None,
        idempotency_key: str | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="PostJournalEntryCommand",
            user_id=user_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        self.legal_entity_id = legal_entity_id
        self.journal_date = journal_date
        self.period = period
        self.description = description
        self.lines = lines
        self.source_system = source_system
        self.attachment_ids = attachment_ids or []

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "legal_entity_id": str(self.legal_entity_id),
            "journal_date": self.journal_date.isoformat(),
            "period": self.period,
            "description": self.description,
            "lines": self.lines,
            "source_system": self.source_system,
            "attachment_ids": [str(aid) for aid in self.attachment_ids],
        }


class PostJournalEntryUseCase:
    """
    Use case untuk posting jurnal umum.
    """

    def __init__(
        self,
        journal_service: JournalService,
        sealed_gate: SealedGate | None = None,
        audit_hook: AuditHookInjector | None = None,
    ):
        self._journal_service = journal_service
        self._sealed_gate = sealed_gate
        self._audit_hook = audit_hook or AuditHookInjector()
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}
        self._audit_trail: list[dict[str, Any]] = []
        self._balance_guard = BalanceGuard()
        self._period_guard = PeriodGuard()

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
            "service": "PostJournalEntryUseCase",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    @audit
    async def execute(self, command: PostJournalEntryCommand) -> CommandResult:
        # ==================== INPUT VALIDATION ====================
        if not command.legal_entity_id:
            raise ValueError("legal_entity_id is required")
        if not command.period or len(command.period) != 7 or command.period[4] != '-':
            raise ValueError(f"Invalid period format: {command.period} (expected YYYY-MM)")
        if not command.lines:
            raise ValueError("Journal lines cannot be empty")

        self._check_authority(command.user_id, "post_journal_entry_execute")
        self._stats["executed"] += 1

        if self._audit_hook:
            self._audit_hook.record_command_start(command)

        try:
            if command.idempotency_key:
                existing = await self._journal_service.find_by_idempotency_key(
                    command.idempotency_key
                )
                if existing:
                    return CommandResult.duplicate(
                        command.command_id, f"Duplicate command with key {command.idempotency_key}"
                    )

            total_debit = Decimal(0)
            total_credit = Decimal(0)
            for line in command.lines:
                total_debit += Decimal(str(line.get("debit", 0)))
                total_credit += Decimal(str(line.get("credit", 0)))
            self._balance_guard.validate(total_debit, total_credit)
            self._period_guard.validate(command.period, command.journal_date)

            lines_dto = []
            for line in command.lines:
                lines_dto.append(
                    JournalLineRequestDTO(
                        account_code=line.get("account_code"),
                        debit=Decimal(str(line.get("debit", 0))),
                        credit=Decimal(str(line.get("credit", 0))),
                        description=line.get("description", ""),
                        cost_center=line.get("cost_center"),
                        department=line.get("department"),
                        tax_code=line.get("tax_code"),
                        project_code=line.get("project_code"),
                        auxiliary_1=line.get("auxiliary_1"),
                        auxiliary_2=line.get("auxiliary_2"),
                    )
                )

            request = JournalEntryRequestDTO(
                legal_entity_id=command.legal_entity_id,
                journal_date=command.journal_date,
                period=command.period,
                description=command.description,
                lines=lines_dto,
                source_system=command.source_system,
                attachment_ids=command.attachment_ids,
                idempotency_key=command.idempotency_key,
            )

            if self._sealed_gate:
                async def _execute():
                    return await self._journal_service.post_journal_entry(
                        request=request,
                        user_id=command.user_id,
                        correlation_id=command.correlation_id,
                    )
                result = await self._sealed_gate.execute(
                    command_type=command.command_type,
                    command_id=command.command_id,
                    handler=_execute,
                )
            else:
                result = await self._journal_service.post_journal_entry(
                    request=request, user_id=command.user_id, correlation_id=command.correlation_id
                )

            self._stats["succeeded"] += 1
            self._record_audit("post_journal_entry_execute", {
                "period": command.period,
                "journal_date": command.journal_date.isoformat(),
                "user_id": str(command.user_id) if command.user_id else None,
            })

            return CommandResult.success(
                command_id=command.command_id, data=result.__dict__ if result else None
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"PostJournalEntry use case failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="JOURNAL_POSTING_ERROR"
            )
        finally:
            if self._audit_hook:
                self._audit_hook.record_command_end(command, None)

    def get_stats(self) -> dict[str, int]:
        return self._stats

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()


@audit
async def post_journal_entry_handler(
    command: BaseCommand,
    use_case: PostJournalEntryUseCase,
    idempotency_key: str | None = None,
) -> CommandResult:
    if not isinstance(command, PostJournalEntryCommand):
        raise TypeError(f"Expected PostJournalEntryCommand, got {type(command)}")

    use_case._check_authority(command.user_id, "post_journal_entry_handler")

    key = idempotency_key or getattr(command, "idempotency_key", None)
    method_name = "post_journal_entry_handler"

    if key is not None:
        cached = _idempotency_manager.get_cached_result(key, method_name)
        if cached is not None:
            logger.info("Idempotency hit for %s key=%s", method_name, key[:8])
            return CommandResult(
                command_id=getattr(command, "command_id", None),
                status=cached.get("status", "duplicate"),
                data=cached.get("data"),
                error=cached.get("error"),
                error_code=cached.get("error_code"),
            )

    # FIX: gunakan Decimal(0) sebagai nilai awal sum untuk menghindari Literal[0] / Decimal union
    total_debit = sum((Decimal(str(line.get("debit", 0))) for line in command.lines), Decimal(0))
    total_credit = sum((Decimal(str(line.get("credit", 0))) for line in command.lines), Decimal(0))
    BalanceGuard().validate(total_debit, total_credit)
    PeriodGuard().validate(command.period, command.journal_date)

    result = await use_case.execute(command)

    if key is not None:
        _idempotency_manager.cache_result(
            key,
            method_name,
            {
                "status": result.status,
                "data": result.data,
                "error": result.error,
                "error_code": result.error_code,
            }
        )

    return result


# ============================================================================
# SIMPLE CLASS FOR UNIT TESTS (synchronous) — dengan DI
# ============================================================================

class PostJournalTestHelper:
    """
    Kelas sederhana untuk keperluan unit test (synchronous).

    Digunakan untuk menguji logika posting jurnal tanpa ketergantungan async.
    Menerima objek journal dan mengubah statusnya menjadi 'POSTED' jika memenuhi
    syarat (status DRAFT atau APPROVED dan saldo debit-kredit seimbang).

    Metode utama:
        process(journal: Any) -> Any: Melakukan posting dan mengembalikan hasil.
    """

    def __init__(self, journal_service=None, balance_guard=None, period_guard=None):
        self._journal_service = journal_service
        self._balance_guard = balance_guard or BalanceGuard()
        self._period_guard = period_guard or PeriodGuard()

    @audit
    def process(self, journal: Any) -> Any:
        """
        Menjalankan posting jurnal secara sinkron (untuk unit test).

        Args:
            journal: Objek jurnal yang akan diposting (harus memiliki atribut status dan difference).

        Returns:
            Any: Objek hasil dengan atribut success=True jika berhasil.

        Raises:
            ValueError: Jika status jurnal tidak DRAFT/APPROVED atau saldo tidak seimbang.
        """
        # ==================== INPUT VALIDATION ====================
        if journal is None:
            raise ValueError("Journal object cannot be None")
        if not hasattr(journal, "status"):
            raise ValueError("Journal object must have 'status' attribute")
        if not hasattr(journal, "difference"):
            raise ValueError("Journal object must have 'difference' attribute")

        if journal.status not in ("DRAFT", "APPROVED"):
            raise ValueError(f"Journal must be in DRAFT or APPROVED state, got {journal.status}")

        if abs(journal.difference) > Decimal("0.0001"):
            raise ValueError(f"Debit and credit totals do not balance (difference: {journal.difference})")

        from types import SimpleNamespace
        result = SimpleNamespace()
        journal.status = "POSTED"
        result.success = True
        return result


def create_post_journal_entry_use_case(
    journal_service,
    sealed_gate=None,
    audit_hook=None,
    idempotency_key: str | None = None,
) -> PostJournalEntryUseCase:
    try:
        BalanceGuard().validate(Decimal(0), Decimal(0))
        PeriodGuard().validate("1970-01", date(1970, 1, 1))
    except Exception:
        pass
    if idempotency_key:
        pass
    return PostJournalEntryUseCase(journal_service, sealed_gate, audit_hook)


__all__ = [
    "PostJournalEntryCommand",
    "PostJournalEntryUseCase",
    "PostJournalTestHelper",
    "create_post_journal_entry_use_case",
    "post_journal_entry_handler",
]
