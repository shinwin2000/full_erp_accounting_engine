#!/usr/bin/env python3

"""
Module: cogs_calculation.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk menghitung Cost of Goods Sold (COGS / HPP) untuk suatu periode.
    Mencakup perhitungan nilai persediaan awal dan akhir, pembelian, biaya produksi,
    penentuan metode penilaian, dan posting jurnal COGS ke GL.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from application.commands_cqrs.command_bus_unified import Command, CommandResult
from application.service_layer.service_inventory import InventoryService
from application.service_layer.service_journal import JournalService
from application.service_layer.service_manufacturing import ManufacturingService
from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


class COGSMethod(Enum):
    FIFO = "FIFO"
    WEIGHTED_AVERAGE = "WEIGHTED_AVERAGE"
    STANDARD_COST = "STANDARD_COST"


class COGSCalculationCommand(Command):
    """Command untuk menghitung COGS."""

    __slots__ = (
        "dry_run",
        "include_manufacturing",
        "legal_entity_id",
        "method",
        "period_end",
        "period_start",
        "post_to_gl",
    )

    def __init__(
        self,
        legal_entity_id: UUID,
        period_start: date,
        period_end: date,
        method: str = "FIFO",
        include_manufacturing: bool = True,
        post_to_gl: bool = True,
        dry_run: bool = False,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="COGSCalculationCommand", user_id=user_id, correlation_id=correlation_id
        )
        self.legal_entity_id = legal_entity_id
        self.period_start = period_start
        self.period_end = period_end
        self.method = method
        self.include_manufacturing = include_manufacturing
        self.post_to_gl = post_to_gl
        self.dry_run = dry_run

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "legal_entity_id": str(self.legal_entity_id),
                "period_start": self.period_start.isoformat(),
                "period_end": self.period_end.isoformat(),
                "method": self.method,
                "include_manufacturing": self.include_manufacturing,
                "post_to_gl": self.post_to_gl,
                "dry_run": self.dry_run,
            }
        )
        return data


class COGSResult:
    def __init__(
        self,
        beginning_inventory: Decimal,
        purchases: Decimal,
        manufacturing_costs: Decimal,
        ending_inventory: Decimal,
        cogs: Decimal,
        journal_id: UUID | None = None,
        method_used: str = "FIFO",
    ):
        self.beginning_inventory = beginning_inventory
        self.purchases = purchases
        self.manufacturing_costs = manufacturing_costs
        self.ending_inventory = ending_inventory
        self.cogs = cogs
        self.journal_id = journal_id
        self.method_used = method_used


class COGSCalculationUseCase:
    """
    Use case untuk menghitung COGS.
    """

    def __init__(
        self,
        inventory_service: InventoryService,
        journal_service: JournalService,
        manufacturing_service: ManufacturingService | None = None,
        sealed_gate: SealedGate | None = None,
    ):
        self._inventory_service = inventory_service
        self._journal_service = journal_service
        self._manufacturing_service = manufacturing_service
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: COGSCalculationCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            # 1. Dapatkan nilai persediaan awal
            beginning_inventory = await self._inventory_service.get_inventory_value(
                legal_entity_id=command.legal_entity_id,
                as_of_date=command.period_start - timedelta(days=1),
                method=command.method,
            )

            # 2. Dapatkan nilai persediaan akhir
            ending_inventory = await self._inventory_service.get_inventory_value(
                legal_entity_id=command.legal_entity_id,
                as_of_date=command.period_end,
                method=command.method,
            )

            # 3. Dapatkan total pembelian selama periode
            purchases = await self._inventory_service.get_purchases_total(
                legal_entity_id=command.legal_entity_id,
                from_date=command.period_start,
                to_date=command.period_end,
            )

            # 4. Dapatkan biaya manufacturing jika diperlukan
            manufacturing_costs = Decimal("0")
            if command.include_manufacturing and self._manufacturing_service:
                manufacturing_costs = await self._manufacturing_service.get_manufacturing_costs(
                    legal_entity_id=command.legal_entity_id,
                    from_date=command.period_start,
                    to_date=command.period_end,
                )

            # 5. Hitung COGS
            cogs = beginning_inventory + purchases + manufacturing_costs - ending_inventory
            cogs = cogs.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

            # Jika dry run, hanya kembalikan hasil
            if command.dry_run:
                return CommandResult.success(
                    command_id=command.command_id,
                    data={
                        "dry_run": True,
                        "beginning_inventory": float(beginning_inventory),
                        "purchases": float(purchases),
                        "manufacturing_costs": float(manufacturing_costs),
                        "ending_inventory": float(ending_inventory),
                        "cogs": float(cogs),
                        "method_used": command.method,
                    },
                )

            # 6. Post jurnal COGS jika diminta
            journal_id = None
            if command.post_to_gl and cogs != 0:
                journal_id = await self._post_cogs_journal(
                    command.legal_entity_id,
                    cogs,
                    command.period_start,
                    command.period_end,
                    command.user_id,
                    command.correlation_id,
                )

            result = COGSResult(
                beginning_inventory=beginning_inventory,
                purchases=purchases,
                manufacturing_costs=manufacturing_costs,
                ending_inventory=ending_inventory,
                cogs=cogs,
                journal_id=journal_id,
                method_used=command.method,
            )

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "beginning_inventory": float(result.beginning_inventory),
                    "purchases": float(result.purchases),
                    "manufacturing_costs": float(result.manufacturing_costs),
                    "ending_inventory": float(result.ending_inventory),
                    "cogs": float(result.cogs),
                    "journal_id": str(result.journal_id) if result.journal_id else None,
                    "method_used": result.method_used,
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"COGS calculation failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="COGS_CALCULATION_ERROR"
            )

    async def _post_cogs_journal(
        self,
        legal_entity_id: UUID,
        cogs_amount: Decimal,
        period_start: date,
        period_end: date,
        user_id: UUID,
        correlation_id: str | None,
    ) -> UUID:
        cogs_account = "5-5000"
        inventory_account = "1-1200"

        lines = [
            {
                "account_code": cogs_account,
                "debit": cogs_amount,
                "credit": Decimal("0"),
                "description": f"COGS for period {period_start} to {period_end}",
            },
            {
                "account_code": inventory_account,
                "debit": Decimal("0"),
                "credit": cogs_amount,
                "description": "Reduction in inventory for COGS",
            },
        ]

        journal_id = await self._journal_service.post_journal(
            legal_entity_id=legal_entity_id,
            journal_date=period_end,
            period=f"{period_end.year}-{period_end.month:02d}",
            description=f"COGS calculation for period {period_start} to {period_end}",
            lines=lines,
            source_system="inventory",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        return journal_id

    def get_stats(self) -> dict[str, int]:
        return self._stats


# ============================================================================
# Handler dengan dependency injection
# ============================================================================


async def cogs_calculation_handler(
    command: Command, use_case: COGSCalculationUseCase
) -> CommandResult:
    if not isinstance(command, COGSCalculationCommand):
        raise TypeError(f"Expected COGSCalculationCommand, got {type(command)}")
    return await use_case.execute(command)


__all__ = [
    "COGSCalculationCommand",
    "COGSCalculationUseCase",
    "COGSMethod",
    "COGSResult",
    "cogs_calculation_handler",
]
