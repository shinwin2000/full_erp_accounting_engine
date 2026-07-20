# test_signature_vo.py
# Comprehensive tests for signature_vo.py

import json
import secrets
from datetime import UTC, datetime, timedelta

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
# Fixtures
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
def valid_signature_hmac(sample_data, secret_key):
    """Create a valid HMAC-SHA256 signature."""
    return SignatureVO.create(
        data=sample_data,
        signed_by="user123",
        algorithm="HMAC-SHA256",
        key=secret_key,
        certificate_id="cert-1",
        key_id="key-1",
    )


@pytest.fixture
def valid_signature_hmac_512(sample_data, secret_key):
    """Create a valid HMAC-SHA512 signature."""
    return SignatureVO.create(
        data=sample_data,
        signed_by="user123",
        algorithm="HMAC-SHA512",
        key=secret_key,
    )


# ============================================================================
# Tests for Exceptions
# ============================================================================

def test_signature_error_is_value_error():
    assert issubclass(SignatureError, ValueError)


def test_invalid_signature_error_is_signature_error():
    assert issubclass(InvalidSignatureError, SignatureError)


def test_unsupported_algorithm_error_is_signature_error():
    assert issubclass(UnsupportedAlgorithmError, SignatureError)


# ============================================================================
# Tests for SignatureVO Construction
# ============================================================================

class TestSignatureVOConstruction:
    def test_valid_construction(self, valid_signature_hmac):
        assert valid_signature_hmac.signature_hex is not None
        assert len(valid_signature_hmac.signature_hex) == 64  # SHA256 hex digest length
        assert valid_signature_hmac.algorithm == "HMAC-SHA256"
        assert valid_signature_hmac.signed_by == "user123"
        assert valid_signature_hmac.signed_at.tzinfo == UTC
        assert valid_signature_hmac.certificate_id == "cert-1"
        assert valid_signature_hmac.key_id == "key-1"

    def test_construction_with_naive_datetime(self):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        sig = SignatureVO(
            signature_hex="a" * 64,
            algorithm="HMAC-SHA256",
            signed_by="user",
            signed_at=naive,
        )
        assert sig.signed_at.tzinfo == UTC

    def test_invalid_algorithm(self):
        with pytest.raises(UnsupportedAlgorithmError, match="Algorithm 'INVALID' not supported"):
            SignatureVO(
                signature_hex="a" * 64,
                algorithm="INVALID",
                signed_by="user",
                signed_at=datetime.now(UTC),
            )

    def test_invalid_hex_string_odd_length(self):
        with pytest.raises(SignatureError, match="even length"):
            SignatureVO(
                signature_hex="abc",  # odd length
                algorithm="HMAC-SHA256",
                signed_by="user",
                signed_at=datetime.now(UTC),
            )

    def test_invalid_hex_string_non_hex(self):
        with pytest.raises(SignatureError, match="not valid hexadecimal"):
            SignatureVO(
                signature_hex="zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",  # 64 chars of z
                algorithm="HMAC-SHA256",
                signed_by="user",
                signed_at=datetime.now(UTC),
            )

    def test_empty_signed_by(self):
        with pytest.raises(SignatureError, match="signed_by cannot be empty"):
            SignatureVO(
                signature_hex="a" * 64,
                algorithm="HMAC-SHA256",
                signed_by="",
                signed_at=datetime.now(UTC),
            )

    def test_certificate_id_empty_stripped(self):
        sig = SignatureVO(
            signature_hex="a" * 64,
            algorithm="HMAC-SHA256",
            signed_by="user",
            signed_at=datetime.now(UTC),
            certificate_id="  ",
        )
        assert sig.certificate_id is None

    def test_key_id_empty_stripped(self):
        sig = SignatureVO(
            signature_hex="a" * 64,
            algorithm="HMAC-SHA256",
            signed_by="user",
            signed_at=datetime.now(UTC),
            key_id="  ",
        )
        assert sig.key_id is None


