# test_hot_reload_watcher.py
# Comprehensive tests for config/hot_reload_watcher.py
# Covers all methods and edge cases with proper mocking.

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from config.hot_reload_watcher import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_WATCH_PATHS,
    ConfigChange,
    HotReloadWatcher,
    ReloadCallback,
    ReloadResult,
    get_hot_reload_watcher,
)


# -------------------- Fixtures --------------------
@pytest.fixture
def config_change_data():
    return {
        "file_path": "/test/config.yaml",
        "old_hash": "oldhash123",
        "new_hash": "newhash456",
        "changed_keys": ["key1", "key2"],
        "detected_at": datetime.now(UTC),
    }


@pytest.fixture
def config_change(config_change_data):
    return ConfigChange(**config_change_data)


@pytest.fixture
def reload_result_data():
    return {
        "success": True,
        "timestamp": datetime.now(UTC),
        "changes": [],
        "error_message": None,
        "rollback_performed": False,
        "duration_ms": 12.5,
    }


@pytest.fixture
def reload_result(reload_result_data):
    return ReloadResult(**reload_result_data)


@pytest.fixture
def reload_callback():
    return ReloadCallback(name="test_cb", callback=lambda old, new: None)


@pytest.fixture
def mock_loader():
    with patch("config.hot_reload_watcher.get_config_loader") as mock:
        loader = MagicMock()
        loader.get_current_config.return_value = {"foo": "bar"}
        loader.load_file.return_value = {"foo": "baz"}
        loader.reload.return_value = {"foo": "baz"}
        mock.return_value = loader
        yield loader


@pytest.fixture
def mock_validator():
    with patch("config.hot_reload_watcher.get_schema_validator") as mock:
        validator = MagicMock()
        mock.return_value = validator
        yield validator


@pytest.fixture
def mock_validate_config():
    with patch("config.hot_reload_watcher.validate_config") as mock:
        mock.return_value = (True, [])
        yield mock


@pytest.fixture
def mock_file_operations():
    with patch("pathlib.Path.exists") as mock_exists, \
         patch("builtins.open", mock_open(read_data=b"fake content")) as mock_file:
        mock_exists.return_value = True
        yield mock_exists, mock_file


@pytest.fixture
def watcher(mock_loader, mock_validator, mock_validate_config, mock_file_operations):
    # Reset singleton before each test
    HotReloadWatcher._instance = None
    instance = HotReloadWatcher()
    # Reset internal state for clean testing
    instance._file_hashes = {}
    instance._callbacks = []
    instance._reload_history = []
    instance._watching = False
    instance._watch_thread = None
    instance._observer = None
    instance._version = 1
    instance._audit_trail = []
    instance._snapshots = []
    return instance


