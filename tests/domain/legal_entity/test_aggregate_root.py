# test_aggregate_root.py
# Comprehensive tests for aggregate_root.py

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from domain.legal_entity.aggregate_root import (
    FiscalYearType,
    LegalEntity,
    LegalEntityRepository,
    LegalEntityStatus,
    LegalEntityType,
    create_legal_entity,
)
from domain.legal_entity.company_tax_profile_vo import (
    CompanyTaxProfileVO,
    TaxPaymentMethod,
    TaxRegime,
)
from domain.legal_entity.domain_events import (
    CompanyDissolvedEvent,
    CompanyReactivatedEvent,
    CompanySuspendedEvent,
    DomainEvent,
    TaxProfileUpdatedEvent,
)
from domain.shared_value_objects.npwp_vo import NPWP
from domain.shared_value_objects.percentage_vo import Percentage


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def valid_npwp():
    """Return a valid NPWP."""
    return NPWP("123456789012345")


@pytest.fixture
def valid_tax_profile():
    """Return a valid tax profile."""
    return CompanyTaxProfileVO(
        is_pkp=True,
        tax_regime=TaxRegime.GENERAL,
        corporate_income_tax_rate=Percentage(Decimal("22")),
        vat_rate=Percentage(Decimal("11")),
        vat_collection_method="output",
        income_tax_article="PPh 25",
        tax_bracket="Bracket 1",
        payment_method=TaxPaymentMethod.MONTHLY_INSTALLMENT,
        annual_return_deadline_month=4,
    )


@pytest.fixture
def legal_entity(valid_npwp, valid_tax_profile):
    """Create a valid LegalEntity."""
    return LegalEntity(
        entity_id=uuid4(),
        entity_code="LEGAL-001",
        entity_name="PT Maju Jaya",
        legal_name="PT Maju Jaya Tbk",
        entity_type=LegalEntityType.CORPORATION,
        status=LegalEntityStatus.ACTIVE,
        npwp=valid_npwp,
        tax_profile=valid_tax_profile,
        address="Jl. Sudirman No. 10",
        city="Jakarta Selatan",
        province="DKI Jakarta",
        postal_code="10220",
        country="Indonesia",
        phone="021-12345678",
        email="info@majujaya.co.id",
        website="https://majujaya.co.id",
        fiscal_year_type=FiscalYearType.CALENDAR,
        fiscal_year_start_month=1,
        fiscal_year_start_day=1,
        functional_currency="IDR",
        created_by="system",
    )


@pytest.fixture
def legal_entity_inactive(legal_entity):
    """Return an inactive entity."""
    return legal_entity.deactivate("admin", "Test deactivation")


@pytest.fixture
def legal_entity_suspended(legal_entity):
    """Return a suspended entity."""
    return legal_entity.suspend("admin", "Test suspension")


@pytest.fixture
def legal_entity_dissolved(legal_entity):
    """Return a dissolved entity."""
    suspended = legal_entity.suspend("admin", "Test")
    return suspended.dissolve("admin", datetime.now(UTC), "Test dissolution")


@pytest.fixture
def locked_entity(legal_entity):
    """Return a locked entity."""
    return legal_entity.lock("admin", "Test lock")


# ============================================================================
# Tests for Enums
# ============================================================================

class TestLegalEntityStatus:
    def test_members(self):
        assert LegalEntityStatus.ACTIVE.value == "active"
        assert LegalEntityStatus.INACTIVE.value == "inactive"
        assert LegalEntityStatus.SUSPENDED.value == "suspended"
        assert LegalEntityStatus.DISSOLVED.value == "dissolved"

    def test_from_string(self):
        assert LegalEntityStatus.from_string("active") == LegalEntityStatus.ACTIVE
        assert LegalEntityStatus.from_string("INACTIVE") == LegalEntityStatus.INACTIVE
        assert LegalEntityStatus.from_string("suspended") == LegalEntityStatus.SUSPENDED
        assert LegalEntityStatus.from_string("dissolved") == LegalEntityStatus.DISSOLVED
        assert LegalEntityStatus.from_string("invalid") == LegalEntityStatus.ACTIVE  # default

    def test_can_transition_to(self):
        # ACTIVE -> SUSPENDED, INACTIVE
        assert LegalEntityStatus.ACTIVE.can_transition_to(LegalEntityStatus.SUSPENDED) is True
        assert LegalEntityStatus.ACTIVE.can_transition_to(LegalEntityStatus.INACTIVE) is True
        assert LegalEntityStatus.ACTIVE.can_transition_to(LegalEntityStatus.DISSOLVED) is False

        # INACTIVE -> ACTIVE
        assert LegalEntityStatus.INACTIVE.can_transition_to(LegalEntityStatus.ACTIVE) is True
        assert LegalEntityStatus.INACTIVE.can_transition_to(LegalEntityStatus.DISSOLVED) is False

        # SUSPENDED -> ACTIVE, DISSOLVED
        assert LegalEntityStatus.SUSPENDED.can_transition_to(LegalEntityStatus.ACTIVE) is True
        assert LegalEntityStatus.SUSPENDED.can_transition_to(LegalEntityStatus.DISSOLVED) is True

        # DISSOLVED -> none
        assert LegalEntityStatus.DISSOLVED.can_transition_to(LegalEntityStatus.ACTIVE) is False


