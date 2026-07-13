#!/usr/bin/env python3
"""
Module: layer_definitions.py
Layer: Governance & Architecture Enforcement

Responsibility:
    Mendefinisikan lapisan arsitektur dan aturan dependensi.
    Mapping dari modul ke lapisan, dan aturan impor yang diizinkan.

Metode yang ditambahkan:
- Untuk Layer (Enum): display_name, dari string.
- Untuk LayerDefinition: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk fungsi caching: reset_cache, get_cache_stats.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# ============================================================================
# Layer Enum (dengan method tambahan)
# ============================================================================
class Layer(Enum):
    FOUNDATION = 0
    DOMAIN = 1
    APPLICATION = 2
    PORTS = 3
    ADAPTERS = 4
    INFRASTRUCTURE = 5
    EVENT_GATEWAY = 6
    PROJECTIONS = 7
    COMPLIANCE = 8
    TESTS = 9
    UNKNOWN = 99

    def __str__(self) -> str:
        return self.name

    def display_name(self) -> str:
        names = {
            Layer.FOUNDATION: "Foundation (Constitution/Axioms/Kernel)",
            Layer.DOMAIN: "Domain",
            Layer.APPLICATION: "Application",
            Layer.PORTS: "Ports",
            Layer.ADAPTERS: "Adapters",
            Layer.INFRASTRUCTURE: "Infrastructure",
            Layer.EVENT_GATEWAY: "Event Gateway",
            Layer.PROJECTIONS: "Projections",
            Layer.COMPLIANCE: "Compliance/Audit",
            Layer.TESTS: "Tests",
            Layer.UNKNOWN: "Unknown",
        }
        return names.get(self, self.name)

    @classmethod
    def from_string(cls, name: str) -> Layer | None:
        try:
            return cls[name.upper()]
        except KeyError:
            return None

    @property
    def is_inner_than(self, other: Layer) -> bool:
        return self.value < other.value

    @property
    def is_outer_than(self, other: Layer) -> bool:
        return self.value > other.value

    # ==================== ENTITY DASAR UNTUK ENUM ====================
    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {"layer": self.name, "value": self.value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Layer:
        return cls[data["layer"]]

    def clone(self) -> Layer:
        return self

    def snapshot(self) -> dict[str, Any]:
        return {"layer": self.name, "timestamp": datetime.now(UTC).isoformat()}

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> Layer:
        return self


# ============================================================================
# LayerDefinition (dengan entity dasar)
# ============================================================================
@dataclass(kw_only=True)
class LayerDefinition:
    layer: Layer
    module_patterns: list[str]
    allowed_dependencies: list[Layer]
    description: str = ""
    _compiled_patterns: list[re.Pattern] = field(default_factory=list, init=False)

    # Fields untuk audit dan versioning
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _def_id: str = field(default_factory=lambda: str(uuid4()), repr=False)

    def __post_init__(self):
        self._compiled_patterns = [re.compile(p) for p in self.module_patterns]
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not isinstance(self.layer, Layer):
            raise ValueError("layer must be a Layer enum")
        if not self.module_patterns:
            raise ValueError("module_patterns cannot be empty")
        if self.description is None:
            object.__setattr__(self, "description", "")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "def_id": self._def_id,
                "layer": self.layer.name,
                "patterns_count": len(self.module_patterns),
                "dependencies_count": len(self.allowed_dependencies),
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
                "def_id": self._def_id,
                "details": details,
            }
        )

    def matches(self, module_path: str) -> bool:
        for pattern in self._compiled_patterns:
            if pattern.search(module_path):
                return True
        return False

    def allows_dependency(self, target_layer: Layer) -> bool:
        return target_layer in self.allowed_dependencies

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        for pattern in self.module_patterns:
            try:
                re.compile(pattern)
            except re.error as e:
                # Log the error for audit trail
                logger.debug("Invalid regex pattern '%s': %s", pattern, e)
                errors.append(f"Invalid regex pattern '{pattern}': {e}")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "def_id": self._def_id,
            "layer": self.layer.name,
            "module_patterns": self.module_patterns,
            "allowed_dependencies": [dep.name for dep in self.allowed_dependencies],
            "description": self.description,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LayerDefinition:
        instance = cls(
            layer=Layer[data["layer"]],
            module_patterns=data["module_patterns"],
            allowed_dependencies=[Layer[dep] for dep in data.get("allowed_dependencies", [])],
            description=data.get("description", ""),
        )
        instance._version = data.get("version", 1)
        instance._def_id = data.get("def_id", str(uuid4()))
        return instance

    def clone(self) -> LayerDefinition:
        new = LayerDefinition(
            layer=self.layer,
            module_patterns=self.module_patterns.copy(),
            allowed_dependencies=self.allowed_dependencies.copy(),
            description=self.description,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._def_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "def_id": self._def_id,
            "layer": self.layer.name,
            "patterns_count": len(self.module_patterns),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> LayerDefinition:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# Cache dan Fungsi Pencarian (dengan audit dan reset)
# ============================================================================
_module_layer_cache: dict[str, Layer] = {}
_module_layer_cache_by_path: dict[Path, Layer] = {}
_cache_version: int = 1
_cache_audit_trail: list[dict[str, Any]] = []


def _record_cache_audit(action: str, details: dict[str, Any]):
    global _cache_audit_trail
    _cache_audit_trail.append(
        {
            "action": action,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": _cache_version,
            "details": details,
        }
    )
    if len(_cache_audit_trail) > 1000:
        _cache_audit_trail = _cache_audit_trail[-1000:]


def get_layer_for_module(module_path: str) -> Layer | None:
    if module_path in _module_layer_cache:
        return _module_layer_cache[module_path]

    path_with_slash = module_path.replace(".", "/")
    for ld in LAYER_DEFINITIONS:
        if ld.matches(path_with_slash):
            _module_layer_cache[module_path] = ld.layer
            _record_cache_audit(
                "GET_LAYER_FOR_MODULE", {"module": module_path, "layer": ld.layer.name}
            )
            return ld.layer
    _record_cache_audit("GET_LAYER_FOR_MODULE_NOT_FOUND", {"module": module_path})
    return None


def get_layer_for_file(file_path: Path, root_path: Path) -> Layer | None:
    if file_path in _module_layer_cache_by_path:
        return _module_layer_cache_by_path[file_path]

    try:
        rel_path = str(file_path.relative_to(root_path)).replace("\\", "/")
    except ValueError:
        return None
    for ld in LAYER_DEFINITIONS:
        if ld.matches(rel_path):
            _module_layer_cache_by_path[file_path] = ld.layer
            _record_cache_audit(
                "GET_LAYER_FOR_FILE", {"file": str(file_path), "layer": ld.layer.name}
            )
            return ld.layer
    _record_cache_audit("GET_LAYER_FOR_FILE_NOT_FOUND", {"file": str(file_path)})
    return None


def is_allowed_import(from_module: str, to_module: str) -> bool:
    from_layer = get_layer_for_module(from_module)
    to_layer = get_layer_for_module(to_module)

    if from_layer is None or to_layer is None:
        return False
    if from_layer == Layer.TESTS or to_layer == Layer.TESTS:
        return True
    if from_layer == to_layer:
        return True
    if from_layer.value > to_layer.value:
        return True
    for ld in LAYER_DEFINITIONS:
        if ld.layer == from_layer:
            return to_layer in ld.allowed_dependencies
    return False


def get_allowed_imports_for_module(module_path: str) -> list[str]:
    layer = get_layer_for_module(module_path)
    if layer is None:
        return []

    allowed_patterns = []
    for ld in LAYER_DEFINITIONS:
        if ld.layer == layer:
            for dep in ld.allowed_dependencies:
                for dep_ld in LAYER_DEFINITIONS:
                    if dep_ld.layer == dep:
                        allowed_patterns.extend(dep_ld.module_patterns)
            allowed_patterns.extend(ld.module_patterns)
            break
    return list(set(allowed_patterns))


def validate_layer_consistency() -> list[str]:
    issues = []
    all_patterns = [(ld.layer, p) for ld in LAYER_DEFINITIONS for p in ld.module_patterns]
    for i, (layer1, pat1) in enumerate(all_patterns):
        for j, (layer2, pat2) in enumerate(all_patterns):
            if i >= j:
                continue
            try:
                if re.search(pat1, pat2) or re.search(pat2, pat1):
                    issues.append(
                        f"Potential overlap between {layer1.name} pattern '{pat1}' and {layer2.name} pattern '{pat2}'"
                    )
            except re.error:
                # Log regex errors; they indicate problematic patterns but we continue
                logger.debug("Regex error comparing patterns '%s' and '%s'", pat1, pat2)
                # Optionally we could add an issue but we skip to avoid false positives
                continue
    _record_cache_audit("VALIDATE_LAYER_CONSISTENCY", {"issues_count": len(issues)})
    return issues


def get_all_modules_with_layers(root_path: str = ".") -> list[tuple[str, Layer | None]]:
    root = Path(root_path).resolve()
    results = []
    for py_file in root.rglob("*.py"):
        if py_file.name.startswith("__") and py_file.name.endswith("__"):
            continue
        try:
            rel_path = py_file.relative_to(root)
            module_name = str(rel_path).replace("\\", ".").replace("/", ".").replace(".py", "")
            layer = get_layer_for_module(module_name)
            results.append((module_name, layer))
        except ValueError:
            continue
    _record_cache_audit("GET_ALL_MODULES_WITH_LAYERS", {"total": len(results)})
    return results


def reset_cache() -> None:
    """Reset semua cache layer."""
    global _module_layer_cache, _module_layer_cache_by_path, _cache_version
    _module_layer_cache.clear()
    _module_layer_cache_by_path.clear()
    _cache_version += 1
    _record_cache_audit("RESET_CACHE", {"new_version": _cache_version})


def get_cache_stats() -> dict[str, Any]:
    """Mendapatkan statistik cache."""
    return {
        "cache_version": _cache_version,
        "module_cache_size": len(_module_layer_cache),
        "file_cache_size": len(_module_layer_cache_by_path),
        "audit_trail_size": len(_cache_audit_trail),
    }


# ============================================================================
# LAYER_DEFINITIONS (data asli, dipertahankan)
# ============================================================================
LAYER_DEFINITIONS: list[LayerDefinition] = [
    LayerDefinition(
        layer=Layer.FOUNDATION,
        module_patterns=[
            r"^constitution/",
            r"^axioms/",
            r"^kernel/",
            r"^kernel/guards/",
            r"^kernel/immutable_laws/",
            r"^reality/",
            r"^intent/",
            r"^causality/",
        ],
        allowed_dependencies=[],
        description="Hukum tertinggi, aksioma, kernel, aturan immutable. Tidak bergantung pada apapun.",
    ),
    LayerDefinition(
        layer=Layer.DOMAIN,
        module_patterns=[
            r"^domain/",
            r"^policy_engine/",
            r"^legal/",
            r"^ethics/",
        ],
        allowed_dependencies=[Layer.FOUNDATION],
        description="Domain aggregates, entities, value objects. Hanya bergantung pada foundation.",
    ),
    LayerDefinition(
        layer=Layer.APPLICATION,
        module_patterns=[r"^application/"],
        allowed_dependencies=[Layer.FOUNDATION, Layer.DOMAIN, Layer.PORTS],
        description="Use cases, sagas, CQRS. Bergantung pada domain, ports, foundation.",
    ),
    LayerDefinition(
        layer=Layer.PORTS,
        module_patterns=[r"^ports/"],
        allowed_dependencies=[Layer.FOUNDATION, Layer.DOMAIN],
        description="Antarmuka (abstraksi) untuk adapters. Bergantung pada domain dan foundation.",
    ),
    LayerDefinition(
        layer=Layer.ADAPTERS,
        module_patterns=[r"^adapters/"],
        allowed_dependencies=[
            Layer.FOUNDATION,
            Layer.DOMAIN,
            Layer.APPLICATION,
            Layer.PORTS,
            Layer.INFRASTRUCTURE,
        ],
        description="Implementasi konkret dari ports.",
    ),
    LayerDefinition(
        layer=Layer.INFRASTRUCTURE,
        module_patterns=[
            r"^infrastructure/",
            r"^config/",
            r"^bootstrap/",
            r"^persistence_orm/",
            r"^database/",
            r"^message_broker/",
            r"^security/",
            r"^telemetry/",
            r"^caching/",
            r"^file_storage/",
            r"^dependency_container/",
        ],
        allowed_dependencies=[Layer.FOUNDATION, Layer.DOMAIN, Layer.PORTS],
        description="Infrastruktur teknis. Bergantung pada domain dan ports, bukan application.",
    ),
    LayerDefinition(
        layer=Layer.EVENT_GATEWAY,
        module_patterns=[r"^event_gateway/", r"^transformers/"],
        allowed_dependencies=[Layer.PORTS, Layer.INFRASTRUCTURE],
        description="Event gateway dan transformer.",
    ),
    LayerDefinition(
        layer=Layer.PROJECTIONS,
        module_patterns=[r"^projections/", r"^reports/"],
        allowed_dependencies=[Layer.INFRASTRUCTURE, Layer.DOMAIN],
        description="Read models dan proyeksi.",
    ),
    LayerDefinition(
        layer=Layer.COMPLIANCE,
        module_patterns=[r"^audit/", r"^compliance/"],
        allowed_dependencies=[Layer.FOUNDATION, Layer.DOMAIN, Layer.INFRASTRUCTURE],
        description="Audit dan kepatuhan.",
    ),
    LayerDefinition(
        layer=Layer.TESTS,
        module_patterns=[r"^tests/"],
        allowed_dependencies=[],
        description="Test suite.",
    ),
]

# ============================================================================
# Aturan Dokumentasi (opsional)
# ============================================================================
DEPENDENCY_RULES = {
    "constitution": "Tidak boleh mengimpor apapun dari luar folder constitution",
    "axioms": "Tidak boleh mengimpor domain/application/adapters",
    "kernel": "Hanya boleh mengimpor constitution, axioms, guards, immutable_laws, ports/primary",
    "domain": "Tidak boleh mengimpor application, adapters, infrastructure secara langsung",
    "application": "Hanya boleh mengimpor domain, ports, kernel",
    "ports": "Tidak boleh mengimpor adapters, infrastructure secara langsung",
    "adapters": "Boleh mengimpor application, ports, infrastructure",
    "infrastructure": "Tidak boleh mengimpor application, domain aggregates secara langsung",
    "event_gateway": "Hanya boleh mengimpor ports, infrastructure, transformers",
    "projections": "Hanya boleh mengimpor infrastructure/persistence_orm, domain/*/domain_events",
    "audit/compliance": "Boleh mengimpor infrastructure/event_store, domain",
}

# ============================================================================
# EKSPOR
# ============================================================================
__all__ = [
    "DEPENDENCY_RULES",
    "LAYER_DEFINITIONS",
    "Layer",
    "LayerDefinition",
    "get_all_modules_with_layers",
    "get_allowed_imports_for_module",
    "get_cache_stats",
    "get_layer_for_file",
    "get_layer_for_module",
    "is_allowed_import",
    "reset_cache",
    "validate_layer_consistency",
]
