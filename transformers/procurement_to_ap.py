#!/usr/bin/env python3
"""
Module: procurement_to_ap.py
Layer: Transformers
Responsibility: Mentransformasi event dari sistem procurement (Purchase Order,
               Goods Receipt Note, Purchase Invoice) menjadi command untuk membuat
               AP Invoice.

Metode yang ditambahkan:
- BaseTransformer dengan entity dasar: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk ProcurementToAPTransformer.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from application.commands_cqrs.command_bus_unified import UnifiedCommandBus
from application.dto_objects.ap_invoice_request import APInvoiceCreateRequest
from application.service_layer.service_ap import APService
from bootstrap.dependency_container.ioc_container import get_container
from domain.subledger_ap.three_way_match_engine import ThreeWayMatchEngine, ThreeWayMatchResult
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.customer_supplier_repository_port import SupplierRepositoryPort
from ports.primary.goods_receipt_repository_port import GoodsReceiptRepositoryPort
from ports.primary.purchase_order_repository_port import PurchaseOrderRepositoryPort

if TYPE_CHECKING:
    from domain.customer_supplier_employee.supplier_aggregate_root import SupplierAggregate
    from event_gateway.event_gate_singleton import EventEnvelope

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================
DEFAULT_TAX_RATE = Decimal("0.11")
DEFAULT_CURRENCY = "IDR"
DEFAULT_PAYMENT_TERM_DAYS = 30
HANDLED_EVENT_TYPES = [
    "PurchaseInvoiceApproved",
    "GoodsReceiptConfirmed",
    "PurchaseOrderCompleted",
    "PurchaseInvoiceReceived",
    "ProcurementInvoiceReady",
]
MATCH_TOLERANCE_PERCENT = Decimal("0.05")


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
class ProcurementToAPTransformerError(Exception):
    pass


class SupplierNotFoundError(ProcurementToAPTransformerError):
    pass


class InvalidEventDataError(ProcurementToAPTransformerError):
    pass


class ThreeWayMatchFailedError(ProcurementToAPTransformerError):
    pass


class DuplicateInvoiceError(ProcurementToAPTransformerError):
    pass


# ============================================================================
# ProcurementToAPTransformer (dengan entity dasar)
# ============================================================================
class ProcurementToAPTransformer(BaseTransformer):
    def __init__(self):
        super().__init__("ProcurementToAPTransformer")
        self._command_bus: UnifiedCommandBus | None = None
        self._ap_service: APService | None = None
        self._supplier_repo: SupplierRepositoryPort | None = None
        self._po_repo: PurchaseOrderRepositoryPort | None = None
        self._grn_repo: GoodsReceiptRepositoryPort | None = None
        self._match_engine = ThreeWayMatchEngine(tolerance_percent=MATCH_TOLERANCE_PERCENT)
        self._mapping_cache: dict[str, str] = {}
        self._processed_events: set = set()

    async def _get_command_bus(self) -> UnifiedCommandBus:
        if self._command_bus is None:
            container = get_container()
            self._command_bus = container.resolve(UnifiedCommandBus)
        return self._command_bus

    async def _get_ap_service(self) -> APService:
        if self._ap_service is None:
            container = get_container()
            self._ap_service = container.resolve(APService)
        return self._ap_service

    async def _get_supplier_repo(self) -> SupplierRepositoryPort:
        if self._supplier_repo is None:
            container = get_container()
            self._supplier_repo = container.resolve(SupplierRepositoryPort)
        return self._supplier_repo

    async def _get_po_repo(self) -> PurchaseOrderRepositoryPort:
        if self._po_repo is None:
            container = get_container()
            self._po_repo = container.resolve(PurchaseOrderRepositoryPort)
        return self._po_repo

    async def _get_grn_repo(self) -> GoodsReceiptRepositoryPort:
        if self._grn_repo is None:
            container = get_container()
            self._grn_repo = container.resolve(GoodsReceiptRepositoryPort)
        return self._grn_repo

    async def transform(self, envelope: EventEnvelope) -> None:
        event_type = envelope.event_type
        event_id = str(envelope.id)
        event_payload = envelope.payload

        if event_id in self._processed_events:
            logger.debug(f"Event {event_id} already processed, skipping")
            return
        if event_type not in HANDLED_EVENT_TYPES:
            logger.debug(f"Event type {event_type} not handled by ProcurementToAPTransformer")
            return

        logger.info(f"Transforming event {event_type} to AP Invoice command")

        try:
            procurement_data = await self._extract_procurement_data(event_payload, event_type)
            supplier = await self._get_supplier(procurement_data["supplier_id"])
            if procurement_data.get("invoice_number_vendor"):
                duplicate = await self._check_duplicate_invoice(
                    procurement_data["invoice_number_vendor"], supplier.id
                )
                if duplicate:
                    raise DuplicateInvoiceError(
                        f"Invoice {procurement_data['invoice_number_vendor']} already exists for supplier {supplier.supplier_code}"
                    )
            match_result = None
            if procurement_data.get("purchase_order_id") and procurement_data.get(
                "goods_receipt_id"
            ):
                match_result = await self._perform_three_way_match(
                    po_id=procurement_data["purchase_order_id"],
                    grn_id=procurement_data["goods_receipt_id"],
                    invoice_lines=procurement_data.get("lines", []),
                )
                if match_result and match_result.match_status == "mismatch":
                    logger.warning(
                        f"3-way match mismatch for event {event_id}: {match_result.discrepancies}"
                    )
                    await trigger_alert(
                        title="3-Way Match Mismatch",
                        message=f"PO/GRN/Invoice mismatch for procurement {procurement_data.get('procurement_id')}: {match_result.discrepancies}",
                        severity="warning",
                        source="ProcurementToAPTransformer",
                    )
                    procurement_data["match_status"] = "mismatch"
            lines = self._calculate_invoice_lines(procurement_data, supplier, match_result)
            create_request = APInvoiceCreateRequest(
                vendor_id=supplier.id,
                vendor_code=supplier.supplier_code,
                invoice_date=procurement_data["invoice_date"],
                due_date=procurement_data.get(
                    "due_date", self._calculate_due_date(procurement_data["invoice_date"])
                ),
                invoice_number_vendor=procurement_data.get("invoice_number_vendor", ""),
                lines=lines,
                description=f"Purchase Invoice: {procurement_data.get('procurement_number', 'N/A')}",
                reference_number=procurement_data.get("procurement_number"),
                purchase_order_id=procurement_data.get("purchase_order_id"),
                goods_receipt_note_id=procurement_data.get("goods_receipt_id"),
                use_tax=True,
                discount_global=procurement_data.get("discount_percent", 0),
                created_by=procurement_data.get("created_by")
                or UUID("00000000-0000-0000-0000-000000000000"),
                legal_entity_id=envelope.metadata.get(
                    "legal_entity_id", procurement_data.get("legal_entity_id")
                ),
            )
            command_bus = await self._get_command_bus()
            result = await command_bus.dispatch(
                {"type": "ap.invoice.create", "data": create_request.to_dict()}
            )
            procurement_id = procurement_data.get("procurement_id") or procurement_data.get(
                "purchase_order_id"
            )
            if procurement_id:
                self._mapping_cache[str(procurement_id)] = result["id"]
            self._processed_events.add(event_id)
            logger.info(
                f"AP Invoice created: {result['invoice_number']} from procurement event {event_id}"
            )
            if match_result and match_result.match_status == "mismatch":
                await self._flag_invoice_for_review(result["id"], match_result.discrepancies)
        except (SupplierNotFoundError, InvalidEventDataError, DuplicateInvoiceError):
            raise
        except Exception as e:
            logger.exception(f"Failed to transform event {event_id}: {e}")
            await trigger_alert(
                title="Procurement to AP Transformation Failed",
                message=f"Error: {str(e)[:200]}",
                severity="error",
                source="ProcurementToAPTransformer",
            )
            raise ProcurementToAPTransformerError(f"Transformation failed: {e}") from e

    async def _extract_procurement_data(
        self, payload: dict[str, Any], event_type: str
    ) -> dict[str, Any]:
        base_data = {
            "procurement_id": payload.get("id")
            or payload.get("purchase_order_id")
            or payload.get("invoice_id"),
            "procurement_number": payload.get("number")
            or payload.get("po_number")
            or payload.get("invoice_number"),
            "supplier_id": payload.get("supplier_id") or payload.get("vendor_id"),
            "supplier_code": payload.get("supplier_code") or payload.get("vendor_code"),
            "invoice_date": datetime.now(UTC).date(),
            "lines": payload.get("lines", payload.get("items", [])),
            "discount_percent": payload.get("discount_percent", 0),
            "legal_entity_id": UUID(payload.get("legal_entity_id"))
            if payload.get("legal_entity_id")
            else None,
            "created_by": UUID(payload.get("created_by")) if payload.get("created_by") else None,
        }
        if event_type in ("PurchaseInvoiceApproved", "PurchaseInvoiceReceived"):
            base_data.update(
                {
                    "procurement_id": payload.get("invoice_id"),
                    "procurement_number": payload.get("invoice_number"),
                    "invoice_number_vendor": payload.get("vendor_invoice_number"),
                    "invoice_date": self._parse_date(payload.get("invoice_date"))
                    or datetime.now(UTC).date(),
                    "due_date": self._parse_date(payload.get("due_date")),
                    "purchase_order_id": payload.get("purchase_order_id"),
                    "goods_receipt_id": payload.get("goods_receipt_note_id"),
                    "lines": payload.get("lines", []),
                }
            )
        elif event_type == "GoodsReceiptConfirmed":
            base_data.update(
                {
                    "procurement_id": payload.get("grn_id"),
                    "procurement_number": payload.get("grn_number"),
                    "purchase_order_id": payload.get("purchase_order_id"),
                    "goods_receipt_id": payload.get("grn_id"),
                    "invoice_date": self._parse_date(payload.get("receipt_date"))
                    or datetime.now(UTC).date(),
                    "lines": payload.get("received_items", []),
                }
            )
        elif event_type == "PurchaseOrderCompleted":
            base_data.update(
                {
                    "procurement_id": payload.get("po_id"),
                    "procurement_number": payload.get("po_number"),
                    "purchase_order_id": payload.get("po_id"),
                    "invoice_date": self._parse_date(payload.get("completed_date"))
                    or datetime.now(UTC).date(),
                    "lines": payload.get("po_lines", []),
                }
            )
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

    async def _get_supplier(self, supplier_id: Any) -> SupplierAggregate:
        supplier_repo = await self._get_supplier_repo()
        if isinstance(supplier_id, str):
            try:
                supplier_uuid = UUID(supplier_id)
                supplier = await supplier_repo.get_by_id(supplier_uuid)
                if supplier:
                    return supplier
            except ValueError:
                pass
        if isinstance(supplier_id, str):
            supplier = await supplier_repo.get_by_code(supplier_id)
            if supplier:
                return supplier
        raise SupplierNotFoundError(f"Supplier not found for identifier: {supplier_id}")

    async def _check_duplicate_invoice(self, invoice_number_vendor: str, vendor_id: UUID) -> bool:
        ap_service = await self._get_ap_service()
        existing = await ap_service.get_invoice_by_vendor_number(invoice_number_vendor, vendor_id)
        return existing is not None

    async def _perform_three_way_match(
        self, po_id: UUID, grn_id: UUID, invoice_lines: list[dict]
    ) -> ThreeWayMatchResult | None:
        try:
            po_repo = await self._get_po_repo()
            grn_repo = await self._get_grn_repo()
            po = await po_repo.get_by_id(po_id)
            grn = await grn_repo.get_by_id(grn_id)
            if not po or not grn:
                logger.warning(f"PO {po_id} or GRN {grn_id} not found for 3-way match")
                return None
            match_result = await self._match_engine.match(po, grn, invoice_lines)
            return match_result
        except Exception as e:
            logger.error(f"3-way match failed: {e}")
            return None

    def _calculate_invoice_lines(
        self,
        procurement_data: dict[str, Any],
        supplier: SupplierAggregate,
        match_result: ThreeWayMatchResult | None,
    ) -> list[dict[str, Any]]:
        lines = []
        procurement_lines = procurement_data.get("lines", [])
        for idx, line in enumerate(procurement_lines):
            quantity = Decimal(str(line.get("quantity", 1)))
            unit_price = Decimal(str(line.get("unit_price", 0)))
            if match_result and match_result.match_status == "match":
                unit_price = (
                    Decimal(str(match_result.matched_price))
                    if match_result.matched_price
                    else unit_price
                )
            total_amount = quantity * unit_price
            tax_rate = DEFAULT_TAX_RATE
            tax_amount = total_amount * tax_rate
            discount_percent = Decimal(str(line.get("discount_percent", 0)))
            discount_amount = total_amount * (discount_percent / 100)
            net_amount = total_amount - discount_amount
            account_code = line.get("account_code", "5-1100")
            lines.append(
                {
                    "line_number": idx + 1,
                    "description": line.get(
                        "description", line.get("product_name", line.get("item_name", ""))
                    ),
                    "quantity": float(quantity),
                    "unit_price": float(unit_price),
                    "tax_rate": float(tax_rate),
                    "discount_percent": float(discount_percent),
                    "account_code": account_code,
                    "total_amount": float(net_amount + tax_amount),
                    "tax_amount": float(tax_amount),
                    "net_amount": float(net_amount),
                    "purchase_order_line_id": line.get("po_line_id") if match_result else None,
                    "goods_receipt_line_id": line.get("grn_line_id") if match_result else None,
                }
            )
        if not lines:
            raise InvalidEventDataError("No lines found in procurement event")
        return lines

    def _calculate_due_date(self, invoice_date: date) -> date:
        return invoice_date + timedelta(days=DEFAULT_PAYMENT_TERM_DAYS)

    async def _flag_invoice_for_review(self, invoice_id: UUID, discrepancies: list[str]) -> None:
        ap_service = await self._get_ap_service()
        await ap_service.flag_for_review(invoice_id, discrepancies)
        logger.warning(f"Invoice {invoice_id} flagged for review due to 3-way match mismatch")

    async def get_mapping(self, procurement_id: str) -> str | None:
        return self._mapping_cache.get(procurement_id)

    async def reset(self) -> None:
        self._processed_events.clear()
        self._mapping_cache.clear()
        self._version += 1
        logger.info("ProcurementToAPTransformer reset")

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self._match_engine is None:
            errors.append("Match engine not initialized")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["processed_events_count"] = len(self._processed_events)
        data["mapping_cache_size"] = len(self._mapping_cache)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProcurementToAPTransformer:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._transformer_id = data.get("transformer_id", str(uuid4()))
        return instance

    def clone(self) -> ProcurementToAPTransformer:
        new = ProcurementToAPTransformer()
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._transformer_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        snap = super().snapshot()
        snap["processed_events_count"] = len(self._processed_events)
        return snap

    def touch(self, touched_by: str) -> ProcurementToAPTransformer:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# TRANSFORMER FACTORY & EVENT HANDLER
# ============================================================================
_procurement_to_ap_transformer: ProcurementToAPTransformer | None = None


async def get_procurement_to_ap_transformer() -> ProcurementToAPTransformer:
    global _procurement_to_ap_transformer
    if _procurement_to_ap_transformer is None:
        _procurement_to_ap_transformer = ProcurementToAPTransformer()
    return _procurement_to_ap_transformer


async def handle_procurement_event(envelope: EventEnvelope) -> None:
    transformer = await get_procurement_to_ap_transformer()
    await transformer.transform(envelope)


__all__ = [
    "DuplicateInvoiceError",
    "InvalidEventDataError",
    "ProcurementToAPTransformer",
    "ProcurementToAPTransformerError",
    "SupplierNotFoundError",
    "ThreeWayMatchFailedError",
    "get_procurement_to_ap_transformer",
    "handle_procurement_event",
]
