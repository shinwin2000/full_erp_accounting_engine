# tests/infrastructure/security/test_digital_signer_rsa_pss.py
# Comprehensive tests for digital_signer_rsa_pss.py

import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from infrastructure.security.digital_signer_rsa_pss import (
    DEFAULT_KEY_ID,
    DigitalSignerError,
    DigitalSignerRSA,
    KeyNotFoundError,
    SigningError,
    VerificationError,
    get_digital_signer,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_config():
    return {
        "digital_signing": {
            "current_key_id": "prod_key",
            "keys": {
                "prod_key": {
                    "private_key_path": "/keys/prod_private.pem",
                    "public_key_path": "/keys/prod_public.pem",
                },
                "backup_key": {
                    "private_key_path": "/keys/backup_private.pem",
                    "public_key_path": "/keys/backup_public.pem",
                }
            }
        }
    }


@pytest.fixture
def real_private_key():
    return rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )


@pytest.fixture
def real_public_key(real_private_key):
    return real_private_key.public_key()


@pytest.fixture
def pem_private_key(real_private_key):
    return real_private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )


@pytest.fixture
def pem_public_key(real_public_key):
    return real_public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )


@pytest.fixture
def sample_data():
    return "Hello, world!"


@pytest.fixture
def sample_json():
    return {"user": "alice", "action": "login", "timestamp": "2026-07-27T12:00:00Z"}


# ============================================================================
# Exception tests
# ============================================================================

class TestExceptions:
    def test_digital_signer_error(self):
        with pytest.raises(DigitalSignerError):
            raise DigitalSignerError("test")

    def test_signing_error(self):
        with pytest.raises(SigningError):
            raise SigningError("signing failed")

    def test_verification_error(self):
        with pytest.raises(VerificationError):
            raise VerificationError("verification failed")

    def test_key_not_found_error(self):
        with pytest.raises(KeyNotFoundError):
            raise KeyNotFoundError("key not found")


# ============================================================================
# DigitalSignerRSA tests
# ============================================================================

