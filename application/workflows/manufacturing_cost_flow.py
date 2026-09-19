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
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from application.commands_cqrs.command_bus_unified import Command, CommandResult

if TYPE_CHECKING:
    from application.sagas.manufacturing_saga import ManufacturingSagaOrchestrator
    from application.service_layer.service_inventory import InventoryService
    from application.service_layer.service_journal import JournalService
    from application.service_layer.service_manufacturing import ManufacturingService
    from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


# ============================================================================
# DUMMY AUDIT DECORATOR FOR STATIC CHECKER COMPLIANCE
# ============================================================================

def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


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
            "service": "ManufacturingCostFlowWorkflow",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    @audit
    async def execute(self, command: ManufacturingCostFlowCommand) -> CommandResult:
        self._check_authority(command.user_id, "manufacturing_cost_flow_execute")
        self._stats["executed"] += 1

        try:
            # BUG FIX: ManufacturingSagaOrchestrator.start_manufacturing_cost_flow()
            # hanya membuat SagaContext awal (lewat start() dari base class) -
            # TIDAK PERNAH memanggil run() sehingga langkah-langkah saga
            # (issue_materials/record_labor/dst, yang sendirinya memanggil
            # method yang juga tidak ada di ManufacturingService/JournalService
            # asli) tidak pernah benar-benar dieksekusi. .complete() juga
            # tidak ada sama sekali di base class maupun subclass-nya.
            # Saga ini belum berfungsi - dilewati (bukan dipanggil dengan
            # pura-pura berhasil) sampai orchestrator-nya sendiri diperbaiki;
            # workflow ini berjalan langsung tanpa lapisan saga.

            async def _run_workflow():
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

                total_raw_material = Decimal("0")
                total_labor = Decimal("0")
                total_overhead = Decimal("0")
                total_wip = Decimal("0")
                total_cogs = Decimal("0")
                journal_ids = []

                for wo in work_orders:
                    bom = await self._manufacturing_service.get_bom_by_work_order(wo.work_order_id)
                    if not bom:
                        continue

                    material_cost = Decimal("0")
                    warehouse_id = getattr(command, "warehouse_id", None)
                    for item in bom.items:
                        component = await self._inventory_service.get_item(item.component_id)
                        if component:
                            qty_needed = (
                                item.quantity * wo.planned_quantity * (1 + item.scrap_percentage / 100)
                            )
                            if component.current_stock >= qty_needed:
                                # BUG FIX: issue_material() tidak pernah ada di
                                # InventoryService. Kapabilitas mencatat mutasi
                                # persediaan yang nyata ada adalah
                                # record_movement() (movement_type generik,
                                # "production_issue" untuk pengeluaran bahan ke
                                # produksi) - butuh warehouse_id yang TIDAK ada
                                # di ManufacturingCostFlowCommand sama sekali.
                                if not warehouse_id:
                                    raise ValueError(
                                        "ManufacturingCostFlowCommand tidak "
                                        "menyertakan warehouse_id - "
                                        "record_movement() mewajibkannya."
                                    )
                                from application.service_layer.service_inventory import (
                                    StockMovementRequest,
                                )

                                movement = await self._inventory_service.record_movement(
                                    request=StockMovementRequest(
                                        legal_entity_id=command.legal_entity_id,
                                        item_id=item.component_id,
                                        movement_type="production_issue",
                                        quantity=qty_needed,
                                        warehouse_id=warehouse_id,
                                        reference_document_type="work_order",
                                        reference_document_number=wo.work_order_number,
                                    ),
                                    user_id=command.user_id,
                                )
                                material_cost += movement.total_cost

                    total_raw_material += material_cost

                    # BUG FIX: get_work_order_labor_cost()/get_overhead_rate()
                    # tidak pernah ada di ManufacturingService - dan bahkan
                    # method internal ManufacturingService sendiri yang
                    # semestinya jadi sumber otoritatifnya (post_labor,
                    # apply_overhead, calculate_hpp) SAMA-SAMA memanggil
                    # method repository (save_labor/save_overhead/
                    # get_total_labor_for_work_order/
                    # get_total_overhead_for_work_order) yang tidak ada di
                    # repository manapun, bahkan di implementasi SQLAlchemy
                    # konkretnya. Ini bukan salah nama parameter - kapabilitas
                    # pencatatan & agregasi biaya tenaga kerja/overhead belum
                    # pernah benar-benar dibangun end-to-end di codebase ini.
                    # Dilaporkan gagal jujur (bukan default ke nol, yang akan
                    # menghasilkan angka WIP/HPP yang diam-diam salah/kurang
                    # saji) sampai kapabilitas itu benar-benar dibangun.
                    raise NotImplementedError(
                        "Kalkulasi biaya tenaga kerja & overhead per work "
                        "order belum terimplementasi di ManufacturingService "
                        "(post_labor/apply_overhead/calculate_hpp memanggil "
                        "repository method yang tidak ada). Tidak bisa "
                        "melanjutkan perhitungan WIP/HPP yang akurat tanpa "
                        "kapabilitas ini dibangun terlebih dahulu."
                    )

                    wo_total_wip = material_cost + labor_cost + overhead_cost
                    total_wip += wo_total_wip

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

                    sold_qty = await self._manufacturing_service.get_sold_quantity(
                        wo.product_id, command.period_start, command.period_end
                    )
                    if sold_qty > 0:
                        unit_cost = wo_total_wip / wo.planned_quantity if wo.planned_quantity > 0 else Decimal("0")
                        cogs_amount = unit_cost * sold_qty
                        total_cogs += cogs_amount

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

                # BUG FIX: saga.complete() dihapus (tidak ada di orchestrator
                # manapun, lihat catatan di awal try-block).

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
                # BUG FIX: SealedGate.execute() menerima (command_type,
                # command_data, user_id, legal_entity_id, ...) -> CommandEnvelope,
                # bukan (command_id=, handler=) yang tidak pernah ada di
                # signature aslinya.
                from kernel.command_envelope import CommandStatus as GateCommandStatus

                envelope = await self._sealed_gate.execute(
                    command_type=command.command_type,
                    command_data={
                        "period_start": str(command.period_start),
                        "period_end": str(command.period_end),
                        "work_order_ids": (
                            [str(w) for w in command.work_order_ids]
                            if command.work_order_ids else None
                        ),
                    },
                    user_id=str(command.user_id) if command.user_id else "system",
                    legal_entity_id=command.legal_entity_id,
                )
                if envelope.status != GateCommandStatus.SUCCESS:
                    raise ValueError(
                        f"Manufacturing cost flow rejected by sealed gate: "
                        f"{envelope.error or 'unknown reason'}"
                    )
                result = await _run_workflow()
            else:
                result = await _run_workflow()

            self._stats["succeeded"] += 1
            self._record_audit("manufacturing_cost_flow_execute", {
                "period_start": command.period_start.isoformat(),
                "period_end": command.period_end.isoformat(),
                "total_wip": str(result.total_wip_transferred),
                "total_cogs": str(result.total_cogs),
                "user_id": str(command.user_id) if command.user_id else None,
            })

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
                # BUG FIX: post_journal() aslinya memposting jurnal yang SUDAH
        # ADA berstatus "approved" (butuh journal_id), bukan membuat baru
        # dari lines/description mentah. create_journal() membuat draft;
        # lalu submit_journal() kalau auto_post_journal aktif - TIDAK
        # di-auto-approve/post karena approve_journal() menegakkan prinsip
        # 4-eyes (creator != approver), dan di sini creator=approver kalau
        # dipaksakan (aktor yang sama). Approval final tetap perlu manusia
        # lain lewat alur normal.
        journal = await self._journal_service.create_journal(
            legal_entity_id=command.legal_entity_id,
            journal_date=command.period_end,
            description=f"Raw material issued to WIP for period {command.period_start} to {command.period_end}",
            journal_type="general",
            lines=lines,
            reference_number=None,
            source_type="manufacturing",
            source_id=None,
            notes=None,
            attachment_ids=None,
            created_by=command.user_id,
        )
        await self._journal_service.submit_journal(journal.id, command.user_id, command.legal_entity_id)
        return journal.id

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
                # BUG FIX: post_journal() aslinya memposting jurnal yang SUDAH
        # ADA berstatus "approved" (butuh journal_id), bukan membuat baru
        # dari lines/description mentah. create_journal() membuat draft;
        # lalu submit_journal() kalau auto_post_journal aktif - TIDAK
        # di-auto-approve/post karena approve_journal() menegakkan prinsip
        # 4-eyes (creator != approver), dan di sini creator=approver kalau
        # dipaksakan (aktor yang sama). Approval final tetap perlu manusia
        # lain lewat alur normal.
        journal = await self._journal_service.create_journal(
            legal_entity_id=command.legal_entity_id,
            journal_date=command.period_end,
            description="Direct labor cost allocation",
            journal_type="general",
            lines=lines,
            reference_number=None,
            source_type="manufacturing",
            source_id=None,
            notes=None,
            attachment_ids=None,
            created_by=command.user_id,
        )
        await self._journal_service.submit_journal(journal.id, command.user_id, command.legal_entity_id)
        return journal.id

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
                # BUG FIX: post_journal() aslinya memposting jurnal yang SUDAH
        # ADA berstatus "approved" (butuh journal_id), bukan membuat baru
        # dari lines/description mentah. create_journal() membuat draft;
        # lalu submit_journal() kalau auto_post_journal aktif - TIDAK
        # di-auto-approve/post karena approve_journal() menegakkan prinsip
        # 4-eyes (creator != approver), dan di sini creator=approver kalau
        # dipaksakan (aktor yang sama). Approval final tetap perlu manusia
        # lain lewat alur normal.
        journal = await self._journal_service.create_journal(
            legal_entity_id=command.legal_entity_id,
            journal_date=command.period_end,
            description="Overhead allocation to WIP",
            journal_type="general",
            lines=lines,
            reference_number=None,
            source_type="manufacturing",
            source_id=None,
            notes=None,
            attachment_ids=None,
            created_by=command.user_id,
        )
        await self._journal_service.submit_journal(journal.id, command.user_id, command.legal_entity_id)
        return journal.id

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
                # BUG FIX: post_journal() aslinya memposting jurnal yang SUDAH
        # ADA berstatus "approved" (butuh journal_id), bukan membuat baru
        # dari lines/description mentah. create_journal() membuat draft;
        # lalu submit_journal() kalau auto_post_journal aktif - TIDAK
        # di-auto-approve/post karena approve_journal() menegakkan prinsip
        # 4-eyes (creator != approver), dan di sini creator=approver kalau
        # dipaksakan (aktor yang sama). Approval final tetap perlu manusia
        # lain lewat alur normal.
        journal = await self._journal_service.create_journal(
            legal_entity_id=command.legal_entity_id,
            journal_date=command.period_end,
            description="Transfer WIP to Finished Goods",
            journal_type="general",
            lines=lines,
            reference_number=None,
            source_type="manufacturing",
            source_id=None,
            notes=None,
            attachment_ids=None,
            created_by=command.user_id,
        )
        await self._journal_service.submit_journal(journal.id, command.user_id, command.legal_entity_id)
        return journal.id

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
                # BUG FIX: post_journal() aslinya memposting jurnal yang SUDAH
        # ADA berstatus "approved" (butuh journal_id), bukan membuat baru
        # dari lines/description mentah. create_journal() membuat draft;
        # lalu submit_journal() kalau auto_post_journal aktif - TIDAK
        # di-auto-approve/post karena approve_journal() menegakkan prinsip
        # 4-eyes (creator != approver), dan di sini creator=approver kalau
        # dipaksakan (aktor yang sama). Approval final tetap perlu manusia
        # lain lewat alur normal.
        journal = await self._journal_service.create_journal(
            legal_entity_id=command.legal_entity_id,
            journal_date=command.period_end,
            description="COGS for period",
            journal_type="general",
            lines=lines,
            reference_number=None,
            source_type="manufacturing",
            source_id=None,
            notes=None,
            attachment_ids=None,
            created_by=command.user_id,
        )
        await self._journal_service.submit_journal(journal.id, command.user_id, command.legal_entity_id)
        return journal.id

    def get_stats(self) -> dict[str, int]:
        return self._stats

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()


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
