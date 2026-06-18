#!/usr/bin/env python3
"""
Module: namespace_isolation.py
Layer: Infrastructure (Caching)
Responsibility: Menyediakan namespace isolation untuk cache keys, mencegah
               collision antara tenant (legal entity), environment (dev/staging/prod),
               dan jenis cache yang berbeda. Setiap cache key secara otomatis
               memiliki prefix namespace yang sesuai dengan konteks.
Dependencies:
- infrastructure.caching.redis_manager (RedisManager)
- config.loader_yaml
- infrastructure.telemetry.structured_json_logging
Audit: Namespace digunakan untuk isolasi multi-tenant. Akses lintas namespace
       dicegah oleh prefix key.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_NAMESPACE_CONFIG = {
    "environment": "production",  # development, staging, production
    "separator": ":",
    "include_tenant": True,
    "include_environment": True,
    "include_cache_type": True,
}


# Cache types
class CacheType(str, Enum):
    ENTITY = "entity"  # Domain entities
    QUERY = "query"  # Query results
    SESSION = "session"  # User sessions
    RATE_LIMIT = "ratelimit"  # Rate limiting
    IDEMPOTENCY = "idempotency"  # Idempotency keys
    LOCK = "lock"  # Distributed locks
    TEMP = "temp"  # Temporary data
    REPORT = "report"  # Report data


# ============================================================================
# NAMESPACE MANAGER
# ============================================================================


class NamespaceIsolation:
    """
    Manajer namespace untuk cache keys.

    Fitur:
    - Prefix keys dengan environment, tenant, cache type
    - Isolasi antar tenant (legal entity)
    - Isolasi antar environment
    - Support wildcard patterns untuk invalidation
    - Namespace statistics
    """

    def __init__(self, config_path: str = "config_files/cache_config.yaml"):
        self.config = self._load_config(config_path)
        self._separator = self.config.get("separator", DEFAULT_NAMESPACE_CONFIG["separator"])
        self._include_tenant = self.config.get(
            "include_tenant", DEFAULT_NAMESPACE_CONFIG["include_tenant"]
        )
        self._include_environment = self.config.get(
            "include_environment", DEFAULT_NAMESPACE_CONFIG["include_environment"]
        )
        self._include_cache_type = self.config.get(
            "include_cache_type", DEFAULT_NAMESPACE_CONFIG["include_cache_type"]
        )

        # Environment (from config or env var)
        self._environment = self.config.get("environment", "production")
        import os

        self._environment = os.environ.get("ERP_ENV", self._environment)

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            return load_yaml_config(config_path).get("namespace", DEFAULT_NAMESPACE_CONFIG)
        except Exception:
            return DEFAULT_NAMESPACE_CONFIG

    def build_key(self, cache_type: CacheType, key: str, legal_entity_id: str | None = None) -> str:
        """
        Build a namespaced cache key.

        Args:
            cache_type: Type of cache (entity, query, session, etc.)
            key: The actual cache key
            legal_entity_id: Optional tenant ID for multi-tenant isolation

        Returns:
            Namespaced cache key (e.g., "prod:entity:123:user:456")
        """
        parts = []

        # Add environment
        if self._include_environment:
            parts.append(self._environment)

        # Add tenant
        if self._include_tenant and legal_entity_id:
            parts.append(f"tenant_{legal_entity_id}")

        # Add cache type
        if self._include_cache_type:
            parts.append(cache_type.value)

        # Add the actual key
        parts.append(key)

        return self._separator.join(parts)

    def build_pattern(
        self,
        cache_type: CacheType | None = None,
        legal_entity_id: str | None = None,
        pattern: str = "*",
    ) -> str:
        """
        Build a pattern for scanning keys.

        Args:
            cache_type: Filter by cache type
            legal_entity_id: Filter by tenant
            pattern: The key pattern (supports *)

        Returns:
            Namespaced pattern for Redis SCAN
        """
        parts = []

        if self._include_environment:
            parts.append(self._environment)

        if self._include_tenant and legal_entity_id:
            parts.append(f"tenant_{legal_entity_id}")
        elif self._include_tenant:
            parts.append("*")  # Any tenant

        if self._include_cache_type and cache_type:
            parts.append(cache_type.value)
        elif self._include_cache_type:
            parts.append("*")

        parts.append(pattern)

        return self._separator.join(parts)

    def extract_namespace(self, namespaced_key: str) -> dict[str, str]:
        """
        Extract namespace components from a key.

        Returns:
            Dictionary with environment, tenant, cache_type, key
        """
        parts = namespaced_key.split(self._separator)
        result = {}

        idx = 0

        # Extract environment
        if self._include_environment and idx < len(parts):
            result["environment"] = parts[idx]
            idx += 1

        # Extract tenant
        if self._include_tenant and idx < len(parts):
            tenant_part = parts[idx]
            if tenant_part.startswith("tenant_"):
                result["legal_entity_id"] = tenant_part[7:]
            else:
                result["legal_entity_id"] = tenant_part
            idx += 1

        # Extract cache type
        if self._include_cache_type and idx < len(parts):
            result["cache_type"] = parts[idx]
            idx += 1

        # Remaining is the actual key
        if idx < len(parts):
            result["key"] = self._separator.join(parts[idx:])
        else:
            result["key"] = ""

        return result

    def get_tenant_prefix(self, legal_entity_id: str) -> str:
        """
        Get prefix for all keys belonging to a tenant.
        """
        parts = []
        if self._include_environment:
            parts.append(self._environment)
        if self._include_tenant:
            parts.append(f"tenant_{legal_entity_id}")
        parts.append("*")
        return self._separator.join(parts)

    def get_cache_type_prefix(self, cache_type: CacheType) -> str:
        """
        Get prefix for all keys of a cache type.
        """
        parts = []
        if self._include_environment:
            parts.append(self._environment)
        if self._include_tenant:
            parts.append("*")
        if self._include_cache_type:
            parts.append(cache_type.value)
        parts.append("*")
        return self._separator.join(parts)

    def get_environment_prefix(self) -> str:
        """
        Get prefix for all keys in current environment.
        """
        parts = []
        if self._include_environment:
            parts.append(self._environment)
        parts.append("*")
        return self._separator.join(parts)

    def is_same_namespace(self, key1: str, key2: str) -> bool:
        """
        Check if two keys belong to the same namespace (same tenant and cache type).
        """
        ns1 = self.extract_namespace(key1)
        ns2 = self.extract_namespace(key2)

        return (
            ns1.get("environment") == ns2.get("environment")
            and ns1.get("legal_entity_id") == ns2.get("legal_entity_id")
            and ns1.get("cache_type") == ns2.get("cache_type")
        )

    def get_stats(self) -> dict[str, Any]:
        """
        Get namespace configuration statistics.
        """
        return {
            "environment": self._environment,
            "separator": self._separator,
            "include_tenant": self._include_tenant,
            "include_environment": self._include_environment,
            "include_cache_type": self._include_cache_type,
            "example_key": self.build_key(CacheType.ENTITY, "user:123", "tenant_abc"),
        }


# ============================================================================
# DECORATORS
# ============================================================================


def with_namespace(cache_type: CacheType):
    """
    Decorator untuk menambahkan namespace ke cache key.
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Extract legal_entity_id from arguments if present
            legal_entity_id = None
            for arg in args:
                if hasattr(arg, "legal_entity_id"):
                    legal_entity_id = str(arg.legal_entity_id)
                    break
            if "legal_entity_id" in kwargs:
                legal_entity_id = str(kwargs["legal_entity_id"])

            namespace = get_namespace_manager()
            key = kwargs.get("key", args[0] if args else "")
            namespaced_key = namespace.build_key(cache_type, key, legal_entity_id)

            # Replace or add key
            if "key" in kwargs:
                kwargs["key"] = namespaced_key
            elif args and len(args) > 0:
                args = list(args)
                args[0] = namespaced_key
                args = tuple(args)

            return await func(*args, **kwargs)

        return wrapper

    return decorator


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_namespace_manager: NamespaceIsolation | None = None


def get_namespace_manager() -> NamespaceIsolation:
    """Get singleton instance of NamespaceIsolation."""
    global _namespace_manager
    if _namespace_manager is None:
        _namespace_manager = NamespaceIsolation()
    return _namespace_manager


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["CacheType", "NamespaceIsolation", "get_namespace_manager", "with_namespace"]
