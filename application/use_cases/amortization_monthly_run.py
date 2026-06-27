#!/usr/bin/env python3
"""
Module: amortization_monthly_run.py
Layer: Application / Use Cases
Responsibility: Use case untuk amortisasi bulanan aset tidak berwujud.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from application.service_layer.service_intangible_asset import IntangibleAssetService
from application.service_layer.service_journal import JournalService

logger = logging.getLogger(__name__)


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class AmortizationRunRequest:
    """Request untuk amortisasi massal."""
    as_of_date: date
    asset_ids: list[UUID] | None = None
    post_to_ledger: bool = True
    fiscal_year: int | None = None
    period: int | None = None
    run_by: UUID
    legal_entity_id: UUID


@dataclass(kw_only=True)
class AmortizationRunResult:
    """Hasil amortisasi massal."""
    run_id: UUID
    run_number: str
    total_assets: int
    total_amortization: Decimal
    journal_ids: list[UUID]
    status: str
    errors: list[str] = field(default_factory=list)
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None


# ============================================================================
# EXCEPTIONS
# ============================================================================


class AmortizationRunError(Exception):
    pass


class NoAssetsToAmortizeError(AmortizationRunError):
    pass


# ============================================================================
# USE CASE
# ============================================================================


class AmortizationMonthlyRunUseCase:
    """
    Use case untuk menjalankan amortisasi bulanan.
    """

    def __init__(
        self,
        intangible_asset_service: IntangibleAssetService,
        journal_service: JournalService,
    ):
        self._asset_service = intangible_asset_service
        self._journal_service = journal_service
        self._stats = {"runs": 0, "assets_amortized": 0, "total_amortization": Decimal("0")}

    async def execute(self, request: AmortizationRunRequest) -> AmortizationRunResult:
        """
        Execute monthly amortization run.
        """
        logger.info(f"Starting amortization run for {request.as_of_date}")

        # 1. Get all active assets to amortize
        assets = await self._asset_service.get_assets_to_amortize(
            legal_entity_id=request.legal_entity_id,
            as_of_date=request.as_of_date,
            asset_ids=request.asset_ids,
        )

        if not assets:
            raise NoAssetsToAmortizeError("No assets found to amortize")

        # 2. Calculate amortization for each asset
        total_amortization = Decimal("0")
        amortization_entries = []
        errors = []

        for asset in assets:
            try:
                entry = await self._asset_service.calculate_monthly_amortization(
                    asset_id=asset.id,
                    as_of_date=request.as_of_date,
                )
                amortization_entries.append(entry)
                total_amortization += entry.amortization_amount
            except Exception as e:
                errors.append(f"Asset {asset.asset_code}: {e!s}")
                logger.error(f"Failed to calculate amortization for {asset.asset_code}: {e}")

        if not amortization_entries and errors:
            raise AmortizationRunError("All assets failed to amortize")

        # 3. Post amortization journal (if not dry run)
        journal_ids = []
        if request.post_to_ledger and amortization_entries:
            for entry in amortization_entries:
                journal_id = await self._post_amortization_journal(
                    entry=entry,
                    legal_entity_id=request.legal_entity_id,
                    as_of_date=request.as_of_date,
                    run_by=request.run_by,
                )
                journal_ids.append(journal_id)

                # Update asset with amortization
                await self._asset_service.record_amortization(
                    asset_id=entry.asset_id,
                    amortization_amount=entry.amortization_amount,
                    journal_id=journal_id,
                    period_date=request.as_of_date,
                    updated_by=request.run_by,
                )

        # 4. Generate run number
        run_number = await self._generate_run_number(request.legal_entity_id)

        # 5. Update stats
        self._stats["runs"] += 1
        self._stats["assets_amortized"] += len(amortization_entries)
        self._stats["total_amortization"] += total_amortization

        logger.info(
            f"Amortization run completed: {len(amortization_entries)} assets, "
            f"total amortization {total_amortization}"
        )

        return AmortizationRunResult(
            run_id=uuid4(),
            run_number=run_number,
            total_assets=len(amortization_entries),
            total_amortization=total_amortization,
            journal_ids=journal_ids,
            status="COMPLETED" if not errors else "COMPLETED_WITH_ERRORS",
            errors=errors,
            created_at=datetime.utcnow(),
            created_by=request.run_by,
        )

    async def _post_amortization_journal(
        self,
        entry: Any,
        legal_entity_id: UUID,
        as_of_date: date,
        run_by: UUID,
    ) -> UUID:
        """
        Post amortization journal entry to ledger.
        """
        # Debit: Amortization Expense (5-6100)
        # Credit: Accumulated Amortization (1-1900)
        lines = [
            {
                "account_code": "5-6100",  # Amortization Expense
                "debit": entry.amortization_amount,
                "credit": Decimal("0"),
                "description": f"Amortization - {entry.asset_code}",
            },
            {
                "account_code": "1-1900",  # Accumulated Amortization
                "debit": Decimal("0"),
                "credit": entry.amortization_amount,
                "description": f"Amortization - {entry.asset_code}",
            },
        ]

        journal_id = await self._journal_service.post_journal(
            legal_entity_id=legal_entity_id,
            journal_date=as_of_date,
            period=f"{as_of_date.year}-{as_of_date.month:02d}",
            description=f"Amortization run for {as_of_date} - {entry.asset_code}",
            lines=lines,
            source_system="intangible_asset_amortization",
            user_id=run_by,
        )

        return journal_id

    async def _generate_run_number(self, legal_entity_id: UUID) -> str:
        """Generate unique run number."""
        # In production, this would fetch from repository
        import random
        seq = random.randint(1000, 9999)
        return f"AMORT-{date.today().year}{date.today().month:02d}-{seq}"

    def get_stats(self) -> dict[str, Any]:
        """Get use case statistics."""
        return {
            **self._stats,
            "total_amortization": float(self._stats["total_amortization"]),
        }


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "AmortizationMonthlyRunUseCase",
    "AmortizationRunError",
    "AmortizationRunRequest",
    "AmortizationRunResult",
    "NoAssetsToAmortizeError",
]
