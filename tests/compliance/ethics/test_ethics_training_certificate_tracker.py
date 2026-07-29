# tests/compliance/ethics/test_ethics_training_certificate_tracker.py
"""
Comprehensive tests for compliance/ethics/ethics_training_certificate_tracker.py.
Covers all public methods, edge cases, and state transitions.
"""

import json
import tempfile
from datetime import date, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from compliance.ethics.ethics_training_certificate_tracker import (
    EthicsTrainingCertificateTracker,
    TrainingCertificate,
    TrainingStatus,
    TrainingType,
)


# ============================================================================
# Tests for Enums
# ============================================================================
class TestTrainingType:
    def test_members_exist(self):
        assert hasattr(TrainingType, "CODE_OF_CONDUCT")
        assert hasattr(TrainingType, "ANTI_BRIBERY")
        assert hasattr(TrainingType, "CONFLICT_OF_INTEREST")
        assert hasattr(TrainingType, "DATA_PRIVACY")
        assert hasattr(TrainingType, "INSIDER_TRADING")
        assert hasattr(TrainingType, "WHISTLEBLOWER")
        assert hasattr(TrainingType, "FINANCIAL_ETHICS")
        assert hasattr(TrainingType, "LEADERSHIP_ETHICS")

    def test_member_is_instance(self):
        assert isinstance(TrainingType.CODE_OF_CONDUCT, TrainingType)


class TestTrainingStatus:
    def test_members_exist(self):
        assert hasattr(TrainingStatus, "ACTIVE")
        assert hasattr(TrainingStatus, "EXPIRED")
        assert hasattr(TrainingStatus, "REVOKED")
        assert hasattr(TrainingStatus, "PENDING_RENEWAL")

    def test_member_is_instance(self):
        assert isinstance(TrainingStatus.ACTIVE, TrainingStatus)


# ============================================================================
# Tests for TrainingCertificate
# ============================================================================
class TestTrainingCertificate:
    @pytest.fixture
    def cert_data(self):
        return {
            "certificate_id": uuid4(),
            "employee_id": uuid4(),
            "employee_name": "John Doe",
            "training_type": TrainingType.CODE_OF_CONDUCT,
            "training_name": "Code of Conduct 2025",
            "completion_date": date(2025, 1, 15),
            "expiry_date": date(2026, 1, 15),
            "score": 95,
            "provider": "Ethics Training Inc.",
            "certificate_url": "s3://certs/abc123.pdf",
            "status": TrainingStatus.ACTIVE,
            "verified_by": uuid4(),
        }

    @pytest.fixture
    def cert(self, cert_data):
        return TrainingCertificate(**cert_data)

    def test_construction(self, cert_data):
        instance = TrainingCertificate(**cert_data)
        assert instance.id == cert_data["certificate_id"]
        assert instance.employee_id == cert_data["employee_id"]
        assert instance.employee_name == cert_data["employee_name"]
        assert instance.training_type == cert_data["training_type"]
        assert instance.training_name == cert_data["training_name"]
        assert instance.completion_date == cert_data["completion_date"]
        assert instance.expiry_date == cert_data["expiry_date"]
        assert instance.score == cert_data["score"]
        assert instance.provider == cert_data["provider"]
        assert instance.certificate_url == cert_data["certificate_url"]
        assert instance.status == cert_data["status"]
        assert instance.verified_by == cert_data["verified_by"]
        assert instance._hash is not None
        assert instance.created_at is not None
        assert instance.updated_at is not None

    def test_is_valid_active_with_future_expiry(self, cert):
        assert cert.is_valid() is True
        assert cert.is_valid(reference_date=date(2025, 6, 1)) is True

    def test_is_valid_active_with_past_expiry(self, cert):
        assert cert.is_valid(reference_date=date(2026, 6, 1)) is False
        # Still ACTIVE but expired
        cert.status = TrainingStatus.ACTIVE
        cert.expiry_date = date(2025, 1, 1)
        assert cert.is_valid(reference_date=date(2026, 1, 1)) is False

    def test_is_valid_revoked(self, cert):
        cert.status = TrainingStatus.REVOKED
        assert cert.is_valid() is False

    def test_is_valid_expired_status(self, cert):
        cert.status = TrainingStatus.EXPIRED
        assert cert.is_valid() is False

    def test_is_valid_no_expiry_never_expires(self, cert):
        cert.expiry_date = None
        assert cert.is_valid() is True
        assert cert.is_valid(reference_date=date(2099, 1, 1)) is True

    def test_renew(self, cert):
        new_completion = date(2026, 1, 15)
        new_expiry = date(2027, 1, 15)
        new_score = 98
        renewed_by = uuid4()
        old_hash = cert._hash

        cert.renew(new_completion, new_expiry, new_score, renewed_by)

        assert cert.completion_date == new_completion
        assert cert.expiry_date == new_expiry
        assert cert.score == new_score
        assert cert.status == TrainingStatus.ACTIVE
        assert cert._hash != old_hash
        assert cert.updated_at is not None

    def test_renew_sets_updated_at(self, cert):
        old_updated = cert.updated_at
        # Small delay to ensure timestamp changes
        import time
        time.sleep(0.001)
        cert.renew(date.today(), date.today() + timedelta(days=365), 99, uuid4())
        assert cert.updated_at > old_updated

    def test_revoke(self, cert):
        revoked_by = uuid4()
        reason = "Violation found"
        old_hash = cert._hash

        cert.revoke(revoked_by, reason)

        assert cert.status == TrainingStatus.REVOKED
        assert cert._hash != old_hash
        assert cert.updated_at is not None

    def test_to_dict(self, cert_data):
        cert = TrainingCertificate(**cert_data)
        d = cert.to_dict()
        assert d["certificate_id"] == str(cert_data["certificate_id"])
        assert d["employee_id"] == str(cert_data["employee_id"])
        assert d["employee_name"] == cert_data["employee_name"]
        assert d["training_type"] == cert_data["training_type"].value
        assert d["training_name"] == cert_data["training_name"]
        assert d["completion_date"] == cert_data["completion_date"].isoformat()
        assert d["expiry_date"] == cert_data["expiry_date"].isoformat()
        assert d["score"] == cert_data["score"]
        assert d["provider"] == cert_data["provider"]
        assert d["status"] == cert_data["status"].value
        assert d["verified_by"] == str(cert_data["verified_by"])
        assert d["hash"] == cert._hash

    def test_hash_changes_on_state_change(self, cert):
        old_hash = cert._hash
        cert.renew(date.today(), date.today() + timedelta(days=365), 99, uuid4())
        assert cert._hash != old_hash

        old_hash = cert._hash
        cert.revoke(uuid4(), "Revoked")
        assert cert._hash != old_hash