class TestLegalEntityType:
    def test_members(self):
        assert LegalEntityType.CORPORATION.value == "corporation"
        assert LegalEntityType.LIMITED.value == "limited"
        assert LegalEntityType.SOLE_PROPRIETORSHIP.value == "sole"
        assert LegalEntityType.PARTNERSHIP.value == "partnership"
        assert LegalEntityType.COOPERATIVE.value == "cooperative"
        assert LegalEntityType.NON_PROFIT.value == "non_profit"
        assert LegalEntityType.GOVERNMENT.value == "government"

    def test_from_string(self):
        assert LegalEntityType.from_string("corporation") == LegalEntityType.CORPORATION
        assert LegalEntityType.from_string("limited") == LegalEntityType.LIMITED
        assert LegalEntityType.from_string("invalid") == LegalEntityType.CORPORATION  # default


class TestFiscalYearType:
    def test_members(self):
        assert FiscalYearType.CALENDAR.value == "calendar"
        assert FiscalYearType.APRIL_MARCH.value == "april_march"
        assert FiscalYearType.JULY_JUNE.value == "july_june"
        assert FiscalYearType.OCTOBER_SEPTEMBER.value == "october_sep"
        assert FiscalYearType.CUSTOM.value == "custom"

    def test_from_string(self):
        assert FiscalYearType.from_string("calendar") == FiscalYearType.CALENDAR
        assert FiscalYearType.from_string("april_march") == FiscalYearType.APRIL_MARCH
        assert FiscalYearType.from_string("invalid") == FiscalYearType.CALENDAR  # default


# ============================================================================
# Tests for LegalEntity - Construction and Validation
# ============================================================================

