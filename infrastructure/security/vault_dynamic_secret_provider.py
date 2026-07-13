#!/usr/bin/env python3
"""
Module: vault_dynamic_secret_provider.py
Layer: Infrastructure (Security)
Responsibility: Menyediakan akses ke dynamic secrets dari HashiCorp Vault.
               Mendukung lease management, auto-renewal, dan fallback ke
               environment variables jika Vault tidak tersedia. Digunakan
               untuk mengambil kredensial database, API keys, dan secrets lainnya.
Dependencies:
- hvac (python-hvac) optional, fallback ke env
- asyncio, logging
- config.loader_yaml
- infrastructure.telemetry.alert_manager_router
Audit: Setiap akses secret dicatat. Lease renewal dan revoke juga dicatat.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

# Try to import hvac
try:
    import hvac

    VAULT_AVAILABLE = True
except ImportError:
    VAULT_AVAILABLE = False
    hvac = None

# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_VAULT_CONFIG = {
    "url": "http://localhost:8200",
    "token": None,
    "role_id": None,
    "secret_id": None,
    "auth_method": "token",  # token, approle, kubernetes
    "namespace": None,
}

LEASE_RENEWAL_BUFFER_SECONDS = 60  # Renew lease 60 seconds before expiry
LEASE_REVOKE_ON_SHUTDOWN = True

# ============================================================================
# EXCEPTIONS
# ============================================================================


class VaultError(Exception):
    """Base exception untuk Vault provider."""

    pass


class VaultNotAvailableError(VaultError):
    """Vault tidak tersedia (hvac not installed or unreachable)."""

    pass


class SecretNotFoundError(VaultError):
    """Secret tidak ditemukan."""

    pass


class LeaseRenewalError(VaultError):
    """Gagal memperbarui lease."""

    pass


# ============================================================================
# DYNAMIC SECRET PROVIDER
# ============================================================================


class VaultDynamicSecretProvider:
    """
    Provider untuk dynamic secrets dari HashiCorp Vault.

    Fitur:
    - Mengambil secret dari Vault
    - Lease management (auto-renewal)
    - Fallback ke environment variables
    - Multiple auth methods (token, approle)
    - Secret caching
    """

    def __init__(self, config_path: str = "config_files/security_config.yaml"):
        self.config = self._load_config(config_path)
        self._client: hvac.Client | None = None
        self._leases: dict[str, dict[str, Any]] = {}
        self._renewal_task: asyncio.Task | None = None
        self._running = False

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            return config.get("vault", DEFAULT_VAULT_CONFIG)
        except Exception as e:
            logger.warning("External security config load failed: %s", type(e).__name__)
            return DEFAULT_VAULT_CONFIG

    def _get_client(self) -> hvac.Client | None:
        """
        Initialize Vault client.
        """
        if not VAULT_AVAILABLE:
            logger.warning("HVAC not installed, external security disabled")
            return None

        if self._client is not None:
            return self._client

        try:
            client = hvac.Client(
                url=self.config.get("url", DEFAULT_VAULT_CONFIG["url"]),
                token=self.config.get("token"),
                namespace=self.config.get("namespace"),
            )

            # Authenticate if using approle
            auth_method = self.config.get("auth_method", "token")
            if auth_method == "approle":
                role_id = self.config.get("role_id")
                secret_id = self.config.get("secret_id")
                if role_id and secret_id:
                    client.auth.approle.login(role_id=role_id, secret_id=secret_id)

            if client.is_authenticated():
                self._client = client
                logger.info("External security provider connected")
                return client
            else:
                logger.warning("External security provider unavailable, falling back to local")
                return None

        except Exception as e:
            logger.warning("Failed to connect to external security: %s", type(e).__name__)
            return None

    async def get_secret(self, path: str, key: str | None = None) -> Any:
        """
        Get secret from Vault.

        Args:
            path: Vault path (e.g., "secret/data/db_credentials")
            key: Specific key to retrieve (optional)

        Returns:
            Secret value (dict if key is None)
        """
        client = self._get_client()

        if client is None:
            # Fallback to environment variables
            return self._get_from_env(path, key)

        try:
            # Read secret from Vault
            response = client.secrets.kv.v2.read_secret_version(path=path)
            data = response["data"]["data"]

            # Track lease if present
            if "lease_id" in response:
                self._track_lease(response["lease_id"], response.get("lease_duration", 0))

            if key:
                return data.get(key)
            return data

        except Exception as e:
            logger.error("Failed to retrieve data from external provider: %s", type(e).__name__)
            raise SecretNotFoundError(f"Secret not found at {path}: {e}") from e

    def _get_from_env(self, path: str, key: str | None = None) -> Any:
        """
        Fallback to environment variables.
        """
        # Convert path to env var name
        env_name = path.replace("/", "_").replace("-", "_").upper()
        if key:
            env_name = f"{env_name}_{key.upper()}"

        value = os.environ.get(env_name)
        if value:
            # Try to parse JSON
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                # Fallback to raw string if JSON parsing fails
                logger.debug("JSON decode failed for env var %s, returning raw string", env_name)
                return value
        return None

    def _track_lease(self, lease_id: str, lease_duration: int) -> None:
        """
        Track a Vault lease for auto-renewal.
        """
        if lease_id not in self._leases:
            self._leases[lease_id] = {
                "lease_id": lease_id,
                "lease_duration": lease_duration,
                "created_at": datetime.now(UTC),
                "expires_at": datetime.now(UTC) + timedelta(seconds=lease_duration),
                "renewal_count": 0,
            }
            logger.debug("Grant tracked, duration %ds", lease_duration)

    async def renew_lease(self, lease_id: str) -> bool:
        """
        Renew a Vault lease.
        """
        client = self._get_client()
        if client is None:
            return False

        try:
            response = client.sys.renew_lease(lease_id)
            if response:
                lease_info = self._leases.get(lease_id)
                if lease_info:
                    lease_info["expires_at"] = datetime.now(UTC) + timedelta(
                        seconds=lease_info["lease_duration"]
                    )
                    lease_info["renewal_count"] += 1
                logger.debug("Grant renewed")
                return True
        except Exception as e:
            logger.error("Failed to renew grant: %s", type(e).__name__)
        return False

    async def revoke_lease(self, lease_id: str) -> bool:
        """
        Revoke a Vault lease.
        """
        client = self._get_client()
        if client is None:
            return False

        try:
            client.sys.revoke_lease(lease_id)
            if lease_id in self._leases:
                del self._leases[lease_id]
            logger.debug("Grant revoked")
            return True
        except Exception as e:
            logger.error("Failed to revoke grant: %s", type(e).__name__)
            return False

    async def get_database_credentials(self, role_name: str) -> dict[str, str]:
        """
        Get dynamic database credentials.

        Args:
            role_name: Database role name in Vault

        Returns:
            Dict with keys: username, password
        """
        client = self._get_client()
        if client is None:
            # Fallback to env
            return {
                "username": os.environ.get(f"DB_{role_name.upper()}_USERNAME", ""),
                "password": os.environ.get(f"DB_{role_name.upper()}_PASSWORD", ""),
            }

        try:
            response = client.secrets.database.generate_credentials(role_name)
            return {
                "username": response["data"]["username"],
                "password": response["data"]["password"],
            }
        except Exception as e:
            logger.error("Failed to get database access: %s", type(e).__name__)
            raise VaultError(f"Failed to get database credentials: {e}") from e

    async def get_aws_credentials(self, role_name: str) -> dict[str, str]:
        """
        Get dynamic AWS credentials.
        """
        client = self._get_client()
        if client is None:
            return {
                "access_key": os.environ.get("AWS_ACCESS_KEY_ID", ""),
                "secret_key": os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
            }

        try:
            response = client.secrets.aws.generate_credentials(role_name)
            return {
                "access_key": response["data"]["access_key"],
                "secret_key": response["data"]["secret_key"],
                "security_token": response["data"].get("security_token"),
            }
        except Exception as e:
            logger.error("Failed to get AWS access: %s", type(e).__name__)
            raise VaultError(f"Failed to get AWS credentials: {e}") from e

    async def get_transit_key(self, key_name: str) -> dict[str, Any]:
        """
        Get encryption key from Vault Transit engine.
        """
        client = self._get_client()
        if client is None:
            raise VaultNotAvailableError("Vault not available for transit operations")

        try:
            response = client.secrets.transit.read_key(key_name)
            return response["data"]
        except Exception as e:
            logger.error("Failed to get crypto material: %s", type(e).__name__)
            raise VaultError(f"Failed to get transit key: {e}") from e

    async def encrypt_with_transit(self, key_name: str, plaintext: str) -> str:
        """
        Encrypt data using Vault Transit engine.
        """
        client = self._get_client()
        if client is None:
            raise VaultNotAvailableError("Vault not available for transit operations")

        import base64

        try:
            response = client.secrets.transit.encrypt_data(
                name=key_name, plaintext=base64.b64encode(plaintext.encode()).decode()
            )
            return response["data"]["ciphertext"]
        except Exception as e:
            logger.error("Failed to encrypt: %s", type(e).__name__)
            raise VaultError(f"Failed to encrypt: {e}") from e

    async def decrypt_with_transit(self, key_name: str, ciphertext: str) -> str:
        """
        Decrypt data using Vault Transit engine.
        """
        client = self._get_client()
        if client is None:
            raise VaultNotAvailableError("Vault not available for transit operations")

        import base64

        try:
            response = client.secrets.transit.decrypt_data(name=key_name, ciphertext=ciphertext)
            return base64.b64decode(response["data"]["plaintext"]).decode()
        except Exception as e:
            logger.error("Failed to decrypt: %s", type(e).__name__)
            raise VaultError(f"Failed to decrypt: {e}") from e

    async def start_lease_renewal(self) -> None:
        """
        Start background task to renew leases.
        """
        if self._renewal_task is not None:
            logger.warning("Renewal already running")
            return

        self._running = True
        self._renewal_task = asyncio.create_task(self._renewal_loop())
        logger.info("Grant renewal started")

    async def _renewal_loop(self) -> None:
        """
        Background loop for lease renewal.
        """
        while self._running:
            try:
                await asyncio.sleep(60)  # Check every minute

                now = datetime.now(UTC)
                for lease_id, lease_info in list(self._leases.items()):
                    expires_at = lease_info["expires_at"]
                    lease_duration = lease_info["lease_duration"]

                    # Renew if within buffer window
                    if (expires_at - now).total_seconds() <= LEASE_RENEWAL_BUFFER_SECONDS:
                        await self.renew_lease(lease_id)

            except asyncio.CancelledError:
                logger.debug("Lease renewal loop cancelled")
                break
            except Exception as e:
                logger.error("Error in renewal loop: %s", type(e).__name__)

    async def stop_lease_renewal(self) -> None:
        """
        Stop lease renewal and revoke leases.
        """
        self._running = False
        if self._renewal_task:
            self._renewal_task.cancel()
            try:
                await self._renewal_task
            except asyncio.CancelledError:
                logger.debug("Lease renewal task cancelled during shutdown")
                pass
            self._renewal_task = None

        # Revoke all leases if configured
        if LEASE_REVOKE_ON_SHUTDOWN:
            for lease_id in list(self._leases.keys()):
                await self.revoke_lease(lease_id)

        logger.info("Grant renewal stopped")

    async def is_healthy(self) -> bool:
        """
        Check if Vault is healthy and authenticated.
        """
        client = self._get_client()
        if client is None:
            return False
        return client.is_authenticated()


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_vault_provider: VaultDynamicSecretProvider | None = None


async def get_vault_provider() -> VaultDynamicSecretProvider:
    """Get singleton instance of VaultDynamicSecretProvider."""
    global _vault_provider
    if _vault_provider is None:
        _vault_provider = VaultDynamicSecretProvider()
    return _vault_provider


# ============================================================================
# FASTAPI DEPENDENCY
# ============================================================================


async def get_vault_dep():
    """FastAPI dependency for Vault provider."""
    return await get_vault_provider()


# ============================================================================
# EXPORTS
# ============================================================================

VaultSecretProvider = VaultDynamicSecretProvider

__all__ = [
    "LeaseRenewalError",
    "SecretNotFoundError",
    "VaultDynamicSecretProvider",
    "VaultError",
    "VaultNotAvailableError",
    "VaultSecretProvider",
    "get_vault_dep",
    "get_vault_provider",
]
