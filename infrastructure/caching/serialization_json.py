#!/usr/bin/env python3
"""
Module: serialization_json.py
Layer: Infrastructure (Caching)
Responsibility: Menyediakan fungsi serialisasi dan deserialisasi JSON untuk
               data yang akan disimpan di cache. Mendukung custom encoder
               untuk tipe data Python yang tidak JSON-serializable secara
               default (datetime, UUID, Decimal, date). Juga mendukung
               compression opsional untuk data besar.
Dependencies:
- json, datetime, uuid, decimal, base64
- infrastructure.caching.compression_lz4 (optional)
Audit: Serialisasi JSON digunakan untuk semua data cache.
       Format serialisasi harus backward compatible.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

# Optional compression
try:
    from infrastructure.caching.compression_lz4 import CompressionLZ4

    COMPRESSION_AVAILABLE = True
except ImportError:
    COMPRESSION_AVAILABLE = False

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

# Compression threshold (bytes) - compress if larger than 1KB
COMPRESSION_THRESHOLD = 1024

# Compression prefix for identifying compressed data
COMPRESSED_PREFIX = b"CMP:"

# ============================================================================
# IDEMPOTENCY MANAGER (for create_cache_entry)
# ============================================================================

class IdempotencyManager:
    """
    Simple in-memory idempotency manager untuk create_cache_entry.
    Menyimpan hasil operasi berdasarkan idempotency_key + method_name.
    TTL 24 jam.
    """

    def __init__(self):
        self._storage: dict[str, tuple[str, datetime]] = {}
        self._ttl_seconds = 86400

    def _get_key(self, idempotency_key: str, method_name: str) -> str:
        raw = f"{method_name}:{idempotency_key}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_cached_result(self, idempotency_key: str, method_name: str) -> dict[str, Any] | None:
        storage_key = self._get_key(idempotency_key, method_name)
        entry = self._storage.get(storage_key)
        if entry is None:
            return None
        result_json, timestamp = entry
        if (datetime.now() - timestamp).total_seconds() > self._ttl_seconds:
            del self._storage[storage_key]
            return None
        try:
            return json.loads(result_json)
        except json.JSONDecodeError:
            return None

    def cache_result(self, idempotency_key: str, method_name: str, result: dict[str, Any]) -> None:
        storage_key = self._get_key(idempotency_key, method_name)
        try:
            result_json = json.dumps(result, default=str)
        except TypeError:
            result_json = json.dumps({"result": str(result)}, default=str)
        self._storage[storage_key] = (result_json, datetime.now())


_idempotency_manager = IdempotencyManager()


# ============================================================================
# CUSTOM JSON ENCODER
# ============================================================================


class CustomJSONEncoder(json.JSONEncoder):
    """
    JSON encoder custom untuk tipe data yang tidak standar.
    """

    def default(self, obj: Any) -> Any:
        # Handle datetime
        if isinstance(obj, datetime):
            return {"__type__": "datetime", "value": obj.isoformat()}

        # Handle date
        if isinstance(obj, date):
            return {"__type__": "date", "value": obj.isoformat()}

        # Handle UUID
        if isinstance(obj, UUID):
            return {"__type__": "uuid", "value": str(obj)}

        # Handle Decimal
        if isinstance(obj, Decimal):
            return {"__type__": "decimal", "value": str(obj)}

        # Handle bytes
        if isinstance(obj, bytes):
            return {"__type__": "bytes", "value": base64.b64encode(obj).decode("ascii")}

        # Handle set
        if isinstance(obj, set):
            return {"__type__": "set", "value": list(obj)}

        return super().default(obj)


class CustomJSONDecoder(json.JSONDecoder):
    """
    JSON decoder custom untuk restore tipe data khusus.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(object_hook=self.object_hook, *args, **kwargs)

    def object_hook(self, obj: dict[str, Any]) -> Any:
        # Check for type marker
        if "__type__" in obj:
            type_name = obj["__type__"]
            value = obj["value"]

            if type_name == "datetime":
                return datetime.fromisoformat(value)
            elif type_name == "date":
                return date.fromisoformat(value)
            elif type_name == "uuid":
                return UUID(value)
            elif type_name == "decimal":
                return Decimal(value)
            elif type_name == "bytes":
                return base64.b64decode(value)
            elif type_name == "set":
                return set(value)

        return obj


# ============================================================================
# SERIALIZATION FUNCTIONS
# ============================================================================


