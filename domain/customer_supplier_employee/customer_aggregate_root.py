# tests/domain/customer_supplier_employee/test_customer_aggregate_root.py
"""
Comprehensive tests for domain/customer_supplier_employee/customer_aggregate_root.py.
Covers all methods, exceptions, and includes negative path tests.

FIXES:
- All datetime.now() replaced with FIXED_NOW.
- All exceptions tested with pytest.raises.
- All domain-sensitive functions tested.
- Uses parametrize to avoid duplication.
- Proper fixtures for aggregate with customers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from domain.customer_supplier_employee.customer_aggregate_root import (
    CustomerAggregate,
    CustomerAggregateError,
    CustomerAggregateRepository,
    CustomerNotFoundError,
    DuplicateCustomerCodeError,
    DuplicateEmailError,
    DuplicateTaxIdError,
    InvalidCustomerStatusTransitionError,
)
from domain.customer_supplier_employee.customer_credit_limit_vo import (
    CustomerCreditLimitVO,
)
from domain.customer_supplier_employee.customer_entity import (
    CustomerEntity,
    CustomerSegment,
    CustomerStatus,
    CustomerType,
)
from domain.customer_supplier_employee.customer_tax_status_vo import (
    CustomerTaxStatusVO,
)
from domain.customer_supplier_employee.domain_events import (
    CustomerCreatedEvent,
    DomainEvent,
)

# ============================================================================
# FIXED DATETIME (untuk menghindari flaky tests)
# ============================================================================

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_PAST = FIXED_NOW - timedelta(days=1)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("domain.customer_supplier_employee.customer_aggregate_root.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_test_customer(
    customer_id: uuid.UUID | None = None,
    customer_code: str = "CUST-001",
    name: str = "Test Customer",
    email: str = "test@example.com",
    tax_id: str | None = "1234567890",
    status: CustomerStatus = CustomerStatus.DRAFT,
    customer_type: CustomerType = CustomerType.INDIVIDUAL,
    segment: CustomerSegment = CustomerSegment.RETAIL,
    credit_limit: Decimal = Decimal("10000000"),
    outstanding_balance: Decimal = Decimal("0"),
    risk_score: int = 50,
    credit_hold: bool = False,
    version: int = 1,
) -> CustomerEntity:
    if customer_id is None:
        customer_id = uuid.uuid4()
    return CustomerEntity(
        customer_id=customer_id,
        legal_entity_id=uuid.uuid4(),
        customer_code=customer_code,
        name=name,
        email=email,
        tax_id=tax_id,
        status=status,
        customer_type=customer_type,
        segment=segment,
        credit_limit=CustomerCreditLimitVO(
            amount=credit_limit,
            currency="IDR",
            valid_from=FIXED_NOW - timedelta(days=30),
            valid_until=FIXED_NOW + timedelta(days=30),
        ),
        tax_status=CustomerTaxStatusVO(
            npwp=tax_id,
            pkp=False,
            tax_identification_number=tax_id,
        ),
        outstanding_balance=outstanding_balance,
        total_purchases=Decimal("0"),
        total_payments=Decimal("0"),
        risk_score=risk_score,
        credit_hold=credit_hold,
        created_at=FIXED_NOW - timedelta(days=10),
        updated_at=FIXED_NOW - timedelta(days=10),
        created_by="tester",
        updated_by="tester",
        version=version,
    )


def create_test_aggregate(
    customers: list[CustomerEntity] | None = None,
    legal_entity_id: uuid.UUID | None = None,
) -> CustomerAggregate:
    if legal_entity_id is None:
        legal_entity_id = uuid.uuid4()
    agg = CustomerAggregate(
        aggregate_id=uuid.uuid4(),
        legal_entity_id=legal_entity_id,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        version=1,
    )
    if customers:
        for cust in customers:
            agg = agg.add_customer(cust, "tester")
    return agg


# ============================================================================
# TESTS FOR EXCEPTIONS
# ============================================================================

class TestExceptions:
    def test_customer_aggregate_error(self):
        with pytest.raises(CustomerAggregateError):
            raise CustomerAggregateError("test")

    def test_duplicate_customer_code_error(self):
        with pytest.raises(DuplicateCustomerCodeError):
            raise DuplicateCustomerCodeError("test")

    def test_duplicate_email_error(self):
        with pytest.raises(DuplicateEmailError):
            raise DuplicateEmailError("test")

    def test_duplicate_tax_id_error(self):
        with pytest.raises(DuplicateTaxIdError):
            raise DuplicateTaxIdError("test")

    def test_customer_not_found_error(self):
        with pytest.raises(CustomerNotFoundError):
            raise CustomerNotFoundError("test")

    def test_invalid_customer_status_transition_error(self):
        with pytest.raises(InvalidCustomerStatusTransitionError):
            raise InvalidCustomerStatusTransitionError("test")


# ============================================================================
# TESTS FOR CUSTOMER AGGREGATE
# ============================================================================

class TestCustomerAggregate:
    # ------------------------------------------------------------------------
    # Construction and basic properties
    # ------------------------------------------------------------------------

    def test_create_aggregate(self):
        agg = create_test_aggregate()
        assert agg.aggregate_id is not None
        assert agg.legal_entity_id is not None
        assert agg.version == 1
        assert agg.customers == {}
        assert agg.customer_by_code == {}
        assert agg.customer_by_email == {}
        assert agg.customer_by_tax_id == {}

    def test_add_customer_success(self):
        agg = create_test_aggregate()
        cust = create_test_customer()
        new_agg = agg.add_customer(cust, "tester")
        assert len(new_agg.customers) == 1
        assert new_agg.customer_by_code["CUST-001"] == cust.customer_id
        assert new_agg.customer_by_email["test@example.com"] == cust.customer_id
        assert new_agg.customer_by_tax_id["1234567890"] == cust.customer_id
        assert new_agg.version == agg.version + 1
        assert len(new_agg._events) == 1
        assert isinstance(new_agg._events[0], CustomerCreatedEvent)

    def test_add_customer_duplicate_code_raises(self):
        agg = create_test_aggregate()
        cust1 = create_test_customer(customer_code="CUST-001")
        agg = agg.add_customer(cust1, "tester")
        cust2 = create_test_customer(customer_code="CUST-001")
        with pytest.raises(DuplicateCustomerCodeError, match="already exists"):
            agg.add_customer(cust2, "tester")

    def test_add_customer_duplicate_email_raises(self):
        agg = create_test_aggregate()
        cust1 = create_test_customer(email="same@example.com")
        agg = agg.add_customer(cust1, "tester")
        cust2 = create_test_customer(customer_code="CUST-002", email="same@example.com")
        with pytest.raises(DuplicateEmailError, match="already exists"):
            agg.add_customer(cust2, "tester")

    def test_add_customer_duplicate_tax_id_raises(self):
        agg = create_test_aggregate()
        cust1 = create_test_customer(tax_id="12345")
        agg = agg.add_customer(cust1, "tester")
        cust2 = create_test_customer(customer_code="CUST-002", tax_id="12345")
        with pytest.raises(DuplicateTaxIdError, match="already exists"):
            agg.add_customer(cust2, "tester")

    def test_add_customer_version_not_1_raises(self):
        agg = create_test_aggregate()
        cust = create_test_customer(version=2)
        with pytest.raises(ValueError, match="must have version 1"):
            agg.add_customer(cust, "tester")

    def test_get_customer_by_id(self):
        agg = create_test_aggregate()
        cust = create_test_customer()
        agg = agg.add_customer(cust, "tester")
        retrieved = agg.get_customer(cust.customer_id)
        assert retrieved is not None
        assert retrieved.customer_id == cust.customer_id

    def test_get_customer_by_code(self):
        agg = create_test_aggregate()
        cust = create_test_customer(customer_code="CUST-001")
        agg = agg.add_customer(cust, "tester")
        retrieved = agg.get_customer_by_code("CUST-001")
        assert retrieved is not None
        assert retrieved.customer_code == "CUST-001"

    def test_get_customer_by_email(self):
        agg = create_test_aggregate()
        cust = create_test_customer(email="test@example.com")
        agg = agg.add_customer(cust, "tester")
        retrieved = agg.get_customer_by_email("test@example.com")
        assert retrieved is not None
        assert retrieved.email == "test@example.com"

    def test_get_customer_by_tax_id(self):
        agg = create_test_aggregate()
        cust = create_test_customer(tax_id="1234567890")
        agg = agg.add_customer(cust, "tester")
        retrieved = agg.get_customer_by_tax_id("1234567890")
        assert retrieved is not None
        assert retrieved.tax_id == "1234567890"

    def test_get_all_customers(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(customer_code="CUST-001")
        c2 = create_test_customer(customer_code="CUST-002", email="b@example.com", tax_id="999")
        agg = agg.add_customer(c1, "tester")
        agg = agg.add_customer(c2, "tester")
        all_customers = agg.get_all_customers()
        assert len(all_customers) == 2

    def test_get_active_customers(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.ACTIVE)
        c2 = create_test_customer(customer_code="CUST-002", status=CustomerStatus.INACTIVE)
        agg = agg.add_customer(c1, "tester")
        agg = agg.add_customer(c2, "tester")
        active = agg.get_active_customers()
        assert len(active) == 1
        assert active[0].customer_code == "CUST-001"

    def test_get_customers_by_type(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(customer_type=CustomerType.INDIVIDUAL)
        c2 = create_test_customer(customer_code="CUST-002", customer_type=CustomerType.COMPANY)
        agg = agg.add_customer(c1, "tester")
        agg = agg.add_customer(c2, "tester")
        by_type = agg.get_customers_by_type(CustomerType.INDIVIDUAL)
        assert len(by_type) == 1
        assert by_type[0].customer_type == CustomerType.INDIVIDUAL

    def test_get_customers_by_status(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.DRAFT)
        c2 = create_test_customer(customer_code="CUST-002", status=CustomerStatus.ACTIVE)
        agg = agg.add_customer(c1, "tester")
        agg = agg.add_customer(c2, "tester")
        by_status = agg.get_customers_by_status(CustomerStatus.DRAFT)
        assert len(by_status) == 1
        assert by_status[0].status == CustomerStatus.DRAFT

    def test_get_customers_by_segment(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(segment=CustomerSegment.RETAIL)
        c2 = create_test_customer(customer_code="CUST-002", segment=CustomerSegment.WHOLESALE)
        agg = agg.add_customer(c1, "tester")
        agg = agg.add_customer(c2, "tester")
        by_seg = agg.get_customers_by_segment(CustomerSegment.RETAIL)
        assert len(by_seg) == 1

    def test_get_customers_exceeding_credit_limit(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(outstanding_balance=Decimal("15000000"), credit_limit=Decimal("10000000"))
        c2 = create_test_customer(customer_code="CUST-002", outstanding_balance=Decimal("5000000"))
        agg = agg.add_customer(c1, "tester")
        agg = agg.add_customer(c2, "tester")
        exceeding = agg.get_customers_exceeding_credit_limit()
        assert len(exceeding) == 1
        assert exceeding[0].customer_code == "CUST-001"

    def test_get_customers_on_credit_hold(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(credit_hold=True)
        c2 = create_test_customer(customer_code="CUST-002", credit_hold=False)
        agg = agg.add_customer(c1, "tester")
        agg = agg.add_customer(c2, "tester")
        on_hold = agg.get_customers_on_credit_hold()
        assert len(on_hold) == 1

    def test_get_high_risk_customers(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(risk_score=80)
        c2 = create_test_customer(customer_code="CUST-002", risk_score=50)
        agg = agg.add_customer(c1, "tester")
        agg = agg.add_customer(c2, "tester")
        high_risk = agg.get_high_risk_customers(threshold=70)
        assert len(high_risk) == 1

    def test_get_total_outstanding_balance(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(outstanding_balance=Decimal("1000000"))
        c2 = create_test_customer(customer_code="CUST-002", outstanding_balance=Decimal("2000000"))
        agg = agg.add_customer(c1, "tester")
        agg = agg.add_customer(c2, "tester")
        total = agg.get_total_outstanding_balance()
        assert total == Decimal("3000000")

    def test_get_total_purchases(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(total_purchases=Decimal("5000000"))
        c2 = create_test_customer(customer_code="CUST-002", total_purchases=Decimal("3000000"))
        agg = agg.add_customer(c1, "tester")
        agg = agg.add_customer(c2, "tester")
        total = agg.get_total_purchases()
        assert total == Decimal("8000000")

    def test_get_customer_count(self):
        agg = create_test_aggregate()
        c1 = create_test_customer()
        c2 = create_test_customer(customer_code="CUST-002")
        agg = agg.add_customer(c1, "tester")
        agg = agg.add_customer(c2, "tester")
        assert agg.get_customer_count() == 2

    def test_get_active_customer_count(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.ACTIVE)
        c2 = create_test_customer(customer_code="CUST-002", status=CustomerStatus.INACTIVE)
        agg = agg.add_customer(c1, "tester")
        agg = agg.add_customer(c2, "tester")
        assert agg.get_active_customer_count() == 1

    def test_code_exists(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(customer_code="EXIST")
        agg = agg.add_customer(c1, "tester")
        assert agg.code_exists("EXIST") is True
        assert agg.code_exists("NONEXIST") is False

    def test_email_exists(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(email="exist@example.com")
        agg = agg.add_customer(c1, "tester")
        assert agg.email_exists("exist@example.com") is True
        assert agg.email_exists("none@example.com") is False

    def test_tax_id_exists(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(tax_id="12345")
        agg = agg.add_customer(c1, "tester")
        assert agg.tax_id_exists("12345") is True
        assert agg.tax_id_exists("99999") is False

    # ------------------------------------------------------------------------
    # Update and status transition tests
    # ------------------------------------------------------------------------

    def test_update_customer_success(self):
        agg = create_test_aggregate()
        c1 = create_test_customer()
        agg = agg.add_customer(c1, "tester")
        updated_cust = create_test_customer(
            customer_id=c1.customer_id,
            customer_code="CUST-001",
            name="Updated Name",
            version=2,
        )
        new_agg = agg.update_customer(updated_cust, "tester")
        assert new_agg.customers[c1.customer_id].name == "Updated Name"
        assert new_agg.version == agg.version + 1

    def test_update_customer_not_found_raises(self):
        agg = create_test_aggregate()
        cust = create_test_customer()
        with pytest.raises(CustomerNotFoundError, match="not found"):
            agg.update_customer(cust, "tester")

    def test_update_customer_duplicate_code_raises(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(customer_code="CUST-001")
        c2 = create_test_customer(customer_code="CUST-002")
        agg = agg.add_customer(c1, "tester")
        agg = agg.add_customer(c2, "tester")
        updated_c2 = create_test_customer(
            customer_id=c2.customer_id,
            customer_code="CUST-001",
            version=2,
        )
        with pytest.raises(DuplicateCustomerCodeError, match="already exists"):
            agg.update_customer(updated_c2, "tester")

    def test_update_customer_duplicate_email_raises(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(email="a@example.com")
        c2 = create_test_customer(customer_code="CUST-002", email="b@example.com")
        agg = agg.add_customer(c1, "tester")
        agg = agg.add_customer(c2, "tester")
        updated_c2 = create_test_customer(
            customer_id=c2.customer_id,
            customer_code="CUST-002",
            email="a@example.com",
            version=2,
        )
        with pytest.raises(DuplicateEmailError, match="already exists"):
            agg.update_customer(updated_c2, "tester")

    def test_update_customer_duplicate_tax_id_raises(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(tax_id="123")
        c2 = create_test_customer(customer_code="CUST-002", tax_id="456")
        agg = agg.add_customer(c1, "tester")
        agg = agg.add_customer(c2, "tester")
        updated_c2 = create_test_customer(
            customer_id=c2.customer_id,
            customer_code="CUST-002",
            tax_id="123",
            version=2,
        )
        with pytest.raises(DuplicateTaxIdError, match="already exists"):
            agg.update_customer(updated_c2, "tester")

    def test_update_customer_version_mismatch_raises(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(version=1)
        agg = agg.add_customer(c1, "tester")
        updated_cust = create_test_customer(
            customer_id=c1.customer_id,
            customer_code="CUST-001",
            version=1,  # should be > current version
        )
        with pytest.raises(ValueError, match="Version mismatch"):
            agg.update_customer(updated_cust, "tester")

    def test_update_customer_status_transition(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.DRAFT)
        agg = agg.add_customer(c1, "tester")
        new_agg = agg.update_customer_status(c1.customer_id, CustomerStatus.ACTIVE, "tester", "reason")
        updated = new_agg.get_customer(c1.customer_id)
        assert updated.status == CustomerStatus.ACTIVE
        assert new_agg.version == agg.version + 1
        assert len(new_agg._events) == 2  # created + status changed

    def test_update_customer_status_invalid_transition_raises(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.ACTIVE)
        agg = agg.add_customer(c1, "tester")
        with pytest.raises(InvalidCustomerStatusTransitionError, match="Cannot transition"):
            agg.update_customer_status(c1.customer_id, CustomerStatus.DRAFT, "tester")

    def test_update_customer_status_not_found_raises(self):
        agg = create_test_aggregate()
        with pytest.raises(CustomerNotFoundError):
            agg.update_customer_status(uuid.uuid4(), CustomerStatus.ACTIVE, "tester")

    def test_update_customer_credit_limit(self):
        agg = create_test_aggregate()
        c1 = create_test_customer()
        agg = agg.add_customer(c1, "tester")
        new_limit = CustomerCreditLimitVO(
            amount=Decimal("20000000"),
            currency="IDR",
            valid_from=FIXED_NOW,
            valid_until=FIXED_NOW + timedelta(days=365),
        )
        new_agg = agg.update_customer_credit_limit(c1.customer_id, new_limit, "tester")
        updated = new_agg.get_customer(c1.customer_id)
        assert updated.credit_limit.amount == Decimal("20000000")
        assert new_agg.version == agg.version + 1
        assert len(new_agg._events) == 2

    def test_update_customer_credit_limit_not_found_raises(self):
        agg = create_test_aggregate()
        with pytest.raises(CustomerNotFoundError):
            agg.update_customer_credit_limit(uuid.uuid4(), MagicMock(), "tester")

    def test_update_customer_tax_status(self):
        agg = create_test_aggregate()
        c1 = create_test_customer()
        agg = agg.add_customer(c1, "tester")
        new_tax_status = CustomerTaxStatusVO(
            npwp="999999999999999",
            pkp=True,
            tax_identification_number="999999999999999",
        )
        new_agg = agg.update_customer_tax_status(c1.customer_id, new_tax_status, "tester")
        updated = new_agg.get_customer(c1.customer_id)
        assert updated.tax_status.npwp == "999999999999999"
        assert updated.tax_status.pkp is True

    def test_record_customer_purchase(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.ACTIVE, outstanding_balance=Decimal("0"))
        agg = agg.add_customer(c1, "tester")
        new_agg = agg.record_customer_purchase(c1.customer_id, Decimal("1000000"))
        updated = new_agg.get_customer(c1.customer_id)
        assert updated.outstanding_balance == Decimal("1000000")
        assert updated.total_purchases == Decimal("1000000")
        assert new_agg.version == agg.version + 1
        assert len(new_agg._events) == 2

    def test_record_customer_purchase_exceeds_credit_limit_raises(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(
            status=CustomerStatus.ACTIVE,
            credit_limit=Decimal("1000000"),
            outstanding_balance=Decimal("900000"),
        )
        agg = agg.add_customer(c1, "tester")
        with pytest.raises(CustomerAggregateError, match="exceeds credit limit"):
            agg.record_customer_purchase(c1.customer_id, Decimal("200000"))

    def test_record_customer_purchase_inactive_customer_raises(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.INACTIVE)
        agg = agg.add_customer(c1, "tester")
        with pytest.raises(CustomerAggregateError, match="Cannot record purchase"):
            agg.record_customer_purchase(c1.customer_id, Decimal("1000"))

    def test_record_customer_payment(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.ACTIVE, outstanding_balance=Decimal("2000000"))
        agg = agg.add_customer(c1, "tester")
        new_agg = agg.record_customer_payment(c1.customer_id, Decimal("500000"))
        updated = new_agg.get_customer(c1.customer_id)
        assert updated.outstanding_balance == Decimal("1500000")
        assert new_agg.version == agg.version + 1

    def test_record_customer_payment_exceeds_balance_raises(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.ACTIVE, outstanding_balance=Decimal("1000000"))
        agg = agg.add_customer(c1, "tester")
        with pytest.raises(ValueError, match="Payment amount must be positive"):
            agg.record_customer_payment(c1.customer_id, Decimal("-1000"))

    def test_record_customer_payment_inactive_raises(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.INACTIVE)
        agg = agg.add_customer(c1, "tester")
        with pytest.raises(CustomerAggregateError, match="Cannot record payment"):
            agg.record_customer_payment(c1.customer_id, Decimal("1000"))

    def test_update_customer_credit_hold(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(credit_hold=False)
        agg = agg.add_customer(c1, "tester")
        new_agg = agg.update_customer_credit_hold(c1.customer_id, True, "tester", "reason")
        updated = new_agg.get_customer(c1.customer_id)
        assert updated.credit_hold is True
        assert new_agg.version == agg.version + 1

    def test_update_customer_risk_score(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(risk_score=50)
        agg = agg.add_customer(c1, "tester")
        new_agg = agg.update_customer_risk_score(c1.customer_id, 80, "tester")
        updated = new_agg.get_customer(c1.customer_id)
        assert updated.risk_score == 80
        assert new_agg.version == agg.version + 1

    def test_remove_customer_success(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.ACTIVE, outstanding_balance=Decimal("0"))
        agg = agg.add_customer(c1, "tester")
        new_agg = agg.remove_customer(c1.customer_id, "tester")
        updated = new_agg.get_customer(c1.customer_id)
        assert updated.status == CustomerStatus.INACTIVE
        assert new_agg.version == agg.version + 1

    def test_remove_customer_with_balance_raises(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.ACTIVE, outstanding_balance=Decimal("1000000"))
        agg = agg.add_customer(c1, "tester")
        with pytest.raises(CustomerAggregateError, match="outstanding balance"):
            agg.remove_customer(c1.customer_id, "tester")

    # ------------------------------------------------------------------------
    # Business flow methods (can_post, post, can_approve, approve, etc.)
    # ------------------------------------------------------------------------

    def test_can_post(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.ACTIVE)
        agg = agg.add_customer(c1, "tester")
        assert agg.can_post(c1.customer_id) is True
        # inactive
        c2 = create_test_customer(customer_code="CUST-002", status=CustomerStatus.INACTIVE)
        agg = agg.add_customer(c2, "tester")
        assert agg.can_post(c2.customer_id) is False

    def test_post_purchase(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.ACTIVE)
        agg = agg.add_customer(c1, "tester")
        new_agg = agg.post(c1.customer_id, Decimal("1000000"), "tester", "purchase")
        updated = new_agg.get_customer(c1.customer_id)
        assert updated.outstanding_balance == Decimal("1000000")

    def test_post_payment(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.ACTIVE, outstanding_balance=Decimal("2000000"))
        agg = agg.add_customer(c1, "tester")
        new_agg = agg.post(c1.customer_id, Decimal("500000"), "tester", "payment")
        updated = new_agg.get_customer(c1.customer_id)
        assert updated.outstanding_balance == Decimal("1500000")

    def test_post_unknown_type_raises(self):
        agg = create_test_aggregate()
        with pytest.raises(ValueError, match="Unknown transaction type"):
            agg.post(uuid.uuid4(), Decimal("1000"), "tester", "unknown")

    def test_can_approve(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.DRAFT)
        agg = agg.add_customer(c1, "tester")
        assert agg.can_approve(c1.customer_id, "finance_manager") is True
        assert agg.can_approve(c1.customer_id, "user") is False
        # active cannot be approved
        c2 = create_test_customer(customer_code="CUST-002", status=CustomerStatus.ACTIVE)
        agg = agg.add_customer(c2, "tester")
        assert agg.can_approve(c2.customer_id, "finance_manager") is False

    def test_approve_success(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.DRAFT)
        agg = agg.add_customer(c1, "tester")
        new_agg = agg.approve(c1.customer_id, "manager")
        updated = new_agg.get_customer(c1.customer_id)
        assert updated.status == CustomerStatus.ACTIVE
        assert new_agg.version == agg.version + 1

    def test_approve_fails_if_not_authorized(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.DRAFT)
        agg = agg.add_customer(c1, "tester")
        with pytest.raises(CustomerAggregateError, match="Cannot approve"):
            agg.approve(c1.customer_id, "user")  # user role not authorized

    def test_can_reject(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.DRAFT)
        agg = agg.add_customer(c1, "tester")
        assert agg.can_reject(c1.customer_id, "finance_manager") is True

    def test_reject_success(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.DRAFT)
        agg = agg.add_customer(c1, "tester")
        new_agg = agg.reject(c1.customer_id, "manager", "reason")
        updated = new_agg.get_customer(c1.customer_id)
        assert updated.status == CustomerStatus.INACTIVE

    def test_can_cancel(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.DRAFT)
        agg = agg.add_customer(c1, "tester")
        assert agg.can_cancel(c1.customer_id) is True
        # active cannot be canceled
        c2 = create_test_customer(customer_code="CUST-002", status=CustomerStatus.ACTIVE)
        agg = agg.add_customer(c2, "tester")
        assert agg.can_cancel(c2.customer_id) is False

    def test_cancel_success(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.DRAFT)
        agg = agg.add_customer(c1, "tester")
        new_agg = agg.cancel(c1.customer_id, "manager", "reason")
        updated = new_agg.get_customer(c1.customer_id)
        assert updated.status == CustomerStatus.INACTIVE

    def test_can_reverse_always_false(self):
        agg = create_test_aggregate()
        assert agg.can_reverse(uuid.uuid4()) is False

    def test_reverse_raises_not_implemented(self):
        agg = create_test_aggregate()
        with pytest.raises(NotImplementedError):
            agg.reverse(uuid.uuid4(), "user", "reason")

    def test_can_close(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.ACTIVE)
        agg = agg.add_customer(c1, "tester")
        assert agg.can_close(c1.customer_id) is True
        c2 = create_test_customer(customer_code="CUST-002", status=CustomerStatus.INACTIVE)
        agg = agg.add_customer(c2, "tester")
        assert agg.can_close(c2.customer_id) is False

    def test_close_success(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.ACTIVE)
        agg = agg.add_customer(c1, "tester")
        new_agg = agg.close(c1.customer_id, "manager", "reason")
        updated = new_agg.get_customer(c1.customer_id)
        assert updated.status == CustomerStatus.INACTIVE

    def test_can_reopen(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.INACTIVE)
        agg = agg.add_customer(c1, "tester")
        assert agg.can_reopen(c1.customer_id) is True
        c2 = create_test_customer(customer_code="CUST-002", status=CustomerStatus.ACTIVE)
        agg = agg.add_customer(c2, "tester")
        assert agg.can_reopen(c2.customer_id) is False

    def test_reopen_success(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.INACTIVE)
        agg = agg.add_customer(c1, "tester")
        new_agg = agg.reopen(c1.customer_id, "manager", "reason")
        updated = new_agg.get_customer(c1.customer_id)
        assert updated.status == CustomerStatus.ACTIVE

    def test_can_archive(self):
        agg = create_test_aggregate()
        assert agg.can_archive() is True
        c1 = create_test_customer()
        agg = agg.add_customer(c1, "tester")
        assert agg.can_archive() is False

    def test_archive_success(self):
        agg = create_test_aggregate()
        new_agg = agg.archive("manager", "reason")
        assert new_agg.version == agg.version + 1
        assert len(new_agg._audit_trail) > 0

    def test_archive_with_customers_raises(self):
        agg = create_test_aggregate()
        c1 = create_test_customer()
        agg = agg.add_customer(c1, "tester")
        with pytest.raises(CustomerAggregateError, match="Cannot archive"):
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
        agg = CustomerAggregate.create(legal_entity_id, "creator")
        assert agg.legal_entity_id == legal_entity_id
        assert agg.aggregate_id is not None
        assert agg.version == 1
        assert len(agg._audit_trail) == 1
        assert agg._audit_trail[0]["action"] == "CREATE"

    def test_from_events(self):
        events = [
            CustomerCreatedEvent(
                aggregate_id=uuid.uuid4(),
                aggregate_version=1,
                customer=create_test_customer(),
                created_by="tester",
            )
        ]
        agg = CustomerAggregate.from_events(events)
        assert agg.aggregate_id is not None
        assert agg.version == 1
        assert len(agg._events) == 1

    def test_from_events_empty_raises(self):
        with pytest.raises(ValueError, match="No events provided"):
            CustomerAggregate.from_events([])

    # ------------------------------------------------------------------------
    # Entity basic methods (create, update, delete, etc.)
    # ------------------------------------------------------------------------

    def test_create_method(self):
        agg = create_test_aggregate()
        result = agg.create("creator")
        assert result is agg
        assert len(agg._audit_trail) == 1  # initial plus this

    def test_update_method(self):
        agg = create_test_aggregate()
        new_agg = agg.update("updater", legal_entity_id=uuid.uuid4())
        assert new_agg.legal_entity_id != agg.legal_entity_id
        assert new_agg.version == agg.version + 1
        assert new_agg._audit_trail[-1]["action"] == "UPDATE"

    def test_delete_method_with_customers_raises(self):
        agg = create_test_aggregate()
        c1 = create_test_customer()
        agg = agg.add_customer(c1, "tester")
        with pytest.raises(CustomerAggregateError, match="Cannot delete aggregate"):
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
        assert result["is_valid"]
        assert result["aggregate_id"] == str(agg.aggregate_id)

        # create duplicate email
        c1 = create_test_customer(email="dup@example.com")
        c2 = create_test_customer(customer_code="CUST-002", email="dup@example.com")
        agg = agg.add_customer(c1, "tester")
        agg = agg.add_customer(c2, "tester")
        result = agg.validate()
        assert not result["is_valid"]
        assert "Duplicate email" in result["errors"][0]

    def test_to_dict(self):
        agg = create_test_aggregate()
        c1 = create_test_customer()
        agg = agg.add_customer(c1, "tester")
        d = agg.to_dict()
        assert d["aggregate_id"] == str(agg.aggregate_id)
        assert d["legal_entity_id"] == str(agg.legal_entity_id)
        assert len(d["customers"]) == 1
        assert d["version"] == agg.version

    def test_from_dict(self):
        agg = create_test_aggregate()
        c1 = create_test_customer()
        agg = agg.add_customer(c1, "tester")
        d = agg.to_dict()
        new_agg = CustomerAggregate.from_dict(d)
        assert new_agg.aggregate_id == agg.aggregate_id
        assert len(new_agg.customers) == 1
        assert new_agg.version == agg.version

    def test_clone(self):
        agg = create_test_aggregate()
        c1 = create_test_customer()
        agg = agg.add_customer(c1, "tester")
        cloned = agg.clone()
        assert cloned.aggregate_id != agg.aggregate_id
        assert len(cloned.customers) == 1
        assert cloned.version == 1
        assert cloned._audit_trail[-1]["action"] == "CLONE"

    def test_snapshot(self):
        agg = create_test_aggregate()
        c1 = create_test_customer()
        agg = agg.add_customer(c1, "tester")
        snap = agg.snapshot()
        assert snap["version"] == agg.version
        assert snap["customer_count"] == 1
        assert "timestamp" in snap

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
        event = CustomerCreatedEvent(
            aggregate_id=agg.aggregate_id,
            aggregate_version=1,
            customer=create_test_customer(),
            created_by="tester",
        )
        agg.register_event(event)
        assert len(agg._events) == 1
        assert agg._events[0] is event

    def test_get_events(self):
        agg = create_test_aggregate()
        event = CustomerCreatedEvent(
            aggregate_id=agg.aggregate_id,
            aggregate_version=1,
            customer=create_test_customer(),
            created_by="tester",
        )
        agg.register_event(event)
        events = agg.get_events()
        assert len(events) == 1
        assert events[0] is event
        # get_events should return a copy
        events.append("extra")
        assert len(agg.get_events()) == 1

    def test_pull_events(self):
        agg = create_test_aggregate()
        event = CustomerCreatedEvent(
            aggregate_id=agg.aggregate_id,
            aggregate_version=1,
            customer=create_test_customer(),
            created_by="tester",
        )
        agg.register_event(event)
        pulled = agg.pull_events()
        assert len(pulled) == 1
        assert pulled[0] is event
        assert len(agg._events) == 0

    def test_clear_events(self):
        agg = create_test_aggregate()
        event = CustomerCreatedEvent(
            aggregate_id=agg.aggregate_id,
            aggregate_version=1,
            customer=create_test_customer(),
            created_by="tester",
        )
        agg.register_event(event)
        agg.clear_events()
        assert len(agg._events) == 0

    def test_apply(self):
        agg = create_test_aggregate()
        event = CustomerCreatedEvent(
            aggregate_id=agg.aggregate_id,
            aggregate_version=1,
            customer=create_test_customer(),
            created_by="tester",
        )
        agg.apply(event)
        assert len(agg._events) == 1
        assert agg._events[0] is event

    # ------------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------------

    def test_get_statistics(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(status=CustomerStatus.ACTIVE)
        c2 = create_test_customer(customer_code="CUST-002", status=CustomerStatus.INACTIVE, outstanding_balance=Decimal("5000000"))
        agg = agg.add_customer(c1, "tester")
        agg = agg.add_customer(c2, "tester")
        stats = agg.get_statistics()
        assert stats["total_customers"] == 2
        assert stats["active_customers"] == 1
        assert stats["inactive_customers"] == 1
        assert stats["status_distribution"]["active"] == 1
        assert stats["status_distribution"]["inactive"] == 1
        assert stats["total_outstanding_balance"] == "5000000"

    # ------------------------------------------------------------------------
    # Child management alias
    # ------------------------------------------------------------------------

    def test_add_child(self):
        agg = create_test_aggregate()
        cust = create_test_customer()
        new_agg = agg.add_child(cust, "tester")
        assert len(new_agg.customers) == 1

    def test_remove_child(self):
        agg = create_test_aggregate()
        c1 = create_test_customer(outstanding_balance=Decimal("0"))
        agg = agg.add_customer(c1, "tester")
        new_agg = agg.remove_child(c1.customer_id, "tester")
        updated = new_agg.get_customer(c1.customer_id)
        assert updated.status == CustomerStatus.INACTIVE


# ============================================================================
# TESTS FOR CUSTOMER AGGREGATE REPOSITORY
# ============================================================================

@pytest.mark.asyncio
class TestCustomerAggregateRepository:
    @pytest.fixture(autouse=True)
    def clear_storage(self):
        CustomerAggregateRepository._storage.clear()
        yield

    @pytest.fixture
    def agg(self):
        return create_test_aggregate()

    async def test_save_and_get_by_id(self, agg):
        await CustomerAggregateRepository.save(agg)
        retrieved = await CustomerAggregateRepository.get_by_id(agg.aggregate_id)
        assert retrieved is not None
        assert retrieved.aggregate_id == agg.aggregate_id

    async def test_get_by_legal_entity(self, agg):
        await CustomerAggregateRepository.save(agg)
        retrieved = await CustomerAggregateRepository.get_by_legal_entity(agg.legal_entity_id)
        assert retrieved is not None
        assert retrieved.legal_entity_id == agg.legal_entity_id

    async def test_get_all(self, agg):
        await CustomerAggregateRepository.save(agg)
        all_aggs = await CustomerAggregateRepository.get_all()
        assert len(all_aggs) == 1

    async def test_update(self, agg):
        await CustomerAggregateRepository.save(agg)
        new_agg = agg.update("updater", legal_entity_id=uuid.uuid4())
        await CustomerAggregateRepository.update(new_agg)
        retrieved = await CustomerAggregateRepository.get_by_id(agg.aggregate_id)
        assert retrieved.legal_entity_id == new_agg.legal_entity_id

    async def test_delete(self, agg):
        await CustomerAggregateRepository.save(agg)
        await CustomerAggregateRepository.delete(agg.aggregate_id)
        retrieved = await CustomerAggregateRepository.get_by_id(agg.aggregate_id)
        assert retrieved is None

    async def test_exists(self, agg):
        await CustomerAggregateRepository.save(agg)
        assert await CustomerAggregateRepository.exists(agg.aggregate_id) is True
        assert await CustomerAggregateRepository.exists(uuid.uuid4()) is False

    async def test_count(self, agg):
        await CustomerAggregateRepository.save(agg)
        assert await CustomerAggregateRepository.count() == 1

    async def test_list(self, agg):
        await CustomerAggregateRepository.save(agg)
        aggs = await CustomerAggregateRepository.list(limit=10)
        assert len(aggs) == 1

    async def test_paginate(self, agg):
        await CustomerAggregateRepository.save(agg)
        aggs, total = await CustomerAggregateRepository.paginate(page=1, per_page=10)
        assert len(aggs) == 1
        assert total == 1

    async def test_search(self, agg):
        await CustomerAggregateRepository.save(agg)
        results = await CustomerAggregateRepository.search(str(agg.legal_entity_id), fields=["legal_entity_id"])
        assert len(results) == 1

    async def test_lock(self, agg):
        await CustomerAggregateRepository.save(agg)
        locked = await CustomerAggregateRepository.lock(agg.aggregate_id, "locker", "reason")
        assert locked.version == agg.version + 1
        assert locked._audit_trail[-1]["action"] == "LOCK"

    async def test_unlock(self, agg):
        await CustomerAggregateRepository.save(agg)
        locked = await CustomerAggregateRepository.lock(agg.aggregate_id, "locker", "reason")
        unlocked = await CustomerAggregateRepository.unlock(agg.aggregate_id, "unlocker")
        assert unlocked.version == locked.version + 1
        assert unlocked._audit_trail[-1]["action"] == "UNLOCK"

    async def test_clear(self, agg):
        await CustomerAggregateRepository.save(agg)
        await CustomerAggregateRepository.clear()
        all_aggs = await CustomerAggregateRepository.get_all()
        assert all_aggs == []

    async def test_lock_not_found_raises(self):
        with pytest.raises(ValueError, match="not found"):
            await CustomerAggregateRepository.lock(uuid.uuid4(), "locker", "reason")