class TestLegalEntityConstruction:
    def test_construction_valid(self, legal_entity):
        assert legal_entity.entity_code == "LEGAL-001"
        assert legal_entity.entity_name == "PT Maju Jaya"
        assert legal_entity.status == LegalEntityStatus.ACTIVE
        assert legal_entity.version == 1
        assert legal_entity._events == []
        assert legal_entity._audit_trail == []
        assert legal_entity._snapshots == []
        assert legal_entity.is_locked is False

    def test_validation_entity_code_too_short(self, valid_npwp, valid_tax_profile):
        with pytest.raises(ValueError, match="between 3 and 20 characters"):
            LegalEntity(
                entity_id=uuid4(),
                entity_code="AB",
                entity_name="Test",
                legal_name="Test Legal",
                entity_type=LegalEntityType.CORPORATION,
                status=LegalEntityStatus.ACTIVE,
                npwp=valid_npwp,
                tax_profile=valid_tax_profile,
                address="Jl. Merdeka No. 1",
                city="Jakarta",
                province="DKI",
                postal_code="10110",
                country="Indonesia",
                fiscal_year_type=FiscalYearType.CALENDAR,
                fiscal_year_start_month=1,
                fiscal_year_start_day=1,
            )

    def test_validation_entity_code_too_long(self, valid_npwp, valid_tax_profile):
        with pytest.raises(ValueError, match="between 3 and 20 characters"):
            LegalEntity(
                entity_id=uuid4(),
                entity_code="A" * 25,
                entity_name="Test",
                legal_name="Test Legal",
                entity_type=LegalEntityType.CORPORATION,
                status=LegalEntityStatus.ACTIVE,
                npwp=valid_npwp,
                tax_profile=valid_tax_profile,
                address="Jl. Merdeka No. 1",
                city="Jakarta",
                province="DKI",
                postal_code="10110",
                country="Indonesia",
                fiscal_year_type=FiscalYearType.CALENDAR,
                fiscal_year_start_month=1,
                fiscal_year_start_day=1,
            )

    def test_validation_entity_name_too_short(self, valid_npwp, valid_tax_profile):
        with pytest.raises(ValueError, match="at least 2 characters"):
            LegalEntity(
                entity_id=uuid4(),
                entity_code="LEGAL",
                entity_name="A",
                legal_name="Test Legal",
                entity_type=LegalEntityType.CORPORATION,
                status=LegalEntityStatus.ACTIVE,
                npwp=valid_npwp,
                tax_profile=valid_tax_profile,
                address="Jl. Merdeka No. 1",
                city="Jakarta",
                province="DKI",
                postal_code="10110",
                country="Indonesia",
                fiscal_year_type=FiscalYearType.CALENDAR,
                fiscal_year_start_month=1,
                fiscal_year_start_day=1,
            )

    def test_validation_legal_name_too_short(self, valid_npwp, valid_tax_profile):
        with pytest.raises(ValueError, match="at least 2 characters"):
            LegalEntity(
                entity_id=uuid4(),
                entity_code="LEGAL",
                entity_name="Test",
                legal_name="A",
                entity_type=LegalEntityType.CORPORATION,
                status=LegalEntityStatus.ACTIVE,
                npwp=valid_npwp,
                tax_profile=valid_tax_profile,
                address="Jl. Merdeka No. 1",
                city="Jakarta",
                province="DKI",
                postal_code="10110",
                country="Indonesia",
                fiscal_year_type=FiscalYearType.CALENDAR,
                fiscal_year_start_month=1,
                fiscal_year_start_day=1,
            )

    def test_validation_address_too_short(self, valid_npwp, valid_tax_profile):
        with pytest.raises(ValueError, match="at least 5 characters"):
            LegalEntity(
                entity_id=uuid4(),
                entity_code="LEGAL",
                entity_name="Test",
                legal_name="Test Legal",
                entity_type=LegalEntityType.CORPORATION,
                status=LegalEntityStatus.ACTIVE,
                npwp=valid_npwp,
                tax_profile=valid_tax_profile,
                address="Jl.",
                city="Jakarta",
                province="DKI",
                postal_code="10110",
                country="Indonesia",
                fiscal_year_type=FiscalYearType.CALENDAR,
                fiscal_year_start_month=1,
                fiscal_year_start_day=1,
            )

    def test_validation_city_too_short(self, valid_npwp, valid_tax_profile):
        with pytest.raises(ValueError, match="at least 2 characters"):
            LegalEntity(
                entity_id=uuid4(),
                entity_code="LEGAL",
                entity_name="Test",
                legal_name="Test Legal",
                entity_type=LegalEntityType.CORPORATION,
                status=LegalEntityStatus.ACTIVE,
                npwp=valid_npwp,
                tax_profile=valid_tax_profile,
                address="Jl. Merdeka No. 1",
                city="J",
                province="DKI",
                postal_code="10110",
                country="Indonesia",
                fiscal_year_type=FiscalYearType.CALENDAR,
                fiscal_year_start_month=1,
                fiscal_year_start_day=1,
            )

    def test_validation_fiscal_year_start_month_out_of_range(self, valid_npwp, valid_tax_profile):
        with pytest.raises(ValueError, match="between 1 and 12"):
            LegalEntity(
                entity_id=uuid4(),
                entity_code="LEGAL",
                entity_name="Test",
                legal_name="Test Legal",
                entity_type=LegalEntityType.CORPORATION,
                status=LegalEntityStatus.ACTIVE,
                npwp=valid_npwp,
                tax_profile=valid_tax_profile,
                address="Jl. Merdeka No. 1",
                city="Jakarta",
                province="DKI",
                postal_code="10110",
                country="Indonesia",
                fiscal_year_type=FiscalYearType.CALENDAR,
                fiscal_year_start_month=0,
                fiscal_year_start_day=1,
            )

    def test_validation_fiscal_year_start_day_out_of_range(self, valid_npwp, valid_tax_profile):
        with pytest.raises(ValueError, match="between 1 and 31"):
            LegalEntity(
                entity_id=uuid4(),
                entity_code="LEGAL",
                entity_name="Test",
                legal_name="Test Legal",
                entity_type=LegalEntityType.CORPORATION,
                status=LegalEntityStatus.ACTIVE,
                npwp=valid_npwp,
                tax_profile=valid_tax_profile,
                address="Jl. Merdeka No. 1",
                city="Jakarta",
                province="DKI",
                postal_code="10110",
                country="Indonesia",
                fiscal_year_type=FiscalYearType.CALENDAR,
                fiscal_year_start_month=1,
                fiscal_year_start_day=0,
            )

    def test_validation_functional_currency_length(self, valid_npwp, valid_tax_profile):
        with pytest.raises(ValueError, match="ISO 4217"):
            LegalEntity(
                entity_id=uuid4(),
                entity_code="LEGAL",
                entity_name="Test",
                legal_name="Test Legal",
                entity_type=LegalEntityType.CORPORATION,
                status=LegalEntityStatus.ACTIVE,
                npwp=valid_npwp,
                tax_profile=valid_tax_profile,
                address="Jl. Merdeka No. 1",
                city="Jakarta",
                province="DKI",
                postal_code="10110",
                country="Indonesia",
                fiscal_year_type=FiscalYearType.CALENDAR,
                fiscal_year_start_month=1,
                fiscal_year_start_day=1,
                functional_currency="ID",
            )

    def test_validation_parent_self(self, valid_npwp, valid_tax_profile):
        entity_id = uuid4()
        with pytest.raises(ValueError, match="cannot be its own parent"):
            LegalEntity(
                entity_id=entity_id,
                entity_code="LEGAL",
                entity_name="Test",
                legal_name="Test Legal",
                entity_type=LegalEntityType.CORPORATION,
                status=LegalEntityStatus.ACTIVE,
                npwp=valid_npwp,
                tax_profile=valid_tax_profile,
                address="Jl. Merdeka No. 1",
                city="Jakarta",
                province="DKI",
                postal_code="10110",
                country="Indonesia",
                fiscal_year_type=FiscalYearType.CALENDAR,
                fiscal_year_start_month=1,
                fiscal_year_start_day=1,
                parent_entity_id=entity_id,
            )

    def test_validation_version(self, valid_npwp, valid_tax_profile):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            LegalEntity(
                entity_id=uuid4(),
                entity_code="LEGAL",
                entity_name="Test",
                legal_name="Test Legal",
                entity_type=LegalEntityType.CORPORATION,
                status=LegalEntityStatus.ACTIVE,
                npwp=valid_npwp,
                tax_profile=valid_tax_profile,
                address="Jl. Merdeka No. 1",
                city="Jakarta",
                province="DKI",
                postal_code="10110",
                country="Indonesia",
                fiscal_year_type=FiscalYearType.CALENDAR,
                fiscal_year_start_month=1,
                fiscal_year_start_day=1,
                version=0,
            )


