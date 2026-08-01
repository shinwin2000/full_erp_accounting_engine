# test_aggregate_root.py
# Comprehensive tests for domain/hedge/aggregate_root.py

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.hedge.aggregate_root import (
    EffectivenessTestResult,
    HedgeAdjustment,
    HedgeAlreadyDiscontinuedError,
    HedgeEffectivenessStatus,
    HedgeError,
    HedgeNotFoundError,
    HedgeRelationship,
    HedgeRelationshipAggregate,
    HedgeRepository,
    HedgeStatus,
    HedgeType,
    InvalidEffectivenessThresholdError,
    InvalidHedgeTypeError,
)


# -------------------- Enum Tests --------------------
class TestHedgeType:
    def test_members(self):
        assert HedgeType.FAIR_VALUE.value == "fair_value"
        assert HedgeType.CASH_FLOW.value == "cash_flow"
        assert HedgeType.NET_INVESTMENT.value == "net_investment"

    def test_display_name(self):
        assert HedgeType.FAIR_VALUE.display_name() == "Lindung Nilai Nilai Wajar"
        assert HedgeType.CASH_FLOW.display_name() == "Lindung Nilai Arus Kas"
        assert HedgeType.NET_INVESTMENT.display_name() == "Lindung Nilai Investasi Bersih"

    def test_affects_pl_directly(self):
        assert HedgeType.FAIR_VALUE.affects_pl_directly() is True
        assert HedgeType.CASH_FLOW.affects_pl_directly() is False
        assert HedgeType.NET_INVESTMENT.affects_pl_directly() is False

    def test_affects_oci(self):
        assert HedgeType.FAIR_VALUE.affects_oci() is False
        assert HedgeType.CASH_FLOW.affects_oci() is True
        assert HedgeType.NET_INVESTMENT.affects_oci() is True


class TestHedgeStatus:
    def test_members(self):
        assert HedgeStatus.DESIGNATED.value == "designated"
        assert HedgeStatus.ACTIVE.value == "active"
        assert HedgeStatus.INEFFECTIVE.value == "ineffective"
        assert HedgeStatus.DISCONTINUED.value == "discontinued"
        assert HedgeStatus.PROSPECTIVE.value == "prospective"
        assert HedgeStatus.CANCELLED.value == "cancelled"

    def test_is_active(self):
        assert HedgeStatus.DESIGNATED.is_active() is True
        assert HedgeStatus.ACTIVE.is_active() is True
        assert HedgeStatus.INEFFECTIVE.is_active() is False
        assert HedgeStatus.DISCONTINUED.is_active() is False
        assert HedgeStatus.PROSPECTIVE.is_active() is False
        assert HedgeStatus.CANCELLED.is_active() is False

    def test_can_test(self):
        assert HedgeStatus.ACTIVE.can_test() is True
        assert HedgeStatus.DESIGNATED.can_test() is True
        assert HedgeStatus.INEFFECTIVE.can_test() is False
        assert HedgeStatus.DISCONTINUED.can_test() is False
        assert HedgeStatus.PROSPECTIVE.can_test() is False
        assert HedgeStatus.CANCELLED.can_test() is False

    def test_display_name(self):
        assert HedgeStatus.DESIGNATED.display_name() == "Ditunjuk"
        assert HedgeStatus.ACTIVE.display_name() == "Aktif"
        assert HedgeStatus.INEFFECTIVE.display_name() == "Tidak Efektif"
        assert HedgeStatus.DISCONTINUED.display_name() == "Dihentikan"
        assert HedgeStatus.PROSPECTIVE.display_name() == "Prospektif"
        assert HedgeStatus.CANCELLED.display_name() == "Dibatalkan"

    def test_from_string(self):
        assert HedgeStatus.from_string("active") == HedgeStatus.ACTIVE
        assert HedgeStatus.from_string("DESIGNATED") == HedgeStatus.DESIGNATED
        assert HedgeStatus.from_string("unknown") is None


class TestHedgeEffectivenessStatus:
    def test_members(self):
        assert HedgeEffectivenessStatus.EFFECTIVE.value == "effective"
        assert HedgeEffectivenessStatus.INEFFECTIVE.value == "ineffective"
        assert HedgeEffectivenessStatus.HIGHLY_EFFECTIVE.value == "highly_effective"
        assert HedgeEffectivenessStatus.PENDING.value == "pending"

    def test_display_name(self):
        assert HedgeEffectivenessStatus.EFFECTIVE.display_name() == "Efektif"
        assert HedgeEffectivenessStatus.INEFFECTIVE.display_name() == "Tidak Efektif"
        assert HedgeEffectivenessStatus.HIGHLY_EFFECTIVE.display_name() == "Sangat Efektif"
        assert HedgeEffectivenessStatus.PENDING.display_name() == "Menunggu"