# -------------------- Tests for ConfigChange --------------------
class TestConfigChange:
    def test_construction_success(self, config_change_data):
        change = ConfigChange(**config_change_data)
        assert change.file_path == config_change_data["file_path"]
        assert change.old_hash == config_change_data["old_hash"]
        assert change.new_hash == config_change_data["new_hash"]
        assert change.changed_keys == config_change_data["changed_keys"]
        assert change._version == 1
        assert len(change._snapshots) == 1  # __post_init__ takes snapshot

    def test_construction_invalid_no_file_path(self):
        with pytest.raises(ValueError, match="file_path is required"):
            ConfigChange(file_path="", old_hash="a", new_hash="b", changed_keys=[], detected_at=datetime.now(UTC))

    def test_construction_invalid_no_hash(self):
        with pytest.raises(ValueError, match="at least one hash must be provided"):
            ConfigChange(file_path="x", old_hash="", new_hash="", changed_keys=[], detected_at=datetime.now(UTC))

    def test_construction_tz_aware(self):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        change = ConfigChange(file_path="x", old_hash="a", new_hash="b", changed_keys=[], detected_at=naive)
        assert change.detected_at.tzinfo is not None
        assert change.detected_at.tzinfo == UTC

    def test_has_changes(self, config_change):
        assert config_change.has_changes() is True
        change2 = ConfigChange(file_path="x", old_hash="a", new_hash="b", changed_keys=[], detected_at=datetime.now(UTC))
        assert change2.has_changes() is False

    def test_validate_valid(self, config_change):
        result = config_change.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid(self):
        change = ConfigChange(file_path="", old_hash="", new_hash="", changed_keys=[], detected_at=datetime.now(UTC))
        result = change.validate()
        assert result["is_valid"] is False
        assert len(result["errors"]) > 0

    def test_to_dict(self, config_change):
        d = config_change.to_dict()
        assert "change_id" in d
        assert d["file_path"] == config_change.file_path
        assert "old_hash" in d
        assert "new_hash" in d
        assert d["changed_keys"] == config_change.changed_keys
        assert "detected_at" in d
        assert d["version"] == config_change._version

    def test_from_dict(self, config_change):
        d = config_change.to_dict()
        # rebuild with full hashes (to_dict truncates)
        d["old_hash"] = config_change.old_hash
        d["new_hash"] = config_change.new_hash
        restored = ConfigChange.from_dict(d)
        assert restored.file_path == config_change.file_path
        assert restored.old_hash == config_change.old_hash
        assert restored.new_hash == config_change.new_hash
        assert restored.changed_keys == config_change.changed_keys
        assert restored._version == config_change._version
        assert restored._change_id == config_change._change_id

    def test_clone(self, config_change):
        cloned = config_change.clone()
        assert cloned.file_path == config_change.file_path
        assert cloned.old_hash == config_change.old_hash
        assert cloned.new_hash == config_change.new_hash
        assert cloned.changed_keys == config_change.changed_keys
        assert cloned._version == config_change._version + 1
        assert cloned.detected_at != config_change.detected_at  # new timestamp
        # audit trail should have CLONE entry
        assert len(cloned._audit_trail) == 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self, config_change):
        snap = config_change.snapshot()
        assert snap["version"] == config_change._version
        assert snap["change_id"] == config_change._change_id
        assert snap["file_path"] == config_change.file_path
        assert "timestamp" in snap

    def test_version(self, config_change):
        assert config_change.version() == config_change._version

    def test_audit_trail(self, config_change):
        # initially no audit entries
        assert config_change.audit_trail() == []
        # touch adds entry
        config_change.touch("tester")
        trail = config_change.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "tester"
        assert trail[0]["version"] == config_change._version

    def test_touch(self, config_change):
        old_version = config_change._version
        touched = config_change.touch("tester")
        assert touched._version == old_version + 1
        assert len(touched._audit_trail) == 1
        assert touched._audit_trail[0]["action"] == "TOUCH"


