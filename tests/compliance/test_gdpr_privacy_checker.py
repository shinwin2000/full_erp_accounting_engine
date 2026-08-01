# test_gdpr_privacy_checker.py
# Comprehensive tests for compliance/gdpr_privacy_checker.py

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from compliance.gdpr_privacy_checker import (
    ConsentNotFoundError,
    ConsentRecord,
    ConsentStatus,
    DataBreach,
    DataBreachNotificationError,
    DataCategory,
    DataSubjectRequest,
    DataSubjectRequestType,
    ErasureResult,
    FulfillmentResponse,
    GDPRChecker,
    GDPRComplianceError,
    InvalidRequestError,
    PrivacyReport,
    PrivacyRequest,
    ProcessingActivity,
    ProcessingPurpose,
    RequestStatus,
)

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def user_id() -> UUID:
    return uuid4()


@pytest.fixture
def another_user_id() -> UUID:
    return uuid4()


@pytest.fixture
def checker() -> GDPRChecker:
    return GDPRChecker(
        dpo_email="dpo@example.com",
        supervisory_authority_email="supervisory@example.com"
    )


@pytest.fixture
def consent_record(user_id) -> ConsentRecord:
    return ConsentRecord(
        consent_id=uuid4(),
        user_id=user_id,
        purpose=ProcessingPurpose.ACCOUNTING,
        status=ConsentStatus.GIVEN,
        given_at=datetime.now(UTC),
        expiry=datetime.now(UTC) + timedelta(days=30),
        withdrawal_reason=None,
        ip_address="127.0.0.1",
        user_agent="test-agent",
    )


@pytest.fixture
def data_subject_request(user_id) -> DataSubjectRequest:
    return DataSubjectRequest(
        request_id=uuid4(),
        user_id=user_id,
        request_type=DataSubjectRequestType.ACCESS,
        request_date=datetime.now(UTC),
        details={"format": "json"},
        status=RequestStatus.PENDING,
    )


@pytest.fixture
def data_breach() -> DataBreach:
    return DataBreach(
        breach_id=uuid4(),
        description="Test breach",
        affected_data_categories=[DataCategory.PERSONAL_IDENTIFIABLE, DataCategory.SENSITIVE],
        affected_users_count=150,
        discovered_date=datetime.now(UTC),
        discovered_by=uuid4(),
        root_cause="Test root cause",
        containment_measures="Test containment",
    )


@pytest.fixture
def processing_activity() -> ProcessingActivity:
    return ProcessingActivity(
        activity_id=uuid4(),
        name="Test Processing",
        controller="Test Controller",
        purposes=[ProcessingPurpose.ACCOUNTING, ProcessingPurpose.PAYROLL],
        data_categories=[DataCategory.PERSONAL_IDENTIFIABLE, DataCategory.FINANCIAL],
        retention_period_days=365,
        recipients=["Recipient A"],
        transfers_to_third_countries=["US"],
        safeguards=["Encryption"],
    )


# =============================================================================
# Enum Tests
# =============================================================================

class TestConsentStatus:
    def test_members(self):
        assert ConsentStatus.GIVEN.value == "given"
        assert ConsentStatus.WITHDRAWN.value == "withdrawn"
        assert ConsentStatus.NOT_GIVEN.value == "not_given"
        assert ConsentStatus.EXPIRED.value == "expired"


class TestDataSubjectRequestType:
    def test_members(self):
        assert DataSubjectRequestType.ACCESS.value == "access"
        assert DataSubjectRequestType.RECTIFICATION.value == "rectification"
        assert DataSubjectRequestType.ERASURE.value == "erasure"
        assert DataSubjectRequestType.RESTRICT_PROCESSING.value == "restrict_processing"
        assert DataSubjectRequestType.DATA_PORTABILITY.value == "data_portability"
        assert DataSubjectRequestType.OBJECT.value == "object"