# -------------------- Exception Tests --------------------
class TestHedgeError:
    def test_exception(self):
        with pytest.raises(HedgeError):
            raise HedgeError("test")


class TestInvalidHedgeTypeError:
    def test_exception(self):
        with pytest.raises(InvalidHedgeTypeError):
            raise InvalidHedgeTypeError("invalid")


class TestInvalidEffectivenessThresholdError:
    def test_exception(self):
        with pytest.raises(InvalidEffectivenessThresholdError):
            raise InvalidEffectivenessThresholdError("threshold")


class TestHedgeAlreadyDiscontinuedError:
    def test_exception(self):
        with pytest.raises(HedgeAlreadyDiscontinuedError):
            raise HedgeAlreadyDiscontinuedError("already discontinued")


class TestHedgeNotFoundError:
    def test_exception(self):
        with pytest.raises(HedgeNotFoundError):
            raise HedgeNotFoundError("not found")


# -------------------- Value Objects Tests --------------------
class TestEffectivenessTestResult:
    def test_construction(self):
        test_id = uuid4()
        hedge_id = uuid4()
        now = datetime.now(UTC)
        result = EffectivenessTestResult(
            test_id=test_id,
            hedge_id=hedge_id,
            test_date=now,
            test_type="prospective",
            is_effective=True,
            ratio=Decimal("1.05"),
            variance=Decimal("0.05"),
            cumulative_hedge_change=Decimal("1000"),
            cumulative_hedged_change=Decimal("950"),
            message="OK",
            tested_by="tester",
            created_at=now,
        )
        assert result.test_id == test_id
        assert result.hedge_id == hedge_id
        assert result.test_date == now
        assert result.test_type == "prospective"
        assert result.is_effective is True
        assert result.ratio == Decimal("1.05")
        assert result.variance == Decimal("0.05")
        assert result.cumulative_hedge_change == Decimal("1000")
        assert result.cumulative_hedged_change == Decimal("950")
        assert result.message == "OK"
        assert result.tested_by == "tester"
        assert result.created_at == now

    def test_post_init_tz_aware(self):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        result = EffectivenessTestResult(
            test_id=uuid4(),
            hedge_id=uuid4(),
            test_date=naive,
            test_type="retrospective",
            is_effective=False,
            ratio=Decimal("0.9"),
            variance=Decimal("0.1"),
            cumulative_hedge_change=Decimal("0"),
            cumulative_hedged_change=Decimal("0"),
            message="",
            tested_by="tester",
        )
        assert result.test_date.tzinfo is not None
        assert result.created_at.tzinfo is not None

    def test_to_dict(self):
        test_id = uuid4()
        hedge_id = uuid4()
        now = datetime.now(UTC)
        result = EffectivenessTestResult(
            test_id=test_id,
            hedge_id=hedge_id,
            test_date=now,
            test_type="prospective",
            is_effective=True,
            ratio=Decimal("1.05"),
            variance=Decimal("0.05"),
            cumulative_hedge_change=Decimal("1000"),
            cumulative_hedged_change=Decimal("950"),
            message="OK",
            tested_by="tester",
            created_at=now,
        )
        d = result.to_dict()
        assert d["test_id"] == str(test_id)
        assert d["hedge_id"] == str(hedge_id)
        assert d["test_date"] == now.isoformat()
        assert d["test_type"] == "prospective"
        assert d["is_effective"] is True
        assert d["ratio"] == "1.05"
        assert d["variance"] == "0.05"
        assert d["cumulative_hedge_change"] == "1000"
        assert d["cumulative_hedged_change"] == "950"
        assert d["message"] == "OK"
        assert d["tested_by"] == "tester"
        assert d["created_at"] == now.isoformat()

    def test_from_dict(self):
        test_id = uuid4()
        hedge_id = uuid4()
        now = datetime.now(UTC)
        data = {
            "test_id": str(test_id),
            "hedge_id": str(hedge_id),
            "test_date": now.isoformat(),
            "test_type": "prospective",
            "is_effective": True,
            "ratio": "1.05",
            "variance": "0.05",
            "cumulative_hedge_change": "1000",
            "cumulative_hedged_change": "950",
            "message": "OK",
            "tested_by": "tester",
            "created_at": now.isoformat(),
        }
        result = EffectivenessTestResult.from_dict(data)
        assert result.test_id == test_id
        assert result.hedge_id == hedge_id
        assert result.test_date == now
        assert result.test_type == "prospective"
        assert result.is_effective is True
        assert result.ratio == Decimal("1.05")
        assert result.variance == Decimal("0.05")
        assert result.cumulative_hedge_change == Decimal("1000")
        assert result.cumulative_hedged_change == Decimal("950")
        assert result.message == "OK"
        assert result.tested_by == "tester"
        assert result.created_at == now


