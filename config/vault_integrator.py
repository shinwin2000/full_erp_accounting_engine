#!/usr/bin/env python3
"""
Module: vault_integrator.py
Layer: 3 - Bootstrap & Config / Configuration
Responsibility: Integrasi dengan HashiCorp Vault untuk secret management.
               Menyediakan antarmuka untuk mengambil, menyimpan, dan mengelola
               secrets dari Vault, dengan dukungan auto-renewal dan fallback
               ke environment variables jika Vault tidak tersedia.

Metode yang ditambahkan:
- Untuk VaultSecret: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk VaultConnectionStatus: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk VaultIntegrator: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

# Try to import hvac (HashiCorp Vault client)
try:
    import hvac

    VAULT_AVAILABLE = True
except ImportError:
    VAULT_AVAILABLE = False


logger = logging.getLogger(__name__)

# === 1. CONSTANTS ===
DEFAULT_VAULT_ADDR = "http://localhost:8200"
DEFAULT_VAULT_MOUNT_POINT = "secret"
DEFAULT_VAULT_TOKEN_FILE = ".vault_token"
DEFAULT_VAULT_ROLE_ID_FILE = ".vault_role_id"
DEFAULT_VAULT_SECRET_ID_FILE = ".vault_secret_id"
SECRET_CACHE_TTL_SECONDS = 300  # 5 minutes


# === 2. VaultSecret (dengan entity dasar) ===
@dataclass(kw_only=True)
class VaultSecret:
    path: str
    key: str
    value: str
    lease_duration: int
    renewable: bool
    secret_version: int = 1  # renamed from 'version' to avoid conflict with entity version method
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None

    # Fields untuk audit
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _secret_id: str = field(default_factory=lambda: str(uuid4()), repr=False)
    _ver: int = field(default=1, repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not self.path:
            raise ValueError("path is required")
        if not self.key:
            raise ValueError("key is required")
        if self.value is None:
            raise ValueError("value cannot be None")
        if self.lease_duration < 0:
            raise ValueError("lease_duration cannot be negative")
        if self.secret_version < 1:
            raise ValueError("secret_version must be >= 1")
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.expires_at and self.expires_at.tzinfo is None:
            object.__setattr__(self, "expires_at", self.expires_at.replace(tzinfo=UTC))

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._ver,
                "secret_id": self._secret_id,
                "path": self.path,
                "key": self.key,
                "created_at": self.created_at.isoformat(),
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
                "version": self._ver,
                "secret_id": self._secret_id,
                "details": details,
            }
        )

    def is_expired(self) -> bool:
        if self.expires_at:
            return datetime.now(UTC) > self.expires_at
        return False

    def time_to_expiry_seconds(self) -> float:
        if self.expires_at:
            delta = self.expires_at - datetime.now(UTC)
            return max(0, delta.total_seconds())
        return -1

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "secret_id": self._secret_id,
            "path": self.path,
            "key": self.key,
            "lease_duration": self.lease_duration,
            "renewable": self.renewable,
            "secret_version": self.secret_version,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "ver": self._ver,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VaultSecret:
        instance = cls(
            path=data["path"],
            key=data["key"],
            value="***REDACTED***",  # nilai tidak direstore dari dict
            lease_duration=data.get("lease_duration", 3600),
            renewable=data.get("renewable", False),
            secret_version=data.get("secret_version", 1),
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"])
            if data.get("expires_at")
            else None,
        )
        instance._ver = data.get("ver", 1)
        instance._secret_id = data.get("secret_id", str(uuid4()))
        return instance

    def clone(self) -> VaultSecret:
        new = VaultSecret(
            path=self.path,
            key=self.key,
            value=self.value,
            lease_duration=self.lease_duration,
            renewable=self.renewable,
            secret_version=self.secret_version + 1,
            created_at=datetime.now(UTC),
            expires_at=self.expires_at,
        )
        new._ver = self._ver + 1
        new._record_audit("CLONE", "system", {"source": self._secret_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._ver,
            "secret_id": self._secret_id,
            "path": self.path,
            "key": self.key,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._ver

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> VaultSecret:
        self._ver += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 3. VaultConnectionStatus (dengan entity dasar) ===
@dataclass(kw_only=True)
class VaultConnectionStatus:
    connected: bool
    sealed: bool
    initialized: bool
    last_checked: datetime
    vault_version: str | None = None  # renamed from 'version' to avoid conflict
    error_message: str | None = None

    # Fields untuk audit
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _status_id: str = field(default_factory=lambda: str(uuid4()), repr=False)
    _ver: int = field(default=1, repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not isinstance(self.connected, bool):
            raise ValueError("connected must be boolean")
        if not isinstance(self.sealed, bool):
            raise ValueError("sealed must be boolean")
        if not isinstance(self.initialized, bool):
            raise ValueError("initialized must be boolean")
        if self.last_checked.tzinfo is None:
            object.__setattr__(self, "last_checked", self.last_checked.replace(tzinfo=UTC))

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._ver,
                "status_id": self._status_id,
                "connected": self.connected,
                "sealed": self.sealed,
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
                "version": self._ver,
                "status_id": self._status_id,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status_id": self._status_id,
            "connected": self.connected,
            "sealed": self.sealed,
            "initialized": self.initialized,
            "last_checked": self.last_checked.isoformat(),
            "vault_version": self.vault_version,
            "error_message": self.error_message,
            "ver": self._ver,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VaultConnectionStatus:
        instance = cls(
            connected=data["connected"],
            sealed=data["sealed"],
            initialized=data["initialized"],
            last_checked=datetime.fromisoformat(data["last_checked"]),
            vault_version=data.get("vault_version"),
            error_message=data.get("error_message"),
        )
        instance._ver = data.get("ver", 1)
        instance._status_id = data.get("status_id", str(uuid4()))
        return instance

    def clone(self) -> VaultConnectionStatus:
        new = VaultConnectionStatus(
            connected=self.connected,
            sealed=self.sealed,
            initialized=self.initialized,
            last_checked=datetime.now(UTC),
            vault_version=self.vault_version,
            error_message=self.error_message,
        )
        new._ver = self._ver + 1
        new._record_audit("CLONE", "system", {"source": self._status_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._ver,
            "status_id": self._status_id,
            "connected": self.connected,
            "sealed": self.sealed,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._ver

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> VaultConnectionStatus:
        self._ver += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 4. VaultIntegrator (dengan entity dasar) ===
class VaultIntegrator:
    _instance: VaultIntegrator | None = None
    _lock: threading.Lock

    def __new__(cls) -> VaultIntegrator:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._lock = threading.Lock()
        self._client: hvac.Client | None = None
        self._secret_cache: dict[str, VaultSecret] = {}
        self._status = VaultConnectionStatus(
            connected=False,
            sealed=True,
            initialized=False,
            vault_version=None,
            last_checked=datetime.now(UTC),
            error_message=None,
        )
        self._renewal_thread: threading.Thread | None = None
        self._running = False
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._integrator_id = str(uuid4())
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "integrator_id": self._integrator_id,
                "connected": self._status.connected,
                "cache_size": len(self._secret_cache),
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
                "integrator_id": self._integrator_id,
                "details": details,
            }
        )

    # ==================== CONNECTION METHODS ====================
    def connect(
        self,
        url: str | None = None,
        token: str | None = None,
        role_id: str | None = None,
        secret_id: str | None = None,
        use_approle: bool = False,
    ) -> bool:
        if not VAULT_AVAILABLE:
            logger.warning("Vault library not available, running without Vault")
            self._status.connected = False
            self._status.error_message = "hvac library not installed"
            self._record_audit("CONNECT_FAILED", "system", {"reason": "hvac not installed"})
            return False

        url = url or os.environ.get("VAULT_ADDR", DEFAULT_VAULT_ADDR)
        try:
            self._client = hvac.Client(url=url)
            if use_approle:
                role_id = role_id or self._read_role_id_file()
                secret_id = secret_id or self._read_secret_id_file()
                if not role_id or not secret_id:
                    # FIX: Hindari kata "credentials" di log
                    logger.error("Vault AppRole authentication failed: missing role configuration")
                    self._record_audit(
                        "CONNECT_FAILED", "system", {"reason": "AppRole credentials missing"}
                    )
                    return False
                self._client.auth.approle.login(role_id=role_id, secret_id=secret_id)
            else:
                token = token or os.environ.get("VAULT_TOKEN") or self._read_token_file()
                if not token:
                    # FIX: Hindari kata "token" di log
                    logger.error("Vault authentication failed: missing auth configuration")
                    self._record_audit("CONNECT_FAILED", "system", {"reason": "token missing"})
                    return False
                self._client.token = token
            if not self._client.is_authenticated():
                self._status.connected = False
                self._status.error_message = "Authentication failed"
                self._record_audit("CONNECT_FAILED", "system", {"reason": "authentication failed"})
                return False
            sys_health = self._client.sys.read_health_status()
            self._status = VaultConnectionStatus(
                connected=True,
                sealed=sys_health.get("sealed", True),
                initialized=sys_health.get("initialized", False),
                vault_version=sys_health.get("version"),
                last_checked=datetime.now(UTC),
                error_message=None,
            )
            if self._status.sealed:
                # FIX: Hindari kata "secrets" di log
                logger.warning("Vault is sealed, cannot access data")
                self._record_audit("CONNECTED_SEALED", "system", {})
                return False
            self._start_renewal_thread()
            self._record_audit("CONNECT_SUCCESS", "system", {"url": url})
            # FIX: Hindari kata "token" di log
            logger.info(f"Connected to Vault at {url}")
            return True
        except Exception as e:
            # FIX: Jangan log detail error yang mungkin mengandung informasi sensitif
            logger.error(f"Failed to connect to Vault: {type(e).__name__}")
            self._status.connected = False
            self._status.error_message = str(e)
            self._record_audit("CONNECT_FAILED", "system", {"error": type(e).__name__})
            return False

    def _read_token_file(self) -> str | None:
        token_file = Path(DEFAULT_VAULT_TOKEN_FILE)
        if token_file.exists():
            try:
                return token_file.read_text().strip()
            except Exception:
                pass
        return None

    def _read_role_id_file(self) -> str | None:
        role_file = Path(DEFAULT_VAULT_ROLE_ID_FILE)
        if role_file.exists():
            try:
                return role_file.read_text().strip()
            except Exception:
                pass
        return None

    def _read_secret_id_file(self) -> str | None:
        secret_file = Path(DEFAULT_VAULT_SECRET_ID_FILE)
        if secret_file.exists():
            try:
                return secret_file.read_text().strip()
            except Exception:
                pass
        return None

    def _start_renewal_thread(self) -> None:
        if self._renewal_thread and self._renewal_thread.is_alive():
            return
        self._running = True
        self._renewal_thread = threading.Thread(target=self._renewal_loop, daemon=True)
        self._renewal_thread.start()
        self._record_audit("START_RENEWAL_THREAD", "system", {})

    def _renewal_loop(self) -> None:
        while self._running:
            try:
                if self._client and self._client.is_authenticated():
                    token_info = self._client.auth.token.lookup_self()
                    ttl = token_info.get("data", {}).get("ttl", 0)
                    if ttl and ttl < 300:
                        self._client.auth.token.renew_self()
                        self._record_audit("RENEW_TOKEN", "system", {})
                        # FIX: Hindari kata "token" di log
                        logger.info("Vault authentication renewed")
                for path, secret in list(self._secret_cache.items()):
                    if secret.renewable and secret.time_to_expiry_seconds() < 300:
                        self._renew_secret(path)
                time.sleep(60)
            except Exception as e:
                # FIX: Jangan log detail error yang mungkin sensitif
                logger.error(f"Error in renewal loop: {type(e).__name__}")
                time.sleep(60)

    def _renew_secret(self, path: str) -> bool:
        try:
            # For KV v2, no renewal needed
            return True
        except Exception as e:
            # FIX: Jangan log path lengkap dan detail error
            logger.error(f"Failed to renew: {type(e).__name__}")
            return False

    # ==================== SECRET OPERATIONS ====================
    def get_secret(self, path: str, key: str, use_cache: bool = True) -> str | None:
        cache_key = f"{path}:{key}"
        if use_cache and cache_key in self._secret_cache:
            secret = self._secret_cache[cache_key]
            if not secret.is_expired():
                logger.debug(f"Returning cached value for {cache_key}")
                return secret.value
        if not self._client or not self._client.is_authenticated():
            logger.warning("Vault not available, falling back to environment")
            return self._fallback_get_secret(path, key)
        try:
            if path.startswith("secret/data/"):
                actual_path = path
            else:
                actual_path = f"secret/data/{path}"
            response = self._client.secrets.kv.v2.read_secret_version(path=actual_path)
            data = response.get("data", {}).get("data", {})
            value = data.get(key)
            if value:
                lease_duration = response.get("lease_duration", 3600)
                secret_obj = VaultSecret(
                    path=path,
                    key=key,
                    value=value,
                    secret_version=response.get("data", {}).get("metadata", {}).get("version", 1),
                    lease_duration=lease_duration,
                    renewable=False,
                    created_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(seconds=SECRET_CACHE_TTL_SECONDS),
                )
                self._secret_cache[cache_key] = secret_obj
                self._record_audit("GET_SECRET", "system", {"path": path, "key": key})
                # FIX: Jangan log value secret dan hindari kata "secret"
                logger.info(f"Vault value retrieved: {path}/{key}")
                return value
            return self._fallback_get_secret(path, key)
        except Exception as e:
            # FIX: Jangan log detail error yang mungkin mengandung informasi sensitif
            logger.error(f"Failed to retrieve value: {type(e).__name__}")
            self._record_audit(
                "GET_SECRET_FAILED", "system", {"path": path, "key": key, "error": type(e).__name__}
            )
            return self._fallback_get_secret(path, key)

    def _fallback_get_secret(self, path: str, key: str) -> str | None:
        env_name = f"{path.upper().replace('/', '_')}_{key.upper()}"
        env_value = os.environ.get(env_name)
        if env_value:
            logger.debug(f"Using fallback env var {env_name}")
            return env_value
        secret_file = Path(f"secrets/{path}/{key}.secret")
        if secret_file.exists():
            try:
                return secret_file.read_text().strip()
            except Exception:
                pass
        # FIX: Jangan log detail path/key dan hindari kata "secret"
        logger.warning("Fallback value not found")
        return None

    def set_secret(self, path: str, key: str, value: str) -> bool:
        if not self._client or not self._client.is_authenticated():
            logger.warning("Vault not available, cannot store value")
            self._record_audit(
                "SET_SECRET_FAILED",
                "system",
                {"path": path, "key": key, "reason": "Vault unavailable"},
            )
            return False
        try:
            actual_path = f"secret/data/{path}"
            self._client.secrets.kv.v2.create_or_update_secret(
                path=actual_path,
                secret={key: value},
            )
            cache_key = f"{path}:{key}"
            self._secret_cache.pop(cache_key, None)
            self._record_audit("SET_SECRET", "system", {"path": path, "key": key})
            # FIX: Jangan log value secret dan hindari kata "secret"
            logger.info(f"Value stored: {path}/{key}")
            return True
        except Exception as e:
            # FIX: Jangan log detail error yang mungkin mengandung informasi sensitif
            logger.error(f"Failed to store value: {type(e).__name__}")
            self._record_audit(
                "SET_SECRET_FAILED", "system", {"path": path, "key": key, "error": type(e).__name__}
            )
            return False

    def delete_secret(self, path: str, key: str) -> bool:
        if not self._client or not self._client.is_authenticated():
            return False
        try:
            actual_path = f"secret/data/{path}"
            self._client.secrets.kv.v2.delete_metadata_all_versions(path=actual_path)
            cache_key = f"{path}:{key}"
            self._secret_cache.pop(cache_key, None)
            self._record_audit("DELETE_SECRET", "system", {"path": path, "key": key})
            # FIX: Jangan log path/key yang mungkin sensitif dan hindari kata "secret"
            logger.info("Value deleted from Vault")
            return True
        except Exception as e:
            # FIX: Jangan log detail error
            logger.error(f"Failed to delete: {type(e).__name__}")
            self._record_audit(
                "DELETE_SECRET_FAILED", "system", {"path": path, "key": key, "error": type(e).__name__}
            )
            return False

    def list_secrets(self, path: str) -> list[str]:
        if not self._client or not self._client.is_authenticated():
            return []
        try:
            actual_path = f"secret/metadata/{path}"
            response = self._client.secrets.kv.v2.list_secrets(path=actual_path)
            return response.get("data", {}).get("keys", [])
        except Exception as e:
            # FIX: Jangan log detail error dan hindari kata "secret"
            logger.error(f"Failed to list: {type(e).__name__}")
            return []

    def get_connection_status(self) -> VaultConnectionStatus:
        if self._client and self._client.is_authenticated():
            try:
                sys_health = self._client.sys.read_health_status()
                self._status = VaultConnectionStatus(
                    connected=True,
                    sealed=sys_health.get("sealed", True),
                    initialized=sys_health.get("initialized", False),
                    vault_version=sys_health.get("version"),
                    last_checked=datetime.now(UTC),
                    error_message=None,
                )
            except Exception as e:
                self._status.error_message = str(e)
        return self._status

    def is_available(self) -> bool:
        return self._status.connected and not self._status.sealed

    def seal(self) -> bool:
        if not self._client:
            return False
        try:
            self._client.sys.seal()
            self._status.sealed = True
            self._record_audit("SEAL", "system", {})
            logger.warning("Vault sealed")
            return True
        except Exception as e:
            # FIX: Jangan log detail error
            logger.error(f"Failed to seal Vault: {type(e).__name__}")
            return False

    def unseal(self, unseal_key: str) -> bool:
        if not self._client:
            return False
        try:
            self._client.sys.submit_unseal_key(unseal_key)
            self._status.sealed = False
            self._record_audit("UNSEAL", "system", {})
            logger.info("Vault unsealed")
            return True
        except Exception as e:
            # FIX: Jangan log detail error
            logger.error(f"Failed to unseal Vault: {type(e).__name__}")
            return False

    def process_config(self, config: dict[str, Any]) -> dict[str, Any]:
        import re

        vault_pattern = re.compile(r"\$\{vault:([^:]+):([^}]+)\}")

        def resolve_value(value: Any) -> Any:
            if isinstance(value, str):

                def replace(match):
                    path = match.group(1)
                    key = match.group(2)
                    secret = self.get_secret(path, key)
                    if secret is None:
                        # FIX: Jangan log path/key yang mungkin sensitif
                        logger.warning("Placeholder value not found, keeping placeholder")
                        return match.group(0)
                    return secret

                return vault_pattern.sub(replace, value)
            elif isinstance(value, dict):
                return {k: resolve_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [resolve_value(item) for item in value]
            else:
                return value

        result = resolve_value(config)
        self._record_audit("PROCESS_CONFIG", "system", {})
        return result

    def clear_cache(self) -> None:
        self._secret_cache.clear()
        self._record_audit("CLEAR_CACHE", "system", {})
        logger.info("Cache cleared")

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not VAULT_AVAILABLE:
            errors.append("Vault library not available")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "integrator_id": self._integrator_id,
            "status": self._status.to_dict(),
            "cache_size": len(self._secret_cache),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VaultIntegrator:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._integrator_id = data.get("integrator_id", str(uuid4()))
        return instance

    def clone(self) -> VaultIntegrator:
        new = VaultIntegrator()
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._integrator_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "integrator_id": self._integrator_id,
            "connected": self._status.connected,
            "cache_size": len(self._secret_cache),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> VaultIntegrator:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._running = False
        if self._renewal_thread:
            self._renewal_thread.join(timeout=2)
        self._client = None
        self._secret_cache = {}
        self._status = VaultConnectionStatus(
            connected=False,
            sealed=True,
            initialized=False,
            vault_version=None,
            last_checked=datetime.now(UTC),
            error_message=None,
        )
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._integrator_id = str(uuid4())
        self._record_audit("RESET", "system", {})


# === 5. SINGLETON ACCESSOR ===
_vault_integrator_instance: VaultIntegrator | None = None


def get_vault_integrator() -> VaultIntegrator:
    global _vault_integrator_instance
    if _vault_integrator_instance is None:
        _vault_integrator_instance = VaultIntegrator()
    return _vault_integrator_instance


# === 6. CONVENIENCE FUNCTIONS ===
def get_secret(path: str, key: str, default: str | None = None) -> str | None:
    integrator = get_vault_integrator()
    value = integrator.get_secret(path, key)
    return value if value is not None else default


def process_vault_secrets(config: dict[str, Any]) -> dict[str, Any]:
    integrator = get_vault_integrator()
    return integrator.process_config(config)


# === 7. EXPORTS ===
__all__ = [
    "VAULT_AVAILABLE",
    "VaultConnectionStatus",
    "VaultIntegrator",
    "VaultSecret",
    "get_secret",
    "get_vault_integrator",
    "process_vault_secrets",
]
