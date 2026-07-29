# test_customer_entity.py
# Comprehensive tests for customer_entity.py

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.customer_supplier_employee.customer_credit_limit_vo import (
    CustomerCreditLimitVO,
)
from domain.customer_supplier_employee.customer_entity import (
    CustomerEntity,
    CustomerEntityRepository,
    CustomerSegment,
    CustomerStatus,
    CustomerType,
    PaymentTerm,
)
from domain.customer_supplier_employee.customer_tax_status_vo import (
    CustomerTaxStatusVO,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_class_vars():
    """Reset class variables before each test to avoid cross-test contamination."""
    CustomerEntity._audit_trail = []
    CustomerEntity._snapshots = []
    CustomerEntityRepository._storage = {}
    yield
    CustomerEntity._audit_trail = []
    CustomerEntity._snapshots = []
    CustomerEntityRepository._storage = {}


@pytest.fixture
def credit_limit_vo():
    return CustomerCreditLimitVO(
        limit_amount=Decimal("100000000"),
        currency="IDR",
        effective_date=date(2024, 1, 1),
    )


@pytest.fixture
def tax_status_vo():
    return CustomerTaxStatusVO(
        tax_id="123456789012345",
        article="PPh 23",
        rate=Decimal("2.0"),
        is_final=False,
        effective_date=date(2024, 1, 1),
    )


@pytest.fixture
def valid_customer(credit_limit_vo, tax_status_vo):
    return CustomerEntity(
        customer_id=uuid4(),
        legal_entity_id=uuid4(),
        customer_code="CUST-001",
        customer_name="PT Maju Jaya",
        customer_type=CustomerType.COMPANY,
        segment=CustomerSegment.CORPORATE,
        status=CustomerStatus.ACTIVE,
        payment_term=PaymentTerm.NET_30,
        tax_id="123456789012345",
        tax_status=tax_status_vo,
        email="info@majujaya.co.id",
        phone="02112345678",
        mobile="08123456789",
        fax="02112345679",
        contact_person="Budi Santoso",
        address="Jl. Sudirman No. 10",
        address2="Gedung A Lantai 5",
        city="Jakarta",
        province="DKI Jakarta",
        postal_code="10110",
        country="Indonesia",
        website="https://majujaya.co.id",
        credit_limit=credit_limit_vo,
        outstanding_balance=Decimal("0"),
        total_purchases=Decimal("0"),
        last_purchase_date=None,
        last_payment_date=None,
        credit_hold=False,
        risk_score=0,
        notes="Test customer",
    )


@pytest.fixture
def inactive_customer(valid_customer):
    return valid_customer.deactivate(deactivated_by="admin")


@pytest.fixture
def blocked_customer(valid_customer):
    return valid_customer.block(blocked_by="admin", reason="Suspicious activity")


@pytest.fixture
def blacklisted_customer(valid_customer):
    return valid_customer.blacklist(blacklisted_by="admin", reason="Fraud")


@pytest.fixture
def customer_with_balance(valid_customer):
    return valid_customer.record_purchase(Decimal("5000000"), purchase_date=date(2024, 1, 15))


# ============================================================================
# Tests for Enums
# ============================================================================

class TestCustomerStatus:
    def test_display_name(self):
        assert CustomerStatus.ACTIVE.display_name() == "Aktif"
        assert CustomerStatus.INACTIVE.display_name() == "Tidak Aktif"
        assert CustomerStatus.BLOCKED.display_name() == "Diblokir"
        assert CustomerStatus.BLACKLISTED.display_name() == "Blacklist"
        assert CustomerStatus.DRAFT.display_name() == "Draft"
        assert CustomerStatus.SUSPENDED.display_name() == "Ditangguhkan"

    def test_can_transact(self):
        assert CustomerStatus.ACTIVE.can_transact() is True
        assert CustomerStatus.INACTIVE.can_transact() is False
        assert CustomerStatus.BLOCKED.can_transact() is False
        assert CustomerStatus.BLACKLISTED.can_transact() is False
        assert CustomerStatus.DRAFT.can_transact() is False
        assert CustomerStatus.SUSPENDED.can_transact() is False

    def test_can_receive_payment(self):
        assert CustomerStatus.ACTIVE.can_receive_payment() is True
        assert CustomerStatus.INACTIVE.can_receive_payment() is False
        assert CustomerStatus.BLOCKED.can_receive_payment() is True
        assert CustomerStatus.BLACKLISTED.can_receive_payment() is False
        assert CustomerStatus.DRAFT.can_receive_payment() is False
        assert CustomerStatus.SUSPENDED.can_receive_payment() is True


class TestCustomerType:
    def test_display_name(self):
        assert CustomerType.INDIVIDUAL.display_name() == "Perorangan"
        assert CustomerType.COMPANY.display_name() == "Perusahaan"
        assert CustomerType.GOVERNMENT.display_name() == "Instansi Pemerintah"
        assert CustomerType.NON_PROFIT.display_name() == "Non-profit"
        assert CustomerType.FOREIGN.display_name() == "Luar Negeri"


class TestCustomerSegment:
    def test_display_name(self):
        assert CustomerSegment.RETAIL.display_name() == "Ritel"
        assert CustomerSegment.WHOLESALE.display_name() == "Grosir"
        assert CustomerSegment.CORPORATE.display_name() == "Korporasi"
        assert CustomerSegment.GOVERNMENT.display_name() == "Pemerintah"
        assert CustomerSegment.PREMIUM.display_name() == "Premium"
        assert CustomerSegment.REGULAR.display_name() == "Reguler"


class TestPaymentTerm:
    def test_display_name(self):
        assert PaymentTerm.CASH.display_name() == "Cash"
        assert PaymentTerm.NET_30.display_name() == "30 Hari"


# ============================================================================
# Tests for CustomerEntity - Construction and Validation
# ============================================================================

class TestCustomerEntityConstruction:
    def test_create_valid_customer(self, valid_customer):
        assert isinstance(valid_customer.customer_id, uuid4().__class__)
        assert valid_customer.customer_code == "CUST-001"
        assert valid_customer.customer_name == "PT Maju Jaya"
        assert valid_customer.status == CustomerStatus.ACTIVE
        assert valid_customer.version == 1
        assert len(CustomerEntity._snapshots) == 1

    def test_validation_customer_code_too_short(self):
        with pytest.raises(ValueError, match="Customer code must be at least 2 characters"):
            CustomerEntity(
                customer_id=uuid4(),
                legal_entity_id=uuid4(),
                customer_code="A",
                customer_name="Test",
                customer_type=CustomerType.COMPANY,
            )

    def test_validation_customer_name_too_short(self):
        with pytest.raises(ValueError, match="Customer name must be at least 2 characters"):
            CustomerEntity(
                customer_id=uuid4(),
                legal_entity_id=uuid4(),
                customer_code="CUST-001",
                customer_name="A",
                customer_type=CustomerType.COMPANY,
            )

    def test_validation_negative_outstanding_balance(self):
        with pytest.raises(ValueError, match="Outstanding balance cannot be negative"):
            CustomerEntity(
                customer_id=uuid4(),
                legal_entity_id=uuid4(),
                customer_code="CUST-001",
                customer_name="Test",
                customer_type=CustomerType.COMPANY,
                outstanding_balance=Decimal("-100"),
            )

    def test_validation_negative_total_purchases(self):
        with pytest.raises(ValueError, match="Total purchases cannot be negative"):
            CustomerEntity(
                customer_id=uuid4(),
                legal_entity_id=uuid4(),
                customer_code="CUST-001",
                customer_name="Test",
                customer_type=CustomerType.COMPANY,
                total_purchases=Decimal("-100"),
            )

    def test_validation_risk_score_out_of_range(self):
        with pytest.raises(ValueError, match="Risk score must be 0-100"):
            CustomerEntity(
                customer_id=uuid4(),
                legal_entity_id=uuid4(),
                customer_code="CUST-001",
                customer_name="Test",
                customer_type=CustomerType.COMPANY,
                risk_score=150,
            )

    def test_validation_tax_id_wrong_length(self):
        with pytest.raises(ValueError, match="Tax ID must be 15 digits"):
            CustomerEntity(
                customer_id=uuid4(),
                legal_entity_id=uuid4(),
                customer_code="CUST-001",
                customer_name="Test",
                customer_type=CustomerType.COMPANY,
                tax_id="123",
            )

    def test_validation_invalid_email(self):
        with pytest.raises(ValueError, match="Invalid email"):
            CustomerEntity(
                customer_id=uuid4(),
                legal_entity_id=uuid4(),
                customer_code="CUST-001",
                customer_name="Test",
                customer_type=CustomerType.COMPANY,
                email="invalid",
            )

    def test_validation_postal_code_non_digit(self):
        with pytest.raises(ValueError, match="Postal code must be digits"):
            CustomerEntity(
                customer_id=uuid4(),
                legal_entity_id=uuid4(),
                customer_code="CUST-001",
                customer_name="Test",
                customer_type=CustomerType.COMPANY,
                postal_code="A1234",
            )


# ============================================================================
# Tests for Entity Basic Methods
# ============================================================================

class TestCustomerEntityBasicMethods:
    def test_create(self, valid_customer):
        customer = valid_customer.create(created_by="admin")
        assert customer == valid_customer
        assert len(CustomerEntity._audit_trail) == 1
        entry = CustomerEntity._audit_trail[0]
        assert entry["action"] == "CREATE"
        assert entry["performed_by"] == "admin"

    def test_update(self, valid_customer):
        updated = valid_customer.update(
            updated_by="admin",
            customer_name="PT Maju Jaya Baru",
            email="new@majujaya.co.id"
        )
        assert updated.customer_name == "PT Maju Jaya Baru"
        assert updated.email == "new@majujaya.co.id"
        assert updated.version == valid_customer.version + 1
        assert updated.updated_by == "admin"
        assert len(CustomerEntity._audit_trail) == 1
        assert CustomerEntity._audit_trail[0]["action"] == "UPDATE"

    def test_update_blacklisted_fails(self, blacklisted_customer):
        with pytest.raises(ValueError, match="Cannot update customer in status blacklisted"):
            blacklisted_customer.update(updated_by="admin", customer_name="New Name")

    def test_delete_active(self, valid_customer):
        deleted = valid_customer.delete(deleted_by="admin", reason="No longer needed")
        assert deleted.status == CustomerStatus.INACTIVE
        assert deleted.version == valid_customer.version + 1

    def test_delete_blacklisted_fails(self, blacklisted_customer):
        with pytest.raises(ValueError, match="Cannot delete blacklisted customer"):
            blacklisted_customer.delete(deleted_by="admin")

    def test_restore(self, inactive_customer):
        restored = inactive_customer.restore(restored_by="admin")
        assert restored.status == CustomerStatus.ACTIVE
        assert restored.version == inactive_customer.version + 1

    def test_restore_active_fails(self, valid_customer):
        with pytest.raises(ValueError, match="Cannot restore customer in status active"):
            valid_customer.restore("admin")

    def test_activate_inactive(self, inactive_customer):
        activated = inactive_customer.activate(activated_by="admin")
        assert activated.status == CustomerStatus.ACTIVE
        assert activated.version == inactive_customer.version + 1

    def test_activate_already_active(self, valid_customer):
        result = valid_customer.activate("admin")
        assert result == valid_customer

    def test_activate_blacklisted_fails(self, blacklisted_customer):
        with pytest.raises(ValueError, match="Cannot activate blacklisted customer"):
            blacklisted_customer.activate("admin")

    def test_deactivate_active(self, valid_customer):
        deactivated = valid_customer.deactivate("admin")
        assert deactivated.status == CustomerStatus.INACTIVE
        assert deactivated.version == valid_customer.version + 1

    def test_deactivate_already_inactive(self, inactive_customer):
        result = inactive_customer.deactivate("admin")
        assert result == inactive_customer

    def test_lock(self, valid_customer):
        locked = valid_customer.lock(locked_by="admin", reason="Suspicious")
        assert locked.status == CustomerStatus.BLOCKED
        assert locked.version == valid_customer.version + 1
        assert CustomerEntity._audit_trail[0]["details"]["reason"] == "Suspicious"

    def test_lock_non_active_fails(self, inactive_customer):
        with pytest.raises(ValueError, match="Cannot lock customer in status inactive"):
            inactive_customer.lock("admin", "reason")

    def test_unlock(self, blocked_customer):
        unlocked = blocked_customer.unlock(unlocked_by="admin")
        assert unlocked.status == CustomerStatus.ACTIVE
        assert unlocked.version == blocked_customer.version + 1

    def test_unlock_non_blocked_fails(self, valid_customer):
        with pytest.raises(ValueError, match="Cannot unlock customer in status active"):
            valid_customer.unlock("admin")

    def test_validate(self, valid_customer):
        result = valid_customer.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid(self):
        customer = CustomerEntity(
            customer_id=uuid4(),
            legal_entity_id=uuid4(),
            customer_code="A",
            customer_name="A",
            customer_type=CustomerType.COMPANY,
            outstanding_balance=Decimal("-100"),
        )
        result = customer.validate()
        assert result["is_valid"] is False
        assert len(result["errors"]) > 0

    def test_to_dict(self, valid_customer):
        d = valid_customer.to_dict()
        assert d["customer_id"] == str(valid_customer.customer_id)
        assert d["customer_code"] == "CUST-001"
        assert d["status"] == "active"
        assert "tax_status" in d
        assert "credit_limit" in d

    def test_to_dict_without_tax(self, valid_customer):
        d = valid_customer.to_dict(include_tax_status=False)
        assert "tax_status" not in d

    def test_from_dict(self, valid_customer):
        data = valid_customer.to_dict()
        restored = CustomerEntity.from_dict(data)
        assert restored.customer_id == valid_customer.customer_id
        assert restored.credit_limit == valid_customer.credit_limit
        assert restored.tax_status == valid_customer.tax_status

    def test_clone(self, valid_customer):
        cloned = valid_customer.clone()
        assert cloned.customer_id != valid_customer.customer_id
        assert cloned.customer_code == "CUST-001_COPY"
        assert cloned.status == CustomerStatus.DRAFT
        assert cloned.credit_limit.limit_amount == Decimal("0")
        assert cloned.outstanding_balance == Decimal("0")
        assert len(CustomerEntity._audit_trail) == 1
        assert CustomerEntity._audit_trail[0]["action"] == "CLONE"

    def test_clone_with_new_code(self, valid_customer):
        cloned = valid_customer.clone(new_code="CUST-002")
        assert cloned.customer_code == "CUST-002"

    def test_snapshot(self, valid_customer):
        snap = valid_customer.snapshot()
        assert snap["version"] == 1
        assert snap["customer_id"] == str(valid_customer.customer_id)

    def test_get_version(self, valid_customer):
        assert valid_customer.get_version() == 1

    def test_audit_trail(self, valid_customer):
        valid_customer.create("admin")
        valid_customer.update("admin", customer_name="New")
        trail = valid_customer.audit_trail(limit=2)
        assert len(trail) == 2
        assert trail[0]["action"] == "CREATE"
        assert trail[1]["action"] == "UPDATE"

    def test_touch(self, valid_customer):
        touched = valid_customer.touch("toucher")
        assert touched.version == valid_customer.version + 1
        assert touched.updated_by == "toucher"
        assert len(CustomerEntity._audit_trail) == 1
        assert CustomerEntity._audit_trail[0]["action"] == "TOUCH"


# ============================================================================
# Tests for Business Logic
# ============================================================================

class TestCustomerEntityBusiness:
    def test_is_active(self, valid_customer, inactive_customer):
        assert valid_customer.is_active() is True
        assert inactive_customer.is_active() is False

    def test_can_transact(self, valid_customer, inactive_customer, blocked_customer):
        assert valid_customer.can_transact() is True
        assert inactive_customer.can_transact() is False
        assert blocked_customer.can_transact() is False
        cust_on_hold = valid_customer.update_credit_hold(True, "admin")
        assert cust_on_hold.can_transact() is False

    def test_can_receive_payment(self, valid_customer, inactive_customer, blocked_customer, blacklisted_customer):
        assert valid_customer.can_receive_payment() is True
        assert inactive_customer.can_receive_payment() is False
        assert blocked_customer.can_receive_payment() is True
        assert blacklisted_customer.can_receive_payment() is False

    def test_is_exceeding_credit_limit(self, valid_customer):
        customer = valid_customer.record_purchase(Decimal("150000000"))
        assert customer.is_exceeding_credit_limit() is True

    def test_remaining_credit(self, valid_customer):
        customer = valid_customer.record_purchase(Decimal("30000000"))
        assert customer.remaining_credit() == Decimal("70000000")

    def test_credit_utilization_percentage(self, valid_customer):
        customer = valid_customer.record_purchase(Decimal("25000000"))
        assert customer.credit_utilization_percentage() == Decimal("25")

    def test_can_invoice_success(self, valid_customer):
        result, msg = valid_customer.can_invoice(Decimal("50000000"))
        assert result is True
        assert msg is None

    def test_can_invoice_exceeds_limit(self, valid_customer):
        customer = valid_customer.record_purchase(Decimal("80000000"))
        result, msg = customer.can_invoice(Decimal("30000000"))
        assert result is False
        assert "exceeds" in msg or "limit" in msg

    def test_can_invoice_amount_zero(self, valid_customer):
        result, msg = valid_customer.can_invoice(Decimal("0"))
        assert result is False
        assert "positive" in msg

    def test_can_invoice_customer_blocked(self, blocked_customer):
        result, msg = blocked_customer.can_invoice(Decimal("1000"))
        assert result is False
        assert "status" in msg

    def test_can_invoice_credit_hold(self, valid_customer):
        customer = valid_customer.update_credit_hold(True, "admin")
        result, msg = customer.can_invoice(Decimal("1000"))
        assert result is False
        assert "credit hold" in msg

    def test_update_balance(self, valid_customer):
        updated = valid_customer.update_balance(Decimal("1000000"), transaction_date=date(2024, 2, 1))
        assert updated.outstanding_balance == Decimal("1000000")
        assert updated.total_purchases == Decimal("1000000")
        assert updated.last_purchase_date == date(2024, 2, 1)

    def test_update_balance_payment(self, customer_with_balance):
        updated = customer_with_balance.update_balance(Decimal("-3000000"), transaction_date=date(2024, 2, 15))
        assert updated.outstanding_balance == Decimal("2000000")
        assert updated.last_payment_date == date(2024, 2, 15)

    def test_update_balance_clamp(self, customer_with_balance):
        updated = customer_with_balance.update_balance(Decimal("-10000000"))
        assert updated.outstanding_balance == Decimal("0")

    def test_record_payment(self, customer_with_balance):
        updated = customer_with_balance.record_payment(Decimal("2000000"), payment_date=date(2024, 2, 20))
        assert updated.outstanding_balance == Decimal("3000000")
        assert updated.last_payment_date == date(2024, 2, 20)

    def test_record_payment_negative_amount(self, customer_with_balance):
        with pytest.raises(ValueError, match="Payment amount must be positive"):
            customer_with_balance.record_payment(Decimal("-100"))

    def test_record_purchase(self, valid_customer):
        updated = valid_customer.record_purchase(Decimal("7500000"), purchase_date=date(2024, 3, 1))
        assert updated.outstanding_balance == Decimal("7500000")
        assert updated.total_purchases == Decimal("7500000")

    def test_record_purchase_negative_amount(self, valid_customer):
        with pytest.raises(ValueError, match="Purchase amount must be positive"):
            valid_customer.record_purchase(Decimal("-100"))

    def test_update_credit_limit(self, valid_customer, credit_limit_vo):
        new_limit = CustomerCreditLimitVO(limit_amount=Decimal("200000000"), currency="IDR")
        updated = valid_customer.update_credit_limit(new_limit, updated_by="finance")
        assert updated.credit_limit == new_limit
        assert updated.version == valid_customer.version + 1

    def test_update_tax_status(self, valid_customer, tax_status_vo):
        new_tax = CustomerTaxStatusVO(article="PPh 4(2)", rate=Decimal("2.0"), is_final=True)
        updated = valid_customer.update_tax_status(new_tax, updated_by="tax")
        assert updated.tax_status == new_tax
        assert updated.version == valid_customer.version + 1

    def test_block(self, valid_customer):
        blocked = valid_customer.block(blocked_by="admin", reason="Compliance")
        assert blocked.status == CustomerStatus.BLOCKED
        assert blocked.credit_hold is True
        assert "Blocked: Compliance" in blocked.notes

    def test_block_already_blocked(self, blocked_customer):
        result = blocked_customer.block("admin", "again")
        assert result == blocked_customer

    def test_block_blacklisted_fails(self, blacklisted_customer):
        with pytest.raises(ValueError, match="Cannot block blacklisted customer"):
            blacklisted_customer.block("admin", "reason")

    def test_unblock(self, blocked_customer):
        unblocked = blocked_customer.unblock("admin")
        assert unblocked.status == CustomerStatus.ACTIVE
        assert unblocked.credit_hold is False

    def test_unblock_non_blocked_fails(self, valid_customer):
        with pytest.raises(ValueError, match="Customer is not blocked"):
            valid_customer.unblock("admin")

    def test_blacklist(self, valid_customer):
        blacklisted = valid_customer.blacklist(blacklisted_by="admin", reason="Fraud")
        assert blacklisted.status == CustomerStatus.BLACKLISTED
        assert blacklisted.credit_hold is True
        assert blacklisted.risk_score == 100

    def test_deactivate(self, valid_customer):
        deactivated = valid_customer.deactivate("admin")
        assert deactivated.status == CustomerStatus.INACTIVE

    def test_deactivate_already_inactive(self, inactive_customer):
        result = inactive_customer.deactivate("admin")
        assert result == inactive_customer

    def test_update_credit_hold(self, valid_customer):
        updated = valid_customer.update_credit_hold(True, "admin", reason="Overdue")
        assert updated.credit_hold is True
        assert "Credit hold applied" in updated.notes
        updated2 = updated.update_credit_hold(False, "admin", reason="Paid")
        assert updated2.credit_hold is False

    def test_update_credit_hold_no_change(self, valid_customer):
        result = valid_customer.update_credit_hold(False, "admin")
        assert result == valid_customer

    def test_update_risk_score(self, valid_customer):
        updated = valid_customer.update_risk_score(75, updated_by="risk")
        assert updated.risk_score == 75

    def test_update_risk_score_invalid(self, valid_customer):
        with pytest.raises(ValueError, match="Risk score must be 0-100"):
            valid_customer.update_risk_score(200, "admin")


# ============================================================================
# Tests for Dunder Methods
# ============================================================================

class TestCustomerEntityDunder:
    def test_str(self, valid_customer):
        assert str(valid_customer) == "CUST-001 - PT Maju Jaya"

    def test_repr(self, valid_customer):
        assert repr(valid_customer) == "CustomerEntity(CUST-001, status=active)"

    def test_equality(self, valid_customer):
        same = CustomerEntity(
            customer_id=valid_customer.customer_id,
            legal_entity_id=uuid4(),
            customer_code="diff",
            customer_name="diff",
            customer_type=CustomerType.COMPANY,
        )
        assert valid_customer == same
        different = CustomerEntity(
            customer_id=uuid4(),
            legal_entity_id=uuid4(),
            customer_code="CUST-002",
            customer_name="Other",
            customer_type=CustomerType.COMPANY,
        )
        assert valid_customer != different

    def test_hash(self, valid_customer):
        assert hash(valid_customer) == hash(valid_customer.customer_id)


# ============================================================================
# Tests for CustomerEntityRepository (In-memory implementation)
# ============================================================================

class TestCustomerEntityRepository:
    async def test_save_and_get_by_id(self, valid_customer):
        legal_id = valid_customer.legal_entity_id
        await CustomerEntityRepository.save(valid_customer, legal_id)
        retrieved = await CustomerEntityRepository.get_by_id(valid_customer.customer_id, legal_id)
        assert retrieved == valid_customer

    async def test_get_by_code(self, valid_customer):
        legal_id = valid_customer.legal_entity_id
        await CustomerEntityRepository.save(valid_customer, legal_id)
        retrieved = await CustomerEntityRepository.get_by_code(valid_customer.customer_code, legal_id)
        assert retrieved == valid_customer

    async def test_get_by_email(self, valid_customer):
        legal_id = valid_customer.legal_entity_id
        await CustomerEntityRepository.save(valid_customer, legal_id)
        retrieved = await CustomerEntityRepository.get_by_email(valid_customer.email, legal_id)
        assert retrieved == valid_customer

    async def test_get_by_tax_id(self, valid_customer):
        legal_id = valid_customer.legal_entity_id
        await CustomerEntityRepository.save(valid_customer, legal_id)
        retrieved = await CustomerEntityRepository.get_by_tax_id(valid_customer.tax_id, legal_id)
        assert retrieved == valid_customer

    async def test_get_all(self, valid_customer):
        legal_id = valid_customer.legal_entity_id
        await CustomerEntityRepository.save(valid_customer, legal_id)
        all_customers = await CustomerEntityRepository.get_all(legal_id)
        assert len(all_customers) == 1

    async def test_update(self, valid_customer):
        legal_id = valid_customer.legal_entity_id
        await CustomerEntityRepository.save(valid_customer, legal_id)
        updated = valid_customer.update(updated_by="admin", customer_name="New Name")
        await CustomerEntityRepository.update(updated, legal_id)
        retrieved = await CustomerEntityRepository.get_by_id(valid_customer.customer_id, legal_id)
        assert retrieved.customer_name == "New Name"

    async def test_delete(self, valid_customer):
        legal_id = valid_customer.legal_entity_id
        await CustomerEntityRepository.save(valid_customer, legal_id)
        await CustomerEntityRepository.delete(valid_customer.customer_id, legal_id)
        retrieved = await CustomerEntityRepository.get_by_id(valid_customer.customer_id, legal_id)
        assert retrieved is None

    async def test_exists(self, valid_customer):
        legal_id = valid_customer.legal_entity_id
        await CustomerEntityRepository.save(valid_customer, legal_id)
        assert await CustomerEntityRepository.exists(valid_customer.customer_id, legal_id) is True
        assert await CustomerEntityRepository.exists(uuid4(), legal_id) is False

    async def test_count(self, valid_customer):
        legal_id = valid_customer.legal_entity_id
        assert await CustomerEntityRepository.count(legal_id) == 0
        await CustomerEntityRepository.save(valid_customer, legal_id)
        assert await CustomerEntityRepository.count(legal_id) == 1

    async def test_list(self, valid_customer):
        legal_id = valid_customer.legal_entity_id
        await CustomerEntityRepository.save(valid_customer, legal_id)
        cust2 = CustomerEntity(
            customer_id=uuid4(),
            legal_entity_id=legal_id,
            customer_code="CUST-002",
            customer_name="Another",
            customer_type=CustomerType.COMPANY,
        )
        await CustomerEntityRepository.save(cust2, legal_id)
        result = await CustomerEntityRepository.list(legal_id, limit=1, offset=1)
        assert len(result) == 1
        assert result[0].customer_code == "CUST-002"

    async def test_paginate(self, valid_customer):
        legal_id = valid_customer.legal_entity_id
        await CustomerEntityRepository.save(valid_customer, legal_id)
        cust2 = CustomerEntity(
            customer_id=uuid4(),
            legal_entity_id=legal_id,
            customer_code="CUST-002",
            customer_name="Another",
            customer_type=CustomerType.COMPANY,
        )
        await CustomerEntityRepository.save(cust2, legal_id)
        items, total = await CustomerEntityRepository.paginate(legal_id, page=2, per_page=1)
        assert total == 2
        assert len(items) == 1
        assert items[0].customer_code == "CUST-002"

    async def test_search(self, valid_customer):
        legal_id = valid_customer.legal_entity_id
        await CustomerEntityRepository.save(valid_customer, legal_id)
        cust2 = CustomerEntity(
            customer_id=uuid4(),
            legal_entity_id=legal_id,
            customer_code="CUST-002",
            customer_name="PT Abadi",
            customer_type=CustomerType.COMPANY,
            email="abadi@company.com",
        )
        await CustomerEntityRepository.save(cust2, legal_id)
        results = await CustomerEntityRepository.search(legal_id, "maju")
        assert len(results) == 1
        assert results[0].customer_code == "CUST-001"

    async def test_lock_repository(self, valid_customer):
        legal_id = valid_customer.legal_entity_id
        await CustomerEntityRepository.save(valid_customer, legal_id)
        locked = await CustomerEntityRepository.lock(valid_customer.customer_id, legal_id, "admin", "test")
        assert locked.status == CustomerStatus.BLOCKED
        retrieved = await CustomerEntityRepository.get_by_id(valid_customer.customer_id, legal_id)
        assert retrieved.status == CustomerStatus.BLOCKED

    async def test_unlock_repository(self, blocked_customer):
        legal_id = blocked_customer.legal_entity_id
        await CustomerEntityRepository.save(blocked_customer, legal_id)
        unlocked = await CustomerEntityRepository.unlock(blocked_customer.customer_id, legal_id, "admin")
        assert unlocked.status == CustomerStatus.ACTIVE
        retrieved = await CustomerEntityRepository.get_by_id(blocked_customer.customer_id, legal_id)
        assert retrieved.status == CustomerStatus.ACTIVE
