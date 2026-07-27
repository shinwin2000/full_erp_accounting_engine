# test_financial_obligation.py
# =============================
# Comprehensive tests for domain/reality/financial_obligation.py.
# Covers enums, PaymentSchedule, FinancialObligation, and FinancialObligationService.

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from domain.reality.financial_obligation import (
    FinancialObligation,
    FinancialObligationService,
    ObligationStatus,
    ObligationType,
    PaymentSchedule,
    _FallbackObligationStorage,
    get_financial_obligation_service,
)
from domain.shared_value_objects.money_vo import Money


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestObligationType:
    def test_members_exist(self):
        assert hasattr(ObligationType, "ACCOUNTS_PAYABLE")
        assert hasattr(ObligationType, "ACCRUED_EXPENSES")
        assert hasattr(ObligationType, "DEFERRED_REVENUE")
        assert hasattr(ObligationType, "VAT_PAYABLE")
        assert hasattr(ObligationType, "INCOME_TAX_PAYABLE")
        assert hasattr(ObligationType, "WITHHOLDING_TAX_PAYABLE")
        assert hasattr(ObligationType, "BANK_LOAN")
        assert hasattr(ObligationType, "BOND_PAYABLE")
        assert hasattr(ObligationType, "LEASE_LIABILITY")
        assert hasattr(ObligationType, "PURCHASE_COMMITMENT")
        assert hasattr(ObligationType, "PERFORMANCE_OBLIGATION")
        assert hasattr(ObligationType, "WARRANTY_OBLIGATION")
        assert hasattr(ObligationType, "OTHER_PAYABLES")

    def test_member_is_instance(self):
        assert isinstance(ObligationType.ACCOUNTS_PAYABLE, ObligationType)


class TestObligationStatus:
    def test_members_exist(self):
        assert hasattr(ObligationStatus, "INCURRED")
        assert hasattr(ObligationStatus, "CURRENT")
        assert hasattr(ObligationStatus, "PAST_DUE")
        assert hasattr(ObligationStatus, "PARTIALLY_PAID")
        assert hasattr(ObligationStatus, "SETTLED")
        assert hasattr(ObligationStatus, "CANCELLED")
        assert hasattr(ObligationStatus, "WRITTEN_OFF")

    def test_member_is_instance(self):
        assert isinstance(ObligationStatus.INCURRED, ObligationStatus)


# ----------------------------------------------------------------------
# PaymentSchedule
# ----------------------------------------------------------------------
class TestPaymentSchedule:
    def test_construction(self):
        due = datetime(2025, 1, 1, tzinfo=UTC)
        schedule = PaymentSchedule(
            due_date=due,
            amount=Decimal("1000.00"),
            currency="USD",
            paid_amount=Decimal("300.00"),
            paid_at=datetime(2024, 12, 15, tzinfo=UTC),
            payment_reference="PAY-001",
        )
        assert schedule.due_date == due
        assert schedule.amount == Decimal("1000.00")
        assert schedule.currency == "USD"
        assert schedule.paid_amount == Decimal("300.00")
        assert schedule.paid_at == datetime(2024, 12, 15, tzinfo=UTC)
        assert schedule.payment_reference == "PAY-001"

    def test_is_paid_true(self):
        schedule = PaymentSchedule(
            due_date=datetime.now(UTC),
            amount=Decimal("500"),
            paid_amount=Decimal("500"),
        )
        assert schedule.is_paid is True

    def test_is_paid_false(self):
        schedule = PaymentSchedule(
            due_date=datetime.now(UTC),
            amount=Decimal("500"),
            paid_amount=Decimal("300"),
        )
        assert schedule.is_paid is False

    def test_remaining_property(self):
        schedule = PaymentSchedule(
            due_date=datetime.now(UTC),
            amount=Decimal("1000"),
            paid_amount=Decimal("300"),
            currency="IDR",
        )
        remaining = schedule.remaining
        assert isinstance(remaining, Money)
        assert remaining.amount == Decimal("700")
        assert remaining.currency == "IDR"

    def test_record_payment_full(self):
        schedule = PaymentSchedule(
            due_date=datetime.now(UTC),
            amount=Decimal("1000"),
            paid_amount=Decimal("0"),
            currency="USD",
        )
        paid_at = datetime.now(UTC)
        new_schedule = schedule.record_payment(
            amount=Money(Decimal("1000"), "USD"),
            reference="PAY-002",
            paid_at=paid_at,
        )
        assert new_schedule.paid_amount == Decimal("1000")
        assert new_schedule.is_paid is True
        assert new_schedule.payment_reference == "PAY-002"
        assert new_schedule.paid_at == paid_at

    def test_record_payment_partial(self):
        schedule = PaymentSchedule(
            due_date=datetime.now(UTC),
            amount=Decimal("1000"),
            paid_amount=Decimal("0"),
        )
        new_schedule = schedule.record_payment(
            amount=Money(Decimal("400"), "IDR"),
            reference="PAY-003",
            paid_at=datetime.now(UTC),
        )
        assert new_schedule.paid_amount == Decimal("400")
        assert new_schedule.is_paid is False

    def test_record_payment_currency_mismatch_raises(self):
        schedule = PaymentSchedule(
            due_date=datetime.now(UTC),
            amount=Decimal("1000"),
            currency="USD",
        )
        with pytest.raises(ValueError, match="Currency mismatch"):
            schedule.record_payment(
                amount=Money(Decimal("100"), "IDR"),
                reference="REF",
                paid_at=datetime.now(UTC),
            )


