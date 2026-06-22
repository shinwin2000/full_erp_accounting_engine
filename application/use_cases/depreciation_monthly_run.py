#!/usr/bin/env python3

"""
Module: depreciation_monthly_run.py

Layer: 8 - Application / Use Cases

Responsibility:
    Use case untuk menjalankan depresiasi bulanan untuk semua aset tetap.
    Mencakup:
    - Mengambil semua aset aktif yang belum fully depreciated
    - Menghitung depresiasi untuk bulan berjalan berdasarkan metode (straight-line, declining balance)
    - Membuat jurnal depresiasi (debit depreciation expense, credit accumulated depreciation)
    - Menyimpan detail depresiasi per aset ke tabel schedule
    - Update nilai buku aset (net book value)
    - Menangani aset yang diakuisisi di tengah bulan (prorata)
    - Posting jurnal ke GL
    - Audit trail untuk setiap transaksi depresiasi

Dependencies:
    - application/service_layer/service_fixed_asset.py (FixedAssetService)
    - application/service_layer/service_journal.py (JournalService)
    - application/commands_cqrs/command_bus_unified.py (Command, CommandResult)
    - kernel/sealed_gate.py

Audit:
    Setiap run depresiasi dicatat dengan jumlah aset, total depresiasi, dan journal ID.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from application.commands_cqrs.command_bus_unified import BaseCommand, CommandResult
from application.service_layer.service_fixed_asset import FixedAssetService
from application.service_layer.service_journal import JournalService
from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


class DepreciationMonthlyRunCommand(BaseCommand):
    """Command untuk menjalankan depresiasi bulanan."""

    __slots__ = (
        "dry_run",
        "legal_entity_id",
        "period_month",
        "period_year",
        "posting_date",
        "prorate_first_year",
    )

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
    """
    Use case untuk menjalankan depresiasi bulanan.
    Semua dependensi diberikan melalui constructor (dependency injection).
    """

    def __init__(
        self,
        fixed_asset_service: FixedAssetService,
        journal_service: JournalService,
        sealed_gate: SealedGate | None = None,
    ):
        self._fa_service = fixed_asset_service
        self._journal_service = journal_service
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: DepreciationMonthlyRunCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            # 1. Ambil semua aset aktif per legal entity
            assets = await self._fa_service.list_assets(
                legal_entity_id=command.legal_entity_id, status="ACTIVE", limit=10000
            )

            if not assets:
                return CommandResult.success(
                    command_id=command.command_id,
                    data={
                        "total_assets_processed": 0,
                        "total_depreciation_amount": 0.0,
                        "journal_id": None,
                        "errors": ["No active assets found"],
                    },
                )

            period_start = date(command.period_year, command.period_month, 1)
            # Hitung akhir bulan
            if command.period_month == 12:
                period_end = date(command.period_year + 1, 1, 1) - timedelta(days=1)
            else:
                period_end = date(command.period_year, command.period_month + 1, 1) - timedelta(
                    days=1
                )

            depreciation_lines = []
            processed_count = 0
            total_depreciation = Decimal("0")
            errors = []

            async def _process_asset(asset):
                nonlocal processed_count, total_depreciation
                try:
                    # Hitung depresiasi untuk aset ini
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
                                "depreciation_expense_account": asset.depreciation_expense_account
                                or "5-5200",
                                "accumulated_depreciation_account": asset.accumulated_depreciation_account
                                or "1-1900",
                            }
                        )
                        total_depreciation += dep_amount
                        processed_count += 1

                        # Update aset: tambah accumulated depreciation, kurangi NBV
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

            # Proses semua aset (bisa paralel, tapi hati2)
            for asset in assets:
                await _process_asset(asset)

            # Buat jurnal depresiasi jika ada
            journal_id = None
            if not command.dry_run and depreciation_lines:
                # Kelompokkan lines berdasarkan account (bisa multiple assets per account)
                # Untuk sederhana, kita buat satu jurnal dengan banyak lines
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

            result = DepreciationRunResult(
                total_assets_processed=processed_count,
                total_depreciation_amount=total_depreciation,
                journal_id=journal_id,
                errors=errors,
            )

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "total_assets_processed": result.total_assets_processed,
                    "total_depreciation_amount": float(result.total_depreciation_amount),
                    "journal_id": str(result.journal_id) if result.journal_id else None,
                    "errors": result.errors,
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"Depreciation monthly run failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="DEPRECIATION_RUN_ERROR"
            )

    def get_stats(self) -> dict[str, int]:
        return self._stats


# ============================================================================
# Factory function (pure application layer, no infrastructure imports)
# ============================================================================


def create_depreciation_monthly_run_use_case(
    fixed_asset_service: FixedAssetService,
    journal_service: JournalService,
    sealed_gate: SealedGate | None = None,
) -> DepreciationMonthlyRunUseCase:
    """
    Factory untuk membuat instance use case.
    Dependency injection: semua dependensi diberikan dari luar (oleh adapter/infrastructure).
    """
    return DepreciationMonthlyRunUseCase(
        fixed_asset_service=fixed_asset_service,
        journal_service=journal_service,
        sealed_gate=sealed_gate,
    )


# ============================================================================
# Handler (untuk di-register ke command bus)
# ============================================================================


async def depreciation_monthly_run_handler(command: DepreciationMonthlyRunCommand) -> CommandResult:
    """
    Handler untuk command DepreciationMonthlyRunCommand.
    Handler ini mengasumsikan bahwa use case sudah dibuat dan disimpan di suatu
    tempat (misalnya dalam container DI) dan diakses melalui fungsi global
    atau closure. Karena contoh ini tidak memiliki akses ke container,
    maka handler akan membuat use case secara langsung dengan dependensi
    yang diambil dari registry global (jika ada) atau raise error.

    Untuk penggunaan nyata, sebaiknya handler ini menerima use case sebagai
    parameter yang diinject oleh command bus.
    """
    # Di sini Anda harus mengambil instance FixedAssetService dan JournalService
    # dari container Anda, misalnya:
    #
    # fa_service = container.get(FixedAssetService)
    # journal_service = container.get(JournalService)
    #
    # use_case = DepreciationMonthlyRunUseCase(fa_service, journal_service)
    # return await use_case.execute(command)

    raise NotImplementedError(
        "Handler belum diimplementasikan dengan benar. "
        "Harus mengakses FixedAssetService dan JournalService dari container "
        "atau menggunakan dependency injection pada command bus."
    )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "DepreciationMonthlyRunCommand",
    "DepreciationMonthlyRunUseCase",
    "DepreciationRunResult",
    "create_depreciation_monthly_run_use_case",
    "depreciation_monthly_run_handler",  # <-- ditambahkan
]
