# test_supplier_entity.py
# Comprehensive tests for supplier_entity.py

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from domain.customer_supplier_employee.supplier_entity import (
    SupplierEntity,
    SupplierEntityRepository,
    SupplierStatus,
    SupplierType,
)
from domain.customer_supplier_employee.supplier_withholding_category_vo import (
    SupplierWithholdingCategoryVO,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def withholding_category():
    """Create a valid withholding category VO."""
    # We'll create a real object if available, otherwise a dummy
    try:
        # Try to import real VO
        from domain.customer_supplier_employee.supplier_withholding_category_vo import (
            SupplierWithholdingCategoryVO,
        )
        # Return a simple instance; assuming there's a create method
        # If not, we'll fallback to dummy
        return SupplierWithholdingCategoryVO.create_pph23(rate=Decimal("2.0"))
    except (ImportError, AttributeError):
        # Dummy object with required attributes
        dummy = SimpleNamespace()
        dummy.should_withhold = True
        dummy.article = "PPh 23"
        dummy.rate = Decimal("2.0")
        dummy.is_final = False
        dummy.effective_date = date(2024, 1, 1)
        dummy.notes = ""
        dummy.to_dict = lambda: {"article": "PPh 23", "rate": "2.0"}
        return dummy


@pytest.fixture
def valid_supplier(withholding_category):
    """A valid active supplier."""
    return SupplierEntity.create(
        legal_entity_id=uuid4(),
        supplier_code="SUP-001",
        supplier_name="PT Maju Jaya",
        supplier_type=SupplierType.LOCAL,
        created_by="system",
        supplier_id=uuid4(),
        tax_id="123456789012345",
        email="info@majujaya.co.id",
        phone="02112345678",
        fax="02112345679",
        contact_person="Budi Santoso",
        address="Jl. Sudirman No. 10",
        address2="Gedung A Lantai 5",
        city="Jakarta",
        province="DKI Jakarta",
        postal_code="10110",
        country="Indonesia",
        bank_name="BCA",
        bank_account_number="1234567890",
        bank_account_name="PT Maju Jaya",
        withholding_category=withholding_category,
        payment_terms_days=30,
        notes="Supplier utama",
    )


@pytest.fixture
def inactive_supplier(valid_supplier):
    """An inactive supplier."""
    return valid_supplier.deactivate(deactivated_by="admin")


@pytest.fixture
def blocked_supplier(valid_supplier):
    """A blocked supplier."""
    return valid_supplier.block(blocked_by="admin", reason="Pending compliance")


@pytest.fixture
def suspended_supplier(valid_supplier):
    """A suspended supplier."""
    return valid_supplier.suspend(suspended_by="admin", reason="Under review")


@pytest.fixture
def blacklisted_supplier(valid_supplier):
    """A blacklisted supplier."""
    return valid_supplier.blacklist(blacklisted_by="admin", reason="Fraud")


@pytest.fixture
def supplier_with_balance(valid_supplier):
    """Supplier with outstanding balance."""
    return valid_supplier.record_purchase(Decimal("10000000"), purchase_date=date(2024, 1, 15))


# ============================================================================
# Tests for Enums
# ============================================================================

class TestSupplierStatus:
    def test_display_name(self):
        assert SupplierStatus.ACTIVE.display_name() == "Aktif"
        assert SupplierStatus.INACTIVE.display_name() == "Tidak Aktif"
        assert SupplierStatus.BLOCKED.display_name() == "Diblokir"
        assert SupplierStatus.SUSPENDED.display_name() == "Ditangguhkan"
        assert SupplierStatus.BLACKLISTED.display_name() == "Blacklist"
        assert SupplierStatus.DRAFT.display_name() == "Draft"

    def test_can_transact(self):
        assert SupplierStatus.ACTIVE.can_transact() is True
        assert SupplierStatus.INACTIVE.can_transact() is False
        assert SupplierStatus.BLOCKED.can_transact() is False
        assert SupplierStatus.SUSPENDED.can_transact() is False
        assert SupplierStatus.BLACKLISTED.can_transact() is False
        assert SupplierStatus.DRAFT.can_transact() is False

    def test_can_receive_payment(self):
        assert SupplierStatus.ACTIVE.can_receive_payment() is True
        assert SupplierStatus.INACTIVE.can_receive_payment() is False
        assert SupplierStatus.BLOCKED.can_receive_payment() is True
        assert SupplierStatus.SUSPENDED.can_receive_payment() is True
        assert SupplierStatus.BLACKLISTED.can_receive_payment() is False
        assert SupplierStatus.DRAFT.can_receive_payment() is False

    def test_can_modify(self):
        assert SupplierStatus.ACTIVE.can_modify() is True
        assert SupplierStatus.INACTIVE.can_modify() is True
        assert SupplierStatus.BLOCKED.can_modify() is True
        assert SupplierStatus.SUSPENDED.can_modify() is True
        assert SupplierStatus.BLACKLISTED.can_modify() is False
        assert SupplierStatus.DRAFT.can_modify() is True

    def test_from_string(self):
        assert SupplierStatus.from_string("active") == SupplierStatus.ACTIVE
        assert SupplierStatus.from_string("inactive") == SupplierStatus.INACTIVE
        assert SupplierStatus.from_string("blocked") == SupplierStatus.BLOCKED
        assert SupplierStatus.from_string("suspended") == SupplierStatus.SUSPENDED
        assert SupplierStatus.from_string("blacklisted") == SupplierStatus.BLACKLISTED
        assert SupplierStatus.from_string("draft") == SupplierStatus.DRAFT
        assert SupplierStatus.from_string("invalid") is None


class TestSupplierType:
    def test_display_name(self):
        assert SupplierType.LOCAL.display_name() == "Lokal"
        assert SupplierType.FOREIGN.display_name() == "Luar Negeri"
        assert SupplierType.GOVERNMENT.display_name() == "Instansi Pemerintah"
        assert SupplierType.INDIVIDUAL.display_name() == "Perorangan"
        assert SupplierType.MANUFACTURER.display_name() == "Pabrikan"
        assert SupplierType.DISTRIBUTOR.display_name() == "Distributor"
        assert SupplierType.SERVICE_PROVIDER.display_name() == "Penyedia Jasa"

    def test_requires_withholding(self):
        assert SupplierType.LOCAL.requires_withholding() is True
        assert SupplierType.INDIVIDUAL.requires_withholding() is True
        assert SupplierType.MANUFACTURER.requires_withholding() is True
        assert SupplierType.DISTRIBUTOR.requires_withholding() is True
        assert SupplierType.SERVICE_PROVIDER.requires_withholding() is True
        assert SupplierType.GOVERNMENT.requires_withholding() is False
        assert SupplierType.FOREIGN.requires_withholding() is False

    def test_from_string(self):
        assert SupplierType.from_string("local") == SupplierType.LOCAL
        assert SupplierType.from_string("foreign") == SupplierType.FOREIGN
        assert SupplierType.from_string("government") == SupplierType.GOVERNMENT
        assert SupplierType.from_string("individual") == SupplierType.INDIVIDUAL
        assert SupplierType.from_string("manufacturer") == SupplierType.MANUFACTURER
        assert SupplierType.from_string("distributor") == SupplierType.DISTRIBUTOR
        assert SupplierType.from_string("service_provider") == SupplierType.SERVICE_PROVIDER
        assert SupplierType.from_string("invalid") is None


# ============================================================================
# Tests for SupplierEntity - Construction and Validation
# ============================================================================

class TestSupplierEntityConstruction:
    def test_create_supplier_success(self, withholding_category):
        emp = SupplierEntity.create(
            legal_entity_id=uuid4(),
            supplier_code="SUP-002",
            supplier_name="CV Berkah Abadi",
            supplier_type=SupplierType.DISTRIBUTOR,
            created_by="admin",
            tax_id="987654321098765",
            email="berkah@example.com",
            phone="02212345678",
            contact_person="Siti Rahayu",
            address="Jl. Asia Afrika No. 5",
            city="Bandung",
            province="Jawa Barat",
            postal_code="40261",
            withholding_category=withholding_category,
            payment_terms_days=15,
        )
        assert isinstance(emp.supplier_id, UUID)
        assert emp.supplier_code == "SUP-002"
        assert emp.supplier_name == "CV Berkah Abadi"
        assert emp.status == SupplierStatus.ACTIVE
        assert emp.version == 1

    def test_create_supplier_with_defaults(self):
        emp = SupplierEntity.create(
            legal_entity_id=uuid4(),
            supplier_code="SUP-003",
            supplier_name="PT ABC",
            supplier_type=SupplierType.LOCAL,
        )
        assert emp.withholding_category is not None
        assert emp.payment_terms_days == 30
        assert emp.outstanding_balance == Decimal("0")
        assert emp.total_purchases == Decimal("0")

    def test_validation_supplier_code_empty(self):
        with pytest.raises(ValueError, match="Supplier code must be a non-empty string"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="",
                supplier_name="Test",
                supplier_type=SupplierType.LOCAL,
            )

    def test_validation_supplier_code_too_long(self):
        with pytest.raises(ValueError, match="Supplier code must not exceed 30 characters"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="A" * 31,
                supplier_name="Test",
                supplier_type=SupplierType.LOCAL,
            )

    def test_validation_supplier_code_invalid_chars(self):
        with pytest.raises(ValueError, match="Supplier code can only contain letters"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="SUP 001",  # contains space
                supplier_name="Test",
                supplier_type=SupplierType.LOCAL,
            )

    def test_validation_supplier_name_empty(self):
        with pytest.raises(ValueError, match="Supplier name must be a non-empty string"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="SUP-001",
                supplier_name="",
                supplier_type=SupplierType.LOCAL,
            )

    def test_validation_supplier_name_too_long(self):
        with pytest.raises(ValueError, match="Supplier name must not exceed 200 characters"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="SUP-001",
                supplier_name="A" * 201,
                supplier_type=SupplierType.LOCAL,
            )

    def test_validation_invalid_supplier_type(self):
        with pytest.raises(ValueError, match="Invalid supplier_type"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="SUP-001",
                supplier_name="Test",
                supplier_type="invalid",  # type: ignore
            )

    def test_validation_invalid_status(self):
        with pytest.raises(ValueError, match="Invalid status"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="SUP-001",
                supplier_name="Test",
                supplier_type=SupplierType.LOCAL,
                status="invalid",  # type: ignore
            )

    def test_validation_tax_id_invalid_format(self):
        with pytest.raises(ValueError, match="Tax ID must be 15 digits"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="SUP-001",
                supplier_name="Test",
                supplier_type=SupplierType.LOCAL,
                tax_id="123",
            )

    def test_validation_email_invalid(self):
        with pytest.raises(ValueError, match="Invalid email format"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="SUP-001",
                supplier_name="Test",
                supplier_type=SupplierType.LOCAL,
                email="invalid",
            )

    def test_validation_phone_invalid_chars(self):
        with pytest.raises(ValueError, match="Phone number must contain only digits"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="SUP-001",
                supplier_name="Test",
                supplier_type=SupplierType.LOCAL,
                phone="021-1234",
            )

    def test_validation_phone_too_short(self):
        with pytest.raises(ValueError, match="Phone number must be 8-15 digits"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="SUP-001",
                supplier_name="Test",
                supplier_type=SupplierType.LOCAL,
                phone="123",
            )

    def test_validation_fax_too_short(self):
        with pytest.raises(ValueError, match="Phone number must be 8-15 digits"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="SUP-001",
                supplier_name="Test",
                supplier_type=SupplierType.LOCAL,
                fax="123",
            )

    def test_validation_postal_code_invalid(self):
        with pytest.raises(ValueError, match="Postal code must contain only digits"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="SUP-001",
                supplier_name="Test",
                supplier_type=SupplierType.LOCAL,
                postal_code="A1234",
            )

    def test_validation_postal_code_length(self):
        with pytest.raises(ValueError, match="Postal code must be 5 digits"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="SUP-001",
                supplier_name="Test",
                supplier_type=SupplierType.LOCAL,
                postal_code="123456",
            )

    def test_validation_payment_terms_negative(self):
        with pytest.raises(ValueError, match="Payment terms days cannot be negative"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="SUP-001",
                supplier_name="Test",
                supplier_type=SupplierType.LOCAL,
                payment_terms_days=-1,
            )

    def test_validation_payment_terms_too_high(self):
        with pytest.raises(ValueError, match="Payment terms days exceed maximum"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="SUP-001",
                supplier_name="Test",
                supplier_type=SupplierType.LOCAL,
                payment_terms_days=365,
            )

    def test_validation_negative_outstanding_balance(self):
        with pytest.raises(ValueError, match="Outstanding balance cannot be negative"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="SUP-001",
                supplier_name="Test",
                supplier_type=SupplierType.LOCAL,
                outstanding_balance=Decimal("-100"),
            )

    def test_validation_negative_total_purchases(self):
        with pytest.raises(ValueError, match="Total purchases cannot be negative"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="SUP-001",
                supplier_name="Test",
                supplier_type=SupplierType.LOCAL,
                total_purchases=Decimal("-100"),
            )

    def test_validation_version_less_than_one(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            SupplierEntity(
                supplier_id=uuid4(),
                legal_entity_id=uuid4(),
                supplier_code="SUP-001",
                supplier_name="Test",
                supplier_type=SupplierType.LOCAL,
                version=0,
            )


# ============================================================================
# Tests for from_dict factory
# ============================================================================

class TestSupplierEntityFromDict:
    def test_from_dict_success(self, valid_supplier):
        data = valid_supplier.to_dict()
        emp = SupplierEntity.from_dict(data)
        assert emp.supplier_id == valid_supplier.supplier_id
        assert emp.supplier_code == valid_supplier.supplier_code
        assert emp.supplier_name == valid_supplier.supplier_name
        assert emp.tax_id == valid_supplier.tax_id
        assert emp.email == valid_supplier.email
        assert emp.phone == valid_supplier.phone
        assert emp.status == valid_supplier.status

    def test_from_dict_with_invalid_supplier_type(self):
        data = {
            "supplier_id": str(uuid4()),
            "legal_entity_id": str(uuid4()),
            "supplier_code": "SUP-001",
            "supplier_name": "Test",
            "supplier_type": "invalid",
        }
        with pytest.raises(ValueError, match="Invalid supplier_type"):
            SupplierEntity.from_dict(data)

    def test_from_dict_with_missing_status_defaults_active(self):
        data = {
            "supplier_id": str(uuid4()),
            "legal_entity_id": str(uuid4()),
            "supplier_code": "SUP-001",
            "supplier_name": "Test",
            "supplier_type": "local",
        }
        emp = SupplierEntity.from_dict(data)
        assert emp.status == SupplierStatus.ACTIVE

    def test_from_dict_with_dict_withholding_category(self):
        data = {
            "supplier_id": str(uuid4()),
            "legal_entity_id": str(uuid4()),
            "supplier_code": "SUP-001",
            "supplier_name": "Test",
            "supplier_type": "local",
            "withholding_category": {"article": "PPh 23", "rate": "2.0"},
        }
        emp = SupplierEntity.from_dict(data)
        assert emp.withholding_category is not None


# ============================================================================
# Tests for Properties
# ============================================================================

class TestSupplierEntityProperties:
    def test_is_active(self, valid_supplier, inactive_supplier):
        assert valid_supplier.is_active is True
        assert inactive_supplier.is_active is False

    def test_can_transact(self, valid_supplier, inactive_supplier, blocked_supplier, suspended_supplier):
        assert valid_supplier.can_transact is True
        assert inactive_supplier.can_transact is False
        assert blocked_supplier.can_transact is False
        assert suspended_supplier.can_transact is False

    def test_can_receive_payment(self, valid_supplier, inactive_supplier, blocked_supplier, blacklisted_supplier):
        assert valid_supplier.can_receive_payment is True
        assert inactive_supplier.can_receive_payment is False
        assert blocked_supplier.can_receive_payment is True
        assert blacklisted_supplier.can_receive_payment is False

    def test_full_address(self, valid_supplier):
        expected = "Jl. Sudirman No. 10, Gedung A Lantai 5, Jakarta, DKI Jakarta, 10110, Indonesia"
        assert valid_supplier.full_address == expected

    def test_full_address_with_missing_parts(self):
        sup = SupplierEntity(
            supplier_id=uuid4(),
            legal_entity_id=uuid4(),
            supplier_code="SUP-001",
            supplier_name="Test",
            supplier_type=SupplierType.LOCAL,
            address="Jl. Merdeka",
            city="Jakarta",
        )
        assert sup.full_address == "Jl. Merdeka, Jakarta"

    def test_should_withhold_tax(self, valid_supplier):
        assert valid_supplier.should_withhold_tax is True


# ============================================================================
# Tests for Business Logic Methods
# ============================================================================

class TestSupplierEntityBusiness:
    def test_update_balance_positive(self, valid_supplier):
        updated = valid_supplier.update_balance(Decimal("5000000"), transaction_date=date(2024, 2, 1))
        assert updated.outstanding_balance == Decimal("5000000")
        assert updated.total_purchases == Decimal("5000000")
        assert updated.last_purchase_date == date(2024, 2, 1)
        assert updated.last_payment_date is None
        assert updated.version == valid_supplier.version + 1

    def test_update_balance_negative(self, valid_supplier):
        # First add balance
        sup = valid_supplier.update_balance(Decimal("5000000"))
        # Then pay
        updated = sup.update_balance(Decimal("-3000000"), transaction_date=date(2024, 2, 15))
        assert updated.outstanding_balance == Decimal("2000000")
        assert updated.total_purchases == Decimal("5000000")  # unchanged
        assert updated.last_payment_date == date(2024, 2, 15)

    def test_update_balance_clamp_to_zero(self, valid_supplier):
        # Overpay, should clamp to 0
        sup = valid_supplier.update_balance(Decimal("1000000"))
        updated = sup.update_balance(Decimal("-2000000"))
        assert updated.outstanding_balance == Decimal("0")

    def test_record_purchase(self, valid_supplier):
        updated = valid_supplier.record_purchase(Decimal("7500000"), purchase_date=date(2024, 3, 1))
        assert updated.outstanding_balance == Decimal("7500000")
        assert updated.total_purchases == Decimal("7500000")
        assert updated.last_purchase_date == date(2024, 3, 1)

    def test_record_purchase_invalid_amount(self, valid_supplier):
        with pytest.raises(ValueError, match="Purchase amount must be positive"):
            valid_supplier.record_purchase(Decimal("-1000"))

    def test_record_payment(self, valid_supplier):
        sup = valid_supplier.record_purchase(Decimal("10000000"))
        updated = sup.record_payment(Decimal("6000000"), payment_date=date(2024, 4, 1))
        assert updated.outstanding_balance == Decimal("4000000")
        assert updated.last_payment_date == date(2024, 4, 1)

    def test_record_payment_invalid_amount(self, valid_supplier):
        with pytest.raises(ValueError, match="Payment amount must be positive"):
            valid_supplier.record_payment(Decimal("0"))

    def test_update_payment_terms(self, valid_supplier):
        updated = valid_supplier.update_payment_terms(45, updated_by="finance")
        assert updated.payment_terms_days == 45
        assert updated.version == valid_supplier.version + 1
        assert updated.updated_by == "finance"

    def test_update_payment_terms_invalid(self, valid_supplier):
        with pytest.raises(ValueError, match="Payment terms days cannot be negative"):
            valid_supplier.update_payment_terms(-10, "admin")

    def test_update_withholding_category(self, valid_supplier, withholding_category):
        updated = valid_supplier.update_withholding_category(withholding_category, updated_by="tax")
        assert updated.withholding_category == withholding_category
        assert updated.version == valid_supplier.version + 1
        assert "Withholding category updated by tax" in updated.notes


# ============================================================================
# Tests for Status Change Methods
# ============================================================================

class TestSupplierEntityStatusChanges:
    def test_activate_from_inactive(self, inactive_supplier):
        updated = inactive_supplier.activate(activated_by="admin")
        assert updated.status == SupplierStatus.ACTIVE
        assert updated.version == inactive_supplier.version + 1
        assert updated.updated_by == "admin"

    def test_activate_already_active(self, valid_supplier):
        updated = valid_supplier.activate("admin")
        assert updated == valid_supplier  # no change

    def test_activate_blacklisted_raises(self, blacklisted_supplier):
        with pytest.raises(ValueError, match="Cannot activate a blacklisted supplier"):
            blacklisted_supplier.activate("admin")

    def test_deactivate(self, valid_supplier):
        updated = valid_supplier.deactivate("admin")
        assert updated.status == SupplierStatus.INACTIVE
        assert updated.version == valid_supplier.version + 1

    def test_deactivate_already_inactive(self, inactive_supplier):
        updated = inactive_supplier.deactivate("admin")
        assert updated == inactive_supplier  # no change

    def test_block(self, valid_supplier):
        updated = valid_supplier.block(blocked_by="admin", reason="Compliance")
        assert updated.status == SupplierStatus.BLOCKED
        assert "Blocked: Compliance by admin" in updated.notes

    def test_block_blacklisted_raises(self, blacklisted_supplier):
        with pytest.raises(ValueError, match="Cannot block a blacklisted supplier"):
            blacklisted_supplier.block("admin", "test")

    def test_block_already_blocked(self, blocked_supplier):
        updated = blocked_supplier.block("admin", "again")
        assert updated == blocked_supplier  # no change

    def test_unblock(self, blocked_supplier):
        updated = blocked_supplier.unblock(unblocked_by="admin")
        assert updated.status == SupplierStatus.ACTIVE
        assert updated.version == blocked_supplier.version + 1

    def test_unblock_not_blocked(self, valid_supplier):
        with pytest.raises(ValueError, match="Supplier is not blocked"):
            valid_supplier.unblock("admin")

    def test_suspend(self, valid_supplier):
        updated = valid_supplier.suspend(suspended_by="admin", reason="Review")
        assert updated.status == SupplierStatus.SUSPENDED
        assert "Suspended: Review by admin" in updated.notes

    def test_suspend_already_suspended(self, suspended_supplier):
        updated = suspended_supplier.suspend("admin", "again")
        assert updated == suspended_supplier  # no change

    def test_blacklist(self, valid_supplier):
        updated = valid_supplier.blacklist(blacklisted_by="admin", reason="Fraud")
        assert updated.status == SupplierStatus.BLACKLISTED
        assert "BLACKLISTED: Fraud by admin" in updated.notes

    def test_blacklist_already_blacklisted(self, blacklisted_supplier):
        updated = blacklisted_supplier.blacklist("admin", "again")
        assert updated == blacklisted_supplier  # no change


# ============================================================================
# Tests for validate_can_modify
# ============================================================================

class TestSupplierEntityValidate:
    def test_validate_can_modify_blacklisted(self, blacklisted_supplier):
        can, msg = blacklisted_supplier.validate_can_modify()
        assert can is False
        assert msg == "Cannot modify blacklisted supplier"

    def test_validate_can_modify_active(self, valid_supplier):
        can, msg = valid_supplier.validate_can_modify()
        assert can is True
        assert msg == ""


# ============================================================================
# Tests for Serialization
# ============================================================================

class TestSupplierEntitySerialization:
    def test_to_dict(self, valid_supplier):
        d = valid_supplier.to_dict()
        assert d["supplier_id"] == str(valid_supplier.supplier_id)
        assert d["supplier_code"] == valid_supplier.supplier_code
        assert d["supplier_name"] == valid_supplier.supplier_name
        assert d["tax_id"] == valid_supplier.tax_id
        assert d["email"] == valid_supplier.email
        assert d["phone"] == valid_supplier.phone
        assert d["status"] == valid_supplier.status.value
        assert d["version"] == valid_supplier.version
        assert d["outstanding_balance"] == str(valid_supplier.outstanding_balance)
        assert "withholding_category" in d

    def test_to_dict_without_withholding(self, valid_supplier):
        d = valid_supplier.to_dict(include_withholding_details=False)
        assert "withholding_category" not in d

    def test_to_db_record(self, valid_supplier):
        rec = valid_supplier.to_db_record()
        assert rec["supplier_id"] == valid_supplier.supplier_id
        assert rec["supplier_code"] == valid_supplier.supplier_code
        assert rec["tax_id"] == valid_supplier.tax_id
        assert rec["payment_terms_days"] == valid_supplier.payment_terms_days
        assert rec["outstanding_balance"] == valid_supplier.outstanding_balance
        assert rec["withholding_article"] is not None


# ============================================================================
# Tests for Dunder Methods
# ============================================================================

class TestSupplierEntityDunder:
    def test_str(self, valid_supplier):
        assert str(valid_supplier) == "SUP-001 - PT Maju Jaya"

    def test_repr(self, valid_supplier):
        assert repr(valid_supplier) == "SupplierEntity(SUP-001, status=active)"

    def test_equality(self, valid_supplier):
        same = SupplierEntity(
            supplier_id=valid_supplier.supplier_id,
            legal_entity_id=valid_supplier.legal_entity_id,
            supplier_code="different",
            supplier_name="Different",
            supplier_type=SupplierType.LOCAL,
        )
        assert valid_supplier == same  # equality by supplier_id

        different = SupplierEntity(
            supplier_id=uuid4(),
            legal_entity_id=uuid4(),
            supplier_code="SUP-002",
            supplier_name="Other",
            supplier_type=SupplierType.FOREIGN,
        )
        assert valid_supplier != different

    def test_hash(self, valid_supplier):
        assert hash(valid_supplier) == hash(valid_supplier.supplier_id)


# ============================================================================
# Tests for Repository Protocol
# ============================================================================

class TestSupplierEntityRepository:
    def test_repository_abstract_methods_raise_not_implemented(self):
        repo = SupplierEntityRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_code("SUP-001", uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_tax_id("123456789012345", uuid4())
        with pytest.raises(NotImplementedError):
            repo.list_by_status(SupplierStatus.ACTIVE, uuid4())
        with pytest.raises(NotImplementedError):
            repo.list_by_type(SupplierType.LOCAL, uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())