# ----------------------------------------------------------------------
# FinancialObligation
# ----------------------------------------------------------------------
class TestFinancialObligation:
    @pytest.fixture
    def obligation(self) -> FinancialObligation:
        return FinancialObligation(
            obligation_id=uuid4(),
            obligation_type=ObligationType.ACCOUNTS_PAYABLE,
            source_event_id=uuid4(),
            legal_entity_id=uuid4(),
            counterparty_id=uuid4(),
            original_amount=Money(Decimal("5000"), "IDR"),
            outstanding_amount=Money(Decimal("5000"), "IDR"),
            incurred_date=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
            due_date=datetime(2025, 2, 1, 10, 0, tzinfo=UTC),
            status=ObligationStatus.INCURRED,
            description="Test obligation",
            contract_reference="CON-001",
            interest_rate=Decimal("0.05"),
            payment_schedule=[],
            notes="Test notes",
            created_at=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
            updated_at=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
            cryptographic_hash="",
        )

    def test_construction(self, obligation):
        assert obligation.obligation_id is not None
        assert obligation.obligation_type == ObligationType.ACCOUNTS_PAYABLE
        assert obligation.original_amount.amount == Decimal("5000")
        assert obligation.outstanding_amount.amount == Decimal("5000")
        assert obligation.description == "Test obligation"
        assert obligation.cryptographic_hash != ""

    def test_compute_hash(self, obligation):
        h1 = obligation.compute_hash()
        h2 = obligation.compute_hash()
        assert h1 == h2
        assert len(h1) == 64  # SHA3-256

    def test_hash_mismatch_raises(self):
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            FinancialObligation(
                obligation_id=uuid4(),
                obligation_type=ObligationType.ACCOUNTS_PAYABLE,
                source_event_id=uuid4(),
                legal_entity_id=uuid4(),
                counterparty_id=None,
                original_amount=Money(Decimal("1000"), "IDR"),
                outstanding_amount=Money(Decimal("1000"), "IDR"),
                incurred_date=datetime.now(UTC),
                due_date=None,
                status=ObligationStatus.INCURRED,
                description="Test",
                cryptographic_hash="corrupted",
            )

    def test_is_overdue_true(self, obligation):
        # Set due date in past
        obligation = FinancialObligation(
            obligation_id=obligation.obligation_id,
            obligation_type=obligation.obligation_type,
            source_event_id=obligation.source_event_id,
            legal_entity_id=obligation.legal_entity_id,
            counterparty_id=obligation.counterparty_id,
            original_amount=obligation.original_amount,
            outstanding_amount=obligation.outstanding_amount,
            incurred_date=obligation.incurred_date,
            due_date=datetime.now(UTC) - timedelta(days=5),
            status=ObligationStatus.INCURRED,
            description=obligation.description,
            contract_reference=obligation.contract_reference,
            interest_rate=obligation.interest_rate,
            payment_schedule=obligation.payment_schedule,
            notes=obligation.notes,
            created_at=obligation.created_at,
            updated_at=obligation.updated_at,
            cryptographic_hash=obligation.cryptographic_hash,
        )
        assert obligation.is_overdue is True

    def test_is_overdue_false_settled(self, obligation):
        obligation = FinancialObligation(
            obligation_id=obligation.obligation_id,
            obligation_type=obligation.obligation_type,
            source_event_id=obligation.source_event_id,
            legal_entity_id=obligation.legal_entity_id,
            counterparty_id=obligation.counterparty_id,
            original_amount=obligation.original_amount,
            outstanding_amount=Money(Decimal("0"), "IDR"),
            incurred_date=obligation.incurred_date,
            due_date=datetime.now(UTC) - timedelta(days=5),
            status=ObligationStatus.SETTLED,
            description=obligation.description,
            contract_reference=obligation.contract_reference,
            interest_rate=obligation.interest_rate,
            payment_schedule=obligation.payment_schedule,
            notes=obligation.notes,
            created_at=obligation.created_at,
            updated_at=obligation.updated_at,
            cryptographic_hash=obligation.cryptographic_hash,
        )
        assert obligation.is_overdue is False

    def test_days_overdue(self, obligation):
        # Set due_date to 10 days ago
        due = datetime.now(UTC) - timedelta(days=10)
        obligation = FinancialObligation(
            obligation_id=obligation.obligation_id,
            obligation_type=obligation.obligation_type,
            source_event_id=obligation.source_event_id,
            legal_entity_id=obligation.legal_entity_id,
            counterparty_id=obligation.counterparty_id,
            original_amount=obligation.original_amount,
            outstanding_amount=obligation.outstanding_amount,
            incurred_date=obligation.incurred_date,
            due_date=due,
            status=ObligationStatus.INCURRED,
            description=obligation.description,
            contract_reference=obligation.contract_reference,
            interest_rate=obligation.interest_rate,
            payment_schedule=obligation.payment_schedule,
            notes=obligation.notes,
            created_at=obligation.created_at,
            updated_at=obligation.updated_at,
            cryptographic_hash=obligation.cryptographic_hash,
        )
        assert obligation.days_overdue == 10

    def test_days_overdue_zero_when_not_overdue(self, obligation):
        # due_date in future
        obligation = FinancialObligation(
            obligation_id=obligation.obligation_id,
            obligation_type=obligation.obligation_type,
            source_event_id=obligation.source_event_id,
            legal_entity_id=obligation.legal_entity_id,
            counterparty_id=obligation.counterparty_id,
            original_amount=obligation.original_amount,
            outstanding_amount=obligation.outstanding_amount,
            incurred_date=obligation.incurred_date,
            due_date=datetime.now(UTC) + timedelta(days=5),
            status=ObligationStatus.INCURRED,
            description=obligation.description,
            contract_reference=obligation.contract_reference,
            interest_rate=obligation.interest_rate,
            payment_schedule=obligation.payment_schedule,
            notes=obligation.notes,
            created_at=obligation.created_at,
            updated_at=obligation.updated_at,
            cryptographic_hash=obligation.cryptographic_hash,
        )
        assert obligation.days_overdue == 0

    def test_is_fully_settled_true_by_status(self, obligation):
        obligation = FinancialObligation(
            obligation_id=obligation.obligation_id,
            obligation_type=obligation.obligation_type,
            source_event_id=obligation.source_event_id,
            legal_entity_id=obligation.legal_entity_id,
            counterparty_id=obligation.counterparty_id,
            original_amount=obligation.original_amount,
            outstanding_amount=Money(Decimal("100"), "IDR"),
            incurred_date=obligation.incurred_date,
            due_date=obligation.due_date,
            status=ObligationStatus.SETTLED,
            description=obligation.description,
            contract_reference=obligation.contract_reference,
            interest_rate=obligation.interest_rate,
            payment_schedule=obligation.payment_schedule,
            notes=obligation.notes,
            created_at=obligation.created_at,
            updated_at=obligation.updated_at,
            cryptographic_hash=obligation.cryptographic_hash,
        )
        assert obligation.is_fully_settled is True

    def test_is_fully_settled_true_by_zero_outstanding(self, obligation):
        obligation = FinancialObligation(
            obligation_id=obligation.obligation_id,
            obligation_type=obligation.obligation_type,
            source_event_id=obligation.source_event_id,
            legal_entity_id=obligation.legal_entity_id,
            counterparty_id=obligation.counterparty_id,
            original_amount=obligation.original_amount,
            outstanding_amount=Money(Decimal("0"), "IDR"),
            incurred_date=obligation.incurred_date,
            due_date=obligation.due_date,
            status=ObligationStatus.INCURRED,
            description=obligation.description,
            contract_reference=obligation.contract_reference,
            interest_rate=obligation.interest_rate,
            payment_schedule=obligation.payment_schedule,
            notes=obligation.notes,
            created_at=obligation.created_at,
            updated_at=obligation.updated_at,
            cryptographic_hash=obligation.cryptographic_hash,
        )
        assert obligation.is_fully_settled is True

    def test_is_fully_settled_false(self, obligation):
        assert obligation.is_fully_settled is False

    def test_record_payment_full(self, obligation):
        paid_at = datetime.now(UTC)
        payment_amount = Money(Decimal("5000"), "IDR")
        new_obligation = obligation.record_payment(
            amount=payment_amount,
            payment_reference="PAY-FULL",
            paid_at=paid_at,
        )
        assert new_obligation.outstanding_amount.amount == Decimal("0")
        assert new_obligation.status == ObligationStatus.SETTLED
        assert new_obligation.updated_at >= paid_at

    def test_record_payment_partial(self, obligation):
        paid_at = datetime.now(UTC)
        payment_amount = Money(Decimal("2000"), "IDR")
        new_obligation = obligation.record_payment(
            amount=payment_amount,
            payment_reference="PAY-PARTIAL",
            paid_at=paid_at,
        )
        assert new_obligation.outstanding_amount.amount == Decimal("3000")
        assert new_obligation.status == ObligationStatus.PARTIALLY_PAID

    def test_record_payment_with_schedule(self, obligation):
        # Create obligation with payment schedule
        schedule = PaymentSchedule(
            due_date=datetime.now(UTC) + timedelta(days=30),
            amount=Decimal("5000"),
            currency="IDR",
        )
        obligation = FinancialObligation(
            obligation_id=obligation.obligation_id,
            obligation_type=obligation.obligation_type,
            source_event_id=obligation.source_event_id,
            legal_entity_id=obligation.legal_entity_id,
            counterparty_id=obligation.counterparty_id,
            original_amount=obligation.original_amount,
            outstanding_amount=obligation.outstanding_amount,
            incurred_date=obligation.incurred_date,
            due_date=obligation.due_date,
            status=obligation.status,
            description=obligation.description,
            contract_reference=obligation.contract_reference,
            interest_rate=obligation.interest_rate,
            payment_schedule=[schedule],
            notes=obligation.notes,
            created_at=obligation.created_at,
            updated_at=obligation.updated_at,
            cryptographic_hash=obligation.cryptographic_hash,
        )
        paid_at = datetime.now(UTC)
        new_obligation = obligation.record_payment(
            amount=Money(Decimal("2000"), "IDR"),
            payment_reference="PAY-SCHED",
            paid_at=paid_at,
        )
        assert len(new_obligation.payment_schedule) == 1
        updated_schedule = new_obligation.payment_schedule[0]
        assert updated_schedule.paid_amount == Decimal("2000")
        assert updated_schedule.payment_reference == "PAY-SCHED"

    def test_record_payment_currency_mismatch_raises(self, obligation):
        with pytest.raises(ValueError, match="Currency mismatch"):
            obligation.record_payment(
                amount=Money(Decimal("100"), "USD"),
                payment_reference="REF",
                paid_at=datetime.now(UTC),
            )

    def test_to_dict(self, obligation):
        d = obligation.to_dict()
        assert d["obligation_id"] == str(obligation.obligation_id)
        assert d["obligation_type"] == "ACCOUNTS_PAYABLE"
        assert d["source_event_id"] == str(obligation.source_event_id)
        assert d["legal_entity_id"] == str(obligation.legal_entity_id)
        assert d["counterparty_id"] == str(obligation.counterparty_id)
        assert d["original_amount"] == "5000"
        assert d["original_currency"] == "IDR"
        assert d["outstanding_amount"] == "5000"
        assert d["outstanding_currency"] == "IDR"
        assert d["status"] == "INCURRED"
        assert d["description"] == "Test obligation"


