# tests/domain/equity_retained/test_capital_contribution_entity.py
# Comprehensive tests for domain/equity_retained/capital_contribution_entity.py

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from domain.equity_retained.capital_contribution_entity import (
    CapitalContributionEntity,
    CapitalContributionError,
    CapitalContributionRepository,
    ContributionStatus,
    ContributionType,
    InvalidContributionAmountError,
    InvalidSharePercentageError,
    InvalidStatusTransitionError,
    _validate_contribution_number,
    _validate_currency,
    _validate_share_percentage,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def fixed_now():
    return datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime(fixed_now):
    with patch("domain.equity_retained.capital_contribution_entity.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.utcnow.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def sample_contribution():
    return CapitalContributionEntity(
        contribution_id=uuid4(),
        legal_entity_id=uuid4(),
        contribution_number="CAP-001",
        contribution_type=ContributionType.INITIAL,
        shareholder_id=uuid4(),
        shareholder_name="John Doe",
        amount=Decimal("1000000000"),
        currency="IDR",
        contribution_date=datetime(2026, 1, 15, tzinfo=UTC),
        status=ContributionStatus.DRAFT,
        description="Initial capital contribution",
        share_percentage=Decimal("25.5"),
    )


@pytest.fixture
def approved_contribution(sample_contribution):
    return sample_contribution.approve("admin", "APP-001")


@pytest.fixture
def posted_contribution(approved_contribution):
    return approved_contribution.post("admin")


@pytest.fixture
def cancelled_contribution(sample_contribution):
    return sample_contribution.cancel("admin", "Test cancellation")


@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def repo():
    # Clear storage before each test
    CapitalContributionRepository._storage.clear()
    return CapitalContributionRepository()


# ============================================================================
# Tests for Helper Functions
# ============================================================================

class TestValidateContributionNumber:
    def test_valid_number(self):
        result = _validate_contribution_number("CAP-001")
        assert result == "CAP-001"

    def test_valid_with_slash(self):
        result = _validate_contribution_number("CAP/001")
        assert result == "CAP/001"

    def test_valid_with_underscore(self):
        result = _validate_contribution_number("CAP_001")
        assert result == "CAP_001"

    def test_empty_string_raises(self):
        with pytest.raises(CapitalContributionError, match="non-empty string"):
            _validate_contribution_number("")

    def test_none_raises(self):
        with pytest.raises(CapitalContributionError, match="non-empty string"):
            _validate_contribution_number(None)

    def test_too_short_raises(self):
        with pytest.raises(CapitalContributionError, match="at least 3 characters"):
            _validate_contribution_number("AB")

    def test_too_long_raises(self):
        long_str = "A" * 31
        with pytest.raises(CapitalContributionError, match="not exceed 30 characters"):
            _validate_contribution_number(long_str)

    def test_invalid_characters_raises(self):
        with pytest.raises(CapitalContributionError, match="can only contain"):
            _validate_contribution_number("CAP 001")

    def test_strips_whitespace(self):
        result = _validate_contribution_number("  CAP-001  ")
        assert result == "CAP-001"


class TestValidateSharePercentage:
    def test_valid_percentage(self):
        result = _validate_share_percentage(Decimal("25.5"))
        assert result == Decimal("25.5")

    def test_valid_percentage_string(self):
        result = _validate_share_percentage("25.5")
        assert result == Decimal("25.5")

    def test_none_returns_none(self):
        result = _validate_share_percentage(None)
        assert result is None

    def test_zero_percentage(self):
        result = _validate_share_percentage(Decimal("0"))
        assert result == Decimal("0")

    def test_hundred_percentage(self):
        result = _validate_share_percentage(Decimal("100"))
        assert result == Decimal("100")

    def test_negative_percentage_raises(self):
        with pytest.raises(InvalidSharePercentageError, match="between 0 and 100"):
            _validate_share_percentage(Decimal("-1"))

    def test_above_hundred_raises(self):
        with pytest.raises(InvalidSharePercentageError, match="between 0 and 100"):
            _validate_share_percentage(Decimal("101"))

    def test_invalid_type_raises(self):
        with pytest.raises(InvalidSharePercentageError, match="Invalid percentage type"):
            _validate_share_percentage("not a number")

    def test_quantizes_to_4_decimal_places(self):
        result = _validate_share_percentage(Decimal("25.55555"))
        assert result == Decimal("25.5556")


class TestValidateCurrency:
    def test_valid_currency(self):
        result = _validate_currency("IDR")
        assert result == "IDR"

    def test_valid_currency_lowercase(self):
        result = _validate_currency("idr")
        assert result == "IDR"

    def test_valid_currency_with_spaces(self):
        result = _validate_currency("  USD  ")
        assert result == "USD"

    def test_empty_string_raises(self):
        with pytest.raises(CapitalContributionError, match="non-empty string"):
            _validate_currency("")

    def test_none_raises(self):
        with pytest.raises(CapitalContributionError, match="non-empty string"):
            _validate_currency(None)

    def test_too_short_raises(self):
        with pytest.raises(CapitalContributionError, match="exactly 3 characters"):
            _validate_currency("ID")

    def test_too_long_raises(self):
        with pytest.raises(CapitalContributionError, match="exactly 3 characters"):
            _validate_currency("IDRR")

    def test_invalid_characters_raises(self):
        with pytest.raises(CapitalContributionError, match="only letters"):
            _validate_currency("I1R")


# ============================================================================
# Tests for CapitalContributionEntity
# ============================================================================

class TestCapitalContributionEntity:
    def test_construction_valid(self, sample_contribution):
        assert sample_contribution.contribution_number == "CAP-001"
        assert sample_contribution.shareholder_name == "John Doe"
        assert sample_contribution.amount == Decimal("1000000000")
        assert sample_contribution.status == ContributionStatus.DRAFT
        assert sample_contribution.version == 1
        assert len(sample_contribution._snapshots) == 1

    def test_construction_auto_validate_shareholder_name(self):
        contribution = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=uuid4(),
            contribution_number="CAP-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="  Alice   ",
            amount=Decimal("1000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        assert contribution.shareholder_name == "Alice"

    def test_construction_invalid_shareholder_name_raises(self):
        with pytest.raises(CapitalContributionError, match="at least 2 characters"):
            CapitalContributionEntity(
                contribution_id=uuid4(),
                legal_entity_id=uuid4(),
                contribution_number="CAP-001",
                contribution_type=ContributionType.INITIAL,
                shareholder_id=uuid4(),
                shareholder_name="A",
                amount=Decimal("1000000"),
                currency="IDR",
                contribution_date=datetime.now(UTC),
                status=ContributionStatus.DRAFT,
            )

    def test_construction_auto_validate_currency(self):
        contribution = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=uuid4(),
            contribution_number="CAP-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="Alice",
            amount=Decimal("1000000"),
            currency="idr",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        assert contribution.currency == "IDR"

    def test_construction_invalid_currency_raises(self):
        with pytest.raises(CapitalContributionError, match="exactly 3 characters"):
            CapitalContributionEntity(
                contribution_id=uuid4(),
                legal_entity_id=uuid4(),
                contribution_number="CAP-001",
                contribution_type=ContributionType.INITIAL,
                shareholder_id=uuid4(),
                shareholder_name="Alice",
                amount=Decimal("1000000"),
                currency="ID",
                contribution_date=datetime.now(UTC),
                status=ContributionStatus.DRAFT,
            )

    def test_construction_auto_validate_amount(self):
        contribution = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=uuid4(),
            contribution_number="CAP-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="Alice",
            amount=1000000,  # int, will be converted to Decimal
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        assert contribution.amount == Decimal("1000000")

    def test_construction_invalid_amount_zero_raises(self):
        with pytest.raises(InvalidContributionAmountError, match="positive"):
            CapitalContributionEntity(
                contribution_id=uuid4(),
                legal_entity_id=uuid4(),
                contribution_number="CAP-001",
                contribution_type=ContributionType.INITIAL,
                shareholder_id=uuid4(),
                shareholder_name="Alice",
                amount=Decimal("0"),
                currency="IDR",
                contribution_date=datetime.now(UTC),
                status=ContributionStatus.DRAFT,
            )

    def test_construction_invalid_amount_negative_raises(self):
        with pytest.raises(InvalidContributionAmountError, match="positive"):
            CapitalContributionEntity(
                contribution_id=uuid4(),
                legal_entity_id=uuid4(),
                contribution_number="CAP-001",
                contribution_type=ContributionType.INITIAL,
                shareholder_id=uuid4(),
                shareholder_name="Alice",
                amount=Decimal("-1000"),
                currency="IDR",
                contribution_date=datetime.now(UTC),
                status=ContributionStatus.DRAFT,
            )

    def test_construction_approved_without_approved_by_raises(self):
        with pytest.raises(CapitalContributionError, match="must have approved_by"):
            CapitalContributionEntity(
                contribution_id=uuid4(),
                legal_entity_id=uuid4(),
                contribution_number="CAP-001",
                contribution_type=ContributionType.INITIAL,
                shareholder_id=uuid4(),
                shareholder_name="Alice",
                amount=Decimal("1000000"),
                currency="IDR",
                contribution_date=datetime.now(UTC),
                status=ContributionStatus.APPROVED,
                approved_by=None,
            )

    def test_construction_posted_without_posted_by_raises(self):
        with pytest.raises(CapitalContributionError, match="must have posted_by"):
            CapitalContributionEntity(
                contribution_id=uuid4(),
                legal_entity_id=uuid4(),
                contribution_number="CAP-001",
                contribution_type=ContributionType.INITIAL,
                shareholder_id=uuid4(),
                shareholder_name="Alice",
                amount=Decimal("1000000"),
                currency="IDR",
                contribution_date=datetime.now(UTC),
                status=ContributionStatus.POSTED,
                posted_by=None,
            )

    def test_construction_cancelled_without_cancelled_by_raises(self):
        with pytest.raises(CapitalContributionError, match="must have cancelled_by"):
            CapitalContributionEntity(
                contribution_id=uuid4(),
                legal_entity_id=uuid4(),
                contribution_number="CAP-001",
                contribution_type=ContributionType.INITIAL,
                shareholder_id=uuid4(),
                shareholder_name="Alice",
                amount=Decimal("1000000"),
                currency="IDR",
                contribution_date=datetime.now(UTC),
                status=ContributionStatus.CANCELLED,
                cancelled_by=None,
            )

    def test_construction_invalid_version_raises(self):
        with pytest.raises(CapitalContributionError, match="Version must be >= 1"):
            CapitalContributionEntity(
                contribution_id=uuid4(),
                legal_entity_id=uuid4(),
                contribution_number="CAP-001",
                contribution_type=ContributionType.INITIAL,
                shareholder_id=uuid4(),
                shareholder_name="Alice",
                amount=Decimal("1000000"),
                currency="IDR",
                contribution_date=datetime.now(UTC),
                status=ContributionStatus.DRAFT,
                version=0,
            )

    def test_construction_auto_tz_contribution_date(self):
        naive = datetime(2026, 1, 15, 12, 0, 0)
        contribution = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=uuid4(),
            contribution_number="CAP-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="Alice",
            amount=Decimal("1000000"),
            currency="IDR",
            contribution_date=naive,
            status=ContributionStatus.DRAFT,
        )
        assert contribution.contribution_date.tzinfo is not None

    # ---- Property Tests ----
    def test_is_draft(self, sample_contribution):
        assert sample_contribution.is_draft is True
        approved = sample_contribution.approve("admin")
        assert approved.is_draft is False

    def test_is_approved(self, sample_contribution, approved_contribution):
        assert sample_contribution.is_approved is False
        assert approved_contribution.is_approved is True

    def test_is_posted(self, sample_contribution, posted_contribution):
        assert sample_contribution.is_posted is False
        assert posted_contribution.is_posted is True

    def test_is_cancelled(self, sample_contribution, cancelled_contribution):
        assert sample_contribution.is_cancelled is False
        assert cancelled_contribution.is_cancelled is True

    def test_can_edit(self, sample_contribution, approved_contribution, posted_contribution):
        assert sample_contribution.can_edit is True
        assert approved_contribution.can_edit is False
        assert posted_contribution.can_edit is False

    def test_can_approve(self, sample_contribution, approved_contribution):
        assert sample_contribution.can_approve is True
        assert approved_contribution.can_approve is False

    def test_can_post(self, sample_contribution, approved_contribution):
        assert sample_contribution.can_post is False
        assert approved_contribution.can_post is True

    def test_can_cancel(self, sample_contribution, approved_contribution, posted_contribution):
        assert sample_contribution.can_cancel is True
        assert approved_contribution.can_cancel is True
        assert posted_contribution.can_cancel is False

    # ---- approve ----
    def test_approve_from_draft(self, sample_contribution):
        result = sample_contribution.approve("admin", "REF-001")
        assert result.status == ContributionStatus.APPROVED
        assert result.approved_by == "admin"
        assert result.approved_at is not None
        assert result.approval_reference == "REF-001"
        assert result.version == 2
        assert result._audit_trail[-1]["action"] == "APPROVE"

    def test_approve_without_reference(self, sample_contribution):
        result = sample_contribution.approve("admin")
        assert result.approval_reference is None

    def test_approve_from_approved_raises(self, approved_contribution):
        with pytest.raises(InvalidStatusTransitionError, match="Cannot approve"):
            approved_contribution.approve("admin")

    # ---- post ----
    def test_post_from_approved(self, approved_contribution):
        result = approved_contribution.post("admin")
        assert result.status == ContributionStatus.POSTED
        assert result.posted_by == "admin"
        assert result.posted_at is not None
        assert result.version == 3
        assert result._audit_trail[-1]["action"] == "POST"

    def test_post_from_draft_raises(self, sample_contribution):
        with pytest.raises(InvalidStatusTransitionError, match="Cannot post"):
            sample_contribution.post("admin")

    # ---- cancel ----
    def test_cancel_from_draft(self, sample_contribution):
        result = sample_contribution.cancel("admin", "Cancelled due to error")
        assert result.status == ContributionStatus.CANCELLED
        assert result.cancelled_by == "admin"
        assert result.cancelled_at is not None
        assert result.cancel_reason == "Cancelled due to error"
        assert result.version == 2
        assert result._audit_trail[-1]["action"] == "CANCEL"

    def test_cancel_from_approved(self, approved_contribution):
        result = approved_contribution.cancel("admin", "Postponed")
        assert result.status == ContributionStatus.CANCELLED

    def test_cancel_from_posted_raises(self, posted_contribution):
        with pytest.raises(InvalidStatusTransitionError, match="Cannot cancel"):
            posted_contribution.cancel("admin", "Test")

    # ---- update_description ----
    def test_update_description_from_draft(self, sample_contribution):
        result = sample_contribution.update_description("New description", "user")
        assert result.description == "New description"
        assert result.version == 2
        assert result._audit_trail[-1]["action"] == "UPDATE_DESCRIPTION"

    def test_update_description_from_approved_raises(self, approved_contribution):
        with pytest.raises(InvalidStatusTransitionError, match="Cannot edit"):
            approved_contribution.update_description("New", "user")

    # ---- lock / unlock ----
    def test_lock(self, sample_contribution):
        result = sample_contribution.lock("admin", "Review")
        assert result.metadata["locked_by"] == "admin"
        assert "locked_at" in result.metadata
        assert result.metadata["lock_reason"] == "Review"
        assert result.version == 2
        assert result._audit_trail[-1]["action"] == "LOCK"

    def test_unlock(self, sample_contribution):
        locked = sample_contribution.lock("admin", "Review")
        result = locked.unlock("user")
        assert result.metadata.get("locked_by") is None
        assert result.metadata.get("locked_at") is None
        assert result.metadata.get("lock_reason") is None
        assert result.version == 3
        assert result._audit_trail[-1]["action"] == "UNLOCK"

    # ---- update ----
    def test_update_from_draft(self, sample_contribution):
        result = sample_contribution.update("user", description="Updated", amount=Decimal("2000000000"))
        assert result.description == "Updated"
        assert result.amount == Decimal("2000000000")
        assert result.version == 2
        assert result._audit_trail[-1]["action"] == "UPDATE"

    def test_update_from_approved_raises(self, approved_contribution):
        with pytest.raises(InvalidStatusTransitionError, match="Cannot update"):
            approved_contribution.update("user", description="test")

    # ---- create ----
    def test_create(self, sample_contribution):
        result = sample_contribution.create("creator")
        assert result._audit_trail[-1]["action"] == "CREATE"
        assert result._audit_trail[-1]["performed_by"] == "creator"

    # ---- delete ----
    def test_delete_from_draft(self, sample_contribution):
        result = sample_contribution.delete("admin", "No longer needed")
        assert result.status == ContributionStatus.CANCELLED
        assert result.cancel_reason == "No longer needed"
        assert result._audit_trail[-1]["action"] == "DELETE"

    def test_delete_from_cancelled(self, cancelled_contribution):
        result = cancelled_contribution.delete("admin", "Cleanup")
        assert result.status == ContributionStatus.CANCELLED
        assert result._audit_trail[-1]["action"] == "DELETE"

    def test_delete_from_approved_raises(self, approved_contribution):
        with pytest.raises(InvalidStatusTransitionError, match="Cannot delete"):
            approved_contribution.delete("admin")

    # ---- restore ----
    def test_restore_from_cancelled(self, cancelled_contribution):
        result = cancelled_contribution.restore("admin")
        assert result.status == ContributionStatus.DRAFT
        assert result.cancelled_by is None
        assert result.cancelled_at is None
        assert result.cancel_reason == ""
        assert result.version == 2
        assert result._audit_trail[-1]["action"] == "RESTORE"

    def test_restore_from_draft_raises(self, sample_contribution):
        with pytest.raises(InvalidStatusTransitionError, match="Cannot restore"):
            sample_contribution.restore("admin")

    # ---- activate (alias for approve) ----
    def test_activate(self, sample_contribution):
        result = sample_contribution.activate("admin")
        assert result.status == ContributionStatus.APPROVED
        assert result.approved_by == "admin"

    # ---- deactivate (alias for cancel) ----
    def test_deactivate(self, sample_contribution):
        result = sample_contribution.deactivate("admin", "Deactivated")
        assert result.status == ContributionStatus.CANCELLED
        assert result.cancel_reason == "Deactivated by user"

    # ---- validate ----
    def test_validate_valid(self, sample_contribution):
        result = sample_contribution.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid(self):
        contribution = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=uuid4(),
            contribution_number="CAP-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="A",  # too short
            amount=Decimal("1000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        result = contribution.validate()
        assert result["is_valid"] is False
        assert len(result["errors"]) > 0

    # ---- to_dict / from_dict ----
    def test_to_dict(self, sample_contribution):
        d = sample_contribution.to_dict()
        assert d["contribution_number"] == "CAP-001"
        assert d["shareholder_name"] == "John Doe"
        assert d["amount"] == "1000000000"
        assert d["currency"] == "IDR"
        assert d["status"] == "draft"
        assert d["version"] == 1
        assert "contribution_id" in d

    def test_from_dict(self, sample_contribution):
        d = sample_contribution.to_dict()
        reconstructed = CapitalContributionEntity.from_dict(d)
        assert reconstructed.contribution_number == sample_contribution.contribution_number
        assert reconstructed.shareholder_name == sample_contribution.shareholder_name
        assert reconstructed.amount == sample_contribution.amount
        assert reconstructed.currency == sample_contribution.currency
        assert reconstructed.status == sample_contribution.status
        assert reconstructed.version == sample_contribution.version
        assert reconstructed.contribution_id == sample_contribution.contribution_id

    # ---- clone ----
    def test_clone(self, sample_contribution):
        cloned = sample_contribution.clone()
        assert cloned.contribution_id != sample_contribution.contribution_id
        assert cloned.contribution_number == "CAP-001_COPY"
        assert cloned.status == ContributionStatus.DRAFT
        assert cloned.amount == sample_contribution.amount
        assert cloned.version == 1
        assert cloned._audit_trail[-1]["action"] == "CLONE"

    def test_clone_with_custom_number(self, sample_contribution):
        cloned = sample_contribution.clone("CAP-002")
        assert cloned.contribution_number == "CAP-002"

    # ---- snapshot ----
    def test_snapshot(self, sample_contribution):
        snap = sample_contribution.snapshot()
        assert snap["version"] == 1
        assert snap["contribution_id"] == str(sample_contribution.contribution_id)
        assert snap["number"] == "CAP-001"
        assert snap["amount"] == "1000000000"
        assert snap["status"] == "draft"
        assert "timestamp" in snap

    # ---- get_version ----
    def test_get_version(self, sample_contribution):
        assert sample_contribution.get_version() == 1
        approved = sample_contribution.approve("admin")
        assert approved.get_version() == 2

    # ---- audit_trail ----
    def test_audit_trail(self, sample_contribution):
        sample_contribution.create("system")
        sample_contribution.approve("admin")
        trail = sample_contribution.audit_trail(limit=10)
        assert len(trail) == 2
        assert trail[0]["action"] == "CREATE"
        assert trail[1]["action"] == "APPROVE"

    # ---- touch ----
    def test_touch(self, sample_contribution):
        old_version = sample_contribution.version
        result = sample_contribution.touch("admin")
        assert result.version == old_version + 1
        assert result._audit_trail[-1]["action"] == "TOUCH"


# ============================================================================
# Tests for CapitalContributionRepository
# ============================================================================

class TestCapitalContributionRepository:
    def test_storage_is_isolated(self, legal_entity_id):
        # Different legal entities should have separate storage
        le1 = legal_entity_id
        le2 = uuid4()

        contrib1 = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=le1,
            contribution_number="CAP-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="Alice",
            amount=Decimal("1000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )

        CapitalContributionRepository._storage.clear()
        CapitalContributionRepository._storage[le1] = {contrib1.contribution_id: contrib1}

        assert le1 in CapitalContributionRepository._storage
        assert le2 not in CapitalContributionRepository._storage

    @pytest.mark.asyncio
    async def test_get_by_id_found(self, repo, legal_entity_id):
        contrib = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=legal_entity_id,
            contribution_number="CAP-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="Alice",
            amount=Decimal("1000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        await repo.save(contrib, legal_entity_id)

        result = await repo.get_by_id(contrib.contribution_id, legal_entity_id)
        assert result is not None
        assert result.contribution_id == contrib.contribution_id

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, repo, legal_entity_id):
        result = await repo.get_by_id(uuid4(), legal_entity_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_number_found(self, repo, legal_entity_id):
        contrib = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=legal_entity_id,
            contribution_number="CAP-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="Alice",
            amount=Decimal("1000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        await repo.save(contrib, legal_entity_id)

        result = await repo.get_by_number("CAP-001", legal_entity_id)
        assert result is not None
        assert result.contribution_number == "CAP-001"

    @pytest.mark.asyncio
    async def test_get_by_number_not_found(self, repo, legal_entity_id):
        result = await repo.get_by_number("NONEXISTENT", legal_entity_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_shareholder(self, repo, legal_entity_id):
        shareholder_id = uuid4()
        contrib1 = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=legal_entity_id,
            contribution_number="CAP-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=shareholder_id,
            shareholder_name="Alice",
            amount=Decimal("1000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        contrib2 = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=legal_entity_id,
            contribution_number="CAP-002",
            contribution_type=ContributionType.ADDITIONAL,
            shareholder_id=shareholder_id,
            shareholder_name="Alice",
            amount=Decimal("2000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        await repo.save(contrib1, legal_entity_id)
        await repo.save(contrib2, legal_entity_id)

        results = await repo.get_by_shareholder(shareholder_id, legal_entity_id)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_get_by_status(self, repo, legal_entity_id):
        contrib1 = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=legal_entity_id,
            contribution_number="CAP-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="Alice",
            amount=Decimal("1000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        contrib2 = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=legal_entity_id,
            contribution_number="CAP-002",
            contribution_type=ContributionType.ADDITIONAL,
            shareholder_id=uuid4(),
            shareholder_name="Bob",
            amount=Decimal("2000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.APPROVED,
        )
        await repo.save(contrib1, legal_entity_id)
        await repo.save(contrib2, legal_entity_id)

        drafts = await repo.get_by_status(ContributionStatus.DRAFT, legal_entity_id)
        assert len(drafts) == 1
        assert drafts[0].contribution_number == "CAP-001"

        approved = await repo.get_by_status(ContributionStatus.APPROVED, legal_entity_id)
        assert len(approved) == 1
        assert approved[0].contribution_number == "CAP-002"

    @pytest.mark.asyncio
    async def test_get_all(self, repo, legal_entity_id):
        contrib1 = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=legal_entity_id,
            contribution_number="CAP-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="Alice",
            amount=Decimal("1000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        contrib2 = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=legal_entity_id,
            contribution_number="CAP-002",
            contribution_type=ContributionType.ADDITIONAL,
            shareholder_id=uuid4(),
            shareholder_name="Bob",
            amount=Decimal("2000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        await repo.save(contrib1, legal_entity_id)
        await repo.save(contrib2, legal_entity_id)

        results = await repo.get_all(legal_entity_id)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_save_and_update(self, repo, legal_entity_id):
        contrib = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=legal_entity_id,
            contribution_number="CAP-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="Alice",
            amount=Decimal("1000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        await repo.save(contrib, legal_entity_id)
        retrieved = await repo.get_by_id(contrib.contribution_id, legal_entity_id)
        assert retrieved is not None

        updated = contrib.approve("admin")
        await repo.update(updated, legal_entity_id)
        retrieved2 = await repo.get_by_id(contrib.contribution_id, legal_entity_id)
        assert retrieved2.status == ContributionStatus.APPROVED

    @pytest.mark.asyncio
    async def test_delete(self, repo, legal_entity_id):
        contrib = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=legal_entity_id,
            contribution_number="CAP-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="Alice",
            amount=Decimal("1000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        await repo.save(contrib, legal_entity_id)
        assert await repo.exists(contrib.contribution_id, legal_entity_id) is True

        await repo.delete(contrib.contribution_id, legal_entity_id)
        assert await repo.exists(contrib.contribution_id, legal_entity_id) is False

    @pytest.mark.asyncio
    async def test_exists(self, repo, legal_entity_id):
        contrib = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=legal_entity_id,
            contribution_number="CAP-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="Alice",
            amount=Decimal("1000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        await repo.save(contrib, legal_entity_id)
        assert await repo.exists(contrib.contribution_id, legal_entity_id) is True
        assert await repo.exists(uuid4(), legal_entity_id) is False

    @pytest.mark.asyncio
    async def test_count(self, repo, legal_entity_id):
        contrib1 = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=legal_entity_id,
            contribution_number="CAP-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="Alice",
            amount=Decimal("1000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        contrib2 = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=legal_entity_id,
            contribution_number="CAP-002",
            contribution_type=ContributionType.ADDITIONAL,
            shareholder_id=uuid4(),
            shareholder_name="Bob",
            amount=Decimal("2000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        await repo.save(contrib1, legal_entity_id)
        await repo.save(contrib2, legal_entity_id)

        count = await repo.count(legal_entity_id)
        assert count == 2

    @pytest.mark.asyncio
    async def test_list_paginated(self, repo, legal_entity_id):
        # Create 5 contributions
        for i in range(5):
            contrib = CapitalContributionEntity(
                contribution_id=uuid4(),
                legal_entity_id=legal_entity_id,
                contribution_number=f"CAP-{i+1:03d}",
                contribution_type=ContributionType.INITIAL,
                shareholder_id=uuid4(),
                shareholder_name=f"Shareholder {i+1}",
                amount=Decimal(f"{1000000 * (i+1)}"),
                currency="IDR",
                contribution_date=datetime.now(UTC),
                status=ContributionStatus.DRAFT,
            )
            await repo.save(contrib, legal_entity_id)

        results, total = await repo.paginate(legal_entity_id, page=1, per_page=3)
        assert len(results) == 3
        assert total == 5

        results2, total2 = await repo.paginate(legal_entity_id, page=2, per_page=3)
        assert len(results2) == 2
        assert total2 == 5

    @pytest.mark.asyncio
    async def test_search(self, repo, legal_entity_id):
        contrib1 = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=legal_entity_id,
            contribution_number="CAP-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="Alice Wonderland",
            amount=Decimal("1000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
            description="Initial investment",
        )
        contrib2 = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=legal_entity_id,
            contribution_number="CAP-002",
            contribution_type=ContributionType.ADDITIONAL,
            shareholder_id=uuid4(),
            shareholder_name="Bob Smith",
            amount=Decimal("2000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
            description="Additional capital",
        )
        await repo.save(contrib1, legal_entity_id)
        await repo.save(contrib2, legal_entity_id)

        # Search by shareholder name
        results = await repo.search(legal_entity_id, "Alice")
        assert len(results) == 1
        assert results[0].contribution_number == "CAP-001"

        # Search by contribution number
        results2 = await repo.search(legal_entity_id, "CAP-002")
        assert len(results2) == 1
        assert results2[0].contribution_number == "CAP-002"

        # Search by description
        results3 = await repo.search(legal_entity_id, "Additional")
        assert len(results3) == 1
        assert results3[0].contribution_number == "CAP-002"

        # Search with custom fields
        results4 = await repo.search(legal_entity_id, "CAP", fields=["contribution_number"])
        assert len(results4) == 2

        # Search no results
        results5 = await repo.search(legal_entity_id, "XYZ")
        assert len(results5) == 0

    @pytest.mark.asyncio
    async def test_lock_and_unlock(self, repo, legal_entity_id):
        contrib = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=legal_entity_id,
            contribution_number="CAP-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="Alice",
            amount=Decimal("1000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        await repo.save(contrib, legal_entity_id)

        locked = await repo.lock(contrib.contribution_id, legal_entity_id, "admin", "Review")
        assert locked.metadata["locked_by"] == "admin"
        assert locked.version == 2

        unlocked = await repo.unlock(contrib.contribution_id, legal_entity_id, "user")
        assert unlocked.metadata.get("locked_by") is None
        assert unlocked.version == 3

    @pytest.mark.asyncio
    async def test_lock_not_found_raises(self, repo, legal_entity_id):
        with pytest.raises(ValueError, match="not found"):
            await repo.lock(uuid4(), legal_entity_id, "admin", "Review")

    @pytest.mark.asyncio
    async def test_clear(self, repo, legal_entity_id):
        contrib = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=legal_entity_id,
            contribution_number="CAP-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="Alice",
            amount=Decimal("1000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        await repo.save(contrib, legal_entity_id)
        assert len(await repo.get_all(legal_entity_id)) == 1

        await repo.clear(legal_entity_id)
        assert len(await repo.get_all(legal_entity_id)) == 0

        # Other legal entities should not be affected
        other_le = uuid4()
        contrib2 = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=other_le,
            contribution_number="CAP-002",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="Bob",
            amount=Decimal("1000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
        )
        await repo.save(contrib2, other_le)
        assert len(await repo.get_all(other_le)) == 1


# ============================================================================
# Integration Tests - Full Workflow
# ============================================================================

class TestIntegration:
    @pytest.mark.asyncio
    async def test_full_contribution_lifecycle(self, repo, legal_entity_id):
        # 1. Create contribution
        contrib = CapitalContributionEntity(
            contribution_id=uuid4(),
            legal_entity_id=legal_entity_id,
            contribution_number="CAP-FULL-001",
            contribution_type=ContributionType.INITIAL,
            shareholder_id=uuid4(),
            shareholder_name="John Doe",
            amount=Decimal("5000000000"),
            currency="IDR",
            contribution_date=datetime.now(UTC),
            status=ContributionStatus.DRAFT,
            description="Full lifecycle test",
            share_percentage=Decimal("40.0"),
        )
        assert contrib.status == ContributionStatus.DRAFT
        assert contrib.version == 1

        # 2. Save
        await repo.save(contrib, legal_entity_id)

        # 3. Approve
        approved = contrib.approve("admin", "REF-001")
        assert approved.status == ContributionStatus.APPROVED
        assert approved.version == 2

        await repo.update(approved, legal_entity_id)

        # 4. Post
        posted = approved.post("admin")
        assert posted.status == ContributionStatus.POSTED
        assert posted.version == 3

        await repo.update(posted, legal_entity_id)

        # 5. Retrieve and verify
        retrieved = await repo.get_by_id(contrib.contribution_id, legal_entity_id)
        assert retrieved.status == ContributionStatus.POSTED
        assert retrieved.version == 3
        assert retrieved.approved_by == "admin"
        assert retrieved.posted_by == "admin"
        assert retrieved.approval_reference == "REF-001"
        assert retrieved.share_percentage == Decimal("40.0")

        # 6. Audit trail check
        trail = retrieved.audit_trail(limit=10)
        actions = [entry["action"] for entry in trail]
        assert "CREATE" in actions
        assert "APPROVE" in actions
        assert "POST" in actions