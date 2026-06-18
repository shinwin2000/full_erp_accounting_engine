#!/usr/bin/env python3
from __future__ import annotations

"""
Package: policy_engine
Responsibility: Mesin kebijakan akuntansi, perpajakan, dan standar keuangan.
               Menyediakan antarmuka untuk mengelola kebijakan akuntansi
               (PSAK, IFRS), aturan perpajakan Indonesia, dan resolusi
               konflik antar kebijakan berdasarkan jurisdiksi dan periode.
"""

from .cache_engine import PolicyCacheEngine, get_policy_cache_engine
from .conflict_resolver import ConflictResolver, get_conflict_resolver
from .interpreter import PolicyInterpreter, get_policy_interpreter
from .jurisdiction_resolver import JurisdictionResolver, get_jurisdiction_resolver
from .loader_yaml import PolicyLoader, get_policy_loader
from .override_authorizer import OverrideAuthorizer, get_override_authorizer
from .policy_exceptions import (
    JurisdictionResolutionError,
    PolicyConflictError,
    PolicyError,
    PolicyNotFoundError,
    PolicyOverrideNotAuthorizedError,
    PolicyValidationError,
    PolicyVersionError,
    TemporalResolutionError,
)
from .temporal_resolver import TemporalResolver, get_temporal_resolver
from .version_manager import PolicyVersionManager, get_policy_version_manager

__all__ = [
    # Loader
    "PolicyLoader",
    "get_policy_loader",
    # Interpreter
    "PolicyInterpreter",
    "get_policy_interpreter",
    # Resolvers
    "TemporalResolver",
    "get_temporal_resolver",
    "JurisdictionResolver",
    "get_jurisdiction_resolver",
    "ConflictResolver",
    "get_conflict_resolver",
    # Override
    "OverrideAuthorizer",
    "get_override_authorizer",
    # Cache
    "PolicyCacheEngine",
    "get_policy_cache_engine",
    # Version
    "PolicyVersionManager",
    "get_policy_version_manager",
    # Exceptions
    "PolicyError",
    "PolicyNotFoundError",
    "PolicyValidationError",
    "PolicyConflictError",
    "PolicyOverrideNotAuthorizedError",
    "PolicyVersionError",
    "TemporalResolutionError",
    "JurisdictionResolutionError",
]
