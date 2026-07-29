# tests/security_hardening/test_hsm_pkcs11_manager.py
"""
Comprehensive tests for hsm_pkcs11_manager.py
Covers all methods, edge cases, and exceptions with proper mocking.
"""

import base64
from unittest.mock import MagicMock, patch

import pytest

from security_hardening.hsm_pkcs11_manager import (
    HSM_PKCS11_Manager,
    HSMError,
    HSMKeyError,
    HSMSessionError,
    KeyTypeEnum,
    SignatureMechanism,
)

# ============================================================================
# Enum Tests
# ============================================================================

class TestKeyTypeEnum:
    def test_members_exist(self):
        assert hasattr(KeyTypeEnum, 'RSA')
        assert hasattr(KeyTypeEnum, 'EC')
        assert hasattr(KeyTypeEnum, 'AES')
        assert KeyTypeEnum.RSA.value == "RSA"
        assert KeyTypeEnum.EC.value == "EC"
        assert KeyTypeEnum.AES.value == "AES"


class TestSignatureMechanism:
    def test_members_exist(self):
        assert hasattr(SignatureMechanism, 'SHA1_RSA_PKCS')
        assert hasattr(SignatureMechanism, 'SHA256_RSA_PKCS')
        assert hasattr(SignatureMechanism, 'SHA384_RSA_PKCS')
        assert hasattr(SignatureMechanism, 'SHA512_RSA_PKCS')
        assert hasattr(SignatureMechanism, 'RSA_PKCS')
        assert hasattr(SignatureMechanism, 'ECDSA_SHA256')
        assert hasattr(SignatureMechanism, 'ECDSA_SHA384')

    def test_display_name(self):
        assert SignatureMechanism.SHA256_RSA_PKCS.display_name() == "SHA256_RSA_PKCS"


# ============================================================================
# Exception Tests
# ============================================================================

class TestHSMError:
    def test_construction(self):
        error = HSMError("test")
        assert str(error) == "test"
        assert isinstance(error, Exception)


class TestHSMSessionError:
    def test_construction_and_raise(self):
        with pytest.raises(HSMSessionError, match="session error"):
            raise HSMSessionError("session error")
        assert issubclass(HSMSessionError, HSMError)


class TestHSMKeyError:
    def test_construction_and_raise(self):
        with pytest.raises(HSMKeyError, match="key error"):
            raise HSMKeyError("key error")
        assert issubclass(HSMKeyError, HSMError)


# ============================================================================
# Fixtures and Mocks
# ============================================================================

