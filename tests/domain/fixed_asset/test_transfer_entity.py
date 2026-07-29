# test_transfer_entity.py
# Comprehensive tests for domain/fixed_asset/transfer_entity.py

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

# We need to import FixedAsset for type checking and mocking
from domain.fixed_asset.asset_entity import AssetStatus, FixedAsset
from domain.fixed_asset.transfer_entity import (
    AssetNotTransferableError,
    AssetTransfer,
    InvalidStatusTransitionError,
    InvalidTransferDateError,
    SameSourceDestinationError,
    TransferEntity,
    TransferError,
    TransferRepository,
    TransferStatus,
    TransferType,
    get_transfer_summary,
    is_transfer_allowed,
)


# -------------------- Fixtures --------------------
@pytest.fixture
def sample_asset():
    """Create a mock FixedAsset for testing."""
    asset = MagicMock(spec=FixedAsset)
    asset.id = uuid4()
    asset.asset_code = "AST-001"
    asset.name = "Test Asset"
    asset.acquisition_date = date(2020, 1, 1)
    asset.is_disposed = False
    asset.status = AssetStatus.ACTIVE
    # Make sure status has can_transfer method
    asset.status.can_transfer = MagicMock(return_value=True)
    # Ensure display_name method exists
    asset.status.display_name = MagicMock(return_value="Active")
    return asset


@pytest.fixture
def sample_transfer(sample_asset):
    """Create a basic TransferEntity in DRAFT status."""
    now = datetime.now()
    return TransferEntity(
        transfer_id=uuid4(),
        asset_id=sample_asset.id,
        asset_code=sample_asset.asset_code,
        asset_name=sample_asset.name,
        transfer_date=date.today(),
        transfer_type=TransferType.DEPARTMENT,
        source="Dept A",
        destination="Dept B",
        status=TransferStatus.DRAFT,
        reason="Test reason",
        notes="Test notes",
        created_at=now,
        updated_at=now,
        created_by=uuid4(),
        updated_by=uuid4(),
        version=1,
    )


@pytest.fixture
def approved_transfer(sample_transfer):
    """Return an approved transfer."""
    return sample_transfer.approve(uuid4())


@pytest.fixture
def completed_transfer(approved_transfer):
    """Return a completed transfer."""
    return approved_transfer.complete(uuid4())


@pytest.fixture
def cancelled_transfer(sample_transfer):
    """Return a cancelled transfer."""
    return sample_transfer.cancel(uuid4(), "Cancelled by test")


# -------------------- Tests for Enums --------------------
class TestTransferType:
    def test_members(self):
        assert TransferType.DEPARTMENT.value == "department"
        assert TransferType.LOCATION.value == "location"
        assert TransferType.COST_CENTER.value == "cost_center"
        assert TransferType.CUSTODIAN.value == "custodian"

    def test_display_name(self):
        assert TransferType.DEPARTMENT.display_name() == "Transfer Departemen"
        assert TransferType.LOCATION.display_name() == "Transfer Lokasi"
        assert TransferType.COST_CENTER.display_name() == "Transfer Pusat Biaya"
        assert TransferType.CUSTODIAN.display_name() == "Transfer Penanggung Jawab"

    def test_requires_approval(self):
        assert TransferType.DEPARTMENT.requires_approval() is True
        assert TransferType.COST_CENTER.requires_approval() is True
        assert TransferType.LOCATION.requires_approval() is False
        assert TransferType.CUSTODIAN.requires_approval() is False

    def test_from_string_valid(self):
        assert TransferType.from_string("department") == TransferType.DEPARTMENT
        assert TransferType.from_string("LOCATION") == TransferType.LOCATION
        assert TransferType.from_string("cost_center") == TransferType.COST_CENTER
        assert TransferType.from_string("custodian") == TransferType.CUSTODIAN

    def test_from_string_invalid(self):
        assert TransferType.from_string("invalid") is None
        assert TransferType.from_string("") is None