# ----------------------------------------------------------------------
# _FallbackObligationStorage (internal, but we test it)
# ----------------------------------------------------------------------
class TestFallbackObligationStorage:
    def test_save_and_get(self):
        storage = _FallbackObligationStorage()
        obligation_id = uuid4()
        obligation = FinancialObligation(
            obligation_id=obligation_id,
            obligation_type=ObligationType.ACCOUNTS_PAYABLE,
            source_event_id=uuid4(),
            legal_entity_id=uuid4(),
            counterparty_id=None,
            original_amount=Money(Decimal("1000"), "IDR"),
            outstanding_amount=Money(Decimal("1000"), "IDR"),
            incurred_date=datetime.now(UTC),
            due_date=None,
            status=ObligationStatus.INCURRED,
            description="Test",
        )
        storage.save(obligation)
        data = storage.get(obligation_id)
        assert data is not None
        assert data["obligation_id"] == str(obligation_id)

        # get non-existent
        assert storage.get(uuid4()) is None

    def test_get_all(self):
        storage = _FallbackObligationStorage()
        le_id = uuid4()
        for i in range(3):
            obligation = FinancialObligation(
                obligation_id=uuid4(),
                obligation_type=ObligationType.ACCOUNTS_PAYABLE,
                source_event_id=uuid4(),
                legal_entity_id=le_id,
                counterparty_id=None,
                original_amount=Money(Decimal("100"), "IDR"),
                outstanding_amount=Money(Decimal("100"), "IDR"),
                incurred_date=datetime.now(UTC),
                due_date=None,
                status=ObligationStatus.INCURRED,
                description=f"Test {i}",
            )
            storage.save(obligation)
        all_data = storage.get_all(le_id)
        assert len(all_data) == 3
        # Different legal entity returns empty
        other_le = uuid4()
        assert storage.get_all(other_le) == []