@pytest.fixture
def mock_pkcs11():
    """Mock the pkcs11 module and its components."""
    with patch('security_hardening.hsm_pkcs11_manager.HAS_PKCS11', True):
        # Create mock classes
        mock_lib = MagicMock()
        mock_slot = MagicMock()
        mock_token = MagicMock()
        mock_session = MagicMock()
        mock_private_key = MagicMock()
        mock_public_key = MagicMock()
        mock_secret_key = MagicMock()

        # Configure mock objects
        mock_slot.slot_id = 1
        mock_slot.get_token.return_value = mock_token
        mock_token.label = "MyToken"
        mock_token.is_present = True
        mock_token.manufacturer_id = "SoftHSM"
        mock_token.model = "SoftHSM v2"
        mock_token.serial_number = "123456"
        mock_token.is_initialized = True
        mock_token.is_read_only = False

        # Session methods
        mock_session.open_session.return_value = mock_session
        mock_session.login.return_value = None
        mock_session.logout.return_value = None
        mock_session.close.return_value = None
        mock_session.get_token.return_value = mock_token

        # Key generation
        mock_session.generate_key_pair.return_value = mock_private_key
        mock_private_key.public_key.return_value = mock_public_key
        mock_private_key.handle = 100
        mock_public_key.handle = 200

        # Key operations
        mock_session.get_key.return_value = mock_private_key
        mock_private_key.sign.return_value = b"signature"
        mock_private_key.verify.return_value = None  # success
        mock_private_key.encrypt.return_value = b"ciphertext"
        mock_private_key.decrypt.return_value = b"plaintext"
        mock_private_key.destroy.return_value = None

        # Find objects
        mock_session.find_objects.return_value = [mock_private_key]

        # Token info attributes
        mock_private_key.__getitem__.side_effect = lambda attr: {
            1: "label",
            2: base64.b64encode(b"id").decode(),
        }.get(attr)

        mock_public_key.__getitem__.return_value = "public_label"

        # Set up lib
        mock_lib.get_slot.return_value = mock_slot
        mock_lib.get_slots.return_value = [mock_slot]

        # Patch the imported pkcs11 module
        with patch('security_hardening.hsm_pkcs11_manager.lib', mock_lib), \
             patch('security_hardening.hsm_pkcs11_manager.Session', mock_session), \
             patch('security_hardening.hsm_pkcs11_manager.Mechanism') as mock_mech, \
             patch('security_hardening.hsm_pkcs11_manager.UserType', MagicMock()), \
             patch('security_hardening.hsm_pkcs11_manager.Attribute') as mock_attr, \
             patch('security_hardening.hsm_pkcs11_manager.ObjectClass') as mock_obj_class, \
             patch('security_hardening.hsm_pkcs11_manager.PKCS11Error', Exception):

            # Set Attribute constants
            mock_attr.LABEL = 1
            mock_attr.CLASS = 2
            mock_attr.ID = 3

            # ObjectClass constants
            mock_obj_class.PRIVATE_KEY = 4
            mock_obj_class.PUBLIC_KEY = 5
            mock_obj_class.SECRET_KEY = 6

            # Mechanism constants
            mock_mech.RSA_PKCS_KEY_PAIR_GEN = MagicMock()
            mock_mech.EC_KEY_PAIR_GEN = MagicMock()
            mock_mech.SHA256_RSA_PKCS = MagicMock()
            mock_mech.RSA_PKCS = MagicMock()

            yield {
                'lib': mock_lib,
                'slot': mock_slot,
                'token': mock_token,
                'session': mock_session,
                'private_key': mock_private_key,
                'public_key': mock_public_key,
                'secret_key': mock_secret_key,
                'mock_mech': mock_mech,
            }


@pytest.fixture
def manager(mock_pkcs11):
    """Create a manager instance with mocked pkcs11."""
    with patch('security_hardening.hsm_pkcs11_manager.HAS_PKCS11', True):
        manager = HSM_PKCS11_Manager(
            library_path="/path/to/lib",
            slot_id=1,
            pin="1234",
            token_label="MyToken",
            user_type="user",
            read_only=False,
        )
        # Replace internal session with mock
        manager._session = mock_pkcs11['session']
        manager._slot = mock_pkcs11['slot']
        manager._token = mock_pkcs11['token']
        manager._pkcs11_lib = mock_pkcs11['lib']
        return manager


# ============================================================================
# HSM_PKCS11_Manager Tests
# ============================================================================

class TestHSM_PKCS11_ManagerConstruction:
    def test_construction_without_pkcs11(self):
        with patch('security_hardening.hsm_pkcs11_manager.HAS_PKCS11', False):
            with pytest.raises(HSMError, match="PKCS#11 library not available"):
                HSM_PKCS11_Manager(library_path="/path")

    def test_construction_success(self, mock_pkcs11):
        with patch('security_hardening.hsm_pkcs11_manager.HAS_PKCS11', True):
            manager = HSM_PKCS11_Manager(
                library_path="/path",
                slot_id=1,
                pin="1234",
                token_label="MyToken",
                user_type="user",
                read_only=False,
            )
            assert manager._lib_path == "/path"
            assert manager._slot_id == 1
            assert manager._pin == "1234"
            assert manager._token_label == "MyToken"
            assert manager._read_only is False
            assert manager._version == 1
            assert len(manager._snapshots) == 1
            # Check that _connect was called
            mock_pkcs11['lib'].get_slot.assert_called_with(1)

    def test_construction_slot_not_found(self, mock_pkcs11):
        mock_pkcs11['lib'].get_slot.side_effect = Exception("Slot not found")
        with patch('security_hardening.hsm_pkcs11_manager.HAS_PKCS11', True):
            with pytest.raises(HSMError, match="Slot 1 not found"):
                HSM_PKCS11_Manager(library_path="/path", slot_id=1)

    def test_construction_token_label_not_found(self, mock_pkcs11):
        mock_pkcs11['lib'].get_slots.return_value = []
        with patch('security_hardening.hsm_pkcs11_manager.HAS_PKCS11', True):
            with pytest.raises(HSMError, match="No slot with token label 'MyToken' found"):
                HSM_PKCS11_Manager(library_path="/path", token_label="MyToken")

    def test_construction_no_slot_available(self, mock_pkcs11):
        mock_slot_no_token = MagicMock()
        mock_slot_no_token.get_token.return_value.is_present = False
        mock_pkcs11['lib'].get_slots.return_value = [mock_slot_no_token]
        with patch('security_hardening.hsm_pkcs11_manager.HAS_PKCS11', True):
            with pytest.raises(HSMError, match="No available slot with token found"):
                HSM_PKCS11_Manager(library_path="/path")