# ============================================================================
# Tests for Factory Methods
# ============================================================================

class TestSignatureVOFactory:
    def test_create_with_bytes(self, sample_data, secret_key):
        sig = SignatureVO.create(
            data=sample_data,
            signed_by="user",
            algorithm="HMAC-SHA256",
            key=secret_key,
        )
        assert isinstance(sig, SignatureVO)
        # Verify it later

    def test_create_with_string(self, sample_data_str, secret_key):
        sig = SignatureVO.create(
            data=sample_data_str,
            signed_by="user",
            algorithm="HMAC-SHA256",
            key=secret_key,
        )
        assert sig.signature_hex is not None

    def test_create_with_dict(self, sample_data_dict, secret_key):
        sig = SignatureVO.create(
            data=sample_data_dict,
            signed_by="user",
            algorithm="HMAC-SHA256",
            key=secret_key,
        )
        assert sig.signature_hex is not None

    def test_create_with_unsupported_data_type(self, secret_key):
        with pytest.raises(SignatureError, match="Unsupported data type"):
            SignatureVO.create(
                data=123,  # int not supported
                signed_by="user",
                algorithm="HMAC-SHA256",
                key=secret_key,
            )

    def test_create_with_hmac_sha512(self, sample_data, secret_key):
        sig = SignatureVO.create(
            data=sample_data,
            signed_by="user",
            algorithm="HMAC-SHA512",
            key=secret_key,
        )
        assert sig.algorithm == "HMAC-SHA512"
        assert len(sig.signature_hex) == 128  # SHA512 hex digest length

    def test_create_with_rsa_raises(self, sample_data, secret_key):
        with pytest.raises(UnsupportedAlgorithmError, match="RSA-PSS signature requires"):
            SignatureVO.create(
                data=sample_data,
                signed_by="user",
                algorithm="SHA256-RSA-PSS",
                key=secret_key,
            )

    def test_create_with_idempotency_key(self, sample_data, secret_key):
        # Should not raise; idempotency_key is a no-op.
        sig = SignatureVO.create(
            data=sample_data,
            signed_by="user",
            algorithm="HMAC-SHA256",
            key=secret_key,
            idempotency_key="abc123",
        )
        assert isinstance(sig, SignatureVO)

    def test_create_with_default_key(self, sample_data):
        # If no key provided, uses _DEFAULT_SECRET_KEY
        sig = SignatureVO.create(
            data=sample_data,
            signed_by="user",
            algorithm="HMAC-SHA256",
        )
        assert sig.signature_hex is not None

    def test_create_with_signed_at(self, sample_data, secret_key):
        dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        sig = SignatureVO.create(
            data=sample_data,
            signed_by="user",
            algorithm="HMAC-SHA256",
            key=secret_key,
            signed_at=dt,
        )
        assert sig.signed_at == dt

    def test_from_dict(self, valid_signature_hmac):
        d = valid_signature_hmac.to_dict(include_full_signature=True)
        sig2 = SignatureVO.from_dict(d)
        assert sig2 == valid_signature_hmac

    def test_from_dict_without_full_signature(self, valid_signature_hmac):
        d = valid_signature_hmac.to_dict(include_full_signature=False)
        # This dict lacks signature_hex, so from_dict would miss it.
        # The test should use include_full_signature=True to reconstruct.
        # We'll test that from_dict requires signature_hex.
        with pytest.raises(KeyError):
            SignatureVO.from_dict(d)

    def test_from_db_record(self, valid_signature_hmac):
        record = valid_signature_hmac.to_db_record()
        sig2 = SignatureVO.from_db_record(record)
        assert sig2 == valid_signature_hmac


# ============================================================================
# Tests for Properties
# ============================================================================