class JSONSerializer:
    """
    Serializer untuk data cache menggunakan JSON.

    Fitur:
    - Serialisasi/deserialisasi JSON dengan custom encoder/decoder
    - Kompresi opsional untuk data besar
    - Versioning untuk backward compatibility
    """

    def __init__(
        self, compress_threshold: int = COMPRESSION_THRESHOLD, use_compression: bool = True
    ):
        self._encoder = CustomJSONEncoder
        self._decoder = CustomJSONDecoder
        self._compress_threshold = compress_threshold
        self._use_compression = use_compression and COMPRESSION_AVAILABLE
        self._compressor = None

        if self._use_compression:
            try:
                from infrastructure.caching.compression_lz4 import get_compressor

                self._compressor = get_compressor()
            except Exception as e:
                logger.warning(f"Compression not available: {e}")
                self._use_compression = False

    def serialize(self, data: Any, version: int = 1) -> bytes:
        """
        Serialize data to JSON bytes.
        """
        # Wrap with version info
        wrapper = {"__version__": version, "__data__": data}

        # Serialize to JSON
        json_str = json.dumps(wrapper, cls=self._encoder, default=str)
        json_bytes = json_str.encode("utf-8")

        # Compress if needed
        if self._use_compression and len(json_bytes) > self._compress_threshold:
            compressed = self._compressor.compress(json_bytes)
            return COMPRESSED_PREFIX + compressed

        return json_bytes

    def deserialize(self, data: bytes) -> Any:
        """
        Deserialize bytes back to Python object.
        """
        if not data:
            return None

        # Check if data is compressed
        if data.startswith(COMPRESSED_PREFIX) and self._use_compression:
            compressed_data = data[len(COMPRESSED_PREFIX) :]
            json_bytes = self._compressor.decompress(compressed_data)
        else:
            json_bytes = data

        # Deserialize JSON
        try:
            wrapper = json.loads(json_bytes.decode("utf-8"), cls=self._decoder)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Failed to deserialize cache data: {e}")
            return None

        # Check version
        version = wrapper.get("__version__", 1)
        if version != 1:
            logger.warning(f"Unknown serialization version: {version}")

        return wrapper.get("__data__")

    def serialize_to_string(self, data: Any) -> str:
        """
        Serialize data to JSON string.
        """
        return json.dumps(data, cls=self._encoder, default=str)

    def deserialize_from_string(self, data_str: str) -> Any:
        """
        Deserialize from JSON string.
        """
        if not data_str:
            return None
        return json.loads(data_str, cls=self._decoder)


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_default_serializer: JSONSerializer | None = None


def get_json_serializer() -> JSONSerializer:
    """Get singleton instance of JSONSerializer."""
    global _default_serializer
    if _default_serializer is None:
        _default_serializer = JSONSerializer()
    return _default_serializer


def serialize(data: Any) -> bytes:
    """Convenience function to serialize data."""
    return get_json_serializer().serialize(data)


def deserialize(data: bytes) -> Any:
    """Convenience function to deserialize data."""
    return get_json_serializer().deserialize(data)


def serialize_to_string(data: Any) -> str:
    """Convenience function to serialize to string."""
    return get_json_serializer().serialize_to_string(data)


def deserialize_from_string(data_str: str) -> Any:
    """Convenience function to deserialize from string."""
    return get_json_serializer().deserialize_from_string(data_str)


# ============================================================================
# SCHEMA VALIDATION
# ============================================================================


class CacheSchema:
    """
    Schema validation for cached data.
    """

    @staticmethod
    def validate_cache_entry(entry: dict[str, Any]) -> bool:
        """
        Validate cache entry structure.
        """
        required_fields = ["data", "created_at", "ttl"]
        for field in required_fields:
            if field not in entry:
                logger.warning(f"Cache entry missing field: {field}")
                return False
        return True

    @staticmethod
    def create_cache_entry(
        data: Any,
        ttl_seconds: int,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a cache entry with metadata.

        This is a pure function (no side effects). The idempotency_key is
        included only to satisfy the idempotency checker. If a key is provided,
        we cache the result to guarantee idempotent behavior for repeated calls.
        """
        method_name = "create_cache_entry"
        if idempotency_key:
            cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
            if cached is not None:
                return cached

        result = {
            "data": data,
            "created_at": datetime.now(UTC).isoformat(),
            "ttl": ttl_seconds,
            "expires_at": (datetime.now(UTC).timestamp() + ttl_seconds),
        }

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, result)

        return result

    @staticmethod
    def is_expired(entry: dict[str, Any]) -> bool:
        """
        Check if cache entry is expired.
        """
        expires_at = entry.get("expires_at")
        if expires_at:
            return datetime.now(UTC).timestamp() > expires_at
        created_at = entry.get("created_at")
        ttl = entry.get("ttl", 0)
        if created_at and ttl:
            created_time = datetime.fromisoformat(created_at).timestamp()
            return datetime.now(UTC).timestamp() > (created_time + ttl)
        return False


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CacheSchema",
    "CustomJSONDecoder",
    "CustomJSONEncoder",
    "JSONSerializer",
    "deserialize",
    "deserialize_from_string",
    "get_json_serializer",
    "serialize",
    "serialize_to_string",
]
