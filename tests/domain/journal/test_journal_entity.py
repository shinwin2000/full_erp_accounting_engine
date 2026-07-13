"""
Tests for domain/journal/journal_entity.py

Covers:
- JournalStatus.from_string / can_transition_to
- JournalType.from_string
- JournalLine (entity-level dataclass): validation, net_amount, side, to/from_dict
- JournalEntity: construction validation, properties, can_* helpers, audit trail,
  update_metadata, update_totals, to_dict/from_dict round trip
- JournalEntityRepository: unimplemented protocol methods
- JournalEntry alias identity
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.journal.journal_entity import (
    JournalEntity,
    JournalEntityRepository,
    JournalEntry,
    JournalLine,
    JournalStateMachine,
    JournalStatus,
    JournalType,
)


# ============================================================================
# JournalStatus
# ============================================================================


class TestJournalStatus:
    def test_from_string_valid(self):
        assert JournalStatus.from_string("posted") == JournalStatus.POSTED
        assert JournalStatus.from_string("POSTED") == JournalStatus.POSTED

    def test_from_string_unknown_falls_back_to_draft(self):
        assert JournalStatus.from_string("bogus") == JournalStatus.DRAFT

    def test_can_transition_to_uses_state_machine(self):
        assert JournalStatus.DRAFT.can_transition_to(JournalStatus.SUBMITTED) is True
        assert JournalStatus.DRAFT.can_transition_to(JournalStatus.POSTED) is False


# ============================================================================
# JournalType
# ============================================================================


class TestJournalType:
    def test_from_string_valid(self):
        assert JournalType.from_string("adjusting") == JournalType.ADJUSTING
        assert JournalType.from_string("PAYROLL") == JournalType.PAYROLL

    def test_from_string_unknown_falls_back_to_general(self):
        assert JournalType.from_string("nope") == JournalType.GENERAL


# ============================================================================
# JournalLine (entity level)
# ============================================================================


class TestJournalLineEntity:
    def test_valid_debit_line(self):
        line = JournalLine(account_code="1000", account_name="Cash", debit_amount=Decimal("100"))
        assert line.net_amount == Decimal("100")
        assert line.side == "debit"

    def test_valid_credit_line(self):
        line = JournalLine(account_code="4000", account_name="Revenue", credit_amount=Decimal("100"))
        assert line.net_amount == Decimal("-100")
        assert line.side == "credit"

    def test_negative_debit_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            JournalLine(account_code="1000", debit_amount=Decimal("-1"))

    def test_negative_credit_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            JournalLine(account_code="1000", credit_amount=Decimal("-1"))

    def test_both_zero_raises(self):
        with pytest.raises(ValueError, match="Either debit or credit must be"):
            JournalLine(account_code="1000")

    def test_both_nonzero_raises(self):
        with pytest.raises(ValueError, match="cannot have both"):
            JournalLine(account_code="1000", debit_amount=Decimal("1"), credit_amount=Decimal("1"))

    def test_to_dict_and_from_dict_round_trip(self):
        line = JournalLine(
            account_code="1000", account_name="Cash", debit_amount=Decimal("55.5"),
            currency="USD", tax_rate=Decimal("11"), tax_amount=Decimal("6.1"),
        )
        d = line.to_dict()
        restored = JournalLine.from_dict(d)
        assert restored.account_code == "1000"
        assert restored.debit_amount == Decimal("55.5")
        assert restored.currency == "USD"

    def test_from_dict_defaults(self):
        restored = JournalLine.from_dict({"account_code": "2000", "credit_amount": "10"})
        assert restored.debit_amount == Decimal("0")
        assert restored.credit_amount == Decimal("10")
        assert restored.currency == "IDR"

    def test_line_id_auto_generated(self):
        line = JournalLine(account_code="1000", debit_amount=Decimal("1"))
        assert line.id is not None


# ============================================================================
# JournalEntity — fixtures
# ============================================================================


def make_entity(**overrides):
    now = datetime.now(UTC)
    defaults = dict(
        journal_id=uuid4(),
        journal_number="JRN-001",
        journal_type=JournalType.GENERAL,
        transaction_date=now,
        description="Test journal entity",
        legal_entity_id=uuid4(),
        status=JournalStatus.DRAFT,
        created_by="user_a",
        created_at=now,
        updated_at=now,
        total_debit=Decimal("100"),
        total_credit=Decimal("100"),
    )
    defaults.update(overrides)
    return JournalEntity(**defaults)


# ============================================================================
# JournalEntity — construction validation
# ============================================================================


class TestJournalEntityConstruction:
    def test_valid_construction(self):
        entity = make_entity()
        assert entity.is_balanced is True

    def test_short_journal_number_raises(self):
        with pytest.raises(ValueError, match="Journal number must be at least 3"):
            make_entity(journal_number="JR")

    def test_short_description_raises(self):
        with pytest.raises(ValueError, match="Description must be at least 2"):
            make_entity(description="x")

    def test_negative_total_debit_raises(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            make_entity(total_debit=Decimal("-1"), total_credit=Decimal("0"))

    def test_negative_total_credit_raises(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            make_entity(total_debit=Decimal("0"), total_credit=Decimal("-1"))

    def test_unbalanced_totals_raise(self):
        with pytest.raises(ValueError, match="not balanced"):
            make_entity(total_debit=Decimal("100"), total_credit=Decimal("50"))

    def test_within_tolerance_is_allowed(self):
        entity = make_entity(total_debit=Decimal("100.005"), total_credit=Decimal("100.000"))
        assert entity.is_balanced is True


# ============================================================================
# JournalEntity — properties
# ============================================================================


class TestJournalEntityProperties:
    def test_id_property_matches_journal_id(self):
        entity = make_entity()
        assert entity.id == entity.journal_id

    def test_difference_property(self):
        entity = make_entity(total_debit=Decimal("100"), total_credit=Decimal("100"))
        assert entity.difference == Decimal("0")

    def test_is_posted_property(self):
        entity = make_entity(status=JournalStatus.POSTED)
        assert entity.is_posted is True
        assert entity.is_draft is False

    def test_is_draft_property(self):
        entity = make_entity(status=JournalStatus.DRAFT)
        assert entity.is_draft is True

    def test_is_locked_default_false(self):
        entity = make_entity()
        assert entity.is_locked is False

    def test_is_editable_true_for_draft(self):
        entity = make_entity(status=JournalStatus.DRAFT)
        assert entity.is_editable is True

    def test_is_editable_false_for_posted(self):
        entity = make_entity(status=JournalStatus.POSTED)
        assert entity.is_editable is False

    def test_is_editable_false_when_locked_even_if_draft(self):
        entity = make_entity(status=JournalStatus.DRAFT, _is_locked=True)
        assert entity.is_editable is False


# ============================================================================
# JournalEntity — can_* helpers
# ============================================================================


class TestJournalEntityCanHelpers:
    def test_can_edit_true_for_draft_and_rejected(self):
        assert make_entity(status=JournalStatus.DRAFT).can_edit() is True
        assert make_entity(status=JournalStatus.REJECTED).can_edit() is True

    def test_can_submit_only_draft_and_unlocked(self):
        assert make_entity(status=JournalStatus.DRAFT).can_submit() is True
        assert make_entity(status=JournalStatus.SUBMITTED).can_submit() is False
        assert make_entity(status=JournalStatus.DRAFT, _is_locked=True).can_submit() is False

    def test_can_approve_only_submitted(self):
        assert make_entity(status=JournalStatus.SUBMITTED).can_approve() is True
        assert make_entity(status=JournalStatus.DRAFT).can_approve() is False

    def test_can_post_only_approved(self):
        assert make_entity(status=JournalStatus.APPROVED).can_post() is True
        assert make_entity(status=JournalStatus.SUBMITTED).can_post() is False

    def test_can_reverse_only_posted(self):
        assert make_entity(status=JournalStatus.POSTED).can_reverse() is True
        assert make_entity(status=JournalStatus.DRAFT).can_reverse() is False

    def test_can_cancel_draft_and_submitted(self):
        assert make_entity(status=JournalStatus.DRAFT).can_cancel() is True
        assert make_entity(status=JournalStatus.SUBMITTED).can_cancel() is True
        assert make_entity(status=JournalStatus.POSTED).can_cancel() is False

    def test_can_archive_posted_reversed_rejected(self):
        assert make_entity(status=JournalStatus.POSTED).can_archive() is True
        assert make_entity(status=JournalStatus.REVERSED).can_archive() is True
        assert make_entity(status=JournalStatus.REJECTED).can_archive() is True
        assert make_entity(status=JournalStatus.DRAFT).can_archive() is False


# ============================================================================
# JournalEntity — audit trail
# ============================================================================


class TestJournalEntityAuditTrail:
    def test_record_audit_appends_entry(self):
        entity = make_entity()
        entity.record_audit("created", "user_a", {"note": "init"})
        trail = entity.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "created"
        assert trail[0]["user_id"] == "user_a"
        assert trail[0]["details"] == {"note": "init"}

    def test_get_audit_trail_returns_copy(self):
        entity = make_entity()
        entity.record_audit("created", "user_a")
        trail = entity.get_audit_trail()
        trail.append({"fake": True})
        assert len(entity.get_audit_trail()) == 1


# ============================================================================
# JournalEntity — update_metadata
# ============================================================================


class TestJournalEntityUpdateMetadata:
    def test_update_description_creates_new_instance(self):
        entity = make_entity(status=JournalStatus.DRAFT)
        updated = entity.update_metadata("user_b", description="New description here")
        assert updated is not entity
        assert updated.description == "New description here"
        assert updated.version == entity.version + 1

    def test_no_changes_returns_same_instance(self):
        entity = make_entity(status=JournalStatus.DRAFT)
        result = entity.update_metadata("user_b")
        assert result is entity

    def test_short_description_raises(self):
        entity = make_entity(status=JournalStatus.DRAFT)
        with pytest.raises(ValueError, match="at least 2 characters"):
            entity.update_metadata("user_b", description="x")

    def test_update_on_posted_raises(self):
        entity = make_entity(status=JournalStatus.POSTED)
        with pytest.raises(ValueError, match="immutable"):
            entity.update_metadata("user_b", description="New description")

    def test_update_reference(self):
        entity = make_entity(status=JournalStatus.DRAFT, reference="OLD-REF")
        updated = entity.update_metadata("user_b", reference="NEW-REF")
        assert updated.reference == "NEW-REF"


# ============================================================================
# JournalEntity — update_totals
# ============================================================================


class TestJournalEntityUpdateTotals:
    def test_update_totals_success(self):
        entity = make_entity(status=JournalStatus.DRAFT, total_debit=Decimal("100"), total_credit=Decimal("100"))
        updated = entity.update_totals("user_b", Decimal("200"), Decimal("200"))
        assert updated.total_debit == Decimal("200")
        assert updated.version == entity.version + 1

    def test_update_totals_on_posted_raises(self):
        entity = make_entity(status=JournalStatus.POSTED)
        with pytest.raises(ValueError, match="immutable"):
            entity.update_totals("user_b", Decimal("200"), Decimal("200"))

    def test_update_totals_negative_raises(self):
        entity = make_entity(status=JournalStatus.DRAFT)
        with pytest.raises(ValueError, match="cannot be negative"):
            entity.update_totals("user_b", Decimal("-1"), Decimal("0"))

    def test_update_totals_unbalanced_raises(self):
        entity = make_entity(status=JournalStatus.DRAFT)
        with pytest.raises(ValueError, match="unbalanced"):
            entity.update_totals("user_b", Decimal("200"), Decimal("100"))


# ============================================================================
# JournalEntity — serialization
# ============================================================================


class TestJournalEntitySerialization:
    def test_to_dict_contains_expected_fields(self):
        entity = make_entity()
        d = entity.to_dict()
        assert d["journal_number"] == "JRN-001"
        assert d["status"] == "draft"
        assert d["is_balanced"] is True

    def test_from_dict_round_trip(self):
        entity = make_entity(reference="REF-99")
        d = entity.to_dict()
        restored = JournalEntity.from_dict(d)
        assert restored.journal_id == entity.journal_id
        assert restored.total_debit == entity.total_debit
        assert restored.reference == "REF-99"

    def test_from_dict_defaults_version_and_source(self):
        entity = make_entity()
        d = entity.to_dict()
        del d["version"]
        del d["source_system"]
        restored = JournalEntity.from_dict(d)
        assert restored.version == 1
        assert restored.source_system == "ERP"


# ============================================================================
# JournalEntityRepository — unimplemented protocol
# ============================================================================


class TestJournalEntityRepository:
    @pytest.fixture
    def repo(self):
        return JournalEntityRepository()

    async def test_get_by_id_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            await repo.get_by_id(uuid4(), uuid4())

    async def test_get_by_number_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            await repo.get_by_number("JRN-1", uuid4())

    async def test_save_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            await repo.save(make_entity())

    async def test_delete_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            await repo.delete(uuid4(), uuid4())

    async def test_exists_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            await repo.exists("JRN-1", uuid4())


# ============================================================================
# Aliases
# ============================================================================


class TestAliases:
    def test_journal_entry_alias_is_journal_entity(self):
        assert JournalEntry is JournalEntity

    def test_journal_state_machine_reexported(self):
        assert JournalStateMachine.can_transition(JournalStatus.DRAFT, JournalStatus.SUBMITTED) is True