class TestTransferStatus:
    def test_members(self):
        assert TransferStatus.DRAFT.value == "draft"
        assert TransferStatus.APPROVED.value == "approved"
        assert TransferStatus.COMPLETED.value == "completed"
        assert TransferStatus.CANCELLED.value == "cancelled"

    def test_can_edit(self):
        assert TransferStatus.DRAFT.can_edit() is True
        assert TransferStatus.APPROVED.can_edit() is False
        assert TransferStatus.COMPLETED.can_edit() is False
        assert TransferStatus.CANCELLED.can_edit() is False

    def test_can_approve(self):
        assert TransferStatus.DRAFT.can_approve() is True
        assert TransferStatus.APPROVED.can_approve() is False
        assert TransferStatus.COMPLETED.can_approve() is False
        assert TransferStatus.CANCELLED.can_approve() is False

    def test_can_complete(self):
        assert TransferStatus.APPROVED.can_complete() is True
        assert TransferStatus.DRAFT.can_complete() is False
        assert TransferStatus.COMPLETED.can_complete() is False
        assert TransferStatus.CANCELLED.can_complete() is False

    def test_can_cancel(self):
        assert TransferStatus.DRAFT.can_cancel() is True
        assert TransferStatus.APPROVED.can_cancel() is True
        assert TransferStatus.COMPLETED.can_cancel() is False
        assert TransferStatus.CANCELLED.can_cancel() is False

    def test_display_name(self):
        assert TransferStatus.DRAFT.display_name() == "Draft"
        assert TransferStatus.APPROVED.display_name() == "Disetujui"
        assert TransferStatus.COMPLETED.display_name() == "Selesai"
        assert TransferStatus.CANCELLED.display_name() == "Dibatalkan"

    def test_from_string_valid(self):
        assert TransferStatus.from_string("draft") == TransferStatus.DRAFT
        assert TransferStatus.from_string("APPROVED") == TransferStatus.APPROVED
        assert TransferStatus.from_string("completed") == TransferStatus.COMPLETED
        assert TransferStatus.from_string("cancelled") == TransferStatus.CANCELLED

    def test_from_string_invalid(self):
        assert TransferStatus.from_string("invalid") is None


# -------------------- Tests for Helper Functions --------------------
class TestHelpers:
    def test_validate_transfer_date_valid(self):
        from domain.fixed_asset.transfer_entity import _validate_transfer_date
        # Today's date is okay
        _validate_transfer_date(date.today(), date(2020, 1, 1))
        # Past date is okay
        _validate_transfer_date(date(2025, 1, 1), date(2020, 1, 1))

    def test_validate_transfer_date_future(self):
        from domain.fixed_asset.transfer_entity import _validate_transfer_date
        future = date.today() + timedelta(days=1)
        with pytest.raises(InvalidTransferDateError, match="cannot be in the future"):
            _validate_transfer_date(future, date(2020, 1, 1))

    def test_validate_transfer_date_before_acquisition(self):
        from domain.fixed_asset.transfer_entity import _validate_transfer_date
        with pytest.raises(InvalidTransferDateError, match="cannot be before acquisition"):
            _validate_transfer_date(date(2019, 1, 1), date(2020, 1, 1))

    def test_validate_source_destination_same(self):
        from domain.fixed_asset.transfer_entity import _validate_source_destination
        with pytest.raises(SameSourceDestinationError, match="cannot be the same"):
            _validate_source_destination("A", "A")

    def test_validate_source_destination_different(self):
        from domain.fixed_asset.transfer_entity import _validate_source_destination
        # Should not raise
        _validate_source_destination("A", "B")

    def test_validate_string_field(self):
        from domain.fixed_asset.transfer_entity import _validate_string_field
        assert _validate_string_field("  hello  ", "field") == "hello"
        with pytest.raises(TransferError, match="field must be at least"):
            _validate_string_field("", "field", min_len=2)
        with pytest.raises(TransferError, match="field must not exceed"):
            _validate_string_field("a"*300, "field", max_len=200)

    def test_validate_reason(self):
        from domain.fixed_asset.transfer_entity import _validate_reason
        assert _validate_reason("  reason  ") == "reason"
        with pytest.raises(TransferError, match="not exceed 500 characters"):
            _validate_reason("a"*501)

    def test_validate_notes(self):
        from domain.fixed_asset.transfer_entity import _validate_notes
        assert _validate_notes("  notes  ") == "notes"
        with pytest.raises(TransferError, match="not exceed 1000 characters"):
            _validate_notes("a"*1001)

    def test_validate_asset_code(self):
        from domain.fixed_asset.transfer_entity import _validate_asset_code
        assert _validate_asset_code("  CODE  ") == "CODE"
        with pytest.raises(TransferError, match="at least 2 characters"):
            _validate_asset_code("A")
        with pytest.raises(TransferError, match="not exceed 30 characters"):
            _validate_asset_code("A"*31)

    def test_validate_asset_name(self):
        from domain.fixed_asset.transfer_entity import _validate_asset_name
        assert _validate_asset_name("  Name  ") == "Name"
        with pytest.raises(TransferError, match="at least 2 characters"):
            _validate_asset_name("A")
        with pytest.raises(TransferError, match="not exceed 200 characters"):
            _validate_asset_name("A"*201)

    def test_validate_asset_transferable(self, sample_asset):
        from domain.fixed_asset.transfer_entity import _validate_asset_transferable
        # Should not raise for active asset
        _validate_asset_transferable(sample_asset)
        # Disposed asset
        sample_asset.is_disposed = True
        with pytest.raises(AssetNotTransferableError, match="already disposed"):
            _validate_asset_transferable(sample_asset)
        sample_asset.is_disposed = False
        # Asset not transferable due to status
        sample_asset.status.can_transfer.return_value = False
        with pytest.raises(AssetNotTransferableError, match="cannot be transferred"):
            _validate_asset_transferable(sample_asset)