class TestRequestStatus:
    def test_members(self):
        assert RequestStatus.PENDING.value == "pending"
        assert RequestStatus.IN_PROGRESS.value == "in_progress"
        assert RequestStatus.FULFILLED.value == "fulfilled"
        assert RequestStatus.REJECTED.value == "rejected"
        assert RequestStatus.EXPIRED.value == "expired"


class TestProcessingPurpose:
    def test_members(self):
        assert ProcessingPurpose.ACCOUNTING.value == "accounting"
        assert ProcessingPurpose.PAYROLL.value == "payroll"
        assert ProcessingPurpose.CUSTOMER_MANAGEMENT.value == "customer_management"
        assert ProcessingPurpose.SUPPLIER_MANAGEMENT.value == "supplier_management"
        assert ProcessingPurpose.MARKETING.value == "marketing"
        assert ProcessingPurpose.ANALYTICS.value == "analytics"
        assert ProcessingPurpose.LEGAL_COMPLIANCE.value == "legal_compliance"
        assert ProcessingPurpose.AUDIT.value == "audit"
        assert ProcessingPurpose.SECURITY.value == "security"


class TestDataCategory:
    def test_members(self):
        assert DataCategory.PERSONAL_IDENTIFIABLE.value == "personal_identifiable"
        assert DataCategory.SENSITIVE.value == "sensitive"
        assert DataCategory.FINANCIAL.value == "financial"
        assert DataCategory.EMPLOYMENT.value == "employment"
        assert DataCategory.BIOMETRIC.value == "biometric"
        assert DataCategory.CHILDREN.value == "children"


# =============================================================================
# Exception Tests
# =============================================================================

class TestGDPRComplianceError:
    def test_exception(self):
        with pytest.raises(GDPRComplianceError):
            raise GDPRComplianceError("Test")


class TestConsentNotFoundError:
    def test_exception(self):
        with pytest.raises(ConsentNotFoundError):
            raise ConsentNotFoundError("Not found")


class TestInvalidRequestError:
    def test_exception(self):
        with pytest.raises(InvalidRequestError):
            raise InvalidRequestError("Invalid")


class TestDataBreachNotificationError:
    def test_exception(self):
        with pytest.raises(DataBreachNotificationError):
            raise DataBreachNotificationError("Notification failed")


# =============================================================================
# ErasureResult Tests
# =============================================================================

class TestErasureResult:
    def test_construction(self):
        result = ErasureResult(is_erased=True, anonymized_log_retained=False)
        assert result.is_erased is True
        assert result.anonymized_log_retained is False


# =============================================================================
# ConsentRecord Tests
# =============================================================================

class TestConsentRecord:
    def test_construction(self, user_id):
        now = datetime.now(UTC)
        expiry = now + timedelta(days=30)
        record = ConsentRecord(
            consent_id=uuid4(),
            user_id=user_id,
            purpose=ProcessingPurpose.MARKETING,
            status=ConsentStatus.GIVEN,
            given_at=now,
            expiry=expiry,
            withdrawal_reason=None,
            ip_address="127.0.0.1",
            user_agent="Mozilla/5.0",
        )
        assert record.user_id == user_id
        assert record.purpose == ProcessingPurpose.MARKETING
        assert record.status == ConsentStatus.GIVEN
        assert record.given_at == now
        assert record.expiry == expiry
        assert record.ip_address == "127.0.0.1"
        assert record.user_agent == "Mozilla/5.0"
        assert record.hash is not None

    def test_withdraw(self, consent_record):
        consent_record.withdraw(reason="User requested", withdrawn_at=None)
        assert consent_record.status == ConsentStatus.WITHDRAWN
        assert consent_record.withdrawal_reason == "User requested"
        # Hash should be recomputed
        old_hash = consent_record.hash
        consent_record.withdraw(reason="Another reason")
        assert consent_record.hash != old_hash

    def test_is_active(self, consent_record):
        assert consent_record.is_active() is True
        consent_record.status = ConsentStatus.WITHDRAWN
        assert consent_record.is_active() is False
        consent_record.status = ConsentStatus.GIVEN
        consent_record.expiry = datetime.now(UTC) - timedelta(days=1)
        assert consent_record.is_active() is False

    def test_is_active_with_reference_date(self, consent_record):
        past = datetime.now(UTC) - timedelta(days=10)
        future = datetime.now(UTC) + timedelta(days=10)
        assert consent_record.is_active(reference_date=past) is True
        consent_record.expiry = datetime.now(UTC) - timedelta(days=5)
        assert consent_record.is_active(reference_date=future) is False