class TestSignatureVOProperties:
    def test_signature_bytes(self, valid_signature_hmac):
        assert isinstance(valid_signature_hmac.signature_bytes, bytes)
        assert valid_signature_hmac.signature_bytes == bytes.fromhex(valid_signature_hmac.signature_hex)

    def test_short_signature(self, valid_signature_hmac):
        short = valid_signature_hmac.short_signature
        assert short.endswith("...")
        assert len(short) == 19  # 16 chars + "..."

    def test_algorithm_type(self, valid_signature_hmac):
        assert valid_signature_hmac.algorithm_type == "hmac"
        # For RSA, would be "rsa", but we skip due to unsupported.


# ============================================================================
# Tests for Verification
# ============================================================================

class TestSignatureVOVerification:
    def test_verify_with_bytes_ok(self, valid_signature_hmac, sample_data, secret_key):
        assert valid_signature_hmac.verify(sample_data, key=secret_key) is True

    def test_verify_with_string_ok(self, valid_signature_hmac, sample_data_str, secret_key):
        # The signature was created with bytes, but verify should accept string
        assert valid_signature_hmac.verify(sample_data_str, key=secret_key) is True

    def test_verify_with_dict_ok(self, valid_signature_hmac, sample_data_dict, secret_key):
        # Create signature with dict
        sig = SignatureVO.create(
            data=sample_data_dict,
            signed_by="user",
            algorithm="HMAC-SHA256",
            key=secret_key,
        )
        assert sig.verify(sample_data_dict, key=secret_key) is True

    def test_verify_with_wrong_data(self, valid_signature_hmac, secret_key):
        wrong_data = b"Goodbye, world!"
        assert valid_signature_hmac.verify(wrong_data, key=secret_key) is False

    def test_verify_with_wrong_key(self, valid_signature_hmac, sample_data):
        wrong_key = b"98765432109876543210987654321098"
        assert valid_signature_hmac.verify(sample_data, key=wrong_key) is False

    def test_verify_with_key_id_mismatch(self, valid_signature_hmac, sample_data):
        # valid_signature_hmac has key_id="key-1"
        with pytest.raises(SignatureError, match="Key ID mismatch"):
            valid_signature_hmac.verify(sample_data, key_id="key-2")

    def test_verify_with_unsupported_data_type(self, valid_signature_hmac):
        with pytest.raises(SignatureError, match="Unsupported data type"):
            valid_signature_hmac.verify(123)  # int

    def test_verify_rsa_unsupported(self, sample_data, secret_key):
        # We cannot create RSA, but we can create a dummy VO with RSA algorithm
        sig = SignatureVO(
            signature_hex="a" * 64,  # dummy
            algorithm="SHA256-RSA-PSS",
            signed_by="user",
            signed_at=datetime.now(UTC),
        )
        with pytest.raises(UnsupportedAlgorithmError, match="RSA-PSS verification"):
            sig.verify(sample_data, key=secret_key)

    def test_verify_with_unsupported_algorithm(self, sample_data, secret_key):
        sig = SignatureVO(
            signature_hex="a" * 64,
            algorithm="UNKNOWN",
            signed_by="user",
            signed_at=datetime.now(UTC),
        )
        with pytest.raises(UnsupportedAlgorithmError, match="Algorithm UNKNOWN not supported"):
            sig.verify(sample_data, key=secret_key)

    def test_verify_with_key_method(self, valid_signature_hmac, sample_data, secret_key):
        assert valid_signature_hmac.verify_with_key(sample_data, key=secret_key) is True
        wrong_key = b"98765432109876543210987654321098"
        assert valid_signature_hmac.verify_with_key(sample_data, key=wrong_key) is False


# ============================================================================
# Tests for Serialization
# ============================================================================