# -------------------- Tests for TransferEntity --------------------
class TestTransferEntity:
    def test_construction_valid(self, sample_transfer):
        assert sample_transfer.transfer_id is not None
        assert sample_transfer.asset_code == "AST-001"
        assert sample_transfer.source == "Dept A"
        assert sample_transfer.destination == "Dept B"
        assert sample_transfer.status == TransferStatus.DRAFT
        assert sample_transfer.version == 1
        assert sample_transfer.created_at.tzinfo is not None

    def test_construction_invalid_asset_code(self, sample_asset):
        with pytest.raises(TransferError, match="at least 2 characters"):
            TransferEntity(
                transfer_id=uuid4(),
                asset_id=sample_asset.id,
                asset_code="A",
                asset_name="Test",
                transfer_date=date.today(),
                transfer_type=TransferType.DEPARTMENT,
                source="A",
                destination="B",
                status=TransferStatus.DRAFT,
            )

    def test_construction_invalid_source_empty(self, sample_asset):
        with pytest.raises(TransferError, match="Source cannot be empty"):
            TransferEntity(
                transfer_id=uuid4(),
                asset_id=sample_asset.id,
                asset_code="CODE",
                asset_name="Test",
                transfer_date=date.today(),
                transfer_type=TransferType.DEPARTMENT,
                source="",
                destination="B",
                status=TransferStatus.DRAFT,
            )

    def test_construction_source_destination_same(self, sample_asset):
        with pytest.raises(SameSourceDestinationError, match="cannot be the same"):
            TransferEntity(
                transfer_id=uuid4(),
                asset_id=sample_asset.id,
                asset_code="CODE",
                asset_name="Test",
                transfer_date=date.today(),
                transfer_type=TransferType.DEPARTMENT,
                source="A",
                destination="A",
                status=TransferStatus.DRAFT,
            )

    def test_construction_status_inconsistent_approved(self, sample_asset):
        with pytest.raises(TransferError, match="must have approved_by"):
            TransferEntity(
                transfer_id=uuid4(),
                asset_id=sample_asset.id,
                asset_code="CODE",
                asset_name="Test",
                transfer_date=date.today(),
                transfer_type=TransferType.DEPARTMENT,
                source="A",
                destination="B",
                status=TransferStatus.APPROVED,
                approved_by=None,
            )

    def test_construction_status_inconsistent_completed(self, sample_asset):
        with pytest.raises(TransferError, match="must have completed_by"):
            TransferEntity(
                transfer_id=uuid4(),
                asset_id=sample_asset.id,
                asset_code="CODE",
                asset_name="Test",
                transfer_date=date.today(),
                transfer_type=TransferType.DEPARTMENT,
                source="A",
                destination="B",
                status=TransferStatus.COMPLETED,
                completed_by=None,
            )

    def test_construction_status_inconsistent_cancelled(self, sample_asset):
        with pytest.raises(TransferError, match="must have cancelled_by"):
            TransferEntity(
                transfer_id=uuid4(),
                asset_id=sample_asset.id,
                asset_code="CODE",
                asset_name="Test",
                transfer_date=date.today(),
                transfer_type=TransferType.DEPARTMENT,
                source="A",
                destination="B",
                status=TransferStatus.CANCELLED,
                cancelled_by=None,
            )

    def test_construction_invalid_version(self, sample_asset):
        with pytest.raises(TransferError, match="Version must be >= 1"):
            TransferEntity(
                transfer_id=uuid4(),
                asset_id=sample_asset.id,
                asset_code="CODE",
                asset_name="Test",
                transfer_date=date.today(),
                transfer_type=TransferType.DEPARTMENT,
                source="A",
                destination="B",
                status=TransferStatus.DRAFT,
                version=0,
            )

    # ---- Properties ----
    def test_is_properties(self, sample_transfer, approved_transfer, completed_transfer, cancelled_transfer):
        assert sample_transfer.is_draft is True
        assert sample_transfer.is_approved is False
        assert sample_transfer.is_completed is False
        assert sample_transfer.is_cancelled is False

        assert approved_transfer.is_approved is True
        assert approved_transfer.is_draft is False

        assert completed_transfer.is_completed is True
        assert cancelled_transfer.is_cancelled is True

    def test_can_properties(self, sample_transfer, approved_transfer, completed_transfer):
        assert sample_transfer.can_edit is True
        assert sample_transfer.can_approve is True
        assert sample_transfer.can_complete is False
        assert sample_transfer.can_cancel is True

        assert approved_transfer.can_edit is False
        assert approved_transfer.can_approve is False
        assert approved_transfer.can_complete is True
        assert approved_transfer.can_cancel is True

        assert completed_transfer.can_edit is False
        assert completed_transfer.can_approve is False
        assert completed_transfer.can_complete is False
        assert completed_transfer.can_cancel is False

    def test_display(self, sample_transfer):
        expected = f"{sample_transfer.asset_code}: {sample_transfer.source} → {sample_transfer.destination} (Transfer Departemen)"
        assert sample_transfer.display == expected

    def test_duration_days(self, sample_transfer, completed_transfer):
        # For draft, duration is from creation to today
        assert sample_transfer.duration_days >= 0
        # For completed, duration is from creation to completion
        assert completed_transfer.duration_days >= 0
        # Should be number of days between creation and completion
        days = (completed_transfer.completed_at.date() - completed_transfer.created_at.date()).days
        assert completed_transfer.duration_days == days

    # ---- Factory Methods ----
    def test_create_department_transfer(self, sample_asset):
        created_by = uuid4()
        transfer = TransferEntity.create_department_transfer(
            asset=sample_asset,
            transfer_date=date.today(),
            source_department="Dept A",
            destination_department="Dept B",
            created_by=created_by,
            reason="Test reason",
            notes="Test notes",
        )
        assert transfer.transfer_type == TransferType.DEPARTMENT
        assert transfer.status == TransferStatus.DRAFT
        assert transfer.source == "Dept A"
        assert transfer.destination == "Dept B"
        assert transfer.created_by == created_by
        assert transfer.updated_by == created_by
        assert transfer.reason == "Test reason"
        assert transfer.notes == "Test notes"

    def test_create_department_transfer_with_invalid_asset(self, sample_asset):
        sample_asset.is_disposed = True
        with pytest.raises(AssetNotTransferableError, match="already disposed"):
            TransferEntity.create_department_transfer(
                asset=sample_asset,
                transfer_date=date.today(),
                source_department="A",
                destination_department="B",
                created_by=uuid4(),
            )

    def test_create_location_transfer(self, sample_asset):
        transfer = TransferEntity.create_location_transfer(
            asset=sample_asset,
            transfer_date=date.today(),
            source_location="Loc A",
            destination_location="Loc B",
            created_by=uuid4(),
        )
        assert transfer.transfer_type == TransferType.LOCATION
        assert transfer.source == "Loc A"
        assert transfer.destination == "Loc B"

    def test_create_cost_center_transfer(self, sample_asset):
        transfer = TransferEntity.create_cost_center_transfer(
            asset=sample_asset,
            transfer_date=date.today(),
            source_cost_center="CC A",
            destination_cost_center="CC B",
            created_by=uuid4(),
        )
        assert transfer.transfer_type == TransferType.COST_CENTER
        assert transfer.source == "CC A"
        assert transfer.destination == "CC B"

    def test_create_custodian_transfer(self, sample_asset):
        transfer = TransferEntity.create_custodian_transfer(
            asset=sample_asset,
            transfer_date=date.today(),
            source_custodian="Cust A",
            destination_custodian="Cust B",
            created_by=uuid4(),
        )
        assert transfer.transfer_type == TransferType.CUSTODIAN
        assert transfer.source == "Cust A"
        assert transfer.destination == "Cust B"

    # ---- Business Logic ----
    def test_approve(self, sample_transfer):
        approver = uuid4()
        approved = sample_transfer.approve(approver)
        assert approved.status == TransferStatus.APPROVED
        assert approved.approved_by == approver
        assert approved.approved_at is not None
        assert approved.updated_by == approver
        assert approved.version == sample_transfer.version + 1

    def test_approve_invalid_status(self, approved_transfer):
        with pytest.raises(InvalidStatusTransitionError, match="Cannot approve"):
            approved_transfer.approve(uuid4())

    def test_complete(self, approved_transfer):
        completer = uuid4()
        completed = approved_transfer.complete(completer)
        assert completed.status == TransferStatus.COMPLETED
        assert completed.completed_by == completer
        assert completed.completed_at is not None
        assert completed.updated_by == completer
        assert completed.version == approved_transfer.version + 1

    def test_complete_invalid_status(self, sample_transfer):
        with pytest.raises(InvalidStatusTransitionError, match="Cannot complete"):
            sample_transfer.complete(uuid4())

    def test_cancel(self, sample_transfer):
        canceller = uuid4()
        cancelled = sample_transfer.cancel(canceller, "Reason")
        assert cancelled.status == TransferStatus.CANCELLED
        assert cancelled.cancelled_by == canceller
        assert cancelled.cancelled_at is not None
        assert cancelled.cancel_reason == "Reason"
        assert cancelled.updated_by == canceller
        assert cancelled.version == sample_transfer.version + 1

    def test_cancel_invalid_status(self, completed_transfer):
        with pytest.raises(InvalidStatusTransitionError, match="Cannot cancel"):
            completed_transfer.cancel(uuid4(), "reason")

    def test_update_reason(self, sample_transfer):
        new_reason = "Updated reason"
        updated_by = uuid4()
        updated = sample_transfer.update_reason(new_reason, updated_by)
        assert updated.reason == "Updated reason"
        assert updated.updated_by == updated_by
        assert updated.version == sample_transfer.version + 1

    def test_update_reason_invalid_status(self, approved_transfer):
        with pytest.raises(InvalidStatusTransitionError, match="Cannot edit"):
            approved_transfer.update_reason("new", uuid4())

    def test_update_notes(self, sample_transfer):
        new_notes = "Updated notes"
        updated_by = uuid4()
        updated = sample_transfer.update_notes(new_notes, updated_by)
        assert updated.notes == "Updated notes"
        assert updated.updated_by == updated_by
        assert updated.version == sample_transfer.version + 1

    def test_update_notes_invalid_status(self, approved_transfer):
        with pytest.raises(InvalidStatusTransitionError, match="Cannot edit"):
            approved_transfer.update_notes("new", uuid4())

    # ---- Serialization ----
    def test_to_dict(self, sample_transfer):
        d = sample_transfer.to_dict()
        assert d["transfer_id"] == str(sample_transfer.transfer_id)
        assert d["asset_id"] == str(sample_transfer.asset_id)
        assert d["asset_code"] == "AST-001"
        assert d["transfer_type"] == "department"
        assert d["transfer_type_display"] == "Transfer Departemen"
        assert d["status"] == "draft"
        assert d["status_display"] == "Draft"
        assert d["source"] == "Dept A"
        assert d["destination"] == "Dept B"
        assert d["reason"] == "Test reason"
        assert d["version"] == 1
        assert "duration_days" in d
        assert d["can_approve"] is True
        assert d["can_complete"] is False
        assert d["can_cancel"] is True

    def test_from_dict(self, sample_transfer):
        d = sample_transfer.to_dict()
        # from_dict expects dates and UUIDs in specific format; we need to convert strings appropriately
        restored = TransferEntity.from_dict(d)
        assert restored.transfer_id == sample_transfer.transfer_id
        assert restored.asset_id == sample_transfer.asset_id
        assert restored.asset_code == sample_transfer.asset_code
        assert restored.transfer_type == sample_transfer.transfer_type
        assert restored.source == sample_transfer.source
        assert restored.destination == sample_transfer.destination
        assert restored.status == sample_transfer.status
        assert restored.reason == sample_transfer.reason
        assert restored.notes == sample_transfer.notes
        assert restored.version == sample_transfer.version

    def test_from_dict_invalid_type(self, sample_transfer):
        d = sample_transfer.to_dict()
        d["transfer_type"] = "invalid"
        with pytest.raises(TransferError, match="Invalid transfer_type"):
            TransferEntity.from_dict(d)

    def test_from_dict_invalid_status(self, sample_transfer):
        d = sample_transfer.to_dict()
        d["status"] = "invalid"
        with pytest.raises(TransferError, match="Invalid status"):
            TransferEntity.from_dict(d)

    def test_to_db_record(self, sample_transfer):
        rec = sample_transfer.to_db_record()
        assert rec["transfer_id"] == sample_transfer.transfer_id
        assert rec["asset_id"] == sample_transfer.asset_id
        assert rec["asset_code"] == sample_transfer.asset_code
        assert rec["transfer_type"] == "department"
        assert rec["status"] == "draft"

    # ---- Dunder methods ----
    def test_str(self, sample_transfer):
        assert str(sample_transfer) == sample_transfer.display

    def test_repr(self, sample_transfer):
        expected = f"TransferEntity(asset={sample_transfer.asset_code}, status=draft)"
        assert repr(sample_transfer) == expected

    def test_equality(self, sample_transfer):
        same = sample_transfer
        assert sample_transfer == same
        different = sample_transfer.clone()
        # clone changes name, so not equal
        assert sample_transfer != different
        assert sample_transfer != "not a transfer"

    def test_hash(self, sample_transfer):
        assert hash(sample_transfer) == hash(sample_transfer.transfer_id)