# -------------------- Tests for ReloadResult --------------------
class TestReloadResult:
    def test_construction_success(self, reload_result_data):
        result = ReloadResult(**reload_result_data)
        assert result.success is True
        assert result.error_message is None
        assert result.rollback_performed is False
        assert result.duration_ms == 12.5
        assert len(result._snapshots) == 1

    def test_construction_invalid_success_not_bool(self):
        with pytest.raises(ValueError, match="success must be boolean"):
            ReloadResult(success="yes", timestamp=datetime.now(UTC), changes=[])

    def test_construction_invalid_negative_duration(self):
        with pytest.raises(ValueError, match="duration_ms cannot be negative"):
            ReloadResult(success=True, timestamp=datetime.now(UTC), changes=[], duration_ms=-1.0)

    def test_construction_invalid_missing_error_message(self):
        with pytest.raises(ValueError, match="error_message required when success=False"):
            ReloadResult(success=False, timestamp=datetime.now(UTC), changes=[], error_message=None)

    def test_construction_tz_aware(self):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        result = ReloadResult(success=True, timestamp=naive, changes=[])
        assert result.timestamp.tzinfo == UTC

    def test_validate_valid(self, reload_result):
        result = reload_result.validate()
        assert result["is_valid"] is True

    def test_validate_invalid(self):
        result = ReloadResult(success=False, timestamp=datetime.now(UTC), changes=[], error_message=None)
        validation = result.validate()
        assert validation["is_valid"] is False
        assert "error_message required" in validation["errors"][0]

    def test_to_dict(self, reload_result):
        d = reload_result.to_dict()
        assert d["result_id"] == reload_result._result_id
        assert d["success"] is True
        assert "timestamp" in d
        assert d["changes"] == []
        assert d["error_message"] is None
        assert d["rollback_performed"] is False
        assert d["duration_ms"] == 12.5
        assert d["version"] == reload_result._version

    def test_from_dict(self, reload_result):
        d = reload_result.to_dict()
        restored = ReloadResult.from_dict(d)
        assert restored.success == reload_result.success
        assert restored.error_message == reload_result.error_message
        assert restored.rollback_performed == reload_result.rollback_performed
        assert restored.duration_ms == reload_result.duration_ms
        assert restored._version == reload_result._version
        assert restored._result_id == reload_result._result_id
        # timestamp comparison: we don't compare exact due to iso format, but check presence
        assert restored.timestamp is not None

    def test_clone(self, reload_result):
        cloned = reload_result.clone()
        assert cloned.success == reload_result.success
        assert cloned.error_message == reload_result.error_message
        assert cloned.rollback_performed == reload_result.rollback_performed
        assert cloned.duration_ms == reload_result.duration_ms
        assert cloned._version == reload_result._version + 1
        assert cloned.timestamp != reload_result.timestamp
        assert len(cloned._audit_trail) == 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self, reload_result):
        snap = reload_result.snapshot()
        assert snap["version"] == reload_result._version
        assert snap["result_id"] == reload_result._result_id
        assert snap["success"] is True
        assert "timestamp" in snap

    def test_version(self, reload_result):
        assert reload_result.version() == reload_result._version

    def test_audit_trail(self, reload_result):
        reload_result.touch("tester")
        trail = reload_result.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "tester"

    def test_touch(self, reload_result):
        old_version = reload_result._version
        touched = reload_result.touch("tester")
        assert touched._version == old_version + 1
        assert len(touched._audit_trail) == 1
        assert touched._audit_trail[0]["action"] == "TOUCH"


# -------------------- Tests for ReloadCallback --------------------
class TestReloadCallback:
    def test_construction_success(self):
        cb = ReloadCallback(name="cb", callback=lambda x, y: None)
        assert cb.name == "cb"
        assert cb.enabled is True
        assert len(cb._snapshots) == 1

    def test_construction_invalid_no_name(self):
        with pytest.raises(ValueError, match="name is required"):
            ReloadCallback(name="", callback=lambda x, y: None)

    def test_construction_invalid_not_callable(self):
        with pytest.raises(ValueError, match="callback must be callable"):
            ReloadCallback(name="cb", callback="not callable")

    def test_validate_valid(self, reload_callback):
        result = reload_callback.validate()
        assert result["is_valid"] is True

    def test_validate_invalid(self):
        cb = ReloadCallback(name="", callback=lambda x, y: None)
        result = cb.validate()
        assert result["is_valid"] is False
        assert "name is required" in result["errors"][0]

    def test_to_dict(self, reload_callback):
        d = reload_callback.to_dict()
        assert d["cb_id"] == reload_callback._cb_id
        assert d["name"] == "test_cb"
        assert d["enabled"] is True
        assert d["version"] == reload_callback._version

    def test_from_dict(self, reload_callback):
        d = reload_callback.to_dict()
        # from_dict uses placeholder callback
        restored = ReloadCallback.from_dict(d)
        assert restored.name == reload_callback.name
        assert restored.enabled == reload_callback.enabled
        assert restored._version == reload_callback._version
        assert restored._cb_id == reload_callback._cb_id
        # callback is a placeholder (lambda)
        assert callable(restored.callback)

    def test_clone(self, reload_callback):
        cloned = reload_callback.clone()
        assert cloned.name == reload_callback.name
        assert cloned.enabled == reload_callback.enabled
        assert cloned._version == reload_callback._version + 1
        assert cloned._cb_id != reload_callback._cb_id
        assert len(cloned._audit_trail) == 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self, reload_callback):
        snap = reload_callback.snapshot()
        assert snap["version"] == reload_callback._version
        assert snap["cb_id"] == reload_callback._cb_id
        assert snap["name"] == "test_cb"
        assert snap["enabled"] is True
        assert "timestamp" in snap

    def test_version(self, reload_callback):
        assert reload_callback.version() == reload_callback._version

    def test_audit_trail(self, reload_callback):
        reload_callback.touch("tester")
        trail = reload_callback.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"

    def test_touch(self, reload_callback):
        old_version = reload_callback._version
        touched = reload_callback.touch("tester")
        assert touched._version == old_version + 1
        assert len(touched._audit_trail) == 1
        assert touched._audit_trail[0]["action"] == "TOUCH"


