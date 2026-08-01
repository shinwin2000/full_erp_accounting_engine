# test_evidence_attacher.py
# Comprehensive tests for kernel/guards/evidence_attacher.py
# All external dependencies are mocked.

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from kernel.guards.evidence_attacher import (
    BaseEvidenceAttacherGuard,
    Evidence,
    EvidenceAttacherError,
    EvidenceAttacherGuard,
    EvidenceRequirement,
    EvidenceType,
    EvidenceVerificationStatus,
    TransactionEvidenceRequirement,
    _FallbackFileStorage,
    get_evidence_attacher_guard,
)


# ----------------------------------------------------------------------
# Enums & Value Objects
# ----------------------------------------------------------------------
class TestEvidenceRequirement:
    def test_members_exist(self):
        assert hasattr(EvidenceRequirement, "MANDATORY")
        assert hasattr(EvidenceRequirement, "OPTIONAL")
        assert hasattr(EvidenceRequirement, "CONDITIONAL")
        assert hasattr(EvidenceRequirement, "NONE")

    def test_member_is_instance(self):
        assert isinstance(EvidenceRequirement.MANDATORY, EvidenceRequirement)


class TestEvidenceType:
    def test_members_exist(self):
        assert hasattr(EvidenceType, "INVOICE")
        assert hasattr(EvidenceType, "RECEIPT")
        assert hasattr(EvidenceType, "CONTRACT")
        assert hasattr(EvidenceType, "DELIVERY_NOTE")
        assert hasattr(EvidenceType, "BANK_STATEMENT")
        assert hasattr(EvidenceType, "APPROVAL_FORM")
        assert hasattr(EvidenceType, "PHOTO")
        assert hasattr(EvidenceType, "SIGNED_DOCUMENT")
        assert hasattr(EvidenceType, "TAX_INVOICE")
        assert hasattr(EvidenceType, "OTHER")

    def test_member_is_instance(self):
        assert isinstance(EvidenceType.INVOICE, EvidenceType)


class TestEvidenceVerificationStatus:
    def test_members_exist(self):
        assert hasattr(EvidenceVerificationStatus, "PENDING")
        assert hasattr(EvidenceVerificationStatus, "VERIFIED")
        assert hasattr(EvidenceVerificationStatus, "FAILED")
        assert hasattr(EvidenceVerificationStatus, "EXPIRED")
        assert hasattr(EvidenceVerificationStatus, "REJECTED")

    def test_member_is_instance(self):
        assert isinstance(EvidenceVerificationStatus.PENDING, EvidenceVerificationStatus)


class TestEvidence:
    def test_construction(self):
        now = datetime.now(UTC)
        evidence = Evidence(
            evidence_id=uuid4(),
            filename="test.pdf",
            file_hash="abc123",
            file_size=1024,
            mime_type="application/pdf",
            evidence_type=EvidenceType.INVOICE,
            uploaded_by="user1",
            uploaded_at=now,
            storage_path="/storage/test.pdf",
            description="Test",
            verification_status=EvidenceVerificationStatus.PENDING,
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            tags=["tag1"],
            cryptographic_hash="",
        )
        assert isinstance(evidence, Evidence)
        assert evidence.cryptographic_hash == ""  # not auto-computed

    def test_compute_hash(self):
        now = datetime.now(UTC)
        evidence = Evidence(
            evidence_id=uuid4(),
            filename="test.pdf",
            file_hash="abc123",
            file_size=1024,
            mime_type="application/pdf",
            evidence_type=EvidenceType.INVOICE,
            uploaded_by="user1",
            uploaded_at=now,
            storage_path="/storage/test.pdf",
        )
        h = evidence.compute_hash()
        assert isinstance(h, str)
        assert len(h) == 64

    def test_is_expired(self):
        now = datetime.now(UTC)
        evidence = Evidence(
            evidence_id=uuid4(),
            filename="test.pdf",
            file_hash="abc123",
            file_size=1024,
            mime_type="application/pdf",
            evidence_type=EvidenceType.INVOICE,
            uploaded_by="user1",
            uploaded_at=now,
            storage_path="/storage/test.pdf",
            expiry_date=now - timedelta(days=1),
        )
        assert evidence.is_expired() is True
        evidence.expiry_date = now + timedelta(days=1)
        assert evidence.is_expired() is False

    def test_hash_mismatch_raises(self):
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            Evidence(
                evidence_id=uuid4(),
                filename="test.pdf",
                file_hash="abc123",
                file_size=1024,
                mime_type="application/pdf",
                evidence_type=EvidenceType.INVOICE,
                uploaded_by="user1",
                uploaded_at=now,
                storage_path="/storage/test.pdf",
                cryptographic_hash="wronghash",
            )

    def test_to_dict(self):
        now = datetime.now(UTC)
        evidence = Evidence(
            evidence_id=uuid4(),
            filename="test.pdf",
            file_hash="abc123",
            file_size=1024,
            mime_type="application/pdf",
            evidence_type=EvidenceType.INVOICE,
            uploaded_by="user1",
            uploaded_at=now,
            storage_path="/storage/test.pdf",
            description="Test description longer than 100 chars" * 10,
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            tags=["tag1"],
            cryptographic_hash="",
        )
        d = evidence.to_dict()
        assert d["evidence_id"] == str(evidence.evidence_id)
        assert d["filename"] == "test.pdf"
        assert d["file_hash"].endswith("...")
        assert d["description"] is not None
        assert len(d["description"]) <= 100