# =============================================================================
# DataSubjectRequest Tests
# =============================================================================

class TestDataSubjectRequest:
    def test_construction(self, user_id):
        now = datetime.now(UTC)
        req = DataSubjectRequest(
            request_id=uuid4(),
            user_id=user_id,
            request_type=DataSubjectRequestType.ERASURE,
            request_date=now,
            details={"reason": "test"},
            status=RequestStatus.PENDING,
        )
        assert req.user_id == user_id
        assert req.request_type == DataSubjectRequestType.ERASURE
        assert req.request_date == now
        assert req.details == {"reason": "test"}
        assert req.status == RequestStatus.PENDING
        assert req.hash is not None

    def test_fulfill(self, data_subject_request):
        response_data = {"status": "completed"}
        data_subject_request.fulfill(response_data, fulfilled_by=uuid4())
        assert data_subject_request.status == RequestStatus.FULFILLED
        assert data_subject_request.fulfilled_date is not None
        assert data_subject_request.response_data == response_data
        assert data_subject_request.hash is not None

    def test_reject(self, data_subject_request):
        data_subject_request.reject(reason="Insufficient data")
        assert data_subject_request.status == RequestStatus.REJECTED
        assert data_subject_request.rejection_reason == "Insufficient data"
        assert data_subject_request.hash is not None


# =============================================================================
# DataBreach Tests
# =============================================================================

class TestDataBreach:
    def test_construction(self):
        now = datetime.now(UTC)
        discovered_by = uuid4()
        breach = DataBreach(
            breach_id=uuid4(),
            description="Test data breach",
            affected_data_categories=[DataCategory.SENSITIVE],
            affected_users_count=100,
            discovered_date=now,
            discovered_by=discovered_by,
            root_cause="Misconfiguration",
            containment_measures="Isolated systems",
        )
        assert breach.description == "Test data breach"
        assert breach.affected_categories == [DataCategory.SENSITIVE]
        assert breach.affected_users_count == 100
        assert breach.discovered_date == now
        assert breach.discovered_by == discovered_by
        assert breach.root_cause == "Misconfiguration"
        assert breach.containment_measures == "Isolated systems"
        assert breach.notified_supervisory is False
        assert breach.resolved is False

    def test_notify_supervisory_authority(self, data_breach):
        now = datetime.now(UTC)
        data_breach.notify_supervisory_authority(now)
        assert data_breach.notified_supervisory is True
        assert data_breach.notification_date == now

    def test_notify_affected_users(self, data_breach):
        data_breach.notify_affected_users()
        assert data_breach.notified_affected_users is True

    def test_resolve(self, data_breach):
        now = datetime.now(UTC)
        data_breach.resolve(now)
        assert data_breach.resolved is True
        assert data_breach.resolution_date == now


# =============================================================================
# ProcessingActivity Tests
# =============================================================================

class TestProcessingActivity:
    def test_construction(self, processing_activity):
        assert processing_activity.name == "Test Processing"
        assert processing_activity.controller == "Test Controller"
        assert ProcessingPurpose.ACCOUNTING in processing_activity.purposes
        assert DataCategory.PERSONAL_IDENTIFIABLE in processing_activity.data_categories
        assert processing_activity.retention_period_days == 365
        assert "Recipient A" in processing_activity.recipients
        assert "US" in processing_activity.transfers
        assert "Encryption" in processing_activity.safeguards
        assert processing_activity.last_review_date is None


