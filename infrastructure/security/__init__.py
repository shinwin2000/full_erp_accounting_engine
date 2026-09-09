#!/usr/bin/env python3
"""
Package: infrastructure.security
Security utilities: JWT, RBAC, encryption, key management, mTLS, HSM.
"""

from __future__ import annotations

# ============================================================================
# API Key Validator
# ============================================================================
try:
    from .api_key_validator import APIKeyValidator, validate_api_key  # type: ignore[attr-defined]
except ImportError:
    APIKeyValidator = None  # type: ignore
    validate_api_key = None  # type: ignore

# ============================================================================
# Audit Log Security Events
# ============================================================================
try:
    from .audit_log_security_events import (  # type: ignore[attr-defined]
        SecurityAuditLogger,
        log_security_event,
    )
except ImportError:
    SecurityAuditLogger = None  # type: ignore
    log_security_event = None  # type: ignore

# ============================================================================
# Authority Matrix
# ============================================================================
try:
    from .authority_matrix import (  # type: ignore[attr-defined]
        AuthorityMatrix,
        get_authority_matrix,
    )
except ImportError:
    AuthorityMatrix = None  # type: ignore
    get_authority_matrix = None  # type: ignore

# ============================================================================
# Digital Signature
# ============================================================================
try:
    from .digital_signature_verifier import (  # type: ignore[attr-defined]
        DigitalSignatureVerifier,
        verify_signature,
    )
except ImportError:
    DigitalSignatureVerifier = None  # type: ignore
    verify_signature = None  # type: ignore

try:
    from .digital_signer_rsa_pss import (  # type: ignore[attr-defined]
        DigitalSignerRSA_PSS,
        generate_rsa_keypair,
        sign_data,
        verify_signature_rsa,
    )
except ImportError:
    DigitalSignerRSA_PSS = None  # type: ignore
    generate_rsa_keypair = None  # type: ignore
    sign_data = None  # type: ignore
    verify_signature_rsa = None  # type: ignore

# ============================================================================
# Field Encryption / Decryption
# ============================================================================
try:
    from .field_decryption_service import (  # type: ignore[attr-defined]
        FieldDecryptionService,
        decrypt_field,
    )
except ImportError:
    FieldDecryptionService = None  # type: ignore
    decrypt_field = None  # type: ignore

try:
    from .field_encryption_aes256_gcm import (  # type: ignore[attr-defined]
        FieldEncryptionAES256GCM,
        decrypt_field_aes,
        encrypt_field,
    )
except ImportError:
    FieldEncryptionAES256GCM = None  # type: ignore
    encrypt_field = None  # type: ignore
    decrypt_field_aes = None  # type: ignore

# ============================================================================
# Hashing
# ============================================================================
try:
    from .hashing_service_sha3_256 import (  # type: ignore[attr-defined]
        HashingServiceSHA3_256,
        hash_data,
        verify_hash,
    )
except ImportError:
    HashingServiceSHA3_256 = None  # type: ignore
    hash_data = None  # type: ignore
    verify_hash = None  # type: ignore

# ============================================================================
# HSM (Hardware Security Module)
# ============================================================================
try:
    from .hsm_pkcs11_signing_adapter import HSMSigner, sign_with_hsm  # type: ignore[attr-defined]
except ImportError:
    HSMSigner = None  # type: ignore
    sign_with_hsm = None  # type: ignore

# ============================================================================
# JWT (Issuer, Validator, Revocation)
# ============================================================================
try:
    from .jwt_issuer import JWTIssuer, issue_jwt, issue_refresh_token  # type: ignore[attr-defined]
except ImportError:
    JWTIssuer = None  # type: ignore
    issue_jwt = None  # type: ignore
    issue_refresh_token = None  # type: ignore

try:
    from .jwt_validator import JWTValidator, decode_jwt, validate_jwt  # type: ignore[attr-defined]
except ImportError:
    JWTValidator = None  # type: ignore
    validate_jwt = None  # type: ignore
    decode_jwt = None  # type: ignore

try:
    from .jwt_revocation_list import (  # type: ignore[attr-defined]
        JWTRevocationList,
        is_token_revoked,
        revoke_token,
    )
except ImportError:
    JWTRevocationList = None  # type: ignore
    revoke_token = None  # type: ignore
    is_token_revoked = None  # type: ignore

# ============================================================================
# Key Management & Rotation
# ============================================================================
try:
    from .key_management import KeyManager, get_key_manager  # type: ignore[attr-defined]
except ImportError:
    KeyManager = None  # type: ignore
    get_key_manager = None  # type: ignore

try:
    from .key_rotation_scheduler_vault import (  # type: ignore[attr-defined]
        KeyRotationSchedulerVault,
        rotate_keys,
        schedule_key_rotation,
    )
