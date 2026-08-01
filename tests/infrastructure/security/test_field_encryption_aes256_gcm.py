# tests/infrastructure/security/test_field_encryption_aes256_gcm.py
"""
Comprehensive tests for infrastructure/security/field_encryption_aes256_gcm.py
"""

import base64
import os
from unittest.mock import MagicMock, patch

import pytest

from infrastructure.security.field_encryption_aes256_gcm import (
    AES_KEY_SIZE,
    DEFAULT_KEY_ID,
    DecryptionError,
    FieldEncryptionError,
    FieldEncryptionService,
    KeyNotFoundError,
    get_field_encryption,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_key():
    # Generate a valid AES-256 key
    import secrets
    return secrets.token_bytes(AES_KEY_SIZE)


@pytest.fixture
def sample_key_b64(sample_key):
    return base64.b64encode(sample_key).decode()


@pytest.fixture
def service_with_keys(sample_key_b64):
    config = {
        "encryption": {
            "current_key_id": "test_key",
            "keys": {
                "test_key": {
                    "key": sample_key_b64,
                    "created_at": "2026-01-01T00:00:00",
                    "version": 1,
                }
            }
        }
    }
    with patch("infrastructure.security.field_encryption_aes256_gcm.load_yaml_config") as mock_load:
        mock_load.return_value = config
        service = FieldEncryptionService("dummy.yaml")
        return service


@pytest.fixture
def service_with_ephemeral():
    with patch("infrastructure.security.field_encryption_aes256_gcm.load_yaml_config") as mock_load:
        mock_load.return_value = {}
        # Ensure environment variable not set
        with patch.dict(os.environ, {}, clear=True):
            service = FieldEncryptionService("dummy.yaml")
            return service


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestExceptions:
    def test_field_encryption_error(self):
        with pytest.raises(FieldEncryptionError):
            raise FieldEncryptionError("test")

    def test_decryption_error(self):
        with pytest.raises(DecryptionError):
            raise DecryptionError("test")

    def test_key_not_found_error(self):
        with pytest.raises(KeyNotFoundError):
            raise KeyNotFoundError("key not found")


# ============================================================================
# Tests for FieldEncryptionService
# ============================================================================

class TestFieldEncryptionService:
    def test_initialization_with_config(self, sample_key_b64):
        config = {
            "encryption": {
                "current_key_id": "prod_key",
                "keys": {
                    "prod_key": {
                        "key": sample_key_b64,
                        "created_at": "2026-01-01T00:00:00",
                        "version": 2,
                    }
                }
            }
        }
        with patch("infrastructure.security.field_encryption_aes256_gcm.load_yaml_config") as mock_load:
            mock_load.return_value = config
            service = FieldEncryptionService("dummy.yaml")
            assert service._current_key_id == "prod_key"
            assert "prod_key" in service._keys
            assert service._key_meta["prod_key"]["version"] == 2

    def test_initialization_with_env_key(self, sample_key_b64):
        with patch("infrastructure.security.field_encryption_aes256_gcm.load_yaml_config") as mock_load:
            mock_load.return_value = {}
            with patch.dict(os.environ, {"ENCRYPTION_KEY": sample_key_b64}):
                service = FieldEncryptionService("dummy.yaml")
                assert DEFAULT_KEY_ID in service._keys
                assert service._current_key_id == DEFAULT_KEY_ID

    def test_initialization_no_keys_generates_ephemeral(self):
        with patch("infrastructure.security.field_encryption_aes256_gcm.load_yaml_config") as mock_load:
            mock_load.return_value = {}
            with patch.dict(os.environ, {}, clear=True):
                service = FieldEncryptionService("dummy.yaml")
                assert DEFAULT_KEY_ID in service._keys
                assert len(service._keys[DEFAULT_KEY_ID]) == AES_KEY_SIZE
                assert service._current_key_id == DEFAULT_KEY_ID

    def test_initialization_current_key_fallback(self, sample_key_b64):
        config = {
            "encryption": {
                "current_key_id": "nonexistent",
                "keys": {
                    "test_key": {"key": sample_key_b64}
                }
            }
        }
        with patch("infrastructure.security.field_encryption_aes256_gcm.load_yaml_config") as mock_load:
            mock_load.return_value = config
            service = FieldEncryptionService("dummy.yaml")
            # Should fallback to first available key
            assert service._current_key_id == "test_key"

    def test_initialization_config_load_failure(self):
        with patch("infrastructure.security.field_encryption_aes256_gcm.load_yaml_config") as mock_load:
            mock_load.side_effect = Exception("Config error")
            with patch.dict(os.environ, {}, clear=True):
                service = FieldEncryptionService("dummy.yaml")
                # Should still generate ephemeral key
                assert DEFAULT_KEY_ID in service._keys
                assert service._current_key_id == DEFAULT_KEY_ID

    # ---- _get_key ----
    def test_get_key_default(self, service_with_keys):
        key, key_id = service_with_keys._get_key()
        assert key_id == "test_key"
        assert key == service_with_keys._keys["test_key"]

    def test_get_key_specific(self, service_with_keys, sample_key_b64):
        # Add another key
        import secrets
        new_key = secrets.token_bytes(AES_KEY_SIZE)
        service_with_keys.add_key("another_key", new_key)
        key, key_id = service_with_keys._get_key("another_key")
        assert key_id == "another_key"
        assert key == new_key

    def test_get_key_not_found(self, service_with_keys):
        with pytest.raises(KeyNotFoundError, match="key_not_found"):
            service_with_keys._get_key("key_not_found")

    # ---- encrypt / decrypt ----
    def test_encrypt_decrypt_roundtrip(self, service_with_keys):
        plaintext = "Hello, World!"
        encrypted = service_with_keys.encrypt(plaintext)
        decrypted = service_with_keys.decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_decrypt_with_custom_key_id(self, service_with_keys, sample_key_b64):
        import secrets
        new_key = secrets.token_bytes(AES_KEY_SIZE)
        service_with_keys.add_key("custom_key", new_key)

        plaintext = "Secret data"
        encrypted = service_with_keys.encrypt(plaintext, key_id="custom_key")
        decrypted = service_with_keys.decrypt(encrypted)
        assert decrypted == plaintext
        # Check that key_id is in the encrypted string
        parts = encrypted.split("|")
        assert parts[1] == "custom_key"

    def test_encrypt_decrypt_with_aad(self, service_with_keys):
        plaintext = "Data with AAD"
        aad = b"additional_authenticated_data"
        encrypted = service_with_keys.encrypt(plaintext, aad=aad)
        decrypted = service_with_keys.decrypt(encrypted, aad=aad)
        assert decrypted == plaintext

    def test_encrypt_decrypt_wrong_aad_raises(self, service_with_keys):
        plaintext = "Data with AAD"
        aad1 = b"correct_aad"
        aad2 = b"wrong_aad"
        encrypted = service_with_keys.encrypt(plaintext, aad=aad1)
        with pytest.raises(DecryptionError):
            service_with_keys.decrypt(encrypted, aad=aad2)

    def test_encrypt_empty_string(self, service_with_keys):
        assert service_with_keys.encrypt("") == ""
        assert service_with_keys.decrypt("") == ""

    def test_decrypt_invalid_format_raises(self, service_with_keys):
        with pytest.raises(DecryptionError, match="Invalid encrypted data format"):
            service_with_keys.decrypt("invalid_format")

    def test_decrypt_unsupported_version_raises(self, service_with_keys):
        # Create a ciphertext with wrong version
        plaintext = "test"
        encrypted = service_with_keys.encrypt(plaintext)
        parts = encrypted.split("|")
        parts[0] = "v999"
        corrupted = "|".join(parts)
        with pytest.raises(DecryptionError, match="Unsupported version"):
            service_with_keys.decrypt(corrupted)

    def test_decrypt_wrong_key_raises(self, service_with_keys):
        plaintext = "test"
        encrypted = service_with_keys.encrypt(plaintext)
        # Create a new service with different key
        import secrets
        diff_service = FieldEncryptionService()
        diff_service._keys[DEFAULT_KEY_ID] = secrets.token_bytes(AES_KEY_SIZE)
        # The decrypt will fail because key mismatch
        with pytest.raises(DecryptionError):
            diff_service.decrypt(encrypted)

    def test_decrypt_corrupted_data_raises(self, service_with_keys):
        plaintext = "test"
        encrypted = service_with_keys.encrypt(plaintext)
        # Corrupt the ciphertext part
        parts = encrypted.split("|")
        parts[3] = parts[3][:-5] + "AAAAA"
        corrupted = "|".join(parts)
        with pytest.raises(DecryptionError):
            service_with_keys.decrypt(corrupted)

    def test_encrypt_uses_random_nonce_each_time(self, service_with_keys):
        plaintext = "same text"
        enc1 = service_with_keys.encrypt(plaintext)
        enc2 = service_with_keys.encrypt(plaintext)
        # Nonce is different, so ciphertext should differ
        assert enc1 != enc2

    # ---- deterministic encrypt / decrypt ----
    def test_encrypt_decrypt_deterministic_roundtrip(self, service_with_keys):
        plaintext = "Deterministic data"
        encrypted = service_with_keys.encrypt_deterministic(plaintext)
        decrypted = service_with_keys.decrypt_deterministic(encrypted)
        assert decrypted == plaintext

    def test_encrypt_deterministic_consistent(self, service_with_keys):
        plaintext = "same deterministic"
        enc1 = service_with_keys.encrypt_deterministic(plaintext)
        enc2 = service_with_keys.encrypt_deterministic(plaintext)
        assert enc1 == enc2

    def test_encrypt_deterministic_empty(self, service_with_keys):
        assert service_with_keys.encrypt_deterministic("") == ""
        assert service_with_keys.decrypt_deterministic("") == ""

    def test_decrypt_deterministic_with_aad(self, service_with_keys):
        plaintext = "test"
        aad = b"aad_data"
        encrypted = service_with_keys.encrypt_deterministic(plaintext)
        decrypted = service_with_keys.decrypt_deterministic(encrypted, aad=aad)
        assert decrypted == plaintext

    # ---- encrypt_json / decrypt_to_json ----
    def test_encrypt_decrypt_json(self, service_with_keys):
        data = {"user": "alice", "balance": 1000.5, "active": True}
        encrypted = service_with_keys.encrypt_json(data)
        decrypted = service_with_keys.decrypt_to_json(encrypted)
        assert decrypted == data

    def test_encrypt_json_empty_dict(self, service_with_keys):
        encrypted = service_with_keys.encrypt_json({})
        decrypted = service_with_keys.decrypt_to_json(encrypted)
        assert decrypted == {}

    def test_decrypt_json_invalid_data_raises(self, service_with_keys):
        # Encrypt a string that is not JSON
        encrypted = service_with_keys.encrypt("not json")
        with pytest.raises(json.JSONDecodeError):
            service_with_keys.decrypt_to_json(encrypted)

    # ---- add_key ----
    def test_add_key(self, service_with_keys):
        import secrets
        new_key = secrets.token_bytes(AES_KEY_SIZE)
        service_with_keys.add_key("new_key", new_key, version=3, created_at="2026-01-01T00:00:00")
        assert "new_key" in service_with_keys._keys
        assert service_with_keys._keys["new_key"] == new_key
        assert service_with_keys._key_meta["new_key"]["version"] == 3
        assert service_with_keys._key_meta["new_key"]["created_at"] == "2026-01-01T00:00:00"

    def test_add_key_default_created_at(self, service_with_keys):
        import secrets
        new_key = secrets.token_bytes(AES_KEY_SIZE)
        service_with_keys.add_key("another_key", new_key)
        assert "created_at" in service_with_keys._key_meta["another_key"]

    # ---- rotate_key ----
    def test_rotate_key(self, service_with_keys):
        old_id = service_with_keys._current_key_id
        old_keys_count = len(service_with_keys._keys)

        # Mock callback
        callback_mock = MagicMock()
        service_with_keys.set_rotation_callback(callback_mock)

        new_id = service_with_keys.rotate_key()

        assert new_id != old_id
        assert service_with_keys._current_key_id == new_id
        assert len(service_with_keys._keys) == old_keys_count + 1
        assert new_id in service_with_keys._keys
        # Version should be incremented
        old_version = service_with_keys._key_meta[old_id]["version"]
        new_version = service_with_keys._key_meta[new_id]["version"]
        assert new_version == old_version + 1
        # Callback should be called
        callback_mock.assert_called_once_with(old_id, new_id)

    def test_rotate_key_with_custom_id(self, service_with_keys):
        custom_id = "my_custom_key"
        new_id = service_with_keys.rotate_key(new_key_id=custom_id)
        assert new_id == custom_id
        assert service_with_keys._current_key_id == custom_id

    def test_rotate_key_without_callback(self, service_with_keys):
        new_id = service_with_keys.rotate_key()
        assert service_with_keys._current_key_id == new_id

    # ---- set_rotation_callback ----
    def test_set_rotation_callback(self, service_with_keys):
        def callback(old, new):
            pass
        service_with_keys.set_rotation_callback(callback)
        assert service_with_keys._rotation_callback is callback

    # ---- get_current_key_id ----
    def test_get_current_key_id(self, service_with_keys):
        assert service_with_keys.get_current_key_id() == "test_key"
        # After rotation
        service_with_keys.rotate_key()
        assert service_with_keys.get_current_key_id() == service_with_keys._current_key_id

    # ---- get_key_ids ----
    def test_get_key_ids(self, service_with_keys):
        ids = service_with_keys.get_key_ids()
        assert "test_key" in ids
        assert len(ids) == 1
        # Add another key
        import secrets
        service_with_keys.add_key("another", secrets.token_bytes(AES_KEY_SIZE))
        ids2 = service_with_keys.get_key_ids()
        assert "another" in ids2
        assert len(ids2) == 2

    # ---- get_key_info ----
    def test_get_key_info(self, service_with_keys):
        info = service_with_keys.get_key_info("test_key")
        assert "created_at" in info
        assert "version" in info
        # Non-existent key
        info2 = service_with_keys.get_key_info("nonexistent")
        assert info2 == {}


# ============================================================================
# Tests for Singleton Accessor
# ============================================================================

class TestSingleton:
    def test_get_field_encryption(self):
        with patch("infrastructure.security.field_encryption_aes256_gcm.FieldEncryptionService") as MockService:
            mock_instance = MagicMock()
            MockService.return_value = mock_instance
            # Reset global
            import infrastructure.security.field_encryption_aes256_gcm as module
            module._field_encryption = None

            s1 = get_field_encryption()
            s2 = get_field_encryption()
            assert s1 is s2
            assert MockService.call_count == 1


# ============================================================================
# Integration Tests (real encryption/decryption)
# ============================================================================

class TestIntegration:
    def test_full_encryption_workflow(self):
        # Use service with ephemeral key
        service = FieldEncryptionService()
        # Test encrypt/decrypt cycle
        test_cases = [
            ("Hello, World!", None),
            ("", None),
            ("Data with AAD", b"my_aad"),
            ("Long string" * 100, b"another_aad"),
            ("Special chars: !@#$%^&*()", None),
            ("Unicode: 你好, 世界", None),
        ]
        for plaintext, aad in test_cases:
            encrypted = service.encrypt(plaintext, aad=aad)
            decrypted = service.decrypt(encrypted, aad=aad)
            assert decrypted == plaintext

    def test_deterministic_consistency(self):
        service = FieldEncryptionService()
        plaintext = "consistent data"
        enc1 = service.encrypt_deterministic(plaintext)
        enc2 = service.encrypt_deterministic(plaintext)
        assert enc1 == enc2
        # Decrypt
        dec = service.decrypt_deterministic(enc1)
        assert dec == plaintext

    def test_rotation_preserves_decryption(self):
        service = FieldEncryptionService()
        # Encrypt with default key
        plaintext = "Pre-rotation data"
        encrypted = service.encrypt(plaintext)

        # Rotate
        service.rotate_key()

        # Should still decrypt with old data (old key preserved)
        decrypted = service.decrypt(encrypted)
        assert decrypted == plaintext

        # New encryption uses new key
        new_plaintext = "Post-rotation data"
        new_encrypted = service.encrypt(new_plaintext)
        assert new_encrypted.split("|")[1] == service.get_current_key_id()

        # Decrypt new data
        assert service.decrypt(new_encrypted) == new_plaintext

    def test_key_not_found_on_decryption(self):
        service = FieldEncryptionService()
        # Encrypt with default key
        plaintext = "test"
        encrypted = service.encrypt(plaintext)
        # Manually change key_id in ciphertext to non-existent
        parts = encrypted.split("|")
        parts[1] = "nonexistent_key"
        corrupted = "|".join(parts)
        with pytest.raises(KeyNotFoundError, match="nonexistent_key"):
            service.decrypt(corrupted)
