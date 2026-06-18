#!/usr/bin/env python3
"""
Module: hot_reload_watcher.py
Layer: 3 - Bootstrap & Config / Configuration
Responsibility: Mengawasi perubahan file konfigurasi dan reload otomatis.
               Mendukung hot reload untuk perubahan konfigurasi tanpa restart
               aplikasi, dengan validasi sebelum apply dan rollback jika gagal.

Metode yang ditambahkan:
- Untuk ConfigChange: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk ReloadResult: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk ReloadCallback: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk HotReloadWatcher: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from config.loader_yaml import get_config_loader
from config.schema_validator import get_schema_validator, validate_config

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# === 1. CONSTANTS ===
DEFAULT_POLL_INTERVAL_SECONDS = 5
DEFAULT_WATCH_PATHS = [
    Path("config_files/application.yaml"),
    Path("config_files/security_tls_jwt_mfa.yaml"),
    Path("config_files/feature_flags.yaml"),
]


# === 2. ConfigChange (dengan entity dasar) ===
@dataclass(kw_only=True)
class ConfigChange:
    file_path: str
    old_hash: str
    new_hash: str
    changed_keys: list[str]
    detected_at: datetime

    # Fields untuk audit dan versioning
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _change_id: str = field(default_factory=lambda: str(uuid4()), repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not self.file_path:
            raise ValueError("file_path is required")
        if not self.old_hash and not self.new_hash:
            raise ValueError("at least one hash must be provided")
        if self.detected_at.tzinfo is None:
            object.__setattr__(self, "detected_at", self.detected_at.replace(tzinfo=UTC))

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "change_id": self._change_id,
                "file_path": self.file_path,
                "changed_keys_count": len(self.changed_keys),
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
                "change_id": self._change_id,
                "details": details,
            }
        )

    def has_changes(self) -> bool:
        return len(self.changed_keys) > 0

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
            "file_path": self.file_path,
            "old_hash": self.old_hash[:16] + "..." if self.old_hash else None,
            "new_hash": self.new_hash[:16] + "..." if self.new_hash else None,
            "changed_keys": self.changed_keys,
            "detected_at": self.detected_at.isoformat(),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConfigChange:
        instance = cls(
            file_path=data["file_path"],
            old_hash=data.get("old_hash", ""),
            new_hash=data.get("new_hash", ""),
            changed_keys=data.get("changed_keys", []),
            detected_at=datetime.fromisoformat(data["detected_at"]),
        )
        instance._version = data.get("version", 1)
        instance._change_id = data.get("change_id", str(uuid4()))
        return instance

    def clone(self) -> ConfigChange:
        new = ConfigChange(
            file_path=self.file_path,
            old_hash=self.old_hash,
            new_hash=self.new_hash,
            changed_keys=self.changed_keys.copy(),
            detected_at=datetime.now(UTC),
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._change_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "change_id": self._change_id,
            "file_path": self.file_path,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ConfigChange:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 3. ReloadResult (dengan entity dasar) ===
@dataclass(kw_only=True)
class ReloadResult:
    success: bool
    timestamp: datetime
    changes: list[ConfigChange]
    error_message: str | None = None
    rollback_performed: bool = False
    duration_ms: float = 0.0

    # Fields untuk audit
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _result_id: str = field(default_factory=lambda: str(uuid4()), repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not isinstance(self.success, bool):
            raise ValueError("success must be boolean")
        if self.timestamp.tzinfo is None:
            object.__setattr__(self, "timestamp", self.timestamp.replace(tzinfo=UTC))
        if self.duration_ms < 0:
            raise ValueError("duration_ms cannot be negative")
        if not self.success and not self.error_message:
            raise ValueError("error_message required when success=False")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "result_id": self._result_id,
                "success": self.success,
                "changes_count": len(self.changes),
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
                "result_id": self._result_id,
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
        for c in self.changes:
            res = c.validate()
            if not res["is_valid"]:
                errors.extend([f"Change {c.file_path}: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self._result_id,
            "success": self.success,
            "timestamp": self.timestamp.isoformat(),
            "changes": [c.to_dict() for c in self.changes],
            "error_message": self.error_message,
            "rollback_performed": self.rollback_performed,
            "duration_ms": self.duration_ms,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReloadResult:
        changes = [ConfigChange.from_dict(c) for c in data.get("changes", [])]
        instance = cls(
            success=data["success"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            changes=changes,
            error_message=data.get("error_message"),
            rollback_performed=data.get("rollback_performed", False),
            duration_ms=data.get("duration_ms", 0.0),
        )
        instance._version = data.get("version", 1)
        instance._result_id = data.get("result_id", str(uuid4()))
        return instance

    def clone(self) -> ReloadResult:
        new = ReloadResult(
            success=self.success,
            timestamp=datetime.now(UTC),
            changes=[c.clone() for c in self.changes],
            error_message=self.error_message,
            rollback_performed=self.rollback_performed,
            duration_ms=self.duration_ms,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._result_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "result_id": self._result_id,
            "success": self.success,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ReloadResult:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 4. ReloadCallback (dengan entity dasar) ===
@dataclass(kw_only=True)
class ReloadCallback:
    name: str
    callback: Callable[[dict[str, Any], dict[str, Any]], None]
    enabled: bool = True

    # Fields untuk audit
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _cb_id: str = field(default_factory=lambda: str(uuid4()), repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not self.name:
            raise ValueError("name is required")
        if not callable(self.callback):
            raise ValueError("callback must be callable")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "cb_id": self._cb_id,
                "name": self.name,
                "enabled": self.enabled,
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
                "cb_id": self._cb_id,
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
            "cb_id": self._cb_id,
            "name": self.name,
            "enabled": self.enabled,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReloadCallback:
        instance = cls(
            name=data["name"],
            callback=lambda old, new: None,  # placeholder
            enabled=data.get("enabled", True),
        )
        instance._version = data.get("version", 1)
        instance._cb_id = data.get("cb_id", str(uuid4()))
        return instance

    def clone(self) -> ReloadCallback:
        new = ReloadCallback(
            name=self.name,
            callback=self.callback,
            enabled=self.enabled,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._cb_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "cb_id": self._cb_id,
            "name": self.name,
            "enabled": self.enabled,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ReloadCallback:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 5. HotReloadWatcher (dengan entity dasar) ===
class HotReloadWatcher:
    _instance: HotReloadWatcher | None = None
    _lock: threading.Lock

    def __new__(cls) -> HotReloadWatcher:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._lock = threading.Lock()
        self._loader = get_config_loader()
        self._validator = get_schema_validator()
        self._file_hashes: dict[str, str] = {}
        self._callbacks: list[ReloadCallback] = []
        self._reload_history: list[ReloadResult] = []
        self._watching = False
        self._watch_thread: threading.Thread | None = None
        self._observer = None
        self._poll_interval = DEFAULT_POLL_INTERVAL_SECONDS
        self._watch_paths = DEFAULT_WATCH_PATHS.copy()
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._watcher_id = str(uuid4())
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "watcher_id": self._watcher_id,
                "watching": self._watching,
                "watch_paths_count": len(self._watch_paths),
                "callbacks_count": len(self._callbacks),
                "history_count": len(self._reload_history),
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
                "watcher_id": self._watcher_id,
                "details": details,
            }
        )

    # ==================== PUBLIC METHODS ====================
    def start_watching(
        self,
        paths: list[Path] | None = None,
        poll_interval: int = DEFAULT_POLL_INTERVAL_SECONDS,
        use_watchdog: bool = False,
    ) -> None:
        if self._watching:
            logger.warning("Watcher already running")
            return

        if paths:
            self._watch_paths = paths
        self._poll_interval = poll_interval
        self._update_file_hashes()

        if use_watchdog:
            self._start_watchdog()
        else:
            self._start_polling()

        self._watching = True
        self._record_audit("START_WATCHING", "system", {"paths_count": len(self._watch_paths)})
        logger.info(f"Hot reload watcher started, monitoring {len(self._watch_paths)} files")

    def _start_polling(self) -> None:
        self._watch_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._watch_thread.start()

    def _poll_loop(self) -> None:
        while self._watching:
            try:
                time.sleep(self._poll_interval)
                self._check_for_changes()
            except Exception as e:
                logger.error(f"Error in polling loop: {e}")

    def _start_watchdog(self) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer

            class ConfigFileHandler(FileSystemEventHandler):
                def __init__(self, watcher: HotReloadWatcher):
                    self.watcher = watcher

                def on_modified(self, event):
                    if not event.is_directory:
                        self.watcher._check_for_changes()

                def on_created(self, event):
                    if not event.is_directory:
                        self.watcher._check_for_changes()

            self._observer = Observer()
            for path in self._watch_paths:
                dir_path = path.parent
                if dir_path.exists():
                    self._observer.schedule(ConfigFileHandler(self), str(dir_path), recursive=False)
            self._observer.start()
            logger.info("Watchdog observer started")
        except ImportError:
            logger.warning("Watchdog not available, falling back to polling")
            self._start_polling()

    def stop_watching(self) -> None:
        self._watching = False
        if hasattr(self, "_observer") and self._observer:
            self._observer.stop()
            self._observer.join()
        self._record_audit("STOP_WATCHING", "system", {})
        logger.info("Hot reload watcher stopped")

    def _update_file_hashes(self) -> None:
        for path in self._watch_paths:
            if path.exists():
                try:
                    with open(path, "rb") as f:
                        content = f.read()
                        file_hash = hashlib.sha256(content).hexdigest()
                        self._file_hashes[str(path)] = file_hash
                except Exception as e:
                    logger.error(f"Failed to hash {path}: {e}")
            else:
                self._file_hashes.pop(str(path), None)

    def _check_for_changes(self) -> None:
        changes = []
        for path in self._watch_paths:
            if not path.exists():
                continue
            try:
                with open(path, "rb") as f:
                    content = f.read()
                    new_hash = hashlib.sha256(content).hexdigest()
                old_hash = self._file_hashes.get(str(path))
                if old_hash and old_hash != new_hash:
                    changed_keys = self._get_changed_keys(path)
                    change = ConfigChange(
                        file_path=str(path),
                        old_hash=old_hash,
                        new_hash=new_hash,
                        changed_keys=changed_keys,
                        detected_at=datetime.now(UTC),
                    )
                    changes.append(change)
                    self._file_hashes[str(path)] = new_hash
            except Exception as e:
                logger.error(f"Failed to check {path}: {e}")

        if changes:
            logger.info(f"Detected changes in {len(changes)} files")
            self._reload_config(changes)

    def _get_changed_keys(self, path: Path) -> list[str]:
        try:
            old_config = self._loader.get_current_config()
            temp_config = self._loader.load_file(path)
            changed = []
            for key in temp_config:
                old_value = self._get_nested_value(old_config, key)
                new_value = temp_config.get(key)
                if old_value != new_value:
                    changed.append(key)
            return changed
        except Exception as e:
            logger.error(f"Failed to get changed keys: {e}")
            return []

    def _get_nested_value(self, config: dict[str, Any], key: str) -> Any:
        keys = key.split(".")
        value = config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return None
            else:
                return None
        return value

    def _reload_config(self, changes: list[ConfigChange]) -> None:
        start_time = time.time()
        old_config = self._loader.get_current_config().copy()
        try:
            new_config = self._loader.reload()
            is_valid, errors = validate_config(new_config)
            if not is_valid:
                raise ValueError(f"Config validation failed: {errors}")
            for callback in self._callbacks:
                if callback.enabled:
                    try:
                        callback.callback(old_config, new_config)
                    except Exception as e:
                        logger.error(f"Callback {callback.name} failed: {e}")
            duration_ms = (time.time() - start_time) * 1000
            result = ReloadResult(
                success=True,
                timestamp=datetime.now(UTC),
                changes=changes,
                duration_ms=duration_ms,
            )
            self._reload_history.append(result)
            self._record_audit("RELOAD_CONFIG_SUCCESS", "system", {"changes_count": len(changes)})
            logger.info(f"Config reloaded successfully in {duration_ms:.2f}ms")
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            result = ReloadResult(
                success=False,
                timestamp=datetime.now(UTC),
                changes=changes,
                error_message=str(e),
                duration_ms=duration_ms,
            )
            self._reload_history.append(result)
            self._record_audit("RELOAD_CONFIG_FAILED", "system", {"error": str(e)})
            logger.error(f"Config reload failed: {e}")

    def force_reload(self) -> ReloadResult:
        logger.info("Forced config reload initiated")
        changes = [
            ConfigChange(
                file_path="manual",
                old_hash="",
                new_hash="",
                changed_keys=["all"],
                detected_at=datetime.now(UTC),
            )
        ]
        start_time = time.time()
        try:
            new_config = self._loader.reload()
            is_valid, errors = validate_config(new_config)
            if not is_valid:
                raise ValueError(f"Config validation failed: {errors}")
            duration_ms = (time.time() - start_time) * 1000
            result = ReloadResult(
                success=True,
                timestamp=datetime.now(UTC),
                changes=changes,
                duration_ms=duration_ms,
            )
            self._reload_history.append(result)
            self._record_audit("FORCE_RELOAD_SUCCESS", "system", {})
            return result
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            result = ReloadResult(
                success=False,
                timestamp=datetime.now(UTC),
                changes=changes,
                error_message=str(e),
                duration_ms=duration_ms,
            )
            self._reload_history.append(result)
            self._record_audit("FORCE_RELOAD_FAILED", "system", {"error": str(e)})
            return result

    def register_callback(
        self, name: str, callback: Callable[[dict[str, Any], dict[str, Any]], None]
    ) -> None:
        with self._lock:
            self._callbacks.append(ReloadCallback(name=name, callback=callback))
        self._record_audit("REGISTER_CALLBACK", "system", {"name": name})
        logger.info(f"Registered reload callback: {name}")

    def unregister_callback(self, name: str) -> bool:
        with self._lock:
            for i, cb in enumerate(self._callbacks):
                if cb.name == name:
                    self._callbacks.pop(i)
                    self._record_audit("UNREGISTER_CALLBACK", "system", {"name": name})
                    logger.info(f"Unregistered reload callback: {name}")
                    return True
        return False

    def enable_callback(self, name: str, enabled: bool) -> bool:
        with self._lock:
            for cb in self._callbacks:
                if cb.name == name:
                    cb.enabled = enabled
                    self._record_audit(
                        "ENABLE_CALLBACK", "system", {"name": name, "enabled": enabled}
                    )
                    return True
        return False

    def get_reload_history(self, limit: int = 20) -> list[ReloadResult]:
        return self._reload_history[-limit:]

    def get_last_reload(self) -> ReloadResult | None:
        return self._reload_history[-1] if self._reload_history else None

    def get_watched_files(self) -> list[str]:
        return [str(p) for p in self._watch_paths]

    def is_watching(self) -> bool:
        return self._watching

    def add_watch_path(self, path: Path) -> None:
        if path not in self._watch_paths:
            self._watch_paths.append(path)
            if path.exists():
                with open(path, "rb") as f:
                    content = f.read()
                    self._file_hashes[str(path)] = hashlib.sha256(content).hexdigest()
            self._record_audit("ADD_WATCH_PATH", "system", {"path": str(path)})
            logger.info(f"Added watch path: {path}")

    def remove_watch_path(self, path: Path) -> bool:
        if path in self._watch_paths:
            self._watch_paths.remove(path)
            self._file_hashes.pop(str(path), None)
            self._record_audit("REMOVE_WATCH_PATH", "system", {"path": str(path)})
            logger.info(f"Removed watch path: {path}")
            return True
        return False

    def get_status(self) -> dict[str, Any]:
        return {
            "watcher_id": self._watcher_id,
            "is_watching": self._watching,
            "watched_files": self.get_watched_files(),
            "poll_interval_seconds": self._poll_interval,
            "registered_callbacks": [cb.name for cb in self._callbacks],
            "total_reloads": len(self._reload_history),
            "last_reload": self.get_last_reload().to_dict() if self.get_last_reload() else None,
            "last_reload_success": self.get_last_reload().success
            if self.get_last_reload()
            else None,
            "version": self._version,
        }

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self._poll_interval <= 0:
            errors.append("poll_interval_seconds must be positive")
        for cb in self._callbacks:
            res = cb.validate()
            if not res["is_valid"]:
                errors.extend([f"Callback {cb.name}: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "watcher_id": self._watcher_id,
            "watching": self._watching,
            "poll_interval": self._poll_interval,
            "watch_paths": self.get_watched_files(),
            "callbacks_count": len(self._callbacks),
            "history_count": len(self._reload_history),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HotReloadWatcher:
        instance = cls()
        instance._poll_interval = data.get("poll_interval", DEFAULT_POLL_INTERVAL_SECONDS)
        instance._version = data.get("version", 1)
        instance._watcher_id = data.get("watcher_id", str(uuid4()))
        return instance

    def clone(self) -> HotReloadWatcher:
        new = HotReloadWatcher()
        new._poll_interval = self._poll_interval
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._watcher_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "watcher_id": self._watcher_id,
            "watching": self._watching,
            "watch_paths_count": len(self._watch_paths),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> HotReloadWatcher:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self.stop_watching()
        self._file_hashes = {}
        self._callbacks = []
        self._reload_history = []
        self._watching = False
        self._watch_paths = DEFAULT_WATCH_PATHS.copy()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._watcher_id = str(uuid4())
        self._record_audit("RESET", "system", {})


# === 6. SINGLETON ACCESSOR ===
_hot_reload_watcher_instance: HotReloadWatcher | None = None


def get_hot_reload_watcher() -> HotReloadWatcher:
    global _hot_reload_watcher_instance
    if _hot_reload_watcher_instance is None:
        _hot_reload_watcher_instance = HotReloadWatcher()
    return _hot_reload_watcher_instance


# === 7. EXPORTS ===
__all__ = [
    "ConfigChange",
    "HotReloadWatcher",
    "ReloadCallback",
    "ReloadResult",
    "get_hot_reload_watcher",
]
