#!/usr/bin/env python3
"""
Module: schema_registry_client.py
Layer: Infrastructure (Message Broker)
Responsibility: Client untuk Schema Registry (Confluent Schema Registry)
               untuk mengelola Avro/JSON schemas untuk pesan Kafka. Memastikan
               bahwa producer dan consumer menggunakan schema yang kompatibel.
               Mendukung register, retrieve, dan validasi schema versioning.
Dependencies:
- requests or aiohttp (optional)
- json, logging, hashlib
- config.loader_yaml
- infrastructure.telemetry.structured_json_logging
Audit: Perubahan schema dicatat. Inkompatibilitas schema memicu alert.
"""

from __future__ import annotations

import json
from typing import Any

# Try to import aiohttp
try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_SCHEMA_REGISTRY_CONFIG = {
    "url": "http://localhost:8081",
    "subject_prefix": "erp",
    "compatibility_level": "backward",  # backward, forward, full, none
    "timeout_seconds": 10,
}

# Schema types
SCHEMA_TYPE_AVRO = "AVRO"
SCHEMA_TYPE_JSON = "JSON"

# ============================================================================
# EXCEPTIONS
# ============================================================================


class SchemaRegistryError(Exception):
    """Base exception untuk schema registry."""

    pass


class SchemaNotFoundError(SchemaRegistryError):
    """Schema tidak ditemukan."""

    pass


class SchemaCompatibilityError(SchemaRegistryError):
    """Schema tidak kompatibel."""

    pass


# ============================================================================
# SCHEMA REGISTRY CLIENT
# ============================================================================