# ============================================================================
# Tests for Properties
# ============================================================================

class TestLegalEntityProperties:
    def test_id(self, legal_entity):
        assert legal_entity.id == legal_entity.entity_id

    def test_is_active(self, legal_entity, legal_entity_inactive):
        assert legal_entity.is_active is True
        assert legal_entity_inactive.is_active is False

    def test_is_suspended(self, legal_entity, legal_entity_suspended):
        assert legal_entity.is_suspended is False
        assert legal_entity_suspended.is_suspended is True

    def test_is_dissolved(self, legal_entity, legal_entity_dissolved):
        assert legal_entity.is_dissolved is False
        assert legal_entity_dissolved.is_dissolved is True

    def test_is_locked(self, legal_entity, locked_entity):
        assert legal_entity.is_locked is False
        assert locked_entity.is_locked is True


# ============================================================================
# Tests for Event Management
# ============================================================================

class TestLegalEntityEvents:
    def test_register_event(self, legal_entity):
        event = MagicMock(spec=DomainEvent)
        event.event_type = MagicMock()
        event.event_type.value = "test"
        legal_entity.register_event(event)
        assert len(legal_entity._events) == 1
        assert legal_entity._events[0] == event
        # Check audit trail
        assert any(e["action"] == "event_added" for e in legal_entity._audit_trail)

    def test_clear_events(self, legal_entity):
        event = MagicMock(spec=DomainEvent)
        event.event_type = MagicMock()
        event.event_type.value = "test"
        legal_entity._add_event(event)
        assert len(legal_entity._events) == 1
        legal_entity.clear_events()
        assert len(legal_entity._events) == 0
        assert any(e["action"] == "events_cleared" for e in legal_entity._audit_trail)

    def test_get_events(self, legal_entity):
        event = MagicMock(spec=DomainEvent)
        event.event_type = MagicMock()
        event.event_type.value = "test"
        legal_entity._add_event(event)
        events = legal_entity.get_events()
        assert len(events) == 1
        assert events is not legal_entity._events

    def test_pop_events(self, legal_entity):
        event = MagicMock(spec=DomainEvent)
        event.event_type = MagicMock()
        event.event_type.value = "test"
        legal_entity._add_event(event)
        popped = legal_entity.pop_events()
        assert len(popped) == 1
        assert len(legal_entity._events) == 0

    def test_pull_events(self, legal_entity):
        event = MagicMock(spec=DomainEvent)
        event.event_type = MagicMock()
        event.event_type.value = "test"
        legal_entity._add_event(event)
        pulled = legal_entity.pull_events()
        assert len(pulled) == 1
        assert len(legal_entity._events) == 0


# ============================================================================
# Tests for Audit Trail
# ============================================================================

class TestLegalEntityAudit:
    def test_audit_trail(self, legal_entity):
        legal_entity._record_audit_trail("test", {"key": "value"})
        trail = legal_entity.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "test"
        assert trail[0]["details"] == {"key": "value"}
        assert trail[0]["version"] == legal_entity.version

    def test_clear_audit_trail(self, legal_entity):
        legal_entity._record_audit_trail("test", {})
        assert len(legal_entity._audit_trail) == 1
        legal_entity.clear_audit_trail()
        assert len(legal_entity._audit_trail) == 0


# ============================================================================
# Tests for Snapshot
# ============================================================================

