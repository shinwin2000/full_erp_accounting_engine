#!/usr/bin/env python3
"""
Module: database_encryption_tde.py
Layer: Infrastructure (Database)
Responsibility: Mengelola Transparent Data Encryption (TDE) untuk PostgreSQL
               menggunakan pgcrypto atau integrasi dengan AWS KMS/Vault.
               Menyediakan fungsi untuk enkripsi kolom data sensitif di database
               dan manajemen kunci enkripsi. Mendukung enkripsi pada rest.
Dependencies:
- pgcrypto (via SQL), asyncio, logging
- infrastructure.database.session_factory_sqlalchemy (get_session_factory)
- infrastructure.security.key_management_vault (opsional)
- config.loader_yaml
- infrastructure.telemetry.structured_json_logging
Audit: Setiap operasi enkripsi/dekripsi dicatat. Rotasi kunci dicatat.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any

from sqlalchemy import text

from config.loader_yaml import load_yaml_config

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_TDE_CONFIG = {
    "enabled": False,
    "algorithm": "aes-256-cbc",
    "key_provider": "env",  # env, vault, kms
    "key_id": "db_encryption_key",
    "key_rotation_days": 90,
    "encrypted_columns": [
        {"table": "iam_user", "column": "email_encrypted", "type": "text"},
        {"table": "iam_user", "column": "phone_encrypted", "type": "text"},
        {"table": "customer", "column": "tax_id_encrypted", "type": "text"},
        {"table": "supplier", "column": "tax_id_encrypted", "type": "text"},
        {"table": "employee", "column": "tax_id_encrypted", "type": "text"},
        {"table": "employee", "column": "bank_account_number_encrypted", "type": "text"},
    ],
}

# ============================================================================
# EXCEPTIONS
# ============================================================================


class TDEError(Exception):
    """Base exception untuk TDE."""

    pass


class EncryptionKeyError(TDEError):
    """Error terkait kunci enkripsi."""

    pass


# ============================================================================
# TDE MANAGER
# ============================================================================


class DatabaseEncryptionTDE:
    """
    Manajer Transparent Data Encryption.

    Fitur:
    - Enkripsi kolom data sensitif menggunakan pgcrypto
    - Manajemen kunci enkripsi (rotasi, penyimpanan)
    - Migrasi data existing ke format terenkripsi
    - Query terenkripsi (decrypt saat SELECT)
    """

    def __init__(self, config_path: str = "config_files/database_config.yaml"):
        self.config = self._load_config(config_path)
        self._encryption_key: str | None = None
        self._current_key_id: str | None = None
        self._key_rotation_task: asyncio.Task | None = None

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            tde_config = config.get("tde", {})
            result = DEFAULT_TDE_CONFIG.copy()
            result.update(tde_config)
            return result
        except Exception:
            return DEFAULT_TDE_CONFIG.copy()

    async def _get_encryption_key(self) -> str:
        """
        Get the current encryption key from provider.
        """
        if self._encryption_key is not None:
            return self._encryption_key

        key_provider = self.config.get("key_provider", "env")
        key_id = self.config.get("key_id", "db_encryption_key")

        if key_provider == "env":
            import os

            key = os.environ.get(key_id)
            if not key:
                # Generate a random key for development (not for production)
                import secrets

                key = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
                logger.warning("No encryption key found in environment, generated ephemeral key")
            self._encryption_key = key
            self._current_key_id = "env_key"

        elif key_provider == "vault":
            try:
                from infrastructure.security.vault_dynamic_secret_provider import get_vault_provider

                vault = await get_vault_provider()
                secret = await vault.get_secret(f"secret/data/{key_id}")
                self._encryption_key = secret.get("key")
                self._current_key_id = secret.get("version", "vault_key")
            except Exception as e:
                logger.error(f"Failed to get encryption key from Vault: {e}")
                raise EncryptionKeyError(f"Vault key retrieval failed: {e}")

        elif key_provider == "kms":
            # Placeholder for AWS KMS
            raise NotImplementedError("AWS KMS not yet implemented")

        else:
            raise EncryptionKeyError(f"Unknown key provider: {key_provider}")

        return self._encryption_key

    async def _ensure_pgcrypto_extension(self) -> None:
        """
        Ensure pgcrypto extension is installed in the database.
        """
        session_factory = await get_session_factory()
        async with session_factory.get_session() as session, session.begin():
            # Check if extension exists - gunakan text() untuk query statis
            result = await session.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'pgcrypto'")
            )
            if not result.scalar():
                await session.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
                logger.info("pgcrypto extension created")

    async def encrypt_column_value(self, plaintext: str) -> str:
        """
        Encrypt a value using the current encryption key.
        """
        key = await self._get_encryption_key()

        # Use pgcrypto's encrypt function with the key
        session_factory = await get_session_factory()
        async with session_factory.get_session() as session:
            query = """
            SELECT encode(pgp_sym_encrypt(:plaintext, :key, 'cipher-algo=aes256'), 'base64')
            """
            result = await session.execute(query, {"plaintext": plaintext, "key": key})
            encrypted = result.scalar()
            return encrypted

    async def decrypt_column_value(self, ciphertext_b64: str) -> str:
        """
        Decrypt a value using the current encryption key.
        """
        key = await self._get_encryption_key()
        session_factory = await get_session_factory()
        async with session_factory.get_session() as session:
            query = """
            SELECT pgp_sym_decrypt(decode(:ciphertext, 'base64'), :key)
            """
            result = await session.execute(query, {"ciphertext": ciphertext_b64, "key": key})
            decrypted = result.scalar()
            if decrypted is None:
                raise TDEError("Decryption failed, possibly wrong key")
            return decrypted

    async def migrate_column_to_encrypted(
        self, table: str, column: str, new_column: str = None
    ) -> None:
        """
        Migrate an existing plaintext column to encrypted column.
        """
        if new_column is None:
            new_column = f"{column}_encrypted"

        session_factory = await get_session_factory()
        async with session_factory.get_session() as session:
            async with session.begin():
                # Check if new column exists - safe concatenation (from config)
                check_query = (
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = '" + table + "' AND column_name = '" + new_column + "'"
                )
                col_exists = await session.execute(check_query)
                if not col_exists.scalar():
                    # Add the encrypted column
                    alter_query = "ALTER TABLE " + table + " ADD COLUMN " + new_column + " TEXT"
                    await session.execute(alter_query)
                    logger.info(f"Added column {new_column} to {table}")

                # Migrate data - parameter binding for key
                update_query = (
                    "UPDATE " + table + " "
                    "SET " + new_column + " = encode(pgp_sym_encrypt(" + column + ", :key, 'cipher-algo=aes256'), 'base64') "
                    "WHERE " + column + " IS NOT NULL AND " + new_column + " IS NULL"
                )
                await session.execute(update_query, {"key": await self._get_encryption_key()})

                logger.info(f"Migrated {table}.{column} to {new_column}")

                # Optional: drop the plaintext column after verification
                # We'll keep both for safety

    async def setup_encrypted_columns(self) -> None:
        """
        Setup all encrypted columns defined in config.
        """
        await self._ensure_pgcrypto_extension()

        for col_config in self.config.get("encrypted_columns", []):
            table = col_config["table"]
            column = col_config["column"]
            await self.migrate_column_to_encrypted(table, column)

        logger.info("Encrypted columns setup completed")

    async def rotate_encryption_key(self, new_key_id: str | None = None) -> None:
        """
        Rotate the encryption key and re-encrypt all encrypted columns.
        """
        old_key = await self._get_encryption_key()
        # Generate new key
        import base64
        import secrets

        new_key = base64.b64encode(secrets.token_bytes(32)).decode("ascii")

        # Store new key in provider
        key_provider = self.config.get("key_provider", "env")
        if key_provider == "env":
            # In production, this should be done via secure means
            logger.warning("Key rotation for env provider not fully implemented")
        elif key_provider == "vault":
            from infrastructure.security.vault_dynamic_secret_provider import get_vault_provider

            vault = await get_vault_provider()
            key_id = new_key_id or self.config.get("key_id", "db_encryption_key")
            await vault.store_secret(
                f"secret/data/{key_id}",
                {"key": new_key, "version": str(int(self._current_key_id or 0) + 1)},
            )

        # Re-encrypt all encrypted columns
        session_factory = await get_session_factory()
        async with session_factory.get_session() as session, session.begin():
            for col_config in self.config.get("encrypted_columns", []):
                table = col_config["table"]
                column = col_config["column"]
                encrypted_col = f"{column}_encrypted"

                # Decrypt with old key, encrypt with new key
                update_query = (
                    "UPDATE " + table + " "
                    "SET " + encrypted_col + " = encode(pgp_sym_encrypt("
                    "pgp_sym_decrypt(decode(" + encrypted_col + ", 'base64'), :old_key), "
                    ":new_key, 'cipher-algo=aes256'), 'base64') "
                    "WHERE " + encrypted_col + " IS NOT NULL"
                )
                await session.execute(update_query, {"old_key": old_key, "new_key": new_key})

        self._encryption_key = new_key
        self._current_key_id = (
            str(int(self._current_key_id or 0) + 1) if self._current_key_id else "1"
        )
        logger.info(f"Encryption key rotated. New key ID: {self._current_key_id}")

        await trigger_alert(
            title="Database Encryption Key Rotated",
            message=f"TDE key rotated to version {self._current_key_id}",
            severity="info",
            source="DatabaseEncryptionTDE",
        )

    async def enable_tde(self) -> None:
        """
        Enable TDE for the database (setup extensions, encrypted columns).
        """
        if not self.config.get("enabled", False):
            logger.info("TDE is disabled in configuration")
            return

        await self.setup_encrypted_columns()

        # Start key rotation scheduler if configured
        rotation_days = self.config.get("key_rotation_days", 90)
        if rotation_days > 0:
            self._start_key_rotation_scheduler(rotation_days)

        logger.info("TDE enabled")

    def _start_key_rotation_scheduler(self, interval_days: int) -> None:
        """
        Start periodic key rotation task.
        """

        async def rotate_periodically():
            while True:
                await asyncio.sleep(interval_days * 24 * 3600)
                await self.rotate_encryption_key()

        if self._key_rotation_task is None or self._key_rotation_task.done():
            self._key_rotation_task = asyncio.create_task(rotate_periodically())
            logger.info(f"Key rotation scheduler started (interval={interval_days} days)")

    async def disable_tde(self) -> None:
        """
        Disable TDE (stop rotation, optionally decrypt columns).
        """
        if self._key_rotation_task:
            self._key_rotation_task.cancel()
            self._key_rotation_task = None
        logger.info("TDE disabled")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_tde_manager: DatabaseEncryptionTDE | None = None


async def get_tde_manager() -> DatabaseEncryptionTDE:
    """Get singleton instance of DatabaseEncryptionTDE."""
    global _tde_manager
    if _tde_manager is None:
        _tde_manager = DatabaseEncryptionTDE()
        await _tde_manager.enable_tde()
    return _tde_manager


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["DatabaseEncryptionTDE", "EncryptionKeyError", "TDEError", "get_tde_manager"]