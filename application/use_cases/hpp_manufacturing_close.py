#!/usr/bin/env python3

"""
Module: hpp_manufacturing_close.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk menghitung dan menutup Harga Pokok Produksi (HPP) di akhir periode manufaktur.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any
from uuid import UUID

from application.commands_cqrs.command_bus_unified import BaseCommand, CommandResult
from application.service_layer.service_inventory import InventoryService
from application.service_layer.service_journal import JournalService
from application.service_layer.service_manufacturing import ManufacturingService
from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


class HPPManufacturingCloseCommand(BaseCommand):
    """Command untuk close HPP manufaktur."""

    __slots__ = ("dry_run", "legal_entity_id", "period_end", "period_start", "post_to_gl")

    def __init__(
        self,
        legal_entity_id: UUID,
        period_start: date,
        period_end: date,
        post_to_gl: bool = True,
        dry_run: bool = False,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="HPPManufacturingCloseCommand",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        self.legal_entity_id = legal_entity_id
        self.period_start = period_start
        self.period_end = period_end
        self.post_to_gl = post_to_gl
        self.dry_run = dry_run

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "legal_entity_id": str(self.legal_entity_id),
                "period_start": self.period_start.isoformat(),
                "period_end": self.period_end.isoformat(),
                "post_to_gl": self.post_to_gl,
                "dry_run": self.dry_run,
            }
        )
        return data


class HPPResult:
    def __init__(
        self,
        total_material_cost: Decimal,
        total_labor_cost: Decimal,
        total_overhead_cost: Decimal,
        total_manufacturing_cost: Decimal,
        beginning_wip: Decimal,
        ending_wip: Decimal,
        cogm: Decimal,
        journal_id: UUID | None,
        product_costs: list[dict[str, Any]],
    ):
        self.total_material_cost = total_material_cost
        self.total_labor_cost = total_labor_cost
        self.total_overhead_cost = total_overhead_cost
        self.total_manufacturing_cost = total_manufacturing_cost
        self.beginning_wip = beginning_wip
        self.ending_wip = ending_wip
        self.cogm = cogm
        self.journal_id = journal_id
        self.product_costs = product_costs


class HPPManufacturingCloseUseCase:
    """
    Use case untuk close HPP manufaktur.
    """

    def __init__(
        self,
        manufacturing_service: ManufacturingService,
        inventory_service: InventoryService,
        journal_service: JournalService,
        sealed_gate: SealedGate | None = None,
    ):
        self._manufacturing_service = manufacturing_service
        self._inventory_service = inventory_service
        self._journal_service = journal_service
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: HPPManufacturingCloseCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            completed_work_orders = await self._manufacturing_service.get_completed_work_orders(
                command.legal_entity_id, command.period_start, command.period_end
            )

            total_material = Decimal("0")
            total_labor = Decimal("0")
            total_overhead = Decimal("0")
            product_costs = []

            for wo in completed_work_orders:
                costs = await self._manufacturing_service.get_work_order_costs(wo.id)
                total_material += costs.material_cost
                total_labor += costs.labor_cost
                total_overhead += costs.overhead_cost
                product_costs.append(
                    {
                        "product_id": str(wo.product_id),
                        "product_code": wo.product_code,
                        "quantity": float(wo.completed_quantity),
                        "unit_cost": float(costs.total_cost / wo.completed_quantity)
                        if wo.completed_quantity > 0
                        else 0,
                        "total_cost": float(costs.total_cost),
                    }
                )

            total_manufacturing_cost = total_material + total_labor + total_overhead
            beginning_wip = await self._manufacturing_service.get_wip_value(
                command.legal_entity_id, as_of_date=command.period_start - timedelta(days=1)
            )
            ending_wip = await self._manufacturing_service.get_wip_value(
                command.legal_entity_id, as_of_date=command.period_end
            )
            cogm = beginning_wip + total_manufacturing_cost - ending_wip
            cogm = cogm.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

            if command.dry_run:
                return CommandResult.success(
                    command_id=command.command_id,
                    data={
                        "dry_run": True,
                        "total_material_cost": float(total_material),
                        "total_labor_cost": float(total_labor),
                        "total_overhead_cost": float(total_overhead),
                        "total_manufacturing_cost": float(total_manufacturing_cost),
                        "beginning_wip": float(beginning_wip),
                        "ending_wip": float(ending_wip),
                        "cogm": float(cogm),
                        "product_costs": product_costs,
                    },
                )

            journal_id = None
            if command.post_to_gl and cogm != 0:
                journal_id = await self._post_cogm_journal(
                    command.legal_entity_id,
                    cogm,
                    ending_wip,
                    command.period_end,
                    command.user_id,
                    command.correlation_id,
                )

            for pc in product_costs:
                await self._manufacturing_service.update_cost_card(
                    product_id=UUID(pc["product_id"]),
                    period=f"{command.period_end.year}-{command.period_end.month:02d}",
                    unit_cost=Decimal(str(pc["unit_cost"])),
                    total_cost=Decimal(str(pc["total_cost"])),
                    user_id=command.user_id,
                )

            await self._manufacturing_service.close_period(
                command.legal_entity_id,
                f"{command.period_end.year}-{command.period_end.month:02d}",
                command.user_id,
            )

            result = HPPResult(
                total_material_cost=total_material,
                total_labor_cost=total_labor,
                total_overhead_cost=total_overhead,
                total_manufacturing_cost=total_manufacturing_cost,
                beginning_wip=beginning_wip,
                ending_wip=ending_wip,
                cogm=cogm,
                journal_id=journal_id,
                product_costs=product_costs,
            )

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "total_material_cost": float(result.total_material_cost),
                    "total_labor_cost": float(result.total_labor_cost),
                    "total_overhead_cost": float(result.total_overhead_cost),
                    "total_manufacturing_cost": float(result.total_manufacturing_cost),
                    "beginning_wip": float(result.beginning_wip),
                    "ending_wip": float(result.ending_wip),
                    "cogm": float(result.cogm),
                    "journal_id": str(result.journal_id) if result.journal_id else None,
                    "product_costs": result.product_costs,
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"HPP manufacturing close failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="HPP_MANUFACTURING_ERROR"
            )

    async def _post_cogm_journal(
        self,
        legal_entity_id: UUID,
        cogm: Decimal,
        ending_wip: Decimal,
        journal_date: date,
        user_id: UUID,
        correlation_id: str | None,
    ) -> UUID:
        finished_goods_account = "1-1300"
        wip_account = "1-1200"
        lines = [
            {
                "account_code": finished_goods_account,
                "debit": cogm,
                "credit": Decimal("0"),
                "description": "COGM transfer from WIP",
            },
            {
                "account_code": wip_account,
                "debit": Decimal("0"),
                "credit": cogm,
                "description": "Reduce WIP",
            },
        ]
        journal_id = await self._journal_service.post_journal(
            legal_entity_id=legal_entity_id,
            journal_date=journal_date,
            period=f"{journal_date.year}-{journal_date.month:02d}",
            description=f"COGM closing for period {journal_date}",
            lines=lines,
            source_system="manufacturing",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        return journal_id

    def get_stats(self) -> dict[str, int]:
        return self._stats


# ============================================================================
# Handler dengan dependency injection
# ============================================================================


async def hpp_manufacturing_close_handler(
    command: BaseCommand, use_case: HPPManufacturingCloseUseCase
) -> CommandResult:
    if not isinstance(command, HPPManufacturingCloseCommand):
        raise TypeError(f"Expected HPPManufacturingCloseCommand, got {type(command)}")
    return await use_case.execute(command)


__all__ = [
    "HPPManufacturingCloseCommand",
    "HPPManufacturingCloseUseCase",
    "HPPResult",
    "hpp_manufacturing_close_handler",
]
