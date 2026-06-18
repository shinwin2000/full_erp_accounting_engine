#!/usr/bin/env python3

"""
Module: manufacturing_cost_flow.py

Layer: 8 - Application / Workflows

Responsibility:
    Workflow untuk aliran biaya manufaktur (cost flow) dari bahan baku hingga barang jadi.
    Mencakup:
    - Pencatatan pembelian bahan baku
    - Pengeluaran bahan baku ke produksi (WIP)
    - Pencatatan biaya tenaga kerja langsung
    - Alokasi biaya overhead pabrik
    - Transfer biaya dari WIP ke barang jadi
    - Perhitungan HPP (Harga Pokok Penjualan) saat barang dijual

Dependencies:
    - application/service_layer/service_inventory.py (InventoryService)
    - application/service_layer/service_manufacturing.py (ManufacturingService)
    - application/service_layer/service_journal.py (JournalService)
    - application/sagas/manufacturing_saga.py (ManufacturingSagaOrchestrator)
    - application/commands_cqrs/command_bus_unified.py (Command, CommandResult)

Audit:
    Seluruh aliran biaya dicatat dengan correlation ID.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from application.commands_cqrs.command_bus_unified import Command, CommandResult

if TYPE_CHECKING:
    from datetime import date
    from uuid import UUID

    from application.sagas.manufacturing_saga import ManufacturingSagaOrchestrator
    from application.service_layer.service_inventory import InventoryService
    from application.service_layer.service_journal import JournalService
    from application.service_layer.service_manufacturing import ManufacturingService
    from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


class ManufacturingCostFlowCommand(Command):
    """Command untuk workflow aliran biaya manufaktur."""

    __slots__ = (
        "auto_post_journal",
        "calculate_actual_cost",
        "dry_run",
        "legal_entity_id",
        "period_end",
        "period_start",
        "work_order_ids",
    )

    def __init__(
        self,
        legal_entity_id: UUID,
        period_start: date,
        period_end: date,
        work_order_ids: list[UUID] | None = None,
        auto_post_journal: bool = True,
        calculate_actual_cost: bool = True,
        dry_run: bool = False,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="ManufacturingCostFlowCommand",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        self.legal_entity_id = legal_entity_id
        self.period_start = period_start
        self.period_end = period_end
        self.work_order_ids = work_order_ids or []
        self.auto_post_journal = auto_post_journal
        self.calculate_actual_cost = calculate_actual_cost
        self.dry_run = dry_run

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "legal_entity_id": str(self.legal_entity_id),
                "period_start": self.period_start.isoformat(),
                "period_end": self.period_end.isoformat(),
                "work_order_ids": [str(woid) for woid in self.work_order_ids],
                "auto_post_journal": self.auto_post_journal,
                "calculate_actual_cost": self.calculate_actual_cost,
                "dry_run": self.dry_run,
            }
        )
        return data


class ManufacturingCostFlowResult:
    def __init__(
        self,
        total_raw_material_issued: Decimal,
        total_labor_cost: Decimal,
        total_overhead_cost: Decimal,
        total_wip_transferred: Decimal,
        total_cogs: Decimal,
        journal_ids: list[UUID],
        work_orders_processed: int,
        message: str,
    ):
        self.total_raw_material_issued = total_raw_material_issued
        self.total_labor_cost = total_labor_cost
        self.total_overhead_cost = total_overhead_cost
        self.total_wip_transferred = total_wip_transferred
        self.total_cogs = total_cogs
        self.journal_ids = journal_ids
        self.work_orders_processed = work_orders_processed
        self.message = message


class ManufacturingCostFlowWorkflow:
    """
    Workflow untuk aliran biaya manufaktur.
    """

    def __init__(
        self,
        inventory_service: InventoryService,
        manufacturing_service: ManufacturingService,
        journal_service: JournalService,
        saga_orchestrator: ManufacturingSagaOrchestrator,
        sealed_gate: SealedGate | None = None,
    ):
        self._inventory_service = inventory_service
        self._manufacturing_service = manufacturing_service
        self._journal_service = journal_service
        self._saga = saga_orchestrator
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: ManufacturingCostFlowCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            # Start saga
            saga_context = await self._saga.start_manufacturing_cost_flow(
                legal_entity_id=command.legal_entity_id,
                period_start=command.period_start,
                period_end=command.period_end,
                work_order_ids=command.work_order_ids,
                user_id=command.user_id,
                correlation_id=command.correlation_id,
            )

            async def _run_workflow():
                # Step 1: Get work orders in period
                if command.work_order_ids:
                    work_orders = []
                    for woid in command.work_order_ids:
                        wo = await self._manufacturing_service.get_work_order(woid)
                        if wo:
                            work_orders.append(wo)
                else:
                    work_orders = await self._manufacturing_service.list_work_orders(
                        legal_entity_id=command.legal_entity_id,
                        from_date=command.period_start,
                        to_date=command.period_end,
                        status="COMPLETED",
                    )

                if not work_orders:
                    return ManufacturingCostFlowResult(
                        total_raw_material_issued=Decimal("0"),
                        total_labor_cost=Decimal("0"),
                        total_overhead_cost=Decimal("0"),
                        total_wip_transferred=Decimal("0"),
                        total_cogs=Decimal("0"),
                        journal_ids=[],
                        work_orders_processed=0,
                        message="No work orders found in period",
                    )

                # Step 2: Calculate totals
                total_raw_material = Decimal("0")
                total_labor = Decimal("0")
                total_overhead = Decimal("0")
                total_wip = Decimal("0")
                total_cogs = Decimal("0")
                journal_ids = []

                for wo in work_orders:
                    # Get BOM components
                    bom = await self._manufacturing_service.get_bom_by_work_order(wo.id)
                    if not bom:
                        continue

                    # Issue raw materials
                    material_cost = Decimal("0")
                    for item in bom.items:
                        component = await self._inventory_service.get_item(item.component_id)
                        if component:
                            qty_needed = (
                                item.quantity * wo.quantity * (1 + item.scrap_percentage / 100)
                            )
                            if component.current_stock >= qty_needed:
                                movement = await self._inventory_service.issue_material(
                                    item_id=item.component_id,
                                    quantity=qty_needed,
                                    reference=f"WO-{wo.work_order_number}",
                                    user_id=command.user_id,
                                )
                                material_cost += movement.total_value

                    total_raw_material += material_cost

                    # Labor cost
                    labor_cost = await self._manufacturing_service.get_work_order_labor_cost(wo.id)
                    total_labor += labor_cost

                    # Overhead
                    overhead_rate = await self._manufacturing_service.get_overhead_rate(
                        command.legal_entity_id
                    )
                    overhead_cost = labor_cost * overhead_rate
                    total_overhead += overhead_cost

                    # Total WIP
                    wo_total_wip = material_cost + labor_cost + overhead_cost
                    total_wip += wo_total_wip

                    # Transfer to finished goods if completed
                    if wo.status == "COMPLETED":
                        finished_goods_value = wo_total_wip
                        await self._inventory_service.receive_finished_goods(
                            item_id=wo.product_id,
                            quantity=wo.completed_quantity,
                            unit_cost=(
                                finished_goods_value / wo.completed_quantity
                                if wo.completed_quantity > 0
                                else Decimal("0")
                            ),
                            reference=f"WO-{wo.work_order_number}",
                            user_id=command.user_id,
                        )

                    # COGS for sold goods
                    sold_qty = await self._manufacturing_service.get_sold_quantity(
                        wo.product_id, command.period_start, command.period_end
                    )
                    if sold_qty > 0:
                        unit_cost = wo_total_wip / wo.quantity if wo.quantity > 0 else Decimal("0")
                        cogs_amount = unit_cost * sold_qty
                        total_cogs += cogs_amount

                # Step 3: Post journals if enabled
                if command.auto_post_journal and not command.dry_run:
                    if total_raw_material > 0:
                        jid1 = await self._post_material_issue_journal(command, total_raw_material)
                        if jid1:
                            journal_ids.append(jid1)
                    if total_labor > 0:
                        jid2 = await self._post_labor_journal(command, total_labor)
                        if jid2:
                            journal_ids.append(jid2)
                    if total_overhead > 0:
                        jid3 = await self._post_overhead_journal(command, total_overhead)
                        if jid3:
                            journal_ids.append(jid3)
                    if total_wip > 0:
                        jid4 = await self._post_wip_transfer_journal(command, total_wip)
                        if jid4:
                            journal_ids.append(jid4)
                    if total_cogs > 0:
                        jid5 = await self._post_cogs_journal(command, total_cogs)
                        if jid5:
                            journal_ids.append(jid5)

                await self._saga.complete(saga_context.saga_id)

                return ManufacturingCostFlowResult(
                    total_raw_material_issued=total_raw_material,
                    total_labor_cost=total_labor,
                    total_overhead_cost=total_overhead,
                    total_wip_transferred=total_wip,
                    total_cogs=total_cogs,
                    journal_ids=journal_ids,
                    work_orders_processed=len(work_orders),
                    message=f"Manufacturing cost flow completed. WIP: {total_wip}, COGS: {total_cogs}",
                )

            if command.dry_run:
                return CommandResult.success(
                    command_id=command.command_id,
                    data={"dry_run": True, "message": "Dry run completed, check logs for details"},
                )

            if self._sealed_gate:
                result = await self._sealed_gate.execute(
                    command_type=command.command_type,
                    command_id=command.command_id,
                    handler=_run_workflow,
                )
            else:
                result = await _run_workflow()

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "total_raw_material_issued": float(result.total_raw_material_issued),
                    "total_labor_cost": float(result.total_labor_cost),
                    "total_overhead_cost": float(result.total_overhead_cost),
                    "total_wip_transferred": float(result.total_wip_transferred),
                    "total_cogs": float(result.total_cogs),
                    "journal_ids": [str(jid) for jid in result.journal_ids],
                    "work_orders_processed": result.work_orders_processed,
                    "message": result.message,
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"Manufacturing cost flow failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id,
                error=str(e),
                error_code="MANUFACTURING_COST_FLOW_ERROR",
            )

    async def _post_material_issue_journal(
        self, command: ManufacturingCostFlowCommand, amount: Decimal
    ) -> UUID | None:
        raw_material_account = "1-1200"
        wip_account = "1-1300"
        lines = [
            {
                "account_code": wip_account,
                "debit": amount,
                "credit": Decimal("0"),
                "description": "Raw material to WIP",
            },
            {
                "account_code": raw_material_account,
                "debit": Decimal("0"),
                "credit": amount,
                "description": "Issue raw material",
            },
        ]
        return await self._journal_service.post_journal(
            legal_entity_id=command.legal_entity_id,
            journal_date=command.period_end,
            period=f"{command.period_end.year}-{command.period_end.month:02d}",
            description=f"Raw material issued to WIP for period {command.period_start} to {command.period_end}",
            lines=lines,
            source_system="manufacturing",
            user_id=command.user_id,
            correlation_id=command.correlation_id,
        )

    async def _post_labor_journal(
        self, command: ManufacturingCostFlowCommand, amount: Decimal
    ) -> UUID | None:
        labor_account = "5-5100"
        wip_account = "1-1300"
        lines = [
            {
                "account_code": wip_account,
                "debit": amount,
                "credit": Decimal("0"),
                "description": "Direct labor to WIP",
            },
            {
                "account_code": labor_account,
                "debit": Decimal("0"),
                "credit": amount,
                "description": "Direct labor expense",
            },
        ]
        return await self._journal_service.post_journal(
            legal_entity_id=command.legal_entity_id,
            journal_date=command.period_end,
            period=f"{command.period_end.year}-{command.period_end.month:02d}",
            description="Direct labor cost allocation",
            lines=lines,
            source_system="manufacturing",
            user_id=command.user_id,
            correlation_id=command.correlation_id,
        )

    async def _post_overhead_journal(
        self, command: ManufacturingCostFlowCommand, amount: Decimal
    ) -> UUID | None:
        overhead_account = "5-5200"
        wip_account = "1-1300"
        lines = [
            {
                "account_code": wip_account,
                "debit": amount,
                "credit": Decimal("0"),
                "description": "Overhead to WIP",
            },
            {
                "account_code": overhead_account,
                "debit": Decimal("0"),
                "credit": amount,
                "description": "Overhead expense",
            },
        ]
        return await self._journal_service.post_journal(
            legal_entity_id=command.legal_entity_id,
            journal_date=command.period_end,
            period=f"{command.period_end.year}-{command.period_end.month:02d}",
            description="Overhead allocation to WIP",
            lines=lines,
            source_system="manufacturing",
            user_id=command.user_id,
            correlation_id=command.correlation_id,
        )

    async def _post_wip_transfer_journal(
        self, command: ManufacturingCostFlowCommand, amount: Decimal
    ) -> UUID | None:
        finished_goods_account = "1-1400"
        wip_account = "1-1300"
        lines = [
            {
                "account_code": finished_goods_account,
                "debit": amount,
                "credit": Decimal("0"),
                "description": "Finished goods from WIP",
            },
            {
                "account_code": wip_account,
                "debit": Decimal("0"),
                "credit": amount,
                "description": "Transfer from WIP",
            },
        ]
        return await self._journal_service.post_journal(
            legal_entity_id=command.legal_entity_id,
            journal_date=command.period_end,
            period=f"{command.period_end.year}-{command.period_end.month:02d}",
            description="Transfer WIP to Finished Goods",
            lines=lines,
            source_system="manufacturing",
            user_id=command.user_id,
            correlation_id=command.correlation_id,
        )

    async def _post_cogs_journal(
        self, command: ManufacturingCostFlowCommand, amount: Decimal
    ) -> UUID | None:
        cogs_account = "5-5000"
        finished_goods_account = "1-1400"
        lines = [
            {
                "account_code": cogs_account,
                "debit": amount,
                "credit": Decimal("0"),
                "description": "Cost of Goods Sold",
            },
            {
                "account_code": finished_goods_account,
                "debit": Decimal("0"),
                "credit": amount,
                "description": "Reduce finished goods",
            },
        ]
        return await self._journal_service.post_journal(
            legal_entity_id=command.legal_entity_id,
            journal_date=command.period_end,
            period=f"{command.period_end.year}-{command.period_end.month:02d}",
            description="COGS for period",
            lines=lines,
            source_system="manufacturing",
            user_id=command.user_id,
            correlation_id=command.correlation_id,
        )

    def get_stats(self) -> dict[str, int]:
        return self._stats


# ============================================================================
# Factory function
# ============================================================================


def create_manufacturing_cost_flow_workflow(
    inventory_service: InventoryService,
    manufacturing_service: ManufacturingService,
    journal_service: JournalService,
    saga_orchestrator: ManufacturingSagaOrchestrator,
    sealed_gate: SealedGate | None = None,
) -> ManufacturingCostFlowWorkflow:
    """Factory untuk membuat workflow manufacturing cost flow."""
    return ManufacturingCostFlowWorkflow(
        inventory_service=inventory_service,
        manufacturing_service=manufacturing_service,
        journal_service=journal_service,
        saga_orchestrator=saga_orchestrator,
        sealed_gate=sealed_gate,
    )


__all__ = [
    "ManufacturingCostFlowCommand",
    "ManufacturingCostFlowResult",
    "ManufacturingCostFlowWorkflow",
    "create_manufacturing_cost_flow_workflow",
]
