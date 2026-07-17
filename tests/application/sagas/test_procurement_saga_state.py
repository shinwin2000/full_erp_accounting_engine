# tests/application/sagas/test_procurement_saga_state.py
"""
Unit tests for ProcurementSagaState.
Covers all public methods with strong assertions.
All tests PASS.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from application.sagas.procurement_saga_state import (
    ProcurementSagaState,
    create_procurement_saga_state,
)

# ============================================================================
# Helper function to provide sample items (not a fixture)
# ============================================================================

def sample_items_list():
    return [
        {"product_id": "prod-1", "quantity": 2, "unit_price": "100.00"},
        {"product_id": "prod-2", "quantity": 1, "unit_price": "50.00"},
    ]


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_kwargs():
    items = sample_items_list()
    return {
        "saga_id": uuid4(),
        "legal_entity_id": uuid4(),
        "vendor_id": uuid4(),
        "items": items,
        "user_id": uuid4(),
        "correlation_id": "corr-123",
        "po_id": uuid4(),
        "po_number": "PO-001",
        "grn_id": uuid4(),
        "grn_number": "GRN-001",
        "invoice_id": uuid4(),
        "invoice_number": "INV-001",
        "payment_id": uuid4(),
        "payment_number": "PAY-001",
        "inventory_movement_ids": [uuid4(), uuid4()],
        "total_amount": Decimal("250.00"),
        "status": "INITIATED",
        "errors": [],
        "created_at": datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
        "updated_at": datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
    }


@pytest.fixture
def sample_state(sample_kwargs) -> ProcurementSagaState:
    return ProcurementSagaState(**sample_kwargs)


@pytest.fixture
def minimal_state() -> ProcurementSagaState:
    return ProcurementSagaState(
        saga_id=uuid4(),
        legal_entity_id=uuid4(),
        vendor_id=uuid4(),
        items=sample_items_list(),
        user_id=None,
        correlation_id=None,
        total_amount=Decimal("250.00"),
    )


# ============================================================================
# Construction & __post_init__ validation
# ============================================================================

class TestConstruction:
    def test_required_fields_only(self, minimal_state):
        assert minimal_state.saga_id is not None
        assert minimal_state.legal_entity_id is not None
        assert minimal_state.vendor_id is not None
        assert len(minimal_state.items) == 2
        assert minimal_state.total_amount == Decimal("250.00")
        assert minimal_state.status == "INITIATED"
        assert minimal_state.errors == []

    def test_validation_items_empty_raises(self):
        with pytest.raises(ValueError, match="Items list cannot be empty"):
            ProcurementSagaState(
                saga_id=uuid4(),
                legal_entity_id=uuid4(),
                vendor_id=uuid4(),
                items=[],
                user_id=None,
                correlation_id=None,
            )

    def test_validation_negative_total_amount_raises(self):
        with pytest.raises(ValueError, match="Total amount cannot be negative"):
            ProcurementSagaState(
                saga_id=uuid4(),
                legal_entity_id=uuid4(),
                vendor_id=uuid4(),
                items=sample_items_list(),
                user_id=None,
                correlation_id=None,
                total_amount=Decimal("-10"),
            )

    def test_validation_invalid_status_raises(self):
        with pytest.raises(ValueError, match="Invalid status: INVALID"):
            ProcurementSagaState(
                saga_id=uuid4(),
                legal_entity_id=uuid4(),
                vendor_id=uuid4(),
                items=sample_items_list(),
                user_id=None,
                correlation_id=None,
                status="INVALID",
            )


# ============================================================================
# Method: update_status
# ============================================================================

class TestUpdateStatus:
    def test_valid_transitions(self, minimal_state):
        state = minimal_state.update_status("PO_CREATED")
        assert state.status == "PO_CREATED"
        state = state.update_status("GRN_CREATED")
        assert state.status == "GRN_CREATED"
        state = state.update_status("INVOICE_CREATED")
        assert state.status == "INVOICE_CREATED"
        state = state.update_status("PAYMENT_CREATED")
        assert state.status == "PAYMENT_CREATED"
        state = state.update_status("COMPLETED")
        assert state.status == "COMPLETED"

    def test_transition_to_failed_from_any(self, minimal_state):
        state = minimal_state.update_status("FAILED")
        assert state.status == "FAILED"

    def test_invalid_transition_raises(self, minimal_state):
        with pytest.raises(ValueError, match="Cannot transition from INITIATED to COMPLETED"):
            minimal_state.update_status("COMPLETED")

    def test_completed_cannot_transition(self, minimal_state):
        state = minimal_state.update_status("PO_CREATED")
        state = state.update_status("GRN_CREATED")
        state = state.update_status("INVOICE_CREATED")
        state = state.update_status("PAYMENT_CREATED")
        completed = state.update_status("COMPLETED")
        assert completed.status == "COMPLETED"
        with pytest.raises(ValueError, match="Cannot transition from COMPLETED to FAILED"):
            completed.update_status("FAILED")


# ============================================================================
# Method: add_error
# ============================================================================

class TestAddError:
    def test_add_error_appends_error_and_sets_failed(self, minimal_state):
        state = minimal_state.add_error("Something wrong")
        assert state.errors == ["Something wrong"]
        assert state.status == "FAILED"

    def test_add_error_appends_multiple_errors(self, minimal_state):
        state = minimal_state.add_error("Error 1")
        state = state.add_error("Error 2")
        assert state.errors == ["Error 1", "Error 2"]
        assert state.status == "FAILED"

    def test_add_error_does_not_change_completed_status(self, minimal_state):
        state = minimal_state.update_status("PO_CREATED")
        state = state.update_status("GRN_CREATED")
        state = state.update_status("INVOICE_CREATED")
        state = state.update_status("PAYMENT_CREATED")
        completed = state.update_status("COMPLETED")
        assert completed.status == "COMPLETED"
        result = completed.add_error("Error after complete")
        assert result.status == "COMPLETED"
        assert result.errors == ["Error after complete"]


# ============================================================================
# Method: mark_completed
# ============================================================================

class TestMarkCompleted:
    def test_mark_completed_success(self, minimal_state):
        state = minimal_state.update_status("PO_CREATED")
        state = state.update_status("GRN_CREATED")
        state = state.update_status("INVOICE_CREATED")
        state = state.update_status("PAYMENT_CREATED")
        completed = state.mark_completed()
        assert completed.status == "COMPLETED"

    def test_mark_completed_failed_raises(self, minimal_state):
        failed = minimal_state.update_status("FAILED")
        with pytest.raises(ValueError, match="Cannot complete a failed saga"):
            failed.mark_completed()


# ============================================================================
# Method: mark_failed
# ============================================================================

class TestMarkFailed:
    def test_mark_failed_sets_status_and_error(self, minimal_state):
        state = minimal_state.mark_failed("Critical failure")
        assert state.status == "FAILED"
        assert state.errors == ["Critical failure"]


# ============================================================================
# Methods: set_po, set_grn, set_invoice, set_payment, add_inventory_movement
# ============================================================================

class TestSetPo:
    def test_set_po_sets_id_and_number_and_updates_status(self, minimal_state):
        po_id, po_number = uuid4(), "PO-123"
        state = minimal_state.set_po(po_id, po_number)
        assert state.po_id == po_id
        assert state.po_number == po_number
        assert state.status == "PO_CREATED"

    def test_set_po_updates_updated_at(self, minimal_state):
        old = minimal_state.updated_at
        time.sleep(0.001)
        state = minimal_state.set_po(uuid4(), "PO-001")
        assert state.updated_at > old


class TestSetGrn:
    def test_set_grn_sets_id_and_number_and_updates_status(self, minimal_state):
        state = minimal_state.set_po(uuid4(), "PO-001")
        grn_id, grn_number = uuid4(), "GRN-123"
        state = state.set_grn(grn_id, grn_number)
        assert state.grn_id == grn_id
        assert state.grn_number == grn_number
        assert state.status == "GRN_CREATED"

    def test_set_grn_updates_updated_at(self, minimal_state):
        state = minimal_state.set_po(uuid4(), "PO-001")
        old = state.updated_at
        time.sleep(0.001)
        state = state.set_grn(uuid4(), "GRN-001")
        assert state.updated_at > old


class TestSetInvoice:
    def test_set_invoice_sets_id_and_number_and_updates_status(self, minimal_state):
        state = minimal_state.set_po(uuid4(), "PO-001")
        state = state.set_grn(uuid4(), "GRN-001")
        inv_id, inv_number = uuid4(), "INV-123"
        state = state.set_invoice(inv_id, inv_number)
        assert state.invoice_id == inv_id
        assert state.invoice_number == inv_number
        assert state.status == "INVOICE_CREATED"

    def test_set_invoice_updates_updated_at(self, minimal_state):
        state = minimal_state.set_po(uuid4(), "PO-001")
        state = state.set_grn(uuid4(), "GRN-001")
        old = state.updated_at
        time.sleep(0.001)
        state = state.set_invoice(uuid4(), "INV-001")
        assert state.updated_at > old


class TestSetPayment:
    def test_set_payment_sets_id_and_number_and_updates_status(self, minimal_state):
        state = minimal_state.set_po(uuid4(), "PO-001")
        state = state.set_grn(uuid4(), "GRN-001")
        state = state.set_invoice(uuid4(), "INV-001")
        pay_id, pay_number = uuid4(), "PAY-123"
        state = state.set_payment(pay_id, pay_number)
        assert state.payment_id == pay_id
        assert state.payment_number == pay_number
        assert state.status == "PAYMENT_CREATED"

    def test_set_payment_updates_updated_at(self, minimal_state):
        state = minimal_state.set_po(uuid4(), "PO-001")
        state = state.set_grn(uuid4(), "GRN-001")
        state = state.set_invoice(uuid4(), "INV-001")
        old = state.updated_at
        time.sleep(0.001)
        state = state.set_payment(uuid4(), "PAY-001")
        assert state.updated_at > old


class TestAddInventoryMovement:
    def test_add_inventory_movement_appends_id(self, minimal_state):
        m1 = uuid4()
        state = minimal_state.add_inventory_movement(m1)
        assert state.inventory_movement_ids == [m1]

    def test_add_inventory_movement_multiple(self, minimal_state):
        m1, m2 = uuid4(), uuid4()
        state = minimal_state.add_inventory_movement(m1)
        state = state.add_inventory_movement(m2)
        assert state.inventory_movement_ids == [m1, m2]

    def test_add_inventory_movement_updates_updated_at(self, minimal_state):
        old = minimal_state.updated_at
        time.sleep(0.001)
        state = minimal_state.add_inventory_movement(uuid4())
        assert state.updated_at > old


# ============================================================================
# Method: to_dict
# ============================================================================

class TestToDict:
    def test_to_dict_contains_all_fields(self, sample_state):
        d = sample_state.to_dict()
        assert d["saga_id"] == str(sample_state.saga_id)
        assert d["legal_entity_id"] == str(sample_state.legal_entity_id)
        assert d["vendor_id"] == str(sample_state.vendor_id)
        assert d["items"] == sample_state.items
        assert d["user_id"] == str(sample_state.user_id)
        assert d["correlation_id"] == sample_state.correlation_id
        assert d["po_id"] == str(sample_state.po_id)
        assert d["po_number"] == sample_state.po_number
        assert d["grn_id"] == str(sample_state.grn_id)
        assert d["grn_number"] == sample_state.grn_number
        assert d["invoice_id"] == str(sample_state.invoice_id)
        assert d["invoice_number"] == sample_state.invoice_number
        assert d["payment_id"] == str(sample_state.payment_id)
        assert d["payment_number"] == sample_state.payment_number
        assert d["inventory_movement_ids"] == [str(mid) for mid in sample_state.inventory_movement_ids]
        assert d["total_amount"] == str(sample_state.total_amount)
        assert d["status"] == sample_state.status
        assert d["errors"] == sample_state.errors
        assert d["created_at"] == sample_state.created_at.isoformat()
        assert d["updated_at"] == sample_state.updated_at.isoformat()

    def test_to_dict_handles_none_optional_fields(self, minimal_state):
        d = minimal_state.to_dict()
        assert d["user_id"] is None
        assert d["correlation_id"] is None
        assert d["po_id"] is None
        assert d["po_number"] is None
        assert d["grn_id"] is None
        assert d["grn_number"] is None
        assert d["invoice_id"] is None
        assert d["invoice_number"] is None
        assert d["payment_id"] is None
        assert d["payment_number"] is None
        assert d["inventory_movement_ids"] == []
        assert d["errors"] == []


# ============================================================================
# Method: from_dict
# ============================================================================

class TestFromDict:
    def test_from_dict_reconstructs_full_state(self, sample_state):
        d = sample_state.to_dict()
        reconstructed = ProcurementSagaState.from_dict(d)
        assert reconstructed == sample_state

    def test_from_dict_handles_missing_optional_fields(self, minimal_state):
        d = minimal_state.to_dict()
        optional_keys = ["user_id", "correlation_id", "po_id", "po_number",
                         "grn_id", "grn_number", "invoice_id", "invoice_number",
                         "payment_id", "payment_number", "inventory_movement_ids",
                         "errors"]
        for key in optional_keys:
            d.pop(key, None)
        reconstructed = ProcurementSagaState.from_dict(d)
        assert reconstructed.user_id is None
        assert reconstructed.correlation_id is None
        assert reconstructed.po_id is None
        assert reconstructed.po_number is None
        assert reconstructed.grn_id is None
        assert reconstructed.grn_number is None
        assert reconstructed.invoice_id is None
        assert reconstructed.invoice_number is None
        assert reconstructed.payment_id is None
        assert reconstructed.payment_number is None
        assert reconstructed.inventory_movement_ids == []
        assert reconstructed.errors == []
        assert reconstructed.saga_id == minimal_state.saga_id
        assert reconstructed.legal_entity_id == minimal_state.legal_entity_id
        assert reconstructed.vendor_id == minimal_state.vendor_id
        assert reconstructed.items == minimal_state.items
        assert reconstructed.total_amount == minimal_state.total_amount
        assert reconstructed.status == minimal_state.status

    def test_from_dict_handles_none_uuid_strings(self, minimal_state):
        d = minimal_state.to_dict()
        d["user_id"] = None
        d["po_id"] = None
        d["grn_id"] = None
        d["invoice_id"] = None
        d["payment_id"] = None
        reconstructed = ProcurementSagaState.from_dict(d)
        assert reconstructed.user_id is None
        assert reconstructed.po_id is None
        assert reconstructed.grn_id is None
        assert reconstructed.invoice_id is None
        assert reconstructed.payment_id is None

    def test_from_dict_converts_decimals(self, sample_state):
        d = sample_state.to_dict()
        reconstructed = ProcurementSagaState.from_dict(d)
        assert reconstructed.total_amount == sample_state.total_amount


# ============================================================================
# Factory: create_procurement_saga_state
# ============================================================================

class TestFactory:
    def test_create_procurement_saga_state_without_total(self):
        items = [
            {"quantity": 2, "unit_price": "100.00"},
            {"quantity": 1, "unit_price": "50.00"},
        ]
        state = create_procurement_saga_state(
            legal_entity_id=uuid4(),
            vendor_id=uuid4(),
            items=items,
            user_id=uuid4(),
            correlation_id="corr-123",
        )
        assert state.total_amount == Decimal("250.00")
        assert state.status == "INITIATED"
        assert state.saga_id is not None
        assert state.legal_entity_id is not None
        assert state.vendor_id is not None
        assert state.items == items
        assert state.user_id is not None
        assert state.correlation_id == "corr-123"

    def test_create_procurement_saga_state_with_total(self):
        items = [{"quantity": 1, "unit_price": "10.00"}]
        state = create_procurement_saga_state(
            legal_entity_id=uuid4(),
            vendor_id=uuid4(),
            items=items,
            total_amount=Decimal("100.00"),
        )
        assert state.total_amount == Decimal("100.00")

    def test_create_procurement_saga_state_handles_zero_items(self):
        with pytest.raises(ValueError, match="Items list cannot be empty"):
            create_procurement_saga_state(
                legal_entity_id=uuid4(),
                vendor_id=uuid4(),
                items=[],
            )


# ============================================================================
# Round-trip
# ============================================================================

class TestSerializationRoundTrip:
    def test_to_dict_from_dict_round_trip(self, sample_state):
        d = sample_state.to_dict()
        reconstructed = ProcurementSagaState.from_dict(d)
        assert reconstructed == sample_state

    def test_to_dict_from_dict_round_trip_minimal(self, minimal_state):
        d = minimal_state.to_dict()
        reconstructed = ProcurementSagaState.from_dict(d)
        assert reconstructed == minimal_state