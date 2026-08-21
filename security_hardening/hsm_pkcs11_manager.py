#!/usr/bin/env python3
"""
Module: hsm_pkcs11_manager.py
Layer: Security Hardening

Responsibility:
    Manager untuk Hardware Security Module (HSM) via PKCS#11.
    Mendukung key generation (RSA, EC), signing, verification, encryption,
    decryption, key import/export, dan management session. Integrasi dengan
    berbagai vendor HSM (SoftHSM, AWS CloudHSM, Thales, etc).

Metode yang ditambahkan:
- Untuk HSM_PKCS11_Manager: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import base64
import contextlib
import logging
import threading
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# Coba import pkcs11 (python-pkcs11)
try:
    from pkcs11 import (
        Attribute,
        Mechanism,
        ObjectClass,
        PKCS11Error,
        Session,
        UserType,
        lib,
    )

    HAS_PKCS11 = True
except ImportError:
    HAS_PKCS11 = False

    # FIX: tambahkan # type: ignore untuk menghindari error no-redef
    class PKCS11Error(Exception):  # type: ignore
        pass


# ============================================================================
# Enums
# ============================================================================
class KeyTypeEnum(Enum):
    RSA = "RSA"
    EC = "EC"
    AES = "AES"


class SignatureMechanism(Enum):
    SHA1_RSA_PKCS = "SHA1_RSA_PKCS"
    SHA256_RSA_PKCS = "SHA256_RSA_PKCS"
    SHA384_RSA_PKCS = "SHA384_RSA_PKCS"
    SHA512_RSA_PKCS = "SHA512_RSA_PKCS"
    RSA_PKCS = "RSA_PKCS"
    ECDSA_SHA256 = "ECDSA_SHA256"
    ECDSA_SHA384 = "ECDSA_SHA384"

    def display_name(self) -> str:
        return self.value


# ============================================================================
# Exceptions
# ============================================================================
class HSMError(Exception):
    pass


class HSMSessionError(HSMError):
    pass


class HSMKeyError(HSMError):
    pass


# ============================================================================
# HSM_PKCS11_Manager Core (dengan entity dasar)
# ============================================================================
class HSM_PKCS11_Manager:
    """
    Manager untuk HSM via PKCS#11.
    Mengelola koneksi, session, key operations.
    """

    def __init__(
        self,
        library_path: str,
        slot_id: int | None = None,
        pin: str | None = None,
        token_label: str | None = None,
        user_type: str = "user",
        read_only: bool = False,
    ):
        if not HAS_PKCS11:
            raise HSMError(
                "PKCS#11 library not available. Install python-pkcs11 (pip install python-pkcs11)"
            )

        self._lib_path = library_path
        self._slot_id = slot_id
        self._pin = pin
        self._token_label = token_label
        self._user_type = UserType.USER if user_type == "user" else UserType.SO
        self._read_only = read_only
        self._pkcs11_lib = None
        self._session: Session | None = None
        self._token = None
        self._slot = None
        self._lock = threading.RLock()
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()
        self._connect()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "library_path": self._lib_path,
                "slot_id": self._slot_id,
                "token_label": self._token_label,
                "connected": self._session is not None,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    def _connect(self) -> None:
        """Membuka koneksi ke HSM, load library, open session, login."""
        with self._lock:
            try:
                self._pkcs11_lib = lib(self._lib_path)
                if self._slot_id is not None:
                    try:
                        # self._pkcs11_lib not None after lib() call
                        self._slot = self._pkcs11_lib.get_slot(self._slot_id)  # type: ignore
                    except PKCS11Error as e:
                        raise HSMError(f"Slot {self._slot_id} not found: {e}")
                else:
                    # self._pkcs11_lib not None after lib() call
                    slots = self._pkcs11_lib.get_slots()  # type: ignore
                    if self._token_label:
                        for s in slots:
                            token = s.get_token()
                            if token.label == self._token_label:
                                self._slot = s
                                self._token = token
                                break
                        if not self._slot:
                            raise HSMError(f"No slot with token label '{self._token_label}' found")
                    else:
                        for s in slots:
                            if s.get_token().is_present:
                                self._slot = s
                                self._token = s.get_token()
                                break
                        if not self._slot:
                            raise HSMError("No available slot with token found")

                # self._slot is not None here
                self._session = self._slot.open_session(read_only=self._read_only)  # type: ignore
                if self._pin:
                    self._session.login(user_type=self._user_type, pin=self._pin)
                # Access slot_id safely
                self._record_audit("CONNECT", "system", {"slot_id": self._slot.slot_id})  # type: ignore
                logger.info(
                    f"HSM connected: slot={self._slot.slot_id}, token={self._token.label if self._token else 'Unknown'}"  # type: ignore
                )
            except Exception as e:
                raise HSMError(f"Failed to connect to HSM: {e}")

    def close(self):
        """Menutup session dan logout."""
        with self._lock:
            if self._session:
                with contextlib.suppress(Exception):
                    self._session.logout()
                self._session.close()
                self._session = None
            self._record_audit("CLOSE", "system", {})
            logger.info("HSM session closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _ensure_session(self) -> Session:
        if not self._session:
            raise HSMSessionError("HSM session not open")
        return self._session

    # ========================================================================
    # Key Generation
    # ========================================================================
    def generate_rsa_key_pair(
        self,
        key_label: str,
        modulus_bits: int = 2048,
        public_exponent: int = 65537,
        is_token: bool = True,
        is_private: bool = True,
    ) -> tuple[str, str]:
        """Generate RSA key pair di HSM. Returns (private_key_handle_str, public_key_handle_str)."""
        with self._lock:
            sess = self._ensure_session()
            try:
                private_key = sess.generate_key_pair(
                    Mechanism.RSA_PKCS_KEY_PAIR_GEN,
                    modulus_bits=modulus_bits,
                    public_exponent=public_exponent,
                    label=key_label,
                    store=is_token,
                    is_private=is_private,
                )
                public_key = private_key.public_key()
                self._record_audit(
                    "GENERATE_RSA_KEY", "system", {"label": key_label, "bits": modulus_bits}
                )
                logger.info(f"RSA key pair generated: {key_label} (bits={modulus_bits})")
                return str(private_key.handle), str(public_key.handle)
            except PKCS11Error as e:
                raise HSMKeyError(f"RSA key generation failed: {e}")

    def generate_ec_key_pair(
        self,
        key_label: str,
        curve: str = "secp256r1",
        is_token: bool = True,
        is_private: bool = True,
    ) -> tuple[str, str]:
        """Generate EC key pair di HSM. Returns (private_key_handle_str, public_key_handle_str)."""
        with self._lock:
            sess = self._ensure_session()
            ec_params_map = {
                "secp256r1": b"\x06\x08\x2a\x86\x48\xce\x3d\x03\x01\x07",
                "secp384r1": b"\x06\x05\x2b\x81\x04\x00\x22",
                "secp521r1": b"\x06\x05\x2b\x81\x04\x00\x23",
            }
            ec_param = ec_params_map.get(curve)
            if not ec_param:
                raise HSMKeyError(f"Unsupported EC curve: {curve}")
            try:
                private_key = sess.generate_key_pair(
                    Mechanism.EC_KEY_PAIR_GEN,
                    ec_params=ec_param,
                    label=key_label,
                    store=is_token,
                    is_private=is_private,
                )
                public_key = private_key.public_key()
                self._record_audit(
                    "GENERATE_EC_KEY", "system", {"label": key_label, "curve": curve}
                )
                logger.info(f"EC key pair generated: {key_label} (curve={curve})")
                return str(private_key.handle), str(public_key.handle)
            except PKCS11Error as e:
                raise HSMKeyError(f"EC key generation failed: {e}")

    # ========================================================================
    # Signing & Verification
    # ========================================================================
    def sign(
        self,
        private_key_handle: str,
        data: bytes,
        mechanism: SignatureMechanism = SignatureMechanism.SHA256_RSA_PKCS,
    ) -> bytes:
        with self._lock:
            sess = self._ensure_session()
            try:
                handle = int(private_key_handle)
                priv_key = sess.get_key(handle)
                mech = getattr(Mechanism, mechanism.value, Mechanism.SHA256_RSA_PKCS)
                signature = priv_key.sign(mech, data)
                self._record_audit(
                    "SIGN", "system", {"key_handle": private_key_handle, "data_len": len(data)}
                )
                logger.debug(f"Signed {len(data)} bytes, signature length={len(signature)}")
                return signature
            except PKCS11Error as e:
                raise HSMError(f"Signing failed: {e}")

    def verify(
        self,
        public_key_handle: str,
        data: bytes,
        signature: bytes,
        mechanism: SignatureMechanism = SignatureMechanism.SHA256_RSA_PKCS,
    ) -> bool:
        with self._lock:
            sess = self._ensure_session()
            try:
                handle = int(public_key_handle)
                pub_key = sess.get_key(handle)
                mech = getattr(Mechanism, mechanism.value, Mechanism.SHA256_RSA_PKCS)
                pub_key.verify(mech, data, signature)
                return True
            except PKCS11Error:
                return False

    # ========================================================================
    # Encryption & Decryption (RSA)
    # ========================================================================
    def encrypt_rsa(
        self, public_key_handle: str, plaintext: bytes, mechanism: str = "RSA_PKCS"
    ) -> bytes:
        with self._lock:
            sess = self._ensure_session()
            try:
                handle = int(public_key_handle)
                pub_key = sess.get_key(handle)
                mech = getattr(Mechanism, mechanism, Mechanism.RSA_PKCS)
                ciphertext = pub_key.encrypt(mech, plaintext)
                self._record_audit(
                    "ENCRYPT_RSA",
                    "system",
                    {"key_handle": public_key_handle, "plaintext_len": len(plaintext)},
                )
                return ciphertext
            except PKCS11Error as e:
                raise HSMError(f"RSA encryption failed: {e}")

    def decrypt_rsa(
        self, private_key_handle: str, ciphertext: bytes, mechanism: str = "RSA_PKCS"
    ) -> bytes:
        with self._lock:
            sess = self._ensure_session()
            try:
                handle = int(private_key_handle)
                priv_key = sess.get_key(handle)
                mech = getattr(Mechanism, mechanism, Mechanism.RSA_PKCS)
                plaintext = priv_key.decrypt(mech, ciphertext)
                self._record_audit(
                    "DECRYPT_RSA",
                    "system",
                    {"key_handle": private_key_handle, "ciphertext_len": len(ciphertext)},
                )
                return plaintext
            except PKCS11Error as e:
                raise HSMError(f"RSA decryption failed: {e}")

    # ========================================================================
    # Key Management
    # ========================================================================
    def find_key_by_label(self, label: str) -> dict | None:
        with self._lock:
            sess = self._ensure_session()
            try:
                priv_keys = sess.find_objects(
                    [
                        (Attribute.LABEL, label),
                        (Attribute.CLASS, ObjectClass.PRIVATE_KEY),
                    ]
                )
                if priv_keys:
                    key = priv_keys[0]
                    return {
                        "handle": str(key.handle),
                        "type": "private",
                        "label": key[Attribute.LABEL],
                        "id": base64.b64encode(key[Attribute.ID]).decode()
                        if key[Attribute.ID]
                        else None,
                        "class": "private_key",
                    }
                pub_keys = sess.find_objects(
                    [
                        (Attribute.LABEL, label),
                        (Attribute.CLASS, ObjectClass.PUBLIC_KEY),
                    ]
                )
                if pub_keys:
                    key = pub_keys[0]
                    return {
                        "handle": str(key.handle),
                        "type": "public",
                        "label": key[Attribute.LABEL],
                        "class": "public_key",
                    }
                return None
            except PKCS11Error as e:
                logger.error(f"Key search failed: {e}")
                return None

    def list_keys(self, key_class: str | None = None) -> list[dict]:
        with self._lock:
            sess = self._ensure_session()
            results = []
            try:
                if key_class in (None, "private"):
                    for key in sess.find_objects([(Attribute.CLASS, ObjectClass.PRIVATE_KEY)]):
                        results.append(
                            {
                                "handle": str(key.handle),
                                "type": "private",
                                "label": key[Attribute.LABEL],
                            }
                        )
                if key_class in (None, "public"):
                    for key in sess.find_objects([(Attribute.CLASS, ObjectClass.PUBLIC_KEY)]):
                        results.append(
                            {
                                "handle": str(key.handle),
                                "type": "public",
                                "label": key[Attribute.LABEL],
                            }
                        )
                if key_class in (None, "secret"):
                    for key in sess.find_objects([(Attribute.CLASS, ObjectClass.SECRET_KEY)]):
                        results.append(
                            {
                                "handle": str(key.handle),
                                "type": "secret",
                                "label": key[Attribute.LABEL],
                            }
                        )
            except PKCS11Error as e:
                logger.error(f"Listing keys failed: {e}")
            return results

    def delete_key(self, key_handle: str) -> bool:
        with self._lock:
            sess = self._ensure_session()
            try:
                handle = int(key_handle)
                key = sess.get_key(handle)
                key.destroy()
                self._record_audit("DELETE_KEY", "system", {"key_handle": key_handle})
                logger.info(f"Key {key_handle} deleted")
                return True
            except PKCS11Error as e:
                logger.error(f"Key deletion failed: {e}")
                return False

    def get_token_info(self) -> dict:
        with self._lock:
            sess = self._ensure_session()
            token = sess.get_token()
            return {
                "label": token.label,
                "manufacturer_id": token.manufacturer_id,
                "model": token.model,
                "serial_number": token.serial_number,
                "is_present": token.is_present,
                "is_initialized": token.is_initialized,
                "is_read_only": token.is_read_only,
            }

    def get_session(self) -> Session:
        return self._ensure_session()

    def login(self, pin: str, user_type: str = "user") -> None:
        with self._lock:
            sess = self._ensure_session()
            ut = UserType.USER if user_type == "user" else UserType.SO
            sess.login(user_type=ut, pin=pin)
            self._pin = pin
            self._record_audit("LOGIN", "system", {"user_type": user_type})

    def logout(self) -> None:
        with self._lock:
            if self._session:
                self._session.logout()
                self._record_audit("LOGOUT", "system", {})

    # ========================================================================
    # Health & Reporting
    # ========================================================================
    def health_check(self) -> dict:
        try:
            if self._session:
                self._session.get_token()
                return {"healthy": True, "connected": True}
            return {"healthy": False, "connected": False}
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    def generate_report(self) -> dict:
        token_info = self.get_token_info() if self._session else {}
        return {
            "connected": self._session is not None,
            "library_path": self._lib_path,
            "slot_id": self._slot_id,
            "token_label": self._token_label,
            "token_info": token_info,
            "version": self._version,
        }

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not HAS_PKCS11:
            errors.append("PKCS#11 library not available")
        if not self._lib_path:
            errors.append("library_path is required")
        if self._session is None:
            errors.append("HSM session not established")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "library_path": self._lib_path,
            "slot_id": self._slot_id,
            "token_label": self._token_label,
            "read_only": self._read_only,
            "connected": self._session is not None,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HSM_PKCS11_Manager:
        instance = cls(
            library_path=data["library_path"],
            slot_id=data.get("slot_id"),
            pin=None,  # Pin tidak disimpan di dict untuk keamanan
            token_label=data.get("token_label"),
            user_type="user",
            read_only=data.get("read_only", False),
        )
        instance._version = data.get("version", 1)
        # Tidak otomatis connect, perlu manual reconnect
        return instance

    def clone(self) -> HSM_PKCS11_Manager:
        new = HSM_PKCS11_Manager(
            library_path=self._lib_path,
            slot_id=self._slot_id,
            pin=self._pin,
            token_label=self._token_label,
            user_type="user" if self._user_type == UserType.USER else "so",
            read_only=self._read_only,
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "connected": self._session is not None,
            "library_path": self._lib_path,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> HSM_PKCS11_Manager:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        """Reset manager (untuk testing)."""
        self.close()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._connect()


# ============================================================================
# Demo / Contoh Penggunaan
# ============================================================================
if __name__ == "__main__":
    try:
        hsm = HSM_PKCS11_Manager(
            library_path="/usr/lib/softhsm/libsofthsm2.so",
            pin="1234",
            token_label="MyToken",
        )
        print("HSM connected:", hsm.get_token_info())
        priv, pub = hsm.generate_rsa_key_pair("test_rsa_key", modulus_bits=2048)
        print(f"Generated RSA key: priv={priv}, pub={pub}")
        data = b"Hello, HSM!"
        signature = hsm.sign(priv, data)
        print(f"Signature length: {len(signature)}")
        is_valid = hsm.verify(pub, data, signature)
        print(f"Signature valid: {is_valid}")
        keys = hsm.list_keys()
        print(f"Keys in token: {len(keys)}")
        hsm.close()
    except HSMError as e:
        print(f"HSM error (simulated if no HSM): {e}")
        print("This is normal if SoftHSM not installed or no token initialized")