class TestLegalEntitySnapshot:
    def test_snapshot(self, legal_entity):
        snap = legal_entity.snapshot()
        assert snap["aggregate_id"] == str(legal_entity.entity_id)
        assert snap["aggregate_type"] == "LegalEntity"
        assert snap["version"] == legal_entity.version
        assert snap["state"]["entity_code"] == legal_entity.entity_code
        assert snap["state"]["entity_name"] == legal_entity.entity_name
        assert "hash" in snap
        assert len(legal_entity._snapshots) == 1
        assert legal_entity._snapshots[0] == snap

    def test_restore_from_snapshot(self, legal_entity):
        snap = legal_entity.snapshot()
        new_entity = LegalEntity(
            entity_id=legal_entity.entity_id,
            entity_code=legal_entity.entity_code,
            entity_name=legal_entity.entity_name,
            legal_name=legal_entity.legal_name,
            entity_type=legal_entity.entity_type,
            status=legal_entity.status,
            npwp=legal_entity.npwp,
            tax_profile=legal_entity.tax_profile,
            address=legal_entity.address,
            city=legal_entity.city,
            province=legal_entity.province,
            postal_code=legal_entity.postal_code,
            country=legal_entity.country,
            phone=legal_entity.phone,
            email=legal_entity.email,
            website=legal_entity.website,
            fiscal_year_type=legal_entity.fiscal_year_type,
            fiscal_year_start_month=legal_entity.fiscal_year_start_month,
            fiscal_year_start_day=legal_entity.fiscal_year_start_day,
            functional_currency=legal_entity.functional_currency,
            parent_entity_id=legal_entity.parent_entity_id,
            consolidation_group=legal_entity.consolidation_group,
            established_date=legal_entity.established_date,
            created_at=legal_entity.created_at,
            updated_at=legal_entity.updated_at,
            created_by=legal_entity.created_by,
            version=legal_entity.version,
        )
        new_entity.restore_from_snapshot(snap)
        assert any(e["action"] == "restored_from_snapshot" for e in new_entity._audit_trail)

    def test_restore_from_snapshot_wrong_id(self, legal_entity):
        snap = legal_entity.snapshot()
        new_entity = LegalEntity(
            entity_id=uuid4(),
            entity_code="OTHER",
            entity_name="Other",
            legal_name="Other Legal",
            entity_type=LegalEntityType.CORPORATION,
            status=LegalEntityStatus.ACTIVE,
            npwp=legal_entity.npwp,
            tax_profile=legal_entity.tax_profile,
            address=legal_entity.address,
            city=legal_entity.city,
            province=legal_entity.province,
            postal_code=legal_entity.postal_code,
            country=legal_entity.country,
            phone=legal_entity.phone,
            email=legal_entity.email,
            website=legal_entity.website,
            fiscal_year_type=legal_entity.fiscal_year_type,
            fiscal_year_start_month=legal_entity.fiscal_year_start_month,
            fiscal_year_start_day=legal_entity.fiscal_year_start_day,
            functional_currency=legal_entity.functional_currency,
        )
        with pytest.raises(ValueError, match="Snapshot belongs to different aggregate"):
            new_entity.restore_from_snapshot(snap)


# ============================================================================
# Tests for Lock / Unlock
# ============================================================================

class TestLegalEntityLock:
    def test_lock(self, legal_entity):
        locked = legal_entity.lock("admin", "Test lock")
        assert locked.is_locked is True
        assert locked._locked_by == "admin"
        assert locked._locked_at is not None
        assert any(e["action"] == "locked" for e in locked._audit_trail)

    def test_lock_already_locked(self, locked_entity):
        with pytest.raises(ValueError, match="already locked"):
            locked_entity.lock("admin2", "Another")

    def test_unlock(self, locked_entity):
        unlocked = locked_entity.unlock("admin")
        assert unlocked.is_locked is False
        assert unlocked._locked_by is None
        assert unlocked._locked_at is None
        assert any(e["action"] == "unlocked" for e in unlocked._audit_trail)

    def test_unlock_not_locked(self, legal_entity):
        with pytest.raises(ValueError, match="not locked"):
            legal_entity.unlock("admin")

    def test_unlock_wrong_user(self, locked_entity):
        with pytest.raises(ValueError, match="locked by admin, cannot unlock by user2"):
            locked_entity.unlock("user2")


# ============================================================================
# Tests for Status Transitions
# ============================================================================

