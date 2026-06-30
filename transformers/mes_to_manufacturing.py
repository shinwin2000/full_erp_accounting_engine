#!/usr/bin/env python3
"""
Module: mes_to_manufacturing.py
Layer: Transformers
Responsibility: Mentransformasi event dari sistem MES (Manufacturing Execution System)
               atau produksi menjadi command untuk mencatat Work In Process (WIP),
               perhitungan HPP (Harga Pokok Produksi), dan journal manufacturing.

Metode yang ditambahkan:
- BaseTransformer dengan entity dasar: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk ManufacturingCostCalculator, MESToManufacturingTransformer.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from application.commands_cqrs.command_bus_unified import UnifiedCommandBus
from application.dto_objects.journal_request import JournalCreateRequest, JournalLineRequest
from application.dto_objects.manufacturing_request import (
    LaborRecordRequest,
    MaterialIssueRequest,
    ProductionCompletionRequest,
    WorkOrderCreateRequest,
)
from application.service_layer.service_inventory import InventoryService
from application.service_layer.service_manufacturing import ManufacturingService
from domain.manufacturing.hpp_per_product_calculator import HPPCalculator
from domain.manufacturing.overhead_allocation_engine import OverheadAllocationEngine
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.bill_of_materials_repository_port import BillOfMaterialsRepositoryPort
from ports.primary.work_order_repository_port import WorkOrderRepositoryPort

if TYPE_CHECKING:
    from domain.manufacturing.work_order_entity import WorkOrderEntity
    from event_gateway.event_gate_singleton import EventEnvelope

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================
DEFAULT_CURRENCY = "IDR"
DEFAULT_RAW_MATERIAL_ACCOUNT = "1-1300"
DEFAULT_WIP_ACCOUNT = "1-1400"
DEFAULT_FINISHED_GOODS_ACCOUNT = "1-1500"
DEFAULT_LABOR_ACCOUNT = "5-3100"
DEFAULT_OVERHEAD_ACCOUNT = "5-3200"
DEFAULT_COGS_ACCOUNT = "5-1100"
DEFAULT_OVERHEAD_RATE_PERCENT = Decimal("0.15")
DEFAULT_MACHINE_HOUR_RATE = Decimal("50000")

HANDLED_EVENT_TYPES = [
    "ProductionOrderStarted",
    "ProductionOrderReleased",
    "MaterialIssuedToProduction",
    "LaborRecorded",
    "MachineReported",
    "ProductionCompleted",
    "ProductionOrderClosed",
    "QualityInspected",
]


# ============================================================================
# BaseTransformer
# ============================================================================
class BaseTransformer:
    def __init__(self, name: str):
        self.name = name
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._transformer_id = str(uuid4())

    def _take_snapshot(self):
        import datetime
        self._snapshots.append(
            {
                "version": self._version,
                "transformer_id": self._transformer_id,
                "name": self.name,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        import datetime
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                "version": self._version,
                "transformer_id": self._transformer_id,
                "details": details,
            }
        )

    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {"transformer_id": self._transformer_id, "name": self.name, "version": self._version}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseTransformer:
        instance = cls(data["name"])
        instance._version = data.get("version", 1)
        instance._transformer_id = data.get("transformer_id", str(uuid4()))
        return instance

    def clone(self) -> BaseTransformer:
        new = self.__class__(self.name)
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._transformer_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        import datetime
        return {
            "version": self._version,
            "transformer_id": self._transformer_id,
            "name": self.name,
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> BaseTransformer:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# EXCEPTIONS
# ============================================================================
class MESToManufacturingTransformerError(Exception):
    pass


class WorkOrderNotFoundError(MESToManufacturingTransformerError):
    pass


class MaterialIssueError(MESToManufacturingTransformerError):
    pass


class ProductionCompletionError(MESToManufacturingTransformerError):
    pass


class BillOfMaterialsNotFoundError(MESToManufacturingTransformerError):
    pass


# ============================================================================
# ManufacturingCostCalculator (dengan entity dasar)
# ============================================================================
class ManufacturingCostCalculator(BaseTransformer):
    def __init__(self):
        super().__init__("ManufacturingCostCalculator")
        self._overhead_engine = OverheadAllocationEngine()
        self._hpp_calculator = HPPCalculator()

    async def calculate_wip_cost(
        self,
        work_order_id: UUID,
        material_costs: list[dict],
        labor_costs: list[dict],
        machine_costs: list[dict],
    ) -> dict[str, Decimal]:
        total_material = sum(Decimal(str(m.get("cost", 0))) for m in material_costs)
        total_labor = sum(Decimal(str(l.get("cost", 0))) for l in labor_costs)
        total_machine = sum(Decimal(str(mc.get("cost", 0))) for mc in machine_costs)
        overhead = await self._overhead_engine.calculate_overhead(
            labor_cost=total_labor,
            machine_hours=(
                total_machine / DEFAULT_MACHINE_HOUR_RATE if DEFAULT_MACHINE_HOUR_RATE > 0 else 0
            ),
        )
        total_wip = total_material + total_labor + total_machine + overhead
        return {
            "material_cost": total_material,
            "labor_cost": total_labor,
            "machine_cost": total_machine,
            "overhead_cost": overhead,
            "total_wip": total_wip,
        }

    async def calculate_finished_goods_cost(
        self, work_order: WorkOrderEntity, wip_cost: Decimal, completed_quantity: Decimal
    ) -> dict[str, Any]:
        if completed_quantity <= 0:
            return {"unit_cost": Decimal(0), "total_cost": wip_cost, "scrap_loss": Decimal(0)}
        unit_cost = wip_cost / completed_quantity
        standard_cost = getattr(work_order, "standard_cost", Decimal(0)) or Decimal(0)
        variance = unit_cost - standard_cost
        return {
            "unit_cost": unit_cost,
            "total_cost": wip_cost,
            "standard_cost": standard_cost,
            "variance": variance,
            "variance_percent": (variance / standard_cost * 100) if standard_cost > 0 else 0,
        }

    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return super().to_dict()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManufacturingCostCalculator:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._transformer_id = data.get("transformer_id", str(uuid4()))
        return instance

    def clone(self) -> ManufacturingCostCalculator:
        new = ManufacturingCostCalculator()
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._transformer_id})
        return new


# ============================================================================
# MESToManufacturingTransformer (dengan entity dasar)
# ============================================================================
class MESToManufacturingTransformer(BaseTransformer):
    def __init__(
        self,
        command_bus: UnifiedCommandBus,
        manufacturing_service: ManufacturingService,
        inventory_service: InventoryService,
        work_order_repo: WorkOrderRepositoryPort,
        bom_repo: BillOfMaterialsRepositoryPort,
    ):
        super().__init__("MESToManufacturingTransformer")
        self._command_bus = command_bus
        self._manufacturing_service = manufacturing_service
        self._inventory_service = inventory_service
        self._work_order_repo = work_order_repo
        self._bom_repo = bom_repo
        self._cost_calculator = ManufacturingCostCalculator()
        self._processed_events: set = set()
        self._wip_costs: dict[UUID, dict] = {}
        self._material_issues: dict[UUID, list] = {}
        self._labor_records: dict[UUID, list] = {}
        self._machine_records: dict[UUID, list] = {}

    async def transform(self, envelope: EventEnvelope) -> None:
        event_type = envelope.event_type
        event_id = str(envelope.id)
        event_payload = envelope.payload

        if event_id in self._processed_events:
            logger.debug(f"Event {event_id} already processed, skipping")
            return
        if event_type not in HANDLED_EVENT_TYPES:
            logger.debug(f"Event type {event_type} not handled")
            return

        logger.info(f"Transforming event {event_type} to manufacturing command")
        try:
            if event_type in ("ProductionOrderStarted", "ProductionOrderReleased"):
                await self._handle_work_order_start(event_payload, envelope)
            elif event_type == "MaterialIssuedToProduction":
                await self._handle_material_issue(event_payload, envelope)
            elif event_type == "LaborRecorded":
                await self._handle_labor_record(event_payload, envelope)
            elif event_type == "MachineReported":
                await self._handle_machine_record(event_payload, envelope)
            elif event_type in ("ProductionCompleted", "QualityInspected"):
                await self._handle_production_completion(event_payload, envelope)
            elif event_type == "ProductionOrderClosed":
                await self._handle_work_order_close(event_payload, envelope)
            self._processed_events.add(event_id)
        except Exception as e:
            logger.exception(f"Failed to transform event {event_id}: {e}")
            await trigger_alert(
                title="MES to Manufacturing Transformation Failed",
                message=f"Event: {event_type}, Error: {str(e)[:200]}",
                severity="error",
                source="MESToManufacturingTransformer",
            )
            raise

    async def _handle_work_order_start(
        self, payload: dict[str, Any], envelope: EventEnvelope
    ) -> None:
        work_order_id = UUID(payload.get("work_order_id") or payload.get("production_order_id"))
        product_id = UUID(payload.get("product_id"))
        planned_quantity = Decimal(str(payload.get("planned_quantity", 0)))
        legal_entity_id = (
            UUID(payload.get("legal_entity_id"))
            if payload.get("legal_entity_id")
            else envelope.metadata.get("legal_entity_id")
        )
        bom = await self._get_bom_for_product(product_id, legal_entity_id)
        if not bom:
            raise BillOfMaterialsNotFoundError(f"BOM not found for product {product_id}")
        create_request = WorkOrderCreateRequest(
            work_order_number=payload.get(
                "order_number", f"WO-{datetime.now().strftime('%Y%m%d')}-{work_order_id.hex[:6]}"
            ),
            product_id=product_id,
            product_name=payload.get("product_name", ""),
            planned_quantity=planned_quantity,
            bom_id=bom.id,
            routing_id=payload.get("routing_id"),
            planned_start_date=self._parse_date(payload.get("start_date")) or datetime.now().date(),
            planned_end_date=self._parse_date(payload.get("end_date"))
            or (datetime.now().date() + timedelta(days=7)),
            legal_entity_id=legal_entity_id,
            created_by=UUID(payload.get("created_by")) if payload.get("created_by") else None,
        )
        result = await self._command_bus.dispatch(
            {"type": "manufacturing.work_order.create", "data": create_request.to_dict()}
        )
        self._wip_costs[work_order_id] = {
            "material": Decimal(0),
            "labor": Decimal(0),
            "machine": Decimal(0),
        }
        self._material_issues[work_order_id] = []
        self._labor_records[work_order_id] = []
        self._machine_records[work_order_id] = []
        logger.info(
            f"Work order {result.get('work_order_number')} created for product {product_id}"
        )

    async def _handle_material_issue(
        self, payload: dict[str, Any], envelope: EventEnvelope
    ) -> None:
        work_order_id = UUID(payload.get("work_order_id"))
        material_id = UUID(payload.get("material_id") or payload.get("item_id"))
        quantity = Decimal(str(payload.get("quantity", 0)))
        unit_cost = Decimal(str(payload.get("unit_cost", 0)))
        legal_entity_id = (
            UUID(payload.get("legal_entity_id"))
            if payload.get("legal_entity_id")
            else envelope.metadata.get("legal_entity_id")
        )
        issue_request = MaterialIssueRequest(
            work_order_id=work_order_id,
            material_id=material_id,
            quantity=quantity,
            unit_cost=unit_cost,
            issue_date=self._parse_date(payload.get("issue_date")) or datetime.now().date(),
            issued_by=UUID(payload.get("issued_by")) if payload.get("issued_by") else None,
            legal_entity_id=legal_entity_id,
        )
        await self._command_bus.dispatch(
            {"type": "manufacturing.material.issue", "data": issue_request.to_dict()}
        )
        total_cost = quantity * unit_cost
        if work_order_id in self._wip_costs:
            self._wip_costs[work_order_id]["material"] += total_cost
            self._material_issues[work_order_id].append(
                {
                    "material_id": material_id,
                    "quantity": quantity,
                    "unit_cost": unit_cost,
                    "total_cost": total_cost,
                }
            )
        logger.info(f"Material issued to work order {work_order_id}: {material_id} x{quantity}")

    async def _handle_labor_record(self, payload: dict[str, Any], envelope: EventEnvelope) -> None:
        work_order_id = UUID(payload.get("work_order_id"))
        employee_id = UUID(payload.get("employee_id"))
        hours = Decimal(str(payload.get("hours", 0)))
        hourly_rate = Decimal(str(payload.get("hourly_rate", 0)))
        legal_entity_id = (
            UUID(payload.get("legal_entity_id"))
            if payload.get("legal_entity_id")
            else envelope.metadata.get("legal_entity_id")
        )
        labor_request = LaborRecordRequest(
            work_order_id=work_order_id,
            employee_id=employee_id,
            hours=hours,
            hourly_rate=hourly_rate,
            labor_date=self._parse_date(payload.get("record_date")) or datetime.now().date(),
            recorded_by=UUID(payload.get("recorded_by")) if payload.get("recorded_by") else None,
            legal_entity_id=legal_entity_id,
        )
        await self._command_bus.dispatch(
            {"type": "manufacturing.labor.record", "data": labor_request.to_dict()}
        )
        total_cost = hours * hourly_rate
        if work_order_id in self._wip_costs:
            self._wip_costs[work_order_id]["labor"] += total_cost
            self._labor_records[work_order_id].append(
                {
                    "employee_id": employee_id,
                    "hours": hours,
                    "hourly_rate": hourly_rate,
                    "total_cost": total_cost,
                }
            )
        logger.info(f"Labor recorded for work order {work_order_id}: {hours} hours")

    async def _handle_machine_record(
        self, payload: dict[str, Any], envelope: EventEnvelope
    ) -> None:
        work_order_id = UUID(payload.get("work_order_id"))
        machine_id = UUID(payload.get("machine_id"))
        hours = Decimal(str(payload.get("machine_hours", 0)))
        cost_per_hour = Decimal(str(payload.get("cost_per_hour", DEFAULT_MACHINE_HOUR_RATE)))
        legal_entity_id = (
            UUID(payload.get("legal_entity_id"))
            if payload.get("legal_entity_id")
            else envelope.metadata.get("legal_entity_id")
        )
        total_cost = hours * cost_per_hour
        if work_order_id in self._wip_costs:
            self._wip_costs[work_order_id]["machine"] += total_cost
            self._machine_records[work_order_id].append(
                {
                    "machine_id": machine_id,
                    "hours": hours,
                    "cost_per_hour": cost_per_hour,
                    "total_cost": total_cost,
                }
            )
        logger.info(f"Machine usage recorded for work order {work_order_id}: {hours} hours")

    async def _handle_production_completion(
        self, payload: dict[str, Any], envelope: EventEnvelope
    ) -> None:
        work_order_id = UUID(payload.get("work_order_id"))
        completed_quantity = Decimal(str(payload.get("completed_quantity", 0)))
        rejected_quantity = Decimal(str(payload.get("rejected_quantity", 0)))
        legal_entity_id = (
            UUID(payload.get("legal_entity_id"))
            if payload.get("legal_entity_id")
            else envelope.metadata.get("legal_entity_id")
        )
        work_order = await self._work_order_repo.get_by_id(work_order_id)
        if not work_order:
            raise WorkOrderNotFoundError(f"Work order {work_order_id} not found")
        wip = self._wip_costs.get(
            work_order_id, {"material": Decimal(0), "labor": Decimal(0), "machine": Decimal(0)}
        )
        wip_cost = await self._cost_calculator.calculate_wip_cost(
            work_order_id,
            self._material_issues.get(work_order_id, []),
            self._labor_records.get(work_order_id, []),
            self._machine_records.get(work_order_id, []),
        )
        fg_cost = await self._cost_calculator.calculate_finished_goods_cost(
            work_order, wip_cost["total_wip"], completed_quantity
        )
        completion_request = ProductionCompletionRequest(
            work_order_id=work_order_id,
            completed_quantity=completed_quantity,
            rejected_quantity=rejected_quantity,
            completion_date=self._parse_date(payload.get("completion_date"))
            or datetime.now().date(),
            unit_cost=fg_cost["unit_cost"],
            total_cost=fg_cost["total_cost"],
            completed_by=UUID(payload.get("completed_by")) if payload.get("completed_by") else None,
            legal_entity_id=legal_entity_id,
        )
        await self._command_bus.dispatch(
            {"type": "manufacturing.production.complete", "data": completion_request.to_dict()}
        )
        await self._create_manufacturing_journal(
            work_order_id, work_order, wip_cost, fg_cost, legal_entity_id
        )
        logger.info(
            f"Production completed for work order {work_order_id}: {completed_quantity} units at {fg_cost['unit_cost']}/unit"
        )
        if work_order_id in self._wip_costs:
            del self._wip_costs[work_order_id]

    async def _handle_work_order_close(
        self, payload: dict[str, Any], envelope: EventEnvelope
    ) -> None:
        work_order_id = UUID(payload.get("work_order_id"))
        legal_entity_id = (
            UUID(payload.get("legal_entity_id"))
            if payload.get("legal_entity_id")
            else envelope.metadata.get("legal_entity_id")
        )
        await self._command_bus.dispatch(
            {
                "type": "manufacturing.work_order.close",
                "data": {
                    "work_order_id": str(work_order_id),
                    "closed_by": str(payload.get("closed_by"))
                    if payload.get("closed_by")
                    else None,
                    "legal_entity_id": str(legal_entity_id),
                },
            }
        )
        logger.info(f"Work order {work_order_id} closed")

    async def _create_manufacturing_journal(
        self,
        work_order_id: UUID,
        work_order: WorkOrderEntity,
        wip_cost: dict,
        fg_cost: dict,
        legal_entity_id: UUID,
    ) -> None:
        journal_lines = []
        journal_lines.append(
            JournalLineRequest(
                account_code=DEFAULT_WIP_ACCOUNT,
                debit_amount=wip_cost["total_wip"],
                credit_amount=Decimal(0),
                cost_center=getattr(work_order, "cost_center", None),
                description=f"WIP - Work Order {work_order.work_order_number}",
            )
        )
        journal_lines.append(
            JournalLineRequest(
                account_code=DEFAULT_RAW_MATERIAL_ACCOUNT,
                debit_amount=Decimal(0),
                credit_amount=wip_cost["material_cost"],
                cost_center=getattr(work_order, "cost_center", None),
                description=f"Raw material consumed - WO {work_order.work_order_number}",
            )
        )
        journal_lines.append(
            JournalLineRequest(
                account_code=DEFAULT_LABOR_ACCOUNT,
                debit_amount=Decimal(0),
                credit_amount=wip_cost["labor_cost"],
                cost_center=getattr(work_order, "cost_center", None),
                description=f"Direct labor - WO {work_order.work_order_number}",
            )
        )
        journal_lines.append(
            JournalLineRequest(
                account_code=DEFAULT_OVERHEAD_ACCOUNT,
                debit_amount=Decimal(0),
                credit_amount=wip_cost["overhead_cost"],
                cost_center=getattr(work_order, "cost_center", None),
                description=f"Manufacturing overhead - WO {work_order.work_order_number}",
            )
        )
        journal_lines.append(
            JournalLineRequest(
                account_code=DEFAULT_FINISHED_GOODS_ACCOUNT,
                debit_amount=fg_cost["total_cost"],
                credit_amount=Decimal(0),
                cost_center=getattr(work_order, "cost_center", None),
                description=f"Finished goods - WO {work_order.work_order_number}",
            )
        )
        journal_lines.append(
            JournalLineRequest(
                account_code=DEFAULT_WIP_ACCOUNT,
                debit_amount=Decimal(0),
                credit_amount=fg_cost["total_cost"],
                cost_center=getattr(work_order, "cost_center", None),
                description=f"WIP transfer to FG - WO {work_order.work_order_number}",
            )
        )
        create_request = JournalCreateRequest(
            journal_date=datetime.now().date(),
            description=f"Manufacturing Journal - Work Order {work_order.work_order_number}",
            lines=journal_lines,
            reference_number=work_order.work_order_number,
            source_type="manufacturing",
            source_id=str(work_order_id),
            created_by=UUID("00000000-0000-0000-0000-000000000000"),
            legal_entity_id=legal_entity_id,
        )
        await self._command_bus.dispatch({"type": "journal.create", "data": create_request.to_dict()})

    async def _get_bom_for_product(self, product_id: UUID, legal_entity_id: UUID) -> Any | None:
        return await self._bom_repo.get_active_by_product(product_id, legal_entity_id)

    def _parse_date(self, date_value: Any) -> date | None:
        if date_value is None:
            return None
        if isinstance(date_value, date):
            return date_value
        if isinstance(date_value, str):
            try:
                return datetime.fromisoformat(date_value).date()
            except ValueError:
                try:
                    return datetime.strptime(date_value, "%Y-%m-%d").date()
                except ValueError:
                    return None
        return None

    async def reset(self) -> None:
        self._processed_events.clear()
        self._wip_costs.clear()
        self._material_issues.clear()
        self._labor_records.clear()
        self._machine_records.clear()
        self._version += 1
        logger.info("MESToManufacturingTransformer reset")

    def validate(self) -> dict[str, Any]:
        errors = []
        if self._cost_calculator is None:
            errors.append("Cost calculator not initialized")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["processed_events_count"] = len(self._processed_events)
        data["cost_calculator"] = self._cost_calculator.to_dict()
        data["wip_costs_count"] = len(self._wip_costs)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MESToManufacturingTransformer:
        instance = cls.__new__(cls)
        instance._version = data.get("version", 1)
        instance._transformer_id = data.get("transformer_id", str(uuid4()))
        instance._command_bus = None
        instance._manufacturing_service = None
        instance._inventory_service = None
        instance._work_order_repo = None
        instance._bom_repo = None
        instance._cost_calculator = ManufacturingCostCalculator()
        instance._processed_events = set()
        instance._wip_costs = {}
        instance._material_issues = {}
        instance._labor_records = {}
        instance._machine_records = {}
        return instance

    def clone(self) -> MESToManufacturingTransformer:
        new = MESToManufacturingTransformer(
            command_bus=self._command_bus,
            manufacturing_service=self._manufacturing_service,
            inventory_service=self._inventory_service,
            work_order_repo=self._work_order_repo,
            bom_repo=self._bom_repo,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._transformer_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        snap = super().snapshot()
        snap["processed_events_count"] = len(self._processed_events)
        return snap

    def touch(self, touched_by: str) -> MESToManufacturingTransformer:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# TRANSFORMER FACTORY & EVENT HANDLER
# ============================================================================
_mes_to_manufacturing_transformer: MESToManufacturingTransformer | None = None


async def get_mes_to_manufacturing_transformer() -> MESToManufacturingTransformer:
    global _mes_to_manufacturing_transformer
    if _mes_to_manufacturing_transformer is None:
        from bootstrap.dependency_container.ioc_container import get_container

        container = get_container()
        command_bus = container.resolve(UnifiedCommandBus)
        manufacturing_service = container.resolve(ManufacturingService)
        inventory_service = container.resolve(InventoryService)
        work_order_repo = container.resolve(WorkOrderRepositoryPort)
        bom_repo = container.resolve(BillOfMaterialsRepositoryPort)
        _mes_to_manufacturing_transformer = MESToManufacturingTransformer(
            command_bus=command_bus,
            manufacturing_service=manufacturing_service,
            inventory_service=inventory_service,
            work_order_repo=work_order_repo,
            bom_repo=bom_repo,
        )
    return _mes_to_manufacturing_transformer


async def handle_mes_event(envelope: EventEnvelope) -> None:
    transformer = await get_mes_to_manufacturing_transformer()
    await transformer.transform(envelope)


__all__ = [
    "BillOfMaterialsNotFoundError",
    "MESToManufacturingTransformer",
    "MESToManufacturingTransformerError",
    "MaterialIssueError",
    "ProductionCompletionError",
    "WorkOrderNotFoundError",
    "get_mes_to_manufacturing_transformer",
    "handle_mes_event",
]