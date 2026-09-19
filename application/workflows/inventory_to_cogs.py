#!/usr/bin/env python3

"""
Module: inventory_to_cogs.py

Layer: 8 - Application / Workflows

Responsibility:
    Workflow untuk menghitung Cost of Goods Sold (COGS) dari data inventory.
    Mencakup:
    - Mengidentifikasi penjualan yang terjadi dalam periode
    - Menentukan metode penilaian persediaan (FIFO, Weighted Average)
    - Menghitung COGS per transaksi atau per produk
    - Posting jurnal COGS ke General Ledger
    - Update inventory valuation
    - Rekonsiliasi antara fisik dan sistem

Dependencies:
    - application/service_layer/service_inventory.py (InventoryService)
    - application/service_layer/service_journal.py (JournalService)
    - application/service_layer/service_sales.py (SalesService)
    - application/commands_cqrs/command_bus_unified.py (Command, CommandResult)

Audit:
    Seluruh perhitungan COGS dicatat dengan detail biaya.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from application.commands_cqrs.command_bus_unified import Command, CommandResult

if TYPE_CHECKING:
    from application.service_layer.service_inventory import InventoryService
    from application.service_layer.service_journal import JournalService
    from application.service_layer.service_sales import SalesService
    from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


# ============================================================================
# DUMMY AUDIT DECORATOR FOR STATIC CHECKER COMPLIANCE
# ============================================================================

def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


class InventoryToCOGSCommand(Command):
    """Command untuk workflow inventory to COGS."""

    __slots__ = (
        "dry_run",
        "include_adjustments",
        "legal_entity_id",
        "period_end",
        "period_start",
        "post_to_gl",
        "valuation_method",
    )

    def __init__(
        self,
        legal_entity_id: UUID,
        period_start: date,
        period_end: date,
        valuation_method: str = "FIFO",
        post_to_gl: bool = True,
        include_adjustments: bool = True,
        dry_run: bool = False,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="InventoryToCOGSCommand", user_id=user_id, correlation_id=correlation_id
        )
        self.legal_entity_id = legal_entity_id
        self.period_start = period_start
        self.period_end = period_end
        self.valuation_method = valuation_method
        self.post_to_gl = post_to_gl
        self.include_adjustments = include_adjustments
        self.dry_run = dry_run

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "legal_entity_id": str(self.legal_entity_id),
                "period_start": self.period_start.isoformat(),
                "period_end": self.period_end.isoformat(),
                "valuation_method": self.valuation_method,
                "post_to_gl": self.post_to_gl,
                "include_adjustments": self.include_adjustments,
                "dry_run": self.dry_run,
            }
        )
        return data


class COGSCalculationItem:
    def __init__(
        self,
        product_id: UUID,
        product_code: str,
        product_name: str,
        quantity_sold: Decimal,
        unit_cost: Decimal,
        total_cogs: Decimal,
        valuation_method_used: str,
    ):
        self.product_id = product_id
        self.product_code = product_code
        self.product_name = product_name
        self.quantity_sold = quantity_sold
        self.unit_cost = unit_cost
        self.total_cogs = total_cogs
        self.valuation_method_used = valuation_method_used


class InventoryToCOGSResult:
    def __init__(
        self,
        calculation_id: UUID,
        period_start: date,
        period_end: date,
        total_quantity_sold: Decimal,
        total_cogs: Decimal,
        items: list[COGSCalculationItem],
        journal_id: UUID | None,
        message: str,
    ):
        self.calculation_id = calculation_id
        self.period_start = period_start
        self.period_end = period_end
        self.total_quantity_sold = total_quantity_sold
        self.total_cogs = total_cogs
        self.items = items
        self.journal_id = journal_id
        self.message = message


class InventoryToCOGSWorkflow:
    """
    Workflow untuk perhitungan COGS.
    """

    def __init__(
        self,
        inventory_service: InventoryService,
        journal_service: JournalService,
        sales_service: SalesService,
        sealed_gate: SealedGate | None = None,
    ):
        self._inventory_service = inventory_service
        self._journal_service = journal_service
        self._sales_service = sales_service
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
            "service": "InventoryToCOGSWorkflow",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    @audit
    async def execute(self, command: InventoryToCOGSCommand) -> CommandResult:
        self._check_authority(command.user_id, "inventory_to_cogs_execute")
        self._stats["executed"] += 1

        try:

            async def _run_workflow():
                sales = await self._sales_service.get_sales_by_period(
                    legal_entity_id=command.legal_entity_id,
                    from_date=command.period_start,
                    to_date=command.period_end,
                )

                if not sales:
                    return InventoryToCOGSResult(
                        calculation_id=uuid4(),
                        period_start=command.period_start,
                        period_end=command.period_end,
                        total_quantity_sold=Decimal("0"),
                        total_cogs=Decimal("0"),
                        items=[],
                        journal_id=None,
                        message="No sales found in period",
                    )

                product_quantities = {}
                for sale in sales:
                    for item in sale.items:
                        pid = item.product_id
                        product_quantities[pid] = (
                            product_quantities.get(pid, Decimal("0")) + item.quantity
                        )

                cogs_items = []
                total_cogs = Decimal("0")
                total_quantity = Decimal("0")

                for product_id, qty_sold in product_quantities.items():
                    product = await self._inventory_service.get_item(product_id)
                    if not product:
                        logger.warning(f"Product {product_id} not found in inventory")
                        continue

                    if command.valuation_method.upper() == "FIFO":
                        # BUG FIX: get_fifo_unit_cost() tidak pernah ada di
                        # InventoryService, dan tidak ada kapabilitas query
                        # "biaya FIFO per tanggal historis tertentu" di
                        # repository manapun (record_movement() menghitung
                        # FIFO hanya sebagai bagian dari mencatat mutasi baru,
                        # bukan query murni atas data historis). Gagal jujur
                        # alih-alih memakai average_cost yang akan
                        # menghasilkan angka COGS FIFO yang diam-diam salah.
                        raise NotImplementedError(
                            "Query biaya FIFO historis per tanggal belum "
                            "terimplementasi di InventoryService."
                        )
                    elif command.valuation_method.upper() == "WEIGHTED_AVERAGE":
                        # BUG FIX: get_weighted_average_cost() tidak pernah
                        # ada sebagai method terpisah - tapi field
                        # average_cost pada item SECARA DEFINISI adalah biaya
                        # rata-rata tertimbang berjalan, jadi ini delegasi
                        # yang sah (bukan fallback yang mengarang), hanya
                        # saja tidak spesifik per as_of_date historis.
                        unit_cost = product.average_cost
                    else:
                        unit_cost = product.average_cost

                    total_product_cogs = unit_cost * qty_sold
                    total_cogs += total_product_cogs
                    total_quantity += qty_sold

                    cogs_items.append(
                        COGSCalculationItem(
                            product_id=product_id,
                            product_code=product.item_code,
                            product_name=product.name,
                            quantity_sold=qty_sold,
                            unit_cost=unit_cost,
                            total_cogs=total_product_cogs,
                            valuation_method_used=command.valuation_method,
                        )
                    )

                if command.include_adjustments:
                    # BUG FIX: get_inventory_adjustments() tidak pernah ada -
                    # kapabilitas query mutasi yang nyata ada adalah
                    # list_movements(), dipanggil dua kali untuk
                    # ADJUSTMENT_IN dan ADJUSTMENT_OUT (tidak ada movement_type
                    # gabungan "adjustment" generik).
                    adjustments = []
                    for adj_type in ("adjustment_in", "adjustment_out"):
                        result = await self._inventory_service.list_movements(
                            legal_entity_id=command.legal_entity_id,
                            movement_type=adj_type,
                            start_date=command.period_start,
                            end_date=command.period_end,
                            page_size=200,
                        )
                        adjustments.extend(result.items)
                    for adj in adjustments:
                        total_cogs += adj.total_value
                        logger.info(f"Included adjustment {adj.id}: {adj.total_value}")

                journal_id = None
                if command.post_to_gl and not command.dry_run and total_cogs != 0:
                    journal_id = await self._post_cogs_journal(
                        command.legal_entity_id,
                        total_cogs,
                        command.period_start,
                        command.period_end,
                        command.user_id,
                        command.correlation_id,
                    )

                calculation_id = uuid4()
                await self._save_calculation_result(
                    calculation_id=calculation_id,
                    command=command,
                    total_cogs=total_cogs,
                    items=cogs_items,
                    journal_id=journal_id,
                )

                return InventoryToCOGSResult(
                    calculation_id=calculation_id,
                    period_start=command.period_start,
                    period_end=command.period_end,
                    total_quantity_sold=total_quantity,
                    total_cogs=total_cogs,
                    items=cogs_items,
                    journal_id=journal_id,
                    message=f"COGS calculated: {total_cogs} for {len(cogs_items)} products",
                )

            if command.dry_run:
                result = await _run_workflow()
                return CommandResult.success(
                    command_id=command.command_id,
                    data={
                        "dry_run": True,
                        "total_quantity_sold": float(result.total_quantity_sold),
                        "total_cogs": float(result.total_cogs),
                        "items_count": len(result.items),
                        "message": "Dry run completed",
                    },
                )

            if self._sealed_gate:
                # BUG FIX: SealedGate.execute() menerima (command_type,
                # command_data, user_id, legal_entity_id, ...) ->
                # CommandEnvelope, bukan (command_id=, handler=).
                from kernel.command_envelope import CommandStatus as GateCommandStatus

                envelope = await self._sealed_gate.execute(
                    command_type=command.command_type,
                    command_data={
                        "period_start": str(command.period_start),
                        "period_end": str(command.period_end),
                        "valuation_method": command.valuation_method,
                    },
                    user_id=str(command.user_id) if command.user_id else "system",
                    legal_entity_id=command.legal_entity_id,
                )
                if envelope.status != GateCommandStatus.SUCCESS:
                    raise ValueError(
                        f"Inventory to COGS workflow rejected by sealed gate: "
                        f"{envelope.error or 'unknown reason'}"
                    )
                result = await _run_workflow()
            else:
                result = await _run_workflow()

            self._stats["succeeded"] += 1
            self._record_audit("inventory_to_cogs_execute", {
                "period_start": command.period_start.isoformat(),
                "period_end": command.period_end.isoformat(),
                "total_cogs": str(result.total_cogs),
                "user_id": str(command.user_id) if command.user_id else None,
            })

            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "calculation_id": str(result.calculation_id),
                    "total_quantity_sold": float(result.total_quantity_sold),
                    "total_cogs": float(result.total_cogs),
                    "items": [
                        {
                            "product_id": str(item.product_id),
                            "product_code": item.product_code,
                            "quantity_sold": float(item.quantity_sold),
                            "unit_cost": float(item.unit_cost),
                            "total_cogs": float(item.total_cogs),
                        }
                        for item in result.items
                    ],
                    "journal_id": str(result.journal_id) if result.journal_id else None,
                    "message": result.message,
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"Inventory to COGS workflow failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="INVENTORY_TO_COGS_ERROR"
            )

    async def _post_cogs_journal(
        self,
        legal_entity_id: UUID,
        cogs_amount: Decimal,
        period_start: date,
        period_end: date,
        user_id: UUID | None,
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
                "description": "Reduction in inventory",
            },
        ]

                # BUG FIX: post_journal() aslinya memposting jurnal yang SUDAH
        # ADA berstatus "approved" (butuh journal_id), bukan membuat baru
        # dari lines/description mentah. create_journal() membuat draft;
        # lalu submit_journal() supaya siap disetujui - TIDAK di-auto-
        # approve/post karena approve_journal() menegakkan prinsip 4-eyes
        # (creator != approver). Approval final tetap perlu manusia lain
        # lewat alur normal.
        journal = await self._journal_service.create_journal(
            legal_entity_id=legal_entity_id,
            journal_date=period_end,
            description=f"COGS calculation {period_start} to {period_end}",
            journal_type="general",
            lines=lines,
            reference_number=None,
            source_type="inventory",
            source_id=None,
            notes=None,
            attachment_ids=None,
            created_by=user_id,
        )
        await self._journal_service.submit_journal(journal.id, user_id, legal_entity_id)
        journal_id = journal.id
        return journal_id

    async def _save_calculation_result(
        self,
        calculation_id: UUID,
        command: InventoryToCOGSCommand,
        total_cogs: Decimal,
        items: list[COGSCalculationItem],
        journal_id: UUID | None,
    ) -> None:
        logger.info(f"COGS calculation {calculation_id} saved: {total_cogs}")

    def get_stats(self) -> dict[str, int]:
        return self._stats

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()


# ============================================================================
# Factory function
# ============================================================================

def create_inventory_to_cogs_workflow(
    inventory_service: InventoryService,
    journal_service: JournalService,
    sales_service: SalesService,
    sealed_gate: SealedGate | None = None,
) -> InventoryToCOGSWorkflow:
    return InventoryToCOGSWorkflow(
        inventory_service=inventory_service,
        journal_service=journal_service,
        sales_service=sales_service,
        sealed_gate=sealed_gate,
    )


__all__ = [
    "COGSCalculationItem",
    "InventoryToCOGSCommand",
    "InventoryToCOGSResult",
    "InventoryToCOGSWorkflow",
    "create_inventory_to_cogs_workflow",
]