# ============================================================================
# _connect and _ensure_session tests
# ============================================================================

class TestHSMPKCS11Connect:
    def test_connect_success(self, mock_pkcs11):
        with patch('security_hardening.hsm_pkcs11_manager.HAS_PKCS11', True):
            manager = HSM_PKCS11_Manager(library_path="/path", slot_id=1, pin="1234")
            assert manager._session is not None
            mock_pkcs11['session'].login.assert_called_with(user_type=mock_pkcs11['session'].UserType.USER, pin="1234")

    def test_connect_login_fails(self, mock_pkcs11):
        mock_pkcs11['session'].login.side_effect = Exception("Invalid PIN")
        with patch('security_hardening.hsm_pkcs11_manager.HAS_PKCS11', True):
            with pytest.raises(HSMError, match="Failed to connect to HSM"):
                HSM_PKCS11_Manager(library_path="/path", slot_id=1, pin="wrong")

    def test_ensure_session_success(self, manager):
        session = manager._ensure_session()
        assert session is manager._session

    def test_ensure_session_fails(self, manager):
        manager._session = None
        with pytest.raises(HSMSessionError, match="HSM session not open"):
            manager._ensure_session()


# ============================================================================
# Entity Methods (validate, to_dict, etc.)
# ============================================================================

class TestHSMPKCS11EntityMethods:
    def test_validate_success(self, manager):
        result = manager.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_missing_library(self, manager):
        manager._lib_path = ""
        result = manager.validate()
        assert result["is_valid"] is False
        assert "library_path is required" in result["errors"]

    def test_validate_no_session(self, manager):
        manager._session = None
        result = manager.validate()
        assert result["is_valid"] is False
        assert "HSM session not established" in result["errors"]

    def test_validate_pkcs11_not_available(self):
        with patch('security_hardening.hsm_pkcs11_manager.HAS_PKCS11', False):
            manager = HSM_PKCS11_Manager.__new__(HSM_PKCS11_Manager)
            manager._session = MagicMock()
            result = manager.validate()
            assert result["is_valid"] is False
            assert "PKCS#11 library not available" in result["errors"]

    def test_to_dict(self, manager):
        d = manager.to_dict()
        assert d["library_path"] == "/path/to/lib"
        assert d["slot_id"] == 1
        assert d["token_label"] == "MyToken"
        assert d["read_only"] is False
        assert d["connected"] is True
        assert d["version"] == 1

    def test_from_dict(self, mock_pkcs11):
        data = {
            "library_path": "/path",
            "slot_id": 2,
            "token_label": "OtherToken",
            "read_only": True,
            "version": 5,
        }
        with patch('security_hardening.hsm_pkcs11_manager.HAS_PKCS11', True):
            manager = HSM_PKCS11_Manager.from_dict(data)
            assert manager._lib_path == "/path"
            assert manager._slot_id == 2
            assert manager._token_label == "OtherToken"
            assert manager._read_only is True
            assert manager._version == 5
            # Should not auto-connect (pin missing)
            assert manager._session is None

    def test_clone(self, manager):
        original_version = manager.version()
        cloned = manager.clone()
        assert cloned is not manager
        assert cloned._lib_path == manager._lib_path
        assert cloned._slot_id == manager._slot_id
        assert cloned._token_label == manager._token_label
        assert cloned._pin == manager._pin
        assert cloned.version() == original_version + 1

    def test_snapshot(self, manager):
        snap = manager.snapshot()
        assert snap["version"] == 1
        assert snap["connected"] is True
        assert snap["library_path"] == "/path/to/lib"
        assert "timestamp" in snap

    def test_version(self, manager):
        assert manager.version() == 1
        manager._version = 10
        assert manager.version() == 10

    def test_audit_trail(self, manager):
        assert manager.audit_trail() == []
        manager._record_audit("TEST", "user", {"detail": "value"})
        trail = manager.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test_touch(self, manager):
        initial_version = manager.version()
        result = manager.touch("tester")
        assert result is manager
        assert manager.version() == initial_version + 1
        trail = manager.audit_trail()
        assert trail[-1]["action"] == "TOUCH"

    def test_reset(self, manager):
        manager._record_audit("TEST", "user", {})
        manager._version = 5
        with patch.object(manager, '_connect') as mock_connect:
            manager.reset()
            assert manager._version == 1
            assert manager._audit_trail == []
            assert manager._snapshots == []
            mock_connect.assert_called_once()


