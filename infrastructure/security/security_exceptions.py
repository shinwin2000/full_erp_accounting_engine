#!/usr/bin/env python3
"""
Module: security_exceptions.py
Layer: Infrastructure (Security)
Responsibility: Mendefinisikan semua exception yang terkait dengan security
               infrastructure. Exception dibagi dalam kategori: JWT, encryption,
               signing, certificate, RBAC, SOD, Vault, dan audit.
               Setiap exception membawa metadata untuk debugging dan audit.
Dependencies:
- none (standalone module)
Audit: Exception yang terjadi di security layer dicatat oleh security audit logger.
"""

from __future__ import annotations

from typing import Any

# ============================================================================
# BASE EXCEPTION
# ============================================================================


class SecurityError(Exception):
    """
    Base exception untuk semua error di security infrastructure.
    """

    def __init__(
        self, message: str, code: str | None = None, details: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


# ============================================================================
# JWT EXCEPTIONS
# ============================================================================


class JWTError(SecurityError):
    """Base exception untuk JWT operations."""

    pass


class JWTIssuerError(JWTError):
    """Error saat issuer JWT token."""

    pass


class PrivateKeyNotFoundError(JWTIssuerError):
    """Private key tidak ditemukan."""

    def __init__(self, message: str = "Private key not found", **kwargs):
        super().__init__(message, code="PRIVATE_KEY_NOT_FOUND", **kwargs)


class TokenGenerationError(JWTIssuerError):
    """Gagal generate token."""

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="TOKEN_GENERATION_FAILED", **kwargs)


class JWTValidatorError(JWTError):
    """Error saat validasi JWT token."""

    pass


class InvalidTokenError(JWTValidatorError):
    """Token tidak valid."""

    def __init__(self, message: str = "Invalid token", **kwargs):
        super().__init__(message, code="INVALID_TOKEN", **kwargs)


class ExpiredTokenError(JWTValidatorError):
    """Token sudah expired."""

    def __init__(self, message: str = "Token expired", **kwargs):
        super().__init__(message, code="TOKEN_EXPIRED", **kwargs)


class RevokedTokenError(JWTValidatorError):
    """Token sudah di-revoke."""

    def __init__(self, message: str = "Token revoked", **kwargs):
        super().__init__(message, code="TOKEN_REVOKED", **kwargs)


class InvalidIssuerError(JWTValidatorError):
    """Issuer tidak sesuai."""

    def __init__(self, expected: str, actual: str, **kwargs):
        super().__init__(
            f"Invalid issuer: expected {expected}, got {actual}", code="INVALID_ISSUER", **kwargs
        )
        self.expected = expected
        self.actual = actual


class InvalidAudienceError(JWTValidatorError):
    """Audience tidak sesuai."""

    def __init__(self, expected: str, actual: str, **kwargs):
        super().__init__(
            f"Invalid audience: expected {expected}, got {actual}",
            code="INVALID_AUDIENCE",
            **kwargs,
        )
        self.expected = expected
        self.actual = actual


class JWTRevocationError(JWTError):
    """Error saat revokasi token."""

    pass


class RevocationNotFoundError(JWTRevocationError):
    """Revocation record tidak ditemukan."""

    def __init__(self, jti: str, **kwargs):
        super().__init__(
            f"Revocation record not found for {jti}", code="REVOCATION_NOT_FOUND", **kwargs
        )
        self.jti = jti


# ============================================================================
# ENCRYPTION EXCEPTIONS
# ============================================================================


class FieldEncryptionError(SecurityError):
    """Base exception untuk field encryption."""

    pass


class DecryptionError(FieldEncryptionError):
    """Gagal mendekripsi data."""

    def __init__(self, message: str = "Decryption failed", **kwargs):
        super().__init__(message, code="DECRYPTION_FAILED", **kwargs)


class KeyNotFoundError(FieldEncryptionError):
    """Encryption key tidak ditemukan."""

    def __init__(self, key_id: str, **kwargs):
        super().__init__(f"Encryption key not found: {key_id}", code="KEY_NOT_FOUND", **kwargs)
        self.key_id = key_id


# ============================================================================
# DIGITAL SIGNING EXCEPTIONS
# ============================================================================


class DigitalSignerError(SecurityError):
    """Base exception untuk digital signer."""

    pass


class SigningError(DigitalSignerError):
    """Gagal melakukan signing."""

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SIGNING_FAILED", **kwargs)


class VerificationError(DigitalSignerError):
    """Signature verification failed."""

    def __init__(self, message: str = "Signature verification failed", **kwargs):
        super().__init__(message, code="VERIFICATION_FAILED", **kwargs)


# ============================================================================
# CERTIFICATE EXCEPTIONS
# ============================================================================


class CertificateError(SecurityError):
    """Base exception untuk certificate operations."""

    pass


class CertificateLoadError(CertificateError):
    """Gagal load certificate."""

    pass


class CertificateNotFoundError(CertificateLoadError):
    """Certificate file tidak ditemukan."""

    def __init__(self, path: str, **kwargs):
        super().__init__(f"Certificate not found: {path}", code="CERTIFICATE_NOT_FOUND", **kwargs)
        self.path = path


