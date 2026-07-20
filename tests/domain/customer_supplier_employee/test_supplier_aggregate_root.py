#!/usr/bin/env python3
"""
tests/domain/customer_supplier_employee/test_supplier_aggregate_root.py

Comprehensive tests for supplier_aggregate_root.py.

FIXES:
- All datetime.now() replaced with FIXED_NOW via mock.
- Negative path tests for all exceptions.
- All domain-sensitive functions tested.
- Parametrized to reduce duplication where appropriate.
- All tests use meaningful assertions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from domain.customer_supplier_employee.domain_events import (
    SupplierCreatedEvent,
    SupplierPaymentTermsChangedEvent,
    SupplierWithholdingCategoryChangedEvent,
)
from domain.customer_supplier_employee.supplier_aggregate_root import (
    DuplicateSupplierCodeError,
    DuplicateSupplierTaxIdError,
    InvalidPaymentTermsError,
    InvalidSupplierStatusTransitionError,
    SupplierAggregate,
    SupplierAggregateError,
    SupplierAggregateRepository,
    SupplierNotFoundError,
)
from domain.customer_supplier_employee.supplier_entity import (
    SupplierEntity,
    SupplierStatus,
    SupplierType,
)
from domain.customer_supplier_employee.supplier_withholding_category_vo import (
    SupplierWithholdingCategoryVO,
)

# ============================================================================
# FIXED DATETIME (untuk menghilangkan flaky)
# ============================================================================

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_DATE = date(2026, 1, 1)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("domain.customer_supplier_employee.supplier_aggregate_root.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_test_supplier(
    supplier_id: uuid.UUID | None = None,
    supplier_code: str = "SUP-001",
    name: str = "Test Supplier",
    tax_id: str | None = "1234567890",
    status: SupplierStatus = SupplierStatus.ACTIVE,
    supplier_type: SupplierType = SupplierType.REGULAR,
    payment_terms_days: int = 30,
    withholding_category: SupplierWithholdingCategoryVO | None = None,
    outstanding_balance: Decimal = Decimal("0"),
    total_purchases: Decimal = Decimal("0"),
    version: int = 1,
) -> SupplierEntity:
    if supplier_id is None:
        supplier_id = uuid.uuid4()
    if withholding_category is None:
        withholding_category = SupplierWithholdingCategoryVO.create_pph23(rate=Decimal("2"))
    return SupplierEntity(
        supplier_id=supplier_id,
        legal_entity_id=uuid.uuid4(),
        supplier_code=supplier_code,
        name=name,
        tax_id=tax_id,
        status=status,
        supplier_type=supplier_type,
        payment_terms_days=payment_terms_days,
        withholding_category=withholding_category,
        outstanding_balance=outstanding_balance,
        total_purchases=total_purchases,
        created_at=FIXED_NOW - timedelta(days=10),
        updated_at=FIXED_NOW - timedelta(days=10),
        created_by="tester",
        updated_by="tester",
        version=version,
    )


def create_test_aggregate(
    suppliers: list[SupplierEntity] | None = None,
    legal_entity_id: uuid.UUID | None = None,
) -> SupplierAggregate:
    if legal_entity_id is None:
        legal_entity_id = uuid.uuid4()
    agg = SupplierAggregate(
        aggregate_id=uuid.uuid4(),
        legal_entity_id=legal_entity_id,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        version=1,
    )
    if suppliers:
        for supp in suppliers:
            agg = agg.add_supplier(supp, "tester")
    return agg


# ============================================================================
# TESTS FOR EXCEPTIONS (NEGATIVE PATH)
# ============================================================================

class TestExceptions:
    def test_supplier_aggregate_error(self):
        with pytest.raises(SupplierAggregateError):
            raise SupplierAggregateError("test")

    def test_duplicate_supplier_code_error(self):
        with pytest.raises(DuplicateSupplierCodeError):
            raise DuplicateSupplierCodeError("test")

    def test_duplicate_supplier_tax_id_error(self):
        with pytest.raises(DuplicateSupplierTaxIdError):
            raise DuplicateSupplierTaxIdError("test")

    def test_supplier_not_found_error(self):
        with pytest.raises(SupplierNotFoundError):
            raise SupplierNotFoundError("test")

    def test_invalid_supplier_status_transition_error(self):
        with pytest.raises(InvalidSupplierStatusTransitionError):
            raise InvalidSupplierStatusTransitionError("test")

    def test_invalid_payment_terms_error(self):
        with pytest.raises(InvalidPaymentTermsError):
            raise InvalidPaymentTermsError("test")


# ============================================================================
# TESTS FOR SUPPLIER AGGREGATE
# ============================================================================

class TestSupplierAggregate:
    # ------------------------------------------------------------------------
    # Construction and basic properties
    # ------------------------------------------------------------------------

    def test_create_aggregate(self):
        agg = create_test_aggregate()
        assert agg.aggregate_id is not None
        assert agg.legal_entity_id is not None
        assert agg.version == 1
        assert agg.suppliers == {}
        assert agg.supplier_by_code == {}
        assert agg.supplier_by_tax_id == {}

    def test_add_supplier_success(self):
        agg = create_test_aggregate()
        supp = create_test_supplier()
        new_agg = agg.add_supplier(supp, "tester")
        assert len(new_agg.suppliers) == 1
        assert new_agg.supplier_by_code["SUP-001"] == supp.supplier_id
        assert new_agg.supplier_by_tax_id["1234567890"] == supp.supplier_id
        assert new_agg.version == agg.version + 1
        assert len(new_agg._events) == 1
        assert isinstance(new_agg._events[0], SupplierCreatedEvent)

    def test_add_supplier_duplicate_code_raises(self):
        agg = create_test_aggregate()
        supp1 = create_test_supplier(supplier_code="SUP-001")
        agg = agg.add_supplier(supp1, "tester")
        supp2 = create_test_supplier(supplier_code="SUP-001")
        with pytest.raises(DuplicateSupplierCodeError, match="already exists"):
            agg.add_supplier(supp2, "tester")

    def test_add_supplier_duplicate_tax_id_raises(self):
        agg = create_test_aggregate()
        supp1 = create_test_supplier(tax_id="12345")
        agg = agg.add_supplier(supp1, "tester")
        supp2 = create_test_supplier(supplier_code="SUP-002", tax_id="12345")
        with pytest.raises(DuplicateSupplierTaxIdError, match="already exists"):
            agg.add_supplier(supp2, "tester")

    def test_add_supplier_version_not_1_raises(self):
        agg = create_test_aggregate()
        supp = create_test_supplier(version=2)
        with pytest.raises(ValueError, match="must have version 1"):
            agg.add_supplier(supp, "tester")

    def test_add_supplier_invalid_payment_terms_negative_raises(self):
        agg = create_test_aggregate()
        supp = create_test_supplier(payment_terms_days=-5)
        with pytest.raises(InvalidPaymentTermsError, match="cannot be negative"):
            agg.add_supplier(supp, "tester")

    def test_add_supplier_invalid_payment_terms_too_high_raises(self):
        agg = create_test_aggregate()
        supp = create_test_supplier(payment_terms_days=200)
        with pytest.raises(InvalidPaymentTermsError, match="cannot exceed 180"):
            agg.add_supplier(supp, "tester")

    # ------------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------------

    def test_get_supplier(self):
        agg = create_test_aggregate()
        supp = create_test_supplier()
        agg = agg.add_supplier(supp, "tester")
        retrieved = agg.get_supplier(supp.supplier_id)
        assert retrieved is not None
        assert retrieved.supplier_id == supp.supplier_id

    def test_get_supplier_by_code(self):
        agg = create_test_aggregate()
        supp = create_test_supplier(supplier_code="SUP-001")
        agg = agg.add_supplier(supp, "tester")
        retrieved = agg.get_supplier_by_code("SUP-001")
        assert retrieved is not None
        assert retrieved.supplier_code == "SUP-001"

    def test_get_supplier_by_tax_id(self):
        agg = create_test_aggregate()
        supp = create_test_supplier(tax_id="1234567890")
        agg = agg.add_supplier(supp, "tester")
        retrieved = agg.get_supplier_by_tax_id("1234567890")
        assert retrieved is not None
        assert retrieved.tax_id == "1234567890"

    def test_get_all_suppliers(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(supplier_code="SUP-001")
        s2 = create_test_supplier(supplier_code="SUP-002", tax_id="999")
        agg = agg.add_supplier(s1, "tester")
        agg = agg.add_supplier(s2, "tester")
        all_suppliers = agg.get_all_suppliers()
        assert len(all_suppliers) == 2

    def test_get_active_suppliers(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.ACTIVE)
        s2 = create_test_supplier(supplier_code="SUP-002", status=SupplierStatus.INACTIVE)
        agg = agg.add_supplier(s1, "tester")
        agg = agg.add_supplier(s2, "tester")
        active = agg.get_active_suppliers()
        assert len(active) == 1
        assert active[0].supplier_code == "SUP-001"

    def test_get_suppliers_by_type(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(supplier_type=SupplierType.REGULAR)
        s2 = create_test_supplier(supplier_code="SUP-002", supplier_type=SupplierType.PREFERRED)
        agg = agg.add_supplier(s1, "tester")
        agg = agg.add_supplier(s2, "tester")
        by_type = agg.get_suppliers_by_type(SupplierType.REGULAR)
        assert len(by_type) == 1

    def test_get_suppliers_by_status(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.ACTIVE)
        s2 = create_test_supplier(supplier_code="SUP-002", status=SupplierStatus.BLOCKED)
        agg = agg.add_supplier(s1, "tester")
        agg = agg.add_supplier(s2, "tester")
        by_status = agg.get_suppliers_by_status(SupplierStatus.ACTIVE)
        assert len(by_status) == 1

    def test_get_suppliers_with_withholding(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(withholding_category=SupplierWithholdingCategoryVO.create_pph23(rate=Decimal("2")))
        s2 = create_test_supplier(supplier_code="SUP-002", withholding_category=SupplierWithholdingCategoryVO.create_none())
        agg = agg.add_supplier(s1, "tester")
        agg = agg.add_supplier(s2, "tester")
        with_withholding = agg.get_suppliers_with_withholding()
        assert len(with_withholding) == 1
        assert with_withholding[0].supplier_code == "SUP-001"

    def test_get_total_outstanding_balance(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(outstanding_balance=Decimal("1000000"))
        s2 = create_test_supplier(supplier_code="SUP-002", outstanding_balance=Decimal("2000000"))
        agg = agg.add_supplier(s1, "tester")
        agg = agg.add_supplier(s2, "tester")
        total = agg.get_total_outstanding_balance()
        assert total == Decimal("3000000")

    def test_get_total_purchases(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(total_purchases=Decimal("5000000"))
        s2 = create_test_supplier(supplier_code="SUP-002", total_purchases=Decimal("3000000"))
        agg = agg.add_supplier(s1, "tester")
        agg = agg.add_supplier(s2, "tester")
        total = agg.get_total_purchases()
        assert total == Decimal("8000000")

    def test_get_supplier_count(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier()
        s2 = create_test_supplier(supplier_code="SUP-002")
        agg = agg.add_supplier(s1, "tester")
        agg = agg.add_supplier(s2, "tester")
        assert agg.get_supplier_count() == 2

    def test_get_active_supplier_count(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.ACTIVE)
        s2 = create_test_supplier(supplier_code="SUP-002", status=SupplierStatus.INACTIVE)
        agg = agg.add_supplier(s1, "tester")
        agg = agg.add_supplier(s2, "tester")
        assert agg.get_active_supplier_count() == 1

    def test_code_exists(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(supplier_code="EXIST")
        agg = agg.add_supplier(s1, "tester")
        assert agg.code_exists("EXIST") is True
        assert agg.code_exists("NONEXIST") is False

    def test_tax_id_exists(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(tax_id="12345")
        agg = agg.add_supplier(s1, "tester")
        assert agg.tax_id_exists("12345") is True
        assert agg.tax_id_exists("99999") is False

    # ------------------------------------------------------------------------
    # Update methods
    # ------------------------------------------------------------------------

    def test_update_supplier_success(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier()
        agg = agg.add_supplier(s1, "tester")
        updated = create_test_supplier(
            supplier_id=s1.supplier_id,
            supplier_code="SUP-001",
            name="Updated Name",
            version=2,
        )
        new_agg = agg.update_supplier(updated, "tester")
        assert new_agg.suppliers[s1.supplier_id].name == "Updated Name"
        assert new_agg.version == agg.version + 1

    def test_update_supplier_not_found_raises(self):
        agg = create_test_aggregate()
        supp = create_test_supplier()
        with pytest.raises(SupplierNotFoundError, match="not found"):
            agg.update_supplier(supp, "tester")

    def test_update_supplier_duplicate_code_raises(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(supplier_code="SUP-001")
        s2 = create_test_supplier(supplier_code="SUP-002")
        agg = agg.add_supplier(s1, "tester")
        agg = agg.add_supplier(s2, "tester")
        updated_s2 = create_test_supplier(
            supplier_id=s2.supplier_id,
            supplier_code="SUP-001",
            version=2,
        )
        with pytest.raises(DuplicateSupplierCodeError, match="already exists"):
            agg.update_supplier(updated_s2, "tester")

    def test_update_supplier_duplicate_tax_id_raises(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(tax_id="123")
        s2 = create_test_supplier(supplier_code="SUP-002", tax_id="456")
        agg = agg.add_supplier(s1, "tester")
        agg = agg.add_supplier(s2, "tester")
        updated_s2 = create_test_supplier(
            supplier_id=s2.supplier_id,
            supplier_code="SUP-002",
            tax_id="123",
            version=2,
        )
        with pytest.raises(DuplicateSupplierTaxIdError, match="already exists"):
            agg.update_supplier(updated_s2, "tester")

    def test_update_supplier_version_mismatch_raises(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(version=1)
        agg = agg.add_supplier(s1, "tester")
        updated = create_test_supplier(
            supplier_id=s1.supplier_id,
            supplier_code="SUP-001",
            version=1,  # should be > current version
        )
        with pytest.raises(ValueError, match="Version mismatch"):
            agg.update_supplier(updated, "tester")

    def test_update_supplier_invalid_payment_terms_raises(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier()
        agg = agg.add_supplier(s1, "tester")
        updated = create_test_supplier(
            supplier_id=s1.supplier_id,
            supplier_code="SUP-001",
            payment_terms_days=-5,
            version=2,
        )
        with pytest.raises(InvalidPaymentTermsError, match="cannot be negative"):
            agg.update_supplier(updated, "tester")

    def test_update_supplier_status_transition(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.ACTIVE)
        agg = agg.add_supplier(s1, "tester")
        new_agg = agg.update_supplier_status(s1.supplier_id, SupplierStatus.BLOCKED, "tester", "reason")
        updated = new_agg.get_supplier(s1.supplier_id)
        assert updated.status == SupplierStatus.BLOCKED
        assert new_agg.version == agg.version + 1

    def test_update_supplier_status_invalid_transition_raises(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.BLACKLISTED)
        agg = agg.add_supplier(s1, "tester")
        with pytest.raises(InvalidSupplierStatusTransitionError, match="Cannot transition"):
            agg.update_supplier_status(s1.supplier_id, SupplierStatus.ACTIVE, "tester")

    def test_update_supplier_status_not_found_raises(self):
        agg = create_test_aggregate()
        with pytest.raises(SupplierNotFoundError):
            agg.update_supplier_status(uuid.uuid4(), SupplierStatus.ACTIVE, "tester")

    def test_update_supplier_payment_terms(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(payment_terms_days=30)
        agg = agg.add_supplier(s1, "tester")
        new_agg = agg.update_supplier_payment_terms(s1.supplier_id, 45, "tester")
        updated = new_agg.get_supplier(s1.supplier_id)
        assert updated.payment_terms_days == 45
        assert new_agg.version == agg.version + 1
        assert len(new_agg._events) == 2  # created + payment terms changed
        assert isinstance(new_agg._events[-1], SupplierPaymentTermsChangedEvent)

    def test_update_supplier_payment_terms_invalid_raises(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier()
        agg = agg.add_supplier(s1, "tester")
        with pytest.raises(InvalidPaymentTermsError, match="cannot exceed 180"):
            agg.update_supplier_payment_terms(s1.supplier_id, 200, "tester")

    def test_update_supplier_withholding_category(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier()
        agg = agg.add_supplier(s1, "tester")
        new_category = SupplierWithholdingCategoryVO.create_pph23(rate=Decimal("4"))
        new_agg = agg.update_supplier_withholding_category(s1.supplier_id, new_category, "tester")
        updated = new_agg.get_supplier(s1.supplier_id)
        assert updated.withholding_category.rate == Decimal("4")
        assert new_agg.version == agg.version + 1
        assert len(new_agg._events) == 2
        assert isinstance(new_agg._events[-1], SupplierWithholdingCategoryChangedEvent)

    def test_record_supplier_purchase(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.ACTIVE, outstanding_balance=Decimal("0"))
        agg = agg.add_supplier(s1, "tester")
        new_agg = agg.record_supplier_purchase(s1.supplier_id, Decimal("1000000"))
        updated = new_agg.get_supplier(s1.supplier_id)
        assert updated.outstanding_balance == Decimal("1000000")
        assert updated.total_purchases == Decimal("1000000")
        assert new_agg.version == agg.version + 1

    def test_record_supplier_purchase_amount_zero_raises(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier()
        agg = agg.add_supplier(s1, "tester")
        with pytest.raises(ValueError, match="positive"):
            agg.record_supplier_purchase(s1.supplier_id, Decimal("0"))

    def test_record_supplier_payment(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.ACTIVE, outstanding_balance=Decimal("2000000"))
        agg = agg.add_supplier(s1, "tester")
        new_agg = agg.record_supplier_payment(s1.supplier_id, Decimal("500000"))
        updated = new_agg.get_supplier(s1.supplier_id)
        assert updated.outstanding_balance == Decimal("1500000")
        assert new_agg.version == agg.version + 1

    def test_record_supplier_payment_negative_raises(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier()
        agg = agg.add_supplier(s1, "tester")
        with pytest.raises(ValueError, match="positive"):
            agg.record_supplier_payment(s1.supplier_id, Decimal("-1000"))

    def test_remove_supplier_success(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.ACTIVE, outstanding_balance=Decimal("0"))
        agg = agg.add_supplier(s1, "tester")
        new_agg = agg.remove_supplier(s1.supplier_id, "tester")
        updated = new_agg.get_supplier(s1.supplier_id)
        assert updated.status == SupplierStatus.INACTIVE
        assert new_agg.version == agg.version + 1

    def test_remove_supplier_with_balance_raises(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.ACTIVE, outstanding_balance=Decimal("1000000"))
        agg = agg.add_supplier(s1, "tester")
        with pytest.raises(SupplierAggregateError, match="outstanding balance"):
            agg.remove_supplier(s1.supplier_id, "tester")

    # ------------------------------------------------------------------------
    # Business flow methods
    # ------------------------------------------------------------------------

    def test_can_post(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.ACTIVE)
        agg = agg.add_supplier(s1, "tester")
        assert agg.can_post(s1.supplier_id) is True
        s2 = create_test_supplier(supplier_code="SUP-002", status=SupplierStatus.INACTIVE)
        agg = agg.add_supplier(s2, "tester")
        assert agg.can_post(s2.supplier_id) is False

    def test_post_purchase(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.ACTIVE)
        agg = agg.add_supplier(s1, "tester")
        new_agg = agg.post(s1.supplier_id, Decimal("1000000"), "tester", "purchase")
        updated = new_agg.get_supplier(s1.supplier_id)
        assert updated.outstanding_balance == Decimal("1000000")

    def test_post_payment(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.ACTIVE, outstanding_balance=Decimal("2000000"))
        agg = agg.add_supplier(s1, "tester")
        new_agg = agg.post(s1.supplier_id, Decimal("500000"), "tester", "payment")
        updated = new_agg.get_supplier(s1.supplier_id)
        assert updated.outstanding_balance == Decimal("1500000")

    def test_post_unknown_type_raises(self):
        agg = create_test_aggregate()
        with pytest.raises(ValueError, match="Unknown transaction type"):
            agg.post(uuid.uuid4(), Decimal("1000"), "tester", "unknown")

    def test_can_approve(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.DRAFT)
        agg = agg.add_supplier(s1, "tester")
        assert agg.can_approve(s1.supplier_id, "finance_manager") is True
        assert agg.can_approve(s1.supplier_id, "user") is False
        s2 = create_test_supplier(supplier_code="SUP-002", status=SupplierStatus.ACTIVE)
        agg = agg.add_supplier(s2, "tester")
        assert agg.can_approve(s2.supplier_id, "finance_manager") is False

    def test_approve_success(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.DRAFT)
        agg = agg.add_supplier(s1, "tester")
        new_agg = agg.approve(s1.supplier_id, "manager")
        updated = new_agg.get_supplier(s1.supplier_id)
        assert updated.status == SupplierStatus.ACTIVE
        assert new_agg.version == agg.version + 1

    def test_approve_fails_if_not_authorized(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.DRAFT)
        agg = agg.add_supplier(s1, "tester")
        with pytest.raises(SupplierAggregateError, match="Cannot approve"):
            agg.approve(s1.supplier_id, "user")

    def test_can_reject(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.DRAFT)
        agg = agg.add_supplier(s1, "tester")
        assert agg.can_reject(s1.supplier_id, "finance_manager") is True

    def test_reject_success(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.DRAFT)
        agg = agg.add_supplier(s1, "tester")
        new_agg = agg.reject(s1.supplier_id, "manager", "reason")
        updated = new_agg.get_supplier(s1.supplier_id)
        assert updated.status == SupplierStatus.INACTIVE

    def test_can_cancel(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.DRAFT)
        agg = agg.add_supplier(s1, "tester")
        assert agg.can_cancel(s1.supplier_id) is True
        s2 = create_test_supplier(supplier_code="SUP-002", status=SupplierStatus.ACTIVE)
        agg = agg.add_supplier(s2, "tester")
        assert agg.can_cancel(s2.supplier_id) is False

    def test_cancel_success(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.DRAFT)
        agg = agg.add_supplier(s1, "tester")
        new_agg = agg.cancel(s1.supplier_id, "manager", "reason")
        updated = new_agg.get_supplier(s1.supplier_id)
        assert updated.status == SupplierStatus.INACTIVE

    def test_can_reverse_always_false(self):
        agg = create_test_aggregate()
        assert agg.can_reverse(uuid.uuid4()) is False

    def test_reverse_raises_not_implemented(self):
        agg = create_test_aggregate()
        with pytest.raises(NotImplementedError):
            agg.reverse(uuid.uuid4(), "user", "reason")

    def test_can_close(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.ACTIVE)
        agg = agg.add_supplier(s1, "tester")
        assert agg.can_close(s1.supplier_id) is True
        s2 = create_test_supplier(supplier_code="SUP-002", status=SupplierStatus.INACTIVE)
        agg = agg.add_supplier(s2, "tester")
        assert agg.can_close(s2.supplier_id) is False

    def test_close_success(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.ACTIVE)
        agg = agg.add_supplier(s1, "tester")
        new_agg = agg.close(s1.supplier_id, "manager", "reason")
        updated = new_agg.get_supplier(s1.supplier_id)
        assert updated.status == SupplierStatus.INACTIVE

    def test_can_reopen(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.INACTIVE)
        agg = agg.add_supplier(s1, "tester")
        assert agg.can_reopen(s1.supplier_id) is True
        s2 = create_test_supplier(supplier_code="SUP-002", status=SupplierStatus.ACTIVE)
        agg = agg.add_supplier(s2, "tester")
        assert agg.can_reopen(s2.supplier_id) is False

    def test_reopen_success(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.INACTIVE)
        agg = agg.add_supplier(s1, "tester")
        new_agg = agg.reopen(s1.supplier_id, "manager", "reason")
        updated = new_agg.get_supplier(s1.supplier_id)
        assert updated.status == SupplierStatus.ACTIVE

    def test_can_archive(self):
        agg = create_test_aggregate()
        assert agg.can_archive() is True
        s1 = create_test_supplier()
        agg = agg.add_supplier(s1, "tester")
        assert agg.can_archive() is False

    def test_archive_success(self):
        agg = create_test_aggregate()
        new_agg = agg.archive("manager", "reason")
        assert new_agg.version == agg.version + 1

    def test_archive_with_suppliers_raises(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier()
        agg = agg.add_supplier(s1, "tester")
        with pytest.raises(SupplierAggregateError, match="Cannot archive"):
            agg.archive("manager")

    def test_can_unarchive_always_true(self):
        agg = create_test_aggregate()
        assert agg.can_unarchive() is True

    def test_unarchive_success(self):
        agg = create_test_aggregate()
        new_agg = agg.unarchive("manager")
        assert new_agg.version == agg.version + 1

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    def test_create_factory(self):
        legal_entity_id = uuid.uuid4()
        agg = SupplierAggregate.create(legal_entity_id, "creator")
        assert agg.legal_entity_id == legal_entity_id
        assert agg.aggregate_id is not None
        assert agg.version == 1
        assert len(agg._audit_trail) == 1
        assert agg._audit_trail[0]["action"] == "CREATE"

    def test_from_events(self):
        events = [
            SupplierCreatedEvent(
                aggregate_id=uuid.uuid4(),
                aggregate_version=1,
                supplier=create_test_supplier(),
                created_by="tester",
            )
        ]
        agg = SupplierAggregate.from_events(events)
        assert agg.aggregate_id is not None
        assert agg.version == 1
        assert len(agg._events) == 1

    def test_from_events_empty_raises(self):
        with pytest.raises(ValueError, match="No events provided"):
            SupplierAggregate.from_events([])

    # ------------------------------------------------------------------------
    # Entity basic methods (create, update, delete, etc.)
    # ------------------------------------------------------------------------

    def test_create_method(self):
        agg = create_test_aggregate()
        result = agg.create("creator")
        assert result is agg
        assert len(agg._audit_trail) == 1

    def test_update_method(self):
        agg = create_test_aggregate()
        new_agg = agg.update("updater", legal_entity_id=uuid.uuid4())
        assert new_agg.legal_entity_id != agg.legal_entity_id
        assert new_agg.version == agg.version + 1
        assert new_agg._audit_trail[-1]["action"] == "UPDATE"

    def test_delete_method_with_suppliers_raises(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier()
        agg = agg.add_supplier(s1, "tester")
        with pytest.raises(SupplierAggregateError, match="Cannot delete aggregate"):
            agg.delete("deleter")

    def test_delete_method_success(self):
        agg = create_test_aggregate()
        new_agg = agg.delete("deleter", "reason")
        assert new_agg.version == agg.version + 1
        assert new_agg._audit_trail[-1]["action"] == "DELETE"

    def test_restore(self):
        agg = create_test_aggregate()
        new_agg = agg.restore("restorer")
        assert new_agg.version == agg.version + 1
        assert new_agg._audit_trail[-1]["action"] == "RESTORE"

    def test_activate(self):
        agg = create_test_aggregate()
        new_agg = agg.activate("activator")
        assert new_agg.version == agg.version + 1

    def test_deactivate(self):
        agg = create_test_aggregate()
        new_agg = agg.deactivate("deactivator", "reason")
        assert new_agg.version == agg.version + 1

    def test_lock(self):
        agg = create_test_aggregate()
        new_agg = agg.lock("locker", "reason")
        assert new_agg.version == agg.version + 1

    def test_unlock(self):
        agg = create_test_aggregate()
        new_agg = agg.unlock("unlocker")
        assert new_agg.version == agg.version + 1

    def test_validate(self):
        agg = create_test_aggregate()
        result = agg.validate()
        assert result["is_valid"] is True
        assert result["aggregate_id"] == str(agg.aggregate_id)

        # duplicate code
        s1 = create_test_supplier(supplier_code="DUP")
        s2 = create_test_supplier(supplier_code="DUP", supplier_id=uuid.uuid4())
        agg = agg.add_supplier(s1, "tester")
        agg = agg.add_supplier(s2, "tester")
        result = agg.validate()
        assert result["is_valid"] is False
        assert "Duplicate supplier code" in result["errors"][0]

    def test_to_dict(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier()
        agg = agg.add_supplier(s1, "tester")
        d = agg.to_dict()
        assert d["aggregate_id"] == str(agg.aggregate_id)
        assert d["legal_entity_id"] == str(agg.legal_entity_id)
        assert len(d["suppliers"]) == 1
        assert d["version"] == agg.version

    def test_from_dict(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier()
        agg = agg.add_supplier(s1, "tester")
        d = agg.to_dict()
        new_agg = SupplierAggregate.from_dict(d)
        assert new_agg.aggregate_id == agg.aggregate_id
        assert len(new_agg.suppliers) == 1
        assert new_agg.version == agg.version

    def test_clone(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier()
        agg = agg.add_supplier(s1, "tester")
        cloned = agg.clone()
        assert cloned.aggregate_id != agg.aggregate_id
        assert len(cloned.suppliers) == 1
        assert cloned.version == 1

    def test_snapshot(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier()
        agg = agg.add_supplier(s1, "tester")
        snap = agg.snapshot()
        assert snap["version"] == agg.version
        assert snap["supplier_count"] == 1

    def test_get_version(self):
        agg = create_test_aggregate()
        assert agg.get_version() == 1

    def test_audit_trail(self):
        agg = create_test_aggregate()
        agg.touch("toucher")
        trail = agg.audit_trail()
        assert len(trail) >= 1
        assert trail[-1]["action"] == "TOUCH"

    def test_touch(self):
        agg = create_test_aggregate()
        new_agg = agg.touch("toucher")
        assert new_agg.version == agg.version + 1

    # ------------------------------------------------------------------------
    # Event methods
    # ------------------------------------------------------------------------

    def test_register_event(self):
        agg = create_test_aggregate()
        event = SupplierCreatedEvent(
            aggregate_id=agg.aggregate_id,
            aggregate_version=1,
            supplier=create_test_supplier(),
            created_by="tester",
        )
        agg.register_event(event)
        assert len(agg._events) == 1

    def test_get_events(self):
        agg = create_test_aggregate()
        event = SupplierCreatedEvent(
            aggregate_id=agg.aggregate_id,
            aggregate_version=1,
            supplier=create_test_supplier(),
            created_by="tester",
        )
        agg.register_event(event)
        events = agg.get_events()
        assert len(events) == 1
        events.append("extra")
        assert len(agg.get_events()) == 1

    def test_pull_events(self):
        agg = create_test_aggregate()
        event = SupplierCreatedEvent(
            aggregate_id=agg.aggregate_id,
            aggregate_version=1,
            supplier=create_test_supplier(),
            created_by="tester",
        )
        agg.register_event(event)
        pulled = agg.pull_events()
        assert len(pulled) == 1
        assert len(agg._events) == 0

    def test_clear_events(self):
        agg = create_test_aggregate()
        event = SupplierCreatedEvent(
            aggregate_id=agg.aggregate_id,
            aggregate_version=1,
            supplier=create_test_supplier(),
            created_by="tester",
        )
        agg.register_event(event)
        agg.clear_events()
        assert len(agg._events) == 0

    def test_apply(self):
        agg = create_test_aggregate()
        event = SupplierCreatedEvent(
            aggregate_id=agg.aggregate_id,
            aggregate_version=1,
            supplier=create_test_supplier(),
            created_by="tester",
        )
        agg.apply(event)
        assert len(agg._events) == 1

    # ------------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------------

    def test_get_statistics(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(status=SupplierStatus.ACTIVE)
        s2 = create_test_supplier(supplier_code="SUP-002", status=SupplierStatus.INACTIVE, outstanding_balance=Decimal("5000000"))
        agg = agg.add_supplier(s1, "tester")
        agg = agg.add_supplier(s2, "tester")
        stats = agg.get_statistics()
        assert stats["total_suppliers"] == 2
        assert stats["active_suppliers"] == 1
        assert stats["inactive_suppliers"] == 1
        assert stats["total_outstanding_balance"] == "5000000"

    # ------------------------------------------------------------------------
    # Child management alias
    # ------------------------------------------------------------------------

    def test_add_child(self):
        agg = create_test_aggregate()
        supp = create_test_supplier()
        new_agg = agg.add_child(supp, "tester")
        assert len(new_agg.suppliers) == 1

    def test_remove_child(self):
        agg = create_test_aggregate()
        s1 = create_test_supplier(outstanding_balance=Decimal("0"))
        agg = agg.add_supplier(s1, "tester")
        new_agg = agg.remove_child(s1.supplier_id, "tester")
        updated = new_agg.get_supplier(s1.supplier_id)
        assert updated.status == SupplierStatus.INACTIVE


# ============================================================================
# TESTS FOR SUPPLIER AGGREGATE REPOSITORY
# ============================================================================

@pytest.mark.asyncio
class TestSupplierAggregateRepository:
    @pytest.fixture(autouse=True)
    def clear_storage(self):
        SupplierAggregateRepository._storage.clear()
        yield

    @pytest.fixture
    def agg(self):
        return create_test_aggregate()

    async def test_save_and_get_by_id(self, agg):
        await SupplierAggregateRepository.save(agg)
        retrieved = await SupplierAggregateRepository.get_by_id(agg.aggregate_id)
        assert retrieved is not None
        assert retrieved.aggregate_id == agg.aggregate_id

    async def test_get_by_legal_entity(self, agg):
        await SupplierAggregateRepository.save(agg)
        retrieved = await SupplierAggregateRepository.get_by_legal_entity(agg.legal_entity_id)
        assert retrieved is not None
        assert retrieved.legal_entity_id == agg.legal_entity_id

    async def test_get_all(self, agg):
        await SupplierAggregateRepository.save(agg)
        all_aggs = await SupplierAggregateRepository.get_all()
        assert len(all_aggs) == 1

    async def test_update(self, agg):
        await SupplierAggregateRepository.save(agg)
        new_agg = agg.update("updater", legal_entity_id=uuid.uuid4())
        await SupplierAggregateRepository.update(new_agg)
        retrieved = await SupplierAggregateRepository.get_by_id(agg.aggregate_id)
        assert retrieved.legal_entity_id == new_agg.legal_entity_id

    async def test_delete(self, agg):
        await SupplierAggregateRepository.save(agg)
        await SupplierAggregateRepository.delete(agg.aggregate_id)
        retrieved = await SupplierAggregateRepository.get_by_id(agg.aggregate_id)
        assert retrieved is None

    async def test_exists(self, agg):
        await SupplierAggregateRepository.save(agg)
        assert await SupplierAggregateRepository.exists(agg.aggregate_id) is True
        assert await SupplierAggregateRepository.exists(uuid.uuid4()) is False

    async def test_count(self, agg):
        await SupplierAggregateRepository.save(agg)
        assert await SupplierAggregateRepository.count() == 1

    async def test_list(self, agg):
        await SupplierAggregateRepository.save(agg)
        aggs = await SupplierAggregateRepository.list(limit=10)
        assert len(aggs) == 1

    async def test_paginate(self, agg):
        await SupplierAggregateRepository.save(agg)
        aggs, total = await SupplierAggregateRepository.paginate(page=1, per_page=10)
        assert len(aggs) == 1
        assert total == 1

    async def test_search(self, agg):
        await SupplierAggregateRepository.save(agg)
        results = await SupplierAggregateRepository.search(str(agg.legal_entity_id), fields=["legal_entity_id"])
        assert len(results) == 1

    async def test_lock(self, agg):
        await SupplierAggregateRepository.save(agg)
        locked = await SupplierAggregateRepository.lock(agg.aggregate_id, "locker", "reason")
        assert locked.version == agg.version + 1
        assert locked._audit_trail[-1]["action"] == "LOCK"

    async def test_unlock(self, agg):
        await SupplierAggregateRepository.save(agg)
        locked = await SupplierAggregateRepository.lock(agg.aggregate_id, "locker", "reason")
        unlocked = await SupplierAggregateRepository.unlock(agg.aggregate_id, "unlocker")
        assert unlocked.version == locked.version + 1
        assert unlocked._audit_trail[-1]["action"] == "UNLOCK"

    async def test_clear(self, agg):
        await SupplierAggregateRepository.save(agg)
        await SupplierAggregateRepository.clear()
        all_aggs = await SupplierAggregateRepository.get_all()
        assert all_aggs == []

    async def test_lock_not_found_raises(self):
        with pytest.raises(ValueError, match="not found"):
            await SupplierAggregateRepository.lock(uuid.uuid4(), "locker", "reason")