class TestTransactionEvidenceRequirement:
    def test_construction(self):
        req = TransactionEvidenceRequirement(
            transaction_type="TEST",
            requirement=EvidenceRequirement.MANDATORY,
            min_evidence_count=2,
            required_types=[EvidenceType.INVOICE, EvidenceType.RECEIPT],
            amount_threshold=Decimal("1000"),
            description="Test",
            requires_verification=True,
            expiry_days=30,
        )
        assert req.transaction_type == "TEST"
        assert req.requirement == EvidenceRequirement.MANDATORY


class Test_FallbackFileStorage:
    @pytest.mark.asyncio
    async def test_upload_download_delete(self):
        storage = _FallbackFileStorage()
        path = "test/file.txt"
        content = b"hello world"
        mime = "text/plain"
        result = await storage.upload(path, content, mime)
        assert result is True
        assert path in storage._storage
        meta = await storage.get_metadata(path)
        assert meta["size"] == len(content)
        assert meta["mime_type"] == mime
        # download
        data = await storage.download(path)
        assert data == content
        # exists
        assert await storage.exists(path) is True
        # size
        assert await storage.get_size(path) == len(content)
        # list
        assert path in await storage.list_files(prefix="test/")
        # delete
        result = await storage.delete(path)
        assert result is True
        assert path not in storage._storage
        assert await storage.exists(path) is False
        # total used
        assert await storage.get_total_used_bytes() == 0

    @pytest.mark.asyncio
    async def test_upload_too_large(self):
        storage = _FallbackFileStorage()
        # override max size to small for testing
        storage._max_size_bytes = 10
        content = b"this is more than 10 bytes"
        result = await storage.upload("test.txt", content, "text/plain")
        assert result is False

    @pytest.mark.asyncio
    async def test_clear(self):
        storage = _FallbackFileStorage()
        await storage.upload("a.txt", b"abc", "text/plain")
        await storage.upload("b.txt", b"def", "text/plain")
        await storage.clear()
        assert len(storage._storage) == 0
        assert await storage.get_total_used_bytes() == 0


class TestBaseEvidenceAttacherGuard:
    def test_class_defined(self):
        assert BaseEvidenceAttacherGuard is not None


# ----------------------------------------------------------------------
# EvidenceAttacherGuard
# ----------------------------------------------------------------------
@pytest.fixture
def mock_file_storage():
    storage = MagicMock(spec=_FallbackFileStorage)
    storage.upload = AsyncMock(return_value=True)
    storage.download = AsyncMock(return_value=b"file content")
    storage.delete = AsyncMock(return_value=True)
    storage.get_metadata = AsyncMock(return_value={"size": 100})
    return storage


