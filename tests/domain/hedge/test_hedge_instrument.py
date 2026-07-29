# test_hedge_instrument.py
# Comprehensive tests for hedge_instrument.py

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.hedge.aggregate_root import HedgeType
from domain.hedge.hedge_instrument import (
    HedgeInstrument,
    HedgeInstrumentError,
    HedgeInstrumentRepository,
    InstrumentFairValueHistory,
    InstrumentStatus,
    InstrumentType,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_audit_trail():
    """Reset class variables before each test."""
    HedgeInstrument._audit_trail = []
    HedgeInstrumentRepository._storage = {}
    yield
    HedgeInstrument._audit_trail = []
    HedgeInstrumentRepository._storage = {}


@pytest.fixture
def valid_forward_instrument():
    """Create a valid forward instrument."""
    return HedgeInstrument.create(
        instrument_number="FWD-001",
        instrument_type=InstrumentType.FORWARD,
        legal_entity_id=uuid4(),
        notional=Decimal("1000000"),
        currency="IDR",
        hedge_type=HedgeType.FAIR_VALUE,
        counterparty="Bank ABC",
        start_date=date(2024, 1, 1),
        maturity_date=date(2024, 12, 31),
        description="Forward contract for inventory",
        created_by=uuid4(),
    )


@pytest.fixture
def valid_option_instrument():
    """Create a valid option instrument."""
    return HedgeInstrument.create(
        instrument_number="OPT-001",
        instrument_type=InstrumentType.OPTION,
        legal_entity_id=uuid4(),
        notional=Decimal("500000"),
        currency="USD",
        hedge_type=HedgeType.CASH_FLOW,
        counterparty="Bank XYZ",
        start_date=date(2024, 3, 1),
        maturity_date=date(2024, 9, 1),
        strike_price=Decimal("15000"),
        premium_paid=Decimal("25000"),
        description="Call option on USD",
        created_by=uuid4(),
    )


@pytest.fixture
def instrument_with_history(valid_forward_instrument):
    """Instrument with fair value history."""
    now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
    return valid_forward_instrument.record_fair_value(
        new_fair_value=Decimal("5000"),
        valuation_date=now,
        valuation_method="mark_to_market",
        valued_by="trader1",
        notes="Initial valuation",
    )


@pytest.fixture
def cash_flow_instrument():
    """Instrument with cash flow hedge type."""
    return HedgeInstrument.create(
        instrument_number="CF-001",
        instrument_type=InstrumentType.SWAP,
        legal_entity_id=uuid4(),
        notional=Decimal("2000000"),
        currency="IDR",
        hedge_type=HedgeType.CASH_FLOW,
        counterparty="Bank DEF",
        start_date=date(2024, 2, 1),
        maturity_date=date(2025, 2, 1),
        description="Interest rate swap",
        created_by=uuid4(),
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestInstrumentType:
    def test_display_name(self):
        assert InstrumentType.FORWARD.display_name() == "Kontrak Forward"
        assert InstrumentType.FUTURE.display_name() == "Kontrak Berjangka"
        assert InstrumentType.SWAP.display_name() == "Swap"
        assert InstrumentType.OPTION.display_name() == "Opsi"
        assert InstrumentType.OTHER.display_name() == "Lainnya"

    def test_is_derivative(self):
        assert InstrumentType.FORWARD.is_derivative() is True
        assert InstrumentType.FUTURE.is_derivative() is True
        assert InstrumentType.SWAP.is_derivative() is True
        assert InstrumentType.OPTION.is_derivative() is True
        assert InstrumentType.OTHER.is_derivative() is False

    def test_has_premium(self):
        assert InstrumentType.OPTION.has_premium() is True
        assert InstrumentType.FORWARD.has_premium() is False
        assert InstrumentType.FUTURE.has_premium() is False
        assert InstrumentType.SWAP.has_premium() is False

    def test_from_string(self):
        assert InstrumentType.from_string("forward") == InstrumentType.FORWARD
        assert InstrumentType.from_string("future") == InstrumentType.FUTURE
        assert InstrumentType.from_string("swap") == InstrumentType.SWAP
        assert InstrumentType.from_string("option") == InstrumentType.OPTION
        assert InstrumentType.from_string("other") == InstrumentType.OTHER
        assert InstrumentType.from_string("unknown") is None


class TestInstrumentStatus:
    def test_is_active(self):
        assert InstrumentStatus.ACTIVE.is_active() is True
        assert InstrumentStatus.EXERCISED.is_active() is False
        assert InstrumentStatus.EXPIRED.is_active() is False
        assert InstrumentStatus.TERMINATED.is_active() is False
        assert InstrumentStatus.CANCELLED.is_active() is False

    def test_display_name(self):
        assert InstrumentStatus.ACTIVE.display_name() == "Aktif"
        assert InstrumentStatus.EXERCISED.display_name() == "Dieksekusi"
        assert InstrumentStatus.EXPIRED.display_name() == "Kadaluarsa"
        assert InstrumentStatus.TERMINATED.display_name() == "Dihentikan"
        assert InstrumentStatus.CANCELLED.display_name() == "Dibatalkan"

    def test_from_string(self):
        assert InstrumentStatus.from_string("active") == InstrumentStatus.ACTIVE
        assert InstrumentStatus.from_string("exercised") == InstrumentStatus.EXERCISED
        assert InstrumentStatus.from_string("expired") == InstrumentStatus.EXPIRED
        assert InstrumentStatus.from_string("terminated") == InstrumentStatus.TERMINATED
        assert InstrumentStatus.from_string("cancelled") == InstrumentStatus.CANCELLED
        assert InstrumentStatus.from_string("unknown") is None


# ============================================================================
# Tests for InstrumentFairValueHistory
# ============================================================================

class TestInstrumentFairValueHistory:
    def test_construction(self):
        hid = uuid4()
        iid = uuid4()
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        history = InstrumentFairValueHistory(
            history_id=hid,
            instrument_id=iid,
            valuation_date=now,
            fair_value=Decimal("1000"),
            valuation_method="mark_to_model",
            valued_by="analyst1",
            notes="Test",
            created_at=now,
        )
        assert history.history_id == hid
        assert history.fair_value == Decimal("1000")

    def test_post_init_timezone(self):
        naive = datetime(2024, 1, 1, 0, 0, 0)
        history = InstrumentFairValueHistory(
            history_id=uuid4(),
            instrument_id=uuid4(),
            valuation_date=naive,
            fair_value=Decimal("100"),
            valuation_method="method",
            valued_by="user",
            created_at=naive,
        )
        assert history.valuation_date.tzinfo is not None
        assert history.created_at.tzinfo is not None

    def test_to_dict(self):
        hid = uuid4()
        iid = uuid4()
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        history = InstrumentFairValueHistory(
            history_id=hid,
            instrument_id=iid,
            valuation_date=now,
            fair_value=Decimal("2000"),
            valuation_method="method",
            valued_by="user",
            notes="Note",
            created_at=now,
        )
        d = history.to_dict()
        assert d["history_id"] == str(hid)
        assert d["fair_value"] == "2000"
        assert d["valuation_date"] == now.isoformat()

    def test_from_dict(self):
        hid = uuid4()
        iid = uuid4()
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        data = {
            "history_id": str(hid),
            "instrument_id": str(iid),
            "valuation_date": now.isoformat(),
            "fair_value": "2000",
            "valuation_method": "method",
            "valued_by": "user",
            "notes": "Note",
            "created_at": now.isoformat(),
        }
        history = InstrumentFairValueHistory.from_dict(data)
        assert history.history_id == hid
        assert history.fair_value == Decimal("2000")


# ============================================================================
# Tests for HedgeInstrument Construction and Validation
# ============================================================================

class TestHedgeInstrumentConstruction:
    def test_create_valid_forward(self, valid_forward_instrument):
        assert isinstance(valid_forward_instrument.id, uuid4().__class__)
        assert valid_forward_instrument.instrument_number == "FWD-001"
        assert valid_forward_instrument.instrument_type == InstrumentType.FORWARD
        assert valid_forward_instrument.notional == Decimal("1000000")
        assert valid_forward_instrument.status == InstrumentStatus.ACTIVE
        assert valid_forward_instrument.version == 1

    def test_create_valid_option(self, valid_option_instrument):
        assert valid_option_instrument.instrument_type == InstrumentType.OPTION
        assert valid_option_instrument.strike_price == Decimal("15000")
        assert valid_option_instrument.premium_paid == Decimal("25000")

    def test_validation_instrument_number_too_short(self):
        with pytest.raises(HedgeInstrumentError, match="Instrument number must be at least 3 characters"):
            HedgeInstrument(
                id=uuid4(),
                instrument_number="AB",
                instrument_type=InstrumentType.FORWARD,
                legal_entity_id=uuid4(),
                notional=Decimal("1000"),
                currency="IDR",
                hedge_type=HedgeType.FAIR_VALUE,
                counterparty="Bank",
            )

    def test_validation_notional_non_positive(self):
        with pytest.raises(HedgeInstrumentError, match="Notional must be positive"):
            HedgeInstrument(
                id=uuid4(),
                instrument_number="INS-001",
                instrument_type=InstrumentType.FORWARD,
                legal_entity_id=uuid4(),
                notional=Decimal("-100"),
                currency="IDR",
                hedge_type=HedgeType.FAIR_VALUE,
                counterparty="Bank",
            )

    def test_validation_invalid_currency(self):
        with pytest.raises(HedgeInstrumentError, match="Invalid currency"):
            HedgeInstrument(
                id=uuid4(),
                instrument_number="INS-001",
                instrument_type=InstrumentType.FORWARD,
                legal_entity_id=uuid4(),
                notional=Decimal("1000"),
                currency="ID",
                hedge_type=HedgeType.FAIR_VALUE,
                counterparty="Bank",
            )

    def test_validation_counterparty_too_short(self):
        with pytest.raises(HedgeInstrumentError, match="Counterparty name must be at least 2 characters"):
            HedgeInstrument(
                id=uuid4(),
                instrument_number="INS-001",
                instrument_type=InstrumentType.FORWARD,
                legal_entity_id=uuid4(),
                notional=Decimal("1000"),
                currency="IDR",
                hedge_type=HedgeType.FAIR_VALUE,
                counterparty="A",
            )

    def test_validation_start_date_future(self):
        future_date = date.today() + timedelta(days=10)
        with pytest.raises(HedgeInstrumentError, match="Start date .* cannot be in the future"):
            HedgeInstrument(
                id=uuid4(),
                instrument_number="INS-001",
                instrument_type=InstrumentType.FORWARD,
                legal_entity_id=uuid4(),
                notional=Decimal("1000"),
                currency="IDR",
                hedge_type=HedgeType.FAIR_VALUE,
                counterparty="Bank",
                start_date=future_date,
            )

    def test_validation_maturity_before_start(self):
        start = date(2024, 1, 1)
        maturity = date(2023, 12, 31)
        with pytest.raises(HedgeInstrumentError, match="Maturity date .* cannot be before start date"):
            HedgeInstrument(
                id=uuid4(),
                instrument_number="INS-001",
                instrument_type=InstrumentType.FORWARD,
                legal_entity_id=uuid4(),
                notional=Decimal("1000"),
                currency="IDR",
                hedge_type=HedgeType.FAIR_VALUE,
                counterparty="Bank",
                start_date=start,
                maturity_date=maturity,
            )

    def test_validation_negative_premium(self):
        with pytest.raises(HedgeInstrumentError, match="Premium paid cannot be negative"):
            HedgeInstrument(
                id=uuid4(),
                instrument_number="INS-001",
                instrument_type=InstrumentType.OPTION,
                legal_entity_id=uuid4(),
                notional=Decimal("1000"),
                currency="IDR",
                hedge_type=HedgeType.FAIR_VALUE,
                counterparty="Bank",
                premium_paid=Decimal("-100"),
            )

    def test_validation_version_less_than_one(self):
        with pytest.raises(HedgeInstrumentError, match="Version must be >= 1"):
            HedgeInstrument(
                id=uuid4(),
                instrument_number="INS-001",
                instrument_type=InstrumentType.FORWARD,
                legal_entity_id=uuid4(),
                notional=Decimal("1000"),
                currency="IDR",
                hedge_type=HedgeType.FAIR_VALUE,
                counterparty="Bank",
                version=0,
            )


# ============================================================================
# Tests for Properties
# ============================================================================

class TestHedgeInstrumentProperties:
    def test_is_active(self, valid_forward_instrument):
        assert valid_forward_instrument.is_active is True
        expired = valid_forward_instrument.expire()
        assert expired.is_active is False

    def test_is_derivative(self, valid_forward_instrument, valid_option_instrument):
        assert valid_forward_instrument.is_derivative is True
        # For OTHER type, it should be False
        other = HedgeInstrument.create(
            instrument_number="OTH-001",
            instrument_type=InstrumentType.OTHER,
            legal_entity_id=uuid4(),
            notional=Decimal("1000"),
            currency="IDR",
            hedge_type=HedgeType.FAIR_VALUE,
            counterparty="Bank",
        )
        assert other.is_derivative is False

    def test_has_premium(self, valid_option_instrument):
        assert valid_option_instrument.has_premium is True
        assert valid_forward_instrument.has_premium is False

    def test_is_expired(self, valid_forward_instrument):
        # maturity_date = 2024-12-31; today probably before that
        assert valid_forward_instrument.is_expired is False
        # Set as_of after maturity
        future_date = date(2025, 1, 1)
        assert valid_forward_instrument.is_expired(as_of=future_date) is True

    def test_days_to_maturity(self, valid_forward_instrument):
        # maturity_date = 2024-12-31; days from today
        days = valid_forward_instrument.days_to_maturity()
        assert days >= 0
        # as_of after maturity returns 0
        future = date(2025, 1, 1)
        assert valid_forward_instrument.days_to_maturity(as_of=future) == 0

    def test_total_fair_value_change(self, instrument_with_history):
        # instrument_with_history has fair_value 5000, history has first value 5000, so change 0
        assert instrument_with_history.total_fair_value_change == Decimal("0")
        # Add another history with different value
        later = datetime(2024, 7, 1, 12, 0, 0, tzinfo=UTC)
        updated = instrument_with_history.record_fair_value(
            new_fair_value=Decimal("7000"),
            valuation_date=later,
            valuation_method="mark_to_market",
            valued_by="trader1",
        )
        # first value 5000, current 7000, change = 2000
        assert updated.total_fair_value_change == Decimal("2000")


# ============================================================================
# Tests for Serialization (from_dict, to_dict)
# ============================================================================

class TestHedgeInstrumentSerialization:
    def test_to_dict(self, valid_forward_instrument):
        d = valid_forward_instrument.to_dict(include_history=False)
        assert d["id"] == str(valid_forward_instrument.id)
        assert d["instrument_number"] == "FWD-001"
        assert d["status"] == "active"
        assert d["notional"] == "1000000"
        assert "fair_value_history" not in d

    def test_to_dict_with_history(self, instrument_with_history):
        d = instrument_with_history.to_dict(include_history=True)
        assert "fair_value_history" in d
        assert len(d["fair_value_history"]) == 1

    def test_from_dict(self, valid_forward_instrument):
        data = valid_forward_instrument.to_dict(include_history=True)
        restored = HedgeInstrument.from_dict(data)
        assert restored.id == valid_forward_instrument.id
        assert restored.instrument_number == valid_forward_instrument.instrument_number
        assert restored.notional == valid_forward_instrument.notional
        assert restored.status == valid_forward_instrument.status

    def test_from_dict_invalid_type(self):
        data = {
            "id": str(uuid4()),
            "instrument_number": "INS-001",
            "instrument_type": "invalid",
            "legal_entity_id": str(uuid4()),
            "notional": "1000",
            "currency": "IDR",
            "hedge_type": "fair_value",
            "counterparty": "Bank",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        with pytest.raises(HedgeInstrumentError, match="Invalid instrument_type"):
            HedgeInstrument.from_dict(data)


# ============================================================================
# Tests for Entity Basic Methods
# ============================================================================

class TestHedgeInstrumentBasicMethods:
    def test_stamp_create_audit(self, valid_forward_instrument):
        item = valid_forward_instrument.stamp_create_audit(created_by="admin")
        assert item == valid_forward_instrument
        trail = item.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == "admin"
        assert trail[0]["details"]["instrument_number"] == "FWD-001"

    def test_update(self, valid_forward_instrument):
        updated = valid_forward_instrument.update(
            updated_by="admin",
            description="Updated description",
            notional="2000000"
        )
        assert updated.description == "Updated description"
        assert updated.notional == Decimal("2000000")
        assert updated.version == valid_forward_instrument.version + 1
        trail = updated.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "UPDATE"
        assert trail[0]["details"]["changes"]["description"] == "Updated description"

    def test_delete(self, valid_forward_instrument):
        deleted = valid_forward_instrument.delete(deleted_by="admin", reason="Cancel")
        assert deleted.status == InstrumentStatus.CANCELLED
        assert deleted.version == valid_forward_instrument.version + 1
        trail = deleted.audit_trail()
        assert trail[0]["action"] == "DELETE"
        assert trail[0]["details"]["reason"] == "Cancel"

    def test_delete_non_active_raises(self, valid_forward_instrument):
        expired = valid_forward_instrument.expire()
        with pytest.raises(HedgeInstrumentError, match="Cannot delete instrument in status expired"):
            expired.delete("admin")

    def test_restore(self, valid_forward_instrument):
        cancelled = valid_forward_instrument.delete("admin")
        restored = cancelled.restore(restored_by="admin")
        assert restored.status == InstrumentStatus.ACTIVE
        assert restored.version == cancelled.version + 1
        trail = restored.audit_trail()
        assert trail[0]["action"] == "RESTORE"

    def test_restore_active_fails(self, valid_forward_instrument):
        with pytest.raises(HedgeInstrumentError, match="Cannot restore instrument in status active"):
            valid_forward_instrument.restore("admin")

    def test_activate(self, valid_forward_instrument):
        deactivated = valid_forward_instrument.deactivate("admin")
        activated = deactivated.activate("admin2")
        assert activated.status == InstrumentStatus.ACTIVE
        assert activated.version == deactivated.version + 1

    def test_activate_already_active(self, valid_forward_instrument):
        result = valid_forward_instrument.activate("admin")
        assert result == valid_forward_instrument

    def test_deactivate(self, valid_forward_instrument):
        deactivated = valid_forward_instrument.deactivate(deactivated_by="admin", reason="Terminated")
        assert deactivated.status == InstrumentStatus.TERMINATED
        assert deactivated.version == valid_forward_instrument.version + 1
        trail = deactivated.audit_trail()
        assert trail[0]["action"] == "DEACTIVATE"
        assert trail[0]["details"]["reason"] == "Terminated"

    def test_deactivate_non_active_raises(self, valid_forward_instrument):
        expired = valid_forward_instrument.expire()
        with pytest.raises(HedgeInstrumentError, match="Cannot deactivate instrument in status expired"):
            expired.deactivate("admin")

    def test_lock(self, valid_forward_instrument):
        locked = valid_forward_instrument.lock(locked_by="admin", reason="Review")
        assert locked.version == valid_forward_instrument.version + 1
        trail = locked.audit_trail()
        assert trail[0]["action"] == "LOCK"
        assert trail[0]["details"]["reason"] == "Review"

    def test_unlock(self, valid_forward_instrument):
        unlocked = valid_forward_instrument.unlock(unlocked_by="admin")
        assert unlocked.version == valid_forward_instrument.version + 1
        trail = unlocked.audit_trail()
        assert trail[0]["action"] == "UNLOCK"

    def test_validate(self, valid_forward_instrument):
        result = valid_forward_instrument.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid(self):
        instrument = HedgeInstrument(
            id=uuid4(),
            instrument_number="AB",
            instrument_type=InstrumentType.FORWARD,
            legal_entity_id=uuid4(),
            notional=Decimal("-100"),
            currency="IDR",
            hedge_type=HedgeType.FAIR_VALUE,
            counterparty="Bank",
        )
        result = instrument.validate()
        assert result["is_valid"] is False
        assert len(result["errors"]) > 0

    def test_clone(self, valid_forward_instrument):
        cloned = valid_forward_instrument.clone()
        assert cloned.id != valid_forward_instrument.id
        assert cloned.instrument_number == "FWD-001_COPY"
        assert cloned.description == "Cloned from FWD-001"
        assert cloned.status == InstrumentStatus.ACTIVE
        assert cloned.version == 1
        trail = cloned.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "CLONE"
        assert trail[0]["details"]["source"] == str(valid_forward_instrument.id)

    def test_snapshot(self, valid_forward_instrument):
        snap = valid_forward_instrument.snapshot()
        assert snap["instrument_id"] == str(valid_forward_instrument.id)
        assert snap["version"] == 1
        assert snap["status"] == "active"

    def test_get_version(self, valid_forward_instrument):
        assert valid_forward_instrument.get_version() == 1

    def test_audit_trail(self, valid_forward_instrument):
        item = valid_forward_instrument.stamp_create_audit("admin")
        item = item.update("admin", description="Updated")
        trail = item.audit_trail(limit=2)
        assert len(trail) == 2
        assert trail[0]["action"] == "CREATE"
        assert trail[1]["action"] == "UPDATE"

    def test_touch(self, valid_forward_instrument):
        touched = valid_forward_instrument.touch("toucher")
        assert touched.version == valid_forward_instrument.version + 1
        trail = touched.audit_trail()
        assert trail[0]["action"] == "TOUCH"


# ============================================================================
# Tests for Business Methods
# ============================================================================

class TestHedgeInstrumentBusiness:
    def test_designate(self, valid_forward_instrument):
        hedged_item_id = uuid4()
        designated = valid_forward_instrument.designate(hedged_item_id, designated_by="admin")
        assert designated.hedged_item_id == hedged_item_id
        assert designated.version == valid_forward_instrument.version + 1
        trail = designated.audit_trail()
        assert trail[0]["action"] == "DESIGNATE"
        assert trail[0]["details"]["hedged_item_id"] == str(hedged_item_id)

    def test_record_fair_value_fair_value_hedge(self, valid_forward_instrument):
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        updated = valid_forward_instrument.record_fair_value(
            new_fair_value=Decimal("8000"),
            valuation_date=now,
            valuation_method="mark_to_market",
            valued_by="trader1",
            notes="Valuation note",
        )
        assert updated.fair_value == Decimal("8000")
        assert updated.accumulated_oci == Decimal("0")  # For fair value hedge, OCI unchanged
        assert len(updated.fair_value_history) == 1
        assert updated.version == valid_forward_instrument.version + 1
        trail = updated.audit_trail()
        assert trail[0]["action"] == "RECORD_FAIR_VALUE"
        assert trail[0]["details"]["old_fair_value"] == "0"
        assert trail[0]["details"]["new_fair_value"] == "8000"

    def test_record_fair_value_cash_flow_hedge(self, cash_flow_instrument):
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        updated = cash_flow_instrument.record_fair_value(
            new_fair_value=Decimal("3000"),
            valuation_date=now,
            valuation_method="mark_to_market",
            valued_by="trader1",
        )
        assert updated.fair_value == Decimal("3000")
        assert updated.accumulated_oci == Decimal("3000")  # change from 0 to 3000
        assert len(updated.fair_value_history) == 1

    def test_record_oci_reclassification(self, cash_flow_instrument):
        # First record a fair value to build OCI
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        instrument = cash_flow_instrument.record_fair_value(
            new_fair_value=Decimal("5000"),
            valuation_date=now,
            valuation_method="mark_to_market",
            valued_by="trader1",
        )
        # Now reclassify some amount
        reclassified = instrument.record_oci_reclassification(amount=Decimal("2000"), reclassified_by="accountant")
        assert reclassified.accumulated_oci == Decimal("3000")
        assert reclassified.version == instrument.version + 1
        trail = reclassified.audit_trail()
        assert trail[0]["action"] == "RECLASSIFY_OCI"
        assert trail[0]["details"]["amount"] == "2000"

    def test_record_oci_reclassification_exceeds_oci(self, cash_flow_instrument):
        instrument = cash_flow_instrument.record_fair_value(
            new_fair_value=Decimal("5000"),
            valuation_date=datetime.now(UTC),
            valuation_method="method",
            valued_by="user",
        )
        with pytest.raises(HedgeInstrumentError, match="Reclassification amount .* exceeds accumulated OCI"):
            instrument.record_oci_reclassification(amount=Decimal("6000"), reclassified_by="user")

    def test_record_oci_reclassification_non_cash_flow_raises(self, valid_forward_instrument):
        with pytest.raises(HedgeInstrumentError, match="OCI reclassification only applies to cash flow hedges"):
            valid_forward_instrument.record_oci_reclassification(amount=Decimal("100"), reclassified_by="user")

    def test_exercise(self, valid_option_instrument):
        exercised = valid_option_instrument.exercise(exercised_by="trader")
        assert exercised.status == InstrumentStatus.EXERCISED
        assert exercised.version == valid_option_instrument.version + 1
        trail = exercised.audit_trail()
        assert trail[0]["action"] == "EXERCISE"

    def test_exercise_non_option_raises(self, valid_forward_instrument):
        with pytest.raises(HedgeInstrumentError, match="Only options can be exercised"):
            valid_forward_instrument.exercise("trader")

    def test_exercise_non_active_raises(self, valid_option_instrument):
        expired = valid_option_instrument.expire()
        with pytest.raises(HedgeInstrumentError, match="Cannot exercise instrument in status expired"):
            expired.exercise("trader")

    def test_expire(self, valid_forward_instrument):
        expired = valid_forward_instrument.expire()
        assert expired.status == InstrumentStatus.EXPIRED
        assert expired.version == valid_forward_instrument.version + 1
        trail = expired.audit_trail()
        assert trail[0]["action"] == "EXPIRE"
        assert trail[0]["details"]["maturity_date"] == str(valid_forward_instrument.maturity_date)

    def test_expire_already_expired(self, valid_forward_instrument):
        expired = valid_forward_instrument.expire()
        result = expired.expire()
        assert result == expired  # no change

    def test_get_fair_value_at_date(self, instrument_with_history):
        # instrument_with_history has one history at 2024-06-01 with fair value 5000
        date1 = datetime(2024, 5, 1, 12, 0, 0, tzinfo=UTC)  # before history
        assert instrument_with_history.get_fair_value_at_date(date1) is None
        date2 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)  # exactly
        assert instrument_with_history.get_fair_value_at_date(date2) == Decimal("5000")
        date3 = datetime(2024, 7, 1, 12, 0, 0, tzinfo=UTC)  # after
        assert instrument_with_history.get_fair_value_at_date(date3) == Decimal("5000")


# ============================================================================
# Tests for HedgeInstrumentRepository
# ============================================================================

class TestHedgeInstrumentRepository:
    async def test_save_and_get_by_id(self, valid_forward_instrument):
        legal_id = valid_forward_instrument.legal_entity_id
        await HedgeInstrumentRepository.save(valid_forward_instrument, legal_id)
        retrieved = await HedgeInstrumentRepository.get_by_id(valid_forward_instrument.id, legal_id)
        assert retrieved == valid_forward_instrument

    async def test_get_by_number(self, valid_forward_instrument):
        legal_id = valid_forward_instrument.legal_entity_id
        await HedgeInstrumentRepository.save(valid_forward_instrument, legal_id)
        retrieved = await HedgeInstrumentRepository.get_by_number(valid_forward_instrument.instrument_number, legal_id)
        assert retrieved == valid_forward_instrument

    async def test_get_by_legal_entity(self, valid_forward_instrument):
        legal_id = valid_forward_instrument.legal_entity_id
        await HedgeInstrumentRepository.save(valid_forward_instrument, legal_id)
        items = await HedgeInstrumentRepository.get_by_legal_entity(legal_id)
        assert len(items) == 1
        assert items[0] == valid_forward_instrument

    async def test_get_by_type(self, valid_forward_instrument):
        legal_id = valid_forward_instrument.legal_entity_id
        await HedgeInstrumentRepository.save(valid_forward_instrument, legal_id)
        items = await HedgeInstrumentRepository.get_by_type(InstrumentType.FORWARD, legal_id)
        assert len(items) == 1

    async def test_get_active(self, valid_forward_instrument):
        legal_id = valid_forward_instrument.legal_entity_id
        await HedgeInstrumentRepository.save(valid_forward_instrument, legal_id)
        expired = valid_forward_instrument.expire()
        await HedgeInstrumentRepository.save(expired, legal_id)
        active_items = await HedgeInstrumentRepository.get_active(legal_id)
        assert len(active_items) == 1
        assert active_items[0].is_active is True

    async def test_get_all(self, valid_forward_instrument):
        legal_id = valid_forward_instrument.legal_entity_id
        await HedgeInstrumentRepository.save(valid_forward_instrument, legal_id)
        all_items = await HedgeInstrumentRepository.get_all(legal_id)
        assert len(all_items) == 1

    async def test_delete(self, valid_forward_instrument):
        legal_id = valid_forward_instrument.legal_entity_id
        await HedgeInstrumentRepository.save(valid_forward_instrument, legal_id)
        await HedgeInstrumentRepository.delete(valid_forward_instrument.id, legal_id)
        retrieved = await HedgeInstrumentRepository.get_by_id(valid_forward_instrument.id, legal_id)
        assert retrieved is None

    async def test_clear(self, valid_forward_instrument):
        legal_id = valid_forward_instrument.legal_entity_id
        await HedgeInstrumentRepository.save(valid_forward_instrument, legal_id)
        await HedgeInstrumentRepository.clear(legal_id)
        all_items = await HedgeInstrumentRepository.get_all(legal_id)
        assert len(all_items) == 0