class TestHedgeAdjustment:
    def test_construction(self):
        adj_id = uuid4()
        hedge_id = uuid4()
        now = datetime.now(UTC)
        adjustment = HedgeAdjustment(
            adjustment_id=adj_id,
            hedge_id=hedge_id,
            adjustment_date=now,
            adjustment_amount=Decimal("500"),
            ineffectiveness=Decimal("50"),
            adjustment_type="fair_value",
            description="Test adjustment",
            recorded_by="accountant",
            created_at=now,
        )
        assert adjustment.adjustment_id == adj_id
        assert adjustment.hedge_id == hedge_id
        assert adjustment.adjustment_date == now
        assert adjustment.adjustment_amount == Decimal("500")
        assert adjustment.ineffectiveness == Decimal("50")
        assert adjustment.adjustment_type == "fair_value"
        assert adjustment.description == "Test adjustment"
        assert adjustment.recorded_by == "accountant"
        assert adjustment.created_at == now

    def test_post_init_tz_aware(self):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        adjustment = HedgeAdjustment(
            adjustment_id=uuid4(),
            hedge_id=uuid4(),
            adjustment_date=naive,
            adjustment_amount=Decimal("0"),
            ineffectiveness=Decimal("0"),
            adjustment_type="cash_flow",
            description="",
            recorded_by="test",
        )
        assert adjustment.adjustment_date.tzinfo is not None
        assert adjustment.created_at.tzinfo is not None

    def test_to_dict(self):
        adj_id = uuid4()
        hedge_id = uuid4()
        now = datetime.now(UTC)
        adjustment = HedgeAdjustment(
            adjustment_id=adj_id,
            hedge_id=hedge_id,
            adjustment_date=now,
            adjustment_amount=Decimal("500"),
            ineffectiveness=Decimal("50"),
            adjustment_type="fair_value",
            description="Test",
            recorded_by="accountant",
            created_at=now,
        )
        d = adjustment.to_dict()
        assert d["adjustment_id"] == str(adj_id)
        assert d["hedge_id"] == str(hedge_id)
        assert d["adjustment_date"] == now.isoformat()
        assert d["adjustment_amount"] == "500"
        assert d["ineffectiveness"] == "50"
        assert d["adjustment_type"] == "fair_value"
        assert d["description"] == "Test"
        assert d["recorded_by"] == "accountant"
        assert d["created_at"] == now.isoformat()

    def test_from_dict(self):
        adj_id = uuid4()
        hedge_id = uuid4()
        now = datetime.now(UTC)
        data = {
            "adjustment_id": str(adj_id),
            "hedge_id": str(hedge_id),
            "adjustment_date": now.isoformat(),
            "adjustment_amount": "500",
            "ineffectiveness": "50",
            "adjustment_type": "fair_value",
            "description": "Test",
            "recorded_by": "accountant",
            "created_at": now.isoformat(),
        }
        adjustment = HedgeAdjustment.from_dict(data)
        assert adjustment.adjustment_id == adj_id
        assert adjustment.hedge_id == hedge_id
        assert adjustment.adjustment_date == now
        assert adjustment.adjustment_amount == Decimal("500")
        assert adjustment.ineffectiveness == Decimal("50")
        assert adjustment.adjustment_type == "fair_value"
        assert adjustment.description == "Test"
        assert adjustment.recorded_by == "accountant"
        assert adjustment.created_at == now


