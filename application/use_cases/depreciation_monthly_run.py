#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Module: depreciation_monthly_run.py

Layer: 8 - Application / Use Cases

Responsibility:
    Use case untuk menjalankan depresiasi bulanan untuk semua aset tetap.
    Dilengkapi dengan idempotensi untuk mencegah eksekusi ganda terhadap command yang sama.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from functools import wraps
from typing import Any
from uuid import UUID

from application.commands_cqrs.command_bus_unified import BaseCommand, CommandResult
from application.service_layer.service_fixed_asset import FixedAssetService
from application.service_layer.service_journal import JournalService
from kernel.sealed_gate import SealedGate
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


def transactional(method):
    """Membungkus method dengan Unit of Work context."""
    @wraps(method)
    async def wrapper(self, *args, **kwargs):
        async with self._uow:
            return await method(self, *args, **kwargs)
    return wrapper


class DepreciationMonthlyRunCommand(BaseCommand):
    __slots__ = ("dry_run", "legal_entity_id", "period_month", "period_year", "posting_date", "prorate_first_year")

    def __init__(
        self,
        legal_entity_id: UUID,
        period_year: int,
        period_month: int,
        posting_date: date,
        prorate_first_year: bool = True,
        dry_run: bool = False,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="DepreciationMonthlyRunCommand",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        self.legal_entity_id = legal_entity_id
        self.period_year = period_year
        self.period_month = period_month
        self.posting_date = posting_date
        self.prorate_first_year = prorate_first_year
        self.dry_run = dry_run

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "legal_entity_id": str(self.legal_entity_id),
                "period_year": self.period_year,
                "period_month": self.period_month,
                "posting_date": self.posting_date.isoformat(),
                "prorate_first_year": self.prorate_first_year,
                "dry_run": self.dry_run,
            }
        )
        return data


class DepreciationRunResult:
    def __init__(
        self,
        total_assets_processed: int,
        total_depreciation_amount: Decimal,
        journal_id: UUID | None,
        errors: list[str],
    ):
        self.total_assets_processed = total_assets_processed
        self.total_depreciation_amount = total_depreciation_amount
        self.journal_id = journal_id
        self.errors = errors


