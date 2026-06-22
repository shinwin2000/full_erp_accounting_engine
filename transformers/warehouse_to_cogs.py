#!/usr/bin/env python3
"""
Module: warehouse_to_cogs.py
Layer: Transformers
Responsibility: Mentransformasi event dari sistem warehouse (Stock Movement,
               Delivery Order, Sales Dispatch) menjadi command untuk mencatat
               COGS (Cost of Goods Sold).

Metode yang ditambahkan:
- BaseTransformer dengan entity dasar: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk COGSCalculator, WarehouseToCOGSTransformer.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from application.commands_cqrs.command_bus_unified import UnifiedCommandBus
from application.dto_objects.journal_request import JournalCreateRequest, JournalLineRequest
from application.service_layer.service_inventory import InventoryService
from application.service_layer.service_journal import JournalService
from bootstrap.dependency_container.ioc_container import get_container
from domain.inventory.valuation_method import (
    AverageValuation as AverageValuationEngine,
)
from domain.inventory.valuation_method import (
    FIFOValuation as FIFOValuationEngine,
)
from domain.inventory.valuation_method import (
    ValuationMethodStrategy as ValuationMethod,
)
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.inventory_repository_port import InventoryRepositoryPort

if TYPE_CHECKING:
    from domain.inventory.aggregate_root import InventoryItemAggregate
    from event_gateway.event_gate_singleton import EventEnvelope

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================
DEFAULT_CURRENCY = "IDR"
DEFAULT_COGS_ACCOUNT = "5-1100"
DEFAULT_INVENTORY_ACCOUNT = "1-1200"
DEFAULT_SALES_REVENUE_ACCOUNT = "4-1100"

HANDLED_EVENT_TYPES = [
    "GoodsIssued",
    "SalesOrderShipped",
    "StockOutOccurred",
    "DeliveryOrderCompleted",
    "SalesInvoiceCreated",
]


# ============================================================================
# BaseTransformer (didefinisikan ulang untuk kemandirian file)
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
class WarehouseToCOGSTransformerError(Exception):
    pass


class ItemNotFoundError(WarehouseToCOGSTransformerError):
    pass


class InsufficientStockError(WarehouseToCOGSTransformerError):
    pass


class ValuationError(WarehouseToCOGSTransformerError):
    pass


# ============================================================================
# COGSCalculator (dengan entity dasar)
# ============================================================================
class COGSCalculator(BaseTransformer):
    def __init__(self, valuation_method: ValuationMethod):
        super().__init__("COGSCalculator")
        self.valuation_method = valuation_method
        self._fifo_engine: FIFOValuationEngine | None = None
        self._avg_engine: AverageValuationEngine | None = None
        self._item_id: UUID | None = None

    async def initialize(self, item_id: UUID, inventory_service: InventoryService):
        self._item_id = item_id
        if self.valuation_method == ValuationMethod.FIFO:
            self._fifo_engine = FIFOValuationEngine(item_id, inventory_service)
            await self._fifo_engine.initialize()
        elif self.valuation_method == ValuationMethod.AVERAGE:
            self._avg_engine = AverageValuationEngine(item_id, inventory_service)
            await self._avg_engine.initialize()

    async def calculate_cogs(
        self, quantity: Decimal, as_of_date: date
    ) -> tuple[Decimal, list[dict]]:
        if self.valuation_method == ValuationMethod.FIFO:
            if not self._fifo_engine:
                raise ValuationError("FIFO engine not initialized")
            return await self._fifo_engine.calculate_cogs(quantity, as_of_date)
        elif self.valuation_method == ValuationMethod.AVERAGE:
            if not self._avg_engine:
                raise ValuationError("Average engine not initialized")
            avg_cost = await self._avg_engine.get_average_cost()
            total_cogs = quantity * avg_cost
            return total_cogs, [{"method": "average", "unit_cost": avg_cost, "quantity": quantity}]
        elif self.valuation_method == ValuationMethod.STANDARD:
            return Decimal(0), []
        else:
            raise ValuationError(f"Unsupported valuation method: {self.valuation_method}")

    def validate(self) -> dict[str, Any]:
        errors = []
        if not isinstance(self.valuation_method, ValuationMethod):
            errors.append("Invalid valuation method")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["valuation_method"] = (
            self.valuation_method.value
            if hasattr(self.valuation_method, "value")
            else str(self.valuation_method)
        )
        data["item_id"] = str(self._item_id) if self._item_id else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> COGSCalculator:
        valuation_method = ValuationMethod(data.get("valuation_method", "fifo"))
        instance = cls(valuation_method)
        instance._version = data.get("version", 1)
        instance._transformer_id = data.get("transformer_id", str(uuid4()))
        return instance

    def clone(self) -> COGSCalculator:
        new = COGSCalculator(self.valuation_method)
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._transformer_id})
        return new


# ============================================================================
# WarehouseToCOGSTransformer (dengan entity dasar)
# ============================================================================
class WarehouseToCOGSTransformer(BaseTransformer):
    def __init__(self):
        super().__init__("WarehouseToCOGSTransformer")
        self._command_bus: UnifiedCommandBus | None = None
        self._inventory_service: InventoryService | None = None
        self._journal_service: JournalService | None = None
        self._inventory_repo: InventoryRepositoryPort | None = None
        self._processed_events: set = set()
        self._cogs_calculators: dict[UUID, COGSCalculator] = {}

    async def _get_command_bus(self) -> UnifiedCommandBus:
        if self._command_bus is None:
            container = get_container()
            self._command_bus = container.resolve(UnifiedCommandBus)
        return self._command_bus

    async def _get_inventory_service(self) -> InventoryService:
        if self._inventory_service is None:
            container = get_container()
            self._inventory_service = container.resolve(InventoryService)
        return self._inventory_service

    async def _get_journal_service(self) -> JournalService:
        if self._journal_service is None:
            container = get_container()
            self._journal_service = container.resolve(JournalService)
        return self._journal_service

    async def _get_inventory_repo(self) -> InventoryRepositoryPort:
        if self._inventory_repo is None:
            container = get_container()
            self._inventory_repo = container.resolve(InventoryRepositoryPort)
        return self._inventory_repo

    async def _get_cogs_calculator(
        self, item_id: UUID, item: InventoryItemAggregate
    ) -> COGSCalculator:
        if item_id not in self._cogs_calculators:
            calculator = COGSCalculator(item.valuation_method)
            await calculator.initialize(item_id, await self._get_inventory_service())
            self._cogs_calculators[item_id] = calculator
        return self._cogs_calculators[item_id]

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

        logger.info(f"Transforming event {event_type} to COGS journal")
        try:
            shipment_data = await self._extract_shipment_data(event_payload, event_type)
            journal_lines = []
            total_cogs = Decimal(0)
            for item_data in shipment_data["items"]:
                item_id = item_data["item_id"]
                quantity = Decimal(str(item_data["quantity"]))
                item = await self._get_item(item_id, shipment_data["legal_entity_id"])
                if not item:
                    raise ItemNotFoundError(f"Item {item_id} not found")
                calculator = await self._get_cogs_calculator(item_id, item)
                try:
                    cogs_amount, _breakdown = await calculator.calculate_cogs(
                        quantity, shipment_data["movement_date"]
                    )
                    if cogs_amount <= 0 and quantity > 0:
                        cogs_amount = item.standard_cost.amount * quantity
                        logger.warning(
                            f"Using standard cost for item {item.item_code}: {cogs_amount}"
                        )
                    total_cogs += cogs_amount
                    journal_lines.append(
                        JournalLineRequest(
                            account_code=DEFAULT_COGS_ACCOUNT,
                            debit_amount=cogs_amount,
                            credit_amount=Decimal(0),
                            cost_center=item_data.get("cost_center"),
                            department=item_data.get("department"),
                            description=f"COGS for {item.item_code} - {shipment_data.get('reference_number', '')}",
                        )
                    )
                    journal_lines.append(
                        JournalLineRequest(
                            account_code=item.gl_inventory_account or DEFAULT_INVENTORY_ACCOUNT,
                            debit_amount=Decimal(0),
                            credit_amount=cogs_amount,
                            cost_center=item_data.get("cost_center"),
                            department=item_data.get("department"),
                            description=f"Inventory reduction for {item.item_code}",
                        )
                    )
                    if item_data.get("selling_price") and item_data.get("quantity"):
                        revenue = Decimal(str(item_data["selling_price"])) * quantity
                        journal_lines.append(
                            JournalLineRequest(
                                account_code=DEFAULT_SALES_REVENUE_ACCOUNT,
                                debit_amount=Decimal(0),
                                credit_amount=revenue,
                                cost_center=item_data.get("cost_center"),
                                description=f"Sales revenue for {item.item_code}",
                            )
                        )
                except InsufficientStockError as e:
                    logger.error(f"Insufficient stock for item {item.item_code}: {e}")
                    await trigger_alert(
                        title="COGS Calculation Error",
                        message=f"Insufficient stock for item {item.item_code}. Quantity: {quantity}",
                        severity="warning",
                        source="WarehouseToCOGSTransformer",
                    )
                    cogs_amount = item.standard_cost.amount * quantity
                    total_cogs += cogs_amount
                    journal_lines.append(
                        JournalLineRequest(
                            account_code=DEFAULT_COGS_ACCOUNT,
                            debit_amount=cogs_amount,
                            credit_amount=Decimal(0),
                            description=f"COGS for {item.item_code} (fallback - standard cost)",
                        )
                    )
                    journal_lines.append(
                        JournalLineRequest(
                            account_code=item.gl_inventory_account or DEFAULT_INVENTORY_ACCOUNT,
                            debit_amount=Decimal(0),
                            credit_amount=cogs_amount,
                            description=f"Inventory reduction for {item.item_code}",
                        )
                    )
            if not journal_lines:
                logger.warning(f"No journal lines created for event {event_id}")
                return
            total_debit = sum(line.debit_amount for line in journal_lines)
            total_credit = sum(line.credit_amount for line in journal_lines)
            if abs(total_debit - total_credit) > Decimal("0.01"):
                difference = total_debit - total_credit
                if difference > 0:
                    journal_lines.append(
                        JournalLineRequest(
                            account_code=DEFAULT_COGS_ACCOUNT,
                            debit_amount=Decimal(0),
                            credit_amount=difference,
                            description="COGS balancing entry",
                        )
                    )
                else:
                    journal_lines.append(
                        JournalLineRequest(
                            account_code=DEFAULT_COGS_ACCOUNT,
                            debit_amount=abs(difference),
                            credit_amount=Decimal(0),
                            description="COGS balancing entry",
                        )
                    )
            create_request = JournalCreateRequest(
                journal_date=shipment_data["movement_date"],
                description=f"COGS Journal - {shipment_data.get('reference_number', 'Shipment')}",
                lines=journal_lines,
                reference_number=shipment_data.get("reference_number"),
                source_type="warehouse_shipment",
                source_id=str(shipment_data.get("shipment_id")),
                created_by=shipment_data.get("created_by")
                or UUID("00000000-0000-0000-0000-000000000000"),
                legal_entity_id=shipment_data["legal_entity_id"],
            )
            command_bus = await self._get_command_bus()
            result = await command_bus.dispatch(
                {"type": "journal.create", "data": create_request.to_dict()}
            )
            self._processed_events.add(event_id)
            logger.info(
                f"COGS journal created: {result['voucher_number']} for event {event_id}, total COGS: {total_cogs}"
            )
        except (ItemNotFoundError, ValuationError) as e:
            logger.error(f"Failed to transform event {event_id}: {e}")
            await trigger_alert(
                title="Warehouse to COGS Transformation Failed",
                message=f"Error: {str(e)[:200]}",
                severity="error",
                source="WarehouseToCOGSTransformer",
            )
            raise

    async def _extract_shipment_data(
        self, payload: dict[str, Any], event_type: str
    ) -> dict[str, Any]:
        base_data = {
            "movement_date": datetime.now(UTC).date(),
            "legal_entity_id": UUID(payload.get("legal_entity_id"))
            if payload.get("legal_entity_id")
            else None,
            "items": [],
            "created_by": UUID(payload.get("created_by")) if payload.get("created_by") else None,
        }
        if event_type in ("GoodsIssued", "StockOutOccurred"):
            base_data.update(
                {
                    "shipment_id": payload.get("movement_id") or payload.get("issue_id"),
                    "reference_number": payload.get("movement_number")
                    or payload.get("issue_number"),
                    "movement_date": self._parse_date(payload.get("movement_date"))
                    or datetime.now(UTC).date(),
                    "items": [
                        {
                            "item_id": UUID(line.get("item_id")) if line.get("item_id") else None,
                            "item_code": line.get("item_code"),
                            "quantity": Decimal(str(line.get("quantity", 0))),
                            "cost_center": line.get("cost_center"),
                            "department": line.get("department"),
                            "selling_price": line.get("selling_price"),
                        }
                        for line in payload.get("items", [])
                    ],
                }
            )
        elif event_type in ("SalesOrderShipped", "DeliveryOrderCompleted"):
            base_data.update(
                {
                    "shipment_id": payload.get("delivery_id") or payload.get("shipment_id"),
                    "reference_number": payload.get("delivery_number")
                    or payload.get("shipment_number"),
                    "movement_date": self._parse_date(
                        payload.get("shipped_date") or payload.get("delivery_date")
                    )
                    or datetime.now(UTC).date(),
                    "items": [
                        {
                            "item_id": UUID(line.get("product_id"))
                            if line.get("product_id")
                            else UUID(line.get("item_id"))
                            if line.get("item_id")
                            else None,
                            "item_code": line.get("product_code") or line.get("item_code"),
                            "quantity": Decimal(str(line.get("quantity", 0))),
                            "cost_center": line.get("cost_center"),
                            "department": line.get("department"),
                            "selling_price": line.get("unit_price", 0),
                        }
                        for line in payload.get("items", [])
                    ],
                }
            )
        elif event_type == "SalesInvoiceCreated":
            base_data.update(
                {
                    "shipment_id": payload.get("invoice_id"),
                    "reference_number": payload.get("invoice_number"),
                    "movement_date": self._parse_date(payload.get("invoice_date"))
                    or datetime.now(UTC).date(),
                    "items": [
                        {
                            "item_id": UUID(line.get("item_id")) if line.get("item_id") else None,
                            "item_code": line.get("item_code"),
                            "quantity": Decimal(str(line.get("quantity", 0))),
                            "cost_center": line.get("cost_center"),
                            "selling_price": Decimal(str(line.get("unit_price", 0))),
                        }
                        for line in payload.get("lines", [])
                    ],
                }
            )
        base_data["items"] = [item for item in base_data["items"] if item["item_id"]]
        return base_data

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

    async def _get_item(
        self, item_id: UUID, legal_entity_id: UUID
    ) -> InventoryItemAggregate | None:
        inventory_repo = await self._get_inventory_repo()
        return await inventory_repo.get_item_by_id(item_id)

    async def reset(self) -> None:
        self._processed_events.clear()
        self._cogs_calculators.clear()
        self._version += 1
        logger.info("WarehouseToCOGSTransformer reset")

    def validate(self) -> dict[str, Any]:
        errors = []
        if not self._cogs_calculators:
            errors.append("No COGS calculators initialized")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["processed_events_count"] = len(self._processed_events)
        data["cogs_calculators_count"] = len(self._cogs_calculators)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WarehouseToCOGSTransformer:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._transformer_id = data.get("transformer_id", str(uuid4()))
        return instance

    def clone(self) -> WarehouseToCOGSTransformer:
        new = WarehouseToCOGSTransformer()
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._transformer_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        snap = super().snapshot()
        snap["processed_events_count"] = len(self._processed_events)
        return snap

    def touch(self, touched_by: str) -> WarehouseToCOGSTransformer:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# TRANSFORMER FACTORY & EVENT HANDLER
# ============================================================================
_warehouse_to_cogs_transformer: WarehouseToCOGSTransformer | None = None


async def get_warehouse_to_cogs_transformer() -> WarehouseToCOGSTransformer:
    global _warehouse_to_cogs_transformer
    if _warehouse_to_cogs_transformer is None:
        _warehouse_to_cogs_transformer = WarehouseToCOGSTransformer()
    return _warehouse_to_cogs_transformer


async def handle_warehouse_event(envelope: EventEnvelope) -> None:
    transformer = await get_warehouse_to_cogs_transformer()
    await transformer.transform(envelope)


__all__ = [
    "InsufficientStockError",
    "ItemNotFoundError",
    "ValuationError",
    "WarehouseToCOGSTransformer",
    "WarehouseToCOGSTransformerError",
    "get_warehouse_to_cogs_transformer",
    "handle_warehouse_event",
]
