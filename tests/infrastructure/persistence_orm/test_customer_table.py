# tests/infrastructure/persistence_orm/test_customer_table.py
"""
Comprehensive unit tests for infrastructure/persistence_orm/customer_table.py.
Covers ORM model initialization, all properties, methods, and edge cases.
No database session required – tests use in-memory model instances.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from infrastructure.persistence_orm.customer_table import CustomerTable

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_customer_data():
    return {
        "id": uuid.uuid4(),
        "customer_code": "CUST-001",
        "customer_name": "PT Test Customer",
        "customer_type": "company",
        "tax_id": "123456789012345",
        "tax_status": "pkp",
        "address": "Jl. Sudirman No. 1",
        "shipping_address": "Jl. Thamrin No. 2",
        "city": "Jakarta",
        "postal_code": "10110",
        "country": "ID",
        "phone": "021-1234567",
        "email": "info@test.com",
        "website": "www.test.com",
        "contact_person": "John Doe",
        "contact_phone": "08123456789",
        "contact_email": "john@test.com",
        "credit_limit": Decimal("100000000"),
        "used_credit": Decimal("30000000"),
        "payment_term_days": 30,
        "discount_percent": Decimal("5.00"),
        "category": "RETAIL",
        "price_group": "GOLD",
        "sales_person_id": uuid.uuid4(),
        "bank_name": "BCA",
        "bank_account_number": "1234567890",
        "bank_account_name": "PT Test",
        "status": "active",
        "is_active": True,
        "blocked_reason": None,
        "first_purchase_date": date(2025, 1, 1),
        "last_purchase_date": date(2026, 7, 1),
        "credit_check_date": date(2026, 1, 1),
        "extra_metadata": {"industry": "retail"},
        "created_by": uuid.uuid4(),
        "legal_entity_id": uuid.uuid4(),
        "version": 1,
    }


@pytest.fixture
def customer(sample_customer_data):
    """Create a CustomerTable instance."""
    return CustomerTable(**sample_customer_data)


# ============================================================================
# Tests for ORM model definition
# ============================================================================

class TestCustomerTableDefinition:
    def test_tablename(self):
        assert CustomerTable.__tablename__ == "customer"

    def test_table_args(self):
        # Check that unique constraints and indexes exist
        args = CustomerTable.__table_args__
        assert any("uq_customer_code_legal_entity" in str(arg) for arg in args)
        assert any("uq_customer_tax_id" in str(arg) for arg in args)
        assert any("ck_customer_code" in str(arg) for arg in args)
        assert any("ck_customer_name" in str(arg) for arg in args)
        assert any("idx_customer_customer_code" in str(arg) for arg in args)
        assert any("idx_customer_status" in str(arg) for arg in args)

    def test_columns_exist(self, customer):
        # Check that all expected columns are accessible
        assert hasattr(customer, "id")
        assert hasattr(customer, "customer_code")
        assert hasattr(customer, "customer_name")
        assert hasattr(customer, "credit_limit")
        assert hasattr(customer, "used_credit")
        assert hasattr(customer, "status")
        assert hasattr(customer, "is_active")


# ============================================================================
# Tests for properties
# ============================================================================

class TestCustomerTableProperties:
    def test_available_credit(self, customer):
        # credit_limit 100M, used_credit 30M => available 70M
        assert customer.available_credit == Decimal("70000000")
        # When used_credit > credit_limit, available should be 0
        customer.used_credit = Decimal("150000000")
        assert customer.available_credit == Decimal("0")
        customer.used_credit = Decimal("-10000")
        assert customer.available_credit == Decimal("100010000")

    def test_is_credit_exceeded(self, customer):
        assert customer.is_credit_exceeded is False
        customer.used_credit = Decimal("150000000")
        assert customer.is_credit_exceeded is True
        # Equal is not exceeded
        customer.used_credit = Decimal("100000000")
        assert customer.is_credit_exceeded is False

    def test_is_blocked(self, customer):
        assert customer.is_blocked is False
        customer.status = "blocked"
        assert customer.is_blocked is True
        customer.status = "suspended"
        assert customer.is_blocked is False

    def test_is_active_customer(self, customer):
        assert customer.is_active_customer is True
        customer.status = "inactive"
        assert customer.is_active_customer is False
        customer.is_active = False
        customer.status = "active"
        assert customer.is_active_customer is False

    def test_credit_utilization_percent(self, customer):
        # 30M / 100M * 100 = 30%
        assert customer.credit_utilization_percent == Decimal("30")
        # Zero credit limit -> 0
        customer.credit_limit = Decimal("0")
        assert customer.credit_utilization_percent == Decimal("0")
        # Used credit exceeds limit -> >100%
        customer.credit_limit = Decimal("100000000")
        customer.used_credit = Decimal("150000000")
        assert customer.credit_utilization_percent == Decimal("150")


# ============================================================================
# Tests for methods
# ============================================================================

class TestCustomerTableMethods:
    def test_activate(self, customer):
        customer.status = "inactive"
        customer.is_active = False
        customer.blocked_reason = "Some reason"
        old_version = customer.version
        customer.activate()
        assert customer.status == "active"
        assert customer.is_active is True
        assert customer.blocked_reason is None
        assert customer.version == old_version + 1

    def test_activate_when_already_active(self, customer):
        old_version = customer.version
        customer.activate()
        assert customer.status == "active"
        assert customer.is_active is True
        assert customer.version == old_version + 1  # version still increments

    def test_deactivate(self, customer):
        old_version = customer.version
        customer.deactivate()
        assert customer.status == "inactive"
        assert customer.is_active is False
        assert customer.version == old_version + 1

    def test_block(self, customer):
        reason = "Fraud suspicion"
        old_version = customer.version
        customer.block(reason)
        assert customer.status == "blocked"
        assert customer.blocked_reason == reason
        assert customer.version == old_version + 1

    def test_update_credit_usage(self, customer):
        old_version = customer.version
        customer.update_credit_usage(Decimal("5000000"))
        assert customer.used_credit == Decimal("35000000")
        assert customer.version == old_version + 1

    def test_update_credit_usage_negative(self, customer):
        old_version = customer.version
        customer.update_credit_usage(Decimal("-10000000"))
        assert customer.used_credit == Decimal("20000000")
        assert customer.version == old_version + 1

    def test_reset_credit_usage(self, customer):
        old_version = customer.version
        customer.reset_credit_usage()
        assert customer.used_credit == Decimal("0")
        assert customer.version == old_version + 1

    def test_record_purchase(self, customer):
        old_version = customer.version
        purchase_date = date(2026, 7, 23)
        amount = Decimal("10000000")
        customer.record_purchase(purchase_date, amount)
        assert customer.last_purchase_date == purchase_date
        assert customer.first_purchase_date == date(2025, 1, 1)  # unchanged
        assert customer.used_credit == Decimal("40000000")
        assert customer.version == old_version + 1

    def test_record_purchase_first_purchase(self, customer):
        customer.first_purchase_date = None
        purchase_date = date(2026, 7, 23)
        customer.record_purchase(purchase_date, Decimal("1000"))
        assert customer.first_purchase_date == purchase_date
        assert customer.last_purchase_date == purchase_date

    def test_can_create_invoice(self, customer):
        # Active, credit limit 100M, used 30M, invoice 70M => OK
        assert customer.can_create_invoice(Decimal("70000000")) is True
        # Invoice 71M => exceeds limit
        assert customer.can_create_invoice(Decimal("71000000")) is False
        # Zero credit limit => always allowed
        customer.credit_limit = Decimal("0")
        assert customer.can_create_invoice(Decimal("1000000000")) is True
        # Inactive customer
        customer.credit_limit = Decimal("100000000")
        customer.status = "inactive"
        assert customer.can_create_invoice(Decimal("1000")) is False
        # Blocked customer
        customer.status = "blocked"
        assert customer.can_create_invoice(Decimal("1000")) is False

    def test_can_create_invoice_negative_amount(self, customer):
        # Even if negative, should still check logic; but we treat as valid if within credit
        customer.used_credit = Decimal("100000000")
        # Invoice negative reduces usage, so should be allowed
        assert customer.can_create_invoice(Decimal("-1000")) is True

    def test_to_dict(self, customer):
        d = customer.to_dict()
        assert d["id"] == str(customer.id)
        assert d["customer_code"] == "CUST-001"
        assert d["customer_name"] == "PT Test Customer"
        assert d["credit_limit"] == float(customer.credit_limit)
        assert d["used_credit"] == float(customer.used_credit)
        assert d["available_credit"] == float(customer.available_credit)
        assert d["status"] == "active"
        assert d["is_active"] is True
        assert d["legal_entity_id"] == str(customer.legal_entity_id)
        assert d["version"] == customer.version
        assert d["extra_metadata"] == {"industry": "retail"}


# ============================================================================
# Edge cases and corner cases
# ============================================================================

class TestCustomerTableEdgeCases:
    def test_credit_limit_zero(self, customer):
        customer.credit_limit = Decimal("0")
        customer.used_credit = Decimal("100")
        assert customer.available_credit == Decimal("0")
        assert customer.is_credit_exceeded is True
        assert customer.credit_utilization_percent == Decimal("0")

    def test_credit_limit_negative(self, customer):
        # Should not happen with constraints, but test defensively
        customer.credit_limit = Decimal("-1000000")
        customer.used_credit = Decimal("0")
        assert customer.available_credit == Decimal("0")
        assert customer.is_credit_exceeded is True

    def test_used_credit_negative(self, customer):
        customer.used_credit = Decimal("-1000")
        assert customer.available_credit == Decimal("100001000")
        assert customer.is_credit_exceeded is False

    def test_activate_already_blocked(self, customer):
        customer.status = "blocked"
        customer.blocked_reason = "Fraud"
        customer.activate()
        assert customer.status == "active"
        assert customer.is_active is True
        assert customer.blocked_reason is None

    def test_deactivate_already_inactive(self, customer):
        customer.status = "inactive"
        old_version = customer.version
        customer.deactivate()
        assert customer.status == "inactive"
        assert customer.version == old_version + 1


# ============================================================================
# Tests for SQLAlchemy column types (using dummy values)
# ============================================================================

class TestCustomerTableColumnTypes:
    def test_all_columns_assignable(self, sample_customer_data):
        # Ensure that we can assign all types correctly.
        cust = CustomerTable(**sample_customer_data)
        # UUID fields
        assert isinstance(cust.id, uuid.UUID)
        assert isinstance(cust.legal_entity_id, uuid.UUID)
        # Decimal fields
        assert isinstance(cust.credit_limit, Decimal)
        assert isinstance(cust.used_credit, Decimal)
        # Date fields
        assert isinstance(cust.first_purchase_date, date)
        # JSONB
        assert isinstance(cust.extra_metadata, dict)
        # Boolean
        assert isinstance(cust.is_active, bool)

    def test_nullable_fields_accept_none(self):
        data = {
            "id": uuid.uuid4(),
            "customer_code": "CUST-002",
            "customer_name": "Test Customer",
            "customer_type": "company",
            "tax_status": "pkp",
            "country": "ID",
            "credit_limit": Decimal("0"),
            "used_credit": Decimal("0"),
            "payment_term_days": 30,
            "discount_percent": Decimal("0"),
            "status": "active",
            "is_active": True,
            "legal_entity_id": uuid.uuid4(),
        }
        cust = CustomerTable(**data)
        assert cust.tax_id is None
        assert cust.address is None
        assert cust.extra_metadata is None
        assert cust.created_by is None