class TestSignatureVOSerialization:
    def test_to_dict_without_full_signature(self, valid_signature_hmac):
        d = valid_signature_hmac.to_dict(include_full_signature=False)
        assert "signature_hex" not in d
        assert "signature" in d
        assert d["signature"] == valid_signature_hmac.short_signature
        assert d["algorithm"] == "HMAC-SHA256"
        assert d["signed_by"] == "user123"
        assert d["certificate_id"] == "cert-1"
        assert d["key_id"] == "key-1"

    def test_to_dict_with_full_signature(self, valid_signature_hmac):
        d = valid_signature_hmac.to_dict(include_full_signature=True)
        assert "signature_hex" in d
        assert d["signature_hex"] == valid_signature_hmac.signature_hex
        assert "signature" not in d  # not present when include_full_signature=True? Actually code includes "signature" if include_full_signature is false, else it adds signature_hex but still maybe adds signature? Let's check: the code sets result with signature if not include_full, else signature_hex. It doesn't include both. So fine.

    def test_to_db_record(self, valid_signature_hmac):
        rec = valid_signature_hmac.to_db_record()
        assert rec["signature_hex"] == valid_signature_hmac.signature_hex
        assert rec["algorithm"] == "HMAC-SHA256"
        assert rec["signed_by"] == "user123"
        assert rec["signed_at"] == valid_signature_hmac.signed_at
        assert rec["certificate_id"] == "cert-1"
        assert rec["key_id"] == "key-1"


# ============================================================================
# Tests for Dunder Methods
# ============================================================================

class TestSignatureVODunder:
    def test_str(self, valid_signature_hmac):
        s = str(valid_signature_hmac)
        assert "Signature(HMAC-SHA256, by=user123, sig=" in s

    def test_repr(self, valid_signature_hmac):
        r = repr(valid_signature_hmac)
        assert "SignatureVO('" + valid_signature_hmac.short_signature + "', algorithm='HMAC-SHA256', signed_by='user123')" in r

    def test_equality(self, valid_signature_hmac):
        same = SignatureVO(
            signature_hex=valid_signature_hmac.signature_hex,
            algorithm=valid_signature_hmac.algorithm,
            signed_by=valid_signature_hmac.signed_by,
            signed_at=valid_signature_hmac.signed_at,
            certificate_id=valid_signature_hmac.certificate_id,
            key_id=valid_signature_hmac.key_id,
        )
        assert valid_signature_hmac == same
        different = SignatureVO(
            signature_hex="a" * 64,
            algorithm="HMAC-SHA256",
            signed_by="other",
            signed_at=datetime.now(UTC),
        )
        assert valid_signature_hmac != different

    def test_hash(self, valid_signature_hmac):
        h1 = hash(valid_signature_hmac)
        same = SignatureVO(
            signature_hex=valid_signature_hmac.signature_hex,
            algorithm=valid_signature_hmac.algorithm,
            signed_by=valid_signature_hmac.signed_by,
            signed_at=valid_signature_hmac.signed_at,
        )
        assert h1 == hash(same)


# ============================================================================
# Tests for Helper Functions
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

    def test_sign_data_with_idempotency_key(self, sample_data, secret_key):
        # Should not raise
        sig = sign_data(
            data=sample_data,
            key=secret_key,
            signed_by="user",
            algorithm="HMAC-SHA256",
            idempotency_key="abc",
        )
        assert isinstance(sig, SignatureVO)

    def test_verify_signature(self, valid_signature_hmac, sample_data, secret_key):
        assert verify_signature(valid_signature_hmac, sample_data, secret_key) is True
        wrong_data = b"Wrong data"
        assert verify_signature(valid_signature_hmac, wrong_data, secret_key) is False


# ============================================================================
# Additional edge cases: default key usage
# ============================================================================

def test_create_with_default_key_and_verify(sample_data):
    sig = SignatureVO.create(
        data=sample_data,
        signed_by="system",
        algorithm="HMAC-SHA256",
    )
    # Verify using default key (which is same as internal _DEFAULT_SECRET_KEY)
    # We need to import _DEFAULT_SECRET_KEY from module
    from domain.shared_value_objects.signature_vo import _DEFAULT_SECRET_KEY
    assert sig.verify(sample_data, key=_DEFAULT_SECRET_KEY) is True