class TestLegalEntityStatusTransitions:
    def test_activate(self, legal_entity_inactive):
        activated = legal_entity_inactive.activate("admin", "Activation reason")
        assert activated.status == LegalEntityStatus.ACTIVE
        assert activated.version == legal_entity_inactive.version + 1
        assert any(e["action"] == "activated" for e in activated._audit_trail)

    def test_activate_from_suspended(self, legal_entity_suspended):
        activated = legal_entity_suspended.activate("admin", "Reactivate")
        assert activated.status == LegalEntityStatus.ACTIVE

    def test_activate_from_active_raises(self, legal_entity):
        with pytest.raises(ValueError, match="Cannot activate entity with status active"):
            legal_entity.activate("admin")

    def test_activate_from_dissolved_raises(self, legal_entity_dissolved):
        with pytest.raises(ValueError, match="Cannot activate entity with status dissolved"):
            legal_entity_dissolved.activate("admin")

    def test_activate_locked_raises(self, locked_entity):
        with pytest.raises(ValueError, match="Cannot activate locked legal entity"):
            locked_entity.activate("admin")

    def test_deactivate(self, legal_entity):
        deactivated = legal_entity.deactivate("admin", "Deactivation reason")
        assert deactivated.status == LegalEntityStatus.INACTIVE
        assert deactivated.version == legal_entity.version + 1
        assert any(e["action"] == "deactivated" for e in deactivated._audit_trail)

    def test_deactivate_from_inactive_raises(self, legal_entity_inactive):
        with pytest.raises(ValueError, match="Cannot deactivate entity with status inactive"):
            legal_entity_inactive.deactivate("admin")

    def test_deactivate_locked_raises(self, locked_entity):
        with pytest.raises(ValueError, match="Cannot deactivate locked legal entity"):
            locked_entity.deactivate("admin")

    def test_suspend(self, legal_entity):
        suspended = legal_entity.suspend("admin", "Suspension reason")
        assert suspended.status == LegalEntityStatus.SUSPENDED
        assert suspended.version == legal_entity.version + 1
        # Check event
        events = suspended.get_events()
        assert any(isinstance(e, CompanySuspendedEvent) for e in events)
        assert any(e["action"] == "suspended" for e in suspended._audit_trail)

    def test_suspend_already_suspended(self, legal_entity_suspended):
        with pytest.raises(ValueError, match="already suspended"):
            legal_entity_suspended.suspend("admin", "Again")

    def test_suspend_dissolved_raises(self, legal_entity_dissolved):
        with pytest.raises(ValueError, match="Cannot suspend a dissolved entity"):
            legal_entity_dissolved.suspend("admin", "Test")

    def test_suspend_locked_raises(self, locked_entity):
        with pytest.raises(ValueError, match="Cannot suspend locked legal entity"):
            locked_entity.suspend("admin", "Test")

    def test_reactivate(self, legal_entity_suspended):
        reactivated = legal_entity_suspended.reactivate("admin", "Reactivate reason")
        assert reactivated.status == LegalEntityStatus.ACTIVE
        assert reactivated.version == legal_entity_suspended.version + 1
        events = reactivated.get_events()
        assert any(isinstance(e, CompanyReactivatedEvent) for e in events)
        assert any(e["action"] == "reactivated" for e in reactivated._audit_trail)

    def test_reactivate_from_active_raises(self, legal_entity):
        with pytest.raises(ValueError, match="Cannot reactivate entity with status active"):
            legal_entity.reactivate("admin", "Test")

    def test_reactivate_locked_raises(self, locked_entity):
        with pytest.raises(ValueError, match="Cannot reactivate locked legal entity"):
            locked_entity.reactivate("admin", "Test")

    def test_dissolve(self, legal_entity_suspended):
        effective = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        dissolved = legal_entity_suspended.dissolve("admin", effective, "Dissolution reason")
        assert dissolved.status == LegalEntityStatus.DISSOLVED
        assert dissolved.version == legal_entity_suspended.version + 1
        events = dissolved.get_events()
        assert any(isinstance(e, CompanyDissolvedEvent) for e in events)
        assert any(e["action"] == "dissolved" for e in dissolved._audit_trail)

    def test_dissolve_from_active_raises(self, legal_entity):
        with pytest.raises(ValueError, match="Entity must be suspended before dissolution"):
            legal_entity.dissolve("admin", datetime.now(UTC), "Test")

    def test_dissolve_from_dissolved_raises(self, legal_entity_dissolved):
        with pytest.raises(ValueError, match="Entity already dissolved"):
            legal_entity_dissolved.dissolve("admin", datetime.now(UTC), "Test")

    def test_dissolve_locked_raises(self, locked_entity):
        with pytest.raises(ValueError, match="Cannot dissolve locked legal entity"):
            locked_entity.dissolve("admin", datetime.now(UTC), "Test")


# ============================================================================
# Tests for Tax Profile Update
# ============================================================================

class TestLegalEntityTaxProfile:
    def test_update_tax_profile(self, legal_entity, valid_tax_profile):
        new_profile = CompanyTaxProfileVO(
            is_pkp=True,
            tax_regime=TaxRegime.GENERAL,
            corporate_income_tax_rate=Percentage(Decimal("25")),
            vat_rate=Percentage(Decimal("11")),
        )
        updated = legal_entity.update_tax_profile(new_profile, "admin")
        assert updated.tax_profile == new_profile
        assert updated.version == legal_entity.version + 1
        events = updated.get_events()
        assert any(isinstance(e, TaxProfileUpdatedEvent) for e in events)
        assert any(e["action"] == "tax_profile_updated" for e in updated._audit_trail)

    def test_update_tax_profile_locked(self, locked_entity, valid_tax_profile):
        with pytest.raises(ValueError, match="Cannot update tax profile of locked legal entity"):
            locked_entity.update_tax_profile(valid_tax_profile, "admin")


# ============================================================================
# Tests for Basic Attribute Updates
# ============================================================================