# ============================================================================
# Key Generation Tests
# ============================================================================

class TestHSMPKCS11KeyGeneration:
    def test_generate_rsa_key_pair_success(self, manager, mock_pkcs11):
        priv_handle, pub_handle = manager.generate_rsa_key_pair(
            key_label="test_rsa",
            modulus_bits=2048,
            public_exponent=65537,
            is_token=True,
            is_private=True,
        )
        assert priv_handle == "100"
        assert pub_handle == "200"
        mock_pkcs11['session'].generate_key_pair.assert_called_with(
            mock_pkcs11['mock_mech'].RSA_PKCS_KEY_PAIR_GEN,
            modulus_bits=2048,
            public_exponent=65537,
            label="test_rsa",
            store=True,
            is_private=True,
        )

    def test_generate_rsa_key_pair_fails(self, manager, mock_pkcs11):
        mock_pkcs11['session'].generate_key_pair.side_effect = Exception("PKCS11 error")
        with pytest.raises(HSMKeyError, match="RSA key generation failed"):
            manager.generate_rsa_key_pair("test")

    def test_generate_ec_key_pair_success(self, manager, mock_pkcs11):
        priv_handle, pub_handle = manager.generate_ec_key_pair(
            key_label="test_ec",
            curve="secp256r1",
            is_token=True,
            is_private=True,
        )
        assert priv_handle == "100"
        assert pub_handle == "200"
        mock_pkcs11['session'].generate_key_pair.assert_called_with(
            mock_pkcs11['mock_mech'].EC_KEY_PAIR_GEN,
            ec_params=b"\x06\x08\x2a\x86\x48\xce\x3d\x03\x01\x07",
            label="test_ec",
            store=True,
            is_private=True,
        )

    def test_generate_ec_key_pair_unsupported_curve(self, manager):
        with pytest.raises(HSMKeyError, match="Unsupported EC curve: unknown"):
            manager.generate_ec_key_pair("test", curve="unknown")

    def test_generate_ec_key_pair_fails(self, manager, mock_pkcs11):
        mock_pkcs11['session'].generate_key_pair.side_effect = Exception("PKCS11 error")
        with pytest.raises(HSMKeyError, match="EC key generation failed"):
            manager.generate_ec_key_pair("test")


# ============================================================================
# Sign and Verify Tests
# ============================================================================

class TestHSMPKCS11SignVerify:
    def test_sign_success(self, manager, mock_pkcs11):
        data = b"test data"
        signature = manager.sign("100", data, SignatureMechanism.SHA256_RSA_PKCS)
        assert signature == b"signature"
        mock_pkcs11['session'].get_key.assert_called_with(100)
        mock_pkcs11['private_key'].sign.assert_called_with(
            mock_pkcs11['mock_mech'].SHA256_RSA_PKCS, data
        )

    def test_sign_fails(self, manager, mock_pkcs11):
        mock_pkcs11['session'].get_key.side_effect = Exception("Invalid handle")
        with pytest.raises(HSMError, match="Signing failed"):
            manager.sign("999", b"data")

    def test_verify_success(self, manager, mock_pkcs11):
        result = manager.verify("200", b"data", b"sig", SignatureMechanism.SHA256_RSA_PKCS)
        assert result is True
        mock_pkcs11['session'].get_key.assert_called_with(200)
        mock_pkcs11['private_key'].verify.assert_called_with(
            mock_pkcs11['mock_mech'].SHA256_RSA_PKCS, b"data", b"sig"
        )

    def test_verify_fails(self, manager, mock_pkcs11):
        mock_pkcs11['private_key'].verify.side_effect = Exception("Verification failed")
        result = manager.verify("200", b"data", b"sig")
        assert result is False


