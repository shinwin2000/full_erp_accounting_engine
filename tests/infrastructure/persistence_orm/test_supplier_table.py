# tests/infrastructure/persistence_orm/test_supplier_table.py
"""
Comprehensive tests for infrastructure/persistence_orm/supplier_table.py
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from infrastructure.persistence_orm.supplier_table import SupplierTable


class TestSupplierTable:
    """Tests for the SupplierTable ORM model."""

    def test_tablename_defined(self):
        assert hasattr(SupplierTable, "__tablename__")
        assert isinstance(SupplierTable.__tablename__, str)
        assert len(SupplierTable.__tablename__) > 0

    def test_instantiation(self):
        instance = SupplierTable(
            id=uuid4(),
            supplier_code="SUP-001",
            supplier_name="PT Supplier Maju",
            supplier_type="company",
            status="active",
            is_active=True,
            payment_term_days=30,
        )
        assert isinstance(instance, SupplierTable)
        assert instance.supplier_code == "SUP-001"
        assert instance.supplier_name == "PT Supplier Maju"

    # -------------------- Fixtures --------------------
    @pytest.fixture
    def supplier(self):
        return SupplierTable(
            id=uuid4(),
            supplier_code="SUP-001",
            supplier_name="PT Supplier Maju",
            supplier_type="company",
            tax_id="123456789012345",
            tax_status="pkp",
            withholding_category="pph23",
            withholding_rate=Decimal("0"),
            has_npwp=True,
            country="ID",
            payment_term_days=30,
            discount_percent=Decimal("0"),
            lead_time_days=7,
            quality_rating=Decimal("4.5"),
            on_time_delivery_rate=Decimal("95.5"),
            status="active",
            is_active=True,
            blocked_reason=None,
            version=1,
        )

    @pytest.fixture
    def inactive_supplier(self):
        return SupplierTable(
            id=uuid4(),
            supplier_code="SUP-002",
            supplier_name="PT Inactive",
            status="inactive",
            is_active=False,
            version=1,
        )

    @pytest.fixture
    def blocked_supplier(self):
        return SupplierTable(
            id=uuid4(),
            supplier_code="SUP-003",
            supplier_name="PT Blocked",
            status="blocked",
            is_active=False,
            blocked_reason="Late deliveries",
            version=1,
        )

    # -------------------- Property Tests --------------------
    def test_effective_withholding_rate_pph23_with_npwp(self, supplier):
        # pph23 with npwp -> 2%
        supplier.withholding_category = "pph23"
        supplier.has_npwp = True
        assert supplier.effective_withholding_rate == Decimal("2.0")

    def test_effective_withholding_rate_pph23_without_npwp(self, supplier):
        supplier.withholding_category = "pph23"
        supplier.has_npwp = False
        assert supplier.effective_withholding_rate == Decimal("4.0")

    def test_effective_withholding_rate_pph26(self, supplier):
        supplier.withholding_category = "pph26"
        assert supplier.effective_withholding_rate == Decimal("20.0")

    def test_effective_withholding_rate_both_with_npwp(self, supplier):
        supplier.withholding_category = "both"
        supplier.has_npwp = True
        assert supplier.effective_withholding_rate == Decimal("2.0")

    def test_effective_withholding_rate_both_without_npwp(self, supplier):
        supplier.withholding_category = "both"
        supplier.has_npwp = False
        assert supplier.effective_withholding_rate == Decimal("4.0")

    def test_effective_withholding_rate_none(self, supplier):
        supplier.withholding_category = "none"
        assert supplier.effective_withholding_rate == Decimal("0")

    def test_is_active_supplier(self, supplier, inactive_supplier):
        assert supplier.is_active_supplier is True
        assert inactive_supplier.is_active_supplier is False
        # active but is_active False
        supplier.is_active = False
        assert supplier.is_active_supplier is False

    def test_is_blocked(self, supplier, blocked_supplier):
        assert supplier.is_blocked is False
        assert blocked_supplier.is_blocked is True

    # -------------------- Method Tests --------------------
    def test_activate(self, inactive_supplier):
        inactive_supplier.activate()
        assert inactive_supplier.status == "active"
        assert inactive_supplier.is_active is True
        assert inactive_supplier.blocked_reason is None
        assert inactive_supplier.version == 2

    def test_deactivate(self, supplier):
        supplier.deactivate()
        assert supplier.status == "inactive"
        assert supplier.is_active is False
        assert supplier.version == 2

    def test_block(self, supplier):
        reason = "Quality issues"
        supplier.block(reason)
        assert supplier.status == "blocked"
        assert supplier.blocked_reason == reason
        assert supplier.is_active is False  # blocked implies inactive
        assert supplier.version == 2

    def test_record_purchase_first_time(self, supplier):
        purchase_date = date(2026, 7, 31)
        assert supplier.first_purchase_date is None
        supplier.record_purchase(purchase_date)
        assert supplier.last_purchase_date == purchase_date
        assert supplier.first_purchase_date == purchase_date
        assert supplier.version == 2

    def test_record_purchase_subsequent(self, supplier):
        first = date(2026, 1, 1)
        second = date(2026, 7, 31)
        supplier.first_purchase_date = first
        supplier.last_purchase_date = first
        supplier.record_purchase(second)
        assert supplier.last_purchase_date == second
        assert supplier.first_purchase_date == first  # unchanged
        assert supplier.version == 2

    def test_update_quality_rating(self, supplier):
        new_rating = Decimal("4.8")
        supplier.update_quality_rating(new_rating)
        assert supplier.quality_rating == new_rating
        assert supplier.version == 2

    def test_update_on_time_delivery(self, supplier):
        new_rate = Decimal("98.7")
        supplier.update_on_time_delivery(new_rate)
        assert supplier.on_time_delivery_rate == new_rate
        assert supplier.version == 2

    def test_can_create_po_active(self, supplier):
        assert supplier.can_create_po() is True

    def test_can_create_po_inactive(self, inactive_supplier):
        assert inactive_supplier.can_create_po() is False

    def test_can_create_po_blocked(self, blocked_supplier):
        assert blocked_supplier.can_create_po() is False

    # -------------------- to_dict Tests --------------------
    def test_to_dict(self, supplier):
        d = supplier.to_dict()
        assert d["supplier_code"] == "SUP-001"
        assert d["supplier_name"] == "PT Supplier Maju"
        assert d["withholding_category"] == "pph23"
        assert d["withholding_rate"] == float(supplier.withholding_rate)
        assert d["effective_withholding_rate"] == float(supplier.effective_withholding_rate)
        assert d["has_npwp"] is True
        assert d["payment_term_days"] == 30
        assert d["quality_rating"] == float(supplier.quality_rating)
        assert d["on_time_delivery_rate"] == float(supplier.on_time_delivery_rate)
        assert d["status"] == "active"
        assert d["is_active"] is True
        assert d["version"] == 1

    # -------------------- Edge Cases --------------------
    def test_effective_withholding_rate_unknown_category(self, supplier):
        # If category is something else, should return 0
        supplier.withholding_category = "unknown"
        assert supplier.effective_withholding_rate == Decimal("0")

    def test_activate_already_active(self, supplier):
        # Activating an active supplier should be idempotent (just sets version)
        old_version = supplier.version
        supplier.activate()
        assert supplier.status == "active"
        assert supplier.is_active is True
        assert supplier.version == old_version + 1

    def test_block_already_blocked(self, blocked_supplier):
        old_version = blocked_supplier.version
        blocked_supplier.block("New reason")
        assert blocked_supplier.status == "blocked"
        assert blocked_supplier.blocked_reason == "New reason"
        assert blocked_supplier.version == old_version + 1

    def test_deactivate_already_inactive(self, inactive_supplier):
        old_version = inactive_supplier.version
        inactive_supplier.deactivate()
        assert inactive_supplier.status == "inactive"
        assert inactive_supplier.is_active is False
        assert inactive_supplier.version == old_version + 1

    def test_record_purchase_with_date_in_future(self, supplier):
        # Should still record even if date is in future (business logic may allow)
        future = date.today() + timedelta(days=10)
        supplier.record_purchase(future)
        assert supplier.last_purchase_date == future
        assert supplier.first_purchase_date == future
        assert supplier.version == 2

    def test_update_quality_rating_with_negative(self, supplier):
        # Should accept any Decimal, validation not in this method
        supplier.update_quality_rating(Decimal("-1"))
        assert supplier.quality_rating == Decimal("-1")
        assert supplier.version == 2

    def test_update_on_time_delivery_with_negative(self, supplier):
        supplier.update_on_time_delivery(Decimal("-5"))
        assert supplier.on_time_delivery_rate == Decimal("-5")
        assert supplier.version == 2