class TestLegalEntityBasicUpdates:
    def test_rename(self, legal_entity):
        updated = legal_entity.rename("PT Maju Jaya Baru", "admin")
        assert updated.entity_name == "PT Maju Jaya Baru"
        assert updated.version == legal_entity.version + 1
        assert any(e["action"] == "renamed" for e in updated._audit_trail)

    def test_rename_empty_name(self, legal_entity):
        with pytest.raises(ValueError, match="at least 2 characters"):
            legal_entity.rename("", "admin")

    def test_rename_locked(self, locked_entity):
        with pytest.raises(ValueError, match="Cannot rename locked legal entity"):
            locked_entity.rename("New", "admin")

    def test_update_address(self, legal_entity):
        updated = legal_entity.update_address(
            address="Jl. Thamrin No. 20",
            city="Jakarta Pusat",
            province="DKI Jakarta",
            postal_code="10350",
            country="Indonesia",
            updated_by="admin",
        )
        assert updated.address == "Jl. Thamrin No. 20"
        assert updated.city == "Jakarta Pusat"
        assert updated.province == "DKI Jakarta"
        assert updated.postal_code == "10350"
        assert updated.version == legal_entity.version + 1
        assert any(e["action"] == "address_updated" for e in updated._audit_trail)

    def test_update_address_invalid(self, legal_entity):
        with pytest.raises(ValueError, match="at least 5 characters"):
            legal_entity.update_address(
                address="Jl.",
                city="Jakarta",
                province="DKI",
                postal_code="10110",
                country="Indonesia",
                updated_by="admin",
            )
        with pytest.raises(ValueError, match="at least 2 characters"):
            legal_entity.update_address(
                address="Jl. Merdeka No. 1",
                city="J",
                province="DKI",
                postal_code="10110",
                country="Indonesia",
                updated_by="admin",
            )

    def test_update_address_locked(self, locked_entity):
        with pytest.raises(ValueError, match="Cannot update address of locked legal entity"):
            locked_entity.update_address(
                address="New",
                city="Jakarta",
                province="DKI",
                postal_code="10110",
                country="Indonesia",
                updated_by="admin",
            )

    def test_update_contact(self, legal_entity):
        updated = legal_entity.update_contact(
            phone="021-87654321",
            email="new@company.com",
            website="https://new.company.com",
            updated_by="admin",
        )
        assert updated.phone == "021-87654321"
        assert updated.email == "new@company.com"
        assert updated.website == "https://new.company.com"
        assert updated.version == legal_entity.version + 1
        assert any(e["action"] == "contact_updated" for e in updated._audit_trail)

    def test_update_contact_none(self, legal_entity):
        updated = legal_entity.update_contact(None, None, None, "admin")
        assert updated.phone is None
        assert updated.email is None
        assert updated.website is None

    def test_update_contact_invalid_email(self, legal_entity):
        with pytest.raises(ValueError, match="Invalid email format"):
            legal_entity.update_contact("phone", "invalid", "website", "admin")

    def test_update_contact_locked(self, locked_entity):
        with pytest.raises(ValueError, match="Cannot update contact of locked legal entity"):
            locked_entity.update_contact("phone", "email", "website", "admin")


# ============================================================================
# Tests for Hierarchy Management
# ============================================================================

class TestLegalEntityHierarchy:
    def test_add_child(self, legal_entity):
        child_id = uuid4()
        result = legal_entity.add_child(child_id, "admin")
        # add_child returns self (no state change)
        assert result is legal_entity
        assert any(e["action"] == "child_added" and e["details"]["child_id"] == str(child_id)
                   for e in result._audit_trail)

    def test_add_child_locked(self, locked_entity):
        with pytest.raises(ValueError, match="Cannot add child to locked legal entity"):
            locked_entity.add_child(uuid4(), "admin")

    def test_remove_child(self, legal_entity):
        child_id = uuid4()
        result = legal_entity.remove_child(child_id, "admin")
        assert result is legal_entity
        assert any(e["action"] == "child_removed" and e["details"]["child_id"] == str(child_id)
                   for e in result._audit_trail)

    def test_remove_child_locked(self, locked_entity):
        with pytest.raises(ValueError, match="Cannot remove child from locked legal entity"):
            locked_entity.remove_child(uuid4(), "admin")


# ============================================================================
# Tests for Validation
# ============================================================================

class TestLegalEntityValidation:
    def test_validate(self, legal_entity):
        errors = legal_entity.validate()
        assert errors == []

    def test_validate_invalid(self, legal_entity):
        # Create an invalid entity by bypassing constructor validation? We can't easily.
        # We'll use a valid entity and then modify a field? But frozen dataclass? It's not frozen.
        # We can create a new entity with invalid data and then call validate.
        invalid = LegalEntity(
            entity_id=uuid4(),
            entity_code="AB",  # too short
            entity_name="Test",
            legal_name="Test Legal",
            entity_type=LegalEntityType.CORPORATION,
            status=LegalEntityStatus.ACTIVE,
            npwp=legal_entity.npwp,
            tax_profile=legal_entity.tax_profile,
            address=legal_entity.address,
            city=legal_entity.city,
            province=legal_entity.province,
            postal_code=legal_entity.postal_code,
            country=legal_entity.country,
            phone=legal_entity.phone,
            email=legal_entity.email,
            website=legal_entity.website,
            fiscal_year_type=legal_entity.fiscal_year_type,
            fiscal_year_start_month=legal_entity.fiscal_year_start_month,
            fiscal_year_start_day=legal_entity.fiscal_year_start_day,
            functional_currency=legal_entity.functional_currency,
        )
        errors = invalid.validate()
        assert len(errors) > 0
        assert any("Entity code must be between 3 and 20 characters" in e for e in errors)


# ============================================================================
# Tests for Touch and Clone
# ============================================================================