# -------------------- HedgeRelationship Tests --------------------
class TestHedgeRelationship:
    def test_designate_factory(self):
        legal_entity_id = uuid4()
        hedge_instrument_id = uuid4()
        hedged_item_id = uuid4()
        hedge = HedgeRelationship.designate(
            hedge_number="HEDGE-001",
            legal_entity_id=legal_entity_id,
            hedge_type=HedgeType.CASH_FLOW,
            designation_date=date.today(),
            description="Test hedge",
            hedge_instrument_id=hedge_instrument_id,
            hedged_item_id=hedged_item_id,
            risk_components=["interest_rate"],
            effectiveness_threshold_lower=Decimal("0.80"),
            effectiveness_threshold_upper=Decimal("1.25"),
            created_by=uuid4(),
        )
        assert hedge.hedge_number == "HEDGE-001"
        assert hedge.legal_entity_id == legal_entity_id
        assert hedge.hedge_type == HedgeType.CASH_FLOW
        assert hedge.designation_date == date.today()
        assert hedge.description == "Test hedge"
        assert hedge.hedge_instrument_id == hedge_instrument_id
        assert hedge.hedged_item_id == hedged_item_id
        assert hedge.status == HedgeStatus.DESIGNATED
        assert hedge.risk_components == ["interest_rate"]
        assert hedge.effectiveness_threshold_lower == Decimal("0.80")
        assert hedge.effectiveness_threshold_upper == Decimal("1.25")
        assert hedge.effectiveness_status == HedgeEffectivenessStatus.PENDING
        assert hedge.version == 1

    def test_validate_hedge_number_too_short(self):
        with pytest.raises(HedgeError, match="at least 3 characters"):
            HedgeRelationship(
                id=uuid4(),
                hedge_number="AB",
                legal_entity_id=uuid4(),
                hedge_type=HedgeType.FAIR_VALUE,
                designation_date=date.today(),
                description="",
                hedge_instrument_id=uuid4(),
                hedged_item_id=uuid4(),
            )

    def test_validate_invalid_hedge_type(self):
        with pytest.raises(InvalidHedgeTypeError):
            HedgeRelationship(
                id=uuid4(),
                hedge_number="H001",
                legal_entity_id=uuid4(),
                hedge_type="invalid",  # type ignore
                designation_date=date.today(),
                description="",
                hedge_instrument_id=uuid4(),
                hedged_item_id=uuid4(),
            )

    def test_validate_lower_threshold_out_of_range(self):
        with pytest.raises(InvalidEffectivenessThresholdError, match="between 0 and 1"):
            HedgeRelationship(
                id=uuid4(),
                hedge_number="H001",
                legal_entity_id=uuid4(),
                hedge_type=HedgeType.FAIR_VALUE,
                designation_date=date.today(),
                description="",
                hedge_instrument_id=uuid4(),
                hedged_item_id=uuid4(),
                effectiveness_threshold_lower=Decimal("0"),
            )

    def test_validate_upper_threshold_not_greater_than_1(self):
        with pytest.raises(InvalidEffectivenessThresholdError, match="greater than 1"):
            HedgeRelationship(
                id=uuid4(),
                hedge_number="H001",
                legal_entity_id=uuid4(),
                hedge_type=HedgeType.FAIR_VALUE,
                designation_date=date.today(),
                description="",
                hedge_instrument_id=uuid4(),
                hedged_item_id=uuid4(),
                effectiveness_threshold_upper=Decimal("1"),
            )

    def test_validate_lower_greater_than_upper(self):
        with pytest.raises(InvalidEffectivenessThresholdError, match="cannot exceed"):
            HedgeRelationship(
                id=uuid4(),
                hedge_number="H001",
                legal_entity_id=uuid4(),
                hedge_type=HedgeType.FAIR_VALUE,
                designation_date=date.today(),
                description="",
                hedge_instrument_id=uuid4(),
                hedged_item_id=uuid4(),
                effectiveness_threshold_lower=Decimal("1.2"),
                effectiveness_threshold_upper=Decimal("1.0"),
            )

    def test_validate_designation_date_future(self):
        future_date = date.today() + timedelta(days=1)
        with pytest.raises(HedgeError, match="cannot be in the future"):
            HedgeRelationship(
                id=uuid4(),
                hedge_number="H001",
                legal_entity_id=uuid4(),
                hedge_type=HedgeType.FAIR_VALUE,
                designation_date=future_date,
                description="",
                hedge_instrument_id=uuid4(),
                hedged_item_id=uuid4(),
            )

    def test_validate_discontinued_date_before_designation(self):
        with pytest.raises(HedgeError, match="cannot be before designation date"):
            HedgeRelationship(
                id=uuid4(),
                hedge_number="H001",
                legal_entity_id=uuid4(),
                hedge_type=HedgeType.FAIR_VALUE,
                designation_date=date.today(),
                description="",
                hedge_instrument_id=uuid4(),
                hedged_item_id=uuid4(),
                discontinued_date=date.today() - timedelta(days=1),
            )

    def test_validate_negative_accumulated_ineffectiveness(self):
        with pytest.raises(HedgeError, match="cannot be negative"):
            HedgeRelationship(
                id=uuid4(),
                hedge_number="H001",
                legal_entity_id=uuid4(),
                hedge_type=HedgeType.FAIR_VALUE,
                designation_date=date.today(),
                description="",
                hedge_instrument_id=uuid4(),
                hedged_item_id=uuid4(),
                accumulated_ineffectiveness=Decimal("-1"),
            )

    def test_properties(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        # Initially status DESIGNATED, active True, can_be_tested True
        assert hedge.is_active is True
        assert hedge.is_designated is True
        assert hedge.is_discontinued is False
        assert hedge.is_cancelled is False
        assert hedge.can_be_tested is True
        assert hedge.effectiveness_range_display == "[0.80 - 1.25]"
        assert hedge.total_adjustment == Decimal("0")
        assert hedge.total_ineffectiveness == Decimal("0")

        # Test is_effective with ratio argument
        assert hedge.is_effective(ratio=Decimal("1.0")) is True
        assert hedge.is_effective(ratio=Decimal("0.79")) is False
        assert hedge.is_effective(ratio=Decimal("1.26")) is False

    def test_to_dict_and_from_dict_roundtrip(self):
        original = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.CASH_FLOW,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
            risk_components=["currency"],
            effectiveness_threshold_lower=Decimal("0.85"),
            effectiveness_threshold_upper=Decimal("1.15"),
        )
        # Add a test result and adjustment to history to ensure they are included
        # We'll just test to_dict with include_history=False first
        d = original.to_dict(include_history=False)
        assert d["hedge_number"] == "H001"
        assert d["hedge_type"] == "cash_flow"
        # Now include history (empty lists)
        d_full = original.to_dict(include_history=True)
        assert d_full["test_history"] == []
        assert d_full["adjustments"] == []

        # From dict roundtrip
        reconstructed = HedgeRelationship.from_dict(d)
        assert reconstructed.hedge_number == original.hedge_number
        assert reconstructed.hedge_type == original.hedge_type
        assert reconstructed.legal_entity_id == original.legal_entity_id
        assert reconstructed.designation_date == original.designation_date
        assert reconstructed.effectiveness_threshold_lower == original.effectiveness_threshold_lower
        assert reconstructed.effectiveness_threshold_upper == original.effectiveness_threshold_upper