class CertificateExpiredError(CertificateLoadError):
    """Certificate sudah expired."""

    def __init__(self, expiry_date: str, **kwargs):
        super().__init__(
            f"Certificate expired on {expiry_date}", code="CERTIFICATE_EXPIRED", **kwargs
        )
        self.expiry_date = expiry_date


class CertificateRenewalError(CertificateError):
    """Error saat renewal certificate."""

    pass


class CSRGenerationError(CertificateRenewalError):
    """Gagal generate CSR."""

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="CSR_GENERATION_FAILED", **kwargs)


class CARequestError(CertificateRenewalError):
    """Error saat request ke CA."""

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="CA_REQUEST_FAILED", **kwargs)


# ============================================================================
# RBAC EXCEPTIONS
# ============================================================================


class RBACError(SecurityError):
    """Base exception untuk RBAC."""

    pass


class PermissionDeniedError(RBACError):
    """User tidak memiliki permission yang diperlukan."""

    def __init__(
        self, user_id: str, resource: str, action: str, required_permission: str, **kwargs
    ):
        super().__init__(
            f"Permission denied for user {user_id}: {required_permission}",
            code="PERMISSION_DENIED",
            **kwargs,
        )
        self.user_id = user_id
        self.resource = resource
        self.action = action
        self.required_permission = required_permission


class UserNotFoundError(RBACError):
    """User tidak ditemukan."""

    def __init__(self, user_id: str, **kwargs):
        super().__init__(f"User not found: {user_id}", code="USER_NOT_FOUND", **kwargs)
        self.user_id = user_id


class SODConstraintError(SecurityError):
    """Base exception untuk SoD constraint."""

    pass


class SODViolationError(SODConstraintError):
    """Terjadi pelanggaran Separation of Duties."""

    def __init__(self, user_id: str, violations: list, **kwargs):
        super().__init__(
            f"SoD violations for user {user_id}: {len(violations)} violation(s)",
            code="SOD_VIOLATION",
            **kwargs,
        )
        self.user_id = user_id
        self.violations = violations


# ============================================================================
# VAULT EXCEPTIONS
# ============================================================================


class VaultError(SecurityError):
    """Base exception untuk Vault operations."""

    pass


class VaultNotAvailableError(VaultError):
    """Vault tidak tersedia."""

    def __init__(self, message: str = "Vault not available", **kwargs):
        super().__init__(message, code="VAULT_NOT_AVAILABLE", **kwargs)


class SecretNotFoundError(VaultError):
    """Secret tidak ditemukan di Vault."""

    def __init__(self, path: str, **kwargs):
        super().__init__(f"Secret not found: {path}", code="SECRET_NOT_FOUND", **kwargs)
        self.path = path


class LeaseRenewalError(VaultError):
    """Gagal memperbarui lease."""

    def __init__(self, lease_id: str, message: str = "Lease renewal failed", **kwargs):
        super().__init__(message, code="LEASE_RENEWAL_FAILED", **kwargs)
        self.lease_id = lease_id


# ============================================================================
# KEY ROTATION EXCEPTIONS
# ============================================================================


class KeyRotationError(SecurityError):
    """Base exception untuk key rotation."""

    pass


class KeyRotationLockError(KeyRotationError):
    """Gagal mengakuisisi lock untuk rotasi."""

    def __init__(self, message: str = "Failed to acquire rotation lock", **kwargs):
        super().__init__(message, code="ROTATION_LOCK_FAILED", **kwargs)


class ReEncryptionError(KeyRotationError):
    """Error saat re-encryption data."""

    def __init__(self, message: str, records_affected: int | None = None, **kwargs):
        super().__init__(message, code="RE_ENCRYPTION_FAILED", **kwargs)
        self.records_affected = records_affected


# ============================================================================
# HASHING EXCEPTIONS
# ============================================================================


class HashingError(SecurityError):
    """Base exception untuk hashing service."""

    pass


class HashVerificationError(HashingError):
    """Hash verification failed."""

    def __init__(self, message: str = "Hash verification failed", **kwargs):
        super().__init__(message, code="HASH_VERIFICATION_FAILED", **kwargs)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Base
    "SecurityError",
    # JWT
    "JWTError",
    "JWTIssuerError",
    "PrivateKeyNotFoundError",
    "TokenGenerationError",
    "JWTValidatorError",
    "InvalidTokenError",
    "ExpiredTokenError",
    "RevokedTokenError",
    "InvalidIssuerError",
    "InvalidAudienceError",
    "JWTRevocationError",
    "RevocationNotFoundError",
    # Encryption
    "FieldEncryptionError",
    "DecryptionError",
    "KeyNotFoundError",
    # Digital signing
    "DigitalSignerError",
    "SigningError",
    "VerificationError",
    # Certificate
    "CertificateError",
    "CertificateLoadError",
    "CertificateNotFoundError",
    "CertificateExpiredError",
    "CertificateRenewalError",
    "CSRGenerationError",
    "CARequestError",
    # RBAC
    "RBACError",
    "PermissionDeniedError",
    "UserNotFoundError",
    "SODConstraintError",
    "SODViolationError",
    # Vault
    "VaultError",
    "VaultNotAvailableError",
    "SecretNotFoundError",
    "LeaseRenewalError",
    # Key rotation
    "KeyRotationError",
    "KeyRotationLockError",
    "ReEncryptionError",
    # Hashing
    "HashingError",
    "HashVerificationError",
]