# -------------------- Tests for HotReloadWatcher --------------------
class TestHotReloadWatcher:
    def test_singleton(self):
        w1 = HotReloadWatcher()
        w2 = HotReloadWatcher()
        assert w1 is w2

    def test_construction(self, watcher):
        assert watcher._watching is False
        assert watcher._watch_paths == DEFAULT_WATCH_PATHS
        assert watcher._poll_interval == DEFAULT_POLL_INTERVAL_SECONDS
        assert watcher._version == 1
        assert len(watcher._snapshots) == 1

    # ----- start_watching / stop_watching -----
    @patch("threading.Thread")
    def test_start_watching_polling(self, mock_thread, watcher, mock_file_operations):
        watcher.start_watching(poll_interval=2, use_watchdog=False)
        assert watcher._watching is True
        assert watcher._poll_interval == 2
        mock_thread.assert_called_once()
        # _update_file_hashes should have been called
        assert len(watcher._file_hashes) == len(DEFAULT_WATCH_PATHS)
        # audit trail
        trail = watcher.audit_trail()
        assert any(entry["action"] == "START_WATCHING" for entry in trail)

    @patch("config.hot_reload_watcher.Observer")
    def test_start_watching_watchdog(self, mock_observer, watcher, mock_file_operations):
        # Mock watchdog availability
        with patch.dict("sys.modules", {"watchdog": MagicMock(), "watchdog.events": MagicMock(), "watchdog.observers": MagicMock()}):
            watcher.start_watching(use_watchdog=True)
            assert watcher._watching is True
            mock_observer.assert_called_once()

    def test_start_watching_already_running(self, watcher):
        watcher._watching = True
        watcher.start_watching()
        # should not restart, just log warning
        assert watcher._watching is True

    def test_stop_watching(self, watcher):
        watcher._watching = True
        watcher._watch_thread = MagicMock()
        watcher.stop_watching()
        assert watcher._watching is False
        trail = watcher.audit_trail()
        assert any(entry["action"] == "STOP_WATCHING" for entry in trail)

    def test_stop_watching_with_observer(self, watcher):
        watcher._watching = True
        observer = MagicMock()
        watcher._observer = observer
        watcher.stop_watching()
        observer.stop.assert_called_once()
        observer.join.assert_called_once()

    # ----- _update_file_hashes, _check_for_changes, _reload_config -----
    @patch("pathlib.Path.exists")
    @patch("builtins.open", mock_open(read_data=b"content"))
    def test_update_file_hashes(self, mock_exists, watcher):
        mock_exists.return_value = True
        watcher._update_file_hashes()
        assert len(watcher._file_hashes) == len(DEFAULT_WATCH_PATHS)
        for path in DEFAULT_WATCH_PATHS:
            assert str(path) in watcher._file_hashes
            # hash should be sha256 of "content"
            expected = hashlib.sha256(b"content").hexdigest()
            assert watcher._file_hashes[str(path)] == expected

    @patch("pathlib.Path.exists")
    @patch("builtins.open", mock_open(read_data=b"new content"))
    def test_check_for_changes_detects_change(self, mock_exists, watcher, mock_loader, mock_validate_config):
        # Setup initial hash
        path = DEFAULT_WATCH_PATHS[0]
        watcher._file_hashes[str(path)] = hashlib.sha256(b"old content").hexdigest()
        mock_exists.return_value = True
        # Mock loader.get_current_config and load_file
        mock_loader.get_current_config.return_value = {"foo": "old"}
        mock_loader.load_file.return_value = {"foo": "new"}
        # Mock validate_config to return success
        mock_validate_config.return_value = (True, [])
        # Call
        watcher._check_for_changes()
        # Should have detected change and called _reload_config
        assert len(watcher._reload_history) == 1
        result = watcher._reload_history[0]
        assert result.success is True
        assert len(result.changes) == 1
        change = result.changes[0]
        assert change.file_path == str(path)
        assert change.old_hash != change.new_hash
        # file hash updated
        new_hash = hashlib.sha256(b"new content").hexdigest()
        assert watcher._file_hashes[str(path)] == new_hash

    @patch("pathlib.Path.exists")
    def test_check_for_changes_no_change(self, mock_exists, watcher):
        path = DEFAULT_WATCH_PATHS[0]
        hash_val = hashlib.sha256(b"same").hexdigest()
        watcher._file_hashes[str(path)] = hash_val
        with patch("builtins.open", mock_open(read_data=b"same")):
            mock_exists.return_value = True
            watcher._check_for_changes()
            assert len(watcher._reload_history) == 0

    def test_reload_config_success(self, watcher, mock_loader, mock_validate_config):
        changes = [MagicMock(spec=ConfigChange)]
        mock_loader.reload.return_value = {"foo": "new"}
        mock_validate_config.return_value = (True, [])
        watcher._reload_config(changes)
        assert len(watcher._reload_history) == 1
        result = watcher._reload_history[0]
        assert result.success is True
        assert result.changes == changes
        assert result.duration_ms > 0

    def test_reload_config_failure(self, watcher, mock_loader, mock_validate_config):
        changes = [MagicMock(spec=ConfigChange)]
        mock_loader.reload.side_effect = ValueError("Invalid config")
        mock_validate_config.return_value = (False, ["error"])
        watcher._reload_config(changes)
        assert len(watcher._reload_history) == 1
        result = watcher._reload_history[0]
        assert result.success is False
        assert "Invalid config" in result.error_message
        # audit trail for failure
        trail = watcher.audit_trail()
        assert any(entry["action"] == "RELOAD_CONFIG_FAILED" for entry in trail)

    def test_reload_config_with_callbacks(self, watcher, mock_loader, mock_validate_config):
        cb = MagicMock()
        watcher.register_callback("test", cb)
        changes = [MagicMock(spec=ConfigChange)]
        mock_loader.reload.return_value = {"foo": "new"}
        mock_validate_config.return_value = (True, [])
        watcher._reload_config(changes)
        cb.assert_called_once_with({"foo": "bar"}, {"foo": "new"})

    def test_reload_config_disabled_callback(self, watcher, mock_loader, mock_validate_config):
        cb = MagicMock()
        watcher.register_callback("test", cb)
        watcher.enable_callback("test", False)
        changes = [MagicMock(spec=ConfigChange)]
        mock_loader.reload.return_value = {"foo": "new"}
        mock_validate_config.return_value = (True, [])
        watcher._reload_config(changes)
        cb.assert_not_called()

    # ----- force_reload -----
    def test_force_reload_success(self, watcher, mock_loader, mock_validate_config):
        mock_loader.reload.return_value = {"foo": "new"}
        mock_validate_config.return_value = (True, [])
        result = watcher.force_reload()
        assert result.success is True
        assert len(result.changes) == 1
        assert result.changes[0].file_path == "manual"
        assert len(watcher._reload_history) == 1
        trail = watcher.audit_trail()
        assert any(entry["action"] == "FORCE_RELOAD_SUCCESS" for entry in trail)

    def test_force_reload_failure(self, watcher, mock_loader, mock_validate_config):
        mock_loader.reload.side_effect = ValueError("Config error")
        mock_validate_config.return_value = (True, [])
        result = watcher.force_reload()
        assert result.success is False
        assert "Config error" in result.error_message
        trail = watcher.audit_trail()
        assert any(entry["action"] == "FORCE_RELOAD_FAILED" for entry in trail)

    # ----- callbacks management -----
    def test_register_callback(self, watcher):
        cb = lambda x, y: None
        watcher.register_callback("test", cb)
        assert len(watcher._callbacks) == 1
        assert watcher._callbacks[0].name == "test"
        assert watcher._callbacks[0].callback is cb
        trail = watcher.audit_trail()
        assert any(entry["action"] == "REGISTER_CALLBACK" for entry in trail)

    def test_unregister_callback_exists(self, watcher):
        watcher.register_callback("test", lambda x, y: None)
        assert watcher.unregister_callback("test") is True
        assert len(watcher._callbacks) == 0
        trail = watcher.audit_trail()
        assert any(entry["action"] == "UNREGISTER_CALLBACK" for entry in trail)

    def test_unregister_callback_not_exists(self, watcher):
        assert watcher.unregister_callback("nonexistent") is False

    def test_enable_callback(self, watcher):
        watcher.register_callback("test", lambda x, y: None)
        assert watcher.enable_callback("test", False) is True
        assert watcher._callbacks[0].enabled is False
        trail = watcher.audit_trail()
        assert any(entry["action"] == "ENABLE_CALLBACK" for entry in trail)

    def test_enable_callback_not_exists(self, watcher):
        assert watcher.enable_callback("nonexistent", False) is False

    # ----- history / status -----
    def test_get_reload_history(self, watcher):
        # add some history
        for _ in range(5):
            watcher._reload_history.append(MagicMock(spec=ReloadResult))
        history = watcher.get_reload_history(3)
        assert len(history) == 3

    def test_get_last_reload(self, watcher):
        assert watcher.get_last_reload() is None
        result = MagicMock(spec=ReloadResult)
        watcher._reload_history.append(result)
        assert watcher.get_last_reload() == result

    def test_get_watched_files(self, watcher):
        files = watcher.get_watched_files()
        assert files == [str(p) for p in DEFAULT_WATCH_PATHS]

    def test_is_watching(self, watcher):
        assert watcher.is_watching() is False
        watcher._watching = True
        assert watcher.is_watching() is True

    # ----- watch path management -----
    @patch("pathlib.Path.exists")
    @patch("builtins.open", mock_open(read_data=b"data"))
    def test_add_watch_path(self, mock_exists, watcher):
        mock_exists.return_value = True
        new_path = Path("/new/path.yaml")
        watcher.add_watch_path(new_path)
        assert new_path in watcher._watch_paths
        assert str(new_path) in watcher._file_hashes
        trail = watcher.audit_trail()
        assert any(entry["action"] == "ADD_WATCH_PATH" for entry in trail)

    def test_add_watch_path_already_exists(self, watcher):
        path = DEFAULT_WATCH_PATHS[0]
        watcher.add_watch_path(path)
        # should not duplicate
        assert watcher._watch_paths.count(path) == 1

    def test_remove_watch_path_exists(self, watcher):
        path = DEFAULT_WATCH_PATHS[0]
        watcher._file_hashes[str(path)] = "hash"
        assert watcher.remove_watch_path(path) is True
        assert path not in watcher._watch_paths
        assert str(path) not in watcher._file_hashes
        trail = watcher.audit_trail()
        assert any(entry["action"] == "REMOVE_WATCH_PATH" for entry in trail)

    def test_remove_watch_path_not_exists(self, watcher):
        assert watcher.remove_watch_path(Path("/nonexistent")) is False

    # ----- get_status -----
    def test_get_status(self, watcher):
        watcher._watching = True
        watcher._poll_interval = 10
        status = watcher.get_status()
        assert status["watcher_id"] == watcher._watcher_id
        assert status["is_watching"] is True
        assert status["poll_interval_seconds"] == 10
        assert status["watched_files"] == [str(p) for p in DEFAULT_WATCH_PATHS]
        assert status["registered_callbacks"] == []
        assert status["total_reloads"] == 0
        assert status["last_reload"] is None
        assert status["last_reload_success"] is None
        assert status["version"] == watcher._version

    # ----- entity methods -----
    def test_validate(self, watcher):
        # valid by default
        result = watcher.validate()
        assert result["is_valid"] is True
        # set invalid poll interval
        watcher._poll_interval = -1
        result = watcher.validate()
        assert result["is_valid"] is False
        assert "poll_interval_seconds must be positive" in result["errors"][0]

    def test_to_dict(self, watcher):
        d = watcher.to_dict()
        assert d["watcher_id"] == watcher._watcher_id
        assert d["watching"] is False
        assert d["poll_interval"] == DEFAULT_POLL_INTERVAL_SECONDS
        assert d["watch_paths"] == [str(p) for p in DEFAULT_WATCH_PATHS]
        assert d["callbacks_count"] == 0
        assert d["history_count"] == 0
        assert d["version"] == watcher._version

    def test_from_dict(self, watcher):
        d = watcher.to_dict()
        restored = HotReloadWatcher.from_dict(d)
        assert restored._poll_interval == watcher._poll_interval
        assert restored._version == watcher._version
        assert restored._watcher_id == watcher._watcher_id

    def test_clone(self, watcher):
        cloned = watcher.clone()
        assert cloned._poll_interval == watcher._poll_interval
        assert cloned._version == watcher._version + 1
        assert cloned._watcher_id != watcher._watcher_id
        assert len(cloned._audit_trail) == 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self, watcher):
        snap = watcher.snapshot()
        assert snap["version"] == watcher._version
        assert snap["watcher_id"] == watcher._watcher_id
        assert snap["watching"] is False
        assert snap["watch_paths_count"] == len(DEFAULT_WATCH_PATHS)
        assert "timestamp" in snap

    def test_version(self, watcher):
        assert watcher.version() == watcher._version

    def test_audit_trail(self, watcher):
        watcher.touch("tester")
        trail = watcher.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"

    def test_touch(self, watcher):
        old_version = watcher._version
        watcher.touch("tester")
        assert watcher._version == old_version + 1
        trail = watcher.audit_trail()
        assert any(entry["action"] == "TOUCH" for entry in trail)

    def test_reset(self, watcher):
        watcher._watching = True
        watcher._watch_paths = [Path("/custom")]
        watcher._callbacks = [MagicMock()]
        watcher._reload_history = [MagicMock()]
        watcher.reset()
        assert watcher._watching is False
        assert watcher._watch_paths == DEFAULT_WATCH_PATHS
        assert watcher._callbacks == []
        assert watcher._reload_history == []
        assert watcher._version == 1
        assert watcher._audit_trail == []
        assert len(watcher._snapshots) == 0  # reset clears snapshots
        trail = watcher.audit_trail()
        assert any(entry["action"] == "RESET" for entry in trail)


# -------------------- Test for module-level getter --------------------
def test_get_hot_reload_watcher():
    # Reset singleton
    HotReloadWatcher._instance = None
    w1 = get_hot_reload_watcher()
    w2 = get_hot_reload_watcher()
    assert w1 is w2
    assert isinstance(w1, HotReloadWatcher)
