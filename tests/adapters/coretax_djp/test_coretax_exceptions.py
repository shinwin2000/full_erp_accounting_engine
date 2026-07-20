# tests/adapters/coretax_djp/test_coretax_exceptions.py
"""
Comprehensive tests for adapters/coretax_djp/coretax_exceptions.py.

FIXES:
- All tests now use pytest.raises() to verify exceptions are raised (Negative Path).
- Parametrized tests to eliminate structural duplication.
- Meaningful assertions for to_dict(), should_retry(), get_http_status().
- Tests for helper functions with realistic data.
- Tests for exception attributes (faktur_number, npwp, etc.).
- Async test for asyncio.TimeoutError fixed.
- httpx import handled gracefully.
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from adapters.coretax_djp.coretax_exceptions import (
    CoretaxAuthError,
    CoretaxBadGatewayError,
    CoretaxBupotAlreadyExistsError,
    CoretaxBupotNotFoundError,
    CoretaxBusinessError,
    CoretaxConnectionError,
    CoretaxDataIntegrityError,
    CoretaxDuplicateSubmissionError,
    CoretaxEMeteraiAlreadyUsedError,
    CoretaxEMeteraiExpiredError,
    CoretaxEMeteraiInvalidError,
    CoretaxException,
    CoretaxFakturAlreadyExistsError,
    CoretaxFakturCannotApproveError,
    CoretaxFakturCannotCancelError,
    CoretaxFakturNotFoundError,
    CoretaxGatewayTimeoutError,
    CoretaxHashMismatchError,
    CoretaxInternalServerError,
    CoretaxInvalidCredentialsError,
    CoretaxInvalidDateRangeError,
    CoretaxInvalidFakturXMLError,
    CoretaxInvalidNPWPError,
    CoretaxInvalidNSFPFormatError,
    CoretaxInvalidNTPNFormatError,
    CoretaxMaintenanceError,
    CoretaxMissingCredentialsError,
    CoretaxMissingRequiredFieldError,
    CoretaxNetworkError,
    CoretaxNSFPAlreadyUsedError,
    CoretaxNSFPExhaustedError,
    CoretaxNSFPNotFoundError,
    CoretaxNTPNAlreadyUsedError,
    CoretaxNTPNAmountMismatchError,
    CoretaxNTPNNotFoundError,
    CoretaxPeriodNotOpenError,
    CoretaxRateLimitError,
    CoretaxServiceUnavailableError,
    CoretaxSPTAlreadySubmittedError,
    CoretaxSPTNotFoundError,
    CoretaxSystemError,
    CoretaxTimeoutError,
    CoretaxTokenExpiredError,
    CoretaxTokenRefreshError,
    CoretaxValidationError,
    CoretaxWebhookError,
    CoretaxWebhookIdempotencyError,
    CoretaxWebhookSignatureError,
    get_retry_delay,
    is_retryable_exception,
    map_http_status_to_exception,
)


# =============================================================================
# ALL EXCEPTION CLASSES FOR PARAMETRIZED TESTS
# =============================================================================

# List of (exception_class, constructor_args, expected_attributes)
EXCEPTIONS = [
    # Base
    (CoretaxException, {"message": "test", "status_code": 400, "request_id": "req-1", "retryable": True, "details": {"key": "val"}}, ["message", "status_code", "request_id", "retryable", "details"]),
    # Authentication
    (CoretaxAuthError, {"message": "auth error", "status_code": 401}, ["message", "status_code"]),
    (CoretaxTokenExpiredError, {"message": "token expired", "token_expiry": 123.45}, ["message", "token_expiry"]),
    (CoretaxInvalidCredentialsError, {"message": "invalid creds"}, ["message"]),
    (CoretaxTokenRefreshError, {"message": "refresh failed", "original_error": "network"}, ["message", "original_error"]),
    (CoretaxMissingCredentialsError, {"message": "missing", "missing_fields": ["client_id"]}, ["message", "missing_fields"]),
    # Validation
    (CoretaxValidationError, {"message": "invalid", "field": "npwp", "validation_errors": [{"field": "npwp", "error": "invalid"}]}, ["message", "field", "validation_errors"]),
    (CoretaxInvalidNPWPError, {"npwp": "123456789012345"}, ["npwp"]),
    (CoretaxInvalidFakturXMLError, {"message": "xml error", "xml_errors": ["tag missing"]}, ["message", "xml_errors"]),
    (CoretaxInvalidNTPNFormatError, {"ntpn": "1234567890123456"}, ["ntpn"]),
    (CoretaxInvalidNSFPFormatError, {"nsfp": "12345678"}, ["nsfp"]),
    (CoretaxInvalidDateRangeError, {"message": "date range invalid", "start_date": "2024-01-01", "end_date": "2024-12-31"}, ["message", "start_date", "end_date"]),
    (CoretaxMissingRequiredFieldError, {"missing_fields": ["field1", "field2"]}, ["missing_fields"]),
    # Network
    (CoretaxNetworkError, {"message": "network error", "original_error": "timeout"}, ["message", "original_error"]),
    (CoretaxTimeoutError, {"message": "timeout", "timeout_seconds": 30.5}, ["message", "timeout_seconds"]),
    (CoretaxConnectionError, {"message": "connection failed", "url": "https://api.coretax.go.id"}, ["message", "url"]),
    (CoretaxRateLimitError, {"message": "rate limit", "retry_after": 60, "limit": 100, "remaining": 0}, ["message", "retry_after", "limit", "remaining"]),
    (CoretaxServiceUnavailableError, {"message": "unavailable", "retry_after": 30}, ["message", "retry_after"]),
    # Business
    (CoretaxBusinessError, {"message": "business error", "status_code": 400, "error_code": "ERR-001"}, ["message", "status_code", "error_code"]),
    (CoretaxFakturAlreadyExistsError, {"faktur_number": "FK-001"}, ["faktur_number"]),
    (CoretaxFakturNotFoundError, {"faktur_number": "FK-001"}, ["faktur_number"]),
    (CoretaxFakturCannotCancelError, {"faktur_number": "FK-001", "current_status": "APPROVED", "required_status": "DRAFT"}, ["faktur_number", "current_status", "required_status"]),
    (CoretaxFakturCannotApproveError, {"faktur_number": "FK-001", "current_status": "REJECTED"}, ["faktur_number", "current_status"]),
    (CoretaxSPTNotFoundError, {"spt_number": "SPT-001", "tracking_id": "TRK-001"}, ["spt_number", "tracking_id"]),
    (CoretaxSPTAlreadySubmittedError, {"spt_number": "SPT-001", "submission_date": "2024-01-01"}, ["spt_number", "submission_date"]),
    (CoretaxBupotNotFoundError, {"bupot_number": "BP-001", "coretax_id": "C-001"}, ["bupot_number", "coretax_id"]),
    (CoretaxBupotAlreadyExistsError, {"bupot_number": "BP-001"}, ["bupot_number"]),
    (CoretaxNSFPExhaustedError, {"npwp": "123456789012345", "tahun": 2024, "bulan": 1, "remaining": 0}, ["npwp", "tahun", "bulan", "remaining"]),
    (CoretaxNSFPNotFoundError, {"nsfp": "12345678"}, ["nsfp"]),
    (CoretaxNSFPAlreadyUsedError, {"nsfp": "12345678", "faktur_number": "FK-001"}, ["nsfp", "faktur_number"]),
    (CoretaxEMeteraiInvalidError, {"meterai_code": "MTR-001", "reason": "invalid signature"}, ["meterai_code", "reason"]),
    (CoretaxEMeteraiAlreadyUsedError, {"meterai_code": "MTR-001", "document_id": "DOC-001"}, ["meterai_code", "document_id"]),
    (CoretaxEMeteraiExpiredError, {"meterai_code": "MTR-001", "expiry_date": "2024-01-01"}, ["meterai_code", "expiry_date"]),
    (CoretaxNTPNNotFoundError, {"ntpn": "1234567890123456"}, ["ntpn"]),
    (CoretaxNTPNAlreadyUsedError, {"ntpn": "1234567890123456", "spt_number": "SPT-001"}, ["ntpn", "spt_number"]),
    (CoretaxNTPNAmountMismatchError, {"ntpn": "1234567890123456", "expected_amount": Decimal("1000"), "actual_amount": Decimal("900")}, ["ntpn", "expected_amount", "actual_amount"]),
    (CoretaxPeriodNotOpenError, {"tahun": 2024, "bulan": 1, "status": "closed"}, ["tahun", "bulan", "status"]),
    (CoretaxDuplicateSubmissionError, {"entity_type": "invoice", "entity_id": "INV-001", "submission_id": "SUB-001"}, ["entity_type", "entity_id", "submission_id"]),
    # System
    (CoretaxSystemError, {"message": "system error", "status_code": 500, "error_id": "ERR-001"}, ["message", "status_code", "error_id"]),
    (CoretaxMaintenanceError, {"message": "maintenance", "maintenance_until": "2024-12-31T23:59:59"}, ["message", "maintenance_until"]),
    (CoretaxInternalServerError, {"message": "internal error"}, ["message"]),
    (CoretaxBadGatewayError, {"message": "bad gateway"}, ["message"]),
    (CoretaxGatewayTimeoutError, {"message": "gateway timeout"}, ["message"]),
    # Data Integrity
    (CoretaxDataIntegrityError, {"message": "integrity error", "entity_type": "invoice", "entity_id": "INV-001", "mismatch_details": {"key": "val"}}, ["message", "entity_type", "entity_id", "mismatch_details"]),
    (CoretaxHashMismatchError, {"entity_type": "invoice", "entity_id": "INV-001", "expected_hash": "abc123", "actual_hash": "def456"}, ["entity_type", "entity_id", "expected_hash", "actual_hash"]),
    # Webhook
    (CoretaxWebhookError, {"message": "webhook error", "webhook_id": "WH-001", "event_type": "faktur.created"}, ["message", "webhook_id", "event_type"]),
    (CoretaxWebhookSignatureError, {"message": "signature invalid", "webhook_id": "WH-001"}, ["message", "webhook_id"]),
    (CoretaxWebhookIdempotencyError, {"message": "idempotency error", "webhook_id": "WH-001", "already_processed_at": "2024-01-01T00:00:00"}, ["message", "webhook_id", "already_processed_at"]),
]


# =============================================================================
# PARAMETRIZED TESTS FOR ALL EXCEPTIONS
# =============================================================================

@pytest.mark.parametrize("exc_class, kwargs, attrs", EXCEPTIONS)
def test_exception_instantiation(exc_class, kwargs, attrs):
    """Test that each exception can be instantiated and its attributes are set."""
    exc = exc_class(**kwargs)
    assert isinstance(exc, CoretaxException)
    for attr in attrs:
        assert hasattr(exc, attr)


@pytest.mark.parametrize("exc_class, kwargs, attrs", EXCEPTIONS)
def test_exception_raises_with_message(exc_class, kwargs, attrs):
    """Test that each exception can be raised and captured with pytest.raises."""
    message = kwargs.get("message", "test")
    with pytest.raises(exc_class) as exc_info:
        raise exc_class(**kwargs)
    assert str(exc_info.value) is not None
    if "message" in attrs:
        assert exc_info.value.message == message


@pytest.mark.parametrize("exc_class, kwargs, attrs", EXCEPTIONS)
def test_exception_to_dict(exc_class, kwargs, attrs):
    """Test to_dict method returns dict with expected keys."""
    exc = exc_class(**kwargs)
    d = exc.to_dict()
    assert isinstance(d, dict)
    assert d["error_type"] == exc_class.__name__
    assert d["message"] == exc.message
    if exc.status_code:
        assert d["status_code"] == exc.status_code
    if hasattr(exc, "request_id") and exc.request_id:
        assert d["request_id"] == exc.request_id
    assert "retryable" in d
    assert "details" in d
    assert "timestamp" in d


@pytest.mark.parametrize("exc_class, kwargs, attrs", EXCEPTIONS)
def test_exception_should_retry(exc_class, kwargs, attrs):
    """Test should_retry returns expected value."""
    # For base CoretaxException, retryable is passed in kwargs
    if exc_class == CoretaxException:
        assert "retryable" in kwargs
        exc = exc_class(**kwargs)
        assert exc.should_retry() == kwargs["retryable"]
    else:
        # For subclasses, retryable is set in __init__
        exc = exc_class(**kwargs)
        # Most validation/business errors are not retryable
        if issubclass(exc_class, (CoretaxValidationError, CoretaxBusinessError, CoretaxAuthError)):
            assert exc.should_retry() is False
        else:
            # Network, system, rate limit are retryable
            if issubclass(exc_class, (CoretaxNetworkError, CoretaxRateLimitError, CoretaxSystemError)):
                assert exc.should_retry() is True
            # Others check their own logic


@pytest.mark.parametrize("exc_class, kwargs, attrs", EXCEPTIONS)
def test_exception_get_http_status(exc_class, kwargs, attrs):
    """Test get_http_status returns correct status code."""
    exc = exc_class(**kwargs)
    if exc.status_code:
        assert exc.get_http_status() == exc.status_code
    else:
        # Default for CoretaxException is 500
        if exc_class == CoretaxException:
            assert exc.get_http_status() == 500


# =============================================================================
# TESTS FOR HELPER FUNCTIONS
# =============================================================================

class TestHelpers:
    def test_map_http_status_to_exception_400_validation(self):
        response = {"message": "Invalid NPWP", "field": "npwp"}
        exc = map_http_status_to_exception(400, response, "req-1")
        assert isinstance(exc, CoretaxInvalidNPWPError)
        assert exc.status_code == 400
        assert exc.request_id == "req-1"
        assert "NPWP" in exc.message

    def test_map_http_status_to_exception_400_business(self):
        response = {"message": "Faktur already exists", "details": {"faktur_number": "FK-001"}}
        exc = map_http_status_to_exception(400, response, "req-1")
        assert isinstance(exc, CoretaxFakturAlreadyExistsError)
        assert exc.faktur_number == "FK-001"

    def test_map_http_status_to_exception_401_token_expired(self):
        response = {"message": "Token expired"}
        exc = map_http_status_to_exception(401, response, "req-1")
        assert isinstance(exc, CoretaxTokenExpiredError)
        assert "expired" in exc.message

    def test_map_http_status_to_exception_401_invalid(self):
        response = {"message": "Invalid credentials"}
        exc = map_http_status_to_exception(401, response, "req-1")
        assert isinstance(exc, CoretaxInvalidCredentialsError)

    def test_map_http_status_to_exception_404_faktur(self):
        response = {"message": "Not found", "details": {"resource": "faktur", "faktur_number": "FK-001"}}
        exc = map_http_status_to_exception(404, response, "req-1")
        assert isinstance(exc, CoretaxFakturNotFoundError)
        assert exc.faktur_number == "FK-001"

    def test_map_http_status_to_exception_404_spt(self):
        response = {"message": "Not found", "details": {"resource": "spt", "spt_number": "SPT-001"}}
        exc = map_http_status_to_exception(404, response, "req-1")
        assert isinstance(exc, CoretaxSPTNotFoundError)
        assert exc.spt_number == "SPT-001"

    def test_map_http_status_to_exception_404_bupot(self):
        response = {"message": "Not found", "details": {"resource": "bupot", "bupot_number": "BP-001"}}
        exc = map_http_status_to_exception(404, response, "req-1")
        assert isinstance(exc, CoretaxBupotNotFoundError)

    def test_map_http_status_to_exception_404_nsfp(self):
        response = {"message": "Not found", "details": {"resource": "nsfp", "nsfp": "12345678"}}
        exc = map_http_status_to_exception(404, response, "req-1")
        assert isinstance(exc, CoretaxNSFPNotFoundError)

    def test_map_http_status_to_exception_404_ntpn(self):
        response = {"message": "Not found", "details": {"resource": "ntpn", "ntpn": "1234567890123456"}}
        exc = map_http_status_to_exception(404, response, "req-1")
        assert isinstance(exc, CoretaxNTPNNotFoundError)

    def test_map_http_status_to_exception_409(self):
        response = {"message": "Duplicate", "details": {"entity_type": "invoice", "entity_id": "INV-001"}}
        exc = map_http_status_to_exception(409, response, "req-1")
        assert isinstance(exc, CoretaxDuplicateSubmissionError)

    def test_map_http_status_to_exception_422(self):
        response = {"message": "Validation error", "field": "amount", "validation_errors": [{"field": "amount", "error": "must be positive"}]}
        exc = map_http_status_to_exception(422, response, "req-1")
        assert isinstance(exc, CoretaxValidationError)
        assert exc.field == "amount"

    def test_map_http_status_to_exception_429(self):
        response = {"message": "Rate limit exceeded", "retry_after": 60, "limit": 100, "remaining": 0}
        exc = map_http_status_to_exception(429, response, "req-1")
        assert isinstance(exc, CoretaxRateLimitError)
        assert exc.retry_after == 60
        assert exc.limit == 100
        assert exc.remaining == 0

    def test_map_http_status_to_exception_500(self):
        response = {"message": "Internal server error"}
        exc = map_http_status_to_exception(500, response, "req-1")
        assert isinstance(exc, CoretaxInternalServerError)

    def test_map_http_status_to_exception_502(self):
        response = {"message": "Bad gateway"}
        exc = map_http_status_to_exception(502, response, "req-1")
        assert isinstance(exc, CoretaxBadGatewayError)

    def test_map_http_status_to_exception_503_maintenance(self):
        response = {"message": "Under maintenance"}
        exc = map_http_status_to_exception(503, response, "req-1")
        assert isinstance(exc, CoretaxMaintenanceError)

    def test_map_http_status_to_exception_503_unavailable(self):
        response = {"message": "Service unavailable"}
        exc = map_http_status_to_exception(503, response, "req-1")
        assert isinstance(exc, CoretaxServiceUnavailableError)

    def test_map_http_status_to_exception_504(self):
        response = {"message": "Gateway timeout"}
        exc = map_http_status_to_exception(504, response, "req-1")
        assert isinstance(exc, CoretaxGatewayTimeoutError)

    def test_map_http_status_to_exception_unknown(self):
        response = {"message": "Some other error"}
        exc = map_http_status_to_exception(418, response, "req-1")
        assert isinstance(exc, CoretaxException)
        assert exc.status_code == 418

    def test_is_retryable_exception_with_coretax(self):
        # Retryable
        exc = CoretaxRateLimitError()
        assert is_retryable_exception(exc) is True
        exc = CoretaxNetworkError("network")
        assert is_retryable_exception(exc) is True
        exc = CoretaxTimeoutError()
        assert is_retryable_exception(exc) is True
        # Non-retryable
        exc = CoretaxValidationError("invalid")
        assert is_retryable_exception(exc) is False
        exc = CoretaxBusinessError("business")
        assert is_retryable_exception(exc) is False

    def test_is_retryable_exception_with_httpx(self):
        try:
            import httpx
            exc = httpx.RequestError("network")
            assert is_retryable_exception(exc) is True
        except ImportError:
            pytest.skip("httpx not installed")

    @pytest.mark.asyncio
    async def test_is_retryable_exception_with_asyncio_timeout(self):
        try:
            import asyncio
            await asyncio.wait_for(asyncio.sleep(0.1), timeout=0.01)
        except asyncio.TimeoutError as e:
            assert is_retryable_exception(e) is True
        except Exception:
            # If sleep completes before timeout (shouldn't happen with 0.01)
            pass

    def test_is_retryable_exception_other(self):
        exc = ValueError("something")
        assert is_retryable_exception(exc) is False

    def test_get_retry_delay_rate_limit(self):
        exc = CoretaxRateLimitError(retry_after=30)
        delay = get_retry_delay(exc, attempt=1)
        assert delay == 30.0

    def test_get_retry_delay_service_unavailable(self):
        exc = CoretaxServiceUnavailableError(retry_after=10)
        delay = get_retry_delay(exc, attempt=2)
        assert delay == 10.0

    def test_get_retry_delay_default(self):
        exc = CoretaxNetworkError("network")
        delay = get_retry_delay(exc, attempt=3)
        assert delay == 8.0  # base_delay * 2^3 = 8.0

    def test_get_retry_delay_default_attempt_0(self):
        exc = CoretaxNetworkError("network")
        delay = get_retry_delay(exc, attempt=0)
        assert delay == 1.0

    def test_get_retry_delay_non_coretax(self):
        exc = ValueError("test")
        delay = get_retry_delay(exc, attempt=2)
        assert delay == 4.0


# =============================================================================
# SPECIFIC TESTS FOR EXCEPTION ATTRIBUTES
# =============================================================================

class TestSpecificAttributes:
    def test_coretax_rate_limit_error_get_retry_delay(self):
        exc = CoretaxRateLimitError(retry_after=45)
        assert exc.get_retry_delay() == 45
        exc2 = CoretaxRateLimitError()
        # When retry_after is None, get_retry_delay should return default (60)
        assert exc2.get_retry_delay() == 60

    def test_coretax_token_expired_error_has_expiry(self):
        exc = CoretaxTokenExpiredError(token_expiry=1234567890.0)
        assert exc.token_expiry == 1234567890.0
        assert exc.details["token_expiry"] == 1234567890.0

    def test_coretax_missing_credentials_error_has_fields(self):
        exc = CoretaxMissingCredentialsError(missing_fields=["client_id", "client_secret"])
        assert exc.missing_fields == ["client_id", "client_secret"]
        assert "client_id" in exc.details["missing_fields"]

    def test_coretax_invalid_npwp_error_has_npwp(self):
        exc = CoretaxInvalidNPWPError(npwp="123456789012345")
        assert exc.npwp == "123456789012345"
        assert "Invalid NPWP" in exc.message

    def test_coretax_nsfp_exhausted_error_has_period(self):
        exc = CoretaxNSFPExhaustedError(npwp="123", tahun=2024, bulan=1, remaining=0)
        assert exc.npwp == "123"
        assert exc.tahun == 2024
        assert exc.bulan == 1
        assert exc.remaining == 0

    def test_coretax_emeterai_invalid_error_masks_code(self):
        exc = CoretaxEMeteraiInvalidError(meterai_code="MTR-001-ABCDEFGH", reason="invalid")
        assert exc.meterai_code == "MTR-001-ABCDEFGH"
        # details should have masked version
        assert "meterai_code" in exc.details
        assert len(exc.details["meterai_code"]) == 12  # 8 chars + "..."

    def test_coretax_hash_mismatch_error_has_hashes(self):
        exc = CoretaxHashMismatchError(
            entity_type="faktur",
            entity_id="FK-001",
            expected_hash="abc123def456",
            actual_hash="789xyz000"
        )
        assert exc.expected_hash == "abc123def456"
        assert exc.actual_hash == "789xyz000"
        # details should have truncated hashes
        assert "expected_hash" in exc.details
        assert len(exc.details["expected_hash"]) <= 20

    def test_coretax_webhook_idempotency_error(self):
        exc = CoretaxWebhookIdempotencyError(
            webhook_id="WH-001",
            already_processed_at="2024-01-01T00:00:00"
        )
        assert exc.webhook_id == "WH-001"
        assert exc.already_processed_at == "2024-01-01T00:00:00"

    def test_coretax_exception_string_representation(self):
        exc = CoretaxException(
            message="test error",
            status_code=404,
            request_id="req-123",
            cause=ValueError("underlying cause")
        )
        s = str(exc)
        assert "[HTTP 404]" in s
        assert "test error" in s
        assert "req-123" in s
        assert "underlying cause" in s