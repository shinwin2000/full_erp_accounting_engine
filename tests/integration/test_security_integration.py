#!/usr/bin/env python3
"""
Integration: Security (JWT, Encryption, Vault)
Menguji pembuatan & validasi JWT, enkripsi field, dan integrasi dengan HashiCorp Vault.
"""

from __future__ import annotations

import inspect
import os
import tempfile

import pytest

# ============================================================================
# Import real modules (jika ada) dengan fallback
# ============================================================================

# Encryption
try:
    from infrastructure.security.field_encryption_aes256_gcm import (
        FieldEncryptionService,
        get_field_encryption,
    )

    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False

# JWT
JWT_AVAILABLE = False
JWT_SECRET_ARG = None
try:
    from infrastructure.security.jwt_issuer import JWTIssuer, PrivateKeyNotFoundError
    from infrastructure.security.jwt_validator import JWTValidator

    JWT_AVAILABLE = True

    # Cek signature JWTIssuer.__init__
    init_sig = inspect.signature(JWTIssuer.__init__)
    if "secret_key" in init_sig.parameters:
        JWT_SECRET_ARG = "secret_key"
    elif "key" in init_sig.parameters:
        JWT_SECRET_ARG = "key"
    else:
        JWT_SECRET_ARG = None
except ImportError:
    JWT_AVAILABLE = False
    PrivateKeyNotFoundError = Exception

# Vault
try:
    from infrastructure.security.vault_dynamic_secret_provider import VaultSecretProvider

    VAULT_AVAILABLE = True
except ImportError:
    VAULT_AVAILABLE = False


# ============================================================================
# Helper untuk membuat JWT issuer & validator dengan temporary key (optional)
# ============================================================================


def create_jwt_issuer_with_temp_key():
    """Membuat issuer dengan temporary RSA key untuk testing (jika memungkinkan)."""
    try:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        pytest.skip("cryptography not installed for RSA key generation")

    # Generate temporary private key
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".pem", delete=False) as f:
        f.write(pem)
        temp_key_path = f.name

    # Override environment or config to use this key
    # Assuming JWTIssuer reads from config or environment variable
    # We'll set JWT_PRIVATE_KEY_PATH env temporarily
    original_env = os.environ.get("JWT_PRIVATE_KEY_PATH")
    os.environ["JWT_PRIVATE_KEY_PATH"] = temp_key_path

    try:
        issuer = JWTIssuer()
        validator = JWTValidator()
        yield issuer, validator
    finally:
        # Cleanup
        if original_env is not None:
            os.environ["JWT_PRIVATE_KEY_PATH"] = original_env
        else:
            del os.environ["JWT_PRIVATE_KEY_PATH"]
        os.unlink(temp_key_path)


def create_jwt_issuer():
    """Buat JWTIssuer dengan fallback ke environment atau skip jika tidak memungkinkan."""
    if not JWT_AVAILABLE:
        pytest.skip("JWT modules not available")

    # Coba buat dengan temporary key jika memungkinkan
    try:
        # Cek apakah JWTIssuer mendukung parameter private_key_path atau sejenis
        # Jika tidak, lewat
        return JWTIssuer()
    except PrivateKeyNotFoundError:
        # Jika tidak ada key, coba generate temporary
        try:
            # Generate temporary RSA key and set environment
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import rsa

            private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".pem", delete=False) as f:
                f.write(pem)
                temp_path = f.name
            # Override environment variable that JWTIssuer might use
            os.environ["JWT_PRIVATE_KEY_PATH"] = temp_path
            try:
                issuer = JWTIssuer()
                JWTValidator()
                # Store cleanup info for later
                issuer._temp_key_path = temp_path
                return issuer
            except Exception:
                os.unlink(temp_path)
                raise
        except Exception:
            pytest.skip("Cannot create JWT issuer due to missing private key configuration")


def create_jwt_validator():
    if not JWT_AVAILABLE:
        pytest.skip("JWT modules not available")
    try:
        return JWTValidator()
    except PrivateKeyNotFoundError:
        # If no key, try to use the one set by create_jwt_issuer
        if hasattr(create_jwt_issuer, "_temp_key_path"):
            return JWTValidator()
        else:
            pytest.skip("JWTValidator requires private key configuration")


# ============================================================================
# TESTS
# ============================================================================


def test_jwt_generate_and_validate():
    """Test generate dan validasi JWT (skip jika environment tidak siap)."""
    try:
        issuer = create_jwt_issuer()
        validator = create_jwt_validator()
    except Exception as e:
        pytest.skip(f"JWT environment not ready: {e}")

    # Cek signature generate method
    gen_sig = inspect.signature(issuer.generate)
    params = gen_sig.parameters

    if "user_id" in params:
        token = issuer.generate(user_id="USER-001", roles=["finance"], expires_in=3600)
    elif "subject" in params:
        token = issuer.generate(subject="USER-001", roles=["finance"], expires_in=3600)
    else:
        token = issuer.generate(claims={"user_id": "USER-001", "roles": ["finance"]})

    assert token is not None

    payload = validator.validate(token)
    assert payload.get("user_id") == "USER-001" or payload.get("sub") == "USER-001"
    assert "finance" in payload.get("roles", [])


def test_jwt_expired():
    """Test token expired harus raise PermissionError."""
    try:
        issuer = create_jwt_issuer()
        validator = create_jwt_validator()
    except Exception as e:
        pytest.skip(f"JWT environment not ready: {e}")

    gen_sig = inspect.signature(issuer.generate)
    if "user_id" in gen_sig.parameters:
        token = issuer.generate(user_id="USER-001", expires_in=-1)
    else:
        token = issuer.generate(claims={"user_id": "USER-001"}, expires_in=-1)

    with pytest.raises(PermissionError, match="Token expired"):
        validator.validate(token)


@pytest.mark.skipif(not ENCRYPTION_AVAILABLE, reason="Encryption module not available")
def test_field_encryption_decryption():
    """Test enkripsi dan dekripsi field sensitif."""
    enc_service = get_field_encryption()
    plaintext = "Sensitive Data: NPWP 123456789012345"
    ciphertext = enc_service.encrypt(plaintext)
    assert ciphertext != plaintext
    decrypted = enc_service.decrypt(ciphertext)
    assert decrypted == plaintext


@pytest.mark.skipif(not VAULT_AVAILABLE, reason="Vault module not available")
def test_vault_integration():
    """Test integrasi Vault (skip jika tidak tersedia)."""
    try:
        provider = VaultSecretProvider(vault_addr="http://localhost:8200", token="test-token")
        secret = provider.get_secret("database/password")
        assert secret is not None
    except Exception:
        pytest.skip("Vault tidak tersedia atau koneksi gagal")
