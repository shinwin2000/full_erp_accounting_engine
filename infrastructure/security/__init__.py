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
    from .api_key_validator import APIKeyValidator, validate_api_key
except ImportError:
    APIKeyValidator = None
    validate_api_key = None

# ============================================================================
# Audit Log Security Events
# ============================================================================
try:
    from .audit_log_security_events import SecurityAuditLogger, log_security_event
except ImportError:
    SecurityAuditLogger = None
    log_security_event = None

# ============================================================================
# Authority Matrix
# ============================================================================
try:
    from .authority_matrix import AuthorityMatrix, get_authority_matrix
except ImportError:
    AuthorityMatrix = None
    get_authority_matrix = None

# ============================================================================
# Digital Signature
# ============================================================================
try:
    from .digital_signature_verifier import DigitalSignatureVerifier, verify_signature
except ImportError:
    DigitalSignatureVerifier = None
    verify_signature = None

try:
    from .digital_signer_rsa_pss import (
        DigitalSignerRSA_PSS,
        generate_rsa_keypair,
        sign_data,
        verify_signature_rsa,
    )
except ImportError:
    DigitalSignerRSA_PSS = None
    generate_rsa_keypair = None
    sign_data = None
    verify_signature_rsa = None

# ============================================================================
# Field Encryption / Decryption
# ============================================================================
try:
    from .field_decryption_service import FieldDecryptionService, decrypt_field
except ImportError:
    FieldDecryptionService = None
    decrypt_field = None

# 🔥 PERBAIKAN: typo 'ases' menjadi 'aes'
try:
    from .field_encryption_aes256_gcm import (  # <-- typo diperbaiki
        FieldEncryptionAES256GCM,
        decrypt_field_aes,
        encrypt_field,
    )
except ImportError:
    FieldEncryptionAES256GCM = None
    encrypt_field = None
    decrypt_field_aes = None

# ============================================================================
# Hashing
# ============================================================================
try:
    from .hashing_service_sha3_256 import (
        HashingServiceSHA3_256,
        hash_data,
        verify_hash,
    )
except ImportError:
    HashingServiceSHA3_256 = None
    hash_data = None
    verify_hash = None

# ============================================================================
# HSM (Hardware Security Module)
# ============================================================================
try:
    from .hsm_pkcs11_signing_adapter import HSMSigner, sign_with_hsm
except ImportError:
    HSMSigner = None
    sign_with_hsm = None

# ============================================================================
# JWT (Issuer, Validator, Revocation)
# ============================================================================
try:
    from .jwt_issuer import JWTIssuer, issue_jwt, issue_refresh_token
except ImportError:
    JWTIssuer = None
    issue_jwt = None
    issue_refresh_token = None

try:
    from .jwt_validator import JWTValidator, decode_jwt, validate_jwt
except ImportError:
    JWTValidator = None
    validate_jwt = None
    decode_jwt = None

try:
    from .jwt_revocation_list import JWTRevocationList, is_token_revoked, revoke_token
except ImportError:
    JWTRevocationList = None
    revoke_token = None
    is_token_revoked = None

# ============================================================================
# Key Management & Rotation
# ============================================================================
try:
    from .key_management import KeyManager, get_key_manager
except ImportError:
    KeyManager = None
    get_key_manager = None

try:
    from .key_rotation_scheduler_vault import (
        KeyRotationSchedulerVault,
        rotate_keys,
        schedule_key_rotation,
    )
except ImportError:
    KeyRotationSchedulerVault = None
    schedule_key_rotation = None
    rotate_keys = None

try:
    from .securitykey_management_vault import KeyManagementVault, get_vault_client
except ImportError:
    KeyManagementVault = None
    get_vault_client = None

try:
    from .vault_dynamic_secret_provider import (
        VaultDynamicSecretProvider,
        get_dynamic_secret,
    )
except ImportError:
    VaultDynamicSecretProvider = None
    get_dynamic_secret = None

# ============================================================================
# mTLS
# ============================================================================
try:
    from .mtls_certificate_loader import (
        MTLSClientCertificateLoader,
        load_mtls_certificate,
    )
except ImportError:
    MTLSClientCertificateLoader = None
    load_mtls_certificate = None

try:
    from .mtls_certificate_renewer import (
        MTLSClientCertificateRenewer,
        renew_certificate,
    )
except ImportError:
    MTLSClientCertificateRenewer = None
    renew_certificate = None

# ============================================================================
# RBAC (Role-Based Access Control)
# ============================================================================
try:
    from .rbac_enforcer_unified import (
        RBACEnforcerUnified,
        authorize,
        get_user_roles,
        has_permission,
    )
except ImportError:
    RBACEnforcerUnified = None
    authorize = None
    has_permission = None
    get_user_roles = None

# ============================================================================
# SoD (Separation of Duties)
# ============================================================================
try:
    from .sod_constraint_checker import (
        SODConstraintChecker,
        check_sod_conflict,
        get_sod_violations,
    )
except ImportError:
    SODConstraintChecker = None
    check_sod_conflict = None
    get_sod_violations = None

# ============================================================================
# Exceptions
# ============================================================================
try:
    from .security_exceptions import (
        AuthenticationError,
        AuthorizationError,
        CertificateError,
        EncryptionError,
        JWTError,
        KeyManagementError,
        SecurityError,
    )
except ImportError:
    SecurityError = Exception
    AuthenticationError = Exception
    AuthorizationError = Exception
    EncryptionError = Exception
    JWTError = Exception
    KeyManagementError = Exception
    CertificateError = Exception

# ============================================================================
# __all__ export
# ============================================================================
__all__ = [
    # API Key
    "APIKeyValidator",
    "validate_api_key",
    # Audit
    "SecurityAuditLogger",
    "log_security_event",
    # Authority
    "AuthorityMatrix",
    "get_authority_matrix",
    # Digital Signature
    "DigitalSignatureVerifier",
    "verify_signature",
    "DigitalSignerRSA_PSS",
    "generate_rsa_keypair",
    "sign_data",
    "verify_signature_rsa",
    # Encryption
    "FieldDecryptionService",
    "decrypt_field",
    "FieldEncryptionAES256GCM",
    "encrypt_field",
    "decrypt_field_aes",
    # Hashing
    "HashingServiceSHA3_256",
    "hash_data",
    "verify_hash",
    # HSM
    "HSMSigner",
    "sign_with_hsm",
    # JWT
    "JWTIssuer",
    "issue_jwt",
    "issue_refresh_token",
    "JWTValidator",
    "validate_jwt",
    "decode_jwt",
    "JWTRevocationList",
    "revoke_token",
    "is_token_revoked",
    # Key Management
    "KeyManager",
    "get_key_manager",
    "KeyRotationSchedulerVault",
    "schedule_key_rotation",
    "rotate_keys",
    "KeyManagementVault",
    "get_vault_client",
    "VaultDynamicSecretProvider",
    "get_dynamic_secret",
    # mTLS
    "MTLSClientCertificateLoader",
    "load_mtls_certificate",
    "MTLSClientCertificateRenewer",
    "renew_certificate",
    # RBAC
    "RBACEnforcerUnified",
    "authorize",
    "has_permission",
    "get_user_roles",
    # SoD
    "SODConstraintChecker",
    "check_sod_conflict",
    "get_sod_violations",
    # Exceptions
    "SecurityError",
    "AuthenticationError",
    "AuthorizationError",
    "EncryptionError",
    "JWTError",
    "KeyManagementError",
    "CertificateError",
]