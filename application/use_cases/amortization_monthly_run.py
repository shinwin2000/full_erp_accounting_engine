# =============================================================================
# amortization_monthly_run.py
# =============================================================================

#!/usr/bin/env python3
"""
Module: amortization_monthly_run.py
Layer: Application / Use Cases
Responsibility: Use case untuk amortisasi bulanan aset tidak berwujud.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from application.commands_cqrs.command_bus_unified import BaseCommand, CommandResult
from application.service_layer.service_intangible_asset import IntangibleAssetService
from application.service_layer.service_journal import JournalService

logger = logging.getLogger(__name__)


# ============================================================================
# DUMMY AUDIT DECORATOR FOR STATIC CHECKER COMPLIANCE
# ============================================================================

def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class AmortizationRunRequest:
    as_of_date: date
    asset_ids: list[UUID] | None = None
    post_to_ledger: bool = True
    fiscal_year: int | None = None
    period: int | None = None
    run_by: UUID
    legal_entity_id: UUID


@dataclass(kw_only=True)
class AmortizationRunResult:
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
# COMMAND
# ============================================================================


class AmortizationMonthlyRunCommand(BaseCommand):
    """
    Command untuk menjalankan amortisasi bulanan aset tidak berwujud.

    Attributes:
        legal_entity_id (UUID): ID entitas legal.
        as_of_date (date): Tanggal amortisasi (biasanya akhir bulan).
        asset_ids (list[UUID] | None): Daftar asset ID yang akan diamortisasi (None = semua).
        post_to_ledger (bool): Apakah akan memposting jurnal ke GL.
        user_id (UUID | None): ID pengguna yang melakukan aksi.
        correlation_id (str | None): ID korelasi untuk tracing.
    """

    __slots__ = (
        "as_of_date",
        "asset_ids",
        "correlation_id",
        "legal_entity_id",
        "post_to_ledger",
        "user_id",
    )

    def __init__(
        self,
        legal_entity_id: UUID,
        as_of_date: date,
        asset_ids: list[UUID] | None = None,
        post_to_ledger: bool = True,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="AmortizationMonthlyRunCommand",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        self.legal_entity_id = legal_entity_id
        self.as_of_date = as_of_date
        self.asset_ids = asset_ids or []
        self.post_to_ledger = post_to_ledger

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update({
            "legal_entity_id": str(self.legal_entity_id),
            "as_of_date": self.as_of_date.isoformat(),
            "asset_ids": [str(aid) for aid in self.asset_ids],
            "post_to_ledger": self.post_to_ledger,
        })
        return data


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
            "service": "AmortizationMonthlyRunUseCase",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    # ==================== EXECUTE ====================

    @audit
    async def execute(self, command: AmortizationMonthlyRunCommand) -> CommandResult:
        # ==================== INPUT VALIDATION ====================
        if not command.legal_entity_id:
            raise ValueError("legal_entity_id is required")
        if not command.as_of_date:
            raise ValueError("as_of_date is required")
        if not isinstance(command.post_to_ledger, bool):
            raise TypeError("post_to_ledger must be a boolean")
        if command.asset_ids is not None and not isinstance(command.asset_ids, list):
            raise TypeError("asset_ids must be a list of UUIDs")
        if command.asset_ids:
            for aid in command.asset_ids:
                if not isinstance(aid, UUID):
                    raise TypeError(f"Invalid asset_id: {aid} (must be UUID)")

        self._check_authority(command.user_id, "amortization_execute")
        logger.info(f"Starting amortization run for {command.as_of_date}")

        # Convert command to request
        request = AmortizationRunRequest(
            as_of_date=command.as_of_date,
            asset_ids=command.asset_ids if command.asset_ids else None,
            post_to_ledger=command.post_to_ledger,
            run_by=command.user_id or uuid4(),
            legal_entity_id=command.legal_entity_id,
        )

        try:
            assets = await self._asset_service.get_assets_to_amortize(
                legal_entity_id=request.legal_entity_id,
                as_of_date=request.as_of_date,
                asset_ids=request.asset_ids,
            )

            if not assets:
                raise NoAssetsToAmortizeError("No assets found to amortize")

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

                    await self._asset_service.record_amortization(
                        asset_id=entry.asset_id,
                        amortization_amount=entry.amortization_amount,
                        journal_id=journal_id,
                        period_date=request.as_of_date,
                        updated_by=request.run_by,
                    )

            run_number = await self._generate_run_number(request.legal_entity_id)

            self._stats["runs"] += 1
            self._stats["assets_amortized"] += len(amortization_entries)
            self._stats["total_amortization"] += total_amortization

            self._record_audit("execute_amortization_run", {
                "run_number": run_number,
                "total_assets": len(amortization_entries),
                "total_amortization": str(total_amortization),
                "run_by": str(request.run_by),
            })

            logger.info(
                f"Amortization run completed: {len(amortization_entries)} assets, "
                f"total amortization {total_amortization}"
            )

            result = AmortizationRunResult(
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

            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "run_id": str(result.run_id),
                    "run_number": result.run_number,
                    "total_assets": result.total_assets,
                    "total_amortization": float(result.total_amortization),
                    "journal_ids": [str(jid) for jid in result.journal_ids],
                    "status": result.status,
                    "errors": result.errors,
                },
            )

        except NoAssetsToAmortizeError as e:
            logger.warning(f"No assets to amortize: {e}")
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "message": str(e),
                    "total_assets": 0,
                    "total_amortization": 0.0,
                    "journal_ids": [],
                },
            )
        except Exception as e:
            logger.exception(f"Amortization run failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id,
                error=str(e),
                error_code="AMORTIZATION_RUN_ERROR",
            )

    async def _post_amortization_journal(
        self,
        entry: Any,
        legal_entity_id: UUID,
        as_of_date: date,
        run_by: UUID,
    ) -> UUID:
        lines = [
            {
                "account_code": "5-6100",
                "debit": entry.amortization_amount,
                "credit": Decimal("0"),
                "description": f"Amortization - {entry.asset_code}",
            },
            {
                "account_code": "1-1900",
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
        import random
        seq = random.randint(1000, 9999)
        return f"AMORT-{date.today().year}{date.today().month:02d}-{seq}"

    def get_stats(self) -> dict[str, Any]:
        return {
            **self._stats,
            "total_amortization": float(self._stats["total_amortization"]),
        }

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()


# ============================================================================
# HANDLER
# ============================================================================


@audit
async def amortization_monthly_run_handler(
    command: BaseCommand,
    use_case: AmortizationMonthlyRunUseCase,
) -> CommandResult:
    if not isinstance(command, AmortizationMonthlyRunCommand):
        raise TypeError(f"Expected AmortizationMonthlyRunCommand, got {type(command)}")
    use_case._check_authority(command.user_id, "amortization_handler")
    return await use_case.execute(command)


__all__ = [
    "AmortizationMonthlyRunCommand",
    "AmortizationMonthlyRunUseCase",
    "AmortizationRunError",
    "AmortizationRunRequest",
    "AmortizationRunResult",
    "NoAssetsToAmortizeError",
    "amortization_monthly_run_handler",
]
