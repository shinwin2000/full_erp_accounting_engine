# tests/infrastructure/security/test_security_exceptions.py
"""
Comprehensive tests for infrastructure/security/security_exceptions.py.

FIXES:
- All exceptions tested with parametrize to eliminate structural duplication.
- Negative path tests: verify each exception can be raised and attributes are set.
- Specific tests for exceptions with custom attributes.
- All tests use meaningful assertions.
"""

import pytest

from infrastructure.security.security_exceptions import (
    CARequestError,
    CertificateError,
    CertificateExpiredError,
    CertificateLoadError,
    CertificateNotFoundError,
    CertificateRenewalError,
    CSRGenerationError,
    DecryptionError,
    DigitalSignerError,
    ExpiredTokenError,
    FieldEncryptionError,
    HashingError,
    HashVerificationError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidTokenError,
    JWTError,
    JWTIssuerError,
    JWTRevocationError,
    JWTValidatorError,
    KeyNotFoundError,
    KeyRotationError,
    KeyRotationLockError,
    LeaseRenewalError,
    PermissionDeniedError,
    PrivateKeyNotFoundError,
    RBACError,
    ReEncryptionError,
    RevocationNotFoundError,
    RevokedTokenError,
    SecretNotFoundError,
    SecurityError,
    SigningError,
    SODConstraintError,
    SODViolationError,
    TokenGenerationError,
    UserNotFoundError,
    VaultError,
    VaultNotAvailableError,
    VerificationError,
)

# =============================================================================
# ALL EXCEPTION CLASSES FOR PARAMETRIZED TESTS
# =============================================================================

# List of (exception_class, default_args, expected_attributes)
EXCEPTIONS = [
    # Base
    (SecurityError, {"message": "test", "code": "ERR-001", "details": {"key": "val"}}, ["message", "code", "details"]),
    # JWT
    (JWTError, {}, []),
    (JWTIssuerError, {}, []),
    (PrivateKeyNotFoundError, {"message": "key missing"}, ["message"]),
    (TokenGenerationError, {"message": "gen failed"}, ["message"]),
    (JWTValidatorError, {}, []),
    (InvalidTokenError, {"message": "invalid"}, ["message"]),
    (ExpiredTokenError, {"message": "expired"}, ["message"]),
    (RevokedTokenError, {"message": "revoked"}, ["message"]),
    (InvalidIssuerError, {"expected": "issuer1", "actual": "issuer2"}, ["expected", "actual"]),
    (InvalidAudienceError, {"expected": "aud1", "actual": "aud2"}, ["expected", "actual"]),
    (JWTRevocationError, {}, []),
    (RevocationNotFoundError, {"jti": "jti-123"}, ["jti"]),
    # Encryption
    (FieldEncryptionError, {}, []),
    (DecryptionError, {"message": "decrypt failed"}, ["message"]),
    (KeyNotFoundError, {"key_id": "key-123"}, ["key_id"]),
    # Digital signing
    (DigitalSignerError, {}, []),
    (SigningError, {"message": "sign failed"}, ["message"]),
    (VerificationError, {"message": "verify failed"}, ["message"]),
    # Certificate
    (CertificateError, {}, []),
    (CertificateLoadError, {}, []),
    (CertificateNotFoundError, {"path": "/path/to/cert"}, ["path"]),
    (CertificateExpiredError, {"expiry_date": "2024-01-01"}, ["expiry_date"]),
    (CertificateRenewalError, {}, []),
    (CSRGenerationError, {"message": "csr failed"}, ["message"]),
    (CARequestError, {"message": "ca failed"}, ["message"]),
    # RBAC
    (RBACError, {}, []),
    (PermissionDeniedError, {"user_id": "user1", "resource": "journal", "action": "post", "required_permission": "journal.post"}, ["user_id", "resource", "action", "required_permission"]),
    (UserNotFoundError, {"user_id": "user1"}, ["user_id"]),
    (SODConstraintError, {}, []),
    (SODViolationError, {"user_id": "user1", "violations": ["violation1"]}, ["user_id", "violations"]),
    # Vault
    (VaultError, {}, []),
    (VaultNotAvailableError, {"message": "vault down"}, ["message"]),
    (SecretNotFoundError, {"path": "secret/path"}, ["path"]),
    (LeaseRenewalError, {"lease_id": "lease-123", "message": "renewal failed"}, ["lease_id", "message"]),
    # Key rotation
    (KeyRotationError, {}, []),
    (KeyRotationLockError, {"message": "lock failed"}, ["message"]),
    (ReEncryptionError, {"message": "re-encrypt failed", "records_affected": 10}, ["message", "records_affected"]),
    # Hashing
    (HashingError, {}, []),
    (HashVerificationError, {"message": "hash mismatch"}, ["message"]),
]


