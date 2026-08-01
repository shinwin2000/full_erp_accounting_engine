# tests/transformers/test_procurement_to_ap.py
"""
Comprehensive tests for transformers/procurement_to_ap.py
Covers all methods including private helpers, edge cases, and exceptions.
"""

import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from transformers.procurement_to_ap import (
    BaseTransformer,
    DuplicateInvoiceError,
    InvalidEventDataError,
    ProcurementToAPTransformer,
    ProcurementToAPTransformerError,
    SupplierNotFoundError,
    ThreeWayMatchFailedError,
    _create_mock_dependency,
    get_procurement_to_ap_transformer,
    handle_procurement_event,
)

# ============================================================================
# BaseTransformer tests
# ============================================================================

class TestBaseTransformer:
    def test_construction(self):
        t = BaseTransformer(name="test")
        assert t.name == "test"
        assert t._version == 1
        assert t._audit_trail == []
        assert len(t._snapshots) == 0  # snapshot not taken on init
        assert t._transformer_id is not None

    def test_construction_default_name(self):
        t = BaseTransformer()
        assert t.name == "default"

    def test_take_snapshot(self):
        t = BaseTransformer()
        t._take_snapshot()
        assert len(t._snapshots) == 1
        snap = t._snapshots[0]
        assert snap["version"] == 1
        assert snap["name"] == "default"
        assert "timestamp" in snap

    def test_take_snapshot_limit(self):
        t = BaseTransformer()
        for _i in range(15):
            t._take_snapshot()
        assert len(t._snapshots) == 10

    def test_record_audit(self):
        t = BaseTransformer()
        t._record_audit("TEST", "user", {"detail": "value"})
        assert len(t._audit_trail) == 1
        record = t._audit_trail[0]
        assert record["action"] == "TEST"
        assert record["performed_by"] == "user"
        assert record["version"] == 1

    def test_validate(self):
        t = BaseTransformer()
        result = t.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_to_dict(self):
        t = BaseTransformer(name="test")
        d = t.to_dict()
        assert d["name"] == "test"
        assert d["version"] == 1
        assert "transformer_id" in d

    def test_from_dict(self):
        data = {"name": "test", "version": 3, "transformer_id": "123"}
        t = BaseTransformer.from_dict(data)
        assert t.name == "test"
        assert t._version == 3
        assert t._transformer_id == "123"

    def test_from_dict_missing_name(self):
        t = BaseTransformer.from_dict({})
        assert t.name == "default"

    def test_clone(self):
        t = BaseTransformer(name="test")
        t._version = 5
        cloned = t.clone()
        assert cloned is not t
        assert cloned.name == "test"
        assert cloned._version == 6
        assert len(cloned._audit_trail) == 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self):
        t = BaseTransformer()
        snap = t.snapshot()
        assert snap["version"] == 1
        assert snap["name"] == "default"
        assert "timestamp" in snap

    def test_version(self):
        t = BaseTransformer()
        assert t.version() == 1
        t._version = 10
        assert t.version() == 10

    def test_audit_trail(self):
        t = BaseTransformer()
        t._record_audit("A1", "u1", {})
        t._record_audit("A2", "u2", {})
        trail = t.audit_trail()
        assert len(trail) == 2
        limited = t.audit_trail(limit=1)
        assert len(limited) == 1
        assert limited[0]["action"] == "A2"

    def test_touch(self):
        t = BaseTransformer()
        initial = t.version()
        result = t.touch("tester")
        assert result is t
        assert t.version() == initial + 1
        trail = t.audit_trail()
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "tester"


# ============================================================================
# Exception tests
# ============================================================================

class TestProcurementToAPTransformerError:
    def test_construction(self):
        e = ProcurementToAPTransformerError("test")
        assert str(e) == "test"


class TestSupplierNotFoundError:
    def test_construction(self):
        e = SupplierNotFoundError("not found")
        assert str(e) == "not found"
        assert issubclass(SupplierNotFoundError, ProcurementToAPTransformerError)