# ----------------------------------------------------------------------
# FinancialObligationService
# ----------------------------------------------------------------------
class TestFinancialObligationService:
    @pytest.fixture
    def service(self) -> FinancialObligationService:
        # Reset singleton
        FinancialObligationService._instance = None
        service = FinancialObligationService()
        # Clear internal storage for isolation
        service._storage = _FallbackObligationStorage()
        service._cache.clear()
        return service

    def test_singleton(self):
        s1 = get_financial_obligation_service()
        s2 = get_financial_obligation_service()
        assert s1 is s2

    def test_create_obligation(self, service):
        le_id = uuid4()
        source_id = uuid4()
        amount = Money(Decimal("2000"), "IDR")
        incurred = datetime(2025, 1, 1, tzinfo=UTC)
        due = datetime(2025, 2, 1, tzinfo=UTC)
        obligation = service.create_obligation(
            obligation_type=ObligationType.ACCOUNTS_PAYABLE,
            source_event_id=source_id,
            legal_entity_id=le_id,
            amount=amount,
            incurred_date=incurred,
            due_date=due,
            description="Test obligation",
            counterparty_id=uuid4(),
            contract_reference="CON-001",
            payment_schedule=[],
        )
        assert obligation.obligation_type == ObligationType.ACCOUNTS_PAYABLE
        assert obligation.source_event_id == source_id
        assert obligation.legal_entity_id == le_id
        assert obligation.original_amount.amount == Decimal("2000")
        assert obligation.outstanding_amount.amount == Decimal("2000")
        assert obligation.incurred_date == incurred
        assert obligation.due_date == due
        assert obligation.status == ObligationStatus.INCURRED
        assert obligation.cryptographic_hash != ""
        # Check stored
        retrieved = service.get_obligation(obligation.obligation_id)
        assert retrieved is not None
        assert retrieved.obligation_id == obligation.obligation_id

    def test_get_obligation_caches(self, service):
        obligation = service.create_obligation(
            obligation_type=ObligationType.ACCOUNTS_PAYABLE,
            source_event_id=uuid4(),
            legal_entity_id=uuid4(),
            amount=Money(Decimal("1000"), "IDR"),
            incurred_date=datetime.now(UTC),
            due_date=None,
            description="Test",
        )
        # First get from storage (cache miss)
        with patch.object(service._storage, "get", wraps=service._storage.get) as mock_get:
            retrieved = service.get_obligation(obligation.obligation_id)
            assert retrieved is not None
            assert mock_get.call_count == 1
        # Second get from cache (no storage call)
        with patch.object(service._storage, "get") as mock_get:
            retrieved2 = service.get_obligation(obligation.obligation_id)
            assert retrieved2 is not None
            mock_get.assert_not_called()

    def test_get_obligation_not_found(self, service):
        assert service.get_obligation(uuid4()) is None

    def test_get_outstanding_obligations(self, service):
        le_id = uuid4()
        # Create settled obligation
        settled = service.create_obligation(
            obligation_type=ObligationType.ACCOUNTS_PAYABLE,
            source_event_id=uuid4(),
            legal_entity_id=le_id,
            amount=Money(Decimal("1000"), "IDR"),
            incurred_date=datetime.now(UTC),
            due_date=None,
            description="Settled",
        )
        # Settle by recording payment
        settled = service.get_obligation(settled.obligation_id)
        settled = settled.record_payment(
            amount=Money(Decimal("1000"), "IDR"),
            payment_reference="REF",
            paid_at=datetime.now(UTC),
        )
        service.update_obligation(settled)

        # Create outstanding obligation
        outstanding = service.create_obligation(
            obligation_type=ObligationType.ACCOUNTS_PAYABLE,
            source_event_id=uuid4(),
            legal_entity_id=le_id,
            amount=Money(Decimal("2000"), "IDR"),
            incurred_date=datetime.now(UTC),
            due_date=None,
            description="Outstanding",
        )
        result = service.get_outstanding_obligations(le_id)
        assert len(result) == 1
        assert result[0].obligation_id == outstanding.obligation_id

    def test_get_overdue_obligations(self, service):
        le_id = uuid4()
        # Create overdue
        overdue = service.create_obligation(
            obligation_type=ObligationType.ACCOUNTS_PAYABLE,
            source_event_id=uuid4(),
            legal_entity_id=le_id,
            amount=Money(Decimal("1000"), "IDR"),
            incurred_date=datetime.now(UTC) - timedelta(days=10),
            due_date=datetime.now(UTC) - timedelta(days=5),
            description="Overdue",
        )
        # Create non-overdue
        not_overdue = service.create_obligation(
            obligation_type=ObligationType.ACCOUNTS_PAYABLE,
            source_event_id=uuid4(),
            legal_entity_id=le_id,
            amount=Money(Decimal("2000"), "IDR"),
            incurred_date=datetime.now(UTC),
            due_date=datetime.now(UTC) + timedelta(days=10),
            description="Not overdue",
        )
        result = service.get_overdue_obligations(le_id)
        assert len(result) == 1
        assert result[0].obligation_id == overdue.obligation_id

    def test_get_aging_summary(self, service):
        le_id = uuid4()
        now = datetime.now(UTC)
        # Create obligations with various due dates
        # Current (due > now)
        service.create_obligation(
            obligation_type=ObligationType.ACCOUNTS_PAYABLE,
            source_event_id=uuid4(),
            legal_entity_id=le_id,
            amount=Money(Decimal("100"), "IDR"),
            incurred_date=now - timedelta(days=5),
            due_date=now + timedelta(days=5),
            description="Current",
        )
        # 1-30 days overdue (due 10 days ago)
        service.create_obligation(
            obligation_type=ObligationType.ACCOUNTS_PAYABLE,
            source_event_id=uuid4(),
            legal_entity_id=le_id,
            amount=Money(Decimal("200"), "IDR"),
            incurred_date=now - timedelta(days=15),
            due_date=now - timedelta(days=10),
            description="1-30",
        )
        # 31-60 days overdue (due 40 days ago)
        service.create_obligation(
            obligation_type=ObligationType.ACCOUNTS_PAYABLE,
            source_event_id=uuid4(),
            legal_entity_id=le_id,
            amount=Money(Decimal("300"), "IDR"),
            incurred_date=now - timedelta(days=50),
            due_date=now - timedelta(days=40),
            description="31-60",
        )
        aging = service.get_aging_summary(le_id)
        assert aging["current"] == Decimal("100")
        assert aging["1_30_days"] == Decimal("200")
        assert aging["31_60_days"] == Decimal("300")
        assert aging["61_90_days"] == Decimal("0")
        assert aging["over_90_days"] == Decimal("0")

    def test_get_total_outstanding(self, service):
        le_id = uuid4()
        service.create_obligation(
            obligation_type=ObligationType.ACCOUNTS_PAYABLE,
            source_event_id=uuid4(),
            legal_entity_id=le_id,
            amount=Money(Decimal("1000"), "IDR"),
            incurred_date=datetime.now(UTC),
            due_date=None,
            description="O1",
        )
        service.create_obligation(
            obligation_type=ObligationType.ACCOUNTS_PAYABLE,
            source_event_id=uuid4(),
            legal_entity_id=le_id,
            amount=Money(Decimal("500"), "IDR"),
            incurred_date=datetime.now(UTC),
            due_date=None,
            description="O2",
        )
        total = service.get_total_outstanding(le_id)
        assert total.amount == Decimal("1500")
        assert total.currency == "IDR"

    def test_update_obligation(self, service):
        obligation = service.create_obligation(
            obligation_type=ObligationType.ACCOUNTS_PAYABLE,
            source_event_id=uuid4(),
            legal_entity_id=uuid4(),
            amount=Money(Decimal("1000"), "IDR"),
            incurred_date=datetime.now(UTC),
            due_date=None,
            description="Original",
        )
        # Update by recording payment
        paid = obligation.record_payment(
            amount=Money(Decimal("400"), "IDR"),
            payment_reference="PAY",
            paid_at=datetime.now(UTC),
        )
        service.update_obligation(paid)
        retrieved = service.get_obligation(obligation.obligation_id)
        assert retrieved.outstanding_amount.amount == Decimal("600")
        assert retrieved.status == ObligationStatus.PARTIALLY_PAID

    def test_get_statistics(self, service):
        le_id = uuid4()
        # Create obligations with different statuses
        ob1 = service.create_obligation(
            obligation_type=ObligationType.ACCOUNTS_PAYABLE,
            source_event_id=uuid4(),
            legal_entity_id=le_id,
            amount=Money(Decimal("1000"), "IDR"),
            incurred_date=datetime.now(UTC),
            due_date=None,
            description="O1",
        )
        ob2 = service.create_obligation(
            obligation_type=ObligationType.ACCOUNTS_PAYABLE,
            source_event_id=uuid4(),
            legal_entity_id=le_id,
            amount=Money(Decimal("2000"), "IDR"),
            incurred_date=datetime.now(UTC),
            due_date=None,
            description="O2",
        )
        # Settle ob2 partially (PARTIALLY_PAID)
        paid = ob2.record_payment(
            amount=Money(Decimal("1000"), "IDR"),
            payment_reference="PAY",
            paid_at=datetime.now(UTC),
        )
        service.update_obligation(paid)
        stats = service.get_statistics(le_id)
        assert stats["legal_entity_id"] == str(le_id)
        assert stats["total_obligations"] == 2
        assert stats["by_status"] == {"INCURRED": 1, "PARTIALLY_PAID": 1}
        assert stats["total_outstanding"] == "2000.00"  # 1000 + 1000
        assert stats["overdue_count"] == 0  # no due date

    def test_get_statistics_no_obligations(self, service):
        stats = service.get_statistics(uuid4())
        assert stats == {"total_obligations": 0}