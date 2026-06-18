#!/usr/bin/env python3
"""
Module: key_management_vault_auto_rotate.py
Layer: Security Hardening

Responsibility:
    Manajemen kunci enkripsi menggunakan HashiCorp Vault transit engine dengan
    rotasi otomatis, versioning, audit, dan integrasi dengan aplikasi.

Metode yang ditambahkan:
- Untuk VaultClient: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk VaultKeyManager: semua entity dasar serta health_check, generate_report, reset.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

try:
    import hvac

    HAS_HVAC = True
except ImportError:
    HAS_HVAC = False
    import requests

from .security_exceptions import KeyManagementError

logger = logging.getLogger(__name__)


# ============================================================================
# Vault Client Wrapper (dengan entity dasar)
# ============================================================================
class VaultClient:
    """Wrapper untuk komunikasi dengan HashiCorp Vault."""

    def __init__(self, addr: str, token: str, verify_tls: bool = True):
        self.addr = addr.rstrip("/")
        self.token = token
        self.verify = verify_tls
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

        if HAS_HVAC:
            self.client = hvac.Client(url=addr, token=token, verify=verify_tls)
        else:
            self.client = None
            self.session = requests.Session()
            self.session.headers.update({"X-Vault-Token": token})

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "addr": self.addr,
                "verify": self.verify,
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

    def _request(self, method: str, path: str, json_data: dict | None = None) -> dict:
        url = f"{self.addr}/v1/{path}"
        if HAS_HVAC and self.client:
            if method == "GET":
                resp = self.client.get(path)
            elif method == "POST":
                resp = self.client.post(path, json=json_data)
            else:
                resp = self.client.adapter.request(method, url, json=json_data)
            if resp.status_code >= 400:
                raise KeyManagementError(f"Vault request failed: {resp.status_code} - {resp.text}")
            return resp.json()
        else:
            resp = self.session.request(method, url, json=json_data, verify=self.verify)
            if resp.status_code >= 400:
                raise KeyManagementError(f"Vault request failed: {resp.status_code} - {resp.text}")
            return resp.json()

    def get(self, path: str) -> dict:
        return self._request("GET", path)

    def post(self, path: str, json_data: dict) -> dict:
        return self._request("POST", path, json_data)

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.addr:
            errors.append("Vault address is required")
        if not self.token:
            errors.append("Vault token is required")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "addr": self.addr,
            "verify": self.verify,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VaultClient:
        instance = cls(
            addr=data["addr"],
            token="",  # token tidak disimpan di dict
            verify_tls=data.get("verify", True),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> VaultClient:
        new = VaultClient(self.addr, self.token, self.verify)
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "addr": self.addr,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> VaultClient:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# VaultKeyManager Core (dengan entity dasar)
# ============================================================================
class VaultKeyManager:
    """
    Manajer kunci terintegrasi dengan HashiCorp Vault transit engine.
    Mendukung rotasi otomatis, versioning, dan audit.
    """

    def __init__(
        self,
        vault_addr: str,
        token: str,
        transit_mount: str = "transit",
        key_name: str = "erp-master-key",
        rotation_interval_days: int = 90,
        verify_tls: bool = True,
        auto_rotate_enabled: bool = True,
    ):
        self._vault_addr = vault_addr
        self._token = token
        self._transit_mount = transit_mount.rstrip("/")
        self._key_name = key_name
        self._rotation_interval = timedelta(days=rotation_interval_days)
        self._verify = verify_tls
        self._auto_rotate = auto_rotate_enabled
        self._client = VaultClient(vault_addr, token, verify_tls)
        self._lock = threading.RLock()
        self._rotation_thread: threading.Thread | None = None
        self._running = False
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

        self._ensure_key_exists()
        if auto_rotate_enabled:
            self._start_rotation_monitor()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "key_name": self._key_name,
                "auto_rotate": self._auto_rotate,
                "rotation_interval_days": self._rotation_interval.days,
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

    def _request(self, method: str, path: str, json_data: dict | None = None) -> dict:
        full_path = f"{self._transit_mount}/{path.lstrip('/')}"
        return self._client._request(method, full_path, json_data)

    def _ensure_key_exists(self) -> None:
        try:
            self._request("GET", f"keys/{self._key_name}")
            logger.info(f"Key '{self._key_name}' already exists")
        except KeyManagementError:
            logger.info(f"Creating new key '{self._key_name}'")
            self._request("POST", f"keys/{self._key_name}", json={"type": "aes256-gcm96"})
            self._record_audit("CREATE_KEY", "system", {"key_name": self._key_name})

    def get_latest_key_version(self) -> int:
        resp = self._request("GET", f"keys/{self._key_name}")
        return int(resp["data"]["latest_version"])

    def get_key_versions(self) -> dict[int, dict]:
        resp = self._request("GET", f"keys/{self._key_name}")
        versions = resp["data"].get("keys", {})
        return {int(v): details for v, details in versions.items()}

    def get_key_metadata(self) -> dict:
        resp = self._request("GET", f"keys/{self._key_name}")
        return resp["data"]

    def encrypt(self, plaintext: bytes, key_version: int | None = None) -> dict:
        b64_plain = base64.b64encode(plaintext).decode()
        payload = {"plaintext": b64_plain}
        if key_version is not None:
            payload["key_version"] = key_version
        resp = self._request("POST", f"encrypt/{self._key_name}", json=payload)
        data = resp["data"]
        self._record_audit("ENCRYPT", "system", {"key_version": data["key_version"]})
        return {
            "ciphertext": data["ciphertext"],
            "key_version": int(data["key_version"]),
        }

    def decrypt(self, ciphertext: str) -> bytes:
        payload = {"ciphertext": ciphertext}
        resp = self._request("POST", f"decrypt/{self._key_name}", json=payload)
        b64_plain = resp["data"]["plaintext"]
        return base64.b64decode(b64_plain)

    def rotate_key(self) -> int:
        with self._lock:
            self._request("POST", f"keys/{self._key_name}/rotate")
            new_version = self.get_latest_key_version()
            self._record_audit("ROTATE_KEY", "system", {"new_version": new_version})
            logger.info(f"Key '{self._key_name}' rotated to version {new_version}")
            return new_version

    def rewrap(self, ciphertext: str) -> str:
        payload = {"ciphertext": ciphertext}
        resp = self._request("POST", f"rewrap/{self._key_name}", json=payload)
        return resp["data"]["ciphertext"]

    def backup_key(self, version: int | None = None) -> dict:
        path = f"backup/{self._key_name}"
        if version:
            path += f"/{version}"
        resp = self._request("GET", path)
        return resp["data"]

    def restore_key(self, backup_data: dict) -> None:
        self._request("POST", f"restore/{self._key_name}", json=backup_data)
        self._record_audit("RESTORE_KEY", "system", {})
        logger.info(f"Key '{self._key_name}' restored from backup")

    def _start_rotation_monitor(self) -> None:
        def monitor():
            self._running = True
            while self._running:
                try:
                    metadata = self.get_key_metadata()
                    latest_version = metadata["latest_version"]
                    versions = metadata.get("keys", {})
                    latest_info = versions.get(str(latest_version), {})
                    creation_time = latest_info.get("creation_time")
                    if creation_time:
                        created = datetime.fromtimestamp(creation_time)
                        if datetime.utcnow() - created > self._rotation_interval:
                            self.rotate_key()
                except Exception as e:
                    logger.error(f"Rotation monitor error: {e}")
                time.sleep(86400)

        self._rotation_thread = threading.Thread(target=monitor, daemon=True)
        self._rotation_thread.start()
        self._record_audit("START_ROTATION_MONITOR", "system", {})

    def stop_monitor(self) -> None:
        self._running = False
        if self._rotation_thread:
            self._rotation_thread.join(timeout=5)
        self._record_audit("STOP_MONITOR", "system", {})

    def generate_data_key(self, context: str | None = None) -> dict:
        payload = {}
        if context:
            payload["context"] = base64.b64encode(context.encode()).decode()
        resp = self._request("POST", f"datakey/{self._key_name}", json=payload)
        return {
            "plaintext": base64.b64decode(resp["data"]["plaintext"]),
            "ciphertext": resp["data"]["ciphertext"],
        }

    def health_check(self) -> dict:
        try:
            test_plain = b"health_check"
            enc = self.encrypt(test_plain)
            dec = self.decrypt(enc["ciphertext"])
            healthy = dec == test_plain
            return {
                "healthy": healthy,
                "key_name": self._key_name,
                "latest_version": self.get_latest_key_version(),
                "vault_addr": self._vault_addr,
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    def generate_report(self) -> dict:
        versions = self.get_key_versions()
        return {
            "key_name": self._key_name,
            "latest_version": self.get_latest_key_version(),
            "total_versions": len(versions),
            "auto_rotate_enabled": self._auto_rotate,
            "rotation_interval_days": self._rotation_interval.days,
            "health": self.health_check(),
            "version": self._version,
        }

    def to_json(self, file_path: str) -> None:
        data = self.generate_report()
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self._vault_addr:
            errors.append("vault_addr is required")
        if not self._token:
            errors.append("token is required")
        if self._rotation_interval.days <= 0:
            errors.append("rotation_interval_days must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "vault_addr": self._vault_addr,
            "transit_mount": self._transit_mount,
            "key_name": self._key_name,
            "rotation_interval_days": self._rotation_interval.days,
            "verify_tls": self._verify,
            "auto_rotate_enabled": self._auto_rotate,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VaultKeyManager:
        instance = cls(
            vault_addr=data["vault_addr"],
            token="",  # token tidak disimpan di dict
            transit_mount=data.get("transit_mount", "transit"),
            key_name=data.get("key_name", "erp-master-key"),
            rotation_interval_days=data.get("rotation_interval_days", 90),
            verify_tls=data.get("verify_tls", True),
            auto_rotate_enabled=data.get("auto_rotate_enabled", True),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> VaultKeyManager:
        new = VaultKeyManager(
            vault_addr=self._vault_addr,
            token=self._token,
            transit_mount=self._transit_mount,
            key_name=self._key_name,
            rotation_interval_days=self._rotation_interval.days,
            verify_tls=self._verify,
            auto_rotate_enabled=self._auto_rotate,
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "key_name": self._key_name,
            "latest_version": self.get_latest_key_version(),
            "auto_rotate_enabled": self._auto_rotate,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> VaultKeyManager:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        """Reset manager state (for testing)."""
        self.stop_monitor()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        if self._auto_rotate:
            self._start_rotation_monitor()


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    try:
        manager = VaultKeyManager(
            vault_addr="https://vault.example.com:8200",
            token="s.yourtokenhere",
            key_name="erp-master-key",
            auto_rotate_enabled=False,
        )
        print("Vault connected")
        print(f"Latest version: {manager.get_latest_key_version()}")
        data = b"Sensitive accounting data"
        enc_result = manager.encrypt(data)
        print(f"Encrypted: {enc_result['ciphertext'][:50]}...")
        dec = manager.decrypt(enc_result["ciphertext"])
        print(f"Decrypted: {dec.decode()}")
    except KeyManagementError as e:
        print(f"Vault not available (simulated): {e}")
        print("This is expected if Vault is not running.")
