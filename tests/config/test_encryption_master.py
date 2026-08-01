# tests/config/test_encryption_master.py
"""
Comprehensive tests for config/encryption_master.py
Covers all classes and methods with proper mocking and assertions.
"""

import base64
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from config.encryption_master import (
    ENCRYPTED_PREFIX,
    EncryptedValue,
    EncryptionKey,
    EncryptionMaster,
    decrypt_config_value,
    encrypt_config_value,
    get_encryption_master,
    process_encrypted_config,
)
from config.exceptions import ConfigEncryptionError

# ============================================================================
# Test EncryptedValue
# ============================================================================

class TestEncryptedValue:
    def test_construction_valid(self):
        ciphertext = b"cipher"
        nonce = b"x" * 12
        salt = b"y" * 16
        key_id = "key1"
        now = datetime.now(UTC)
        ev = EncryptedValue(
            ciphertext=ciphertext,
            nonce=nonce,
            salt=salt,
            key_id=key_id,
            encrypted_at=now,
        )
        assert ev.ciphertext == ciphertext
        assert ev.nonce == nonce
        assert ev.salt == salt
        assert ev.key_id == key_id
        assert ev.encrypted_at == now
        assert ev._version == 1
        assert ev._value_id is not None
        assert len(ev._snapshots) == 1

    def test_validation_ciphertext_required(self):
        with pytest.raises(ValueError, match="ciphertext is required"):
            EncryptedValue(
                ciphertext=b"",
                nonce=b"x" * 12,
                salt=b"y" * 16,
                key_id="key1",
                encrypted_at=datetime.now(UTC),
            )

    def test_validation_nonce_length(self):
        with pytest.raises(ValueError, match="nonce must be 12 bytes"):
            EncryptedValue(
                ciphertext=b"c",
                nonce=b"short",
                salt=b"y" * 16,
                key_id="key1",
                encrypted_at=datetime.now(UTC),
            )

    def test_validation_salt_length(self):
        with pytest.raises(ValueError, match="salt must be 16 bytes"):
            EncryptedValue(
                ciphertext=b"c",
                nonce=b"x" * 12,
                salt=b"short",
                key_id="key1",
                encrypted_at=datetime.now(UTC),
            )

    def test_validation_key_id_required(self):
        with pytest.raises(ValueError, match="key_id is required"):
            EncryptedValue(
                ciphertext=b"c",
                nonce=b"x" * 12,
                salt=b"y" * 16,
                key_id="",
                encrypted_at=datetime.now(UTC),
            )

    def test_validation_timezone_aware(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        ev = EncryptedValue(
            ciphertext=b"c",
            nonce=b"x" * 12,
            salt=b"y" * 16,
            key_id="k1",
            encrypted_at=naive,
        )
        assert ev.encrypted_at.tzinfo == UTC
        assert ev.encrypted_at != naive  # tz added

    def test_to_dict(self):
        ev = EncryptedValue(
            ciphertext=b"test",
            nonce=b"x" * 12,
            salt=b"y" * 16,
            key_id="k1",
            encrypted_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        )
        d = ev.to_dict()
        assert d["value_id"] == ev._value_id
        assert d["ciphertext"] == base64.b64encode(b"test").decode()
        assert d["nonce"] == base64.b64encode(b"x" * 12).decode()
        assert d["salt"] == base64.b64encode(b"y" * 16).decode()
        assert d["key_id"] == "k1"
        assert d["encrypted_at"] == "2026-01-01T12:00:00+00:00"
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "value_id": "vid123",
            "ciphertext": base64.b64encode(b"test").decode(),
            "nonce": base64.b64encode(b"x" * 12).decode(),
            "salt": base64.b64encode(b"y" * 16).decode(),
            "key_id": "k1",
            "encrypted_at": "2026-01-01T12:00:00+00:00",
            "version": 3,
        }
        ev = EncryptedValue.from_dict(data)
        assert ev._value_id == "vid123"
        assert ev.ciphertext == b"test"
        assert ev.nonce == b"x" * 12
        assert ev.salt == b"y" * 16
        assert ev.key_id == "k1"
        assert ev.encrypted_at == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        assert ev._version == 3

    def test_to_string_and_from_string(self):
        ev = EncryptedValue(
            ciphertext=b"test",
            nonce=b"x" * 12,
            salt=b"y" * 16,
            key_id="k1",
            encrypted_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        )
        s = ev.to_string()
        assert s.startswith(ENCRYPTED_PREFIX)

        parsed = EncryptedValue.from_string(s)
        assert parsed is not None
        assert parsed.ciphertext == b"test"
        assert parsed.nonce == b"x" * 12
        assert parsed.salt == b"y" * 16
        assert parsed.key_id == "k1"
        assert parsed.encrypted_at == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_from_string_not_encrypted(self):
        result = EncryptedValue.from_string("plain")
        assert result is None

    def test_from_string_invalid(self):
        with patch('config.encryption_master.logger') as mock_log:
            result = EncryptedValue.from_string(ENCRYPTED_PREFIX + "invalid")
            assert result is None
            mock_log.error.assert_called()

    def test_clone(self):
        ev = EncryptedValue(
            ciphertext=b"test",
            nonce=b"x" * 12,
            salt=b"y" * 16,
            key_id="k1",
            encrypted_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        )
        cloned = ev.clone()
        assert cloned is not ev
        assert cloned.ciphertext == ev.ciphertext
        assert cloned.nonce == ev.nonce
        assert cloned.salt == ev.salt
        assert cloned.key_id == ev.key_id
        assert cloned._version == ev._version + 1
        assert cloned._value_id != ev._value_id
        assert len(cloned._audit_trail) == 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self):
        ev = EncryptedValue(
            ciphertext=b"test",
            nonce=b"x" * 12,
            salt=b"y" * 16,
            key_id="k1",
            encrypted_at=datetime.now(UTC),
        )
        snap = ev.snapshot()
        assert snap["version"] == 1
        assert snap["value_id"] == ev._value_id
        assert snap["key_id"] == "k1"
        assert "timestamp" in snap

    def test_version(self):
        ev = EncryptedValue(
            ciphertext=b"test",
            nonce=b"x" * 12,
            salt=b"y" * 16,
            key_id="k1",
            encrypted_at=datetime.now(UTC),
        )
        assert ev.version() == 1
        ev._version = 5
        assert ev.version() == 5

    def test_audit_trail(self):
        ev = EncryptedValue(
            ciphertext=b"test",
            nonce=b"x" * 12,
            salt=b"y" * 16,
            key_id="k1",
            encrypted_at=datetime.now(UTC),
        )
        ev._record_audit("A1", "u1", {})
        ev._record_audit("A2", "u2", {})
        trail = ev.audit_trail()
        assert len(trail) == 2
        assert trail[0]["action"] == "A1"
        limited = ev.audit_trail(limit=1)
        assert len(limited) == 1
        assert limited[0]["action"] == "A2"

    def test_touch(self):
        ev = EncryptedValue(
            ciphertext=b"test",
            nonce=b"x" * 12,
            salt=b"y" * 16,
            key_id="k1",
            encrypted_at=datetime.now(UTC),
        )
        initial = ev.version()
        result = ev.touch("tester")
        assert result is ev
        assert ev.version() == initial + 1
        trail = ev.audit_trail()
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "tester"