class TestInvalidEventDataError:
    def test_construction(self):
        e = InvalidEventDataError("invalid")
        assert str(e) == "invalid"
        assert issubclass(InvalidEventDataError, ProcurementToAPTransformerError)

    def test_raise(self):
        with pytest.raises(InvalidEventDataError, match="invalid"):
            raise InvalidEventDataError("invalid")


class TestThreeWayMatchFailedError:
    def test_construction(self):
        e = ThreeWayMatchFailedError("failed")
        assert str(e) == "failed"


class TestDuplicateInvoiceError:
    def test_construction(self):
        e = DuplicateInvoiceError("duplicate")
        assert str(e) == "duplicate"


# ============================================================================
# ProcurementToAPTransformer tests
# ============================================================================

class TestProcurementToAPTransformer:
    @pytest.fixture
    def mock_deps(self):
        return {
            "command_bus": AsyncMock(),
            "ap_service": AsyncMock(),
            "supplier_repo": AsyncMock(),
            "po_repo": AsyncMock(),
            "grn_repo": AsyncMock(),
        }

    @pytest.fixture
    def transformer(self, mock_deps):
        with patch('transformers.procurement_to_ap.ThreeWayMatchEngine') as mock_match_engine:
            mock_match_engine.return_value = MagicMock()
            t = ProcurementToAPTransformer(
                command_bus=mock_deps["command_bus"],
                ap_service=mock_deps["ap_service"],
                supplier_repo=mock_deps["supplier_repo"],
                po_repo=mock_deps["po_repo"],
                grn_repo=mock_deps["grn_repo"],
            )
            return t

    @pytest.fixture
    def mock_supplier(self):
        supplier = MagicMock()
        supplier.id = UUID("12345678-1234-5678-1234-567812345678")
        supplier.supplier_code = "SUP001"
        return supplier

    # ---- Constructor ----
    def test_construction(self, mock_deps):
        with patch('transformers.procurement_to_ap.ThreeWayMatchEngine'):
            t = ProcurementToAPTransformer(
                command_bus=mock_deps["command_bus"],
                ap_service=mock_deps["ap_service"],
                supplier_repo=mock_deps["supplier_repo"],
                po_repo=mock_deps["po_repo"],
                grn_repo=mock_deps["grn_repo"],
            )
            assert t.name == "ProcurementToAPTransformer"
            assert t._command_bus == mock_deps["command_bus"]
            assert t._match_engine is not None

    # ---- _parse_date ----
    def test_parse_date_none(self, transformer):
        result = transformer._parse_date(None)
        assert result is None

    def test_parse_date_date_object(self, transformer):
        d = date(2026, 1, 15)
        result = transformer._parse_date(d)
        assert result == d

    def test_parse_date_iso_string(self, transformer):
        result = transformer._parse_date("2026-01-15T10:30:00")
        assert result == date(2026, 1, 15)

    def test_parse_date_ymd_string(self, transformer):
        result = transformer._parse_date("2026-01-15")
        assert result == date(2026, 1, 15)

    def test_parse_date_invalid_string(self, transformer):
        result = transformer._parse_date("invalid")
        assert result is None

    def test_parse_date_other_type(self, transformer):
        result = transformer._parse_date(123)
        assert result is None

    # ---- _calculate_due_date ----
    def test_calculate_due_date(self, transformer):
        invoice_date = date(2026, 1, 15)
        due = transformer._calculate_due_date(invoice_date)
        assert due == invoice_date + timedelta(days=30)

    # ---- _calculate_invoice_lines ----
    def test_calculate_invoice_lines_success(self, transformer, mock_supplier):
        procurement_data = {
            "lines": [
                {
                    "quantity": 2,
                    "unit_price": 100000,
                    "discount_percent": 5,
                    "description": "Item A",
                    "account_code": "5-1100",
                },
                {
                    "quantity": 1,
                    "unit_price": 200000,
                    "discount_percent": 0,
                    "description": "Item B",
                    "account_code": "5-1200",
                },
            ]
        }
        lines = transformer._calculate_invoice_lines(procurement_data, mock_supplier, None)
        assert len(lines) == 2
        # Line 1: qty=2, price=100,000, disc=5%, tax=11%
        # total=200,000, disc=10,000, net=190,000, tax=20,900, total=210,900
        assert lines[0]["quantity"] == 2.0
        assert lines[0]["unit_price"] == 100000.0
        assert lines[0]["discount_percent"] == 5.0
        assert lines[0]["net_amount"] == 190000.0
        assert lines[0]["tax_amount"] == 20900.0
        assert lines[0]["total_amount"] == 210900.0
        assert lines[0]["account_code"] == "5-1100"
        # Line 2: qty=1, price=200,000, no disc
        assert lines[1]["net_amount"] == 200000.0
        assert lines[1]["tax_amount"] == 22000.0
        assert lines[1]["total_amount"] == 222000.0

    def test_calculate_invoice_lines_with_match_result(self, transformer, mock_supplier):
        procurement_data = {
            "lines": [
                {
                    "quantity": 1,
                    "unit_price": 100000,
                    "discount_percent": 0,
                    "description": "Item",
                    "account_code": "5-1100",
                }
            ]
        }
        match_result = MagicMock()
        match_result.match_status = "match"
        match_result.matched_price = 90000
        lines = transformer._calculate_invoice_lines(procurement_data, mock_supplier, match_result)
        assert lines[0]["unit_price"] == 90000.0
        assert lines[0]["purchase_order_line_id"] is None

    def test_calculate_invoice_lines_empty_raises(self, transformer, mock_supplier):
        procurement_data = {"lines": []}
        with pytest.raises(InvalidEventDataError, match="No lines found"):
            transformer._calculate_invoice_lines(procurement_data, mock_supplier, None)

    # ---- _extract_procurement_data ----
    def test_extract_procurement_data_general(self, transformer):
        payload = {
            "id": "123",
            "number": "PO-001",
            "supplier_id": "sup-1",
            "supplier_code": "SUP01",
            "discount_percent": 10,
            "legal_entity_id": "12345678-1234-5678-1234-567812345678",
            "created_by": "87654321-1234-5678-1234-567812345678",
            "lines": [{"item": "A"}],
        }
        result = asyncio.run(transformer._extract_procurement_data(payload, "UnknownEvent"))
        assert result["procurement_id"] == "123"
        assert result["procurement_number"] == "PO-001"
        assert result["supplier_id"] == "sup-1"
        assert result["discount_percent"] == 10
        assert result["legal_entity_id"] == UUID("12345678-1234-5678-1234-567812345678")
        assert result["created_by"] == UUID("87654321-1234-5678-1234-567812345678")
        assert isinstance(result["invoice_date"], date)

    def test_extract_procurement_data_purchase_invoice_approved(self, transformer):
        payload = {
            "invoice_id": "inv-1",
            "invoice_number": "INV-001",
            "vendor_invoice_number": "VEND-001",
            "invoice_date": "2026-01-15",
            "due_date": "2026-02-15",
            "purchase_order_id": "po-1",
            "goods_receipt_note_id": "grn-1",
            "lines": [{"qty": 1}],
            "supplier_id": "sup-1",
        }
        result = asyncio.run(transformer._extract_procurement_data(payload, "PurchaseInvoiceApproved"))
        assert result["procurement_id"] == "inv-1"
        assert result["procurement_number"] == "INV-001"
        assert result["invoice_number_vendor"] == "VEND-001"
        assert result["invoice_date"] == date(2026, 1, 15)
        assert result["due_date"] == date(2026, 2, 15)
        assert result["purchase_order_id"] == "po-1"
        assert result["goods_receipt_id"] == "grn-1"

    def test_extract_procurement_data_goods_receipt(self, transformer):
        payload = {
            "grn_id": "grn-1",
            "grn_number": "GRN-001",
            "purchase_order_id": "po-1",
            "receipt_date": "2026-01-20",
            "received_items": [{"item": "A"}],
            "supplier_id": "sup-1",
        }
        result = asyncio.run(transformer._extract_procurement_data(payload, "GoodsReceiptConfirmed"))
        assert result["procurement_id"] == "grn-1"
        assert result["procurement_number"] == "GRN-001"
        assert result["purchase_order_id"] == "po-1"
        assert result["goods_receipt_id"] == "grn-1"
        assert result["invoice_date"] == date(2026, 1, 20)

    def test_extract_procurement_data_po_completed(self, transformer):
        payload = {
            "po_id": "po-1",
            "po_number": "PO-001",
            "completed_date": "2026-01-25",
            "po_lines": [{"item": "A"}],
            "supplier_id": "sup-1",
        }
        result = asyncio.run(transformer._extract_procurement_data(payload, "PurchaseOrderCompleted"))
        assert result["procurement_id"] == "po-1"
        assert result["procurement_number"] == "PO-001"
        assert result["purchase_order_id"] == "po-1"
        assert result["invoice_date"] == date(2026, 1, 25)

    # ---- _get_supplier ----
    @pytest.mark.asyncio
    async def test_get_supplier_by_uuid(self, transformer, mock_deps, mock_supplier):
        supplier_id = UUID("12345678-1234-5678-1234-567812345678")
        mock_deps["supplier_repo"].get_by_id.return_value = mock_supplier
        result = await transformer._get_supplier(str(supplier_id))
        assert result == mock_supplier
        mock_deps["supplier_repo"].get_by_id.assert_called_with(supplier_id)

    @pytest.mark.asyncio
    async def test_get_supplier_by_code(self, transformer, mock_deps, mock_supplier):
        supplier_id = "SUP001"
        mock_deps["supplier_repo"].get_by_id.return_value = None
        mock_deps["supplier_repo"].get_by_code.return_value = mock_supplier
        result = await transformer._get_supplier(supplier_id)
        assert result == mock_supplier
        mock_deps["supplier_repo"].get_by_code.assert_called_with(supplier_id)

    @pytest.mark.asyncio
    async def test_get_supplier_not_found(self, transformer, mock_deps):
        supplier_id = "unknown"
        mock_deps["supplier_repo"].get_by_id.return_value = None
        mock_deps["supplier_repo"].get_by_code.return_value = None
        with pytest.raises(SupplierNotFoundError, match="Supplier not found"):
            await transformer._get_supplier(supplier_id)

    # ---- _check_duplicate_invoice ----
    @pytest.mark.asyncio
    async def test_check_duplicate_invoice_found(self, transformer, mock_deps):
        vendor_id = UUID("12345678-1234-5678-1234-567812345678")
        mock_deps["ap_service"].get_invoice_by_vendor_number.return_value = {"id": "inv-1"}
        result = await transformer._check_duplicate_invoice("INV-001", vendor_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_check_duplicate_invoice_not_found(self, transformer, mock_deps):
        vendor_id = UUID("12345678-1234-5678-1234-567812345678")
        mock_deps["ap_service"].get_invoice_by_vendor_number.return_value = None
        result = await transformer._check_duplicate_invoice("INV-001", vendor_id)
        assert result is False

    # ---- _perform_three_way_match ----
    @pytest.mark.asyncio
    async def test_perform_three_way_match_success(self, transformer, mock_deps):
        po_id = UUID("12345678-1234-5678-1234-567812345678")
        grn_id = UUID("87654321-1234-5678-1234-567812345678")
        mock_deps["po_repo"].get_by_id.return_value = "PO"
        mock_deps["grn_repo"].get_by_id.return_value = "GRN"
        mock_match_result = MagicMock()
        transformer._match_engine.match = AsyncMock(return_value=mock_match_result)
        result = await transformer._perform_three_way_match(po_id, grn_id, [])
        assert result == mock_match_result

    @pytest.mark.asyncio
    async def test_perform_three_way_match_not_found(self, transformer, mock_deps):
        po_id = UUID("12345678-1234-5678-1234-567812345678")
        grn_id = UUID("87654321-1234-5678-1234-567812345678")
        mock_deps["po_repo"].get_by_id.return_value = None
        mock_deps["grn_repo"].get_by_id.return_value = None
        result = await transformer._perform_three_way_match(po_id, grn_id, [])
        assert result is None

    @pytest.mark.asyncio
    async def test_perform_three_way_match_exception(self, transformer, mock_deps):
        po_id = UUID("12345678-1234-5678-1234-567812345678")
        grn_id = UUID("87654321-1234-5678-1234-567812345678")
        mock_deps["po_repo"].get_by_id.side_effect = Exception("DB error")
        result = await transformer._perform_three_way_match(po_id, grn_id, [])
        assert result is None

    # ---- _flag_invoice_for_review ----
    @pytest.mark.asyncio
    async def test_flag_invoice_for_review(self, transformer, mock_deps):
        invoice_id = UUID("12345678-1234-5678-1234-567812345678")
        discrepancies = ["Price mismatch"]
        await transformer._flag_invoice_for_review(invoice_id, discrepancies)
        mock_deps["ap_service"].flag_for_review.assert_called_with(invoice_id, discrepancies)

    # ---- transform ----
    @pytest.mark.asyncio
    async def test_transform_success(self, transformer, mock_deps, mock_supplier):
        envelope = MagicMock()
        envelope.id = "evt-1"
        envelope.event_type = "PurchaseInvoiceApproved"
        envelope.payload = {
            "invoice_id": "inv-1",
            "invoice_number": "INV-001",
            "vendor_invoice_number": "VEND-001",
            "invoice_date": "2026-01-15",
            "due_date": "2026-02-15",
            "purchase_order_id": "po-1",
            "goods_receipt_note_id": "grn-1",
            "lines": [{"quantity": 1, "unit_price": 100000, "discount_percent": 0, "description": "Item"}],
            "supplier_id": "sup-1",
            "legal_entity_id": "12345678-1234-5678-1234-567812345678",
            "created_by": "87654321-1234-5678-1234-567812345678",
        }
        envelope.metadata = {"legal_entity_id": "12345678-1234-5678-1234-567812345678"}

        # Mock dependencies
        mock_deps["supplier_repo"].get_by_id.return_value = mock_supplier
        mock_deps["ap_service"].get_invoice_by_vendor_number.return_value = None
        mock_deps["po_repo"].get_by_id.return_value = "PO"
        mock_deps["grn_repo"].get_by_id.return_value = "GRN"
        mock_match_result = MagicMock()
        mock_match_result.match_status = "match"
        mock_match_result.discrepancies = []
        mock_match_result.matched_price = None
        transformer._match_engine.match = AsyncMock(return_value=mock_match_result)

        # Mock command bus dispatch result
        mock_deps["command_bus"].dispatch.return_value = {"id": "ap-inv-1", "invoice_number": "AP-001"}

        await transformer.transform(envelope)
        mock_deps["command_bus"].dispatch.assert_called_once()
        # Check that mapping cache is updated
        assert "inv-1" in transformer._mapping_cache
        assert transformer._mapping_cache["inv-1"] == "ap-inv-1"
        assert "evt-1" in transformer._processed_events

    @pytest.mark.asyncio
    async def test_transform_already_processed(self, transformer):
        envelope = MagicMock()
        envelope.id = "evt-1"
        transformer._processed_events.add("evt-1")
        await transformer.transform(envelope)
        # No action should be taken
        assert transformer._command_bus.dispatch.call_count == 0

    @pytest.mark.asyncio
    async def test_transform_unhandled_event_type(self, transformer):
        envelope = MagicMock()
        envelope.id = "evt-1"
        envelope.event_type = "Unhandled"
        await transformer.transform(envelope)
        # No action should be taken
        assert transformer._command_bus.dispatch.call_count == 0

    @pytest.mark.asyncio
    async def test_transform_supplier_not_found(self, transformer, mock_deps):
        envelope = MagicMock()
        envelope.id = "evt-1"
        envelope.event_type = "PurchaseInvoiceApproved"
        envelope.payload = {
            "invoice_id": "inv-1",
            "invoice_number": "INV-001",
            "vendor_invoice_number": "VEND-001",
            "invoice_date": "2026-01-15",
            "supplier_id": "unknown",
            "lines": [{"quantity": 1, "unit_price": 100000}],
            "legal_entity_id": "12345678-1234-5678-1234-567812345678",
        }
        envelope.metadata = {}
        mock_deps["supplier_repo"].get_by_id.return_value = None
        mock_deps["supplier_repo"].get_by_code.return_value = None

        with pytest.raises(SupplierNotFoundError):
            await transformer.transform(envelope)

    @pytest.mark.asyncio
    async def test_transform_duplicate_invoice(self, transformer, mock_deps, mock_supplier):
        envelope = MagicMock()
        envelope.id = "evt-1"
        envelope.event_type = "PurchaseInvoiceApproved"
        envelope.payload = {
            "invoice_id": "inv-1",
            "invoice_number": "INV-001",
            "vendor_invoice_number": "VEND-001",
            "invoice_date": "2026-01-15",
            "supplier_id": "sup-1",
            "lines": [{"quantity": 1, "unit_price": 100000}],
            "legal_entity_id": "12345678-1234-5678-1234-567812345678",
        }
        envelope.metadata = {}
        mock_deps["supplier_repo"].get_by_id.return_value = mock_supplier
        mock_deps["ap_service"].get_invoice_by_vendor_number.return_value = {"id": "existing"}

        with pytest.raises(DuplicateInvoiceError, match="already exists"):
            await transformer.transform(envelope)

    @pytest.mark.asyncio
    async def test_transform_three_way_mismatch_alert(self, transformer, mock_deps, mock_supplier):
        envelope = MagicMock()
        envelope.id = "evt-1"
        envelope.event_type = "PurchaseInvoiceApproved"
        envelope.payload = {
            "invoice_id": "inv-1",
            "invoice_number": "INV-001",
            "vendor_invoice_number": "VEND-001",
            "invoice_date": "2026-01-15",
            "purchase_order_id": "po-1",
            "goods_receipt_note_id": "grn-1",
            "lines": [{"quantity": 1, "unit_price": 100000}],
            "supplier_id": "sup-1",
            "legal_entity_id": "12345678-1234-5678-1234-567812345678",
            "created_by": "87654321-1234-5678-1234-567812345678",
        }
        envelope.metadata = {"legal_entity_id": "12345678-1234-5678-1234-567812345678"}

        mock_deps["supplier_repo"].get_by_id.return_value = mock_supplier
        mock_deps["ap_service"].get_invoice_by_vendor_number.return_value = None
        mock_deps["po_repo"].get_by_id.return_value = "PO"
        mock_deps["grn_repo"].get_by_id.return_value = "GRN"
        mock_match_result = MagicMock()
        mock_match_result.match_status = "mismatch"
        mock_match_result.discrepancies = ["Price mismatch"]
        transformer._match_engine.match = AsyncMock(return_value=mock_match_result)

        mock_deps["command_bus"].dispatch.return_value = {"id": "ap-inv-1", "invoice_number": "AP-001"}

        with patch('transformers.procurement_to_ap.trigger_alert') as mock_alert:
            await transformer.transform(envelope)
            mock_alert.assert_called()
            # Check that flag_for_review was called
            mock_deps["ap_service"].flag_for_review.assert_called_once()

    @pytest.mark.asyncio
    async def test_transform_general_exception(self, transformer, mock_deps):
        envelope = MagicMock()
        envelope.id = "evt-1"
        envelope.event_type = "PurchaseInvoiceApproved"
        envelope.payload = {}
        envelope.metadata = {}
        mock_deps["supplier_repo"].get_by_id.side_effect = Exception("DB error")

        with patch('transformers.procurement_to_ap.trigger_alert') as mock_alert:
            with pytest.raises(ProcurementToAPTransformerError, match="Transformation failed"):
                await transformer.transform(envelope)
            mock_alert.assert_called()

    # ---- get_mapping ----
    @pytest.mark.asyncio
    async def test_get_mapping_found(self, transformer):
        transformer._mapping_cache["proc-1"] = "ap-1"
        result = await transformer.get_mapping("proc-1")
        assert result == "ap-1"

    @pytest.mark.asyncio
    async def test_get_mapping_not_found(self, transformer):
        result = await transformer.get_mapping("unknown")
        assert result is None

    # ---- reset ----
    @pytest.mark.asyncio
    async def test_reset(self, transformer):
        transformer._processed_events.add("evt-1")
        transformer._mapping_cache["proc-1"] = "ap-1"
        initial_version = transformer.version()
        await transformer.reset()
        assert transformer._processed_events == set()
        assert transformer._mapping_cache == {}
        assert transformer.version() == initial_version + 1

    # ---- validate ----
    def test_validate_success(self, transformer):
        result = transformer.validate()
        assert result["is_valid"] is True

    def test_validate_no_match_engine(self, transformer):
        transformer._match_engine = None
        result = transformer.validate()
        assert result["is_valid"] is False
        assert "Match engine not initialized" in result["errors"]

    # ---- to_dict ----
    def test_to_dict(self, transformer):
        transformer._processed_events.add("evt-1")
        transformer._mapping_cache["proc-1"] = "ap-1"
        d = transformer.to_dict()
        assert d["name"] == "ProcurementToAPTransformer"
        assert d["processed_events_count"] == 1
        assert d["mapping_cache_size"] == 1

    # ---- from_dict ----
    def test_from_dict(self):
        data = {"version": 3, "transformer_id": "123"}
        with patch('transformers.procurement_to_ap.ThreeWayMatchEngine'):
            t = ProcurementToAPTransformer.from_dict(data)
            assert t._version == 3
            assert t._transformer_id == "123"
            assert t._command_bus is None
            assert t._processed_events == set()
            assert t._match_engine is not None

    # ---- clone ----
    def test_clone(self, transformer):
        transformer._version = 5
        with patch('transformers.procurement_to_ap.ThreeWayMatchEngine'):
            cloned = transformer.clone()
            assert cloned is not transformer
            assert cloned._version == 6
            assert len(cloned._audit_trail) == 1
            assert cloned._audit_trail[0]["action"] == "CLONE"

    # ---- snapshot ----
    def test_snapshot(self, transformer):
        transformer._processed_events.add("evt-1")
        snap = transformer.snapshot()
        assert snap["version"] == 1
        assert snap["name"] == "ProcurementToAPTransformer"
        assert snap["processed_events_count"] == 1

    # ---- touch ----
    def test_touch(self, transformer):
        initial = transformer.version()
        result = transformer.touch("tester")
        assert result is transformer
        assert transformer.version() == initial + 1
        trail = transformer.audit_trail()
        assert trail[-1]["action"] == "TOUCH"


# ============================================================================
# _create_mock_dependency tests
# ============================================================================

class TestCreateMockDependency:
    def test_create_mock_dependency(self):
        result = _create_mock_dependency("SomeClass")
        assert result is not None
        # It returns a MagicMock
        from unittest.mock import MagicMock
        assert isinstance(result, MagicMock)


# ============================================================================
# get_procurement_to_ap_transformer tests
# ============================================================================

class TestGetProcurementToAPTransformer:
    @pytest.mark.asyncio
    async def test_get_transformer_success(self):
        with patch('transformers.procurement_to_ap.get_container') as mock_get_container:
            container = MagicMock()
            container.resolve = MagicMock(side_effect=["cmd", "ap", "supp", "po", "grn"])
            container.resolve_async = None
            mock_get_container.return_value = container

            with patch('transformers.procurement_to_ap.ProcurementToAPTransformer') as mock_transformer:
                mock_transformer.return_value = MagicMock()
                result = await get_procurement_to_ap_transformer()
                assert result is not None
                mock_transformer.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_transformer_fallback(self):
        with patch('transformers.procurement_to_ap.get_container') as mock_get_container:
            mock_get_container.side_effect = Exception("Container error")

            with patch('transformers.procurement_to_ap.ProcurementToAPTransformer') as mock_transformer:
                mock_transformer.return_value = MagicMock()
                result = await get_procurement_to_ap_transformer()
                assert result is not None
                # Should use mock dependencies
                mock_transformer.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_transformer_already_exists(self):
        with patch('transformers.procurement_to_ap._procurement_to_ap_transformer', MagicMock()) as existing:
            result = await get_procurement_to_ap_transformer()
            assert result == existing


# ============================================================================
# handle_procurement_event tests
# ============================================================================

class TestHandleProcurementEvent:
    @pytest.mark.asyncio
    async def test_handle_event(self):
        envelope = MagicMock()
        transformer = AsyncMock()
        transformer.transform = AsyncMock()

        with patch('transformers.procurement_to_ap.get_procurement_to_ap_transformer') as mock_get:
            mock_get.return_value = transformer
            await handle_procurement_event(envelope)
            transformer.transform.assert_called_with(envelope)
