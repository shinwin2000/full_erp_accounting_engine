#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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
from functools import wraps
from typing import Any
from uuid import UUID

from application.commands_cqrs.command_bus_unified import BaseCommand, CommandResult
from application.service_layer.service_inventory import InventoryService
from application.service_layer.service_journal import JournalService
from application.service_layer.service_manufacturing import ManufacturingService
from application.service_layer.service_fiscal_period import FiscalPeriodService
from domain.fiscal_period.aggregate_root import PeriodStatus
from kernel.sealed_gate import SealedGate
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


def transactional(method):
    @wraps(method)
    async def wrapper(self, *args, **kwargs):
        async with self._uow:
            return await method(self, *args, **kwargs)
    return wrapper


class HPPManufacturingCloseCommand(BaseCommand):
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
    def __init__(
        self,
        manufacturing_service: ManufacturingService,
        inventory_service: InventoryService,
        journal_service: JournalService,
        fiscal_period_service: FiscalPeriodService,
        uow: UnitOfWorkPort,
        sealed_gate: SealedGate | None = None,
    ):
        self._manufacturing_service = manufacturing_service
        self._inventory_service = inventory_service
        self._journal_service = journal_service
        self._period_service = fiscal_period_service
        self._uow = uow
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    @transactional
    async def execute(self, command: HPPManufacturingCloseCommand) -> CommandResult:
        self._stats["executed"] += 1
        period_year = command.period_end.year
        period_month = command.period_end.month
        period_str = f"{period_year}-{period_month:02d}"

        try:
            # ========== VALIDATION: Period must be OPEN for posting ==========
            period = await self._period_service.get_period(
                command.legal_entity_id, period_year, period_month
            )
            if not period:
                raise ValueError(f"Period {period_str} does not exist")
            if command.post_to_gl and period.status != PeriodStatus.OPEN.value:
                raise ValueError(
                    f"Cannot post COGM journal: period {period_str} is {period.status}. "
                    "Period must be OPEN."
                )

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
                product_costs.append({
                    "product_id": str(wo.product_id),
                    "product_code": wo.product_code,
                    "quantity": float(wo.completed_quantity),
                    "unit_cost": float(costs.total_cost / wo.completed_quantity) if wo.completed_quantity > 0 else 0,
                    "total_cost": float(costs.total_cost),
                })

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

            # ========== VALIDATION: Period must be OPEN or LOCKED to close ==========
            period = await self._period_service.get_period(
                command.legal_entity_id, period_year, period_month
            )
            if not period:
                raise ValueError(f"Period {period_str} not found")
            if period.status not in (PeriodStatus.OPEN.value, PeriodStatus.LOCKED.value):
                raise ValueError(
                    f"Cannot close period {period_str}: status is {period.status}. "
                    "Must be OPEN or LOCKED."
                )

            await self._manufacturing_service.close_period(
                command.legal_entity_id,
                period_str,
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
        period_year = journal_date.year
        period_month = journal_date.month
        period_str = f"{period_year}-{period_month:02d}"

        # ========== VALIDATION: Period must be OPEN ==========
        period = await self._period_service.get_period(
            legal_entity_id, period_year, period_month
        )
        if not period:
            raise ValueError(f"Period {period_str} does not exist")
        if period.status != PeriodStatus.OPEN.value:
            raise ValueError(
                f"Cannot post COGM journal: period {period_str} is {period.status}. "
                "Period must be OPEN."
            )

        finished_goods_account = "1-1300"
        wip_account = "1-1200"
        lines = [
            {"account_code": finished_goods_account, "debit": cogm, "credit": Decimal("0"), "description": "COGM transfer from WIP"},
            {"account_code": wip_account, "debit": Decimal("0"), "credit": cogm, "description": "Reduce WIP"},
        ]
        journal_id = await self._journal_service.post_journal(
            legal_entity_id=legal_entity_id,
            journal_date=journal_date,
            period=period_str,
            description=f"COGM closing for period {journal_date}",
            lines=lines,
            source_system="manufacturing",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        logger.info(f"COGM journal {journal_id} posted to period {period_str}")
        return journal_id

    def get_stats(self) -> dict[str, int]:
        return self._stats


async def hpp_manufacturing_close_handler(
    command: BaseCommand, use_case: HPPManufacturingCloseUseCase
) -> CommandResult:
    """
    Handler untuk HPPManufacturingCloseCommand.
    Memastikan command yang diterima adalah HPPManufacturingCloseCommand.
    Validasi period status dilakukan di sini dan di use_case.execute().
    """
    if not isinstance(command, HPPManufacturingCloseCommand):
        raise TypeError(f"Expected HPPManufacturingCloseCommand, got {type(command)}")

    # ========== VALIDATION: Period must be OPEN or LOCKED before closing ==========
    period_year = command.period_end.year
    period_month = command.period_end.month
    period_str = f"{period_year}-{period_month:02d}"

    period = await use_case._period_service.get_period(
        command.legal_entity_id, period_year, period_month
    )
    if not period:
        raise ValueError(f"Period {period_str} does not exist")

    # If post_to_gl is True, period must be OPEN for posting
    if command.post_to_gl and period.status != PeriodStatus.OPEN.value:
        raise ValueError(
            f"Cannot post COGM journal: period {period_str} is {period.status}. "
            "Period must be OPEN."
        )

    # For closing, period must be OPEN or LOCKED
    if period.status not in (PeriodStatus.OPEN.value, PeriodStatus.LOCKED.value):
        raise ValueError(
            f"Cannot close period {period_str}: status is {period.status}. "
            "Must be OPEN or LOCKED."
        )

    return await use_case.execute(command)


__all__ = [
    "HPPManufacturingCloseCommand",
    "HPPManufacturingCloseUseCase",
    "HPPResult",
    "hpp_manufacturing_close_handler",
]