# ============================================================================
# Tests for EthicsTrainingCertificateTracker
# ============================================================================
class TestEthicsTrainingCertificateTracker:
    @pytest.fixture
    def tracker(self):
        return EthicsTrainingCertificateTracker(enable_expiry_monitor=False)

    @pytest.fixture
    def employee_id(self):
        return uuid4()

    @pytest.fixture
    def cert_id(self, tracker, employee_id):
        return tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct 2025",
            completion_date=date(2025, 1, 15),
            expiry_date=date(2026, 1, 15),
            score=95,
            provider="Ethics Training Inc.",
            certificate_url="s3://certs/abc.pdf",
            verified_by=uuid4(),
        )

    @pytest.fixture
    def cert(self, tracker, cert_id):
        return tracker.get_certificate(cert_id)

    # --- Construction ---
    def test_construction_without_monitor(self):
        tracker = EthicsTrainingCertificateTracker(enable_expiry_monitor=False)
        assert tracker._certificates == {}
        assert tracker._employee_certs == {}
        assert tracker._enable_monitor is False
        assert tracker._monitor_thread is None
        assert tracker._expiry_callbacks == []

    @patch("threading.Thread")
    def test_construction_with_monitor(self, mock_thread):
        tracker = EthicsTrainingCertificateTracker(enable_expiry_monitor=True, expiry_check_interval_hours=12)
        mock_thread.assert_called_once()
        # Thread should be daemon
        args, kwargs = mock_thread.call_args
        assert kwargs.get("daemon") is True

    # --- add_certificate ---
    def test_add_certificate(self, tracker, employee_id):
        cert_id = tracker.add_certificate(
            employee_id=employee_id,
            employee_name="Jane Doe",
            training_type=TrainingType.ANTI_BRIBERY,
            training_name="Anti-Bribery 2025",
            completion_date=date(2025, 2, 1),
            expiry_date=date(2026, 2, 1),
            score=88,
            provider="Compliance Academy",
            certificate_url="s3://certs/jane_ab.pdf",
            verified_by=uuid4(),
        )
        assert cert_id in tracker._certificates
        cert = tracker._certificates[cert_id]
        assert cert.employee_id == employee_id
        assert cert.employee_name == "Jane Doe"
        assert cert.training_type == TrainingType.ANTI_BRIBERY
        assert employee_id in tracker._employee_certs
        assert cert_id in tracker._employee_certs[employee_id]

    def test_add_certificate_without_expiry(self, tracker, employee_id):
        cert_id = tracker.add_certificate(
            employee_id=employee_id,
            employee_name="No Expiry",
            training_type=TrainingType.DATA_PRIVACY,
            training_name="Data Privacy",
            completion_date=date(2025, 3, 1),
            expiry_date=None,
            score=90,
            provider="Privacy Institute",
        )
        cert = tracker.get_certificate(cert_id)
        assert cert.expiry_date is None
        assert cert.is_valid() is True

    # --- get_certificate ---
    def test_get_certificate(self, tracker, cert_id):
        cert = tracker.get_certificate(cert_id)
        assert cert is not None
        assert cert.id == cert_id

    def test_get_certificate_not_found(self, tracker):
        assert tracker.get_certificate(uuid4()) is None

    # --- get_employee_certificates ---
    def test_get_employee_certificates(self, tracker, employee_id, cert_id):
        certs = tracker.get_employee_certificates(employee_id)
        assert len(certs) == 1
        assert certs[0].id == cert_id

    def test_get_employee_certificates_multiple(self, tracker, employee_id):
        cert_id1 = tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2025, 1, 1),
            expiry_date=date(2026, 1, 1),
            score=90,
            provider="Provider A",
        )
        cert_id2 = tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.ANTI_BRIBERY,
            training_name="Anti-Bribery",
            completion_date=date(2025, 2, 1),
            expiry_date=date(2026, 2, 1),
            score=85,
            provider="Provider B",
        )
        certs = tracker.get_employee_certificates(employee_id)
        assert len(certs) == 2
        assert {c.id for c in certs} == {cert_id1, cert_id2}

    def test_get_employee_certificates_unknown_employee(self, tracker):
        assert tracker.get_employee_certificates(uuid4()) == []

    # --- get_valid_certificates ---
    def test_get_valid_certificates(self, tracker, employee_id):
        # Add valid cert
        tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2025, 1, 1),
            expiry_date=date(2026, 1, 1),
            score=90,
            provider="Provider A",
        )
        # Add expired cert (past expiry date)
        expired_cert_id = tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.ANTI_BRIBERY,
            training_name="Anti-Bribery",
            completion_date=date(2024, 1, 1),
            expiry_date=date(2024, 12, 31),
            score=80,
            provider="Provider B",
        )
        # Force the expired cert to be expired (it still has ACTIVE status but past expiry)
        # The is_valid() method checks expiry date, so it will be invalid
        valid = tracker.get_valid_certificates(employee_id)
        # Only the first one should be valid
        assert len(valid) == 1
        assert valid[0].training_type == TrainingType.CODE_OF_CONDUCT

    def test_get_valid_certificates_filter_by_type(self, tracker, employee_id):
        tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2025, 1, 1),
            expiry_date=date(2026, 1, 1),
            score=90,
            provider="Provider A",
        )
        tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.ANTI_BRIBERY,
            training_name="Anti-Bribery",
            completion_date=date(2025, 2, 1),
            expiry_date=date(2026, 2, 1),
            score=85,
            provider="Provider B",
        )
        valid = tracker.get_valid_certificates(employee_id, TrainingType.CODE_OF_CONDUCT)
        assert len(valid) == 1
        assert valid[0].training_type == TrainingType.CODE_OF_CONDUCT

    # --- has_required_training ---
    def test_has_required_training_true(self, tracker, employee_id):
        tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2025, 1, 1),
            expiry_date=date(2026, 1, 1),
            score=90,
            provider="Provider A",
        )
        assert tracker.has_required_training(employee_id, TrainingType.CODE_OF_CONDUCT) is True

    def test_has_required_training_false(self, tracker, employee_id):
        assert tracker.has_required_training(employee_id, TrainingType.CODE_OF_CONDUCT) is False

    def test_has_required_training_expired_cert(self, tracker, employee_id):
        tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2024, 1, 1),
            expiry_date=date(2024, 12, 31),
            score=90,
            provider="Provider A",
        )
        # is_valid returns False for expired cert
        assert tracker.has_required_training(employee_id, TrainingType.CODE_OF_CONDUCT) is False

    # --- get_expiring_soon ---
    def test_get_expiring_soon(self, tracker, employee_id):
        # Cert expiring in 15 days (should be found with threshold 30)
        tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2025, 1, 1),
            expiry_date=date.today() + timedelta(days=15),
            score=90,
            provider="Provider A",
        )
        # Cert expiring in 45 days (should NOT be found with threshold 30)
        tracker.add_certificate(
            employee_id=uuid4(),  # different employee
            employee_name="Jane Doe",
            training_type=TrainingType.ANTI_BRIBERY,
            training_name="Anti-Bribery",
            completion_date=date(2025, 2, 1),
            expiry_date=date.today() + timedelta(days=45),
            score=85,
            provider="Provider B",
        )
        expiring = tracker.get_expiring_soon(days_threshold=30)
        assert len(expiring) == 1
        assert expiring[0].training_type == TrainingType.CODE_OF_CONDUCT

    def test_get_expiring_soon_ignores_revoked(self, tracker, employee_id):
        cert_id = tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2025, 1, 1),
            expiry_date=date.today() + timedelta(days=15),
            score=90,
            provider="Provider A",
        )
        tracker.revoke_certificate(cert_id, uuid4(), "Revoked")
        expiring = tracker.get_expiring_soon(days_threshold=30)
        assert len(expiring) == 0

    # --- get_expired ---
    def test_get_expired(self, tracker, employee_id):
        # Cert expired yesterday
        tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2024, 1, 1),
            expiry_date=date.today() - timedelta(days=1),
            score=90,
            provider="Provider A",
        )
        # Cert expiring tomorrow (not expired yet)
        tracker.add_certificate(
            employee_id=uuid4(),
            employee_name="Jane Doe",
            training_type=TrainingType.ANTI_BRIBERY,
            training_name="Anti-Bribery",
            completion_date=date(2025, 2, 1),
            expiry_date=date.today() + timedelta(days=1),
            score=85,
            provider="Provider B",
        )
        expired = tracker.get_expired()
        assert len(expired) == 1
        assert expired[0].training_type == TrainingType.CODE_OF_CONDUCT

    # --- renew_certificate ---
    def test_renew_certificate(self, tracker, cert_id, cert):
        new_completion = date(2026, 1, 15)
        new_expiry = date(2027, 1, 15)
        new_score = 97
        renewed_by = uuid4()

        result = tracker.renew_certificate(cert_id, new_completion, new_expiry, new_score, renewed_by)
        assert result is True
        cert = tracker.get_certificate(cert_id)
        assert cert.completion_date == new_completion
        assert cert.expiry_date == new_expiry
        assert cert.score == new_score
        assert cert.status == TrainingStatus.ACTIVE

    def test_renew_certificate_not_found(self, tracker):
        result = tracker.renew_certificate(uuid4(), date.today(), date.today() + timedelta(days=365), 90, uuid4())
        assert result is False

    # --- revoke_certificate ---
    def test_revoke_certificate(self, tracker, cert_id):
        revoked_by = uuid4()
        reason = "Policy violation"
        result = tracker.revoke_certificate(cert_id, revoked_by, reason)
        assert result is True
        cert = tracker.get_certificate(cert_id)
        assert cert.status == TrainingStatus.REVOKED

    def test_revoke_certificate_not_found(self, tracker):
        result = tracker.revoke_certificate(uuid4(), uuid4(), "Reason")
        assert result is False

    # --- get_employee_compliance_summary ---
    def test_get_employee_compliance_summary_fully_compliant(self, tracker, employee_id):
        tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2025, 1, 1),
            expiry_date=date(2026, 1, 1),
            score=90,
            provider="Provider A",
        )
        tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.ANTI_BRIBERY,
            training_name="Anti-Bribery",
            completion_date=date(2025, 2, 1),
            expiry_date=date(2026, 2, 1),
            score=85,
            provider="Provider B",
        )
        required = [TrainingType.CODE_OF_CONDUCT, TrainingType.ANTI_BRIBERY]
        summary = tracker.get_employee_compliance_summary(employee_id, required)
        assert summary["employee_id"] == str(employee_id)
        assert summary["completed_count"] == 2
        assert summary["missing_trainings"] == []
        assert summary["compliant"] is True

    def test_get_employee_compliance_summary_missing_trainings(self, tracker, employee_id):
        tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2025, 1, 1),
            expiry_date=date(2026, 1, 1),
            score=90,
            provider="Provider A",
        )
        required = [TrainingType.CODE_OF_CONDUCT, TrainingType.ANTI_BRIBERY]
        summary = tracker.get_employee_compliance_summary(employee_id, required)
        assert summary["completed_count"] == 1
        assert summary["missing_trainings"] == ["anti_bribery"]
        assert summary["compliant"] is False

    def test_employee_compliance_summary_includes_expiring_soon(self, tracker, employee_id):
        tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2025, 1, 1),
            expiry_date=date.today() + timedelta(days=15),
            score=90,
            provider="Provider A",
        )
        summary = tracker.get_employee_compliance_summary(employee_id, [TrainingType.CODE_OF_CONDUCT])
        assert len(summary["expiring_soon"]) == 1
        assert summary["expiring_soon"][0]["training_type"] == "code_of_conduct"

    # --- generate_report ---
    def test_generate_report(self, tracker, employee_id):
        tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2025, 1, 1),
            expiry_date=date(2026, 1, 1),
            score=90,
            provider="Provider A",
        )
        tracker.add_certificate(
            employee_id=uuid4(),
            employee_name="Jane Doe",
            training_type=TrainingType.ANTI_BRIBERY,
            training_name="Anti-Bribery",
            completion_date=date(2025, 2, 1),
            expiry_date=date(2026, 2, 1),
            score=85,
            provider="Provider B",
        )
        report = tracker.generate_report()
        assert report["total_certificates"] == 2
        assert report["active_certificates"] == 2
        assert report["expired_certificates"] == 0
        assert report["expiring_soon"] == 0  # Not expiring soon
        assert report["by_training_type"]["code_of_conduct"] == 1
        assert report["by_training_type"]["anti_bribery"] == 1
        assert report["employees_trained"] == 2
        assert "generated_at" in report

    def test_generate_report_with_expired(self, tracker, employee_id):
        tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2024, 1, 1),
            expiry_date=date(2024, 12, 31),
            score=90,
            provider="Provider A",
        )
        # The cert is active but expired (status still ACTIVE, but expiry in past)
        report = tracker.generate_report()
        # It's still counted as active but expired
        assert report["total_certificates"] == 1
        assert report["active_certificates"] == 1
        assert report["expired_certificates"] == 1  # get_expired sees it

    # --- to_json ---
    def test_to_json(self, tracker, employee_id):
        tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2025, 1, 1),
            expiry_date=date(2026, 1, 1),
            score=90,
            provider="Provider A",
        )
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker.to_json(path)
            with open(path) as f:
                data = json.load(f)
            assert "report" in data
            assert "certificates" in data
            assert len(data["certificates"]) == 1
            assert data["certificates"][0]["employee_name"] == "John Doe"
        finally:
            import os
            os.unlink(path)

    # --- register_expiry_callback ---
    def test_register_expiry_callback(self, tracker):
        callback = MagicMock()
        tracker.register_expiry_callback(callback)
        assert callback in tracker._expiry_callbacks

    def test_expiry_callback_triggered(self, tracker, employee_id):
        callback = MagicMock()
        tracker.register_expiry_callback(callback)

        # Add a certificate that expires today
        cert_id = tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2024, 1, 1),
            expiry_date=date.today() - timedelta(days=1),  # expired yesterday
            score=90,
            provider="Provider A",
        )
        # Run the expiry check
        tracker._check_expired_certificates()

        # Callback should have been called once
        callback.assert_called_once()
        # The cert status should now be EXPIRED
        cert = tracker.get_certificate(cert_id)
        assert cert.status == TrainingStatus.EXPIRED

    def test_expiry_callback_with_multiple_callbacks(self, tracker, employee_id):
        callback1 = MagicMock()
        callback2 = MagicMock()
        tracker.register_expiry_callback(callback1)
        tracker.register_expiry_callback(callback2)

        tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2024, 1, 1),
            expiry_date=date.today() - timedelta(days=1),
            score=90,
            provider="Provider A",
        )
        tracker._check_expired_certificates()
        callback1.assert_called_once()
        callback2.assert_called_once()

    def test_expiry_callback_handles_exception(self, tracker, employee_id):
        def failing_callback(cert):
            raise RuntimeError("Callback failed")

        tracker.register_expiry_callback(failing_callback)
        # Should not raise, just log error
        tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2024, 1, 1),
            expiry_date=date.today() - timedelta(days=1),
            score=90,
            provider="Provider A",
        )
        # This should not raise
        tracker._check_expired_certificates()

    # --- _check_expired_certificates ---
    def test_check_expired_certificates_updates_status(self, tracker, employee_id):
        cert_id = tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2024, 1, 1),
            expiry_date=date.today() - timedelta(days=1),
            score=90,
            provider="Provider A",
        )
        cert = tracker.get_certificate(cert_id)
        assert cert.status == TrainingStatus.ACTIVE  # still active initially

        tracker._check_expired_certificates()
        cert = tracker.get_certificate(cert_id)
        assert cert.status == TrainingStatus.EXPIRED

    def test_check_expired_certificates_ignores_non_expired(self, tracker, employee_id):
        cert_id = tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2025, 1, 1),
            expiry_date=date(2026, 1, 1),
            score=90,
            provider="Provider A",
        )
        tracker._check_expired_certificates()
        cert = tracker.get_certificate(cert_id)
        assert cert.status == TrainingStatus.ACTIVE

    def test_check_expired_certificates_ignores_revoked(self, tracker, employee_id):
        cert_id = tracker.add_certificate(
            employee_id=employee_id,
            employee_name="John Doe",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2024, 1, 1),
            expiry_date=date.today() - timedelta(days=1),
            score=90,
            provider="Provider A",
        )
        tracker.revoke_certificate(cert_id, uuid4(), "Revoked")
        tracker._check_expired_certificates()
        cert = tracker.get_certificate(cert_id)
        # Should remain revoked, not become expired
        assert cert.status == TrainingStatus.REVOKED

    # --- _start_monitor (indirect testing) ---
    @patch("threading.Thread")
    def test_monitor_thread_started(self, mock_thread):
        tracker = EthicsTrainingCertificateTracker(enable_expiry_monitor=True, expiry_check_interval_hours=12)
        mock_thread.assert_called_once()
        # The thread should be daemon
        args, kwargs = mock_thread.call_args
        assert kwargs.get("daemon") is True
        # The target should be the monitor function
        target = kwargs.get("target")
        assert target is not None
        # The interval should be passed correctly
        assert tracker._enable_monitor is True
        assert tracker._monitor_thread is not None

    # --- Edge cases ---
    def test_certificate_with_zero_score(self, tracker, employee_id):
        # Score can be 0? The code doesn't validate, but let's test
        cert_id = tracker.add_certificate(
            employee_id=employee_id,
            employee_name="Zero Score",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2025, 1, 1),
            expiry_date=date(2026, 1, 1),
            score=0,
            provider="Provider",
        )
        cert = tracker.get_certificate(cert_id)
        assert cert.score == 0

    def test_certificate_with_no_provider(self, tracker, employee_id):
        # Provider can be empty? The code doesn't validate
        cert_id = tracker.add_certificate(
            employee_id=employee_id,
            employee_name="No Provider",
            training_type=TrainingType.CODE_OF_CONDUCT,
            training_name="Code of Conduct",
            completion_date=date(2025, 1, 1),
            expiry_date=date(2026, 1, 1),
            score=90,
            provider="",
        )
        cert = tracker.get_certificate(cert_id)
        assert cert.provider == ""

    def test_get_valid_certificates_no_valid(self, tracker, employee_id):
        assert tracker.get_valid_certificates(employee_id) == []

    def test_employee_compliance_summary_no_certs(self, tracker, employee_id):
        required = [TrainingType.CODE_OF_CONDUCT]
        summary = tracker.get_employee_compliance_summary(employee_id, required)
        assert summary["completed_count"] == 0
        assert summary["missing_trainings"] == ["code_of_conduct"]
        assert summary["compliant"] is False
        assert summary["expiring_soon"] == []

    def test_get_expiring_soon_no_expiring(self, tracker):
        assert tracker.get_expiring_soon() == []

    def test_get_expired_no_expired(self, tracker):
        assert tracker.get_expired() == []