# -------------------- Tests for Module-level Functions --------------------
class TestModuleFunctions:
    def test_is_transfer_allowed(self, sample_asset):
        allowed, msg = is_transfer_allowed(sample_asset)
        assert allowed is True
        assert msg == ""
        sample_asset.is_disposed = True
        allowed, msg = is_transfer_allowed(sample_asset)
        assert allowed is False
        assert "disposed" in msg
        sample_asset.is_disposed = False
        sample_asset.status.can_transfer.return_value = False
        allowed, msg = is_transfer_allowed(sample_asset)
        assert allowed is False
        assert "cannot be transferred" in msg

    def test_get_transfer_summary(self, sample_transfer):
        transfers = [sample_transfer]
        summary = get_transfer_summary(transfers)
        assert summary["total"] == 1
        assert summary["by_status"]["draft"] == 1
        assert summary["by_type"]["department"] == 1
        # Add more transfers
        transfer2 = sample_transfer.clone()
        transfer2.status = TransferStatus.APPROVED
        transfer2.transfer_type = TransferType.LOCATION
        transfers.append(transfer2)
        summary2 = get_transfer_summary(transfers)
        assert summary2["total"] == 2
        assert summary2["by_status"]["draft"] == 1
        assert summary2["by_status"]["approved"] == 1
        assert summary2["by_type"]["department"] == 1
        assert summary2["by_type"]["location"] == 1


# -------------------- Tests for Repository Protocol --------------------
class TestTransferRepository:
    def test_protocol_methods(self):
        repo = TransferRepository()
        # Methods should raise NotImplementedError
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_asset(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_date_range(uuid4(), date.today(), date.today())
        with pytest.raises(NotImplementedError):
            repo.get_by_status(uuid4(), TransferStatus.DRAFT)
        with pytest.raises(NotImplementedError):
            repo.get_by_type(uuid4(), TransferType.DEPARTMENT)
        with pytest.raises(NotImplementedError):
            repo.get_pending_approval(uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())

    def test_get_pending_approval_delegates_to_get_by_status(self):
        repo = TransferRepository()
        with patch.object(repo, 'get_by_status', return_value=[]) as mock_get:
            repo.get_pending_approval(uuid4())
            mock_get.assert_called_once()


# -------------------- Alias Test --------------------
def test_asset_transfer_alias():
    assert AssetTransfer is TransferEntity
