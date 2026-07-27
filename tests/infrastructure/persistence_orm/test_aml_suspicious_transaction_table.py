# tests/infrastructure/persistence_orm/test_aml_suspicious_transaction_table.py
# Comprehensive tests for AMLSuspiciousTransactionTable ORM model

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from infrastructure.persistence_orm.aml_suspicious_transaction_table import (
    AMLSuspiciousTransactionTable,
)


class TestAMLSuspiciousTransactionTable:
    """Tests for the AMLSuspiciousTransactionTable ORM table model."""

    def test_tablename_defined(self):
        assert hasattr(AMLSuspiciousTransactionTable, "__tablename__")
        assert isinstance(AMLSuspiciousTransactionTable.__tablename__, str)
        assert len(AMLSuspiciousTransactionTable.__tablename__) > 0

    def test_instantiation(self):
        """ORM model can be instantiated in-memory."""
        instance = AMLSuspiciousTransactionTable(
            id=uuid4(),
            transaction_id=uuid4(),
            transaction_type="journal",
            customer_id=uuid4(),
            customer_name="John Doe",
            transaction_date=date.today(),
            transaction_amount=Decimal("15000000"),
            currency="IDR",
            detection_type="automated_rule",
            risk_level="medium",
            status="pending_review",
            detected_at=datetime.now(UTC),
        )
        assert isinstance(instance, AMLSuspiciousTransactionTable)
        assert instance.transaction_amount == Decimal("15000000")

    # -------------------- Fixtures --------------------
    @pytest.fixture
    def pending_str(self):
        return AMLSuspiciousTransactionTable(
            id=uuid4(),
            transaction_id=uuid4(),
            transaction_type="payment",
            customer_id=uuid4(),
            customer_name="Alice",
            transaction_date=date(2026, 1, 15),
            transaction_amount=Decimal("100000000"),
            currency="IDR",
            detection_type="automated_rule",
            detection_rule_id="R001",
            detection_score=Decimal("85.5"),
            risk_level="high",
            status="pending_review",
            detected_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            version=1,
        )

    @pytest.fixture
    def under_investigation_str(self):
        return AMLSuspiciousTransactionTable(
            id=uuid4(),
            transaction_id=uuid4(),
            transaction_type="payment",
            customer_id=uuid4(),
            customer_name="Bob",
            transaction_date=date(2026, 1, 15),
            transaction_amount=Decimal("50000000"),
            currency="IDR",
            detection_type="manual_report",
            risk_level="critical",
            status="under_investigation",
            detected_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            version=1,
        )

    @pytest.fixture
    def filed_str(self):
        return AMLSuspiciousTransactionTable(
            id=uuid4(),
            transaction_id=uuid4(),
            transaction_type="payment",
            customer_id=uuid4(),
            customer_name="Charlie",
            transaction_date=date(2026, 1, 15),
            transaction_amount=Decimal("75000000"),
            currency="IDR",
            detection_type="external_alert",
            risk_level="high",
            status="filed",
            filed_to_authority=True,
            filed_at=datetime(2026, 1, 20, 12, 0, 0, tzinfo=UTC),
            version=1,
        )

    @pytest.fixture
    def dismissed_str(self):
        return AMLSuspiciousTransactionTable(
            id=uuid4(),
            transaction_id=uuid4(),
            transaction_type="payment",
            customer_id=uuid4(),
            customer_name="David",
            transaction_date=date(2026, 1, 15),
            transaction_amount=Decimal("25000000"),
            currency="IDR",
            detection_type="automated_rule",
            risk_level="low",
            status="dismissed",
            version=1,
        )

    @pytest.fixture
    def escalated_str(self):
        return AMLSuspiciousTransactionTable(
            id=uuid4(),
            transaction_id=uuid4(),
            transaction_type="payment",
            customer_id=uuid4(),
            customer_name="Eve",
            transaction_date=date(2026, 1, 15),
            transaction_amount=Decimal("120000000"),
            currency="IDR",
            detection_type="automated_rule",
            risk_level="critical",
            status="escalated",
            version=1,
        )

    # -------------------- Property Tests --------------------
    def test_is_pending(self, pending_str, under_investigation_str):
        assert pending_str.is_pending is True
        assert under_investigation_str.is_pending is False

    def test_is_under_investigation(self, pending_str, under_investigation_str):
        assert pending_str.is_under_investigation is False
        assert under_investigation_str.is_under_investigation is True

    def test_is_filed(self, pending_str, filed_str):
        assert pending_str.is_filed is False
        assert filed_str.is_filed is True

    def test_is_dismissed(self, pending_str, dismissed_str):
        assert pending_str.is_dismissed is False
        assert dismissed_str.is_dismissed is True

    def test_is_escalated(self, pending_str, escalated_str):
        assert pending_str.is_escalated is False
        assert escalated_str.is_escalated is True

    def test_requires_immediate_action(self):
        # high risk + pending
        str1 = AMLSuspiciousTransactionTable(risk_level="high", status="pending_review")
        assert str1.requires_immediate_action is True
        # critical risk + pending
        str2 = AMLSuspiciousTransactionTable(risk_level="critical", status="pending_review")
        assert str2.requires_immediate_action is True
        # medium risk + pending -> False
        str3 = AMLSuspiciousTransactionTable(risk_level="medium", status="pending_review")
        assert str3.requires_immediate_action is False
        # high risk but not pending -> False
        str4 = AMLSuspiciousTransactionTable(risk_level="high", status="under_investigation")
        assert str4.requires_immediate_action is False

    # -------------------- start_review --------------------
    def test_start_review_from_pending(self, pending_str):
        reviewer_id = uuid4()
        with patch("infrastructure.persistence_orm.aml_suspicious_transaction_table.datetime") as mock_dt:
            fixed_now = datetime(2026, 1, 16, 9, 0, 0, tzinfo=UTC)
            mock_dt.utcnow.return_value = fixed_now.replace(tzinfo=None)
            pending_str.start_review(reviewer_id)
        assert pending_str.reviewed_by == reviewer_id
        assert pending_str.reviewed_at == fixed_now.replace(tzinfo=None)
        assert pending_str.version == 2

    def test_start_review_from_invalid_status_raises(self, under_investigation_str):
        reviewer_id = uuid4()
        with pytest.raises(ValueError, match="Cannot review transaction with status under_investigation"):
            under_investigation_str.start_review(reviewer_id)

    # -------------------- conclude_review --------------------
    def test_conclude_review_dismissed(self, pending_str):
        with patch("infrastructure.persistence_orm.aml_suspicious_transaction_table.datetime") as mock_dt:
            fixed_now = datetime(2026, 1, 16, 10, 0, 0, tzinfo=UTC)
            mock_dt.utcnow.return_value = fixed_now.replace(tzinfo=None)
            pending_str.conclude_review(status="dismissed", notes="No evidence", is_filed=False)
        assert pending_str.status == "dismissed"
        assert pending_str.review_notes == "No evidence"
        assert pending_str.filed_to_authority is False
        assert pending_str.filed_at is None
        assert pending_str.version == 2

    def test_conclude_review_filed(self, pending_str):
        with patch("infrastructure.persistence_orm.aml_suspicious_transaction_table.datetime") as mock_dt:
            fixed_now = datetime(2026, 1, 16, 10, 0, 0, tzinfo=UTC)
            mock_dt.utcnow.return_value = fixed_now.replace(tzinfo=None)
            pending_str.conclude_review(status="filed", notes="Suspicious, filing to PPATK", is_filed=True)
        assert pending_str.status == "filed"
        assert pending_str.filed_to_authority is True
        assert pending_str.filed_at == fixed_now.replace(tzinfo=None)
        assert pending_str.version == 2

    def test_conclude_review_escalated(self, pending_str):
        pending_str.conclude_review(status="escalated", notes="Escalate to investigation")
        assert pending_str.status == "escalated"
        assert pending_str.filed_to_authority is False

    def test_conclude_review_invalid_status_raises(self, pending_str):
        with pytest.raises(ValueError, match="Invalid conclusion status: invalid"):
            pending_str.conclude_review(status="invalid", notes="test")

    # -------------------- escalate_to_investigation --------------------
    def test_escalate_to_investigation_from_pending(self, pending_str):
        investigator_id = uuid4()
        with patch("infrastructure.persistence_orm.aml_suspicious_transaction_table.datetime") as mock_dt:
            fixed_now = datetime(2026, 1, 16, 11, 0, 0, tzinfo=UTC)
            mock_dt.utcnow.return_value = fixed_now.replace(tzinfo=None)
            pending_str.escalate_to_investigation(investigator_id)
        assert pending_str.status == "under_investigation"
        assert pending_str.reviewed_by == investigator_id
        assert pending_str.reviewed_at == fixed_now.replace(tzinfo=None)
        assert pending_str.investigation_started_at == fixed_now.replace(tzinfo=None)
        assert pending_str.version == 2

    def test_escalate_to_investigation_from_invalid_status_raises(self, under_investigation_str):
        with pytest.raises(ValueError, match="Cannot escalate from status under_investigation"):
            under_investigation_str.escalate_to_investigation(uuid4())

    # -------------------- conclude_investigation --------------------
    def test_conclude_investigation_dismissed(self, under_investigation_str):
        with patch("infrastructure.persistence_orm.aml_suspicious_transaction_table.datetime") as mock_dt:
            fixed_now = datetime(2026, 1, 17, 10, 0, 0, tzinfo=UTC)
            mock_dt.utcnow.return_value = fixed_now.replace(tzinfo=None)
            under_investigation_str.conclude_investigation(
                findings="No fraud found", status="dismissed"
            )
        assert under_investigation_str.status == "dismissed"
        assert under_investigation_str.investigation_findings == "No fraud found"
        assert under_investigation_str.investigation_concluded_at == fixed_now.replace(tzinfo=None)
        assert under_investigation_str.filed_to_authority is False
        assert under_investigation_str.version == 2

    def test_conclude_investigation_filed(self, under_investigation_str):
        with patch("infrastructure.persistence_orm.aml_suspicious_transaction_table.datetime") as mock_dt:
            fixed_now = datetime(2026, 1, 17, 10, 0, 0, tzinfo=UTC)
            mock_dt.utcnow.return_value = fixed_now.replace(tzinfo=None)
            under_investigation_str.conclude_investigation(
                findings="Confirmed fraud", status="filed", filing_reference="PPATK-2026-001"
            )
        assert under_investigation_str.status == "filed"
        assert under_investigation_str.filed_to_authority is True
        assert under_investigation_str.filing_reference == "PPATK-2026-001"
        assert under_investigation_str.filed_at == fixed_now.replace(tzinfo=None)
        assert under_investigation_str.version == 2

    def test_conclude_investigation_from_invalid_status_raises(self, pending_str):
        with pytest.raises(ValueError, match="Cannot conclude investigation from status pending_review"):
            pending_str.conclude_investigation(findings="x", status="dismissed")

    def test_conclude_investigation_invalid_status_raises(self, under_investigation_str):
        with pytest.raises(ValueError, match="Invalid conclusion status: invalid"):
            under_investigation_str.conclude_investigation(findings="x", status="invalid")

    # -------------------- file_to_authority --------------------
    def test_file_to_authority_from_under_investigation(self, under_investigation_str):
        filed_by = uuid4()
        with patch("infrastructure.persistence_orm.aml_suspicious_transaction_table.datetime") as mock_dt:
            fixed_now = datetime(2026, 1, 18, 12, 0, 0, tzinfo=UTC)
            mock_dt.utcnow.return_value = fixed_now.replace(tzinfo=None)
            under_investigation_str.file_to_authority(
                filing_reference="PPATK-2026-002", filed_by=filed_by
            )
        assert under_investigation_str.status == "filed"
        assert under_investigation_str.filed_to_authority is True
        assert under_investigation_str.filing_reference == "PPATK-2026-002"
        assert under_investigation_str.filed_at == fixed_now.replace(tzinfo=None)
        assert under_investigation_str.filed_by == filed_by
        assert under_investigation_str.version == 2

    def test_file_to_authority_from_escalated(self, escalated_str):
        filed_by = uuid4()
        with patch("infrastructure.persistence_orm.aml_suspicious_transaction_table.datetime") as mock_dt:
            fixed_now = datetime(2026, 1, 18, 12, 0, 0, tzinfo=UTC)
            mock_dt.utcnow.return_value = fixed_now.replace(tzinfo=None)
            escalated_str.file_to_authority(
                filing_reference="PPATK-2026-003", filed_by=filed_by
            )
        assert escalated_str.status == "filed"
        assert escalated_str.filed_to_authority is True

    def test_file_to_authority_from_invalid_status_raises(self, pending_str):
        with pytest.raises(ValueError, match="Cannot file STR from status pending_review"):
            pending_str.file_to_authority(filing_reference="ref", filed_by=uuid4())

    # -------------------- to_dict --------------------
    def test_to_dict(self, pending_str):
        d = pending_str.to_dict()
        assert d["id"] == str(pending_str.id)
        assert d["transaction_id"] == str(pending_str.transaction_id)
        assert d["transaction_type"] == "payment"
        assert d["customer_name"] == "Alice"
        assert d["transaction_amount"] == float(pending_str.transaction_amount)
        assert d["detection_type"] == "automated_rule"
        assert d["detection_score"] == float(pending_str.detection_score)
        assert d["risk_level"] == "high"
        assert d["status"] == "pending_review"
        assert d["filed_to_authority"] is False
        assert d["version"] == 1

    def test_to_dict_with_none_detection_score(self):
        str_obj = AMLSuspiciousTransactionTable(
            id=uuid4(),
            transaction_id=uuid4(),
            transaction_type="payment",
            customer_id=uuid4(),
            customer_name="Test",
            transaction_date=date.today(),
            transaction_amount=Decimal("1000"),
            detection_type="manual_report",
            detection_score=None,
        )
        d = str_obj.to_dict()
        assert d["detection_score"] is None

    # -------------------- Version increment consistency --------------------
    def test_version_increment_on_all_mutations(self, pending_str):
        pending_str.start_review(uuid4())
        assert pending_str.version == 2
        pending_str.conclude_review(status="dismissed", notes="ok")
        assert pending_str.version == 3

        # reset
        str2 = AMLSuspiciousTransactionTable(status="pending_review", version=1)
        str2.escalate_to_investigation(uuid4())
        assert str2.version == 2
        str2.conclude_investigation(findings="ok", status="dismissed")
        assert str2.version == 3
        # create new
        str3 = AMLSuspiciousTransactionTable(status="under_investigation", version=1)
        str3.file_to_authority(filing_reference="ref", filed_by=uuid4())
        assert str3.version == 2

    # -------------------- Edge cases and validation --------------------
    def test_start_review_with_none_reviewer(self, pending_str):
        # reviewer_id is UUID, cannot be None, but we don't test type
        pass

    def test_conclude_review_with_empty_notes(self, pending_str):
        pending_str.conclude_review(status="dismissed", notes="")
        assert pending_str.review_notes == ""

    def test_escalate_to_investigation_sets_reviewed_fields(self, pending_str):
        reviewer = uuid4()
        with patch("infrastructure.persistence_orm.aml_suspicious_transaction_table.datetime") as mock_dt:
            fixed_now = datetime(2026, 1, 16, 11, 0, 0, tzinfo=UTC)
            mock_dt.utcnow.return_value = fixed_now.replace(tzinfo=None)
            pending_str.escalate_to_investigation(reviewer)
        assert pending_str.reviewed_by == reviewer
        assert pending_str.reviewed_at == fixed_now.replace(tzinfo=None)
        assert pending_str.investigation_started_at == fixed_now.replace(tzinfo=None)

    def test_file_to_authority_sets_filed_by(self):
        str_obj = AMLSuspiciousTransactionTable(status="under_investigation")
        filed_by = uuid4()
        str_obj.file_to_authority(filing_reference="ref", filed_by=filed_by)
        assert str_obj.filed_by == filed_by