@pytest.mark.parametrize("exc_class, kwargs, attrs", EXCEPTIONS)
def test_exception_instantiation(exc_class, kwargs, attrs):
    """Test that each exception can be instantiated and attributes are set."""
    exc = exc_class(**kwargs)
    assert isinstance(exc, Exception)
    assert isinstance(exc, SecurityError)
    for attr in attrs:
        assert hasattr(exc, attr)
        if attr in kwargs:
            assert getattr(exc, attr) == kwargs[attr]


@pytest.mark.parametrize("exc_class, kwargs, attrs", EXCEPTIONS)
def test_exception_can_be_raised(exc_class, kwargs, attrs):
    """Test that each exception can be raised and caught with correct message."""
    message = kwargs.get("message", "test error")
    with pytest.raises(exc_class) as exc_info:
        raise exc_class(**kwargs)
    assert str(exc_info.value) is not None
    if "message" in attrs:
        assert exc_info.value.message == message


@pytest.mark.parametrize("exc_class, kwargs, attrs", EXCEPTIONS)
def test_exception_inheritance(exc_class, kwargs, attrs):
    """Test that exceptions inherit correctly from SecurityError."""
    exc = exc_class(**kwargs)
    assert isinstance(exc, SecurityError)
    # Also check specific parent chain for categories
    if "JWT" in exc_class.__name__ or exc_class.__name__ in [
        "JWTIssuerError", "PrivateKeyNotFoundError", "TokenGenerationError",
        "JWTValidatorError", "InvalidTokenError", "ExpiredTokenError",
        "RevokedTokenError", "InvalidIssuerError", "InvalidAudienceError",
        "JWTRevocationError", "RevocationNotFoundError"
    ]:
        if exc_class not in (JWTError, JWTIssuerError, JWTValidatorError, JWTRevocationError):
            assert isinstance(exc, JWTError)
    if exc_class.__name__ in ["DecryptionError", "KeyNotFoundError"]:
        assert isinstance(exc, FieldEncryptionError)


# =============================================================================
# SPECIFIC TESTS FOR EXCEPTIONS WITH CUSTOM ATTRIBUTES
# =============================================================================