# ============================================================================
# Encryption and Decryption Tests
# ============================================================================

class TestHSMPKCS11EncryptDecrypt:
    def test_encrypt_rsa_success(self, manager, mock_pkcs11):
        plaintext = b"secret"
        ciphertext = manager.encrypt_rsa("200", plaintext, "RSA_PKCS")
        assert ciphertext == b"ciphertext"
        mock_pkcs11['session'].get_key.assert_called_with(200)
        mock_pkcs11['private_key'].encrypt.assert_called_with(
            mock_pkcs11['mock_mech'].RSA_PKCS, plaintext
        )

    def test_encrypt_rsa_fails(self, manager, mock_pkcs11):
        mock_pkcs11['session'].get_key.side_effect = Exception("Invalid key")
        with pytest.raises(HSMError, match="RSA encryption failed"):
            manager.encrypt_rsa("200", b"data")

    def test_decrypt_rsa_success(self, manager, mock_pkcs11):
        ciphertext = b"cipher"
        plaintext = manager.decrypt_rsa("100", ciphertext, "RSA_PKCS")
        assert plaintext == b"plaintext"
        mock_pkcs11['session'].get_key.assert_called_with(100)
        mock_pkcs11['private_key'].decrypt.assert_called_with(
            mock_pkcs11['mock_mech'].RSA_PKCS, ciphertext
        )

    def test_decrypt_rsa_fails(self, manager, mock_pkcs11):
        mock_pkcs11['session'].get_key.side_effect = Exception("Invalid key")
        with pytest.raises(HSMError, match="RSA decryption failed"):
            manager.decrypt_rsa("100", b"data")


# ============================================================================
# Key Management Tests
# ============================================================================

class TestHSMPKCS11KeyManagement:
    def test_find_key_by_label_private(self, manager, mock_pkcs11):
        mock_pkcs11['session'].find_objects.return_value = [mock_pkcs11['private_key']]
        result = manager.find_key_by_label("mykey")
        assert result is not None
        assert result["handle"] == "100"
        assert result["type"] == "private"
        assert result["label"] == "label"
        assert result["class"] == "private_key"
        mock_pkcs11['session'].find_objects.assert_called_with([
            (1, "mykey"), (2, 4)
        ])

    def test_find_key_by_label_public(self, manager, mock_pkcs11):
        # First call returns empty for private, second returns public
        mock_pkcs11['session'].find_objects.side_effect = [
            [],  # no private
            [mock_pkcs11['public_key']]  # public found
        ]
        result = manager.find_key_by_label("pubkey")
        assert result is not None
        assert result["handle"] == "200"
        assert result["type"] == "public"
        assert result["label"] == "public_label"
        assert result["class"] == "public_key"
        # Two calls: one for private, one for public
        assert mock_pkcs11['session'].find_objects.call_count == 2

    def test_find_key_by_label_not_found(self, manager, mock_pkcs11):
        mock_pkcs11['session'].find_objects.return_value = []
        result = manager.find_key_by_label("nonexistent")
        assert result is None

    def test_list_keys_all(self, manager, mock_pkcs11):
        # Mock find_objects to return different lists based on class filter
        def find_objects_side_effect(filters):
            # Simulate filtering by class
            for attr, val in filters:
                if attr == 2 and val == 4:  # PRIVATE_KEY
                    return [mock_pkcs11['private_key']]
                elif attr == 2 and val == 5:  # PUBLIC_KEY
                    return [mock_pkcs11['public_key']]
                elif attr == 2 and val == 6:  # SECRET_KEY
                    return [mock_pkcs11['secret_key']]
            return []
        mock_pkcs11['session'].find_objects.side_effect = find_objects_side_effect

        results = manager.list_keys()
        assert len(results) == 3  # private, public, secret
        # Check private
        assert results[0]["handle"] == "100"
        assert results[0]["type"] == "private"
        # Check public
        assert results[1]["handle"] == "200"
        assert results[1]["type"] == "public"
        # Check secret
        assert results[2]["handle"] == str(mock_pkcs11['secret_key'].handle)
        assert results[2]["type"] == "secret"

    def test_list_keys_filter_private(self, manager, mock_pkcs11):
        def find_objects_side_effect(filters):
            for attr, val in filters:
                if attr == 2 and val == 4:
                    return [mock_pkcs11['private_key']]
            return []
        mock_pkcs11['session'].find_objects.side_effect = find_objects_side_effect

        results = manager.list_keys(key_class="private")
        assert len(results) == 1
        assert results[0]["type"] == "private"

    def test_delete_key_success(self, manager, mock_pkcs11):
        result = manager.delete_key("100")
        assert result is True
        mock_pkcs11['session'].get_key.assert_called_with(100)
        mock_pkcs11['private_key'].destroy.assert_called_once()

    def test_delete_key_fails(self, manager, mock_pkcs11):
        mock_pkcs11['session'].get_key.side_effect = Exception("Key not found")
        result = manager.delete_key("999")
        assert result is False