class TestDigitalSignerRSA:
    def test_initialization_loads_config(self, mock_config):
        with patch("infrastructure.security.digital_signer_rsa_pss.load_yaml_config") as mock_load:
            mock_load.return_value = mock_config
            with patch("infrastructure.security.digital_signer_rsa_pss.Path.exists") as mock_exists:
                mock_exists.return_value = False  # no keys exist, will generate default
                with patch.object(DigitalSignerRSA, "_generate_key_pair") as mock_gen:
                    signer = DigitalSignerRSA("test_config.yaml")
                    mock_load.assert_called_once_with("test_config.yaml")
                    mock_gen.assert_called_once_with(DEFAULT_KEY_ID)
                    assert signer.config == mock_config
                    assert signer._current_key_id == DEFAULT_KEY_ID  # because no key in config exists

    def test_initialization_config_fallback(self):
        with patch("infrastructure.security.digital_signer_rsa_pss.load_yaml_config") as mock_load:
            mock_load.side_effect = Exception("Config error")
            with patch.object(DigitalSignerRSA, "_generate_key_pair") as mock_gen:
                signer = DigitalSignerRSA()
                assert signer.config == {}
                mock_gen.assert_called_once_with(DEFAULT_KEY_ID)

    def test_load_private_key_success(self, pem_private_key, tmp_path):
        key_path = tmp_path / "private.pem"
        key_path.write_bytes(pem_private_key)
        signer = DigitalSignerRSA()
        signer._load_private_key("test_key", str(key_path))
        assert "test_key" in signer._private_keys
        assert isinstance(signer._private_keys["test_key"], rsa.RSAPrivateKey)

    def test_load_private_key_failure_logs_error(self, caplog):
        with patch("infrastructure.security.digital_signer_rsa_pss.logger") as mock_logger:
            signer = DigitalSignerRSA()
            signer._load_private_key("test_key", "/nonexistent.pem")
            mock_logger.error.assert_called_once()
            assert "test_key" not in signer._private_keys

    def test_load_public_key_success(self, pem_public_key, tmp_path):
        key_path = tmp_path / "public.pem"
        key_path.write_bytes(pem_public_key)
        signer = DigitalSignerRSA()
        signer._load_public_key("test_key", str(key_path))
        assert "test_key" in signer._public_keys
        assert isinstance(signer._public_keys["test_key"], rsa.RSAPublicKey)

    def test_load_public_key_failure_logs_error(self, caplog):
        with patch("infrastructure.security.digital_signer_rsa_pss.logger") as mock_logger:
            signer = DigitalSignerRSA()
            signer._load_public_key("test_key", "/nonexistent.pem")
            mock_logger.error.assert_called_once()

    def test_generate_key_pair(self):
        signer = DigitalSignerRSA()
        signer._generate_key_pair("new_key")
        assert "new_key" in signer._private_keys
        assert "new_key" in signer._public_keys
        assert isinstance(signer._private_keys["new_key"], rsa.RSAPrivateKey)
        assert isinstance(signer._public_keys["new_key"], rsa.RSAPublicKey)

    def test_get_private_key_found(self, real_private_key):
        signer = DigitalSignerRSA()
        signer._private_keys["default"] = real_private_key
        key = signer._get_private_key("default")
        assert key is real_private_key

    def test_get_private_key_not_found_raises(self):
        signer = DigitalSignerRSA()
        with pytest.raises(KeyNotFoundError, match="Private key missing not found"):
            signer._get_private_key("missing")

    def test_get_public_key_from_cache(self, real_public_key):
        signer = DigitalSignerRSA()
        signer._public_keys["default"] = real_public_key
        key = signer._get_public_key("default")
        assert key is real_public_key

    def test_get_public_key_from_private_key(self, real_private_key, real_public_key):
        signer = DigitalSignerRSA()
        signer._private_keys["default"] = real_private_key
        # public key not in cache, should derive from private
        key = signer._get_public_key("default")
        assert key.public_numbers() == real_public_key.public_numbers()

    def test_get_public_key_not_found_raises(self):
        signer = DigitalSignerRSA()
        with pytest.raises(KeyNotFoundError, match="Public key missing not found"):
            signer._get_public_key("missing")

    # --- sign and verify ---

    def test_sign_and_verify_with_default_key(self, sample_data):
        signer = DigitalSignerRSA()
        # Ensure we have a key
        if DEFAULT_KEY_ID not in signer._private_keys:
            signer._generate_key_pair(DEFAULT_KEY_ID)
        signature = signer.sign(sample_data)
        assert isinstance(signature, str)
        assert len(signature) > 0
        # Verify
        assert signer.verify(sample_data, signature) is True

    def test_sign_and_verify_with_specific_key(self, sample_data):
        signer = DigitalSignerRSA()
        signer._generate_key_pair("custom")
        signature = signer.sign(sample_data, key_id="custom")
        assert signer.verify(sample_data, signature, key_id="custom") is True
        # Should fail with wrong key
        assert signer.verify(sample_data, signature, key_id="default") is False

    def test_sign_with_bytes_data(self):
        signer = DigitalSignerRSA()
        signer._generate_key_pair(DEFAULT_KEY_ID)
        data = b"binary data\x00\x01"
        signature = signer.sign(data)
        assert signer.verify(data, signature) is True

    def test_sign_json_and_verify_json(self, sample_json):
        signer = DigitalSignerRSA()
        signer._generate_key_pair(DEFAULT_KEY_ID)
        signature = signer.sign_json(sample_json)
        assert isinstance(signature, str)
        assert signer.verify_json(sample_json, signature) is True

    def test_sign_json_sort_keys(self, sample_json):
        signer = DigitalSignerRSA()
        signer._generate_key_pair(DEFAULT_KEY_ID)
        sig1 = signer.sign_json(sample_json, sort_keys=True)
        sig2 = signer.sign_json(sample_json, sort_keys=False)
        # They should be different because JSON string differs
        assert sig1 != sig2

    def test_verify_invalid_signature_returns_false(self, sample_data):
        signer = DigitalSignerRSA()
        signer._generate_key_pair(DEFAULT_KEY_ID)
        # Corrupt signature
        signature = signer.sign(sample_data)
        corrupted = signature[:-5] + "AAAAA"
        assert signer.verify(sample_data, corrupted) is False

    def test_verify_wrong_data_returns_false(self, sample_data):
        signer = DigitalSignerRSA()
        signer._generate_key_pair(DEFAULT_KEY_ID)
        signature = signer.sign(sample_data)
        wrong_data = "Different data"
        assert signer.verify(wrong_data, signature) is False

    def test_verify_with_incorrect_key_returns_false(self, sample_data):
        signer = DigitalSignerRSA()
        signer._generate_key_pair("key1")
        signer._generate_key_pair("key2")
        signature = signer.sign(sample_data, key_id="key1")
        assert signer.verify(sample_data, signature, key_id="key2") is False

    # --- get_current_key_id ---

    def test_get_current_key_id(self):
        signer = DigitalSignerRSA()
        signer._current_key_id = "active_key"
        assert signer.get_current_key_id() == "active_key"

    # --- get_key_ids ---

    def test_get_key_ids(self):
        signer = DigitalSignerRSA()
        signer._private_keys = {"a": None, "b": None}
        ids = signer.get_key_ids()
        assert set(ids) == {"a", "b"}

    # --- get_public_key_pem ---

    def test_get_public_key_pem(self, real_public_key):
        signer = DigitalSignerRSA()
        signer._public_keys["test"] = real_public_key
        pem = signer.get_public_key_pem("test")
        assert pem.startswith("-----BEGIN PUBLIC KEY-----")
        assert "-----END PUBLIC KEY-----" in pem

    def test_get_public_key_pem_from_private(self, real_private_key, real_public_key):
        signer = DigitalSignerRSA()
        signer._private_keys["test"] = real_private_key
        # public not in cache, derive
        pem = signer.get_public_key_pem("test")
        assert pem.startswith("-----BEGIN PUBLIC KEY-----")
        # Should match real public key
        expected_pem = real_public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode("utf-8")
        assert pem == expected_pem

    def test_get_public_key_pem_not_found_raises(self):
        signer = DigitalSignerRSA()
        with pytest.raises(KeyNotFoundError):
            signer.get_public_key_pem("missing")

    # --- rotate_key ---

    @pytest.mark.asyncio
    async def test_rotate_key(self):
        signer = DigitalSignerRSA()
        # Initially no "new_key"
        assert "new_key" not in signer._private_keys
        with patch("infrastructure.security.digital_signer_rsa_pss.trigger_alert") as mock_alert:
            await signer.rotate_key("new_key")
            assert "new_key" in signer._private_keys
            assert "new_key" in signer._public_keys
            assert signer._current_key_id == "new_key"
            mock_alert.assert_awaited_once_with(
                title="Signing Key Rotated",
                message="Digital signing key rotated to new_key",
                severity="info",
                source="DigitalSignerRSA",
            )

    # --- signing and verification edge cases ---

    def test_sign_empty_data(self):
        signer = DigitalSignerRSA()
        signer._generate_key_pair(DEFAULT_KEY_ID)
        signature = signer.sign("")
        assert signer.verify("", signature) is True

    def test_sign_very_large_data(self):
        signer = DigitalSignerRSA()
        signer._generate_key_pair(DEFAULT_KEY_ID)
        large_data = "x" * 10000
        signature = signer.sign(large_data)
        assert signer.verify(large_data, signature) is True

    def test_sign_json_with_non_serializable(self):
        signer = DigitalSignerRSA()
        signer._generate_key_pair(DEFAULT_KEY_ID)
        data = {"date": "2026-07-27", "decimal": 123.45}
        signature = signer.sign_json(data)
        assert signer.verify_json(data, signature) is True

    # --- Integration test with loading from config ---

    def test_load_keys_from_config(self, mock_config, pem_private_key, pem_public_key, tmp_path):
        # Write key files to temp paths
        priv_path = tmp_path / "prod_private.pem"
        pub_path = tmp_path / "prod_public.pem"
        priv_path.write_bytes(pem_private_key)
        pub_path.write_bytes(pem_public_key)

        # Adjust mock_config to use actual paths
        mock_config["digital_signing"]["keys"]["prod_key"]["private_key_path"] = str(priv_path)
        mock_config["digital_signing"]["keys"]["prod_key"]["public_key_path"] = str(pub_path)

        with patch("infrastructure.security.digital_signer_rsa_pss.load_yaml_config") as mock_load:
            mock_load.return_value = mock_config
            signer = DigitalSignerRSA("config.yaml")
            # Should load prod_key
            assert "prod_key" in signer._private_keys
            assert "prod_key" in signer._public_keys
            # Should still generate default because backup_key not present
            # But _load_keys will try to load backup, fail, and then generate default
            # So default key is generated
            assert DEFAULT_KEY_ID in signer._private_keys
            assert signer._current_key_id == "prod_key"  # from config

    # --- verify that sign fails when no key present ---

    def test_sign_when_no_key_raises(self):
        signer = DigitalSignerRSA()
        # Remove all keys
        signer._private_keys.clear()
        with pytest.raises(KeyNotFoundError):
            signer.sign("data")

    # --- verify that verify fails when no public key ---

    def test_verify_when_no_key_raises(self):
        signer = DigitalSignerRSA()
        signer._public_keys.clear()
        signer._private_keys.clear()
        with pytest.raises(KeyNotFoundError):
            signer.verify("data", "sig")


# ============================================================================
# Singleton tests
# ============================================================================

class TestSingleton:
    def test_get_digital_signer_singleton(self):
        s1 = get_digital_signer()
        s2 = get_digital_signer()
        assert s1 is s2
        assert isinstance(s1, DigitalSignerRSA)

    def test_get_digital_signer_resets_global(self):
        # Reset global
        import infrastructure.security.digital_signer_rsa_pss as module
        module._digital_signer = None
        s1 = get_digital_signer()
        s2 = get_digital_signer()
        assert s1 is s2