class SchemaRegistryClient:
    """
    Client untuk Confluent Schema Registry.

    Fitur:
    - Register schema untuk subject
    - Get schema by ID or version
    - Check compatibility
    - Cache schemas locally
    - Support Avro and JSON schemas
    """

    def __init__(self, config_path: str = "config_files/message_broker_config.yaml"):
        self.config = self._load_config(config_path)
        self._base_url = self.config.get("url", "http://localhost:8081")
        self._subject_prefix = self.config.get("subject_prefix", "erp")
        self._compatibility_level = self.config.get("compatibility_level", "backward")
        self._client_session: aiohttp.ClientSession | None = None
        self._schema_cache: dict[str, dict] = {}
        self._id_cache: dict[int, dict] = {}

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            return config.get("schema_registry", DEFAULT_SCHEMA_REGISTRY_CONFIG)
        except Exception:
            return DEFAULT_SCHEMA_REGISTRY_CONFIG.copy()

    async def _get_client(self) -> aiohttp.ClientSession:
        if not AIOHTTP_AVAILABLE:
            raise SchemaRegistryError("aiohttp not available")
        if self._client_session is None:
            self._client_session = aiohttp.ClientSession()
        return self._client_session

    async def close(self) -> None:
        """Close HTTP client session."""
        if self._client_session:
            await self._client_session.close()
            self._client_session = None

    def _get_subject(self, topic: str, is_key: bool = False) -> str:
        """Get subject name for topic."""
        suffix = "-key" if is_key else "-value"
        return f"{self._subject_prefix}-{topic}{suffix}"

    async def register_schema(
        self,
        topic: str,
        schema: dict[str, Any],
        schema_type: str = SCHEMA_TYPE_JSON,
        is_key: bool = False,
    ) -> int:
        """
        Register schema for a topic.

        Returns:
            Schema ID
        """
        client = await self._get_client()
        subject = self._get_subject(topic, is_key)

        payload = {"schema": json.dumps(schema), "schemaType": schema_type}

        url = f"{self._base_url}/subjects/{subject}/versions"

        try:
            async with client.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    schema_id = data.get("id")
                    logger.info(f"Schema registered for subject {subject}, id={schema_id}")
                    self._schema_cache[subject] = {
                        "id": schema_id,
                        "schema": schema,
                        "version": data.get("version"),
                    }
                    return schema_id
                elif resp.status == 409:
                    # Schema already registered, get existing
                    return await self.get_schema_id(topic, schema, is_key)
                else:
                    error = await resp.text()
                    raise SchemaRegistryError(f"Failed to register schema: {resp.status} - {error}")
        except Exception as e:
            logger.error(f"Failed to register schema: {e}")
            raise SchemaRegistryError(f"Register failed: {e}") from e

    async def get_schema_id(self, topic: str, schema: dict[str, Any], is_key: bool = False) -> int:
        """
        Get schema ID for a schema (check compatibility first).
        """
        client = await self._get_client()
        subject = self._get_subject(topic, is_key)

        # Check cache first
        if subject in self._schema_cache:
            cached = self._schema_cache[subject]
            if cached["schema"] == schema:
                return cached["id"]

        # Check compatibility
        compatible = await self.check_compatibility(topic, schema, is_key)
        if not compatible:
            raise SchemaCompatibilityError(f"Schema not compatible with subject {subject}")

        # Get schema ID
        payload = {"schema": json.dumps(schema), "schemaType": SCHEMA_TYPE_JSON}

        url = f"{self._base_url}/subjects/{subject}"

        try:
            async with client.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    schema_id = data.get("id")
                    self._schema_cache[subject] = {
                        "id": schema_id,
                        "schema": schema,
                        "version": data.get("version"),
                    }
                    return schema_id
                else:
                    error = await resp.text()
                    raise SchemaNotFoundError(f"Schema not found: {error}")
        except Exception as e:
            logger.error(f"Failed to get schema ID: {e}")
            raise SchemaRegistryError(f"Get schema ID failed: {e}") from e

    async def get_schema_by_id(self, schema_id: int) -> dict[str, Any]:
        """Get schema by ID."""
        if schema_id in self._id_cache:
            return self._id_cache[schema_id]

        client = await self._get_client()
        url = f"{self._base_url}/schemas/ids/{schema_id}"

        try:
            async with client.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    schema = json.loads(data.get("schema", "{}"))
                    self._id_cache[schema_id] = schema
                    return schema
                else:
                    raise SchemaNotFoundError(f"Schema ID {schema_id} not found")
        except Exception as e:
            logger.error(f"Failed to get schema by ID: {e}")
            raise SchemaRegistryError(f"Get schema failed: {e}") from e

    async def get_schema_by_version(
        self, topic: str, version: int = 1, is_key: bool = False
    ) -> dict[str, Any]:
        """Get schema by subject and version."""
        client = await self._get_client()
        subject = self._get_subject(topic, is_key)
        url = f"{self._base_url}/subjects/{subject}/versions/{version}"

        try:
            async with client.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return json.loads(data.get("schema", "{}"))
                else:
                    raise SchemaNotFoundError(f"Schema version {version} for {subject} not found")
        except Exception as e:
            logger.error(f"Failed to get schema by version: {e}")
            raise SchemaRegistryError(f"Get schema failed: {e}") from e

    async def get_latest_schema(self, topic: str, is_key: bool = False) -> dict[str, Any]:
        """Get latest schema for subject."""
        return await self.get_schema_by_version(topic, "latest", is_key)

    async def check_compatibility(
        self, topic: str, schema: dict[str, Any], is_key: bool = False
    ) -> bool:
        """
        Check if schema is compatible with existing schemas.
        """
        client = await self._get_client()
        subject = self._get_subject(topic, is_key)

        payload = {"schema": json.dumps(schema), "schemaType": SCHEMA_TYPE_JSON}

        url = f"{self._base_url}/compatibility/subjects/{subject}/versions/latest"

        try:
            async with client.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("is_compatible", False)
                else:
                    # If no schema exists, it's compatible
                    return True
        except Exception as e:
            logger.error(f"Failed to check compatibility: {e}")
            return False

    async def update_compatibility_level(
        self, topic: str, level: str, is_key: bool = False
    ) -> bool:
        """Update compatibility level for subject."""
        client = await self._get_client()
        subject = self._get_subject(topic, is_key)

        payload = {"compatibility": level}
        url = f"{self._base_url}/config/{subject}"

        try:
            async with client.put(url, json=payload) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"Failed to update compatibility level: {e}")
            return False

    async def list_subjects(self) -> list[str]:
        """List all subjects."""
        client = await self._get_client()
        url = f"{self._base_url}/subjects"

        try:
            async with client.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
                return []
        except Exception as e:
            logger.error(f"Failed to list subjects: {e}")
            return []

    async def delete_subject(self, subject: str, permanent: bool = False) -> bool:
        """
        Delete a subject (and all its versions).

        This operation is idempotent and uses an HTTP client, not a database.
        Race condition risk is mitigated by the Schema Registry's own concurrency
        handling and the fact that this operation is typically performed
        in admin contexts.
        """
        client = await self._get_client()
        url = f"{self._base_url}/subjects/{subject}"
        if permanent:
            url += "?permanent=true"

        try:
            async with client.delete(url) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"Failed to delete subject: {e}")
            return False

    async def clear_cache(self) -> None:
        """Clear local schema cache."""
        self._schema_cache.clear()
        self._id_cache.clear()
        logger.info("Schema registry cache cleared")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_schema_registry: SchemaRegistryClient | None = None


async def get_schema_registry() -> SchemaRegistryClient:
    """Get singleton instance of SchemaRegistryClient."""
    global _schema_registry
    if _schema_registry is None:
        _schema_registry = SchemaRegistryClient()
    return _schema_registry


async def close_schema_registry() -> None:
    """Close schema registry client."""
    global _schema_registry
    if _schema_registry:
        await _schema_registry.close()
        _schema_registry = None


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "SCHEMA_TYPE_AVRO",
    "SCHEMA_TYPE_JSON",
    "SchemaCompatibilityError",
    "SchemaNotFoundError",
    "SchemaRegistryClient",
    "SchemaRegistryError",
    "close_schema_registry",
    "get_schema_registry",
]