except ImportError:
    KeyRotationSchedulerVault = None  # type: ignore
    schedule_key_rotation = None  # type: ignore
    rotate_keys = None  # type: ignore

try:
    from .securitykey_management_vault import (  # type: ignore[attr-defined]
        KeyManagementVault,
        get_vault_client,
    )
except ImportError:
    KeyManagementVault = None  # type: ignore
    get_vault_client = None  # type: ignore

try:
    from .vault_dynamic_secret_provider import (  # type: ignore[attr-defined]
        VaultDynamicSecretProvider,
        get_dynamic_secret,
    )
except ImportError:
    VaultDynamicSecretProvider = None  # type: ignore
    get_dynamic_secret = None  # type: ignore

# ============================================================================
# mTLS
# ============================================================================
try:
    from .mtls_certificate_loader import (  # type: ignore[attr-defined]
        MTLSClientCertificateLoader,
        load_mtls_certificate,
    )
except ImportError:
    MTLSClientCertificateLoader = None  # type: ignore
    load_mtls_certificate = None  # type: ignore

try:
    from .mtls_certificate_renewer import (  # type: ignore[attr-defined]
        MTLSClientCertificateRenewer,
        renew_certificate,
    )
except ImportError:
    MTLSClientCertificateRenewer = None  # type: ignore
    renew_certificate = None  # type: ignore

# ============================================================================
# RBAC (Role-Based Access Control)
# ============================================================================
try:
    from .rbac_enforcer_unified import (  # type: ignore[attr-defined]
        RBACEnforcerUnified,
        authorize,
        get_user_roles,
        has_permission,
    )
except ImportError:
    RBACEnforcerUnified = None  # type: ignore
    authorize = None  # type: ignore
    has_permission = None  # type: ignore
    get_user_roles = None  # type: ignore

# ============================================================================
# SoD (Separation of Duties)
# ============================================================================
try:
    from .sod_constraint_checker import (  # type: ignore[attr-defined]
        SODConstraintChecker,
        check_sod_conflict,
        get_sod_violations,
    )
except ImportError:
    SODConstraintChecker = None  # type: ignore
    check_sod_conflict = None  # type: ignore
    get_sod_violations = None  # type: ignore

# ============================================================================
# Exceptions
# ============================================================================
try:
    from .security_exceptions import (  # type: ignore[attr-defined]
        AuthenticationError,
        AuthorizationError,
        CertificateError,
        EncryptionError,
        JWTError,
        KeyManagementError,
        SecurityError,
    )
except ImportError:
    SecurityError = Exception  # type: ignore
    AuthenticationError = Exception  # type: ignore
    AuthorizationError = Exception  # type: ignore
    EncryptionError = Exception  # type: ignore
    JWTError = Exception  # type: ignore
    KeyManagementError = Exception  # type: ignore
    CertificateError = Exception  # type: ignore

# ============================================================================
# __all__ export
# ============================================================================
__all__ = [
    # API Key
    "APIKeyValidator",
    "AuthenticationError",
    # Authority
    "AuthorityMatrix",
    "AuthorizationError",
    "CertificateError",
    # Digital Signature
    "DigitalSignatureVerifier",
    "DigitalSignerRSA_PSS",
    "EncryptionError",
    # Encryption
    "FieldDecryptionService",
    "FieldEncryptionAES256GCM",
    # HSM
    "HSMSigner",
    # Hashing
    "HashingServiceSHA3_256",
    "JWTError",
    # JWT
    "JWTIssuer",
    "JWTRevocationList",
    "JWTValidator",
    "KeyManagementError",
    "KeyManagementVault",
    # Key Management
    "KeyManager",
    "KeyRotationSchedulerVault",
    # mTLS
    "MTLSClientCertificateLoader",
    "MTLSClientCertificateRenewer",
    # RBAC
    "RBACEnforcerUnified",
    # SoD
    "SODConstraintChecker",
    # Audit
    "SecurityAuditLogger",
    # Exceptions
    "SecurityError",
    "VaultDynamicSecretProvider",
    "authorize",
    "check_sod_conflict",
    "decode_jwt",
    "decrypt_field",
    "decrypt_field_aes",
    "encrypt_field",
    "generate_rsa_keypair",
    "get_authority_matrix",
    "get_dynamic_secret",
    "get_key_manager",
    "get_sod_violations",
    "get_user_roles",
    "get_vault_client",
    "has_permission",
    "hash_data",
    "is_token_revoked",
    "issue_jwt",
    "issue_refresh_token",
    "load_mtls_certificate",
    "log_security_event",
    "renew_certificate",
    "revoke_token",
    "rotate_keys",
    "schedule_key_rotation",
    "sign_data",
    "sign_with_hsm",
    "validate_api_key",
    "validate_jwt",
    "verify_hash",
    "verify_signature",
    "verify_signature_rsa",
]