class TestLegalEntityTouchClone:
    def test_touch(self, legal_entity):
        old_updated = legal_entity.updated_at
        touched = legal_entity.touch("admin")
        assert touched.updated_at > old_updated
        assert touched.version == legal_entity.version  # version does NOT increment on touch
        assert any(e["action"] == "touched" for e in touched._audit_trail)

    def test_clone(self, legal_entity):
        cloned = legal_entity.clone()
        assert cloned.entity_id != legal_entity.entity_id
        assert cloned.entity_code == f"COPY-{legal_entity.entity_code}"
        assert cloned.entity_name == f"Copy of {legal_entity.entity_name}"
        assert cloned.status == LegalEntityStatus.INACTIVE
        assert cloned.version == 1
        assert cloned.created_by == "system"
        assert any(e["action"] == "cloned" for e in cloned._audit_trail)


# ============================================================================
# Tests for Serialization
# ============================================================================

class TestLegalEntitySerialization:
    def test_to_dict(self, legal_entity):
        d = legal_entity.to_dict()
        assert d["entity_id"] == str(legal_entity.entity_id)
        assert d["entity_code"] == "LEGAL-001"
        assert d["entity_name"] == "PT Maju Jaya"
        assert d["status"] == "active"
        assert d["version"] == legal_entity.version
        assert "tax_profile" in d
        assert d["tax_profile"]["is_pkp"] is True

    def test_from_dict(self, legal_entity):
        data = legal_entity.to_dict()
        restored = LegalEntity.from_dict(data)
        assert restored.entity_id == legal_entity.entity_id
        assert restored.entity_code == legal_entity.entity_code
        assert restored.entity_name == legal_entity.entity_name
        assert restored.status == legal_entity.status
        assert restored.tax_profile == legal_entity.tax_profile
        assert restored.version == legal_entity.version

    def test_from_dict_missing_fields(self):
        data = {
            "entity_id": str(uuid4()),
            "entity_code": "LEGAL",
            "entity_name": "Test",
            "legal_name": "Test Legal",
            "entity_type": "corporation",
            "status": "active",
            "npwp": "123456789012345",
            "tax_profile": {
                "is_pkp": True,
                "tax_regime": "general",
                "corporate_income_tax_rate": "22",
                "vat_rate": "11",
            },
            "address": "Jl. Merdeka",
            "city": "Jakarta",
            "province": "DKI",
            "postal_code": "10110",
            "country": "Indonesia",
            "fiscal_year_type": "calendar",
            "fiscal_year_start_month": 1,
            "fiscal_year_start_day": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        restored = LegalEntity.from_dict(data)
        assert restored.functional_currency == "IDR"
        assert restored.payment_method == TaxPaymentMethod.MONTHLY_INSTALLMENT
        assert restored.annual_return_deadline_month == 4


# ============================================================================
# Tests for Repository (Protocol)
# ============================================================================

class TestLegalEntityRepository:
    def test_repository_is_protocol(self):
        # The repository is a Protocol, so it's not instantiable with missing methods.
        # We can check that it defines the expected methods.
        assert hasattr(LegalEntityRepository, "get_by_id")
        assert hasattr(LegalEntityRepository, "get_by_code")
        assert hasattr(LegalEntityRepository, "get_by_npwp")
        assert hasattr(LegalEntityRepository, "list_by_status")
        assert hasattr(LegalEntityRepository, "save")
        assert hasattr(LegalEntityRepository, "delete")


# ============================================================================
# Tests for Factory Method
# ============================================================================

class TestCreateLegalEntity:
    def test_create_legal_entity(self, valid_npwp, valid_tax_profile):
        created = create_legal_entity(
            entity_code="LEGAL-002",
            entity_name="PT Contoh",
            legal_name="PT Contoh Tbk",
            entity_type=LegalEntityType.CORPORATION,
            npwp=valid_npwp,
            tax_profile=valid_tax_profile,
            address="Jl. Merdeka No. 1",
            city="Jakarta",
            province="DKI Jakarta",
            postal_code="10110",
            country="Indonesia",
            created_by="admin",
            phone="021-12345",
            email="info@contoh.com",
            website="https://contoh.com",
            fiscal_year_type=FiscalYearType.CALENDAR,
            fiscal_year_start_month=1,
            fiscal_year_start_day=1,
            functional_currency="USD",
            parent_entity_id=None,
            consolidation_group="Group1",
            established_date=datetime(2010, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        assert created.entity_code == "LEGAL-002"
        assert created.entity_name == "PT Contoh"
        assert created.status == LegalEntityStatus.ACTIVE
        assert created.version == 1
        assert created.functional_currency == "USD"
        assert created.consolidation_group == "Group1"
        assert created.established_date == datetime(2010, 1, 1, 0, 0, 0, tzinfo=UTC)

    def test_create_legal_entity_with_parent(self, valid_npwp, valid_tax_profile):
        parent_id = uuid4()
        created = create_legal_entity(
            entity_code="LEGAL-003",
            entity_name="Child",
            legal_name="Child Legal",
            entity_type=LegalEntityType.CORPORATION,
            npwp=valid_npwp,
            tax_profile=valid_tax_profile,
            address="Jl. Anak",
            city="Jakarta",
            province="DKI",
            postal_code="10110",
            country="Indonesia",
            created_by="admin",
            parent_entity_id=parent_id,
        )
        assert created.parent_entity_id == parent_id