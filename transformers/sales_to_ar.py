#!/usr/bin/env python3
"""
Module: sales_to_ar.py
Layer: Transformers
Responsibility: Mentransformasi event dari sistem penjualan (Sales Order, Sales Invoice)
               menjadi command untuk membuat AR Invoice.

Metode yang ditambahkan:
- BaseTransformer dengan entity dasar: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk SalesToARTransformer.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from application.commands_cqrs.command_bus_unified import UnifiedCommandBus
from application.dto_objects.ar_invoice_request import ARInvoiceCreateRequest
from application.service_layer.service_ar import ARService
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.customer_supplier_repository_port import CustomerRepositoryPort

if TYPE_CHECKING:
    from domain.customer_supplier_employee.customer_aggregate_root import CustomerAggregate
    from event_gateway.event_gate_singleton import EventEnvelope

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================
DEFAULT_TAX_RATE = Decimal("0.11")
DEFAULT_CURRENCY = "IDR"
HANDLED_EVENT_TYPES = [
    "SalesInvoiceApproved",
    "SalesOrderFulfilled",
    "SalesOrderCompleted",
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
class SalesToARTransformerError(Exception):
    pass


class CustomerNotFoundError(SalesToARTransformerError):
    pass


class InvalidEventDataError(SalesToARTransformerError):
    pass


# ============================================================================
# SalesToARTransformer (dengan entity dasar)
# ============================================================================
class SalesToARTransformer(BaseTransformer):
    def __init__(
        self,
        command_bus: UnifiedCommandBus,
        ar_service: ARService,
        customer_repo: CustomerRepositoryPort,
    ):
        super().__init__("SalesToARTransformer")
        self._command_bus = command_bus
        self._ar_service = ar_service
        self._customer_repo = customer_repo
        self._mapping_cache: dict[str, str] = {}
        self._processed_events: set = set()

    async def transform(self, envelope: EventEnvelope) -> None:
        event_type = envelope.event_type
        event_id = str(envelope.id)
        event_payload = envelope.payload

        if event_id in self._processed_events:
            logger.debug(f"Event {event_id} already processed, skipping")
            return
        if event_type not in HANDLED_EVENT_TYPES:
            logger.debug(f"Event type {event_type} not handled by SalesToARTransformer")
            return

        logger.info(f"Transforming event {event_type} to AR Invoice command")

        try:
            sales_data = self._extract_sales_data(event_payload, event_type)
            customer = await self._get_customer(sales_data["customer_id"])
            lines = self._calculate_invoice_lines(sales_data, customer)
            create_request = ARInvoiceCreateRequest(
                customer_id=customer.id,
                customer_code=customer.customer_code,
                invoice_date=sales_data["invoice_date"],
                due_date=sales_data.get(
                    "due_date", self._calculate_due_date(sales_data["invoice_date"])
                ),
                lines=lines,
                description=f"Sales Invoice: {sales_data.get('sales_number', 'N/A')}",
                reference_number=sales_data.get("sales_number"),
                sales_order_id=sales_data.get("sales_order_id"),
                use_tax=True,
                discount_global=sales_data.get("discount_percent", 0),
                created_by=sales_data.get("created_by")
                or UUID("00000000-0000-0000-0000-000000000000"),
                legal_entity_id=envelope.metadata.get(
                    "legal_entity_id", sales_data.get("legal_entity_id")
                ),
            )
            result = await self._command_bus.dispatch(
                {"type": "ar.invoice.create", "data": create_request.to_dict()}
            )
            sales_id = sales_data.get("sales_id") or sales_data.get("sales_order_id")
            if sales_id:
                self._mapping_cache[str(sales_id)] = result["id"]
            self._processed_events.add(event_id)
            logger.info(
                f"AR Invoice created: {result['invoice_number']} from sales event {event_id}"
            )
        except CustomerNotFoundError as e:
            logger.error(f"Customer not found for sales event {event_id}: {e}")
            await trigger_alert(
                title="Sales to AR Transformation Failed",
                message=f"Customer not found for sales event {event_id}",
                severity="warning",
                source="SalesToARTransformer",
            )
            raise
        except InvalidEventDataError as e:
            logger.error(f"Invalid event data for {event_id}: {e}")
            await trigger_alert(
                title="Sales to AR Transformation Failed",
                message=f"Invalid event data: {e}",
                severity="warning",
                source="SalesToARTransformer",
            )
            raise
        except Exception as e:
            logger.exception(f"Failed to transform event {event_id}: {e}")
            await trigger_alert(
                title="Sales to AR Transformation Failed",
                message=f"Error: {str(e)[:200]}",
                severity="error",
                source="SalesToARTransformer",
            )
            raise SalesToARTransformerError(f"Transformation failed: {e}") from e

    def _extract_sales_data(self, payload: dict[str, Any], event_type: str) -> dict[str, Any]:
        if event_type == "SalesInvoiceApproved":
            return {
                "sales_id": payload.get("invoice_id"),
                "sales_number": payload.get("invoice_number"),
                "customer_id": payload.get("customer_id"),
                "customer_code": payload.get("customer_code"),
                "invoice_date": self._parse_date(payload.get("invoice_date"))
                or datetime.now(UTC).date(),
                "due_date": self._parse_date(payload.get("due_date")),
                "lines": payload.get("lines", []),
                "discount_percent": payload.get("discount", 0),
                "sales_order_id": payload.get("sales_order_id"),
                "legal_entity_id": UUID(payload.get("legal_entity_id"))
                if payload.get("legal_entity_id")
                else None,
                "created_by": UUID(payload.get("created_by"))
                if payload.get("created_by")
                else None,
            }
        elif event_type == "SalesOrderFulfilled":
            return {
                "sales_id": payload.get("order_id"),
                "sales_number": payload.get("order_number"),
                "customer_id": payload.get("customer_id"),
                "customer_code": payload.get("customer_code"),
                "invoice_date": datetime.now(UTC).date(),
                "lines": payload.get("items", []),
                "discount_percent": payload.get("discount", 0),
                "sales_order_id": payload.get("order_id"),
                "legal_entity_id": UUID(payload.get("legal_entity_id"))
                if payload.get("legal_entity_id")
                else None,
                "created_by": UUID(payload.get("created_by"))
                if payload.get("created_by")
                else None,
            }
        else:
            return {
                "sales_id": payload.get("id"),
                "sales_number": payload.get("number"),
                "customer_id": payload.get("customer_id"),
                "customer_code": payload.get("customer_code"),
                "invoice_date": self._parse_date(payload.get("date")) or datetime.now(UTC).date(),
                "lines": payload.get("lines", []),
                "discount_percent": payload.get("discount", 0),
                "legal_entity_id": UUID(payload.get("legal_entity_id"))
                if payload.get("legal_entity_id")
                else None,
                "created_by": UUID(payload.get("created_by"))
                if payload.get("created_by")
                else None,
            }

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

    async def _get_customer(self, customer_id: Any) -> CustomerAggregate:
        if isinstance(customer_id, str):
            try:
                customer_uuid = UUID(customer_id)
                customer = await self._customer_repo.get_by_id(customer_uuid)
                if customer:
                    return customer
            except ValueError:
                pass
        if isinstance(customer_id, str):
            customer = await self._customer_repo.get_by_code(customer_id)
            if customer:
                return customer
        raise CustomerNotFoundError(f"Customer not found for identifier: {customer_id}")

    def _calculate_invoice_lines(
        self, sales_data: dict[str, Any], customer: CustomerAggregate
    ) -> list[dict[str, Any]]:
        lines = []
        sales_lines = sales_data.get("lines", [])
        for idx, line in enumerate(sales_lines):
            quantity = Decimal(str(line.get("quantity", 1)))
            unit_price = Decimal(str(line.get("unit_price", 0)))
            total_amount = quantity * unit_price
            tax_rate = DEFAULT_TAX_RATE
            tax_amount = total_amount * tax_rate
            discount_percent = Decimal(str(line.get("discount_percent", 0)))
            discount_amount = total_amount * (discount_percent / 100)
            net_amount = total_amount - discount_amount
            lines.append(
                {
                    "line_number": idx + 1,
                    "description": line.get("description", line.get("product_name", "")),
                    "quantity": float(quantity),
                    "unit_price": float(unit_price),
                    "tax_rate": float(tax_rate),
                    "discount_percent": float(discount_percent),
                    "account_code": line.get("account_code", "4-1100"),
                    "total_amount": float(net_amount + tax_amount),
                    "tax_amount": float(tax_amount),
                    "net_amount": float(net_amount),
                }
            )
        if not lines:
            raise InvalidEventDataError("No lines found in sales event")
        return lines

    def _calculate_due_date(self, invoice_date: date) -> date:
        return invoice_date + timedelta(days=30)

    async def get_mapping(self, sales_id: str) -> str | None:
        return self._mapping_cache.get(sales_id)

    async def reset(self) -> None:
        self._processed_events.clear()
        self._mapping_cache.clear()
        self._version += 1
        logger.info("SalesToARTransformer reset")

    def validate(self) -> dict[str, Any]:
        errors = []
        if self._ar_service is None:
            errors.append("AR Service not initialized")
        if self._customer_repo is None:
            errors.append("Customer repository not initialized")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["processed_events_count"] = len(self._processed_events)
        data["mapping_cache_size"] = len(self._mapping_cache)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SalesToARTransformer:
        # Factory will set dependencies; this is for serialization only
        instance = cls.__new__(cls)
        instance._version = data.get("version", 1)
        instance._transformer_id = data.get("transformer_id", str(uuid4()))
        instance._command_bus = None
        instance._ar_service = None
        instance._customer_repo = None
        instance._mapping_cache = {}
        instance._processed_events = set()
        return instance

    def clone(self) -> SalesToARTransformer:
        new = SalesToARTransformer(
            command_bus=self._command_bus,
            ar_service=self._ar_service,
            customer_repo=self._customer_repo,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._transformer_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        snap = super().snapshot()
        snap["processed_events_count"] = len(self._processed_events)
        return snap

    def touch(self, touched_by: str) -> SalesToARTransformer:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# TRANSFORMER FACTORY & EVENT HANDLER
# ============================================================================
_sales_to_ar_transformer: SalesToARTransformer | None = None


async def get_sales_to_ar_transformer() -> SalesToARTransformer:
    global _sales_to_ar_transformer
    if _sales_to_ar_transformer is None:
        # Composition Root: use container to resolve dependencies
        from bootstrap.dependency_container.ioc_container import get_container

        container = get_container()
        command_bus = container.resolve(UnifiedCommandBus)
        ar_service = container.resolve(ARService)
        customer_repo = container.resolve(CustomerRepositoryPort)
        _sales_to_ar_transformer = SalesToARTransformer(
            command_bus=command_bus,
            ar_service=ar_service,
            customer_repo=customer_repo,
        )
    return _sales_to_ar_transformer


async def handle_sales_event(envelope: EventEnvelope) -> None:
    transformer = await get_sales_to_ar_transformer()
    await transformer.transform(envelope)


__all__ = [
    "CustomerNotFoundError",
    "InvalidEventDataError",
    "SalesToARTransformer",
    "SalesToARTransformerError",
    "get_sales_to_ar_transformer",
    "handle_sales_event",
]