# test_cryptographic_signer.py
# =============================
# Comprehensive tests for domain/intent/cryptographic_signer.py.
# Covers all public methods, including those flagged by checker:
# - verify_intent_data
# - get_public_key
# - get_key_info
# Also covers fallback mode, error handling, and entity base methods.

import base64
import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest

from domain.intent.cryptographic_signer import (
    CryptographicSigner,
    get_cryptographic_signer,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def signer():
    """Fresh CryptographicSigner instance with reset singleton."""
    CryptographicSigner._instance = None
    return CryptographicSigner()


@pytest.fixture
def sample_content() -> str:
    return "This is a test content for signing."


@pytest.fixture
def sample_data() -> dict:
    return {"amount": 1000, "currency": "IDR", "description": "Test"}


# ----------------------------------------------------------------------
# Tests for singleton and initialization
# ----------------------------------------------------------------------
class TestCryptographicSignerSingleton:
    def test_singleton(self):
        s1 = get_cryptographic_signer()
        s2 = get_cryptographic_signer()
        assert s1 is s2
        # Reset for other tests
        s1.reset()
        CryptographicSigner._instance = None

    def test_reset_reinitializes(self, signer):
        # reset will reinitialize keys if crypto available
        signer.reset()
        # We can't assert specific state because crypto may or may not be available,
        # but at least it should not raise.
        assert isinstance(signer, CryptographicSigner)


# ----------------------------------------------------------------------
# Tests with cryptography available (mocked)
# ----------------------------------------------------------------------
class TestCryptographicSignerWithCrypto:
    @pytest.fixture(autouse=True)
    def mock_crypto_available(self):
        """Mock cryptography as available for these tests."""
        with patch("domain.intent.cryptographic_signer.CRYPTO_AVAILABLE", True):
            with patch("domain.intent.cryptographic_signer.rsa") as mock_rsa:
                mock_private_key = MagicMock()
                mock_public_key = MagicMock()
                mock_private_key.public_key.return_value = mock_public_key
                mock_private_key.sign.return_value = b"fake_signature"
                mock_public_key.verify.return_value = None  # no exception => success
                mock_rsa.generate_private_key.return_value = mock_private_key

                with patch("domain.intent.cryptographic_signer.serialization") as mock_serialization:
                    mock_serialization.load_pem_private_key.return_value = mock_private_key
                    mock_serialization.load_pem_public_key.return_value = mock_public_key
                    mock_public_key.public_bytes.return_value = b"fake_public_pem"
                    yield

    def test_init_generates_keys(self, signer):
        assert signer._private_key is not None
        assert signer._public_key_pem is not None
        assert signer.is_available() is True

    def test_load_private_key_from_pem_success(self, signer):
        with patch("domain.intent.cryptographic_signer.serialization.load_pem_private_key") as mock_load:
            mock_private = MagicMock()
            mock_public = MagicMock()
            mock_private.public_key.return_value = mock_public
            mock_public.public_bytes.return_value = b"new_public_pem"
            mock_load.return_value = mock_private

            result = signer.load_private_key_from_pem("fake_pem_data", password=b"pass")
            assert result is True
            assert signer._private_key is mock_private
            assert signer._public_key_pem == "new_public_pem"

    def test_load_private_key_from_pem_failure(self, signer):
        with patch("domain.intent.cryptographic_signer.serialization.load_pem_private_key") as mock_load:
            mock_load.side_effect = Exception("Invalid key")
            result = signer.load_private_key_from_pem("invalid")
            assert result is False

    def test_load_private_key_not_rsa(self, signer):
        with patch("domain.intent.cryptographic_signer.serialization.load_pem_private_key") as mock_load:
            mock_load.return_value = MagicMock()  # not RSA
            result = signer.load_private_key_from_pem("fake")
            assert result is False

    def test_sign_success(self, signer, sample_content):
        signature = signer.sign(sample_content, "user123")
        expected = base64.b64encode(b"fake_signature").decode("ascii")
        assert signature == expected

    def test_sign_empty_content_raises(self, signer):
        with pytest.raises(ValueError, match="Content cannot be empty"):
            signer.sign("", "user")

    def test_sign_fallback_when_crypto_unavailable(self, signer, sample_content):
        with patch("domain.intent.cryptographic_signer.CRYPTO_AVAILABLE", False):
            signer._private_key = None
            sig = signer.sign(sample_content, "user")
            assert sig.startswith("FALLBACK_SIG:")
            expected_hash = hashlib.sha3_256(sample_content.encode()).hexdigest()
            assert sig[len("FALLBACK_SIG:"):] == expected_hash[:32]

    def test_verify_success_with_public_key(self, signer, sample_content):
        # Use mock sign to produce signature
        signer._private_key = MagicMock()
        signer._private_key.sign.return_value = b"real_sig"
        signature = signer.sign(sample_content, "user")
        # Now verify
        with patch("domain.intent.cryptographic_signer.serialization.load_pem_public_key") as mock_load:
            mock_pub = MagicMock()
            mock_pub.verify.return_value = None
            mock_load.return_value = mock_pub
            result = signer.verify(sample_content, signature, public_key_pem="some_pem")
            assert result is True

    def test_verify_fallback_signature(self, signer, sample_content):
        content_hash = hashlib.sha3_256(sample_content.encode()).hexdigest()
        fallback_sig = f"FALLBACK_SIG:{content_hash[:32]}"
        result = signer.verify(sample_content, fallback_sig)
        assert result is True

        wrong_sig = f"FALLBACK_SIG:{'x'*32}"
        assert signer.verify(sample_content, wrong_sig) is False

    def test_verify_without_crypto_returns_true(self, signer, sample_content):
        with patch("domain.intent.cryptographic_signer.CRYPTO_AVAILABLE", False):
            # Non-fallback signature: should return True (assumed valid)
            result = signer.verify(sample_content, "some_signature")
            assert result is True

    def test_verify_failure_due_to_exception(self, signer, sample_content):
        signer._private_key = MagicMock()
        signer._private_key.sign.return_value = b"real_sig"
        signature = signer.sign(sample_content, "user")
        with patch("domain.intent.cryptographic_signer.serialization.load_pem_public_key") as mock_load:
            mock_pub = MagicMock()
            mock_pub.verify.side_effect = Exception("Invalid signature")
            mock_load.return_value = mock_pub
            result = signer.verify(sample_content, signature)
            assert result is False

    def test_sign_intent_data(self, signer, sample_data):
        with patch.object(signer, "sign", return_value="mocked_sig") as mock_sign:
            sig = signer.sign_intent_data(sample_data, "alice")
            assert sig == "mocked_sig"
            normalized = json.dumps(sample_data, sort_keys=True, default=str)
            mock_sign.assert_called_with(normalized, "alice")

    def test_sign_intent_data_not_dict_raises(self, signer):
        with pytest.raises(ValueError, match="data must be a dictionary"):
            signer.sign_intent_data(["not", "dict"], "user")

    def test_verify_intent_data(self, signer, sample_data):
        with patch.object(signer, "verify", return_value=True) as mock_verify:
            result = signer.verify_intent_data(sample_data, "sig")
            assert result is True
            normalized = json.dumps(sample_data, sort_keys=True, default=str)
            mock_verify.assert_called_with(normalized, "sig")

    def test_verify_intent_data_not_dict_returns_false(self, signer):
        result = signer.verify_intent_data("not dict", "sig")
        assert result is False

    def test_get_public_key(self, signer):
        signer._public_key_pem = "test_pem"
        assert signer.get_public_key() == "test_pem"

    def test_is_available(self, signer):
        with patch("domain.intent.cryptographic_signer.CRYPTO_AVAILABLE", True):
            signer._private_key = MagicMock()
            assert signer.is_available() is True
        signer._private_key = None
        assert signer.is_available() is False
        with patch("domain.intent.cryptographic_signer.CRYPTO_AVAILABLE", False):
            assert signer.is_available() is False

    def test_get_key_info(self, signer):
        info = signer.get_key_info()
        assert "crypto_available" in info
        assert "key_loaded" in info
        assert "public_key_available" in info
        assert "algorithm" in info
        assert info["algorithm"] == "RSASSA-PSS-SHA256"


# ----------------------------------------------------------------------
# Tests for fallback mode (cryptography unavailable)
# ----------------------------------------------------------------------
class TestCryptographicSignerFallback:
    @pytest.fixture(autouse=True)
    def mock_crypto_unavailable(self):
        with patch("domain.intent.cryptographic_signer.CRYPTO_AVAILABLE", False):
            with patch("domain.intent.cryptographic_signer.rsa", None):
                yield

    def test_init_fallback(self):
        signer = CryptographicSigner()
        CryptographicSigner._instance = None
        assert signer.is_available() is False
        assert signer._private_key is None
        assert signer._public_key_pem is None

    def test_load_private_key_fallback(self, signer):
        result = signer.load_private_key_from_pem("fake")
        assert result is False

    def test_sign_fallback(self, signer, sample_content):
        sig = signer.sign(sample_content, "user")
        assert sig.startswith("FALLBACK_SIG:")
        expected_hash = hashlib.sha3_256(sample_content.encode()).hexdigest()
        assert sig[len("FALLBACK_SIG:"):] == expected_hash[:32]

    def test_verify_fallback(self, signer, sample_content):
        content_hash = hashlib.sha3_256(sample_content.encode()).hexdigest()
        sig = f"FALLBACK_SIG:{content_hash[:32]}"
        assert signer.verify(sample_content, sig) is True
        wrong_sig = f"FALLBACK_SIG:{'a'*32}"
        assert signer.verify(sample_content, wrong_sig) is False
        # Non-fallback signature: assume valid
        assert signer.verify(sample_content, "non_fallback") is True

    def test_get_key_info_fallback(self, signer):
        info = signer.get_key_info()
        assert info["crypto_available"] is False
        assert info["key_loaded"] is False
        assert info["public_key_available"] is False
        assert info["algorithm"] == "FALLBACK_SHA3_256"


# ----------------------------------------------------------------------
# Tests for entity base methods (consistency)
# ----------------------------------------------------------------------
class TestCryptographicSignerEntityMethods:
    def test_create(self, signer):
        result = signer.create("user")
        assert result is signer

    def test_update(self, signer):
        result = signer.update("user", key="value")
        assert result is signer

    def test_delete(self, signer):
        result = signer.delete("user", "reason")
        assert result is signer

    def test_restore(self, signer):
        result = signer.restore("user")
        assert result is signer

    def test_activate(self, signer):
        result = signer.activate("user")
        assert result is signer

    def test_deactivate(self, signer):
        result = signer.deactivate("user", "reason")
        assert result is signer

    def test_lock(self, signer):
        result = signer.lock("user", "reason")
        assert result is signer

    def test_unlock(self, signer):
        result = signer.unlock("user")
        assert result is signer

    def test_validate(self, signer):
        with patch("domain.intent.cryptographic_signer.CRYPTO_AVAILABLE", True):
            signer._private_key = MagicMock()
            result = signer.validate()
            assert result["is_valid"] is True
            assert result["errors"] == []
        with patch("domain.intent.cryptographic_signer.CRYPTO_AVAILABLE", False):
            signer._private_key = None
            result = signer.validate()
            assert result["is_valid"] is False
            assert "Cryptographic signing not available" in result["errors"]

    def test_to_dict(self, signer):
        d = signer.to_dict()
        assert "crypto_available" in d

    def test_from_dict(self, signer):
        new_signer = CryptographicSigner.from_dict({})
        assert isinstance(new_signer, CryptographicSigner)

    def test_clone(self, signer):
        with patch("domain.intent.cryptographic_signer.CRYPTO_AVAILABLE", True):
            with patch("domain.intent.cryptographic_signer.rsa.generate_private_key") as mock_gen:
                mock_gen.return_value = MagicMock()
                cloned = signer.clone()
                assert cloned is not signer
                assert isinstance(cloned, CryptographicSigner)

    def test_snapshot(self, signer):
        snap = signer.snapshot()
        assert "crypto_available" in snap

    def test_version(self, signer):
        assert signer.version() == 1

    def test_audit_trail(self, signer):
        assert signer.audit_trail() == []

    def test_touch(self, signer):
        result = signer.touch("user")
        assert result is signer

    def test_reset(self, signer):
        with patch("domain.intent.cryptographic_signer.CRYPTO_AVAILABLE", True):
            with patch("domain.intent.cryptographic_signer.rsa.generate_private_key") as mock_gen:
                mock_gen.return_value = MagicMock()
                signer.reset()
                assert signer._private_key is not None