class TestSpecificAttributes:
    def test_invalid_issuer_error_attributes(self):
        exc = InvalidIssuerError(expected="issuer-1", actual="issuer-2")
        assert exc.expected == "issuer-1"
        assert exc.actual == "issuer-2"
        assert "expected issuer-1, got issuer-2" in exc.message

    def test_invalid_audience_error_attributes(self):
        exc = InvalidAudienceError(expected="aud-1", actual="aud-2")
        assert exc.expected == "aud-1"
        assert exc.actual == "aud-2"
        assert "expected aud-1, got aud-2" in exc.message

    def test_revocation_not_found_error_attributes(self):
        exc = RevocationNotFoundError(jti="jti-123")
        assert exc.jti == "jti-123"
        assert "jti-123" in exc.message

    def test_key_not_found_error_attributes(self):
        exc = KeyNotFoundError(key_id="key-123")
        assert exc.key_id == "key-123"
        assert "key-123" in exc.message

    def test_certificate_not_found_error_attributes(self):
        exc = CertificateNotFoundError(path="/path/to/cert")
        assert exc.path == "/path/to/cert"
        assert "/path/to/cert" in exc.message

    def test_certificate_expired_error_attributes(self):
        exc = CertificateExpiredError(expiry_date="2024-01-01")
        assert exc.expiry_date == "2024-01-01"
        assert "2024-01-01" in exc.message

    def test_lease_renewal_error_attributes(self):
        exc = LeaseRenewalError(lease_id="lease-123", message="renewal failed")
        assert exc.lease_id == "lease-123"
        assert exc.message == "renewal failed"
        assert "lease-123" in str(exc)

    def test_permission_denied_error_attributes(self):
        exc = PermissionDeniedError(
            user_id="user1",
            resource="journal",
            action="post",
            required_permission="journal.post"
        )
        assert exc.user_id == "user1"
        assert exc.resource == "journal"
        assert exc.action == "post"
        assert exc.required_permission == "journal.post"
        assert "Permission denied" in exc.message

    def test_user_not_found_error_attributes(self):
        exc = UserNotFoundError(user_id="user1")
        assert exc.user_id == "user1"
        assert "user1" in exc.message

    def test_sod_violation_error_attributes(self):
        violations = ["violation1", "violation2"]
        exc = SODViolationError(user_id="user1", violations=violations)
        assert exc.user_id == "user1"
        assert exc.violations == violations
        assert "2 violation(s)" in exc.message

    def test_secret_not_found_error_attributes(self):
        exc = SecretNotFoundError(path="secret/path")
        assert exc.path == "secret/path"
        assert "secret/path" in exc.message

    def test_re_encryption_error_attributes(self):
        exc = ReEncryptionError(message="re-encrypt failed", records_affected=10)
        assert exc.message == "re-encrypt failed"
        assert exc.records_affected == 10

    def test_private_key_not_found_error_code(self):
        exc = PrivateKeyNotFoundError()
        assert exc.code == "PRIVATE_KEY_NOT_FOUND"

    def test_token_generation_error_code(self):
        exc = TokenGenerationError("failed")
        assert exc.code == "TOKEN_GENERATION_FAILED"

    def test_invalid_token_error_code(self):
        exc = InvalidTokenError()
        assert exc.code == "INVALID_TOKEN"

    def test_expired_token_error_code(self):
        exc = ExpiredTokenError()
        assert exc.code == "TOKEN_EXPIRED"

    def test_revoked_token_error_code(self):
        exc = RevokedTokenError()
        assert exc.code == "TOKEN_REVOKED"

    def test_decryption_error_code(self):
        exc = DecryptionError()
        assert exc.code == "DECRYPTION_FAILED"

    def test_signing_error_code(self):
        exc = SigningError("failed")
        assert exc.code == "SIGNING_FAILED"

    def test_verification_error_code(self):
        exc = VerificationError()
        assert exc.code == "VERIFICATION_FAILED"

    def test_vault_not_available_error_code(self):
        exc = VaultNotAvailableError()
        assert exc.code == "VAULT_NOT_AVAILABLE"

    def test_key_rotation_lock_error_code(self):
        exc = KeyRotationLockError()
        assert exc.code == "ROTATION_LOCK_FAILED"

    def test_re_encryption_error_code(self):
        exc = ReEncryptionError("failed")
        assert exc.code == "RE_ENCRYPTION_FAILED"

    def test_hash_verification_error_code(self):
        exc = HashVerificationError()
        assert exc.code == "HASH_VERIFICATION_FAILED"


# =============================================================================
# TESTS FOR DETAILS DICTIONARY
# =============================================================================

class TestDetails:
    def test_security_error_with_details(self):
        details = {"field": "password", "reason": "too_short"}
        exc = SecurityError("test", code="ERR-001", details=details)
        assert exc.details == details
        assert exc.details["field"] == "password"

    def test_permission_denied_error_details(self):
        exc = PermissionDeniedError("user1", "journal", "post", "journal.post")
        assert "user_id" in exc.details
        assert exc.details["user_id"] == "user1"

    def test_invalid_issuer_error_details(self):
        exc = InvalidIssuerError("expected", "actual")
        assert "expected" in exc.details
        assert exc.details["expected"] == "expected"

    def test_sod_violation_error_details(self):
        exc = SODViolationError("user1", ["v1"])
        assert "violations" in exc.details
        assert exc.details["violations"] == ["v1"]
