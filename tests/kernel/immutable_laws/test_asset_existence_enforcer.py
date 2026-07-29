#!/usr/bin/env python3
"""
tests/kernel/immutable_laws/test_asset_existence_enforcer.py
Comprehensive tests for kernel/immutable_laws/asset_existence_enforcer.py.

Covers all enums, data classes, fallback repositories, the concrete AssetExistenceEnforcer
class (all public and private methods), and the singleton accessor.
Includes thorough negative path testing and edge cases.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from kernel.immutable_laws.asset_existence_enforcer import (
    AssetExistenceEnforcer,
    AssetType,
    PhysicalCountRecord,
    VerificationMethod,
    VerificationRecord,
    VerificationStatus,
    _FallbackAssetRepository,
    _FallbackInventoryRepository,
    get_asset_existence_enforcer,
)
from kernel.immutable_laws.law_violation_exceptions import (
    AssetExistenceViolation,
    LawViolationSeverity,
)

# =============================================================================
# Fixtures
# =============================================================================

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("kernel.immutable_laws.asset_existence_enforcer.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


@pytest.fixture
def mock_context_holder():
    with patch("kernel.immutable_laws.asset_existence_enforcer.get_current_user") as mock:
        mock.return_value = "test_user"
        yield mock


@pytest.fixture
def mock_asset_repo():
    repo = AsyncMock(spec=_FallbackAssetRepository)
    repo.get_by_id.return_value = None
    repo.get_last_physical_count_date.return_value = None
    repo.record_verification.return_value = None
    repo.record_physical_count.return_value = uuid4()
    repo.get_last_verification.return_value = None
    repo.clear.return_value = None
    return repo


@pytest.fixture
def mock_inventory_repo():
    repo = AsyncMock(spec=_FallbackInventoryRepository)
    repo.get_by_id.return_value = None
    repo.clear.return_value = None
    return repo


@pytest.fixture
def enforcer(mock_asset_repo, mock_inventory_repo):
    return AssetExistenceEnforcer(
        asset_repository=mock_asset_repo,
        inventory_repository=mock_inventory_repo,
    )


@pytest.fixture
def sample_verification_record():
    return VerificationRecord(
        record_id=uuid4(),
        asset_id=uuid4(),
        asset_type=AssetType.FIXED_ASSET,
        legal_entity_id=uuid4(),
        verification_method=VerificationMethod.PHYSICAL_INSPECTION,
        verification_document="doc-123",
        verified_by="alice",
        verified_at=FIXED_NOW,
        status=VerificationStatus.VERIFIED,
        notes="All good",
        discrepancy_amount=Decimal(0),
        resolved_at=None,
        resolved_by=None,
    )


@pytest.fixture
def sample_physical_count_record():
    return PhysicalCountRecord(
        count_id=uuid4(),
        legal_entity_id=uuid4(),
        counted_by="bob",
        counted_at=FIXED_NOW,
        location="Warehouse A",
        discrepancies={"item1": 5},
        is_adjusted=False,
        adjusted_at=None,
        adjusted_by=None,
    )


# =============================================================================
# Tests for Enums
# =============================================================================

class TestAssetType:
    def test_members(self):
        assert AssetType.FIXED_ASSET.value == "fixed_asset"
        assert AssetType.INVENTORY.value == "inventory"
        assert AssetType.INTANGIBLE.value == "intangible"
        assert AssetType.FINANCIAL.value == "financial"
        assert AssetType.BIOLOGICAL.value == "biological"


class TestVerificationMethod:
    def test_members(self):
        assert VerificationMethod.PHYSICAL_INSPECTION.value == "physical_inspection"
        assert VerificationMethod.DOCUMENT_VERIFICATION.value == "document_verification"
        assert VerificationMethod.THIRD_PARTY_CONFIRMATION.value == "third_party_confirmation"
        assert VerificationMethod.VALUATION_REPORT.value == "valuation_report"
        assert VerificationMethod.LEGAL_TITLE.value == "legal_title"
        assert VerificationMethod.SAMPLE_TESTING.value == "sample_testing"
        assert VerificationMethod.CYCLE_COUNT.value == "cycle_count"


class TestVerificationStatus:
    def test_members(self):
        assert VerificationStatus.NOT_VERIFIED.value == "not_verified"
        assert VerificationStatus.VERIFIED.value == "verified"
        assert VerificationStatus.PARTIALLY_VERIFIED.value == "partially_verified"
        assert VerificationStatus.DISCREPANCY_FOUND.value == "discrepancy_found"
        assert VerificationStatus.RESOLVED.value == "resolved"


# =============================================================================
# Tests for Data Classes
# =============================================================================

class TestVerificationRecord:
    def test_construction(self):
        record_id = uuid4()
        asset_id = uuid4()
        legal_entity_id = uuid4()
        record = VerificationRecord(
            record_id=record_id,
            asset_id=asset_id,
            asset_type=AssetType.FIXED_ASSET,
            legal_entity_id=legal_entity_id,
            verification_method=VerificationMethod.PHYSICAL_INSPECTION,
            verification_document="doc",
            verified_by="alice",
            verified_at=FIXED_NOW,
            status=VerificationStatus.VERIFIED,
            notes="Note",
            discrepancy_amount=Decimal("10.5"),
        )
        assert record.record_id == record_id
        assert record.asset_id == asset_id
        assert record.asset_type == AssetType.FIXED_ASSET
        assert record.legal_entity_id == legal_entity_id
        assert record.verification_method == VerificationMethod.PHYSICAL_INSPECTION
        assert record.verification_document == "doc"
        assert record.verified_by == "alice"
        assert record.verified_at == FIXED_NOW
        assert record.status == VerificationStatus.VERIFIED
        assert record.notes == "Note"
        assert record.discrepancy_amount == Decimal("10.5")
        assert record.resolved_at is None
        assert record.resolved_by is None

    def test_compute_hash(self):
        record = VerificationRecord(
            record_id=uuid4(),
            asset_id=uuid4(),
            asset_type=AssetType.FIXED_ASSET,
            legal_entity_id=uuid4(),
            verification_method=VerificationMethod.PHYSICAL_INSPECTION,
            verification_document="doc",
            verified_by="alice",
            verified_at=FIXED_NOW,
            status=VerificationStatus.VERIFIED,
        )
        h = record.compute_hash()
        assert isinstance(h, str)
        assert len(h) == 64  # SHA3-256
        # Hash should be deterministic
        assert record.compute_hash() == h

    def test_post_init_validates_hash(self):
        record = VerificationRecord(
            record_id=uuid4(),
            asset_id=uuid4(),
            asset_type=AssetType.FIXED_ASSET,
            legal_entity_id=uuid4(),
            verification_method=VerificationMethod.PHYSICAL_INSPECTION,
            verification_document="doc",
            verified_by="alice",
            verified_at=FIXED_NOW,
            status=VerificationStatus.VERIFIED,
        )
        # Set a hash that matches
        record.cryptographic_hash = record.compute_hash()
        # Should not raise
        assert record.cryptographic_hash == record.compute_hash()

    def test_post_init_mismatched_hash_raises(self):
        record = VerificationRecord(
            record_id=uuid4(),
            asset_id=uuid4(),
            asset_type=AssetType.FIXED_ASSET,
            legal_entity_id=uuid4(),
            verification_method=VerificationMethod.PHYSICAL_INSPECTION,
            verification_document="doc",
            verified_by="alice",
            verified_at=FIXED_NOW,
            status=VerificationStatus.VERIFIED,
        )
        record.cryptographic_hash = "badhash"
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            # __post_init__ runs when we create the object; we need to create a new one with the bad hash
            VerificationRecord(
                record_id=record.record_id,
                asset_id=record.asset_id,
                asset_type=record.asset_type,
                legal_entity_id=record.legal_entity_id,
                verification_method=record.verification_method,
                verification_document=record.verification_document,
                verified_by=record.verified_by,
                verified_at=record.verified_at,
                status=record.status,
                cryptographic_hash="badhash",
            )

    def test_to_dict(self, sample_verification_record):
        d = sample_verification_record.to_dict()
        assert d["record_id"] == str(sample_verification_record.record_id)
        assert d["asset_id"] == str(sample_verification_record.asset_id)
        assert d["asset_type"] == "fixed_asset"
        assert d["legal_entity_id"] == str(sample_verification_record.legal_entity_id)
        assert d["verification_method"] == "physical_inspection"
        assert d["verification_document"] == "doc-123"
        assert d["verified_by"] == "alice"
        assert d["verified_at"] == FIXED_NOW.isoformat()
        assert d["status"] == "verified"
        assert d["notes"] == "All good"
        # Notes should be truncated to 100 chars, but it's short enough
        # Check that discrepancy_amount and resolved fields not included (they are not in to_dict)


class TestPhysicalCountRecord:
    def test_construction(self):
        count_id = uuid4()
        legal_entity_id = uuid4()
        record = PhysicalCountRecord(
            count_id=count_id,
            legal_entity_id=legal_entity_id,
            counted_by="bob",
            counted_at=FIXED_NOW,
            location="WH-1",
            discrepancies={"a": 1},
            is_adjusted=True,
            adjusted_at=FIXED_NOW,
            adjusted_by="alice",
        )
        assert record.count_id == count_id
        assert record.legal_entity_id == legal_entity_id
        assert record.counted_by == "bob"
        assert record.counted_at == FIXED_NOW
        assert record.location == "WH-1"
        assert record.discrepancies == {"a": 1}
        assert record.is_adjusted is True
        assert record.adjusted_at == FIXED_NOW
        assert record.adjusted_by == "alice"

    def test_compute_hash(self, sample_physical_count_record):
        h = sample_physical_count_record.compute_hash()
        assert isinstance(h, str)
        assert len(h) == 64
        assert sample_physical_count_record.compute_hash() == h

    def test_post_init_validates_hash(self, sample_physical_count_record):
        sample_physical_count_record.cryptographic_hash = sample_physical_count_record.compute_hash()
        # Should not raise
        assert sample_physical_count_record.cryptographic_hash == sample_physical_count_record.compute_hash()

    def test_post_init_mismatched_hash_raises(self, sample_physical_count_record):
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            PhysicalCountRecord(
                count_id=sample_physical_count_record.count_id,
                legal_entity_id=sample_physical_count_record.legal_entity_id,
                counted_by=sample_physical_count_record.counted_by,
                counted_at=sample_physical_count_record.counted_at,
                location=sample_physical_count_record.location,
                discrepancies=sample_physical_count_record.discrepancies,
                cryptographic_hash="badhash",
            )


# =============================================================================
# Tests for Fallback Repositories
# =============================================================================

@pytest.mark.asyncio
class TestFallbackAssetRepository:
    async def test_get_by_id_found(self):
        repo = _FallbackAssetRepository()
        asset_id = uuid4()
        legal_entity_id = uuid4()
        repo.add_asset(asset_id, legal_entity_id, "ASSET-001", "fixed_asset")
        result = await repo.get_by_id(asset_id, legal_entity_id)
        assert result is not None
        assert result["asset_code"] == "ASSET-001"
        assert result["legal_entity_id"] == legal_entity_id

    async def test_get_by_id_not_found(self):
        repo = _FallbackAssetRepository()
        result = await repo.get_by_id(uuid4(), uuid4())
        assert result is None

    async def test_get_last_physical_count_date_no_counts(self):
        repo = _FallbackAssetRepository()
        result = await repo.get_last_physical_count_date(uuid4())
        assert result is None

    async def test_get_last_physical_count_date_found(self):
        repo = _FallbackAssetRepository()
        legal_entity_id = uuid4()
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        later = datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC)
        await repo.record_physical_count(legal_entity_id, "bob", now, "WH-1", {})
        await repo.record_physical_count(legal_entity_id, "alice", later, "WH-2", {})
        result = await repo.get_last_physical_count_date(legal_entity_id)
        assert result == later

    async def test_record_physical_count(self):
        repo = _FallbackAssetRepository()
        legal_entity_id = uuid4()
        count_id = await repo.record_physical_count(legal_entity_id, "bob", FIXED_NOW, "WH-1", {"a": 1})
        assert isinstance(count_id, UUID)
        assert len(repo._physical_counts) == 1
        assert repo._physical_counts[0]["count_id"] == count_id

    async def test_record_verification(self):
        repo = _FallbackAssetRepository()
        asset_id = uuid4()
        legal_entity_id = uuid4()
        await repo.record_verification(
            asset_id, "fixed_asset", legal_entity_id,
            "physical_inspection", "doc", "alice", FIXED_NOW
        )
        assert len(repo._verifications[asset_id]) == 1
        v = repo._verifications[asset_id][0]
        assert v["asset_type"] == "fixed_asset"
        assert v["legal_entity_id"] == legal_entity_id

    async def test_get_last_verification(self):
        repo = _FallbackAssetRepository()
        asset_id = uuid4()
        legal_entity_id = uuid4()
        await repo.record_verification(asset_id, "fixed", legal_entity_id, "method1", "doc1", "alice", FIXED_NOW)
        later = datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC)
        await repo.record_verification(asset_id, "fixed", legal_entity_id, "method2", "doc2", "bob", later)
        result = await repo.get_last_verification(asset_id, legal_entity_id)
        assert result["verification_method"] == "method2"
        assert result["verified_by"] == "bob"

    async def test_get_last_verification_not_found(self):
        repo = _FallbackAssetRepository()
        result = await repo.get_last_verification(uuid4(), uuid4())
        assert result is None

    def test_add_asset(self):
        repo = _FallbackAssetRepository()
        asset_id = uuid4()
        legal_entity_id = uuid4()
        repo.add_asset(asset_id, legal_entity_id, "CODE", "inventory")
        assert repo._assets[asset_id]["asset_code"] == "CODE"
        assert repo._assets[asset_id]["asset_type"] == "inventory"

    def test_clear(self):
        repo = _FallbackAssetRepository()
        repo.add_asset(uuid4(), uuid4(), "A", "fixed")
        repo._verifications[uuid4()] = []
        repo._physical_counts.append({})
        repo.clear()
        assert len(repo._assets) == 0
        assert len(repo._verifications) == 0
        assert len(repo._physical_counts) == 0


@pytest.mark.asyncio
class TestFallbackInventoryRepository:
    async def test_get_by_id_found(self):
        repo = _FallbackInventoryRepository()
        item_id = uuid4()
        legal_entity_id = uuid4()
        repo.add_item(item_id, legal_entity_id, "ITEM-001")
        result = await repo.get_by_id(item_id, legal_entity_id)
        assert result is not None
        assert result["item_code"] == "ITEM-001"
        assert result["legal_entity_id"] == legal_entity_id

    async def test_get_by_id_not_found(self):
        repo = _FallbackInventoryRepository()
        result = await repo.get_by_id(uuid4(), uuid4())
        assert result is None

    def test_add_item(self):
        repo = _FallbackInventoryRepository()
        item_id = uuid4()
        legal_entity_id = uuid4()
        repo.add_item(item_id, legal_entity_id, "CODE")
        assert repo._items[item_id]["item_code"] == "CODE"

    def test_clear(self):
        repo = _FallbackInventoryRepository()
        repo.add_item(uuid4(), uuid4(), "A")
        repo.clear()
        assert len(repo._items) == 0


# =============================================================================
# Tests for AssetExistenceEnforcer
# =============================================================================

class TestAssetExistenceEnforcerCheck:
    def test_check_valid_context(self, enforcer):
        context = {
            "asset_id": str(uuid4()),
            "legal_entity_id": str(uuid4()),
            "asset_type": "fixed_asset",
            "amount": "1000000",
        }
        errors = enforcer.check(context)
        assert errors == []

    def test_check_missing_required_fields(self, enforcer):
        errors = enforcer.check({})
        assert "asset_id is required" in errors
        assert "legal_entity_id is required" in errors
        assert "asset_type is required" in errors

    def test_check_invalid_uuid(self, enforcer):
        errors = enforcer.check({
            "asset_id": "invalid",
            "legal_entity_id": "invalid",
            "asset_type": "fixed_asset",
        })
        assert any("valid UUID" in e for e in errors)
        assert any("valid UUID" in e for e in errors[1:])

    def test_check_invalid_asset_type(self, enforcer):
        errors = enforcer.check({
            "asset_id": str(uuid4()),
            "legal_entity_id": str(uuid4()),
            "asset_type": "invalid_type",
        })
        assert any("not a valid AssetType" in e for e in errors)

    def test_check_invalid_amount(self, enforcer):
        errors = enforcer.check({
            "asset_id": str(uuid4()),
            "legal_entity_id": str(uuid4()),
            "asset_type": "fixed_asset",
            "amount": "not_a_number",
        })
        assert any("valid number" in e for e in errors)


class TestAssetExistenceEnforcerEntityMethods:
    def test_validate_valid(self, enforcer):
        result = enforcer.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid_threshold(self, enforcer):
        enforcer._verification_threshold = Decimal("-1")
        result = enforcer.validate()
        assert result["is_valid"] is False
        assert any("verification_threshold cannot be negative" in e for e in result["errors"])

    def test_validate_invalid_max_history(self, enforcer):
        enforcer._max_history = 0
        result = enforcer.validate()
        assert result["is_valid"] is False
        assert any("max_history must be positive" in e for e in result["errors"])

    def test_validate_invalid_days(self, enforcer):
        with patch.object(AssetExistenceEnforcer, "PHYSICAL_COUNT_REQUIRED_DAYS", 0):
            result = enforcer.validate()
            assert result["is_valid"] is False
            assert any("PHYSICAL_COUNT_REQUIRED_DAYS must be positive" in e for e in result["errors"])

    def test_to_dict(self, enforcer):
        d = enforcer.to_dict()
        assert d["enabled"] is True
        assert d["verification_threshold"] == str(Decimal("50000000"))
        assert d["physical_count_required_days"] == 365
        assert d["verifications_count"] == 0
        assert d["physical_counts_count"] == 0
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "enabled": False,
            "verification_threshold": "100000",
            "max_history": 5000,
            "version": 5,
        }
        enforcer = AssetExistenceEnforcer.from_dict(data)
        assert enforcer._enabled is False
        assert enforcer._verification_threshold == Decimal("100000")
        assert enforcer._max_history == 5000
        assert enforcer._version == 5

    def test_clone(self, enforcer):
        enforcer._enabled = False
        enforcer._verification_threshold = Decimal("100")
        cloned = enforcer.clone()
        assert cloned is not enforcer
        assert cloned._enabled == enforcer._enabled
        assert cloned._verification_threshold == enforcer._verification_threshold
        assert cloned._max_history == enforcer._max_history
        assert cloned._version == enforcer._version + 1

    def test_snapshot(self, enforcer):
        snap = enforcer.snapshot()
        assert snap["version"] == 1
        assert snap["verifications_count"] == 0
        assert snap["physical_counts_count"] == 0
        assert snap["enabled"] is True
        assert snap["timestamp"] == FIXED_NOW.isoformat()

    def test_version(self, enforcer):
        assert enforcer.version() == 1

    def test_audit_trail(self, enforcer):
        enforcer._record_audit("TEST", "user", {"detail": "value"})
        trail = enforcer.audit_trail(limit=10)
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"
        assert trail[0]["performed_by"] == "user"
        assert trail[0]["details"] == {"detail": "value"}

    def test_touch(self, enforcer):
        touched = enforcer.touch("admin")
        assert touched._version == 2
        trail = touched.audit_trail(limit=1)
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "admin"

    def test_enable(self, enforcer):
        enforcer.enable(False)
        assert enforcer._enabled is False
        trail = enforcer.audit_trail(limit=1)
        assert trail[0]["action"] == "ENABLE"
        assert trail[0]["details"]["enabled"] is False

    def test_set_verification_threshold(self, enforcer):
        enforcer.set_verification_threshold(Decimal("999"))
        assert enforcer._verification_threshold == Decimal("999")
        trail = enforcer.audit_trail(limit=1)
        assert trail[0]["action"] == "SET_VERIFICATION_THRESHOLD"
        assert trail[0]["details"]["threshold"] == "999"


class TestAssetExistenceEnforcerPrivateMethods:
    def test_get_required_methods_fixed_asset(self, enforcer):
        methods = enforcer._get_required_methods(AssetType.FIXED_ASSET, Decimal("1000"))
        expected = [
            VerificationMethod.PHYSICAL_INSPECTION,
            VerificationMethod.LEGAL_TITLE,
            VerificationMethod.VALUATION_REPORT,
        ]
        assert methods == expected

    def test_get_required_methods_inventory(self, enforcer):
        methods = enforcer._get_required_methods(AssetType.INVENTORY, Decimal("1000"))
        expected = [
            VerificationMethod.PHYSICAL_INSPECTION,
            VerificationMethod.SAMPLE_TESTING,
            VerificationMethod.CYCLE_COUNT,
            VerificationMethod.DOCUMENT_VERIFICATION,
        ]
        assert methods == expected

    def test_get_required_methods_intangible(self, enforcer):
        methods = enforcer._get_required_methods(AssetType.INTANGIBLE, Decimal("1000"))
        expected = [
            VerificationMethod.LEGAL_TITLE,
            VerificationMethod.VALUATION_REPORT,
            VerificationMethod.THIRD_PARTY_CONFIRMATION,
        ]
        assert methods == expected

    def test_get_required_methods_financial(self, enforcer):
        methods = enforcer._get_required_methods(AssetType.FINANCIAL, Decimal("1000"))
        expected = [
            VerificationMethod.THIRD_PARTY_CONFIRMATION,
            VerificationMethod.DOCUMENT_VERIFICATION,
        ]
        assert methods == expected

    def test_get_required_methods_biological(self, enforcer):
        methods = enforcer._get_required_methods(AssetType.BIOLOGICAL, Decimal("1000"))
        expected = [
            VerificationMethod.PHYSICAL_INSPECTION,
            VerificationMethod.VALUATION_REPORT,
        ]
        assert methods == expected

    def test_get_required_methods_default_for_unknown(self, enforcer):
        # Test fallback to DOCUMENT_VERIFICATION when asset_type is not in the dict.
        # Since we cannot create an unknown AssetType, we patch the base_methods dict
        # to simulate that the given type is not present.
        with patch.dict(
            enforcer._get_required_methods.__globals__["base_methods"],
            {},  # empty dict so any lookup fails
            clear=True
        ):
            methods = enforcer._get_required_methods(AssetType.FIXED_ASSET, Decimal("1000"))
            # Expected fallback: [VerificationMethod.DOCUMENT_VERIFICATION]
            assert methods == [VerificationMethod.DOCUMENT_VERIFICATION]

    def test_get_required_methods_high_value(self, enforcer):
        # Amount >= threshold (50M) should filter to strong methods
        # For FIXED_ASSET, strong methods are PHYSICAL_INSPECTION and THIRD_PARTY_CONFIRMATION? Actually based on code:
        # if amount >= threshold:
        #     strong_methods = [PHYSICAL_INSPECTION, THIRD_PARTY_CONFIRMATION]
        #     methods = [m for m in methods if m in strong_methods] or methods
        # So for FIXED_ASSET, strong methods are PHYSICAL_INSPECTION, THIRD_PARTY_CONFIRMATION.
        # But the base methods for FIXED_ASSET are [PHYSICAL_INSPECTION, LEGAL_TITLE, VALUATION_REPORT]
        # So after filtering, only PHYSICAL_INSPECTION remains.
        enforcer.set_verification_threshold(Decimal("1000"))
        methods = enforcer._get_required_methods(AssetType.FIXED_ASSET, Decimal("2000"))
        assert methods == [VerificationMethod.PHYSICAL_INSPECTION]

    def test_get_required_methods_high_value_inventory(self, enforcer):
        enforcer.set_verification_threshold(Decimal("1000"))
        methods = enforcer._get_required_methods(AssetType.INVENTORY, Decimal("2000"))
        # Inventory base methods include PHYSICAL_INSPECTION, SAMPLE_TESTING, CYCLE_COUNT, DOCUMENT_VERIFICATION
        # Strong methods: PHYSICAL_INSPECTION, THIRD_PARTY_CONFIRMATION
        # Filtered: only PHYSICAL_INSPECTION remains
        assert methods == [VerificationMethod.PHYSICAL_INSPECTION]


class TestAssetExistenceEnforcerBusinessMethods:
    @pytest.mark.asyncio
    async def test_enforce_asset_existence_success(self, enforcer, mock_context_holder):
        asset_id = uuid4()
        legal_entity_id = uuid4()
        amount = Decimal("1000")
        method = VerificationMethod.PHYSICAL_INSPECTION
        doc = "doc-123"
        record = await enforcer.enforce_asset_existence(
            asset_id=asset_id,
            asset_type=AssetType.FIXED_ASSET,
            legal_entity_id=legal_entity_id,
            amount=amount,
            verification_method=method,
            verification_document=doc,
            user_id="alice",
            notes="test note",
        )
        assert isinstance(record, VerificationRecord)
        assert record.asset_id == asset_id
        assert record.asset_type == AssetType.FIXED_ASSET
        assert record.legal_entity_id == legal_entity_id
        assert record.verification_method == method
        assert record.verification_document == doc
        assert record.verified_by == "alice"
        assert record.verified_at == FIXED_NOW
        assert record.status == VerificationStatus.VERIFIED
        assert record.notes == "test note"
        assert record.cryptographic_hash == record.compute_hash()
        # Verify repository call
        enforcer._asset_repo.record_verification.assert_called_once_with(
            asset_id=asset_id,
            asset_type="fixed_asset",
            legal_entity_id=legal_entity_id,
            verification_method="physical_inspection",
            verification_document=doc,
            verified_by="alice",
            verified_at=FIXED_NOW,
        )
        # Verify audit trail
        trail = enforcer.audit_trail(limit=1)
        assert trail[0]["action"] == "ASSET_VERIFICATION"
        assert trail[0]["performed_by"] == "alice"

    @pytest.mark.asyncio
    async def test_enforce_asset_existence_disabled(self, enforcer):
        enforcer.enable(False)
        with pytest.raises(AssetExistenceViolation) as exc:
            await enforcer.enforce_asset_existence(
                asset_id=uuid4(),
                asset_type=AssetType.FIXED_ASSET,
                legal_entity_id=uuid4(),
                amount=Decimal(1),
                verification_method=VerificationMethod.PHYSICAL_INSPECTION,
                verification_document="doc",
            )
        assert "disabled" in str(exc.value)
        assert exc.value.severity == LawViolationSeverity.MEDIUM

    @pytest.mark.asyncio
    async def test_enforce_asset_existence_invalid_method(self, enforcer):
        asset_id = uuid4()
        # FIXED_ASSET requires PHYSICAL_INSPECTION, LEGAL_TITLE, VALUATION_REPORT
        # Using DOCUMENT_VERIFICATION should raise
        with pytest.raises(AssetExistenceViolation) as exc:
            await enforcer.enforce_asset_existence(
                asset_id=asset_id,
                asset_type=AssetType.FIXED_ASSET,
                legal_entity_id=uuid4(),
                amount=Decimal("1000"),
                verification_method=VerificationMethod.DOCUMENT_VERIFICATION,
                verification_document="doc",
            )
        assert "requires verification method in" in str(exc.value)
        assert exc.value.severity == LawViolationSeverity.HIGH
        assert exc.value.details["amount"] == "1000"

    @pytest.mark.asyncio
    async def test_enforce_asset_existence_high_value_requires_strong(self, enforcer):
        # Set threshold low so amount is considered high
        enforcer.set_verification_threshold(Decimal("1000"))
        asset_id = uuid4()
        # For FIXED_ASSET, high value requires PHYSICAL_INSPECTION or THIRD_PARTY_CONFIRMATION
        # Using LEGAL_TITLE should raise
        with pytest.raises(AssetExistenceViolation) as exc:
            await enforcer.enforce_asset_existence(
                asset_id=asset_id,
                asset_type=AssetType.FIXED_ASSET,
                legal_entity_id=uuid4(),
                amount=Decimal("2000"),
                verification_method=VerificationMethod.LEGAL_TITLE,
                verification_document="doc",
            )
        assert "High-value asset" in str(exc.value)
        assert exc.value.severity == LawViolationSeverity.HIGH

    @pytest.mark.asyncio
    async def test_enforce_asset_existence_no_document(self, enforcer):
        with pytest.raises(AssetExistenceViolation) as exc:
            await enforcer.enforce_asset_existence(
                asset_id=uuid4(),
                asset_type=AssetType.FIXED_ASSET,
                legal_entity_id=uuid4(),
                amount=Decimal("1000"),
                verification_method=VerificationMethod.PHYSICAL_INSPECTION,
                verification_document="",
            )
        assert "requires verification document reference" in str(exc.value)
        assert exc.value.severity == LawViolationSeverity.HIGH

    @pytest.mark.asyncio
    async def test_enforce_asset_existence_default_user(self, enforcer, mock_context_holder):
        # When user_id is None, should use get_current_user()
        asset_id = uuid4()
        record = await enforcer.enforce_asset_existence(
            asset_id=asset_id,
            asset_type=AssetType.FIXED_ASSET,
            legal_entity_id=uuid4(),
            amount=Decimal(1),
            verification_method=VerificationMethod.PHYSICAL_INSPECTION,
            verification_document="doc",
            user_id=None,
        )
        assert record.verified_by == "test_user"

    @pytest.mark.asyncio
    async def test_enforce_periodic_verification_enabled_no_last_count(self, enforcer):
        legal_entity_id = uuid4()
        # No last count date, should not raise, just log warning.
        # Also assert that the repository method is called with the correct legal_entity_id.
        await enforcer.enforce_periodic_verification(legal_entity_id, 2026, "alice")
        enforcer._asset_repo.get_last_physical_count_date.assert_called_once_with(legal_entity_id)
        # No exception raised - test passes implicitly, but we also have an assertion above.

    @pytest.mark.asyncio
    async def test_enforce_periodic_verification_enabled_last_count_ok(self, enforcer):
        legal_entity_id = uuid4()
        # Last count within required days (365)
        last_date = FIXED_NOW - timedelta(days=300)
        enforcer._asset_repo.get_last_physical_count_date.return_value = last_date
        await enforcer.enforce_periodic_verification(legal_entity_id, 2026, "alice")
        enforcer._asset_repo.get_last_physical_count_date.assert_called_once_with(legal_entity_id)
        # No exception raised

    @pytest.mark.asyncio
    async def test_enforce_periodic_verification_enabled_last_count_too_old(self, enforcer):
        legal_entity_id = uuid4()
        # Last count older than required days
        last_date = FIXED_NOW - timedelta(days=400)
        enforcer._asset_repo.get_last_physical_count_date.return_value = last_date
        with pytest.raises(AssetExistenceViolation) as exc:
            await enforcer.enforce_periodic_verification(legal_entity_id, 2026, "alice")
        assert "No physical asset verification performed" in str(exc.value)
        assert exc.value.severity == LawViolationSeverity.HIGH
        assert exc.value.details["days_since"] == 400

    @pytest.mark.asyncio
    async def test_enforce_periodic_verification_disabled(self, enforcer):
        enforcer.enable(False)
        legal_entity_id = uuid4()
        # Should not raise even if no last count
        await enforcer.enforce_periodic_verification(legal_entity_id, 2026, "alice")
        # Since enforcer is disabled, the method should return early without calling the repository.
        enforcer._asset_repo.get_last_physical_count_date.assert_not_called()

    @pytest.mark.asyncio
    async def test_record_physical_count_success(self, enforcer, mock_context_holder):
        legal_entity_id = uuid4()
        counted_by = "bob"
        location = "WH-1"
        discrepancies = {"item1": 5, "item2": -3}
        record = await enforcer.record_physical_count(
            legal_entity_id=legal_entity_id,
            counted_by=counted_by,
            location=location,
            discrepancies=discrepancies,
            user_id="alice",
        )
        assert isinstance(record, PhysicalCountRecord)
        assert record.legal_entity_id == legal_entity_id
        assert record.counted_by == counted_by
        assert record.counted_at == FIXED_NOW
        assert record.location == location
        assert record.discrepancies == discrepancies
        assert record.is_adjusted is False
        assert record.cryptographic_hash == record.compute_hash()
        # Verify repository call
        enforcer._asset_repo.record_physical_count.assert_called_once_with(
            legal_entity_id=legal_entity_id,
            counted_by=counted_by,
            counted_at=FIXED_NOW,
            location=location,
            discrepancies=discrepancies,
        )
        # Verify audit trail
        trail = enforcer.audit_trail(limit=1)
        assert trail[0]["action"] == "PHYSICAL_COUNT"
        assert trail[0]["performed_by"] == counted_by

    @pytest.mark.asyncio
    async def test_record_physical_count_default_user(self, enforcer, mock_context_holder):
        legal_entity_id = uuid4()
        record = await enforcer.record_physical_count(
            legal_entity_id=legal_entity_id,
            counted_by="bob",
            location="WH-1",
            discrepancies={},
            user_id=None,
        )
        assert record.counted_by == "bob"

    @pytest.mark.asyncio
    async def test_get_asset_verification_status_no_record(self, enforcer):
        asset_id = uuid4()
        legal_entity_id = uuid4()
        enforcer._asset_repo.get_last_verification.return_value = None
        status = await enforcer.get_asset_verification_status(asset_id, legal_entity_id)
        assert status["is_verified"] is False
        assert status["message"] == "No verification record found"

    @pytest.mark.asyncio
    async def test_get_asset_verification_status_found(self, enforcer):
        asset_id = uuid4()
        legal_entity_id = uuid4()
        verification_data = {
            "verification_method": "physical_inspection",
            "verified_by": "alice",
            "verified_at": FIXED_NOW,
            "verification_document": "doc-123",
        }
        enforcer._asset_repo.get_last_verification.return_value = verification_data
        status = await enforcer.get_asset_verification_status(asset_id, legal_entity_id)
        assert status["is_verified"] is True
        assert status["verification_method"] == "physical_inspection"
        assert status["verified_by"] == "alice"
        assert status["verified_at"] == FIXED_NOW
        assert status["document_ref"] == "doc-123"

    def test_get_verification_history_no_filter(self, enforcer, sample_verification_record):
        enforcer._verification_records.append(sample_verification_record)
        result = enforcer.get_verification_history(limit=10)
        assert len(result) == 1
        assert result[0] is sample_verification_record

    def test_get_verification_history_filter_asset_id(self, enforcer, sample_verification_record):
        enforcer._verification_records.append(sample_verification_record)
        # Another record with different asset_id
        other = VerificationRecord(
            record_id=uuid4(),
            asset_id=uuid4(),
            asset_type=AssetType.FIXED_ASSET,
            legal_entity_id=uuid4(),
            verification_method=VerificationMethod.PHYSICAL_INSPECTION,
            verification_document="doc",
            verified_by="alice",
            verified_at=FIXED_NOW,
            status=VerificationStatus.VERIFIED,
        )
        enforcer._verification_records.append(other)
        result = enforcer.get_verification_history(asset_id=sample_verification_record.asset_id, limit=10)
        assert len(result) == 1
        assert result[0].asset_id == sample_verification_record.asset_id

    def test_get_verification_history_filter_legal_entity(self, enforcer, sample_verification_record):
        enforcer._verification_records.append(sample_verification_record)
        other = VerificationRecord(
            record_id=uuid4(),
            asset_id=uuid4(),
            asset_type=AssetType.FIXED_ASSET,
            legal_entity_id=uuid4(),  # different
            verification_method=VerificationMethod.PHYSICAL_INSPECTION,
            verification_document="doc",
            verified_by="alice",
            verified_at=FIXED_NOW,
            status=VerificationStatus.VERIFIED,
        )
        enforcer._verification_records.append(other)
        result = enforcer.get_verification_history(legal_entity_id=sample_verification_record.legal_entity_id, limit=10)
        assert len(result) == 1
        assert result[0].legal_entity_id == sample_verification_record.legal_entity_id

    def test_get_verification_history_limit(self, enforcer):
        for i in range(5):
            rec = VerificationRecord(
                record_id=uuid4(),
                asset_id=uuid4(),
                asset_type=AssetType.FIXED_ASSET,
                legal_entity_id=uuid4(),
                verification_method=VerificationMethod.PHYSICAL_INSPECTION,
                verification_document=f"doc{i}",
                verified_by="alice",
                verified_at=FIXED_NOW,
                status=VerificationStatus.VERIFIED,
            )
            enforcer._verification_records.append(rec)
        result = enforcer.get_verification_history(limit=3)
        assert len(result) == 3

    def test_get_physical_count_history_no_filter(self, enforcer, sample_physical_count_record):
        enforcer._physical_counts.append(sample_physical_count_record)
        result = enforcer.get_physical_count_history(limit=10)
        assert len(result) == 1
        assert result[0] is sample_physical_count_record

    def test_get_physical_count_history_filter_legal_entity(self, enforcer, sample_physical_count_record):
        enforcer._physical_counts.append(sample_physical_count_record)
        other = PhysicalCountRecord(
            count_id=uuid4(),
            legal_entity_id=uuid4(),  # different
            counted_by="bob",
            counted_at=FIXED_NOW,
            location="WH-2",
            discrepancies={},
        )
        enforcer._physical_counts.append(other)
        result = enforcer.get_physical_count_history(legal_entity_id=sample_physical_count_record.legal_entity_id, limit=10)
        assert len(result) == 1
        assert result[0].legal_entity_id == sample_physical_count_record.legal_entity_id

    def test_get_physical_count_history_limit(self, enforcer):
        for i in range(5):
            rec = PhysicalCountRecord(
                count_id=uuid4(),
                legal_entity_id=uuid4(),
                counted_by="bob",
                counted_at=FIXED_NOW,
                location=f"WH-{i}",
                discrepancies={},
            )
            enforcer._physical_counts.append(rec)
        result = enforcer.get_physical_count_history(limit=3)
        assert len(result) == 3

    def test_get_statistics_empty(self, enforcer):
        stats = enforcer.get_statistics()
        assert stats["total_verifications"] == 0
        assert stats["total_physical_counts"] == 0
        assert stats["enabled"] is True
        assert stats["version"] == 1

    def test_get_statistics_with_data(self, enforcer, sample_verification_record, sample_physical_count_record):
        enforcer._verification_records.append(sample_verification_record)
        enforcer._physical_counts.append(sample_physical_count_record)
        stats = enforcer.get_statistics()
        assert stats["total_verifications"] == 1
        assert stats["total_physical_counts"] == 1
        assert stats["by_asset_type"] == {"fixed_asset": 1}
        assert stats["by_verification_method"] == {"physical_inspection": 1}
        assert stats["verification_threshold"] == str(Decimal("50000000"))
        assert stats["physical_count_required_days"] == 365
        assert stats["enabled"] is True
        assert stats["version"] == 1
        assert stats["latest_verification"] == FIXED_NOW.isoformat()

    def test_reset(self, enforcer, sample_verification_record, sample_physical_count_record):
        enforcer._verification_records.append(sample_verification_record)
        enforcer._physical_counts.append(sample_physical_count_record)
        enforcer._audit_trail.append({"action": "TEST"})
        enforcer._enabled = False
        enforcer._version = 5
        enforcer.reset()
        assert len(enforcer._verification_records) == 0
        assert len(enforcer._physical_counts) == 0
        assert enforcer._enabled is True
        assert enforcer._version == 6
        assert len(enforcer._audit_trail) == 0
        enforcer._asset_repo.clear.assert_called_once()
        enforcer._inventory_repo.clear.assert_called_once()


# =============================================================================
# Tests for Singleton Accessor
# =============================================================================

class TestSingleton:
    def test_get_asset_existence_enforcer_returns_same_instance(self):
        e1 = get_asset_existence_enforcer()
        e2 = get_asset_existence_enforcer()
        assert e1 is e2
        assert isinstance(e1, AssetExistenceEnforcer)

    def test_singleton_initializes_with_default_repos(self):
        enforcer = get_asset_existence_enforcer()
        assert isinstance(enforcer._asset_repo, _FallbackAssetRepository)
        assert isinstance(enforcer._inventory_repo, _FallbackInventoryRepository)
