#!/usr/bin/env python3

"""
Module: approve_journal_four_eyes.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk approve jurnal dengan prinsip four-eyes (persetujuan dua orang).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from application.commands_cqrs.command_bus_unified import BaseCommand, CommandResult
from application.service_layer.service_journal import JournalService
from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


class ApproveJournalCommand(BaseCommand):
    """Command untuk approve jurnal."""

    __slots__ = ("is_override", "journal_id", "override_reason")

    def __init__(
        self,
        journal_id: UUID,
        is_override: bool = False,
        override_reason: str | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="ApproveJournalCommand", user_id=user_id, correlation_id=correlation_id
        )
        self.journal_id = journal_id
        self.is_override = is_override
        self.override_reason = override_reason

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "journal_id": str(self.journal_id),
                "is_override": self.is_override,
                "override_reason": self.override_reason,
            }
        )
        return data


class ApproveJournalUseCase:
    """
    Use case untuk approve jurnal (four-eyes principle).
    """

    def __init__(self, journal_service: JournalService, sealed_gate: SealedGate | None = None):
        self._journal_service = journal_service
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: ApproveJournalCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            # 1. Ambil jurnal dari repository
            journal_agg = await self._journal_service.get_journal_aggregate(command.journal_id)
            if not journal_agg:
                raise ValueError(f"Journal {command.journal_id} not found")

            journal = journal_agg.journal

            # 2. Validasi status (harus POSTED)
            if journal.status.value != "POSTED":
                raise ValueError(f"Cannot approve journal in status {journal.status.value}")

            # 3. Validasi four-eyes: approver != creator
            if journal.created_by == command.user_id and not command.is_override:
                raise PermissionError(
                    "Creator cannot approve own journal. Use override if allowed."
                )

            # 4. Jika override, butuh reason dan otorisasi khusus
            if command.is_override:
                if not command.override_reason:
                    raise ValueError("Override reason is required")
                # Di sini bisa tambahkan validasi role admin (misal hanya user dengan role tertentu)
                # Untuk implementasi nyata, panggil IAM service
                logger.warning(
                    f"Override approval by {command.user_id}, reason: {command.override_reason}"
                )

            # 5. Panggil service untuk approve
            async def _execute():
                result = await self._journal_service.approve_journal(
                    journal_id=command.journal_id,
                    approver_id=command.user_id,
                    is_override=command.is_override,
                    override_reason=command.override_reason,
                    correlation_id=command.correlation_id,
                )
                return result

            if self._sealed_gate:
                result = await self._sealed_gate.execute(
                    command_type=command.command_type,
                    command_id=command.command_id,
                    handler=_execute,
                )
            else:
                result = await _execute()

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={"journal_id": str(command.journal_id), "status": "APPROVED"},
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"Approve journal failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="APPROVAL_ERROR"
            )

    def get_stats(self) -> dict[str, int]:
        return self._stats


# ============================================================================
# Handler dengan dependency injection (tanpa container)
# ============================================================================


async def approve_journal_handler(
    command: BaseCommand, use_case: ApproveJournalUseCase
) -> CommandResult:
    if not isinstance(command, ApproveJournalCommand):
        raise TypeError(f"Expected ApproveJournalCommand, got {type(command)}")
    return await use_case.execute(command)


# Buat alias eksplisit agar kompatibel dengan penamaan di lapisan FastAPI Journal Router
ApproveJournalFourEyesUseCase = ApproveJournalUseCase

__all__ = [
    "ApproveJournalCommand",
    "ApproveJournalFourEyesUseCase",  # <--- Tambahkan ini ke dalam ekspor modul
    "ApproveJournalUseCase",
    "approve_journal_handler",
]