# -------------------- HedgeRelationshipAggregate Tests --------------------
class TestHedgeRelationshipAggregate:
    def test_construction(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        assert agg.hedge == hedge
        assert agg.id == hedge.id
        assert agg.version == hedge.version
        assert agg.get_events() == []
        # Snapshot should have been taken
        assert len(agg._snapshots) == 1

    def test_register_event_and_pull_events(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        event1 = {"type": "test1"}
        event2 = {"type": "test2"}
        agg.register_event(event1)
        agg.register_event(event2)
        assert agg.get_events() == [event1, event2]
        pulled = agg.pull_events()
        assert pulled == [event1, event2]
        assert agg.get_events() == []
        agg.clear_events()  # no effect

    def test_apply_replay_reconstruct(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        events = [{"type": "e1"}, {"type": "e2"}]
        agg.apply(events[0])
        agg.apply(events[1])
        assert agg.get_events() == events
        pulled = agg.pull_events()
        assert pulled == events
        # replay
        agg.replay(events)
        assert agg.get_events() == events
        # reconstruct (alias)
        agg.clear_events()
        agg.reconstruct(events)
        assert agg.get_events() == events

    def test_snapshot_method(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        snap = agg.snapshot()
        assert snap["version"] == 1
        assert snap["hedge_id"] == str(hedge.id)
        assert snap["hedge_number"] == "H001"
        assert snap["status"] == "designated"
        assert snap["effectiveness_status"] == "pending"

    def test_domain_events_property(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        assert agg.domain_events == []
        event = {"type": "test"}
        agg.register_event(event)
        assert agg.domain_events == [event]

    def test_pop_events(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        event = {"type": "test"}
        agg.register_event(event)
        popped = agg.pop_events()
        assert popped == [event]
        assert agg.get_events() == []

    # ---- Entity Dasar Methods ----
    def test_create(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.create("creator")
        # Audit trail should have an entry
        assert len(agg._audit_trail) == 1
        assert agg._audit_trail[-1]["action"] == "CREATE"
        assert agg._audit_trail[-1]["performed_by"] == "creator"

    def test_update(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.update("updater", description="Updated description")
        assert agg.hedge.description == "Updated description"
        assert agg.version == 2
        # Audit trail
        assert agg._audit_trail[-1]["action"] == "UPDATE"

    def test_delete_calls_cancel(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.delete("deleter", "delete reason")
        assert agg.hedge.status == HedgeStatus.CANCELLED
        assert agg.hedge.cancellation_reason == "delete reason"

    def test_restore(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.cancel("canceller", "cancel reason")
        agg.restore("restorer")
        assert agg.hedge.status == HedgeStatus.DESIGNATED
        assert agg.hedge.cancellation_date is None
        assert agg.hedge.cancellation_reason is None

    def test_restore_fails_if_not_cancelled(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        with pytest.raises(HedgeError, match="Cannot restore hedge in status designated"):
            agg.restore("restorer")

    def test_activate(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.activate("activator")
        assert agg.hedge.status == HedgeStatus.ACTIVE
        assert agg.version == 2

    def test_activate_already_active(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.activate("activator")
        agg.activate("activator2")  # should just return self
        assert agg.hedge.status == HedgeStatus.ACTIVE

    def test_activate_fails_if_cannot_test(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.cancel("canceller", "reason")
        with pytest.raises(HedgeError, match="Cannot activate hedge in status cancelled"):
            agg.activate("activator")

    def test_deactivate_calls_discontinue(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.deactivate("deactivator", "deactivate reason")
        assert agg.hedge.status == HedgeStatus.DISCONTINUED

    def test_lock_and_unlock(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.lock("locker", "lock reason")
        assert agg.version == 2
        # lock doesn't change status
        agg.unlock("unlocker")
        assert agg.version == 3

    def test_validate(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        result = agg.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_clone(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        cloned = agg.clone()
        assert cloned.hedge.hedge_number == "H001_COPY"
        assert cloned.hedge.id != hedge.id
        assert cloned.hedge.status == HedgeStatus.DESIGNATED
        assert cloned.hedge.version == 1

    def test_version_method(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        assert agg.version() == 1

    def test_audit_trail(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.create("creator")
        agg.update("updater", description="new")
        trail = agg.audit_trail(limit=10)
        assert len(trail) == 2
        assert trail[0]["action"] == "CREATE"
        assert trail[1]["action"] == "UPDATE"

    def test_touch(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.touch("toucher")
        assert agg.version == 2
        assert agg._audit_trail[-1]["action"] == "TOUCH"

    # ---- Aggregate Root Methods ----
    def test_add_child_not_implemented(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        with pytest.raises(NotImplementedError):
            agg.add_child("child", "creator")

    def test_remove_child_not_implemented(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        with pytest.raises(NotImplementedError):
            agg.remove_child(uuid4(), "remover")

    def test_can_post(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        assert agg.can_post() is False  # not active yet
        agg.activate("activator")
        assert agg.can_post() is True

    def test_post(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.post("poster")
        assert agg._audit_trail[-1]["action"] == "POST"

    def test_can_approve(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        # designated and admin => can approve
        assert agg.can_approve("admin") is True
        assert agg.can_approve("finance_manager") is True
        assert agg.can_approve("user") is False
        agg.activate("activator")
        assert agg.can_approve("admin") is True

    def test_approve(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.approve("approver")
        assert agg._audit_trail[-1]["action"] == "APPROVE"

    def test_can_reject(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        assert agg.can_reject() is True
        agg.activate("activator")
        assert agg.can_reject() is False

    def test_reject(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.reject("rejecter", "bad hedge")
        assert agg._audit_trail[-1]["action"] == "REJECT"

    def test_can_cancel(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        assert agg.can_cancel() is True
        agg.cancel("canceller", "reason")
        assert agg.can_cancel() is False

    def test_cancel(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.cancel("canceller", "cancel reason")
        assert agg.hedge.status == HedgeStatus.CANCELLED
        assert agg.hedge.cancellation_reason == "cancel reason"
        assert agg.hedge.cancellation_date == date.today()
        # Event registered
        events = agg.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "HedgeDiscontinued"

    def test_cancel_fails_if_already_discontinued(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.discontinue("discontinuer", "reason")
        with pytest.raises(HedgeError, match="Cannot cancel hedge in status discontinued"):
            agg.cancel("canceller", "reason")

    def test_can_reverse(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        assert agg.can_reverse() is False

    def test_reverse_not_implemented(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        with pytest.raises(NotImplementedError):
            agg.reverse("reverser", "reason")

    def test_can_close(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        assert agg.can_close() is False
        agg.discontinue("discontinuer", "reason")
        assert agg.can_close() is True

    def test_close(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.discontinue("discontinuer", "reason")
        agg.close("closer", "close reason")
        assert agg._audit_trail[-1]["action"] == "CLOSE"

    def test_close_fails_if_cannot_close(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        with pytest.raises(HedgeError, match="Cannot close hedge in status designated"):
            agg.close("closer", "reason")

    def test_can_reopen(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        assert agg.can_reopen() is False
        agg.discontinue("discontinuer", "reason")
        assert agg.can_reopen() is True

    def test_reopen(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.discontinue("discontinuer", "reason")
        agg.reopen("reopener", "reopen reason")
        assert agg.hedge.status == HedgeStatus.ACTIVE
        assert agg.hedge.discontinued_date is None
        assert agg.hedge.discontinued_reason is None

    def test_reopen_fails_if_cannot_reopen(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        with pytest.raises(HedgeError, match="Cannot reopen hedge in status designated"):
            agg.reopen("reopener", "reason")

    def test_can_archive(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        assert agg.can_archive() is False
        agg.discontinue("discontinuer", "reason")
        assert agg.can_archive() is True

    def test_archive(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.discontinue("discontinuer", "reason")
        agg.archive("archiver", "archive reason")
        assert agg._audit_trail[-1]["action"] == "ARCHIVE"

    def test_archive_fails_if_cannot_archive(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        with pytest.raises(HedgeError, match="Cannot archive hedge in status designated"):
            agg.archive("archiver")

    def test_can_unarchive(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        assert agg.can_unarchive() is True

    def test_unarchive(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.unarchive("unarchiver")
        assert agg._audit_trail[-1]["action"] == "UNARCHIVE"

    # ---- Business Methods ----
    def test_record_effectiveness_test(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.activate("activator")
        agg.record_effectiveness_test(
            test_type="prospective",
            is_effective=True,
            ratio=Decimal("1.05"),
            cumulative_hedge_change=Decimal("1000"),
            cumulative_hedged_change=Decimal("950"),
            tested_by="tester",
            message="Good",
        )
        assert len(agg.hedge.test_history) == 1
        test = agg.hedge.test_history[0]
        assert test.test_type == "prospective"
        assert test.is_effective is True
        assert test.ratio == Decimal("1.05")
        assert agg.hedge.effectiveness_status == HedgeEffectivenessStatus.EFFECTIVE
        assert agg.hedge.last_test_ratio == Decimal("1.05")
        assert agg.hedge.last_test_is_effective is True
        assert agg.version == 3  # initial 1, activate 2, test 3
        # Event registered
        events = agg.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "HedgeEffectivenessTested"

    def test_record_effectiveness_test_fails_if_cannot_test(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        # Not activated yet
        with pytest.raises(HedgeError, match="Cannot test hedge in status designated"):
            agg.record_effectiveness_test(
                test_type="prospective",
                is_effective=True,
                ratio=Decimal("1.0"),
                cumulative_hedge_change=Decimal("0"),
                cumulative_hedged_change=Decimal("0"),
                tested_by="tester",
            )

    def test_record_adjustment(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.activate("activator")
        agg.record_adjustment(
            adjustment_amount=Decimal("500"),
            ineffectiveness=Decimal("50"),
            adjustment_type="fair_value",
            description="Test adj",
            recorded_by="accountant",
        )
        assert len(agg.hedge.adjustments) == 1
        adj = agg.hedge.adjustments[0]
        assert adj.adjustment_amount == Decimal("500")
        assert adj.ineffectiveness == Decimal("50")
        assert adj.adjustment_type == "fair_value"
        assert agg.hedge.accumulated_ineffectiveness == Decimal("50")
        assert agg.version == 3
        events = agg.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "HedgeFairValueAdjusted"

    def test_record_adjustment_fails_if_not_active(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        with pytest.raises(HedgeError, match="Cannot record adjustment for hedge in status designated"):
            agg.record_adjustment(
                adjustment_amount=Decimal("0"),
                ineffectiveness=Decimal("0"),
                adjustment_type="fair_value",
                description="",
                recorded_by="test",
            )

    def test_discontinue(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.discontinue("discontinuer", "discontinue reason")
        assert agg.hedge.status == HedgeStatus.DISCONTINUED
        assert agg.hedge.discontinued_date == date.today()
        assert agg.hedge.discontinued_reason == "discontinue reason"
        events = agg.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "HedgeDiscontinued"

    def test_discontinue_already_discontinued(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.discontinue("discontinuer", "reason1")
        # Second discontinue should just return self
        agg.discontinue("discontinuer2", "reason2")
        assert agg.hedge.status == HedgeStatus.DISCONTINUED
        # No new event
        events = agg.get_events()
        # Only the first event remains (the second discontinue didn't add)
        assert len(events) == 1

    def test_get_test_history(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.activate("activator")
        # Add multiple tests
        for i in range(3):
            agg.record_effectiveness_test(
                test_type="retrospective",
                is_effective=True,
                ratio=Decimal("1.0"),
                cumulative_hedge_change=Decimal("0"),
                cumulative_hedged_change=Decimal("0"),
                tested_by="tester",
                message=f"test {i}",
            )
        history = agg.get_test_history(limit=2)
        assert len(history) == 2
        assert history[0].message == "test 1"
        assert history[1].message == "test 2"

    def test_get_adjustments(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.activate("activator")
        for i in range(3):
            agg.record_adjustment(
                adjustment_amount=Decimal("100"),
                ineffectiveness=Decimal("10"),
                adjustment_type="fair_value",
                description=f"adj {i}",
                recorded_by="accountant",
            )
        adjustments = agg.get_adjustments(limit=2)
        assert len(adjustments) == 2
        assert adjustments[0].description == "adj 1"
        assert adjustments[1].description == "adj 2"

    def test_get_summary(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        agg.activate("activator")
        agg.record_adjustment(
            adjustment_amount=Decimal("100"),
            ineffectiveness=Decimal("10"),
            adjustment_type="fair_value",
            description="adj",
            recorded_by="accountant",
        )
        summary = agg.get_summary()
        assert summary["hedge_number"] == "H001"
        assert summary["status"] == "active"
        assert summary["total_adjustment"] == "100"
        assert summary["accumulated_ineffectiveness"] == "10"
        assert summary["total_tests"] == 0
        assert summary["is_active"] is True


# -------------------- HedgeRepository Tests --------------------
class TestHedgeRepository:
    @pytest.mark.asyncio
    async def test_save_and_get_by_id(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H001",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        await HedgeRepository.save(agg)
        retrieved = await HedgeRepository.get_by_id(hedge.id)
        assert retrieved is not None
        assert retrieved.hedge.id == hedge.id
        # Clean up
        await HedgeRepository.clear()

    @pytest.mark.asyncio
    async def test_get_by_number(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H002",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        await HedgeRepository.save(agg)
        retrieved = await HedgeRepository.get_by_number("H002")
        assert retrieved is not None
        assert retrieved.hedge.hedge_number == "H002"
        await HedgeRepository.clear()

    @pytest.mark.asyncio
    async def test_get_by_legal_entity(self):
        legal_entity_id = uuid4()
        hedge1 = HedgeRelationship.designate(
            hedge_number="H003",
            legal_entity_id=legal_entity_id,
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test1",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        hedge2 = HedgeRelationship.designate(
            hedge_number="H004",
            legal_entity_id=legal_entity_id,
            hedge_type=HedgeType.CASH_FLOW,
            designation_date=date.today(),
            description="Test2",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg1 = HedgeRelationshipAggregate(hedge1)
        agg2 = HedgeRelationshipAggregate(hedge2)
        await HedgeRepository.save(agg1)
        await HedgeRepository.save(agg2)
        results = await HedgeRepository.get_by_legal_entity(legal_entity_id)
        assert len(results) == 2
        assert {a.hedge.hedge_number for a in results} == {"H003", "H004"}
        await HedgeRepository.clear()

    @pytest.mark.asyncio
    async def test_get_by_status(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H005",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        await HedgeRepository.save(agg)
        results = await HedgeRepository.get_by_status(HedgeStatus.DESIGNATED)
        assert len(results) == 1
        assert results[0].hedge.hedge_number == "H005"
        await HedgeRepository.clear()

    @pytest.mark.asyncio
    async def test_get_all(self):
        hedge1 = HedgeRelationship.designate(
            hedge_number="H006",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        hedge2 = HedgeRelationship.designate(
            hedge_number="H007",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.CASH_FLOW,
            designation_date=date.today(),
            description="Test2",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        await HedgeRepository.save(HedgeRelationshipAggregate(hedge1))
        await HedgeRepository.save(HedgeRelationshipAggregate(hedge2))
        all_aggs = await HedgeRepository.get_all()
        assert len(all_aggs) == 2
        await HedgeRepository.clear()

    @pytest.mark.asyncio
    async def test_delete(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H008",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        await HedgeRepository.save(agg)
        assert await HedgeRepository.exists(hedge.id) is True
        await HedgeRepository.delete(hedge.id)
        assert await HedgeRepository.exists(hedge.id) is False
        await HedgeRepository.clear()

    @pytest.mark.asyncio
    async def test_exists(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H009",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        agg = HedgeRelationshipAggregate(hedge)
        await HedgeRepository.save(agg)
        assert await HedgeRepository.exists(hedge.id) is True
        assert await HedgeRepository.exists(uuid4()) is False
        await HedgeRepository.clear()

    @pytest.mark.asyncio
    async def test_count(self):
        await HedgeRepository.clear()
        assert await HedgeRepository.count() == 0
        hedge = HedgeRelationship.designate(
            hedge_number="H010",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        await HedgeRepository.save(HedgeRelationshipAggregate(hedge))
        assert await HedgeRepository.count() == 1
        await HedgeRepository.clear()

    @pytest.mark.asyncio
    async def test_list(self):
        await HedgeRepository.clear()
        hedges = []
        for i in range(5):
            hedge = HedgeRelationship.designate(
                hedge_number=f"H{i:03d}",
                legal_entity_id=uuid4(),
                hedge_type=HedgeType.FAIR_VALUE,
                designation_date=date.today(),
                description="Test",
                hedge_instrument_id=uuid4(),
                hedged_item_id=uuid4(),
            )
            hedges.append(hedge)
            await HedgeRepository.save(HedgeRelationshipAggregate(hedge))
        results = await HedgeRepository.list(limit=2, offset=1)
        assert len(results) == 2
        await HedgeRepository.clear()

    @pytest.mark.asyncio
    async def test_clear(self):
        hedge = HedgeRelationship.designate(
            hedge_number="H011",
            legal_entity_id=uuid4(),
            hedge_type=HedgeType.FAIR_VALUE,
            designation_date=date.today(),
            description="Test",
            hedge_instrument_id=uuid4(),
            hedged_item_id=uuid4(),
        )
        await HedgeRepository.save(HedgeRelationshipAggregate(hedge))
        assert await HedgeRepository.count() == 1
        await HedgeRepository.clear()
        assert await HedgeRepository.count() == 0