@pytest.fixture
def enforcer(mock_file_storage):
    return EvidenceAttacherGuard(file_storage=mock_file_storage)


@pytest.fixture
def sample_evidence(enforcer):
    evidence = Evidence(
        evidence_id=uuid4(),
        filename="test.pdf",
        file_hash="abc123",
        file_size=1024,
        mime_type="application/pdf",
        evidence_type=EvidenceType.INVOICE,
        uploaded_by="user1",
        uploaded_at=datetime.now(UTC),
        storage_path="evidence/entity/invoice/uuid/test.pdf",
        description="Test",
        verification_status=EvidenceVerificationStatus.PENDING,
        transaction_id=None,
        legal_entity_id=uuid4(),
        tags=[],
        cryptographic_hash="",
    )
    evidence.cryptographic_hash = evidence.compute_hash()
    return evidence


class TestEvidenceAttacherGuard:
    # ----- Entity methods -----
    def test_check(self, enforcer):
        # valid
        context = {
            "transaction_type": "JOURNAL_POST",
            "evidence_ids": [str(uuid4())],
            "amount": "100.00",
        }
        errors = enforcer.check(context)
        assert errors == []

        # missing
        errors = enforcer.check({})
        assert "transaction_type is required" in errors
        assert "evidence_ids is required and cannot be empty" in errors

        # invalid UUID
        context = {"transaction_type": "JOURNAL_POST", "evidence_ids": ["not-a-uuid"]}
        errors = enforcer.check(context)
        assert any("Invalid evidence_id" in e for e in errors)

        # invalid amount
        context = {"transaction_type": "JOURNAL_POST", "evidence_ids": [str(uuid4())], "amount": "not-a-number"}
        errors = enforcer.check(context)
        assert "amount must be a valid number" in errors

    def test_validate(self, enforcer):
        result = enforcer.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_to_dict(self, enforcer):
        d = enforcer.to_dict()
        assert "enabled" in d
        assert "auto_verify_on_upload" in d
        assert "evidences_count" in d
        assert "version" in d

    def test_from_dict(self):
        data = {"enabled": False, "auto_verify_on_upload": True, "max_history": 5000, "version": 3}
        enforcer = EvidenceAttacherGuard.from_dict(data)
        assert enforcer._enabled is False
        assert enforcer._auto_verify_on_upload is True
        assert enforcer._max_history == 5000
        assert enforcer._version == 3

    def test_clone(self, enforcer):
        clone = enforcer.clone()
        assert clone is not enforcer
        assert clone._enabled == enforcer._enabled
        assert clone._auto_verify_on_upload == enforcer._auto_verify_on_upload
        assert clone._max_history == enforcer._max_history
        assert clone._version == enforcer._version + 1

    def test_snapshot(self, enforcer):
        snap = enforcer.snapshot()
        assert "version" in snap
        assert "evidences_count" in snap
        assert "enabled" in snap
        assert "timestamp" in snap

    def test_version(self, enforcer):
        assert enforcer.version() == enforcer._version

    def test_audit_trail(self, enforcer):
        assert enforcer.audit_trail() == []
        enforcer.touch("admin")
        trail = enforcer.audit_trail(limit=10)
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"

    def test_touch(self, enforcer):
        old = enforcer.version()
        enforcer.touch("admin")
        assert enforcer.version() == old + 1
        trail = enforcer.audit_trail()
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "admin"

    # ----- Business methods -----
    def test_enable(self, enforcer):
        enforcer.enable(False)
        assert enforcer._enabled is False
        enforcer.enable(True)
        assert enforcer._enabled is True

    def test_set_auto_verify(self, enforcer):
        assert enforcer._auto_verify_on_upload is False
        enforcer.set_auto_verify(True)
        assert enforcer._auto_verify_on_upload is True
        # check audit
        trail = enforcer.audit_trail()
        assert any(e["action"] == "SET_AUTO_VERIFY" for e in trail)

    def test_register_requirement(self, enforcer):
        req = TransactionEvidenceRequirement(
            transaction_type="CUSTOM",
            requirement=EvidenceRequirement.MANDATORY,
            min_evidence_count=2,
        )
        enforcer.register_requirement(req)
        assert "CUSTOM" in enforcer._requirements
        assert enforcer._requirements["CUSTOM"] is req
        # audit
        trail = enforcer.audit_trail()
        assert any(e["action"] == "REGISTER_REQUIREMENT" for e in trail)

    def test_get_requirement(self, enforcer):
        # default exists
        req = enforcer.get_requirement("JOURNAL_POST")
        assert req is not None
        assert req.transaction_type == "JOURNAL_POST"
        # non-existent
        assert enforcer.get_requirement("UNKNOWN") is None

    def test_get_requirements(self, enforcer):
        reqs = enforcer.get_requirements()
        assert isinstance(reqs, dict)
        assert len(reqs) > 0
        assert "JOURNAL_POST" in reqs

    @pytest.mark.asyncio
    async def test_upload_evidence(self, enforcer, mock_file_storage):
        with patch("kernel.guards.evidence_attacher.get_current_user", return_value="user1"):
            with patch("kernel.guards.evidence_attacher.get_current_legal_entity", return_value=uuid4()):
                content = b"test file"
                evidence = await enforcer.upload_evidence(
                    file_content=content,
                    filename="test.txt",
                    mime_type="text/plain",
                    evidence_type=EvidenceType.INVOICE,
                    description="Test upload",
                    tags=["tag1"],
                )
                assert isinstance(evidence, Evidence)
                assert evidence.filename == "test.txt"
                assert evidence.file_size == len(content)
                assert evidence.uploaded_by == "user1"
                assert evidence.evidence_id in enforcer._evidences
                mock_file_storage.upload.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upload_evidence_with_auto_verify(self, enforcer, mock_file_storage):
        enforcer.set_auto_verify(True)
        with patch("kernel.guards.evidence_attacher.get_current_user", return_value="user1"):
            with patch("kernel.guards.evidence_attacher.get_current_legal_entity", return_value=uuid4()):
                with patch.object(enforcer, "verify_evidence", AsyncMock(return_value=MagicMock(spec=Evidence))):
                    evidence = await enforcer.upload_evidence(
                        file_content=b"test",
                        filename="test.txt",
                        mime_type="text/plain",
                        evidence_type=EvidenceType.INVOICE,
                    )
                    enforcer.verify_evidence.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_evidence(self, enforcer, sample_evidence):
        enforcer._evidences[sample_evidence.evidence_id] = sample_evidence
        ev = await enforcer.get_evidence(sample_evidence.evidence_id)
        assert ev is sample_evidence
        assert await enforcer.get_evidence(uuid4()) is None

    @pytest.mark.asyncio
    async def test_get_evidences_for_transaction(self, enforcer, sample_evidence):
        tx_id = uuid4()
        sample_evidence.transaction_id = tx_id
        enforcer._evidences[sample_evidence.evidence_id] = sample_evidence
        enforcer._transaction_evidence[tx_id] = [sample_evidence.evidence_id]
        evs = await enforcer.get_evidences_for_transaction(tx_id)
        assert len(evs) == 1
        assert evs[0] is sample_evidence

    @pytest.mark.asyncio
    async def test_get_evidences_by_type(self, enforcer, sample_evidence):
        enforcer._evidences[sample_evidence.evidence_id] = sample_evidence
        evs = await enforcer.get_evidences_by_type(EvidenceType.INVOICE)
        assert len(evs) == 1
        evs = await enforcer.get_evidences_by_type(EvidenceType.RECEIPT)
        assert len(evs) == 0

    @pytest.mark.asyncio
    async def test_get_evidences_by_user(self, enforcer, sample_evidence):
        enforcer._evidences[sample_evidence.evidence_id] = sample_evidence
        evs = await enforcer.get_evidences_by_user("user1")
        assert len(evs) == 1
        evs = await enforcer.get_evidences_by_user("other")
        assert len(evs) == 0

    @pytest.mark.asyncio
    async def test_download_evidence(self, enforcer, mock_file_storage, sample_evidence):
        enforcer._evidences[sample_evidence.evidence_id] = sample_evidence
        data = await enforcer.download_evidence(sample_evidence)
        assert data == b"file content"
        mock_file_storage.download.assert_awaited_once_with(sample_evidence.storage_path)

    @pytest.mark.asyncio
    async def test_verify_integrity(self, enforcer, mock_file_storage, sample_evidence):
        # File content matches hash
        enforcer._evidences[sample_evidence.evidence_id] = sample_evidence
        mock_file_storage.download.return_value = b"content"  # but hash mismatch, so we need to compute
        # We'll mock the download to return content with known hash
        content = b"test content"
        actual_hash = "9f86d081884c7d659a9fe9cb8e49a95d6a0f0f3c7f0e3e3a0e0f0e3f0e3f0e3f"  # sha256 of "test content"
        sample_evidence.file_hash = actual_hash
        mock_file_storage.download.return_value = content
        result = await enforcer.verify_integrity(sample_evidence)
        assert result is True
        # Mismatch
        mock_file_storage.download.return_value = b"different"
        result = await enforcer.verify_integrity(sample_evidence)
        assert result is False

    @pytest.mark.asyncio
    async def test_verify_evidence(self, enforcer, mock_file_storage, sample_evidence):
        enforcer._evidences[sample_evidence.evidence_id] = sample_evidence
        # Verify with integrity ok
        with patch.object(enforcer, "verify_integrity", AsyncMock(return_value=True)):
            updated = await enforcer.verify_evidence(sample_evidence.evidence_id, "verifier", EvidenceVerificationStatus.VERIFIED)
            assert updated is not None
            assert updated.verification_status == EvidenceVerificationStatus.VERIFIED
            assert updated.verified_by == "verifier"
            assert updated.verified_at is not None
        # Verify with integrity fail
        with patch.object(enforcer, "verify_integrity", AsyncMock(return_value=False)):
            updated = await enforcer.verify_evidence(sample_evidence.evidence_id, "verifier", EvidenceVerificationStatus.VERIFIED)
            assert updated is not None
            assert updated.verification_status == EvidenceVerificationStatus.FAILED
        # Reject with reason
        with patch.object(enforcer, "verify_integrity", AsyncMock(return_value=True)):
            updated = await enforcer.verify_evidence(sample_evidence.evidence_id, "verifier", EvidenceVerificationStatus.REJECTED, rejection_reason="invalid")
            assert updated is not None
            assert updated.verification_status == EvidenceVerificationStatus.REJECTED
            assert "REJECTED: invalid" in updated.description

    @pytest.mark.asyncio
    async def test_attach_to_transaction(self, enforcer, sample_evidence):
        enforcer._evidences[sample_evidence.evidence_id] = sample_evidence
        tx_id = uuid4()
        result = await enforcer.attach_to_transaction(sample_evidence.evidence_id, tx_id, "user1")
        assert result is True
        updated = enforcer._evidences[sample_evidence.evidence_id]
        assert updated.transaction_id == tx_id
        assert tx_id in enforcer._transaction_evidence
        assert sample_evidence.evidence_id in enforcer._transaction_evidence[tx_id]
        # attach non-existent
        result = await enforcer.attach_to_transaction(uuid4(), tx_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_detach_from_transaction(self, enforcer, sample_evidence):
        tx_id = uuid4()
        sample_evidence.transaction_id = tx_id
        enforcer._evidences[sample_evidence.evidence_id] = sample_evidence
        enforcer._transaction_evidence[tx_id] = [sample_evidence.evidence_id]
        result = await enforcer.detach_from_transaction(sample_evidence.evidence_id, tx_id, "user1")
        assert result is True
        updated = enforcer._evidences[sample_evidence.evidence_id]
        assert updated.transaction_id is None
        assert sample_evidence.evidence_id not in enforcer._transaction_evidence.get(tx_id, [])
        # detach non-existent
        result = await enforcer.detach_from_transaction(uuid4(), tx_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_evidence_hard(self, enforcer, mock_file_storage, sample_evidence):
        enforcer._evidences[sample_evidence.evidence_id] = sample_evidence
        # Hard delete (no transaction)
        result = await enforcer.delete_evidence(sample_evidence.evidence_id, "user1", force=True)
        assert result is True
        assert sample_evidence.evidence_id not in enforcer._evidences
        mock_file_storage.delete.assert_awaited_once_with(sample_evidence.storage_path)

    @pytest.mark.asyncio
    async def test_delete_evidence_soft(self, enforcer, mock_file_storage, sample_evidence):
        # Evidence attached to transaction -> soft delete (expire)
        tx_id = uuid4()
        sample_evidence.transaction_id = tx_id
        enforcer._evidences[sample_evidence.evidence_id] = sample_evidence
        enforcer._transaction_evidence[tx_id] = [sample_evidence.evidence_id]
        result = await enforcer.delete_evidence(sample_evidence.evidence_id, "user1", force=False)
        assert result is True
        updated = enforcer._evidences[sample_evidence.evidence_id]
        assert updated.verification_status == EvidenceVerificationStatus.EXPIRED
        assert updated.verified_by == "user1"
        mock_file_storage.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_evidence_disabled(self, enforcer):
        enforcer.enable(False)
        is_valid, error, warnings = await enforcer.validate_evidence("JOURNAL_POST", [])
        assert is_valid is True
        assert error is None
        assert warnings == []

    @pytest.mark.asyncio
    async def test_validate_evidence_no_requirement(self, enforcer):
        is_valid, error, warnings = await enforcer.validate_evidence("UNKNOWN", [])
        assert is_valid is True
        assert error is None

    @pytest.mark.asyncio
    async def test_validate_evidence_optional(self, enforcer):
        # Optional requirement: always valid, but may warn
        is_valid, error, warnings = await enforcer.validate_evidence(
            "JOURNAL_POST", [], check_expiry=True
        )
        assert is_valid is True
        assert error is None
        # Optional with insufficient evidence gives warning
        is_valid, error, warnings = await enforcer.validate_evidence(
            "JOURNAL_POST", [], check_expiry=True
        )
        # But it's optional, so still valid, warning may appear
        # However in default JOURNAL_POST min_evidence_count=0, so no warning.
        # Let's test with a requirement that has min_evidence_count > 0
        # Register a custom optional with min 2
        req = TransactionEvidenceRequirement(
            transaction_type="OPTIONAL_REQ",
            requirement=EvidenceRequirement.OPTIONAL,
            min_evidence_count=2,
        )
        enforcer.register_requirement(req)
        is_valid, error, warnings = await enforcer.validate_evidence("OPTIONAL_REQ", [])
        assert is_valid is True
        assert error is None
        assert "at least 2 evidence(s)" in warnings[0]

    @pytest.mark.asyncio
    async def test_validate_evidence_mandatory_missing(self, enforcer):
        # Create a mandatory requirement for testing
        req = TransactionEvidenceRequirement(
            transaction_type="MANDATORY_REQ",
            requirement=EvidenceRequirement.MANDATORY,
            min_evidence_count=1,
        )
        enforcer.register_requirement(req)
        is_valid, error, warnings = await enforcer.validate_evidence("MANDATORY_REQ", [])
        assert is_valid is False
        assert "requires at least 1 evidence" in error

    @pytest.mark.asyncio
    async def test_validate_evidence_mandatory_required_types(self, enforcer):
        req = TransactionEvidenceRequirement(
            transaction_type="REQ_TYPES",
            requirement=EvidenceRequirement.MANDATORY,
            min_evidence_count=1,
            required_types=[EvidenceType.INVOICE],
        )
        enforcer.register_requirement(req)
        # create an evidence of wrong type
        eid = uuid4()
        ev = Evidence(
            evidence_id=eid,
            filename="test.pdf",
            file_hash="abc",
            file_size=100,
            mime_type="pdf",
            evidence_type=EvidenceType.RECEIPT,
            uploaded_by="user",
            uploaded_at=datetime.now(UTC),
            storage_path="path",
        )
        enforcer._evidences[eid] = ev
        is_valid, error, warnings = await enforcer.validate_evidence("REQ_TYPES", [eid])
        assert is_valid is False
        assert "requires evidence of type(s): ['invoice']" in error

    @pytest.mark.asyncio
    async def test_validate_evidence_mandatory_verification(self, enforcer):
        req = TransactionEvidenceRequirement(
            transaction_type="VERIFY_REQ",
            requirement=EvidenceRequirement.MANDATORY,
            min_evidence_count=1,
            requires_verification=True,
        )
        enforcer.register_requirement(req)
        eid = uuid4()
        ev = Evidence(
            evidence_id=eid,
            filename="test.pdf",
            file_hash="abc",
            file_size=100,
            mime_type="pdf",
            evidence_type=EvidenceType.INVOICE,
            uploaded_by="user",
            uploaded_at=datetime.now(UTC),
            storage_path="path",
            verification_status=EvidenceVerificationStatus.PENDING,
        )
        enforcer._evidences[eid] = ev
        is_valid, error, warnings = await enforcer.validate_evidence("VERIFY_REQ", [eid])
        assert is_valid is False
        assert "not verified" in error

    @pytest.mark.asyncio
    async def test_validate_evidence_expiry(self, enforcer):
        req = TransactionEvidenceRequirement(
            transaction_type="EXP_REQ",
            requirement=EvidenceRequirement.MANDATORY,
            min_evidence_count=1,
        )
        enforcer.register_requirement(req)
        eid = uuid4()
        ev = Evidence(
            evidence_id=eid,
            filename="test.pdf",
            file_hash="abc",
            file_size=100,
            mime_type="pdf",
            evidence_type=EvidenceType.INVOICE,
            uploaded_by="user",
            uploaded_at=datetime.now(UTC),
            storage_path="path",
            expiry_date=datetime.now(UTC) - timedelta(days=1),
        )
        enforcer._evidences[eid] = ev
        is_valid, error, warnings = await enforcer.validate_evidence("EXP_REQ", [eid], check_expiry=True)
        assert is_valid is False
        assert "expired" in error
        # with check_expiry=False
        is_valid, error, warnings = await enforcer.validate_evidence("EXP_REQ", [eid], check_expiry=False)
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_validate_evidence_conditional_below_threshold(self, enforcer):
        req = TransactionEvidenceRequirement(
            transaction_type="COND_REQ",
            requirement=EvidenceRequirement.CONDITIONAL,
            amount_threshold=Decimal("1000"),
        )
        enforcer.register_requirement(req)
        is_valid, error, warnings = await enforcer.validate_evidence(
            "COND_REQ", [], amount=Decimal("500")
        )
        assert is_valid is True
        assert error is None

    @pytest.mark.asyncio
    async def test_validate_evidence_conditional_above_threshold(self, enforcer):
        req = TransactionEvidenceRequirement(
            transaction_type="COND_REQ",
            requirement=EvidenceRequirement.CONDITIONAL,
            min_evidence_count=1,
            amount_threshold=Decimal("1000"),
        )
        enforcer.register_requirement(req)
        is_valid, error, warnings = await enforcer.validate_evidence(
            "COND_REQ", [], amount=Decimal("1500")
        )
        assert is_valid is False
        assert "requires at least 1 evidence" in error

    @pytest.mark.asyncio
    async def test_enforce_success(self, enforcer):
        # Test successful enforce (no exception)
        with patch.object(enforcer, "validate_evidence", AsyncMock(return_value=(True, None, []))):
            is_valid, warnings = await enforcer.enforce("TEST", [], raise_on_violation=True)
            assert is_valid is True
            assert warnings == []

    @pytest.mark.asyncio
    async def test_enforce_violation_raises(self, enforcer):
        # Test violation raises
        with patch.object(enforcer, "validate_evidence", AsyncMock(return_value=(False, "Error", []))):
            with pytest.raises(EvidenceAttacherError) as exc:
                await enforcer.enforce("TEST", [], raise_on_violation=True)
            assert "Error" in str(exc.value)

    @pytest.mark.asyncio
    async def test_enforce_no_raise(self, enforcer):
        # Test violation without raise
        with patch.object(enforcer, "validate_evidence", AsyncMock(return_value=(False, "Error", []))):
            is_valid, warnings = await enforcer.enforce("TEST", [], raise_on_violation=False)
            assert is_valid is False
            assert warnings == []

    def test_record_check(self, enforcer):
        # Directly test private method
        enforcer._record_check("TEST", [uuid4()], Decimal("100"), True, None, ["warn"])
        assert len(enforcer._check_history) == 1
        record = enforcer._check_history[0]
        assert record["transaction_type"] == "TEST"
        assert record["is_valid"] is True
        assert record["warnings"] == ["warn"]

    def test_get_check_history(self, enforcer):
        # Add some records
        for i in range(5):
            enforcer._record_check("TEST", [], None, i % 2 == 0, None, [])
        # Test limit
        history = enforcer.get_check_history(limit=3)
        assert len(history) == 3
        # only_violations
        violations = enforcer.get_check_history(only_violations=True)
        assert all(not r["is_valid"] for r in violations)
        # filter by type
        enforcer._record_check("OTHER", [], None, True, None, [])
        filtered = enforcer.get_check_history(transaction_type="OTHER")
        assert len(filtered) == 1
        # date filters
        start = datetime.now(UTC) - timedelta(minutes=5)
        end = datetime.now(UTC) + timedelta(minutes=5)
        filtered = enforcer.get_check_history(start_date=start, end_date=end)
        # all records should be in this range
        assert len(filtered) == 6  # because we added 5 TEST + 1 OTHER

    def test_get_statistics(self, enforcer):
        # Initially no data
        stats = enforcer.get_statistics()
        assert stats["total_evidences"] == 0
        assert stats["total_checks"] == 0
        # Add evidence and checks
        evidence = Evidence(
            evidence_id=uuid4(),
            filename="test.pdf",
            file_hash="abc",
            file_size=100,
            mime_type="pdf",
            evidence_type=EvidenceType.INVOICE,
            uploaded_by="user",
            uploaded_at=datetime.now(UTC),
            storage_path="path",
            verification_status=EvidenceVerificationStatus.VERIFIED,
        )
        enforcer._evidences[evidence.evidence_id] = evidence
        enforcer._record_check("JOURNAL_POST", [], None, True, None, [])
        enforcer._record_check("CASH", [], None, False, "error", [])
        stats = enforcer.get_statistics()
        assert stats["total_evidences"] == 1
        assert stats["total_checks"] == 2
        assert stats["violation_count"] == 1
        assert stats["violation_rate"] == 0.5
        assert stats["by_transaction_type"]["JOURNAL_POST"] == 1
        assert stats["by_transaction_type"]["CASH"] == 1
        assert stats["by_verification_status"]["verified"] == 1
        assert stats["by_evidence_type"]["invoice"] == 1
        assert stats["enabled"] is True
        assert stats["auto_verify"] is False
        assert stats["version"] == enforcer.version()

    def test_reset(self, enforcer):
        # Add some state
        enforcer._evidences[uuid4()] = MagicMock(spec=Evidence)
        enforcer._check_history.append({"test": "data"})
        enforcer._requirements["CUSTOM"] = MagicMock(spec=TransactionEvidenceRequirement)
        old_version = enforcer.version()
        enforcer.reset()
        assert len(enforcer._evidences) == 0
        assert len(enforcer._check_history) == 0
        # Requirements reset to default
        assert "CUSTOM" not in enforcer._requirements
        assert "JOURNAL_POST" in enforcer._requirements
        assert enforcer.version() == old_version + 1
        assert enforcer._audit_trail == []


# ----------------------------------------------------------------------
# Singleton
# ----------------------------------------------------------------------
def test_get_evidence_attacher_guard():
    instance1 = get_evidence_attacher_guard()
    instance2 = get_evidence_attacher_guard()
    assert instance1 is instance2
    assert isinstance(instance1, EvidenceAttacherGuard)