# ============================================================================
# Test EncryptionKey
# ============================================================================

class TestEncryptionKey:
    def test_construction_valid(self):
        key_material = b"x" * 32
        now = datetime.now(UTC)
        key = EncryptionKey(
            key_id="k1",
            key_material=key_material,
            expires_at=now + timedelta(days=30),
            is_active=True,
            created_at=now,
            version=1,
        )
        assert key.key_id == "k1"
        assert key.key_material == key_material
        assert key.expires_at == now + timedelta(days=30)
        assert key.is_active is True
        assert key.created_at == now
        assert key.version == 1
        assert key._key_uid is not None
        assert len(key._snapshots) == 1

    def test_validation_key_id_required(self):
        with pytest.raises(ValueError, match="key_id is required"):
            EncryptionKey(
                key_id="",
                key_material=b"x" * 32,
                expires_at=None,
                is_active=True,
            )

    def test_validation_key_material_length(self):
        with pytest.raises(ValueError, match="key_material must be 32 bytes"):
            EncryptionKey(
                key_id="k1",
                key_material=b"short",
                expires_at=None,
                is_active=True,
            )

    def test_validation_timezone_aware(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        key = EncryptionKey(
            key_id="k1",
            key_material=b"x" * 32,
            expires_at=naive,
            is_active=True,
            created_at=naive,
        )
        assert key.expires_at.tzinfo == UTC
        assert key.created_at.tzinfo == UTC

    def test_is_expired(self):
        future = datetime.now(UTC) + timedelta(days=30)
        key = EncryptionKey(
            key_id="k1",
            key_material=b"x" * 32,
            expires_at=future,
            is_active=True,
        )
        assert key.is_expired() is False

        past = datetime.now(UTC) - timedelta(days=1)
        key2 = EncryptionKey(
            key_id="k2",
            key_material=b"x" * 32,
            expires_at=past,
            is_active=True,
        )
        assert key2.is_expired() is True

        key3 = EncryptionKey(
            key_id="k3",
            key_material=b"x" * 32,
            expires_at=None,
            is_active=True,
        )
        assert key3.is_expired() is False

    def test_can_encrypt(self):
        key = EncryptionKey(
            key_id="k1",
            key_material=b"x" * 32,
            expires_at=None,
            is_active=True,
        )
        assert key.can_encrypt() is True

        key2 = EncryptionKey(
            key_id="k2",
            key_material=b"x" * 32,
            expires_at=None,
            is_active=False,
        )
        assert key2.can_encrypt() is False

        past = datetime.now(UTC) - timedelta(days=1)
        key3 = EncryptionKey(
            key_id="k3",
            key_material=b"x" * 32,
            expires_at=past,
            is_active=True,
        )
        assert key3.can_encrypt() is False

    def test_can_decrypt(self):
        key = EncryptionKey(
            key_id="k1",
            key_material=b"x" * 32,
            expires_at=None,
            is_active=True,
        )
        assert key.can_decrypt() is True

        past = datetime.now(UTC) - timedelta(days=1)
        key2 = EncryptionKey(
            key_id="k2",
            key_material=b"x" * 32,
            expires_at=past,
            is_active=True,
        )
        assert key2.can_decrypt() is False

        key3 = EncryptionKey(
            key_id="k3",
            key_material=b"x" * 32,
            expires_at=None,
            is_active=False,
        )
        # can_decrypt only checks expiry, not active
        assert key3.can_decrypt() is True

    def test_to_dict(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        key = EncryptionKey(
            key_id="k1",
            key_material=b"x" * 32,
            expires_at=now + timedelta(days=30),
            is_active=True,
            created_at=now,
            version=2,
        )
        d = key.to_dict()
        assert d["key_uid"] == key._key_uid
        assert d["key_id"] == "k1"
        assert d["expires_at"] == (now + timedelta(days=30)).isoformat()
        assert d["is_active"] is True
        assert d["created_at"] == now.isoformat()
        assert d["version"] == 2

    def test_from_dict(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        data = {
            "key_uid": "uid123",
            "key_id": "k1",
            "expires_at": (now + timedelta(days=30)).isoformat(),
            "is_active": True,
            "created_at": now.isoformat(),
            "version": 3,
        }
        key_material = b"x" * 32
        key = EncryptionKey.from_dict(data, key_material)
        assert key._key_uid == "uid123"
        assert key.key_id == "k1"
        assert key.key_material == key_material
        assert key.expires_at == now + timedelta(days=30)
        assert key.is_active is True
        assert key.created_at == now
        assert key.version == 3

    def test_clone(self):
        key = EncryptionKey(
            key_id="k1",
            key_material=b"x" * 32,
            expires_at=None,
            is_active=True,
            version=1,
        )
        cloned = key.clone()
        assert cloned is not key
        assert cloned.key_id == key.key_id
        assert cloned.key_material == key.key_material
        assert cloned.expires_at == key.expires_at
        assert cloned.is_active == key.is_active
        assert cloned.version == key.version + 1
        assert len(cloned._audit_trail) == 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self):
        key = EncryptionKey(
            key_id="k1",
            key_material=b"x" * 32,
            expires_at=None,
            is_active=True,
        )
        snap = key.snapshot()
        assert snap["version"] == 1
        assert snap["key_uid"] == key._key_uid
        assert snap["key_id"] == "k1"
        assert snap["is_active"] is True
        assert "timestamp" in snap

    def test_audit_trail(self):
        key = EncryptionKey(
            key_id="k1",
            key_material=b"x" * 32,
            expires_at=None,
            is_active=True,
        )
        key._record_audit("A1", "u1", {})
        key._record_audit("A2", "u2", {})
        trail = key.audit_trail()
        assert len(trail) == 2
        assert trail[0]["action"] == "A1"

    def test_touch(self):
        key = EncryptionKey(
            key_id="k1",
            key_material=b"x" * 32,
            expires_at=None,
            is_active=True,
        )
        initial = key.version
        result = key.touch("tester")
        assert result is key
        assert key.version == initial + 1
        trail = key.audit_trail()
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "tester"


# ============================================================================
# Test EncryptionMaster
# ============================================================================

class TestEncryptionMaster:
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        EncryptionMaster._instance = None
        yield
        EncryptionMaster._instance = None

    @pytest.fixture
    def master(self):
        # Use a fresh instance with mocked crypto to avoid actual encryption
        with patch('config.encryption_master.CRYPTO_AVAILABLE', True), \
             patch('config.encryption_master.secrets.token_bytes') as mock_token, \
             patch('config.encryption_master.PBKDF2') as mock_kdf, \
             patch('config.encryption_master.AESGCM') as mock_aesgcm, \
             patch('config.encryption_master.os.environ', {}):
            # Mock token_bytes to return predictable bytes
            mock_token.return_value = b"x" * 32
            # Mock KDF derive
            mock_kdf_instance = MagicMock()
            mock_kdf_instance.derive.return_value = b"y" * 32
            mock_kdf.return_value = mock_kdf_instance
            # Mock AESGCM
            mock_aesgcm_instance = MagicMock()
            mock_aesgcm_instance.encrypt.return_value = b"ciphertext"
            mock_aesgcm.return_value = mock_aesgcm_instance
            master = EncryptionMaster()
            return master

    def test_singleton(self):
        m1 = EncryptionMaster()
        m2 = EncryptionMaster()
        assert m1 is m2

    # ---- _init_default_key ----
    def test_init_default_key_from_env(self):
        env_key = base64.b64encode(b"x" * 32).decode()
        with patch('config.encryption_master.os.environ', {'CONFIG_ENCRYPTION_KEY': env_key}), \
             patch('config.encryption_master.CRYPTO_AVAILABLE', True), \
             patch('config.encryption_master.secrets.token_bytes') as mock_token:
            mock_token.return_value = b"y" * 32  # should not be used
            master = EncryptionMaster()
            assert "default" in master._keys
            key = master._keys["default"]
            assert key.key_material == b"x" * 32
            assert key.is_active is True
            assert master._current_key_id == "default"
            mock_token.assert_not_called()

    def test_init_default_key_from_env_invalid(self):
        env_key = "invalid-base64"
        with patch('config.encryption_master.os.environ', {'CONFIG_ENCRYPTION_KEY': env_key}), \
             patch('config.encryption_master.CRYPTO_AVAILABLE', True), \
             patch('config.encryption_master.secrets.token_bytes') as mock_token:
            mock_token.return_value = b"z" * 32
            master = EncryptionMaster()
            assert "default" in master._keys
            key = master._keys["default"]
            assert key.key_material == b"z" * 32
            mock_token.assert_called_once()

    def test_init_default_key_fallback(self):
        with patch('config.encryption_master.os.environ', {}), \
             patch('config.encryption_master.CRYPTO_AVAILABLE', True), \
             patch('config.encryption_master.secrets.token_bytes') as mock_token:
            mock_token.return_value = b"z" * 32
            master = EncryptionMaster()
            assert "default" in master._keys
            key = master._keys["default"]
            assert key.key_material == b"z" * 32
            mock_token.assert_called_once()

    # ---- _add_key ----
    def test_add_key(self, master):
        key_id = "new_key"
        key_material = b"a" * 32
        key = master._add_key(key_id, key_material, is_active=True)
        assert key_id in master._keys
        assert master._keys[key_id] is key
        assert master._current_key_id == key_id
        assert key.key_material == key_material
        assert key.is_active is True

    def test_add_key_inactive(self, master):
        key_id = "inactive"
        master._add_key(key_id, b"a" * 32, is_active=False)
        assert key_id in master._keys
        assert master._current_key_id != key_id  # active key unchanged

    # ---- rotate_key ----
    def test_rotate_key(self, master):
        old_current = master._current_key_id
        with patch('config.encryption_master.secrets.token_bytes') as mock_token:
            mock_token.return_value = b"r" * 32
            new_id = master.rotate_key()
            assert new_id != old_current
            assert master._current_key_id == new_id
            assert master._keys[new_id] is not None
            # Old key should be inactive
            for k in master._keys.values():
                if k.key_id == old_current:
                    assert k.is_active is False

    def test_rotate_key_with_custom_id(self, master):
        custom = "custom_key"
        with patch('config.encryption_master.secrets.token_bytes') as mock_token:
            mock_token.return_value = b"c" * 32
            new_id = master.rotate_key(custom)
            assert new_id == custom
            assert master._current_key_id == custom

    # ---- encrypt ----
    def test_encrypt_fallback_crypto_unavailable(self):
        with patch('config.encryption_master.CRYPTO_AVAILABLE', False), \
             patch('config.encryption_master.logger') as mock_log:
            master = EncryptionMaster()
            plaintext = "secret"
            encrypted = master.encrypt(plaintext)
            assert encrypted.startswith(ENCRYPTED_PREFIX)
            encoded = encrypted[len(ENCRYPTED_PREFIX):]
            decoded = base64.b64decode(encoded).decode()
            assert decoded == plaintext
            mock_log.warning.assert_called()

    def test_encrypt_success(self, master):
        plaintext = "secret"
        encrypted = master.encrypt(plaintext)
        assert encrypted.startswith(ENCRYPTED_PREFIX)

    def test_encrypt_key_not_found(self, master):
        with pytest.raises(ConfigEncryptionError, match="Encryption key unknown not found"):
            master.encrypt("secret", key_id="unknown")

    def test_encrypt_key_inactive(self, master):
        key_id = "inactive_key"
        master._add_key(key_id, b"a" * 32, is_active=False)
        with pytest.raises(ConfigEncryptionError, match="is not active or expired"):
            master.encrypt("secret", key_id=key_id)

    def test_encrypt_key_expired(self, master):
        key_id = "expired_key"
        past = datetime.now(UTC) - timedelta(days=1)
        master._add_key(key_id, b"a" * 32, is_active=True, expires_at=past)
        with pytest.raises(ConfigEncryptionError, match="is not active or expired"):
            master.encrypt("secret", key_id=key_id)

    # ---- decrypt ----
    def test_decrypt_plaintext_returns_unchanged(self, master):
        result = master.decrypt("plain")
        assert result == "plain"

    def test_decrypt_fallback_crypto_unavailable(self):
        with patch('config.encryption_master.CRYPTO_AVAILABLE', False), \
             patch('config.encryption_master.logger'):
            master = EncryptionMaster()
            plain = "test"
            encrypted = master.encrypt(plain)  # uses base64 fallback
            decrypted = master.decrypt(encrypted)
            assert decrypted == plain

    def test_decrypt_success(self, master):
        plain = "secret"
        encrypted = master.encrypt(plain)
        decrypted = master.decrypt(encrypted)
        assert decrypted == plain

    def test_decrypt_invalid_format(self, master):
        with pytest.raises(ConfigEncryptionError, match="Failed to parse encrypted value"):
            master.decrypt(ENCRYPTED_PREFIX + "invalid")

    def test_decrypt_key_not_found(self, master):
        # Create an encrypted value with a key that doesn't exist
        with patch('config.encryption_master.EncryptedValue.from_string') as mock_from:
            mock_ev = MagicMock()
            mock_ev.key_id = "unknown"
            mock_from.return_value = mock_ev
            with pytest.raises(ConfigEncryptionError, match="Encryption key unknown not found"):
                master.decrypt(ENCRYPTED_PREFIX + "dummy")

    def test_decrypt_key_expired(self, master):
        # Create an encrypted value with an expired key
        key_id = "expired_key"
        past = datetime.now(UTC) - timedelta(days=1)
        master._add_key(key_id, b"a" * 32, is_active=True, expires_at=past)
        with patch('config.encryption_master.EncryptedValue.from_string') as mock_from:
            mock_ev = MagicMock()
            mock_ev.key_id = key_id
            mock_ev.salt = b"y" * 16
            mock_ev.nonce = b"x" * 12
            mock_ev.ciphertext = b"cipher"
            mock_from.return_value = mock_ev
            with pytest.raises(ConfigEncryptionError, match="Encryption key expired_key is expired"):
                master.decrypt(ENCRYPTED_PREFIX + "dummy")

    # ---- reencrypt ----
    def test_reencrypt(self, master):
        plain = "secret"
        encrypted = master.encrypt(plain)
        reencrypted = master.reencrypt(encrypted)
        assert reencrypted != encrypted
        decrypted = master.decrypt(reencrypted)
        assert decrypted == plain

    def test_reencrypt_with_target_key(self, master):
        key2 = "key2"
        master.rotate_key(key2)
        plain = "secret"
        encrypted = master.encrypt(plain)
        reencrypted = master.reencrypt(encrypted, target_key_id=key2)
        # Should be encrypted with key2
        ev = EncryptedValue.from_string(reencrypted)
        assert ev.key_id == key2
        decrypted = master.decrypt(reencrypted)
        assert decrypted == plain

    # ---- is_encrypted ----
    def test_is_encrypted(self, master):
        assert master.is_encrypted(ENCRYPTED_PREFIX + "abc") is True
        assert master.is_encrypted("plain") is False

    # ---- get_current_key_id ----
    def test_get_current_key_id(self, master):
        assert master.get_current_key_id() == master._current_key_id

    # ---- get_keys ----
    def test_get_keys(self, master):
        keys = master.get_keys()
        assert len(keys) == 1  # default key
        key_info = keys[0]
        assert "key_id" in key_info
        assert "created_at" in key_info
        assert "expires_at" in key_info
        assert "is_active" in key_info
        assert "version" in key_info

    # ---- process_config ----
    def test_process_config_plain(self, master):
        config = {"a": 1, "b": "hello", "c": [1, 2]}
        result = master.process_config(config)
        assert result == config

    def test_process_config_with_encrypted(self, master):
        plain = "secret"
        encrypted = master.encrypt(plain)
        config = {"key": encrypted, "other": "plain"}
        result = master.process_config(config)
        assert result["key"] == plain
        assert result["other"] == "plain"

    def test_process_config_nested(self, master):
        plain = "secret"
        encrypted = master.encrypt(plain)
        config = {"nested": {"key": encrypted, "list": [encrypted]}}
        result = master.process_config(config)
        assert result["nested"]["key"] == plain
        assert result["nested"]["list"][0] == plain

    # ---- encrypt_sensitive_values & _encrypt_nested_value ----
    def test_encrypt_sensitive_values(self, master):
        config = {
            "db": {"password": "secret", "user": "admin"},
            "api": {"key": "apikey"},
        }
        sensitive = ["db.password", "api.key"]
        result = master.encrypt_sensitive_values(config, sensitive)
        # Check that values are encrypted
        assert result["db"]["password"].startswith(ENCRYPTED_PREFIX)
        assert result["api"]["key"].startswith(ENCRYPTED_PREFIX)
        # Unchanged fields
        assert result["db"]["user"] == "admin"

    def test_encrypt_sensitive_values_deep_nested(self, master):
        config = {
            "a": {
                "b": {
                    "c": {
                        "secret": "value"
                    }
                }
            }
        }
        sensitive = ["a.b.c.secret"]
        result = master.encrypt_sensitive_values(config, sensitive)
        assert result["a"]["b"]["c"]["secret"].startswith(ENCRYPTED_PREFIX)

    def test_encrypt_sensitive_values_path_not_found(self, master):
        config = {"a": 1}
        result = master.encrypt_sensitive_values(config, ["b.c"])
        assert result == config  # unchanged

    def test_encrypt_sensitive_values_value_not_string(self, master):
        config = {"a": {"b": 123}}
        result = master.encrypt_sensitive_values(config, ["a.b"])
        assert result["a"]["b"] == 123  # unchanged

    def test_encrypt_nested_value(self, master):
        config = {"a": {"b": "secret"}}
        master._encrypt_nested_value(config, "a.b")
        assert config["a"]["b"].startswith(ENCRYPTED_PREFIX)

    def test_encrypt_nested_value_missing(self, master):
        config = {"a": {}}
        master._encrypt_nested_value(config, "a.b.c")
        # No error, just returns

    # ---- validate ----
    def test_validate_success(self, master):
        result = master.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_no_keys(self, master):
        master._keys = {}
        master._current_key_id = None
        result = master.validate()
        assert result["is_valid"] is False
        assert "No encryption keys available" in result["errors"]
        assert "No active encryption key" in result["errors"]

    def test_validate_invalid_key(self, master):
        # Add an invalid key (force invalid key_material)
        invalid_key = EncryptionKey(
            key_id="invalid",
            key_material=b"short",  # invalid length
            expires_at=None,
            is_active=True,
        )
        master._keys["invalid"] = invalid_key
        result = master.validate()
        assert result["is_valid"] is False
        assert any("key_material must be 32 bytes" in e for e in result["errors"])

    # ---- to_dict ----
    def test_to_dict(self, master):
        d = master.to_dict()
        assert d["current_key_id"] == master._current_key_id
        assert "keys" in d
        assert len(d["keys"]) == 1
        assert d["version"] == master._version

    # ---- from_dict ----
    def test_from_dict(self):
        with patch('config.encryption_master.EncryptionMaster._init_default_key') as mock_init:
            data = {"version": 5}
            master = EncryptionMaster.from_dict(data)
            assert master._version == 5
            mock_init.assert_called_once()

    # ---- clone ----
    def test_clone(self, master):
        cloned = master.clone()
        assert cloned is not master
        assert cloned._version == master._version + 1

    # ---- snapshot ----
    def test_snapshot(self, master):
        snap = master.snapshot()
        assert snap["version"] == 1
        assert snap["key_count"] == 1
        assert snap["current_key_id"] == master._current_key_id
        assert "timestamp" in snap

    # ---- version ----
    def test_version(self, master):
        assert master.version() == 1
        master._version = 10
        assert master.version() == 10

    # ---- audit_trail ----
    def test_audit_trail(self, master):
        master._record_audit("A1", "u1", {})
        master._record_audit("A2", "u2", {})
        trail = master.audit_trail()
        assert len(trail) == 2
        assert trail[0]["action"] == "A1"

    # ---- touch ----
    def test_touch(self, master):
        initial = master.version()
        result = master.touch("tester")
        assert result is master
        assert master.version() == initial + 1
        trail = master.audit_trail()
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "tester"

    # ---- reset ----
    def test_reset(self, master):
        master._version = 5
        master._record_audit("test", "u", {})
        master._keys["extra"] = MagicMock()
        master.reset()
        assert master._version == 1
        assert master._audit_trail == []
        assert master._keys == {}
        # Should have re-initialized default key
        assert "default" in master._keys
        assert master._current_key_id == "default"


# ============================================================================
# Test top-level functions
# ============================================================================

def test_get_encryption_master():
    EncryptionMaster._instance = None
    m1 = get_encryption_master()
    m2 = get_encryption_master()
    assert m1 is m2
    assert isinstance(m1, EncryptionMaster)


def test_encrypt_config_value():
    with patch('config.encryption_master.get_encryption_master') as mock_get:
        mock_master = MagicMock()
        mock_master.encrypt.return_value = "encrypted"
        mock_get.return_value = mock_master
        result = encrypt_config_value("plain")
        assert result == "encrypted"
        mock_master.encrypt.assert_called_with("plain")


def test_decrypt_config_value():
    with patch('config.encryption_master.get_encryption_master') as mock_get:
        mock_master = MagicMock()
        mock_master.decrypt.return_value = "plain"
        mock_get.return_value = mock_master
        result = decrypt_config_value("encrypted")
        assert result == "plain"
        mock_master.decrypt.assert_called_with("encrypted")


def test_process_encrypted_config():
    with patch('config.encryption_master.get_encryption_master') as mock_get:
        mock_master = MagicMock()
        mock_master.process_config.return_value = {"a": 1}
        mock_get.return_value = mock_master
        result = process_encrypted_config({"a": 1})
        assert result == {"a": 1}
        mock_master.process_config.assert_called_with({"a": 1})