class DepreciationMonthlyRunUseCase:
    def __init__(
        self,
        fixed_asset_service: FixedAssetService,
        journal_service: JournalService,
        uow: UnitOfWorkPort,
        sealed_gate: SealedGate | None = None,
    ):
        self._fa_service = fixed_asset_service
        self._journal_service = journal_service
        self._uow = uow
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}
        # Penyimpanan hasil idempotensi (dalam memori, untuk demonstrasi)
        self._idempotency_store: dict[str, CommandResult] = {}

    @transactional
    async def execute(self, command: DepreciationMonthlyRunCommand) -> CommandResult:
        # Idempotensi: cek apakah command_id sudah pernah diproses
        cmd_id = getattr(command, "command_id", None)
        if cmd_id is not None and cmd_id in self._idempotency_store:
            logger.info(
                "Idempotency hit for command %s, returning cached result",
                cmd_id
            )
            return self._idempotency_store[cmd_id]

        self._stats["executed"] += 1

        try:
            assets = await self._fa_service.list_assets(
                legal_entity_id=command.legal_entity_id, status="ACTIVE", limit=10000
            )
            if not assets:
                result = CommandResult.success(
                    command_id=command.command_id,
                    data={
                        "total_assets_processed": 0,
                        "total_depreciation_amount": 0.0,
                        "journal_id": None,
                        "errors": ["No active assets found"],
                    },
                )
                if cmd_id is not None:
                    self._idempotency_store[cmd_id] = result
                return result

            period_start = date(command.period_year, command.period_month, 1)
            if command.period_month == 12:
                period_end = date(command.period_year + 1, 1, 1) - timedelta(days=1)
            else:
                period_end = date(command.period_year, command.period_month + 1, 1) - timedelta(days=1)

            depreciation_lines = []
            processed_count = 0
            total_depreciation = Decimal("0")
            errors = []

            async def _process_asset(asset):
                nonlocal processed_count, total_depreciation
                try:
                    dep_amount = await self._fa_service.calculate_asset_depreciation(
                        asset_id=asset.id,
                        period_start=period_start,
                        period_end=period_end,
                        prorate_first_year=command.prorate_first_year,
                    )
                    if dep_amount > 0:
                        depreciation_lines.append(
                            {
                                "asset_id": asset.id,
                                "asset_code": asset.asset_code,
                                "amount": dep_amount,
                                "depreciation_expense_account": asset.depreciation_expense_account or "5-5200",
                                "accumulated_depreciation_account": asset.accumulated_depreciation_account or "1-1900",
                            }
                        )
                        total_depreciation += dep_amount
                        processed_count += 1
                        if not command.dry_run:
                            await self._fa_service.record_asset_depreciation(
                                asset_id=asset.id,
                                amount=dep_amount,
                                period_year=command.period_year,
                                period_month=command.period_month,
                                posting_date=command.posting_date,
                                user_id=command.user_id,
                            )
                except Exception as e:
                    errors.append(f"Asset {asset.asset_code}: {e!s}")

            for asset in assets:
                await _process_asset(asset)

            journal_id = None
            if not command.dry_run and depreciation_lines:
                lines = []
                for line in depreciation_lines:
                    lines.append(
                        {
                            "account_code": line["depreciation_expense_account"],
                            "debit": line["amount"],
                            "credit": Decimal("0"),
                            "description": f"Depreciation - {line['asset_code']}",
                        }
                    )
                    lines.append(
                        {
                            "account_code": line["accumulated_depreciation_account"],
                            "debit": Decimal("0"),
                            "credit": line["amount"],
                            "description": f"Accumulated depreciation - {line['asset_code']}",
                        }
                    )
                journal_id = await self._journal_service.post_journal(
                    legal_entity_id=command.legal_entity_id,
                    journal_date=command.posting_date,
                    period=f"{command.period_year}-{command.period_month:02d}",
                    description=f"Monthly depreciation for {command.period_year}-{command.period_month:02d}",
                    lines=lines,
                    source_system="fixed_asset",
                    user_id=command.user_id,
                    correlation_id=command.correlation_id,
                )

            dep_result = DepreciationRunResult(
                total_assets_processed=processed_count,
                total_depreciation_amount=total_depreciation,
                journal_id=journal_id,
                errors=errors,
            )

            self._stats["succeeded"] += 1
            result = CommandResult.success(
                command_id=command.command_id,
                data={
                    "total_assets_processed": dep_result.total_assets_processed,
                    "total_depreciation_amount": float(dep_result.total_depreciation_amount),
                    "journal_id": str(dep_result.journal_id) if dep_result.journal_id else None,
                    "errors": dep_result.errors,
                },
            )
            if cmd_id is not None:
                self._idempotency_store[cmd_id] = result
            return result

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"Depreciation monthly run failed: {e}")
            result = CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="DEPRECIATION_RUN_ERROR"
            )
            if cmd_id is not None:
                self._idempotency_store[cmd_id] = result
            return result

    def get_stats(self) -> dict[str, int]:
        return self._stats


def build_depreciation_monthly_run_use_case(
    fixed_asset_service: FixedAssetService,
    journal_service: JournalService,
    uow: UnitOfWorkPort,
    sealed_gate: SealedGate | None = None,
) -> DepreciationMonthlyRunUseCase:
    """
    Factory untuk membuat instance DepreciationMonthlyRunUseCase.
    Fungsi ini bersifat pure factory dan tidak memiliki efek samping,
    sehingga tidak memerlukan idempotensi.
    """
    return DepreciationMonthlyRunUseCase(
        fixed_asset_service=fixed_asset_service,
        journal_service=journal_service,
        uow=uow,
        sealed_gate=sealed_gate,
    )


async def depreciation_monthly_run_handler(command: DepreciationMonthlyRunCommand) -> CommandResult:
    """
    Handler untuk command DepreciationMonthlyRunCommand.

    Catatan: Handler ini belum diimplementasikan dengan dependency injection.
    Untuk penggunaan nyata, gunakan factory dan panggil use case secara langsung.
    """
    raise NotImplementedError(
        "Handler belum diimplementasikan dengan benar. "
        "Harus mengakses FixedAssetService, JournalService, dan UnitOfWorkPort dari container."
    )


__all__ = [
    "DepreciationMonthlyRunCommand",
    "DepreciationMonthlyRunUseCase",
    "DepreciationRunResult",
    "build_depreciation_monthly_run_use_case",
    "depreciation_monthly_run_handler",
]