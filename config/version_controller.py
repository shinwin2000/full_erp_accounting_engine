#!/usr/bin/env python3
"""
Module: version_controller.py
Layer: 3 - Bootstrap & Config / Configuration
Responsibility: Melacak versi konfigurasi dan riwayat perubahannya.
               Menyediakan mekanisme versioning untuk konfigurasi,
               mendukung rollback ke versi sebelumnya, dan integritas
               melalui cryptographic hashing.

Metode yang ditambahkan:
- Untuk ConfigVersion: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk VersionChange: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk ConfigVersionController: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from bootstrap.bootstrap_exceptions import BootstrapErrorCode, ConfigError
from config.loader_yaml import get_config_loader

logger = logging.getLogger(__name__)

# === 1. CONSTANTS ===
CONFIG_VERSION_FILE = "config_files/.config_version.json"
MAX_HISTORY_SIZE = 100


# === 2. ConfigVersion (dengan entity dasar) ===
@dataclass(kw_only=True)
class ConfigVersion:
    version_id: str
    version_number: int
    timestamp: datetime
    config_snapshot: dict[str, Any]
    config_hash: str
    description: str
    created_by: str = ""
    parent_version_id: str | None = None

    # Fields untuk audit dan versioning
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _ver: int = field(default=1, repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not self.version_id:
            raise ValueError("version_id is required")
        if self.version_number < 1:
            raise ValueError("version_number must be >= 1")
        if self.timestamp.tzinfo is None:
            object.__setattr__(self, "timestamp", self.timestamp.replace(tzinfo=UTC))
        if not self.config_snapshot:
            raise ValueError("config_snapshot is required")
        if not self.config_hash:
            object.__setattr__(self, "config_hash", self.compute_hash())
        if not self.description:
            raise ValueError("description is required")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._ver,
                "version_id": self.version_id,
                "version_number": self.version_number,
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
                "version_id": self.version_id,
                "details": details,
            }
        )

    def compute_hash(self) -> str:
        content = json.dumps(self.config_snapshot, sort_keys=True, default=str)
        return hashlib.sha3_256(content.encode()).hexdigest()

    def verify_integrity(self) -> bool:
        return self.config_hash == self.compute_hash()

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        if not self.verify_integrity():
            errors.append("Hash integrity check failed")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "version_number": self.version_number,
            "timestamp": self.timestamp.isoformat(),
            "config_hash": self.config_hash,
            "description": self.description,
            "created_by": self.created_by,
            "parent_version_id": self.parent_version_id,
            "ver": self._ver,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], config_snapshot: dict[str, Any]) -> ConfigVersion:
        instance = cls(
            version_id=data["version_id"],
            version_number=data["version_number"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            config_snapshot=config_snapshot,
            config_hash=data["config_hash"],
            description=data.get("description", ""),
            created_by=data.get("created_by", ""),
            parent_version_id=data.get("parent_version_id"),
        )
        instance._ver = data.get("ver", 1)
        return instance

    def clone(self) -> ConfigVersion:
        new = ConfigVersion(
            version_id=str(uuid4()),
            version_number=self.version_number + 1,
            timestamp=datetime.now(UTC),
            config_snapshot=self.config_snapshot.copy(),
            config_hash="",  # will recompute
            description=f"Cloned from {self.version_id}",
            created_by=self.created_by,
            parent_version_id=self.version_id,
        )
        new.config_hash = new.compute_hash()
        new._ver = self._ver + 1
        new._record_audit("CLONE", "system", {"source": self.version_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._ver,
            "version_id": self.version_id,
            "version_number": self.version_number,
            "timestamp": self.timestamp.isoformat(),
            "config_hash": self.config_hash[:16] + "...",
        }

    def version(self) -> int:
        return self._ver

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ConfigVersion:
        self._ver += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 3. VersionChange (dengan entity dasar) ===
@dataclass(kw_only=True)
class VersionChange:
    from_version_id: str
    to_version_id: str
    changed_keys: list[str]
    added_keys: list[str]
    removed_keys: list[str]
    changed_at: datetime
    changed_by: str

    # Fields untuk audit
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _ver: int = field(default=1, repr=False)
    _change_id: str = field(default_factory=lambda: str(uuid4()), repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not self.from_version_id:
            raise ValueError("from_version_id is required")
        if not self.to_version_id:
            raise ValueError("to_version_id is required")
        if self.changed_at.tzinfo is None:
            object.__setattr__(self, "changed_at", self.changed_at.replace(tzinfo=UTC))
        if not self.changed_by:
            raise ValueError("changed_by is required")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._ver,
                "change_id": self._change_id,
                "from_version": self.from_version_id,
                "to_version": self.to_version_id,
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
                "change_id": self._change_id,
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
            "change_id": self._change_id,
            "from_version_id": self.from_version_id,
            "to_version_id": self.to_version_id,
            "changed_keys": self.changed_keys,
            "added_keys": self.added_keys,
            "removed_keys": self.removed_keys,
            "changed_at": self.changed_at.isoformat(),
            "changed_by": self.changed_by,
            "ver": self._ver,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VersionChange:
        instance = cls(
            from_version_id=data["from_version_id"],
            to_version_id=data["to_version_id"],
            changed_keys=data.get("changed_keys", []),
            added_keys=data.get("added_keys", []),
            removed_keys=data.get("removed_keys", []),
            changed_at=datetime.fromisoformat(data["changed_at"]),
            changed_by=data["changed_by"],
        )
        instance._ver = data.get("ver", 1)
        instance._change_id = data.get("change_id", str(uuid4()))
        return instance

    def clone(self) -> VersionChange:
        new = VersionChange(
            from_version_id=self.from_version_id,
            to_version_id=self.to_version_id,
            changed_keys=self.changed_keys.copy(),
            added_keys=self.added_keys.copy(),
            removed_keys=self.removed_keys.copy(),
            changed_at=datetime.now(UTC),
            changed_by=self.changed_by,
        )
        new._ver = self._ver + 1
        new._record_audit("CLONE", "system", {"source": self._change_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._ver,
            "change_id": self._change_id,
            "from_version": self.from_version_id,
            "to_version": self.to_version_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._ver

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> VersionChange:
        self._ver += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 4. ConfigVersionController (dengan entity dasar) ===
class ConfigVersionController:
    _instance: ConfigVersionController | None = None
    _versions: dict[str, ConfigVersion]
    _version_history: list[ConfigVersion]
    _changes: list[VersionChange]
    _current_version_id: str | None

    def __new__(cls) -> ConfigVersionController:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._versions = {}
        self._version_history = []
        self._changes = []
        self._current_version_id = None
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._controller_id = str(uuid4())
        self._take_snapshot()
        self._load_version_file()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "controller_id": self._controller_id,
                "total_versions": len(self._version_history),
                "current_version": self._current_version_id,
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
                "controller_id": self._controller_id,
                "details": details,
            }
        )

    def _load_version_file(self) -> None:
        version_path = Path(CONFIG_VERSION_FILE)
        if version_path.exists():
            try:
                with open(version_path) as f:
                    data = json.load(f)
                self._current_version_id = data.get("current_version_id")
                for v_data in data.get("versions", []):
                    # Note: config_snapshot tidak disimpan di file, hanya metadata
                    version = ConfigVersion(
                        version_id=v_data["version_id"],
                        version_number=v_data["version_number"],
                        timestamp=datetime.fromisoformat(v_data["timestamp"]),
                        config_snapshot={},  # placeholder
                        config_hash=v_data["config_hash"],
                        created_by=v_data["created_by"],
                        description=v_data.get("description", ""),
                        parent_version_id=v_data.get("parent_version_id"),
                    )
                    self._versions[version.version_id] = version
                    self._version_history.append(version)
                self._version_history.sort(key=lambda v: v.version_number)
                logger.info(f"Loaded {len(self._versions)} config versions")
            except Exception as e:
                logger.warning(f"Failed to load version file: {e}")

    def _save_version_file(self) -> None:
        data = {
            "current_version_id": self._current_version_id,
            "versions": [
                {
                    "version_id": v.version_id,
                    "version_number": v.version_number,
                    "timestamp": v.timestamp.isoformat(),
                    "config_hash": v.config_hash,
                    "created_by": v.created_by,
                    "description": v.description,
                    "parent_version_id": v.parent_version_id,
                }
                for v in self._version_history
            ],
        }
        version_path = Path(CONFIG_VERSION_FILE)
        version_path.parent.mkdir(parents=True, exist_ok=True)
        with open(version_path, "w") as f:
            json.dump(data, f, indent=2)

    # FIX: Parameter order - description (required) before created_by (optional)
    def create_version(
        self,
        config: dict[str, Any],
        description: str,
        created_by: str = "",
        parent_version_id: str | None = None,
    ) -> ConfigVersion:
        parent_id = parent_version_id or self._current_version_id
        next_version_number = len(self._version_history) + 1
        version = ConfigVersion(
            version_id=f"v{next_version_number}_{int(datetime.now(UTC).timestamp())}",
            version_number=next_version_number,
            timestamp=datetime.now(UTC),
            config_snapshot=config,
            config_hash="",
            created_by=created_by,
            description=description,
            parent_version_id=parent_id,
        )
        version.config_hash = version.compute_hash()
        self._versions[version.version_id] = version
        self._version_history.append(version)
        self._current_version_id = version.version_id
        if parent_id and parent_id in self._versions:
            parent = self._versions[parent_id]
            changes = self._diff_configs(parent.config_snapshot, config)
            change_record = VersionChange(
                from_version_id=parent_id,
                to_version_id=version.version_id,
                changed_keys=changes["changed"],
                added_keys=changes["added"],
                removed_keys=changes["removed"],
                changed_at=datetime.now(UTC),
                changed_by=created_by,
            )
            self._changes.append(change_record)
        if len(self._version_history) > MAX_HISTORY_SIZE:
            oldest = self._version_history.pop(0)
            self._versions.pop(oldest.version_id, None)
        self._save_version_file()
        self._record_audit(
            "CREATE_VERSION",
            created_by,
            {"version_id": version.version_id, "description": description},
        )
        logger.info(f"Created config version {version.version_id}: {description}")
        return version

    def get_version(self, version_id: str) -> ConfigVersion | None:
        return self._versions.get(version_id)

    def get_current_version(self) -> ConfigVersion | None:
        if self._current_version_id:
            return self._versions.get(self._current_version_id)
        return None

    def get_version_history(self, limit: int = 50) -> list[ConfigVersion]:
        return self._version_history[-limit:]

    def rollback_to_version(self, version_id: str, rolled_by: str, reason: str) -> ConfigVersion:
        target_version = self.get_version(version_id)
        if not target_version:
            raise ConfigError(
                f"Version {version_id} not found",
                error_code=BootstrapErrorCode.CONFIG_NOT_FOUND,
            )
        new_version = self.create_version(
            config=target_version.config_snapshot,
            description=f"Rollback to {version_id}: {reason}",
            created_by=rolled_by,
            parent_version_id=self._current_version_id,
        )
        self._record_audit(
            "ROLLBACK_TO_VERSION",
            rolled_by,
            {"target_version": version_id, "new_version": new_version.version_id},
        )
        logger.warning(f"Rolled back config to {version_id}, new version {new_version.version_id}")
        return new_version

    def rollback_to_previous(self, rolled_by: str, reason: str) -> ConfigVersion | None:
        current = self.get_current_version()
        if not current or not current.parent_version_id:
            return None
        return self.rollback_to_version(current.parent_version_id, rolled_by, reason)

    def _diff_configs(
        self, old_config: dict[str, Any], new_config: dict[str, Any]
    ) -> dict[str, list[str]]:
        changed = []
        added = []
        removed = []
        all_keys = set(self._flatten_keys(old_config)) | set(self._flatten_keys(new_config))
        for key in all_keys:
            old_value = self._get_nested_value(old_config, key)
            new_value = self._get_nested_value(new_config, key)
            if old_value is None and new_value is not None:
                added.append(key)
            elif old_value is not None and new_value is None:
                removed.append(key)
            elif old_value != new_value:
                changed.append(key)
        return {"changed": changed, "added": added, "removed": removed}

    def _flatten_keys(self, config: dict[str, Any], prefix: str = "") -> list[str]:
        keys = []
        for k, v in config.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                keys.extend(self._flatten_keys(v, full_key))
            else:
                keys.append(full_key)
        return keys

    def _get_nested_value(self, config: dict[str, Any], path: str) -> Any:
        keys = path.split(".")
        value = config
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return None
            else:
                return None
        return value

    def get_changes(self, from_version_id: str, to_version_id: str) -> VersionChange | None:
        for change in self._changes:
            if change.from_version_id == from_version_id and change.to_version_id == to_version_id:
                return change
        return None

    def get_version_by_number(self, version_number: int) -> ConfigVersion | None:
        for version in self._version_history:
            if version.version_number == version_number:
                return version
        return None

    def load_version_to_loader(self, version_id: str) -> bool:
        version = self.get_version(version_id)
        if not version:
            return False
        loader = get_config_loader()
        # Note: This would require loader to have a method to set config
        logger.info(f"Loading version {version_id} to config loader (implement if needed)")
        self._record_audit("LOAD_VERSION_TO_LOADER", "system", {"version_id": version_id})
        return True

    def get_statistics(self) -> dict[str, Any]:
        current = self.get_current_version()
        return {
            "controller_id": self._controller_id,
            "total_versions": len(self._version_history),
            "total_changes": len(self._changes),
            "current_version": self._current_version_id,
            "current_version_number": current.version_number if current else None,
            "oldest_version": self._version_history[0].version_id
            if self._version_history
            else None,
            "newest_version": self._version_history[-1].version_id
            if self._version_history
            else None,
            "version": self._version,
        }

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        for version in self._version_history:
            res = version.validate()
            if not res["is_valid"]:
                errors.extend([f"Version {version.version_id}: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "controller_id": self._controller_id,
            "current_version_id": self._current_version_id,
            "total_versions": len(self._version_history),
            "total_changes": len(self._changes),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConfigVersionController:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._controller_id = data.get("controller_id", str(uuid4()))
        return instance

    def clone(self) -> ConfigVersionController:
        new = ConfigVersionController()
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._controller_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "controller_id": self._controller_id,
            "total_versions": len(self._version_history),
            "current_version": self._current_version_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ConfigVersionController:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._versions = {}
        self._version_history = []
        self._changes = []
        self._current_version_id = None
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._controller_id = str(uuid4())
        self._record_audit("RESET", "system", {})


# === 5. SINGLETON ACCESSOR ===
_config_version_controller_instance: ConfigVersionController | None = None


def get_config_version_controller() -> ConfigVersionController:
    global _config_version_controller_instance
    if _config_version_controller_instance is None:
        _config_version_controller_instance = ConfigVersionController()
    return _config_version_controller_instance


# === 6. EXPORTS ===
__all__ = [
    "ConfigVersion",
    "ConfigVersionController",
    "VersionChange",
    "get_config_version_controller",
]