# =============================================================================
# PrivacyRequest / PrivacyReport / FulfillmentResponse Tests
# =============================================================================

class TestPrivacyRequest:
    def test_construction(self):
        req = PrivacyRequest(user_id="user123", request_type="ACCESS")
        assert req.user_id == "user123"
        assert req.request_type == "ACCESS"


class TestPrivacyReport:
    def test_construction(self):
        data = {"user": "test"}
        report = PrivacyReport(data_export=data)
        assert report.data_export == data


class TestFulfillmentResponse:
    def test_construction(self):
        resp = FulfillmentResponse(days_taken=5)
        assert resp.days_taken == 5


# =============================================================================
# GDPRChecker Tests
# =============================================================================

class TestGDPRChecker:
    # -------------------- Consent Management --------------------
    def test_give_consent(self, checker, user_id):
        consent_id = checker.give_consent(
            user_id=user_id,
            purpose=ProcessingPurpose.MARKETING,
            expiry_days=30,
            ip_address="192.168.1.1",
            user_agent="test-agent",
        )
        assert isinstance(consent_id, UUID)
        # Check consent was stored
        consents = checker.get_all_consents(user_id)
        assert len(consents) == 1
        assert consents[0].purpose == ProcessingPurpose.MARKETING
        assert consents[0].status == ConsentStatus.GIVEN
        assert consents[0].ip_address == "192.168.1.1"

    def test_give_consent_with_string_user_id(self, checker):
        user_id_str = "12345678-1234-1234-1234-123456789abc"
        consent_id = checker.give_consent(
            user_id=user_id_str,
            purpose=ProcessingPurpose.ACCOUNTING,
        )
        assert isinstance(consent_id, UUID)
        # The checker will convert string to UUID using UUID() if possible

    def test_give_consent_with_purpose_string(self, checker, user_id):
        consent_id = checker.give_consent(
            user_id=user_id,
            purpose="accounting",
        )
        assert isinstance(consent_id, UUID)
        consents = checker.get_all_consents(user_id)
        assert consents[0].purpose == ProcessingPurpose.ACCOUNTING

    def test_withdraw_consent(self, checker, user_id):
        checker.give_consent(user_id, ProcessingPurpose.MARKETING)
        result = checker.withdraw_consent(
            user_id=user_id,
            purpose=ProcessingPurpose.MARKETING,
            reason="No longer needed",
        )
        assert result is True
        consents = checker.get_all_consents(user_id)
        assert consents[0].status == ConsentStatus.WITHDRAWN
        assert consents[0].withdrawal_reason == "No longer needed"

    def test_withdraw_consent_without_purpose(self, checker, user_id):
        checker.give_consent(user_id, ProcessingPurpose.MARKETING)
        checker.give_consent(user_id, ProcessingPurpose.ACCOUNTING)
        result = checker.withdraw_consent(user_id=user_id, reason="All withdrawn")
        assert result is True
        consents = checker.get_all_consents(user_id)
        assert all(c.status == ConsentStatus.WITHDRAWN for c in consents)

    def test_withdraw_consent_with_string_user_id(self, checker):
        user_id_str = "12345678-1234-1234-1234-123456789abc"
        # First give consent
        checker.give_consent(user_id_str, ProcessingPurpose.MARKETING)
        result = checker.withdraw_consent(user_id=user_id_str, reason="test")
        assert result is True

    def test_has_consent(self, checker, user_id):
        # No consent yet
        assert checker.has_consent(user_id, ProcessingPurpose.MARKETING) is False
        # Give consent
        checker.give_consent(user_id, ProcessingPurpose.MARKETING)
        assert checker.has_consent(user_id, ProcessingPurpose.MARKETING) is True
        # Check different purpose
        assert checker.has_consent(user_id, ProcessingPurpose.ACCOUNTING) is False

    def test_has_consent_without_purpose(self, checker, user_id):
        checker.give_consent(user_id, ProcessingPurpose.MARKETING)
        assert checker.has_consent(user_id) is True

    def test_has_consent_expired(self, checker, user_id):
        checker.give_consent(user_id, ProcessingPurpose.MARKETING, expiry_days=-1)
        assert checker.has_consent(user_id, ProcessingPurpose.MARKETING) is False

    def test_has_consent_withdrawn(self, checker, user_id):
        checker.give_consent(user_id, ProcessingPurpose.MARKETING)
        checker.withdraw_consent(user_id, ProcessingPurpose.MARKETING)
        assert checker.has_consent(user_id, ProcessingPurpose.MARKETING) is False

    def test_has_consent_implicit_for_legal_compliance(self, checker, user_id):
        # Even without explicit consent, legal compliance purposes may be allowed
        assert checker.has_consent(
            user_id, ProcessingPurpose.LEGAL_COMPLIANCE, require_explicit=False
        ) is True
        assert checker.has_consent(
            user_id, ProcessingPurpose.AUDIT, require_explicit=False
        ) is True
        # But not for marketing
        assert checker.has_consent(
            user_id, ProcessingPurpose.MARKETING, require_explicit=False
        ) is False

    def test_get_all_consents(self, checker, user_id):
        checker.give_consent(user_id, ProcessingPurpose.MARKETING)
        checker.give_consent(user_id, ProcessingPurpose.ACCOUNTING)
        consents = checker.get_all_consents(user_id)
        assert len(consents) == 2
        purposes = {c.purpose for c in consents}
        assert ProcessingPurpose.MARKETING in purposes
        assert ProcessingPurpose.ACCOUNTING in purposes

    def test_get_active_consents(self, checker, user_id):
        checker.give_consent(user_id, ProcessingPurpose.MARKETING)
        checker.give_consent(user_id, ProcessingPurpose.ACCOUNTING)
        # Withdraw one
        checker.withdraw_consent(user_id, ProcessingPurpose.MARKETING)
        active = checker.get_active_consents(user_id)
        assert len(active) == 1
        assert active[0].purpose == ProcessingPurpose.ACCOUNTING

    # -------------------- Data Subject Requests --------------------
    def test_submit_request(self, checker, user_id):
        request_id = checker.submit_request(
            user_id=user_id,
            request_type=DataSubjectRequestType.ACCESS,
            details={"format": "json"},
        )
        assert isinstance(request_id, UUID)
        request = checker.get_request(request_id)
        assert request is not None
        assert request.user_id == user_id
        assert request.request_type == DataSubjectRequestType.ACCESS
        assert request.status == RequestStatus.PENDING

    def test_get_pending_requests(self, checker, user_id):
        checker.submit_request(user_id, DataSubjectRequestType.ACCESS)
        checker.submit_request(user_id, DataSubjectRequestType.ERASURE)
        pending = checker.get_pending_requests()
        assert len(pending) == 2

    def test_get_request_not_found(self, checker):
        assert checker.get_request(uuid4()) is None

    def test_fulfill_request(self, checker, user_id):
        request_id = checker.submit_request(user_id, DataSubjectRequestType.ACCESS)
        result = checker.fulfill_request(request_id, response_data={"data": "test"})
        assert result is True
        request = checker.get_request(request_id)
        assert request.status == RequestStatus.FULFILLED
        assert request.response_data == {"data": "test"}

    def test_fulfill_request_with_privacy_request(self, checker):
        # This tests the code path where request_id_or_request is a PrivacyRequest
        privacy_req = PrivacyRequest(user_id="user123", request_type="ACCESS")
        result = checker.fulfill_request(privacy_req)
        assert isinstance(result, FulfillmentResponse)
        assert result.days_taken == 5

    def test_fulfill_request_already_fulfilled_raises(self, checker, user_id):
        request_id = checker.submit_request(user_id, DataSubjectRequestType.ACCESS)
        checker.fulfill_request(request_id, response_data={"data": "test"})
        with pytest.raises(InvalidRequestError, match="already fulfilled"):
            checker.fulfill_request(request_id, response_data={"data": "more"})

    def test_fulfill_request_not_found_returns_false(self, checker):
        result = checker.fulfill_request(uuid4())
        assert result is False

    def test_reject_request(self, checker, user_id):
        request_id = checker.submit_request(user_id, DataSubjectRequestType.ACCESS)
        result = checker.reject_request(request_id, reason="No valid ID")
        assert result is True
        request = checker.get_request(request_id)
        assert request.status == RequestStatus.REJECTED
        assert request.rejection_reason == "No valid ID"

    def test_reject_request_not_found(self, checker):
        result = checker.reject_request(uuid4(), "reason")
        assert result is False

    def test_handle_request(self, checker):
        privacy_req = PrivacyRequest(user_id="user123", request_type="ACCESS")
        report = checker.handle_request(privacy_req)
        assert isinstance(report, PrivacyReport)
        assert report.data_export["user_id"] == "user123"
        assert "email" in report.data_export
        assert "consent_history" in report.data_export

    # -------------------- Right to Access --------------------
    def test_export_user_data(self, checker, user_id):
        checker.give_consent(user_id, ProcessingPurpose.MARKETING)
        data = checker.export_user_data(user_id, format="json")
        assert data["user_id"] == str(user_id)
        assert "export_date" in data
        assert "data_sources" in data
        assert "profile" in data["data_sources"]
        assert "consents" in data["data_sources"]
        assert len(data["data_sources"]["consents"]) == 1

    # -------------------- Right to Erasure --------------------
    def test_request_erasure(self, checker, user_id):
        checker.give_consent(user_id, ProcessingPurpose.MARKETING)
        result = checker.request_erasure(user_id, reason="User request")
        assert isinstance(result, ErasureResult)
        assert result.is_erased is True
        assert result.anonymized_log_retained is True
        # Data should be erased
        assert checker.is_data_erased(str(user_id)) is True
        assert checker.has_anonymized_audit_log(str(user_id)) is True

    def test_request_erasure_with_string_user_id(self, checker):
        user_id_str = "12345678-1234-1234-1234-123456789abc"
        result = checker.request_erasure(user_id_str)
        assert result.is_erased is True
        assert checker.is_data_erased(user_id_str) is True

    def test_request_erasure_raises_on_legal_hold(self, checker, user_id):
        with pytest.raises(PermissionError, match="Tax retention period still active"):
            checker.request_erasure(user_id, ignore_legal_hold=False, force=False)

    def test_request_erasure_with_force(self, checker, user_id):
        result = checker.request_erasure(user_id, force=True)
        assert result.is_erased is True

    def test_is_data_erased(self, checker, user_id):
        assert checker.is_data_erased(str(user_id)) is False
        checker.request_erasure(user_id)
        assert checker.is_data_erased(str(user_id)) is True

    def test_has_anonymized_audit_log(self, checker, user_id):
        assert checker.has_anonymized_audit_log(str(user_id)) is False
        checker.request_erasure(user_id)
        assert checker.has_anonymized_audit_log(str(user_id)) is True

    # -------------------- Right to Data Portability --------------------
    def test_export_portable_data_json(self, checker, user_id):
        checker.give_consent(user_id, ProcessingPurpose.MARKETING)
        result = checker.export_portable_data(user_id, format="json")
        assert result is not None
        assert result.mime_type == "application/json"
        assert "profile" in result.data
        assert "transaction_history" in result.data
        assert "consent_history" in result.data

    def test_export_portable_data_csv(self, checker, user_id):
        result = checker.export_portable_data(user_id, format="csv")
        assert isinstance(result, str)
        assert "user_id" in result

    def test_export_portable_data_invalid_format(self, checker, user_id):
        with pytest.raises(InvalidRequestError, match="Unsupported format"):
            checker.export_portable_data(user_id, format="xml")

    def test_export_portable_data_with_string_user_id(self, checker):
        user_id_str = "user123"
        result = checker.export_portable_data(user_id_str, format="json")
        assert result is not None

    # -------------------- Right to Rectification --------------------
    def test_rectify_data(self, checker, user_id):
        result = checker.rectify_data(
            user_id=user_id,
            field="name",
            new_value="New Name",
            request_id=uuid4(),
        )
        assert result is True

    # -------------------- Data Breach Management --------------------
    def test_report_data_breach(self, checker):
        breach_id = checker.report_data_breach(
            description="Test breach",
            affected_categories=[DataCategory.PERSONAL_IDENTIFIABLE],
            affected_users_count=10,
            discovered_by=uuid4(),
            root_cause="Test",
        )
        assert isinstance(breach_id, UUID)
        breaches = checker.get_breaches()
        assert len(breaches) == 1
        assert breaches[0].id == breach_id

    def test_report_data_breach_triggers_notification_supervisory(self, checker):
        # High risk > 1000 users should notify
        checker.report_data_breach(
            description="Large breach",
            affected_categories=[DataCategory.PERSONAL_IDENTIFIABLE, DataCategory.SENSITIVE],
            affected_users_count=2000,
            discovered_by=uuid4(),
        )
        breaches = checker.get_breaches()
        breach = breaches[0]
        assert breach.notified_supervisory is True
        assert breach.notified_affected_users is True  # high risk due to sensitive data

    def test_report_data_breach_no_notification_low_risk(self, checker):
        checker.report_data_breach(
            description="Small breach",
            affected_categories=[DataCategory.PERSONAL_IDENTIFIABLE],
            affected_users_count=5,
            discovered_by=uuid4(),
        )
        breaches = checker.get_breaches()
        breach = breaches[0]
        assert breach.notified_supervisory is False
        assert breach.notified_affected_users is False

    def test_get_breaches(self, checker, data_breach):
        checker._breaches.append(data_breach)
        all_breaches = checker.get_breaches(unresolved_only=False)
        assert len(all_breaches) == 1
        # Resolve the breach and check unresolved_only
        data_breach.resolve(datetime.now(UTC))
        unresolved = checker.get_breaches(unresolved_only=True)
        assert len(unresolved) == 0

    def test_resolve_breach(self, checker, data_breach):
        checker._breaches.append(data_breach)
        result = checker.resolve_breach(data_breach.id, "Applied fix")
        assert result is True
        assert data_breach.containment_measures == "Applied fix"
        assert data_breach.resolved is True
        assert data_breach.resolution_date is not None

    def test_resolve_breach_not_found(self, checker):
        result = checker.resolve_breach(uuid4(), "fix")
        assert result is False

    def test_resolve_breach_already_resolved(self, checker, data_breach):
        data_breach.resolve(datetime.now(UTC))
        checker._breaches.append(data_breach)
        result = checker.resolve_breach(data_breach.id, "fix")
        assert result is False

    # -------------------- DPIA --------------------
    def test_create_dpia(self, checker):
        dpia = checker.create_dpia(
            processing_name="Test Processing",
            description="Test DPIA",
            data_categories=[DataCategory.SENSITIVE],
            risk_level="high",
            mitigation_measures=["Encryption", "Access Control"],
            controller="Test Controller",
        )
        assert dpia["processing_name"] == "Test Processing"
        assert dpia["risk_level"] == "high"
        assert dpia["status"] == "draft"
        assert len(checker._dpia_records) == 1

    def test_approve_dpia(self, checker):
        dpia = checker.create_dpia(
            processing_name="Test",
            description="Test",
            data_categories=[DataCategory.PERSONAL_IDENTIFIABLE],
            risk_level="medium",
            mitigation_measures=["Training"],
            controller="Controller",
        )
        dpia_id = dpia["dpia_id"]
        checker.approve_dpia(dpia_id, approver="DPO")
        updated = checker._dpia_records[0]
        assert updated["status"] == "approved"
        assert updated["approved_by"] == "DPO"
        assert updated["approved_at"] is not None

    # -------------------- Record of Processing Activities --------------------
    def test_add_and_get_processing_activities(self, checker, processing_activity):
        checker.add_processing_activity(processing_activity)
        activities = checker.get_processing_activities()
        assert len(activities) == 1
        assert activities[0].name == processing_activity.name

    def test_generate_art30_record(self, checker, processing_activity):
        checker.add_processing_activity(processing_activity)
        record = checker.generate_art30_record()
        assert record["controller_name"] == "ERP Accounting Engine Ltd."
        assert record["dpo_contact"] == checker._dpo_email
        assert len(record["activities"]) == 1
        assert record["activities"][0]["name"] == processing_activity.name

    # -------------------- Pseudonymization --------------------
    def test_pseudonymize_depseudonymize(self, checker):
        original = "sensitive-data-123"
        pseudonymized = checker.pseudonymize(original)
        assert pseudonymized != original
        depseudonymized = checker.depseudonymize(pseudonymized)
        assert depseudonymized == original

    def test_pseudonymize_without_crypto(self, monkeypatch):
        # Simulate cryptography not available
        import compliance.gdpr_privacy_checker as gdpr_module
        monkeypatch.setattr(gdpr_module, "HAS_CRYPTO", False)
        checker = GDPRChecker()
        original = "test"
        result = checker.pseudonymize(original)
        assert result == original  # Should return original without crypto

    # -------------------- DPO & Supervisory Authority --------------------
    def test_contact_dpo(self, checker):
        result = checker.contact_dpo(
            subject="Privacy concern",
            message="Please review my data",
            user_id=uuid4(),
        )
        assert result is True

    def test_notify_supervisory_authority(self, checker, data_breach):
        checker._breaches.append(data_breach)
        result = checker.notify_supervisory_authority(data_breach.id)
        assert result is True
        assert data_breach.notified_supervisory is True
        assert data_breach.notification_date is not None

    def test_notify_supervisory_authority_not_found(self, checker):
        result = checker.notify_supervisory_authority(uuid4())
        assert result is False

    # -------------------- Compliance Dashboard --------------------
    def test_get_compliance_status(self, checker, user_id):
        checker.give_consent(user_id, ProcessingPurpose.MARKETING)
        checker.submit_request(user_id, DataSubjectRequestType.ACCESS)
        status = checker.get_compliance_status()
        assert status["consents"]["total"] >= 1
        assert status["data_subject_requests"]["pending"] >= 1
        assert status["processing_activities"] == 0

    # -------------------- Helpers --------------------
    def test_create_access_request(self, checker, user_id):
        request = checker.create_access_request(user_id)
        assert request.user_id == user_id
        assert request.request_type == "ACCESS"
        assert request.request_date is not None

    def test_process_request(self, checker):
        req = SimpleNamespace()
        req.user_id = "user123"
        report = checker.process_request(req)
        assert report.data_export["user_id"] == "user123"
        assert report.completion_date is not None

    # -------------------- Edge Cases --------------------
    def test_give_consent_with_invalid_user_id_type(self, checker):
        # Passing a non-UUID, non-string should still work
        consent_id = checker.give_consent(user_id=12345, purpose=ProcessingPurpose.ACCOUNTING)
        assert isinstance(consent_id, UUID)

    def test_has_consent_with_invalid_user_id(self, checker):
        result = checker.has_consent(user_id="invalid-uuid-format")
        assert result is False

    def test_request_erasure_with_invalid_user_id(self, checker):
        result = checker.request_erasure(user_id="invalid")
        assert result.is_erased is True  # It still processes

    def test_is_data_erased_with_invalid_user_id(self, checker):
        result = checker.is_data_erased("invalid")
        assert result is False

    def test_has_anonymized_audit_log_with_invalid_user_id(self, checker):
        result = checker.has_anonymized_audit_log("invalid")
        assert result is False