# ============================================================================
# Token Info Tests
# ============================================================================

class TestHSMPKCS11TokenInfo:
    def test_get_token_info(self, manager, mock_pkcs11):
        info = manager.get_token_info()
        assert info["label"] == "MyToken"
        assert info["manufacturer_id"] == "SoftHSM"
        assert info["model"] == "SoftHSM v2"
        assert info["serial_number"] == "123456"
        assert info["is_present"] is True
        assert info["is_initialized"] is True
        assert info["is_read_only"] is False

    def test_get_token_info_no_session(self, manager):
        manager._session = None
        with pytest.raises(HSMSessionError):
            manager.get_token_info()


# ============================================================================
# Session Management Tests (login/logout)
# ============================================================================

class TestHSMPKCS11SessionManagement:
    def test_login(self, manager, mock_pkcs11):
        manager.login("newpin", "user")
        mock_pkcs11['session'].login.assert_called_with(
            user_type=mock_pkcs11['session'].UserType.USER, pin="newpin"
        )
        assert manager._pin == "newpin"

    def test_login_so(self, manager, mock_pkcs11):
        manager.login("sopin", "so")
        mock_pkcs11['session'].login.assert_called_with(
            user_type=mock_pkcs11['session'].UserType.SO, pin="sopin"
        )

    def test_logout(self, manager, mock_pkcs11):
        manager.logout()
        mock_pkcs11['session'].logout.assert_called_once()

    def test_close(self, manager, mock_pkcs11):
        manager.close()
        mock_pkcs11['session'].logout.assert_called_once()
        mock_pkcs11['session'].close.assert_called_once()
        assert manager._session is None

    def test_context_manager(self, mock_pkcs11):
        with patch('security_hardening.hsm_pkcs11_manager.HAS_PKCS11', True):
            with HSM_PKCS11_Manager(library_path="/path", slot_id=1, pin="1234") as mgr:
                assert mgr._session is not None
            # After exit, session closed
            assert mgr._session is None


# ============================================================================
# Health and Reporting Tests
# ============================================================================

class TestHSMPKCS11HealthReporting:
    def test_health_check_healthy(self, manager, mock_pkcs11):
        result = manager.health_check()
        assert result["healthy"] is True
        assert result["connected"] is True

    def test_health_check_unhealthy(self, manager):
        manager._session = None
        result = manager.health_check()
        assert result["healthy"] is False
        assert result["connected"] is False

    def test_health_check_error(self, manager, mock_pkcs11):
        mock_pkcs11['session'].get_token.side_effect = Exception("Token error")
        result = manager.health_check()
        assert result["healthy"] is False
        assert "Token error" in result["error"]

    def test_generate_report(self, manager, mock_pkcs11):
        report = manager.generate_report()
        assert report["connected"] is True
        assert report["library_path"] == "/path/to/lib"
        assert report["slot_id"] == 1
        assert report["token_label"] == "MyToken"
        assert "token_info" in report
        assert report["version"] == 1

    def test_generate_report_not_connected(self, manager):
        manager._session = None
        report = manager.generate_report()
        assert report["connected"] is False
        assert report["token_info"] == {}
