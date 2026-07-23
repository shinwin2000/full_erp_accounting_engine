# test_signature_vo.py
# Comprehensive tests for signature_vo.py
# Fixed datetime to avoid flakiness, parameterized to eliminate duplication.

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from domain.shared_value_objects.signature_vo import (
    InvalidSignatureError,
    SignatureError,
    SignatureVO,
    UnsupportedAlgorithmError,
    generate_key,
    rotate_key,
    sign_data,
    verify_signature,
)


# ============================================================================
# FIXED DATETIME FIXTURE
# ============================================================================

@pytest.fixture
def fixed_now():
    """Fixed datetime for deterministic tests."""
    return datetime(2026, 6, 15, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def fixed_past():
    return datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def fixed_future():
    return datetime(2026, 7, 1, 10, 0, 0, tzinfo=UTC)


# ============================================================================
# FIXTURES FOR TEST DATA
# ============================================================================

@pytest.fixture
def secret_key():
    """Return a fixed 32-byte key for deterministic tests."""
    return b"01234567890123456789012345678901"  # 32 bytes


@pytest.fixture
def sample_data():
    return b"Hello, world!"


@pytest.fixture
def sample_data_str():
    return "Hello, world!"


@pytest.fixture
def sample_data_dict():
    return {"message": "Hello", "timestamp": "2025-01-01T00:00:00Z"}


@pytest.fixture
def default_key():
    from domain.shared_value_objects.signature_vo import _DEFAULT_SECRET_KEY
    return _DEFAULT_SECRET_KEY


# ============================================================================
# EXCEPTION TESTS (Parameterized to eliminate duplication)
# ============================================================================

EXCEPTION_CLASSES = [
    (SignatureError, ValueError),
    (InvalidSignatureError, SignatureError),
    (UnsupportedAlgorithmError, SignatureError),
]


@pytest.mark.parametrize("exc_class,parent", EXCEPTION_CLASSES)
def test_exception_hierarchy(exc_class, parent):
    assert issubclass(exc_class, parent)


# ============================================================================
# TESTS FOR SIGNATURE VO CONSTRUCTION
# ============================================================================

class TestSignatureVOConstruction:
    def test_valid_construction_hmac256(self, secret_key, sample_data, fixed_now):
        # Create signature using factory
        sig = SignatureVO.create(
            data=sample_data,
            signed_by="user123",
            algorithm="HMAC-SHA256",
            key=secret_key,
            certificate_id="cert-1",
            key_id="key-1",
            signed_at=fixed_now,
        )
        assert sig.signature_hex is not None
        assert len(sig.signature_hex) == 64  # SHA256 hex digest length
        assert sig.algorithm == "HMAC-SHA256"
        assert sig.signed_by == "user123"
        assert sig.signed_at == fixed_now
        assert sig.certificate_id == "cert-1"
        assert sig.key_id == "key-1"

    def test_valid_construction_hmac512(self, secret_key, sample_data, fixed_now):
        sig = SignatureVO.create(
            data=sample_data,
            signed_by="user123",
            algorithm="HMAC-SHA512",
            key=secret_key,
            signed_at=fixed_now,
        )
        assert len(sig.signature_hex) == 128  # SHA512 hex digest length
        assert sig.algorithm == "HMAC-SHA512"

    def test_construction_with_naive_datetime(self):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        sig = SignatureVO(
            signature_hex="a" * 64,
            algorithm="HMAC-SHA256",
            signed_by="user",
            signed_at=naive,
        )
        assert sig.signed_at.tzinfo == UTC

    def test_construction_with_utc_datetime(self):
        utc = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        sig = SignatureVO(
            signature_hex="a" * 64,
            algorithm="HMAC-SHA256",
            signed_by="user",
            signed_at=utc,
        )
        assert sig.signed_at == utc

    # --- Negative path: invalid algorithm ---
    def test_invalid_algorithm_raises(self):
        with pytest.raises(UnsupportedAlgorithmError, match="Algorithm 'INVALID' not supported"):
            SignatureVO(
                signature_hex="a" * 64,
                algorithm="INVALID",
                signed_by="user",
                signed_at=datetime.now(UTC),
            )

    # --- Negative path: invalid hex strings ---
    def test_hex_odd_length_raises(self):
        with pytest.raises(SignatureError, match="even length"):
            SignatureVO(
                signature_hex="abc",
                algorithm="HMAC-SHA256",
                signed_by="user",
                signed_at=datetime.now(UTC),
            )

    def test_hex_non_hex_chars_raises(self):
        with pytest.raises(SignatureError, match="not valid hexadecimal"):
            SignatureVO(
                signature_hex="z" * 64,
                algorithm="HMAC-SHA256",
                signed_by="user",
                signed_at=datetime.now(UTC),
            )

    # --- Negative path: empty signed_by ---
    def test_empty_signed_by_raises(self):
        with pytest.raises(SignatureError, match="signed_by cannot be empty"):
            SignatureVO(
                signature_hex="a" * 64,
                algorithm="HMAC-SHA256",
                signed_by="",
                signed_at=datetime.now(UTC),
            )

    # --- Whitespace trimming ---
    def test_certificate_id_empty_stripped(self, fixed_now):
        sig = SignatureVO(
            signature_hex="a" * 64,
            algorithm="HMAC-SHA256",
            signed_by="user",
            signed_at=fixed_now,
            certificate_id="  ",
        )
        assert sig.certificate_id is None

    def test_key_id_empty_stripped(self, fixed_now):
        sig = SignatureVO(
            signature_hex="a" * 64,
            algorithm="HMAC-SHA256",
            signed_by="user",
            signed_at=fixed_now,
            key_id="  ",
        )
        assert sig.key_id is None


# ============================================================================
# TESTS FOR FACTORY METHODS
# ============================================================================

class TestSignatureVOFactory:
    @pytest.mark.parametrize("data", [
        (b"Hello, world!"),
        ("Hello, world!"),
        ({"message": "Hello", "timestamp": "2025-01-01T00:00:00Z"}),
    ])
    def test_create_with_various_data_types(self, data, secret_key):
        sig = SignatureVO.create(
            data=data,
            signed_by="user",
            algorithm="HMAC-SHA256",
            key=secret_key,
        )
        assert isinstance(sig, SignatureVO)
        assert sig.verify(data, key=secret_key) is True

    def test_create_with_unsupported_data_type_raises(self, secret_key):
        with pytest.raises(SignatureError, match="Unsupported data type"):
            SignatureVO.create(
                data=123,  # int not supported
                signed_by="user",
                algorithm="HMAC-SHA256",
                key=secret_key,
            )

    def test_create_with_rsa_raises(self, sample_data, secret_key):
        with pytest.raises(UnsupportedAlgorithmError, match="RSA-PSS signature requires"):
            SignatureVO.create(
                data=sample_data,
                signed_by="user",
                algorithm="SHA256-RSA-PSS",
                key=secret_key,
            )

    def test_create_with_idempotency_key_no_effect(self, sample_data, secret_key):
        # The idempotency_key is a no-op in this pure factory.
        sig = SignatureVO.create(
            data=sample_data,
            signed_by="user",
            algorithm="HMAC-SHA256",
            key=secret_key,
            idempotency_key="abc123",
        )
        assert isinstance(sig, SignatureVO)

    def test_create_with_default_key(self, sample_data, fixed_now):
        # No key provided, uses internal default key.
        sig = SignatureVO.create(
            data=sample_data,
            signed_by="user",
            algorithm="HMAC-SHA256",
            signed_at=fixed_now,
        )
        assert sig.signature_hex is not None

    def test_create_with_signed_at(self, sample_data, secret_key, fixed_now):
        sig = SignatureVO.create(
            data=sample_data,
            signed_by="user",
            algorithm="HMAC-SHA256",
            key=secret_key,
            signed_at=fixed_now,
        )
        assert sig.signed_at == fixed_now

    def test_from_dict_full(self, fixed_now):
        data = {
            "signature_hex": "a" * 64,
            "algorithm": "HMAC-SHA256",
            "signed_by": "user",
            "signed_at": fixed_now.isoformat(),
            "certificate_id": "cert-1",
            "key_id": "key-1",
        }
        sig = SignatureVO.from_dict(data)
        assert sig.signature_hex == "a" * 64
        assert sig.algorithm == "HMAC-SHA256"
        assert sig.signed_by == "user"
        assert sig.signed_at == fixed_now
        assert sig.certificate_id == "cert-1"
        assert sig.key_id == "key-1"

    def test_from_dict_missing_optional_fields(self, fixed_now):
        data = {
            "signature_hex": "a" * 64,
            "algorithm": "HMAC-SHA256",
            "signed_by": "user",
            "signed_at": fixed_now.isoformat(),
        }
        sig = SignatureVO.from_dict(data)
        assert sig.certificate_id is None
        assert sig.key_id is None

    def test_from_db_record(self, fixed_now):
        record = {
            "signature_hex": "a" * 64,
            "algorithm": "HMAC-SHA256",
            "signed_by": "user",
            "signed_at": fixed_now,
            "certificate_id": "cert-1",
            "key_id": "key-1",
        }
        sig = SignatureVO.from_db_record(record)
        assert sig.signature_hex == "a" * 64
        assert sig.signed_at == fixed_now


# ============================================================================
# TESTS FOR PROPERTIES
# ============================================================================

class TestSignatureVOProperties:
    def test_signature_bytes(self, secret_key, sample_data):
        sig = SignatureVO.create(sample_data, "user", key=secret_key)
        assert isinstance(sig.signature_bytes, bytes)
        assert sig.signature_bytes == bytes.fromhex(sig.signature_hex)

    def test_short_signature(self, secret_key, sample_data):
        sig = SignatureVO.create(sample_data, "user", key=secret_key)
        short = sig.short_signature
        assert short.endswith("...")
        assert len(short) == 19  # 16 chars + "..."

    def test_algorithm_type_hmac(self, secret_key, sample_data):
        sig = SignatureVO.create(sample_data, "user", algorithm="HMAC-SHA256", key=secret_key)
        assert sig.algorithm_type == "hmac"


# ============================================================================
# TESTS FOR VERIFICATION
# ============================================================================

class TestSignatureVOVerification:
    @pytest.mark.parametrize("data", [
        b"Hello, world!",
        "Hello, world!",
        {"message": "Hello", "timestamp": "2025-01-01T00:00:00Z"},
    ])
    def test_verify_with_correct_data(self, data, secret_key):
        sig = SignatureVO.create(data, "user", key=secret_key)
        assert sig.verify(data, key=secret_key) is True

    def test_verify_with_wrong_data(self, secret_key, sample_data):
        sig = SignatureVO.create(sample_data, "user", key=secret_key)
        wrong_data = b"Goodbye, world!"
        assert sig.verify(wrong_data, key=secret_key) is False

    def test_verify_with_wrong_key(self, secret_key, sample_data):
        sig = SignatureVO.create(sample_data, "user", key=secret_key)
        wrong_key = b"98765432109876543210987654321098"
        assert sig.verify(sample_data, key=wrong_key) is False

    def test_verify_with_key_id_mismatch(self, secret_key, sample_data):
        sig = SignatureVO.create(
            sample_data, "user", key=secret_key, key_id="key-1"
        )
        with pytest.raises(SignatureError, match="Key ID mismatch"):
            sig.verify(sample_data, key_id="key-2", key=secret_key)

    def test_verify_with_unsupported_data_type(self, secret_key, sample_data):
        sig = SignatureVO.create(sample_data, "user", key=secret_key)
        with pytest.raises(SignatureError, match="Unsupported data type"):
            sig.verify(123)  # int

    def test_verify_rsa_unsupported_raises(self):
        # Create a dummy RSA signature object.
        sig = SignatureVO(
            signature_hex="a" * 64,
            algorithm="SHA256-RSA-PSS",
            signed_by="user",
            signed_at=datetime.now(UTC),
        )
        with pytest.raises(UnsupportedAlgorithmError, match="RSA-PSS verification"):
            sig.verify(b"data", key=b"dummy")

    def test_verify_with_unsupported_algorithm_raises(self, secret_key, sample_data):
        sig = SignatureVO(
            signature_hex="a" * 64,
            algorithm="UNKNOWN",
            signed_by="user",
            signed_at=datetime.now(UTC),
        )
        with pytest.raises(UnsupportedAlgorithmError, match="Algorithm UNKNOWN not supported"):
            sig.verify(sample_data, key=secret_key)

    def test_verify_with_key_method(self, secret_key, sample_data):
        sig = SignatureVO.create(sample_data, "user", key=secret_key)
        assert sig.verify_with_key(sample_data, key=secret_key) is True
        wrong_key = b"98765432109876543210987654321098"
        assert sig.verify_with_key(sample_data, key=wrong_key) is False


# ============================================================================
# TESTS FOR SERIALIZATION
# ============================================================================

class TestSignatureVOSerialization:
    def test_to_dict_without_full_signature(self, secret_key, sample_data, fixed_now):
        sig = SignatureVO.create(
            sample_data, "user123", key=secret_key, certificate_id="cert-1", key_id="key-1",
            signed_at=fixed_now,
        )
        d = sig.to_dict(include_full_signature=False)
        assert "signature_hex" not in d
        assert "signature" in d
        assert d["signature"] == sig.short_signature
        assert d["algorithm"] == "HMAC-SHA256"
        assert d["signed_by"] == "user123"
        assert d["signed_at"] == fixed_now.isoformat()
        assert d["certificate_id"] == "cert-1"
        assert d["key_id"] == "key-1"

    def test_to_dict_with_full_signature(self, secret_key, sample_data):
        sig = SignatureVO.create(sample_data, "user", key=secret_key)
        d = sig.to_dict(include_full_signature=True)
        assert "signature_hex" in d
        assert d["signature_hex"] == sig.signature_hex
        assert "signature" not in d

    def test_to_db_record(self, secret_key, sample_data, fixed_now):
        sig = SignatureVO.create(
            sample_data, "user", key=secret_key, certificate_id="cert-1", key_id="key-1",
            signed_at=fixed_now,
        )
        rec = sig.to_db_record()
        assert rec["signature_hex"] == sig.signature_hex
        assert rec["algorithm"] == "HMAC-SHA256"
        assert rec["signed_by"] == "user"
        assert rec["signed_at"] == fixed_now
        assert rec["certificate_id"] == "cert-1"
        assert rec["key_id"] == "key-1"


# ============================================================================
# TESTS FOR DUNDER METHODS
# ============================================================================

class TestSignatureVODunder:
    def test_str(self, secret_key, sample_data):
        sig = SignatureVO.create(sample_data, "user", key=secret_key)
        s = str(sig)
        assert "Signature(HMAC-SHA256, by=user, sig=" in s

    def test_repr(self, secret_key, sample_data):
        sig = SignatureVO.create(sample_data, "user", key=secret_key)
        r = repr(sig)
        assert "SignatureVO('" + sig.short_signature + "', algorithm='HMAC-SHA256', signed_by='user')" in r

    def test_equality(self, secret_key, sample_data):
        sig1 = SignatureVO.create(sample_data, "user", key=secret_key)
        sig2 = SignatureVO(
            signature_hex=sig1.signature_hex,
            algorithm=sig1.algorithm,
            signed_by=sig1.signed_by,
            signed_at=sig1.signed_at,
        )
        assert sig1 == sig2
        sig3 = SignatureVO(
            signature_hex="a" * 64,
            algorithm="HMAC-SHA256",
            signed_by="other",
            signed_at=datetime.now(UTC),
        )
        assert sig1 != sig3
        assert sig1 != "not a signature"

    def test_hash(self, secret_key, sample_data):
        sig1 = SignatureVO.create(sample_data, "user", key=secret_key)
        sig2 = SignatureVO(
            signature_hex=sig1.signature_hex,
            algorithm=sig1.algorithm,
            signed_by=sig1.signed_by,
            signed_at=sig1.signed_at,
        )
        assert hash(sig1) == hash(sig2)
        sig3 = SignatureVO(
            signature_hex="a" * 64,
            algorithm="HMAC-SHA256",
            signed_by="other",
            signed_at=datetime.now(UTC),
        )
        assert hash(sig1) != hash(sig3)


# ============================================================================
# TESTS FOR HELPER FUNCTIONS
# ============================================================================

class TestHelpers:
    def test_generate_key(self):
        key = generate_key()
        assert isinstance(key, bytes)
        assert len(key) == 32

    def test_rotate_key(self):
        old = b"01234567890123456789012345678901"
        new = rotate_key(old)
        assert isinstance(new, bytes)
        assert len(new) == 32
        assert new != old

    def test_sign_data(self, sample_data, secret_key):
        sig = sign_data(
            data=sample_data,
            key=secret_key,
            signed_by="user",
            algorithm="HMAC-SHA256",
        )
        assert isinstance(sig, SignatureVO)
        assert sig.verify(sample_data, key=secret_key) is True

    def test_sign_data_with_idempotency_key_no_effect(self, sample_data, secret_key):
        sig = sign_data(
            data=sample_data,
            key=secret_key,
            signed_by="user",
            algorithm="HMAC-SHA256",
            idempotency_key="abc",
        )
        assert isinstance(sig, SignatureVO)
        # Verify it's a valid signature
        assert sig.verify(sample_data, key=secret_key) is True

    def test_verify_signature(self, sample_data, secret_key):
        sig = sign_data(sample_data, secret_key, "user")
        assert verify_signature(sig, sample_data, secret_key) is True
        wrong_data = b"Wrong data"
        assert verify_signature(sig, wrong_data, secret_key) is False


# ============================================================================
# ADDITIONAL EDGE CASES: DEFAULT KEY USAGE
# ============================================================================

def test_create_with_default_key_and_verify(sample_data, default_key):
    sig = SignatureVO.create(
        data=sample_data,
        signed_by="system",
        algorithm="HMAC-SHA256",
    )
    # Verify using default key
    assert sig.verify(sample_data, key=default_key) is True

    # Verify with wrong key should fail
    wrong_key = b"wrongkeywrongkeywrongkeywrongkeywrongkeywrongkey"  # 32 bytes but wrong
    assert sig.verify(sample_data, key=wrong_key) is False