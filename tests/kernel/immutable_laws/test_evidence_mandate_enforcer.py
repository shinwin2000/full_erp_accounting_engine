# test_evidence_mandate_enforcer.py
# Comprehensive tests for kernel/immutable_laws/evidence_mandate_enforcer.py
# Fixed: All datetime.now() calls are mocked to avoid flaky tests.

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from kernel.immutable_laws.evidence_mandate_enforcer import (
    BaseEvidenceMandateEnforcer,
    Evidence,
    EvidenceMandateEnforcer,
    EvidenceQuality,
    EvidenceRequirement,
    EvidenceType,
    EvidenceVerificationStatus,
    _EvidenceProxy,
    _FallbackEvidenceRepository,
    _FallbackJournalRepository,
    get_evidence_mandate_enforcer,
)

# ============================================================================
# FIXED DATETIME (untuk menghindari flaky tests)
# ============================================================================

FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime():
    """Mock datetime.now and datetime.utcnow to fixed values."""
    with patch("kernel.immutable_laws.evidence_mandate_enforcer.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.utcnow.return_value = FIXED_NOW
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------
@pytest.fixture
def enforcer():
    """Create a fresh EvidenceMandateEnforcer instance."""
    return EvidenceMandateEnforcer()


@pytest.fixture
def sample_evidence_data():
    return {
        "filename": "invoice.pdf",
        "file_content": b"dummy content",
        "mime_type": "application/pdf",
        "evidence_type": EvidenceType.INVOICE,
        "description": "Invoice for purchase",
        "quality": EvidenceQuality.HIGH,
    }


@pytest.fixture
async def created_evidence(enforcer, sample_evidence_data, legal_entity_id):
    """Create an evidence and return it."""
    legal_entity_id = uuid4()
    evidence = await enforcer.create_evidence(
        filename=sample_evidence_data["filename"],
        file_content=sample_evidence_data["file_content"],
        mime_type=sample_evidence_data["mime_type"],
        evidence_type=sample_evidence_data["evidence_type"],
        legal_entity_id=legal_entity_id,
        description=sample_evidence_data["description"],
        quality=sample_evidence_data["quality"],
    )
    return evidence, legal_entity_id


@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def journal_id():
    return uuid4()


@pytest.fixture
def sample_journal_type():
    return "PAYMENT_JOURNAL"  # mandatory in default requirements


# -----------------------------------------------------------------------------
# Enum tests
# -----------------------------------------------------------------------------
class TestEvidenceType:
    def test_members_exist(self):
        assert hasattr(EvidenceType, "INVOICE")
        assert hasattr(EvidenceType, "RECEIPT")
        assert hasattr(EvidenceType, "CONTRACT")
        assert hasattr(EvidenceType, "DELIVERY_NOTE")
        assert hasattr(EvidenceType, "BANK_STATEMENT")
        assert hasattr(EvidenceType, "APPROVAL_FORM")
        assert hasattr(EvidenceType, "PHOTO")
        assert hasattr(EvidenceType, "CALCULATION")
        assert hasattr(EvidenceType, "OTHER")

    def test_member_is_instance(self):
        assert isinstance(EvidenceType.INVOICE, EvidenceType)


class TestEvidenceQuality:
    def test_members_exist(self):
        assert hasattr(EvidenceQuality, "HIGH")
        assert hasattr(EvidenceQuality, "MEDIUM")
        assert hasattr(EvidenceQuality, "LOW")
        assert hasattr(EvidenceQuality, "INSUFFICIENT")

    def test_member_is_instance(self):
        assert isinstance(EvidenceQuality.HIGH, EvidenceQuality)


class TestEvidenceVerificationStatus:
    def test_members_exist(self):
        assert hasattr(EvidenceVerificationStatus, "PENDING")
        assert hasattr(EvidenceVerificationStatus, "VERIFIED")
        assert hasattr(EvidenceVerificationStatus, "REJECTED")
        assert hasattr(EvidenceVerificationStatus, "EXPIRED")

    def test_member_is_instance(self):
        assert isinstance(EvidenceVerificationStatus.PENDING, EvidenceVerificationStatus)


# -----------------------------------------------------------------------------
# Evidence tests
# -----------------------------------------------------------------------------
class TestEvidence:
    def test_construction(self, sample_evidence_data):
        evidence = Evidence(
            evidence_id=uuid4(),
            filename=sample_evidence_data["filename"],
            file_hash="abc123",
            file_size=100,
            mime_type=sample_evidence_data["mime_type"],
            evidence_type=sample_evidence_data["evidence_type"],
            uploaded_by="user1",
            uploaded_at=FIXED_NOW,
            storage_path="/path/file",
            description=sample_evidence_data["description"],
            quality=sample_evidence_data["quality"],
        )
        assert evidence.filename == "invoice.pdf"
        assert evidence.evidence_type == EvidenceType.INVOICE
        assert evidence.quality == EvidenceQuality.HIGH
        assert evidence.verification_status == EvidenceVerificationStatus.PENDING
        assert evidence.is_expired() is False

    def test_compute_hash(self):
        evidence = Evidence(
            evidence_id=uuid4(),
            filename="test.pdf",
            file_hash="abc",
            file_size=10,
            mime_type="pdf",
            evidence_type=EvidenceType.CONTRACT,
            uploaded_by="u",
            uploaded_at=FIXED_NOW,
            storage_path="/s",
        )
        h = evidence.compute_hash()
        assert isinstance(h, str)
        assert len(h) > 0

    def test_hash_mismatch_raises(self):
        evidence_id = uuid4()
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            Evidence(
                evidence_id=evidence_id,
                filename="test.pdf",
                file_hash="abc",
                file_size=10,
                mime_type="pdf",
                evidence_type=EvidenceType.CONTRACT,
                uploaded_by="u",
                uploaded_at=FIXED_NOW,
                storage_path="/s",
                cryptographic_hash="wrong_hash",
            )

    def test_is_expired_with_expiry(self):
        expiry = FIXED_NOW - timedelta(days=1)
        evidence = Evidence(
            evidence_id=uuid4(),
            filename="test.pdf",
            file_hash="abc",
            file_size=10,
            mime_type="pdf",
            evidence_type=EvidenceType.CONTRACT,
            uploaded_by="u",
            uploaded_at=FIXED_NOW,
            storage_path="/s",
            expiry_date=expiry,
        )
        assert evidence.is_expired() is True

    def test_to_dict(self):
        evidence = Evidence(
            evidence_id=uuid4(),
            filename="test.pdf",
            file_hash="abc1234567890" * 10,
            file_size=12345,
            mime_type="image/png",
            evidence_type=EvidenceType.PHOTO,
            uploaded_by="user",
            uploaded_at=FIXED_NOW,
            storage_path="/path",
            description="A test description that is long enough to be truncated",
            quality=EvidenceQuality.MEDIUM,
            verification_status=EvidenceVerificationStatus.VERIFIED,
        )
        data = evidence.to_dict()
        assert data["filename"] == "test.pdf"
        assert data["evidence_type"] == "photo"
        assert data["file_hash"].endswith("...")
        assert data["quality"] == "medium"
        assert data["verification_status"] == "VERIFIED"
        assert data["description"] is not None
        assert len(data["description"]) <= 100


# -----------------------------------------------------------------------------
# EvidenceRequirement tests
# -----------------------------------------------------------------------------
class TestEvidenceRequirement:
    def test_construction(self):
        req = EvidenceRequirement(
            journal_type="PAYMENT",
            is_mandatory=True,
            min_evidence_count=2,
            required_types=[EvidenceType.INVOICE, EvidenceType.RECEIPT],
            amount_threshold=Decimal("1000"),
            quality_required=EvidenceQuality.HIGH,
            requires_verification=True,
            expiry_days=30,
            description="Payment requires invoice and receipt",
        )
        assert req.journal_type == "PAYMENT"
        assert req.min_evidence_count == 2
        assert req.quality_required == EvidenceQuality.HIGH

    def test_to_dict(self):
        req = EvidenceRequirement(
            journal_type="PAYMENT",
            is_mandatory=True,
            min_evidence_count=1,
            required_types=[EvidenceType.INVOICE],
            amount_threshold=Decimal("5000"),
            quality_required=EvidenceQuality.MEDIUM,
            requires_verification=False,
            expiry_days=30,
            description="Test description that is longer than 100 characters" * 3,
        )
        data = req.to_dict()
        assert data["journal_type"] == "PAYMENT"
        assert data["is_mandatory"] is True
        assert data["min_evidence_count"] == 1
        assert data["required_types"] == ["invoice"]
        assert data["amount_threshold"] == "5000"
        assert data["quality_required"] == "medium"
        assert data["requires_verification"] is False
        assert data["expiry_days"] == 30
        assert len(data["description"]) <= 100


# -----------------------------------------------------------------------------
# _FallbackEvidenceRepository tests
# -----------------------------------------------------------------------------
class TestFallbackEvidenceRepository:
    @pytest.mark.asyncio
    async def test_add_and_get_by_id(self):
        repo = _FallbackEvidenceRepository()
        eid = uuid4()
        legal_id = uuid4()
        await repo.add_evidence(
            evidence_id=eid,
            legal_entity_id=legal_id,
            filename="test.pdf",
            file_hash="hash",
            file_size=100,
            mime_type="pdf",
            evidence_type="invoice",
            uploaded_by="user",
            uploaded_at=FIXED_NOW,
            storage_path="/s",
            description="desc",
            quality="high",
        )
        result = await repo.get_by_id(eid, legal_id)
        assert result is not None
        assert result["evidence_id"] == eid
        assert result["filename"] == "test.pdf"
        # wrong legal entity -> None
        assert await repo.get_by_id(eid, uuid4()) is None

    @pytest.mark.asyncio
    async def test_get_by_journal(self):
        repo = _FallbackEvidenceRepository()
        legal_id = uuid4()
        journal_id = uuid4()
        eid1 = uuid4()
        eid2 = uuid4()
        await repo.add_evidence(eid1, legal_id, "a", "h", 1, "pdf", "inv", "u", FIXED_NOW, "/s", None, "high")
        await repo.add_evidence(eid2, legal_id, "b", "h", 1, "pdf", "inv", "u", FIXED_NOW, "/s", None, "high")
        await repo.attach_to_journal(eid1, journal_id, legal_id, "u", FIXED_NOW)
        await repo.attach_to_journal(eid2, journal_id, legal_id, "u", FIXED_NOW)
        results = await repo.get_by_journal(journal_id, legal_id)
        assert len(results) == 2
        # Detach one
        await repo.detach_from_journal(eid1, journal_id, legal_id, "u")
        results2 = await repo.get_by_journal(journal_id, legal_id)
        assert len(results2) == 1
        assert results2[0].evidence_id == eid2

    @pytest.mark.asyncio
    async def test_get_by_type_and_uploader(self):
        repo = _FallbackEvidenceRepository()
        legal_id = uuid4()
        eid = uuid4()
        await repo.add_evidence(eid, legal_id, "a", "h", 1, "pdf", "invoice", "u1", FIXED_NOW, "/s", None, "high")
        results = await repo.get_by_type("invoice", legal_id)
        assert len(results) == 1
        results2 = await repo.get_by_uploader("u1", legal_id)
        assert len(results2) == 1
        # wrong type
        assert len(await repo.get_by_type("receipt", legal_id)) == 0
        # wrong uploader
        assert len(await repo.get_by_uploader("u2", legal_id)) == 0

    @pytest.mark.asyncio
    async def test_get_by_time_range(self):
        repo = _FallbackEvidenceRepository()
        legal_id = uuid4()
        eid = uuid4()
        await repo.add_evidence(eid, legal_id, "a", "h", 1, "pdf", "inv", "u", FIXED_NOW, "/s", None, "high")
        from_date = FIXED_NOW - timedelta(days=1)
        to_date = FIXED_NOW + timedelta(days=1)
        results = await repo.get_by_time_range(legal_id, from_date, to_date)
        assert len(results) == 1
        # out of range
        results2 = await repo.get_by_time_range(legal_id, FIXED_NOW + timedelta(days=1), FIXED_NOW + timedelta(days=2))
        assert len(results2) == 0

    @pytest.mark.asyncio
    async def test_update_verification_status(self):
        repo = _FallbackEvidenceRepository()
        legal_id = uuid4()
        eid = uuid4()
        await repo.add_evidence(eid, legal_id, "a", "h", 1, "pdf", "inv", "u", FIXED_NOW, "/s", None, "high")
        result = await repo.update_verification_status(eid, legal_id, "VERIFIED", "verifier", FIXED_NOW)
        assert result is True
        ev = await repo.get_by_id(eid, legal_id)
        assert ev["verification_status"] == "VERIFIED"
        # wrong legal entity -> False
        result2 = await repo.update_verification_status(eid, uuid4(), "VERIFIED", "v", FIXED_NOW)
        assert result2 is False

    @pytest.mark.asyncio
    async def test_set_expiry(self):
        repo = _FallbackEvidenceRepository()
        legal_id = uuid4()
        eid = uuid4()
        await repo.add_evidence(eid, legal_id, "a", "h", 1, "pdf", "inv", "u", FIXED_NOW, "/s", None, "high")
        expiry = FIXED_NOW + timedelta(days=30)
        result = await repo.set_expiry(eid, legal_id, expiry)
        assert result is True
        ev = await repo.get_by_id(eid, legal_id)
        assert ev["expiry_date"] == expiry

    def test_clear(self):
        repo = _FallbackEvidenceRepository()
        repo._evidences[uuid4()] = {}
        repo.clear()
        assert len(repo._evidences) == 0


# -----------------------------------------------------------------------------
# _FallbackJournalRepository tests
# -----------------------------------------------------------------------------
class TestFallbackJournalRepository:
    @pytest.mark.asyncio
    async def test_add_and_get_by_id(self):
        repo = _FallbackJournalRepository()
        jid = uuid4()
        legal_id = uuid4()
        repo.add_journal(jid, legal_id, "PAYMENT", "DRAFT")
        result = await repo.get_by_id(jid, legal_id)
        assert result is not None
        assert result["journal_id"] == jid
        assert result["status"] == "DRAFT"
        # wrong legal entity
        assert await repo.get_by_id(jid, uuid4()) is None

    @pytest.mark.asyncio
    async def test_update_status(self):
        repo = _FallbackJournalRepository()
        jid = uuid4()
        legal_id = uuid4()
        repo.add_journal(jid, legal_id, "PAYMENT", "DRAFT")
        success = await repo.update_status(jid, legal_id, "POSTED", "user")
        assert success is True
        journal = await repo.get_by_id(jid, legal_id)
        assert journal["status"] == "POSTED"
        assert journal["updated_by"] == "user"
        # wrong legal entity
        success2 = await repo.update_status(jid, uuid4(), "POSTED", "user")
        assert success2 is False


# -----------------------------------------------------------------------------
# _EvidenceProxy tests
# -----------------------------------------------------------------------------
class TestEvidenceProxy:
    def test_construction(self):
        data = {
            "evidence_id": uuid4(),
            "filename": "test.pdf",
            "file_hash": "abc",
            "file_size": 100,
            "mime_type": "pdf",
            "evidence_type": "invoice",
            "uploaded_by": "u",
            "uploaded_at": FIXED_NOW,
            "storage_path": "/s",
            "description": "desc",
            "quality": "high",
            "verification_status": "PENDING",
            "verified_by": None,
            "verified_at": None,
            "expiry_date": None,
        }
        proxy = _EvidenceProxy(data)
        assert proxy.filename == "test.pdf"
        assert proxy.evidence_type == "invoice"
        assert proxy.is_expired() is False

    def test_is_expired_with_expiry(self):
        data = {
            "evidence_id": uuid4(),
            "filename": "test.pdf",
            "file_hash": "abc",
            "file_size": 100,
            "mime_type": "pdf",
            "evidence_type": "invoice",
            "uploaded_by": "u",
            "uploaded_at": FIXED_NOW,
            "storage_path": "/s",
            "description": "desc",
            "quality": "high",
            "verification_status": "PENDING",
            "verified_by": None,
            "verified_at": None,
            "expiry_date": FIXED_NOW - timedelta(days=1),
        }
        proxy = _EvidenceProxy(data)
        assert proxy.is_expired() is True

    def test_to_dict(self):
        proxy = _EvidenceProxy({
            "evidence_id": uuid4(),
            "filename": "test.pdf",
            "file_hash": "abcdefghijklmnopqrstuvwxyz",
            "file_size": 123,
            "mime_type": "pdf",
            "evidence_type": "contract",
            "uploaded_by": "u",
            "uploaded_at": FIXED_NOW,
            "storage_path": "/s",
            "description": "A long description that will be truncated" * 10,
            "quality": "medium",
            "verification_status": "PENDING",
            "verified_by": None,
            "verified_at": None,
            "expiry_date": None,
        })
        data = proxy.to_dict()
        assert data["filename"] == "test.pdf"
        assert data["evidence_type"] == "contract"
        assert data["file_hash"].endswith("...")
        assert len(data["description"]) <= 100


# -----------------------------------------------------------------------------
# EvidenceMandateEnforcer core tests
# -----------------------------------------------------------------------------
class TestEvidenceMandateEnforcer:
    # -------- enable/disable and strict mode ----------
    def test_enable(self, enforcer):
        assert enforcer._enabled is True
        enforcer.enable(False)
        assert enforcer._enabled is False
        enforcer.enable(True)
        assert enforcer._enabled is True

    def test_set_strict_mode(self, enforcer):
        assert enforcer._strict_mode is True
        enforcer.set_strict_mode(False)
        assert enforcer._strict_mode is False
        enforcer.set_strict_mode(True)
        assert enforcer._strict_mode is True

    # -------- requirement registration ----------
    def test_register_and_get_requirement(self, enforcer):
        req = EvidenceRequirement(
            journal_type="CUSTOM",
            is_mandatory=True,
            min_evidence_count=2,
            required_types=[EvidenceType.INVOICE],
            quality_required=EvidenceQuality.HIGH,
        )
        enforcer.register_requirement(req)
        retrieved = enforcer.get_requirement("CUSTOM")
        assert retrieved is not None
        assert retrieved.journal_type == "CUSTOM"
        assert retrieved.min_evidence_count == 2
        # get non-existent
        assert enforcer.get_requirement("NONEXISTENT") is None

    def test_get_all_requirements(self, enforcer):
        all_req = enforcer.get_all_requirements()
        assert len(all_req) > 0
        assert "PAYMENT_JOURNAL" in all_req

    # -------- enforce_evidence_mandate ----------
    @pytest.mark.asyncio
    async def test_enforce_no_requirement(self, enforcer, legal_entity_id, journal_id):
        result, violation = await enforcer.enforce_evidence_mandate(
            journal_id=journal_id,
            legal_entity_id=legal_entity_id,
            journal_type="NONEXISTENT",
            amount=Decimal("1000"),
            raise_on_violation=False,
        )
        assert result is True
        assert violation is None

    @pytest.mark.asyncio
    async def test_enforce_with_mandatory_but_no_evidence(self, enforcer, legal_entity_id, journal_id):
        result, violation = await enforcer.enforce_evidence_mandate(
            journal_id=journal_id,
            legal_entity_id=legal_entity_id,
            journal_type="PAYMENT_JOURNAL",
            amount=Decimal("1000"),
            raise_on_violation=False,
        )
        assert result is False
        assert violation is not None
        assert "requires at least 1" in violation.message
        assert violation.journal_type == "PAYMENT_JOURNAL"
        assert violation.severity.name == "CRITICAL"

    @pytest.mark.asyncio
    async def test_enforce_with_evidence_count_ok(self, enforcer, legal_entity_id, journal_id):
        # Create and attach evidence
        evidence = await enforcer.create_evidence(
            filename="invoice.pdf",
            file_content=b"dummy",
            mime_type="application/pdf",
            evidence_type=EvidenceType.INVOICE,
            legal_entity_id=legal_entity_id,
        )
        await enforcer.attach_evidence_to_journal(journal_id, evidence.evidence_id, legal_entity_id)
        # Verify evidence
        await enforcer.verify_evidence(evidence.evidence_id, legal_entity_id, "verifier")
        result, violation = await enforcer.enforce_evidence_mandate(
            journal_id=journal_id,
            legal_entity_id=legal_entity_id,
            journal_type="PAYMENT_JOURNAL",
            amount=Decimal("1000"),
            raise_on_violation=False,
        )
        assert result is True
        assert violation is None

    @pytest.mark.asyncio
    async def test_enforce_missing_required_type(self, enforcer, legal_entity_id, journal_id):
        # Create evidence of wrong type (RECEIPT instead of INVOICE)
        evidence = await enforcer.create_evidence(
            filename="receipt.pdf",
            file_content=b"dummy",
            mime_type="application/pdf",
            evidence_type=EvidenceType.RECEIPT,
            legal_entity_id=legal_entity_id,
        )
        await enforcer.attach_evidence_to_journal(journal_id, evidence.evidence_id, legal_entity_id)
        await enforcer.verify_evidence(evidence.evidence_id, legal_entity_id, "verifier")
        # PAYMENT_JOURNAL requires INVOICE and RECEIPT
        result, violation = await enforcer.enforce_evidence_mandate(
            journal_id=journal_id,
            legal_entity_id=legal_entity_id,
            journal_type="PAYMENT_JOURNAL",
            amount=Decimal("1000"),
            raise_on_violation=False,
        )
        assert result is False
        assert violation is not None
        assert "requires evidence of type(s): ['invoice']" in violation.message

    @pytest.mark.asyncio
    async def test_enforce_unverified_evidence(self, enforcer, legal_entity_id, journal_id):
        evidence = await enforcer.create_evidence(
            filename="invoice.pdf",
            file_content=b"dummy",
            mime_type="application/pdf",
            evidence_type=EvidenceType.INVOICE,
            legal_entity_id=legal_entity_id,
        )
        await enforcer.attach_evidence_to_journal(journal_id, evidence.evidence_id, legal_entity_id)
        # Do not verify
        result, violation = await enforcer.enforce_evidence_mandate(
            journal_id=journal_id,
            legal_entity_id=legal_entity_id,
            journal_type="PAYMENT_JOURNAL",
            amount=Decimal("1000"),
            raise_on_violation=False,
        )
        assert result is False
        assert violation is not None
        assert "not verified" in violation.message

    @pytest.mark.asyncio
    async def test_enforce_quality_below_required_strict(self, enforcer, legal_entity_id, journal_id):
        # Create evidence with low quality
        evidence = await enforcer.create_evidence(
            filename="invoice.pdf",
            file_content=b"dummy",
            mime_type="application/pdf",
            evidence_type=EvidenceType.INVOICE,
            legal_entity_id=legal_entity_id,
            quality=EvidenceQuality.LOW,
        )
        await enforcer.attach_evidence_to_journal(journal_id, evidence.evidence_id, legal_entity_id)
        await enforcer.verify_evidence(evidence.evidence_id, legal_entity_id, "verifier")
        result, violation = await enforcer.enforce_evidence_mandate(
            journal_id=journal_id,
            legal_entity_id=legal_entity_id,
            journal_type="PAYMENT_JOURNAL",
            amount=Decimal("1000"),
            raise_on_violation=False,
        )
        assert result is False
        assert violation is not None
        assert "quality low is below required medium" in violation.message

    @pytest.mark.asyncio
    async def test_enforce_quality_below_required_non_strict(self, enforcer, legal_entity_id, journal_id):
        enforcer.set_strict_mode(False)
        evidence = await enforcer.create_evidence(
            filename="invoice.pdf",
            file_content=b"dummy",
            mime_type="application/pdf",
            evidence_type=EvidenceType.INVOICE,
            legal_entity_id=legal_entity_id,
            quality=EvidenceQuality.LOW,
        )
        await enforcer.attach_evidence_to_journal(journal_id, evidence.evidence_id, legal_entity_id)
        await enforcer.verify_evidence(evidence.evidence_id, legal_entity_id, "verifier")
        result, violation = await enforcer.enforce_evidence_mandate(
            journal_id=journal_id,
            legal_entity_id=legal_entity_id,
            journal_type="PAYMENT_JOURNAL",
            amount=Decimal("1000"),
            raise_on_violation=False,
        )
        # Non-strict mode: should pass (only warning logged)
        assert result is True
        assert violation is None

    @pytest.mark.asyncio
    async def test_enforce_threshold_based_mandatory(self, enforcer, legal_entity_id, journal_id):
        # CLOSING_JOURNAL is not mandatory unless amount >= threshold (100,000,000)
        # Test below threshold
        result, violation = await enforcer.enforce_evidence_mandate(
            journal_id=journal_id,
            legal_entity_id=legal_entity_id,
            journal_type="CLOSING_JOURNAL",
            amount=Decimal("50000000"),
            raise_on_violation=False,
        )
        assert result is True
        assert violation is None
        # Test above threshold
        result2, violation2 = await enforcer.enforce_evidence_mandate(
            journal_id=journal_id,
            legal_entity_id=legal_entity_id,
            journal_type="CLOSING_JOURNAL",
            amount=Decimal("150000000"),
            raise_on_violation=False,
        )
        assert result2 is False
        assert violation2 is not None
        assert "requires at least 1" in violation2.message

    @pytest.mark.asyncio
    async def test_enforce_raises_exception(self, enforcer, legal_entity_id, journal_id):
        with pytest.raises(EvidenceMandateViolation) as exc:
            await enforcer.enforce_evidence_mandate(
                journal_id=journal_id,
                legal_entity_id=legal_entity_id,
                journal_type="PAYMENT_JOURNAL",
                amount=Decimal("1000"),
                raise_on_violation=True,
            )
        assert "requires at least 1" in str(exc.value)

    # -------- create_evidence ----------
    @pytest.mark.asyncio
    async def test_create_evidence(self, enforcer, legal_entity_id):
        evidence = await enforcer.create_evidence(
            filename="test.pdf",
            file_content=b"test content",
            mime_type="application/pdf",
            evidence_type=EvidenceType.CONTRACT,
            legal_entity_id=legal_entity_id,
            description="Test contract",
            quality=EvidenceQuality.HIGH,
            expiry_days=30,
        )
        assert isinstance(evidence, Evidence)
        assert evidence.filename == "test.pdf"
        assert evidence.evidence_type == EvidenceType.CONTRACT
        assert evidence.quality == EvidenceQuality.HIGH
        assert evidence.verification_status == EvidenceVerificationStatus.PENDING
        assert evidence.cryptographic_hash != ""
        assert evidence.expiry_date is not None
        # Verify it's stored
        stored = await enforcer.get_evidence_by_id(evidence.evidence_id, legal_entity_id)
        assert stored is not None
        assert stored.filename == "test.pdf"

    @pytest.mark.asyncio
    async def test_create_evidence_default_quality(self, enforcer, legal_entity_id):
        evidence = await enforcer.create_evidence(
            filename="test.pdf",
            file_content=b"test",
            mime_type="application/pdf",
            evidence_type=EvidenceType.INVOICE,
            legal_entity_id=legal_entity_id,
        )
        assert evidence.quality == EvidenceQuality.MEDIUM

    # -------- attach/detach ----------
    @pytest.mark.asyncio
    async def test_attach_evidence(self, enforcer, legal_entity_id, journal_id):
        evidence = await enforcer.create_evidence(
            filename="test.pdf",
            file_content=b"test",
            mime_type="application/pdf",
            evidence_type=EvidenceType.INVOICE,
            legal_entity_id=legal_entity_id,
        )
        result = await enforcer.attach_evidence_to_journal(journal_id, evidence.evidence_id, legal_entity_id)
        assert result is True
        summary = await enforcer.get_evidence_summary(journal_id, legal_entity_id)
        assert summary["evidence_count"] == 1
        assert summary["evidence"][0]["filename"] == "test.pdf"

    @pytest.mark.asyncio
    async def test_detach_evidence(self, enforcer, legal_entity_id, journal_id):
        evidence = await enforcer.create_evidence(
            filename="test.pdf",
            file_content=b"test",
            mime_type="application/pdf",
            evidence_type=EvidenceType.INVOICE,
            legal_entity_id=legal_entity_id,
        )
        await enforcer.attach_evidence_to_journal(journal_id, evidence.evidence_id, legal_entity_id)
        result = await enforcer.detach_evidence_from_journal(journal_id, evidence.evidence_id, legal_entity_id)
        assert result is True
        summary = await enforcer.get_evidence_summary(journal_id, legal_entity_id)
        assert summary["evidence_count"] == 0

    # -------- verify_evidence ----------
    @pytest.mark.asyncio
    async def test_verify_evidence(self, enforcer, legal_entity_id):
        evidence = await enforcer.create_evidence(
            filename="test.pdf",
            file_content=b"test",
            mime_type="application/pdf",
            evidence_type=EvidenceType.INVOICE,
            legal_entity_id=legal_entity_id,
        )
        result = await enforcer.verify_evidence(
            evidence.evidence_id,
            legal_entity_id,
            "verifier",
            EvidenceVerificationStatus.VERIFIED,
            notes="Looks good"
        )
        assert result is True
        stored = await enforcer.get_evidence_by_id(evidence.evidence_id, legal_entity_id)
        assert stored.verification_status == EvidenceVerificationStatus.VERIFIED
        assert stored.verified_by == "verifier"

    # -------- get_evidence_summary ----------
    @pytest.mark.asyncio
    async def test_get_evidence_summary(self, enforcer, legal_entity_id, journal_id):
        ev1 = await enforcer.create_evidence(
            filename="a.pdf", file_content=b"a", mime_type="pdf",
            evidence_type=EvidenceType.INVOICE, legal_entity_id=legal_entity_id
        )
        ev2 = await enforcer.create_evidence(
            filename="b.pdf", file_content=b"b", mime_type="pdf",
            evidence_type=EvidenceType.RECEIPT, legal_entity_id=legal_entity_id
        )
        await enforcer.attach_evidence_to_journal(journal_id, ev1.evidence_id, legal_entity_id)
        await enforcer.attach_evidence_to_journal(journal_id, ev2.evidence_id, legal_entity_id)
        summary = await enforcer.get_evidence_summary(journal_id, legal_entity_id)
        assert summary["journal_id"] == str(journal_id)
        assert summary["evidence_count"] == 2
        assert len(summary["evidence"]) == 2

    # -------- get_evidence_by_id ----------
    @pytest.mark.asyncio
    async def test_get_evidence_by_id(self, enforcer, legal_entity_id):
        evidence = await enforcer.create_evidence(
            filename="test.pdf", file_content=b"test", mime_type="pdf",
            evidence_type=EvidenceType.CONTRACT, legal_entity_id=legal_entity_id,
            description="Test desc"
        )
        retrieved = await enforcer.get_evidence_by_id(evidence.evidence_id, legal_entity_id)
        assert retrieved is not None
        assert retrieved.evidence_id == evidence.evidence_id
        assert retrieved.filename == "test.pdf"
        # wrong legal entity
        assert await enforcer.get_evidence_by_id(evidence.evidence_id, uuid4()) is None

    # -------- validate_evidence_quality ----------
    @pytest.mark.asyncio
    async def test_validate_evidence_quality(self, enforcer, legal_entity_id):
        # Create evidence with file size > 50MB
        evidence = await enforcer.create_evidence(
            filename="test.pdf",
            file_content=b"test" * (20 * 1024 * 1024),  # 80MB
            mime_type="application/pdf",
            evidence_type=EvidenceType.INVOICE,
            legal_entity_id=legal_entity_id,
            description="Test",
        )
        quality, issues = await enforcer.validate_evidence_quality(evidence.evidence_id, legal_entity_id)
        assert quality == EvidenceQuality.LOW
        assert any("File size exceeds 50MB limit" in i for i in issues)

    @pytest.mark.asyncio
    async def test_validate_evidence_quality_missing_description(self, enforcer, legal_entity_id):
        evidence = await enforcer.create_evidence(
            filename="test.pdf",
            file_content=b"test",
            mime_type="application/pdf",
            evidence_type=EvidenceType.INVOICE,
            legal_entity_id=legal_entity_id,
            description=None,
        )
        quality, issues = await enforcer.validate_evidence_quality(evidence.evidence_id, legal_entity_id)
        assert quality == EvidenceQuality.MEDIUM
        assert any("Missing description" in i for i in issues)

    # -------- get_violations ----------
    @pytest.mark.asyncio
    async def test_get_violations(self, enforcer, legal_entity_id, journal_id):
        # trigger a violation
        await enforcer.enforce_evidence_mandate(
            journal_id=journal_id,
            legal_entity_id=legal_entity_id,
            journal_type="PAYMENT_JOURNAL",
            amount=Decimal("1000"),
            raise_on_violation=False,
        )
        violations = enforcer.get_violations()
        assert len(violations) == 1
        assert violations[0].journal_type == "PAYMENT_JOURNAL"
        # test filtering
        filtered = enforcer.get_violations(journal_type="PAYMENT_JOURNAL")
        assert len(filtered) == 1
        filtered2 = enforcer.get_violations(journal_type="OTHER")
        assert len(filtered2) == 0

    # -------- get_statistics ----------
    @pytest.mark.asyncio
    async def test_get_statistics(self, enforcer, legal_entity_id, journal_id):
        # initially zero violations
        stats = enforcer.get_statistics()
        assert stats["total_violations"] == 0
        assert stats["enabled"] is True
        assert stats["strict_mode"] is True
        assert stats["active_requirements"] > 0

        # trigger violation
        await enforcer.enforce_evidence_mandate(
            journal_id=journal_id,
            legal_entity_id=legal_entity_id,
            journal_type="PAYMENT_JOURNAL",
            amount=Decimal("1000"),
            raise_on_violation=False,
        )
        stats2 = enforcer.get_statistics()
        assert stats2["total_violations"] == 1
        assert "PAYMENT_JOURNAL" in stats2["by_journal_type"]
        assert stats2["by_journal_type"]["PAYMENT_JOURNAL"] == 1
        assert "CRITICAL" in stats2["by_severity"]

    # -------- reset ----------
    def test_reset(self, enforcer):
        enforcer._violation_history = ["mock"]
        enforcer._requirements = {}
        enforcer._enabled = False
        enforcer._strict_mode = False
        old_version = enforcer._version
        enforcer.reset()
        assert len(enforcer._violation_history) == 0
        assert len(enforcer._requirements) > 0
        assert enforcer._enabled is True
        assert enforcer._strict_mode is True
        assert enforcer._version == old_version + 1

    # -------- sync check ----------
    def test_check_valid_context(self, enforcer):
        context = {
            "journal_id": str(uuid4()),
            "legal_entity_id": str(uuid4()),
            "journal_type": "PAYMENT",
            "amount": "1000",
        }
        errors = enforcer.check(context)
        assert errors == []

    def test_check_invalid_context(self, enforcer):
        context = {
            "journal_id": "invalid",
            "legal_entity_id": "invalid",
            "journal_type": "",
            "amount": "not a number",
        }
        errors = enforcer.check(context)
        assert len(errors) >= 4
        assert any("journal_id must be a valid UUID" in e for e in errors)
        assert any("legal_entity_id must be a valid UUID" in e for e in errors)
        assert any("journal_type is required" in e for e in errors)
        assert any("amount must be a valid number" in e for e in errors)

    # -------- entity methods ----------
    def test_validate(self, enforcer):
        result = enforcer.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

        # invalid max_history
        enforcer._max_history = 0
        result2 = enforcer.validate()
        assert result2["is_valid"] is False
        assert "max_history must be positive" in result2["errors"]

    def test_to_dict(self, enforcer):
        data = enforcer.to_dict()
        assert data["enabled"] is True
        assert data["strict_mode"] is True
        assert data["requirements_count"] > 0
        assert data["violations_count"] == 0
        assert "version" in data

    def test_from_dict(self):
        data = {
            "enabled": False,
            "strict_mode": False,
            "max_history": 5000,
            "version": 3,
        }
        enforcer = EvidenceMandateEnforcer.from_dict(data)
        assert enforcer._enabled is False
        assert enforcer._strict_mode is False
        assert enforcer._max_history == 5000
        assert enforcer._version == 3

    def test_clone(self, enforcer):
        enforcer._enabled = False
        enforcer._strict_mode = False
        clone = enforcer.clone()
        assert clone is not enforcer
        assert clone._enabled == enforcer._enabled
        assert clone._strict_mode == enforcer._strict_mode
        assert clone._version == enforcer._version + 1

    def test_snapshot(self, enforcer):
        snap = enforcer.snapshot()
        assert "version" in snap
        assert "violations_count" in snap
        assert "enabled" in snap
        assert "strict_mode" in snap
        assert "timestamp" in snap

    def test_version(self, enforcer):
        assert enforcer.version() == 1
        enforcer._version = 5
        assert enforcer.version() == 5

    def test_audit_trail(self, enforcer):
        enforcer._audit_trail = [{"a": 1}, {"b": 2}, {"c": 3}]
        trail = enforcer.audit_trail(limit=2)
        assert len(trail) == 2
        assert trail[0] == {"b": 2}
        assert trail[1] == {"c": 3}

    def test_touch(self, enforcer):
        old_version = enforcer._version
        old_trail_len = len(enforcer._audit_trail)
        enforcer.touch("tester")
        assert enforcer._version == old_version + 1
        assert len(enforcer._audit_trail) == old_trail_len + 1
        last = enforcer._audit_trail[-1]
        assert last["action"] == "TOUCH"
        assert last["performed_by"] == "tester"


# -----------------------------------------------------------------------------
# Singleton accessor tests
# -----------------------------------------------------------------------------
def test_get_evidence_mandate_enforcer_singleton():
    e1 = get_evidence_mandate_enforcer()
    e2 = get_evidence_mandate_enforcer()
    assert e1 is e2


# -----------------------------------------------------------------------------
# Base abstract class test
# -----------------------------------------------------------------------------
def test_base_abstract_class():
    assert BaseEvidenceMandateEnforcer is not None
    with pytest.raises(TypeError):
        BaseEvidenceMandateEnforcer()
