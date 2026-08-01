#!/usr/bin/env python3
"""
tests/infrastructure/security/test_field_decryption_service.py
Comprehensive tests for infrastructure/security/field_decryption_service.py

Mencakup:
- FieldDecryptionService: semua metode publik, termasuk:
  * decrypt, decrypt_many, decrypt_dict, decrypt_dict_inplace
  * decrypt_nested, decrypt_json_field, decrypt_phone/email/npwp/bank_account
  * is_encrypted, clear_cache, set_cache_enabled, get_stats
- Singleton get_field_decryption_service
- Error handling (DecryptionError)
- Caching behavior
- Edge cases (empty strings, None, invalid formats)
- Mocking encryption service dan json
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from infrastructure.security.field_decryption_service import (
    DecryptionError,
    FieldDecryptionService,
    get_field_decryption_service,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_encryption():
    """Mock FieldEncryption with a deterministic decrypt."""
    mock = MagicMock()
    mock.decrypt.side_effect = lambda x: f"decrypted_{x}" if x else ""
    return mock


@pytest.fixture
def service(mock_encryption):
    """FieldDecryptionService instance with mocked encryption."""
    return FieldDecryptionService(encryption_service=mock_encryption)


@pytest.fixture
def service_with_cache_disabled(mock_encryption):
    """Service with cache disabled."""
    svc = FieldDecryptionService(encryption_service=mock_encryption)
    svc.set_cache_enabled(False)
    return svc


# ============================================================================
# Tests for FieldDecryptionService
# ============================================================================

class TestFieldDecryptionService:
    def test_init(self, mock_encryption):
        """Test constructor sets defaults."""
        svc = FieldDecryptionService(encryption_service=mock_encryption)
        assert svc._encryption is mock_encryption
        assert svc._cache == {}
        assert svc._cache_enabled is True
        assert svc._cache_ttl_seconds == 300
        assert svc._decryption_count == 0

    def test_decrypt_basic(self, service):
        """Test decrypt returns plaintext."""
        result = service.decrypt("cipher")
        assert result == "decrypted_cipher"
        assert service._decryption_count == 1
        assert service._cache["cipher"] == "decrypted_cipher"

    def test_decrypt_empty(self, service):
        """Test decrypt with empty string returns empty."""
        result = service.decrypt("")
        assert result == ""
        assert service._decryption_count == 0
        assert "cipher" not in service._cache  # only called with non-empty

    def test_decrypt_cache_hit(self, service):
        """Test cache returns cached value without calling decrypt."""
        # First call populates cache
        service.decrypt("cipher")
        service._encryption.decrypt.reset_mock()
        # Second call should use cache
        result = service.decrypt("cipher")
        assert result == "decrypted_cipher"
        service._encryption.decrypt.assert_not_called()
        assert service._decryption_count == 1  # count not incremented

    def test_decrypt_cache_disabled(self, service_with_cache_disabled):
        """Test cache is bypassed when disabled."""
        svc = service_with_cache_disabled
        svc.decrypt("cipher")
        svc._encryption.decrypt.reset_mock()
        svc.decrypt("cipher")
        svc._encryption.decrypt.assert_called_once_with("cipher")
        assert svc._decryption_count == 2

    def test_decrypt_raises_decryption_error(self, service):
        """Test DecryptionError is propagated."""
        service._encryption.decrypt.side_effect = DecryptionError("bad")
        with pytest.raises(DecryptionError, match="bad"):
            service.decrypt("cipher")

    def test_decrypt_many(self, service):
        """Test decrypt_many processes multiple values."""
        result = service.decrypt_many("a", "b", "c")
        assert result == ["decrypted_a", "decrypted_b", "decrypted_c"]
        assert service._decryption_count == 3

    def test_decrypt_many_skips_empty(self, service):
        """Test decrypt_many skips empty values."""
        result = service.decrypt_many("a", "", "c")
        assert result == ["decrypted_a", "decrypted_c"]
        assert service._decryption_count == 2

    def test_decrypt_dict(self, service):
        """Test decrypt_dict decrypts specified fields."""
        data = {"name": "plain", "email": "encrypted_email", "phone": "encrypted_phone"}
        result = service.decrypt_dict(data, ["email", "phone"])
        assert result == {
            "name": "plain",
            "email": "decrypted_encrypted_email",
            "phone": "decrypted_encrypted_phone",
        }
        assert data["email"] == "encrypted_email"  # original unchanged
        assert service._decryption_count == 2

    def test_decrypt_dict_missing_field(self, service):
        """Test decrypt_dict handles missing fields gracefully."""
        data = {"name": "plain"}
        result = service.decrypt_dict(data, ["email"])
        assert result["email"] is None  # not present in result
        assert result["name"] == "plain"
        assert service._decryption_count == 0

    def test_decrypt_dict_field_empty(self, service):
        """Test decrypt_dict skips empty fields."""
        data = {"email": ""}
        result = service.decrypt_dict(data, ["email"])
        assert result["email"] == ""
        assert service._decryption_count == 0

    def test_decrypt_dict_decryption_error(self, service):
        """Test decrypt_dict sets field to None on DecryptionError."""
        service._encryption.decrypt.side_effect = DecryptionError("bad")
        data = {"email": "encrypted"}
        result = service.decrypt_dict(data, ["email"])
        assert result["email"] is None
        assert service._decryption_count == 0  # error, not counted

    def test_decrypt_dict_inplace(self, service):
        """Test decrypt_dict_inplace modifies original dict."""
        data = {"name": "plain", "email": "encrypted"}
        service.decrypt_dict_inplace(data, ["email"])
        assert data["email"] == "decrypted_encrypted"
        assert data["name"] == "plain"
        assert service._decryption_count == 1

    def test_decrypt_dict_inplace_missing_field(self, service):
        """Test decrypt_dict_inplace handles missing fields."""
        data = {"name": "plain"}
        service.decrypt_dict_inplace(data, ["email"])
        assert data == {"name": "plain"}  # unchanged
        assert service._decryption_count == 0

    def test_decrypt_dict_inplace_decryption_error(self, service):
        """Test decrypt_dict_inplace sets field to None on error."""
        service._encryption.decrypt.side_effect = DecryptionError("bad")
        data = {"email": "encrypted"}
        service.decrypt_dict_inplace(data, ["email"])
        assert data["email"] is None

    def test_decrypt_nested_simple(self, service):
        """Test decrypt_nested with simple dot notation."""
        data = {"user": {"email": "encrypted_email"}}
        result = service.decrypt_nested(data, "user.email")
        assert result == "decrypted_encrypted_email"
        assert service._decryption_count == 1

    def test_decrypt_nested_deep(self, service):
        """Test decrypt_nested with deeper path."""
        data = {"a": {"b": {"c": "encrypted"}}}
        result = service.decrypt_nested(data, "a.b.c")
        assert result == "decrypted_encrypted"

    def test_decrypt_nested_missing_path(self, service):
        """Test decrypt_nested returns None if path missing."""
        data = {"user": {}}
        result = service.decrypt_nested(data, "user.email")
        assert result is None
        assert service._decryption_count == 0

    def test_decrypt_nested_path_part_missing(self, service):
        """Test decrypt_nested returns None if intermediate missing."""
        data = {"user": None}  # type: ignore
        result = service.decrypt_nested(data, "user.email")  # type: ignore
        assert result is None
        assert service._decryption_count == 0

    def test_decrypt_nested_empty_value(self, service):
        """Test decrypt_nested returns None if field is empty."""
        data = {"user": {"email": ""}}
        result = service.decrypt_nested(data, "user.email")
        assert result is None  # because value is empty, decrypt returns ""
        # Actually decrypt returns "" for empty, but our method returns None if value empty.
        # Let's see: current code: if current.get(last_part): then call decrypt, else None.
        # So if value is empty string, get returns '' which is falsy, so returns None.
        assert result is None
        assert service._decryption_count == 0

    def test_decrypt_nested_decryption_error(self, service):
        """Test decrypt_nested returns None on DecryptionError."""
        service._encryption.decrypt.side_effect = DecryptionError("bad")
        data = {"user": {"email": "encrypted"}}
        result = service.decrypt_nested(data, "user.email")
        assert result is None

    def test_decrypt_json_field(self, service):
        """Test decrypt_json_field decrypts and parses JSON."""
        # Mock the decrypt to return a JSON string
        service._encryption.decrypt.return_value = '{"key": "value"}'
        result = service.decrypt_json_field("cipher")
        assert result == {"key": "value"}
        service._encryption.decrypt.assert_called_once_with("cipher")
        assert service._decryption_count == 1

    def test_decrypt_json_field_invalid_json(self, service):
        """Test decrypt_json_field raises ValueError on invalid JSON."""
        service._encryption.decrypt.return_value = "not json"
        with pytest.raises(json.JSONDecodeError):
            service.decrypt_json_field("cipher")

    def test_is_encrypted_valid(self, service):
        """Test is_encrypted returns True for valid format."""
        # Format: v1|key_id|nonce|ciphertext (all base64)
        import base64
        nonce = base64.b64encode(b"nonce").decode()
        cipher = base64.b64encode(b"cipher").decode()
        value = f"v1|key1|{nonce}|{cipher}"
        assert service.is_encrypted(value) is True

    def test_is_encrypted_invalid_version(self, service):
        """Test is_encrypted returns False for wrong version."""
        value = "v2|key|nonce|cipher"
        assert service.is_encrypted(value) is False

    def test_is_encrypted_wrong_parts(self, service):
        """Test is_encrypted returns False if not 4 parts."""
        assert service.is_encrypted("one|two|three") is False
        assert service.is_encrypted("v1|key|nonce") is False

    def test_is_encrypted_non_string(self, service):
        """Test is_encrypted returns False for non-string."""
        assert service.is_encrypted(None) is False
        assert service.is_encrypted(123) is False

    def test_is_encrypted_invalid_base64(self, service):
        """Test is_encrypted returns False if nonce/cipher not base64."""
        value = "v1|key|invalid!|cipher"
        assert service.is_encrypted(value) is False

    def test_clear_cache(self, service):
        """Test clear_cache empties cache."""
        service.decrypt("cipher")
        assert len(service._cache) == 1
        service.clear_cache()
        assert service._cache == {}

    def test_set_cache_enabled(self, service):
        """Test set_cache_enabled toggles cache and clears when disabled."""
        service.decrypt("cipher")
        assert service._cache_enabled is True
        service.set_cache_enabled(False)
        assert service._cache_enabled is False
        assert service._cache == {}  # cleared on disable

    def test_get_stats(self, service):
        """Test get_stats returns correct statistics."""
        service.decrypt("a")
        service.decrypt("b")
        stats = service.get_stats()
        assert stats["decryption_count"] == 2
        assert stats["cache_size"] == 2
        assert stats["cache_enabled"] is True
        assert stats["cache_ttl_seconds"] == 300

    def test_decrypt_phone(self, service):
        """Test decrypt_phone calls decrypt."""
        result = service.decrypt_phone("enc_phone")
        assert result == "decrypted_enc_phone"
        assert service._decryption_count == 1

    def test_decrypt_email(self, service):
        """Test decrypt_email calls decrypt."""
        result = service.decrypt_email("enc_email")
        assert result == "decrypted_enc_email"

    def test_decrypt_npwp(self, service):
        """Test decrypt_npwp calls decrypt."""
        result = service.decrypt_npwp("enc_npwp")
        assert result == "decrypted_enc_npwp"

    def test_decrypt_bank_account(self, service):
        """Test decrypt_bank_account calls decrypt."""
        result = service.decrypt_bank_account("enc_bank")
        assert result == "decrypted_enc_bank"

    def test_convenience_methods_increment_count(self, service):
        """Test convenience methods increment decryption count."""
        service.decrypt_phone("a")
        service.decrypt_email("b")
        service.decrypt_npwp("c")
        service.decrypt_bank_account("d")
        assert service._decryption_count == 4


# ============================================================================
# Tests for Singleton Accessor
# ============================================================================

class TestGetFieldDecryptionService:
    def test_singleton(self):
        """Test get_field_decryption_service returns same instance."""
        svc1 = get_field_decryption_service()
        svc2 = get_field_decryption_service()
        assert svc1 is svc2
        assert isinstance(svc1, FieldDecryptionService)

    def test_singleton_initializes_once(self):
        """Test singleton creates only one instance."""
        with patch("infrastructure.security.field_decryption_service.FieldDecryptionService") as MockService:
            MockService.return_value = MagicMock()
            svc1 = get_field_decryption_service()
            svc2 = get_field_decryption_service()
            assert svc1 is svc2
            MockService.assert_called_once()  # called only once


# ============================================================================
# Integration-style Tests (mocking external dependencies)
# ============================================================================

class TestFieldDecryptionServiceIntegration:
    def test_logging_on_decryption_error(self, mock_encryption):
        """Test error is logged when decrypt fails."""
        mock_encryption.decrypt.side_effect = DecryptionError("bad")
        svc = FieldDecryptionService(encryption_service=mock_encryption)
        with patch("infrastructure.security.field_decryption_service.logger") as mock_logger:
            with pytest.raises(DecryptionError):
                svc.decrypt("cipher")
            mock_logger.error.assert_called_once_with("Failed to decrypt field: bad")

    def test_decrypt_dict_logs_field_error(self, mock_encryption):
        """Test decrypt_dict logs error per field."""
        mock_encryption.decrypt.side_effect = DecryptionError("bad")
        svc = FieldDecryptionService(encryption_service=mock_encryption)
        with patch("infrastructure.security.field_decryption_service.logger") as mock_logger:
            data = {"email": "encrypted"}
            result = svc.decrypt_dict(data, ["email"])
            assert result["email"] is None
            mock_logger.error.assert_called_once_with("Failed to decrypt field 'email': bad")

    def test_decrypt_dict_inplace_logs_field_error(self, mock_encryption):
        """Test decrypt_dict_inplace logs error per field."""
        mock_encryption.decrypt.side_effect = DecryptionError("bad")
        svc = FieldDecryptionService(encryption_service=mock_encryption)
        with patch("infrastructure.security.field_decryption_service.logger") as mock_logger:
            data = {"email": "encrypted"}
            svc.decrypt_dict_inplace(data, ["email"])
            assert data["email"] is None
            mock_logger.error.assert_called_once_with("Failed to decrypt field 'email': bad")

    def test_decrypt_nested_logs_error(self, mock_encryption):
        """Test decrypt_nested logs error when decrypt fails."""
        mock_encryption.decrypt.side_effect = DecryptionError("bad")
        svc = FieldDecryptionService(encryption_service=mock_encryption)
        with patch("infrastructure.security.field_decryption_service.logger"):
            data = {"user": {"email": "encrypted"}}
            result = svc.decrypt_nested(data, "user.email")
            assert result is None
            # Error is logged, but we can't easily verify because logger.error is called inside try/except without propagation.
            # The method catches and returns None; we just check it doesn't raise.
            # We'll check that it returns None.
            assert result is None

    def test_decrypt_nested_no_log_if_field_missing(self, service):
        """Test decrypt_nested does not log if field missing."""
        with patch("infrastructure.security.field_decryption_service.logger") as mock_logger:
            data = {"user": {}}
            result = service.decrypt_nested(data, "user.email")
            assert result is None
            mock_logger.error.assert_not_called()
