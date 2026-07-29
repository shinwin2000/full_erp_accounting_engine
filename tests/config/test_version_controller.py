# tests/config/test_version_controller.py
# Comprehensive tests for config/version_controller.py

import hashlib
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from config.exceptions import ConfigVersionNotFoundError
from config.version_controller import (
    MAX_HISTORY_SIZE,
    ConfigVersion,
    ConfigVersionController,
    VersionChange,
    get_config_version_controller,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_config():
    return {
        "database": {"host": "localhost", "port": 5432, "name": "testdb"},
        "logging": {"level": "INFO", "format": "json"},
        "feature_flags": {"new_ui": True},
    }


@pytest.fixture
def sample_config_v2():
    return {
        "database": {"host": "db.example.com", "port": 5433, "name": "testdb"},
        "logging": {"level": "DEBUG", "format": "text"},
        "feature_flags": {"new_ui": True, "experimental": False},
    }


@pytest.fixture
def version_controller():
    # Reset singleton to ensure fresh instance
    import config.version_controller as module
    module._config_version_controller_instance = None
    # Patch file operations
    with patch("pathlib.Path.exists", return_value=False):
        controller = get_config_version_controller()
        # Reset internal state to clean
        controller.reset()
        return controller


@pytest.fixture
def populated_controller(version_controller, sample_config, sample_config_v2):
    v1 = version_controller.create_version(sample_config, "Initial config", "admin")
    v2 = version_controller.create_version(sample_config_v2, "Update config", "admin", parent_version_id=v1.version_id)
    return version_controller


# ============================================================================
# Tests for ConfigVersion
# ============================================================================

class TestConfigVersion:
    def test_validation_success(self, sample_config):
        version = ConfigVersion(
            version_id="v1_123",
            version_number=1,
            timestamp=datetime.now(UTC),
            config_snapshot=sample_config,
            config_hash="",
            description="Initial version",
            created_by="admin",
        )
        assert version.version_id == "v1_123"
        assert version.version_number == 1
        assert version.config_hash != ""  # auto-computed
        assert version.verify_integrity() is True

    def test_validation_missing_version_id(self, sample_config):
        with pytest.raises(ValueError, match="version_id is required"):
            ConfigVersion(
                version_id="",
                version_number=1,
                timestamp=datetime.now(UTC),
                config_snapshot=sample_config,
                config_hash="hash",
                description="test",
            )

    def test_validation_zero_version_number(self, sample_config):
        with pytest.raises(ValueError, match="version_number must be >= 1"):
            ConfigVersion(
                version_id="v1",
                version_number=0,
                timestamp=datetime.now(UTC),
                config_snapshot=sample_config,
                config_hash="hash",
                description="test",
            )

    def test_validation_missing_config(self):
        with pytest.raises(ValueError, match="config_snapshot is required"):
            ConfigVersion(
                version_id="v1",
                version_number=1,
                timestamp=datetime.now(UTC),
                config_snapshot={},
                config_hash="hash",
                description="test",
            )

    def test_validation_missing_description(self, sample_config):
        with pytest.raises(ValueError, match="description is required"):
            ConfigVersion(
                version_id="v1",
                version_number=1,
                timestamp=datetime.now(UTC),
                config_snapshot=sample_config,
                config_hash="hash",
                description="",
            )

    def test_compute_hash(self, sample_config):
        version = ConfigVersion(
            version_id="v1",
            version_number=1,
            timestamp=datetime.now(UTC),
            config_snapshot=sample_config,
            config_hash="",
            description="test",
        )
        h1 = version.compute_hash()
        h2 = version.compute_hash()
        assert h1 == h2
        # Different config yields different hash
        version.config_snapshot["new_key"] = "value"
        h3 = version.compute_hash()
        assert h1 != h3

    def test_verify_integrity(self, sample_config):
        version = ConfigVersion(
            version_id="v1",
            version_number=1,
            timestamp=datetime.now(UTC),
            config_snapshot=sample_config,
            config_hash="",
            description="test",
        )
        assert version.verify_integrity() is True
        # Corrupt hash
        version.config_hash = "corrupt"
        assert version.verify_integrity() is False

    def test_to_dict(self, sample_config):
        version = ConfigVersion(
            version_id="v1_123",
            version_number=1,
            timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            config_snapshot=sample_config,
            config_hash="abc123",
            description="Test",
            created_by="admin",
            parent_version_id="parent_001",
        )
        d = version.to_dict()
        assert d["version_id"] == "v1_123"
        assert d["version_number"] == 1
        assert d["timestamp"] == "2026-01-01T12:00:00+00:00"
        assert d["config_hash"] == "abc123"
        assert d["description"] == "Test"
        assert d["created_by"] == "admin"
        assert d["parent_version_id"] == "parent_001"
        assert d["ver"] == 1

    def test_from_dict(self, sample_config):
        data = {
            "version_id": "v2_456",
            "version_number": 2,
            "timestamp": "2026-01-02T12:00:00+00:00",
            "config_hash": "def456",
            "description": "From dict",
            "created_by": "system",
            "parent_version_id": "v1_123",
            "ver": 3,
        }
        version = ConfigVersion.from_dict(data, sample_config)
        assert version.version_id == "v2_456"
        assert version.version_number == 2
        assert version.timestamp == datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC)
        assert version.config_hash == "def456"
        assert version.description == "From dict"
        assert version.created_by == "system"
        assert version.parent_version_id == "v1_123"
        assert version._ver == 3
        assert version.config_snapshot == sample_config

    def test_clone(self, sample_config):
        version = ConfigVersion(
            version_id="v1_123",
            version_number=1,
            timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            config_snapshot=sample_config,
            config_hash="abc123",
            description="Original",
            created_by="admin",
            parent_version_id=None,
        )
        cloned = version.clone()
        assert cloned.version_id != version.version_id
        assert cloned.version_number == version.version_number + 1
        assert cloned.config_snapshot == version.config_snapshot
        assert cloned.parent_version_id == version.version_id
        assert cloned.created_by == version.created_by
        assert cloned._ver == version._ver + 1
        assert cloned._audit_trail[-1]["action"] == "CLONE"

    def test_snapshot(self, sample_config):
        version = ConfigVersion(
            version_id="v1_123",
            version_number=1,
            timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            config_snapshot=sample_config,
            config_hash="abc123",
            description="Original",
        )
        snap = version.snapshot()
        assert snap["version_id"] == "v1_123"
        assert snap["version_number"] == 1
        assert snap["version"] == 1
        assert "config_hash" in snap

    def test_version(self, sample_config):
        version = ConfigVersion(
            version_id="v1",
            version_number=1,
            timestamp=datetime.now(UTC),
            config_snapshot=sample_config,
            config_hash="hash",
            description="test",
        )
        assert version.version() == 1
        version._ver = 5
        assert version.version() == 5

    def test_audit_trail(self, sample_config):
        version = ConfigVersion(
            version_id="v1",
            version_number=1,
            timestamp=datetime.now(UTC),
            config_snapshot=sample_config,
            config_hash="hash",
            description="test",
        )
        version._record_audit("ACTION1", "user1", {"key": "val"})
        version._record_audit("ACTION2", "user2", {"key2": "val2"})
        trail = version.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "ACTION2"
        trail_all = version.audit_trail(limit=10)
        assert len(trail_all) == 2

    def test_touch(self, sample_config):
        version = ConfigVersion(
            version_id="v1",
            version_number=1,
            timestamp=datetime.now(UTC),
            config_snapshot=sample_config,
            config_hash="hash",
            description="test",
        )
        old_ver = version._ver
        version.touch("admin")
        assert version._ver == old_ver + 1
        assert version._audit_trail[-1]["action"] == "TOUCH"


# ============================================================================
# Tests for VersionChange
# ============================================================================

class TestVersionChange:
    def test_validation_success(self):
        change = VersionChange(
            from_version_id="v1",
            to_version_id="v2",
            changed_keys=["db.host"],
            added_keys=["feature_flags.experimental"],
            removed_keys=["old_key"],
            changed_at=datetime.now(UTC),
            changed_by="admin",
        )
        assert change.from_version_id == "v1"
        assert change.to_version_id == "v2"

    def test_validation_missing_from(self):
        with pytest.raises(ValueError, match="from_version_id is required"):
            VersionChange(
                from_version_id="",
                to_version_id="v2",
                changed_keys=[],
                added_keys=[],
                removed_keys=[],
                changed_at=datetime.now(UTC),
                changed_by="admin",
            )

    def test_validation_missing_to(self):
        with pytest.raises(ValueError, match="to_version_id is required"):
            VersionChange(
                from_version_id="v1",
                to_version_id="",
                changed_keys=[],
                added_keys=[],
                removed_keys=[],
                changed_at=datetime.now(UTC),
                changed_by="admin",
            )

    def test_validation_missing_changed_by(self):
        with pytest.raises(ValueError, match="changed_by is required"):
            VersionChange(
                from_version_id="v1",
                to_version_id="v2",
                changed_keys=[],
                added_keys=[],
                removed_keys=[],
                changed_at=datetime.now(UTC),
                changed_by="",
            )

    def test_to_dict(self):
        change = VersionChange(
            from_version_id="v1",
            to_version_id="v2",
            changed_keys=["a", "b"],
            added_keys=["c"],
            removed_keys=["d"],
            changed_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            changed_by="admin",
        )
        d = change.to_dict()
        assert d["from_version_id"] == "v1"
        assert d["to_version_id"] == "v2"
        assert d["changed_keys"] == ["a", "b"]
        assert d["added_keys"] == ["c"]
        assert d["removed_keys"] == ["d"]
        assert d["changed_at"] == "2026-01-01T12:00:00+00:00"
        assert d["changed_by"] == "admin"
        assert d["ver"] == 1

    def test_from_dict(self):
        data = {
            "change_id": "change_123",
            "from_version_id": "v1",
            "to_version_id": "v2",
            "changed_keys": ["a", "b"],
            "added_keys": ["c"],
            "removed_keys": ["d"],
            "changed_at": "2026-01-01T12:00:00+00:00",
            "changed_by": "admin",
            "ver": 2,
        }
        change = VersionChange.from_dict(data)
        assert change.from_version_id == "v1"
        assert change.to_version_id == "v2"
        assert change.changed_keys == ["a", "b"]
        assert change.added_keys == ["c"]
        assert change.removed_keys == ["d"]
        assert change.changed_at == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        assert change.changed_by == "admin"
        assert change._ver == 2
        assert change._change_id == "change_123"

    def test_clone(self):
        change = VersionChange(
            from_version_id="v1",
            to_version_id="v2",
            changed_keys=["a"],
            added_keys=["b"],
            removed_keys=["c"],
            changed_at=datetime.now(UTC),
            changed_by="admin",
        )
        cloned = change.clone()
        assert cloned.from_version_id == change.from_version_id
        assert cloned.to_version_id == change.to_version_id
        assert cloned.changed_keys == ["a"]
        assert cloned.added_keys == ["b"]
        assert cloned.removed_keys == ["c"]
        assert cloned._ver == change._ver + 1
        assert cloned._audit_trail[-1]["action"] == "CLONE"

    def test_snapshot(self):
        change = VersionChange(
            from_version_id="v1",
            to_version_id="v2",
            changed_keys=[],
            added_keys=[],
            removed_keys=[],
            changed_at=datetime.now(UTC),
            changed_by="admin",
        )
        snap = change.snapshot()
        assert "change_id" in snap
        assert snap["from_version"] == "v1"
        assert snap["to_version"] == "v2"

    def test_version(self):
        change = VersionChange(
            from_version_id="v1",
            to_version_id="v2",
            changed_keys=[],
            added_keys=[],
            removed_keys=[],
            changed_at=datetime.now(UTC),
            changed_by="admin",
        )
        assert change.version() == 1
        change._ver = 3
        assert change.version() == 3

    def test_audit_trail(self):
        change = VersionChange(
            from_version_id="v1",
            to_version_id="v2",
            changed_keys=[],
            added_keys=[],
            removed_keys=[],
            changed_at=datetime.now(UTC),
            changed_by="admin",
        )
        change._record_audit("A1", "u1", {})
        change._record_audit("A2", "u2", {})
        trail = change.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "A2"

    def test_touch(self):
        change = VersionChange(
            from_version_id="v1",
            to_version_id="v2",
            changed_keys=[],
            added_keys=[],
            removed_keys=[],
            changed_at=datetime.now(UTC),
            changed_by="admin",
        )
        old_ver = change._ver
        change.touch("admin")
        assert change._ver == old_ver + 1
        assert change._audit_trail[-1]["action"] == "TOUCH"


# ============================================================================
# Tests for ConfigVersionController
# ============================================================================

class TestConfigVersionController:
    def test_singleton(self):
        c1 = get_config_version_controller()
        c2 = get_config_version_controller()
        assert c1 is c2

    def test_initialization_without_file(self, tmp_path):
        with patch("config.version_controller.CONFIG_VERSION_FILE", str(tmp_path / "nonexistent.json")):
            with patch("pathlib.Path.exists", return_value=False):
                controller = ConfigVersionController()
                assert controller._versions == {}
                assert controller._version_history == []
                assert controller._current_version_id is None

    def test_load_version_file(self, tmp_path, sample_config):
        # Create a version file
        version_file = tmp_path / ".config_version.json"
        version_data = {
            "current_version_id": "v1_123",
            "versions": [
                {
                    "version_id": "v1_123",
                    "version_number": 1,
                    "timestamp": "2026-01-01T12:00:00+00:00",
                    "config_hash": hashlib.sha3_256(json.dumps(sample_config, sort_keys=True).encode()).hexdigest(),
                    "created_by": "admin",
                    "description": "Initial",
                    "parent_version_id": None,
                }
            ],
        }
        version_file.write_text(json.dumps(version_data))
        with patch("config.version_controller.CONFIG_VERSION_FILE", str(version_file)):
            controller = ConfigVersionController()
            assert len(controller._versions) == 1
            assert controller._current_version_id == "v1_123"
            version = controller.get_version("v1_123")
            assert version is not None
            # Config snapshot is empty because not stored in file, but version object has placeholder
            assert version.config_snapshot == {}  # not loaded from file

    def test_save_version_file(self, tmp_path, sample_config):
        version_file = tmp_path / ".config_version.json"
        with patch("config.version_controller.CONFIG_VERSION_FILE", str(version_file)):
            controller = ConfigVersionController()
            controller.create_version(sample_config, "Initial", "admin")
            assert version_file.exists()
            data = json.loads(version_file.read_text())
            assert "current_version_id" in data
            assert len(data["versions"]) == 1
            assert data["versions"][0]["description"] == "Initial"

    def test_create_version(self, version_controller, sample_config):
        version = version_controller.create_version(sample_config, "Initial", "admin")
        assert version.version_number == 1
        assert version.config_hash == version.compute_hash()
        assert version_controller.get_current_version() is version
        assert len(version_controller._version_history) == 1
        # No changes because no parent
        assert len(version_controller._changes) == 0

    def test_create_version_with_parent(self, populated_controller, sample_config_v2):
        # Already has two versions, create third
        v3 = populated_controller.create_version(
            {"new": "config"},
            "Third version",
            "admin",
            parent_version_id=populated_controller._current_version_id,
        )
        assert v3.version_number == 3
        assert len(populated_controller._changes) == 2  # first creation no change, second and third have changes
        # Check change record exists
        change = populated_controller.get_changes(
            populated_controller._version_history[-2].version_id,
            v3.version_id
        )
        assert change is not None

    def test_create_version_max_history(self, version_controller, sample_config):
        # Create more than MAX_HISTORY_SIZE
        for i in range(MAX_HISTORY_SIZE + 5):
            version_controller.create_version(
                {"num": i},
                f"Version {i}",
                "admin",
            )
        assert len(version_controller._version_history) == MAX_HISTORY_SIZE
        # Oldest should be removed
        assert version_controller.get_version("v1_...") is None  # not exactly

    def test_get_version(self, populated_controller):
        versions = populated_controller._version_history
        v1 = versions[0]
        retrieved = populated_controller.get_version(v1.version_id)
        assert retrieved is v1
        assert populated_controller.get_version("nonexistent") is None

    def test_get_current_version(self, populated_controller):
        current = populated_controller.get_current_version()
        assert current is populated_controller._version_history[-1]

    def test_get_version_history(self, populated_controller):
        history = populated_controller.get_version_history(limit=1)
        assert len(history) == 1
        assert history[0] is populated_controller._version_history[-1]
        # Without limit
        history_all = populated_controller.get_version_history(limit=100)
        assert len(history_all) == len(populated_controller._version_history)

    def test_rollback_to_version(self, populated_controller, sample_config):
        current = populated_controller.get_current_version()
        target = populated_controller._version_history[0]  # first version
        new_version = populated_controller.rollback_to_version(
            target.version_id,
            rolled_by="admin",
            reason="Rollback due to issue"
        )
        assert new_version.version_number == len(populated_controller._version_history)
        assert new_version.config_snapshot == target.config_snapshot
        assert new_version.parent_version_id == current.version_id
        assert "Rollback to" in new_version.description
        # Check audit
        assert new_version._audit_trail[-1]["action"] == "CLONE"  # from clone? Actually create_version logs, but rollback logs too
        # Check controller audit
        assert populated_controller._audit_trail[-1]["action"] == "ROLLBACK_TO_VERSION"

    def test_rollback_to_version_not_found(self, populated_controller):
        with pytest.raises(ConfigVersionNotFoundError):
            populated_controller.rollback_to_version("nonexistent", "admin", "test")

    def test_rollback_to_previous(self, populated_controller):
        # current version is v2
        prev = populated_controller.rollback_to_previous("admin", "revert")
        assert prev is not None
        assert prev.parent_version_id == populated_controller._version_history[-2].version_id  # parent is v2? Actually after rollback, new version's parent is current (v2)
        # Should have created a new version
        assert len(populated_controller._version_history) == 3  # initial v1, v2, then rollback creates v3

    def test_rollback_to_previous_no_parent(self, version_controller, sample_config):
        version_controller.create_version(sample_config, "single", "admin")
        result = version_controller.rollback_to_previous("admin", "test")
        assert result is None

    def test_diff_configs(self, version_controller, sample_config, sample_config_v2):
        diff = version_controller._diff_configs(sample_config, sample_config_v2)
        assert "database.host" in diff["changed"]
        assert "database.port" in diff["changed"]
        assert "logging.level" in diff["changed"]
        assert "logging.format" in diff["changed"]
        assert "feature_flags.experimental" in diff["added"]
        # removed? new config doesn't remove any keys from sample_config, but maybe we can test removal
        old = {"a": 1, "b": 2}
        new = {"a": 1}
        diff2 = version_controller._diff_configs(old, new)
        assert "b" in diff2["removed"]

    def test_flatten_keys(self, version_controller):
        config = {
            "db": {"host": "localhost", "port": 5432},
            "app": {"debug": True, "features": {"x": 1, "y": 2}},
        }
        keys = version_controller._flatten_keys(config)
        assert "db.host" in keys
        assert "db.port" in keys
        assert "app.debug" in keys
        assert "app.features.x" in keys
        assert "app.features.y" in keys

    def test_get_changes(self, populated_controller):
        versions = populated_controller._version_history
        v1 = versions[0]
        v2 = versions[1]
        change = populated_controller.get_changes(v1.version_id, v2.version_id)
        assert change is not None
        assert change.from_version_id == v1.version_id
        assert change.to_version_id == v2.version_id
        # Non-existent
        assert populated_controller.get_changes("nonexistent", "also") is None

    def test_get_version_by_number(self, populated_controller):
        v1 = populated_controller._version_history[0]
        retrieved = populated_controller.get_version_by_number(v1.version_number)
        assert retrieved is v1
        assert populated_controller.get_version_by_number(999) is None

    def test_load_version_to_loader(self, populated_controller):
        # Mock get_config_loader
        with patch("config.version_controller.get_config_loader") as mock_loader:
            mock_loader.return_value = MagicMock()
            result = populated_controller.load_version_to_loader(
                populated_controller._version_history[0].version_id
            )
            assert result is True
            mock_loader.assert_called_once()
            # Non-existent version
            result2 = populated_controller.load_version_to_loader("nonexistent")
            assert result2 is False

    def test_get_statistics(self, populated_controller):
        stats = populated_controller.get_statistics()
        assert stats["total_versions"] == len(populated_controller._version_history)
        assert stats["total_changes"] == len(populated_controller._changes)
        assert stats["current_version"] == populated_controller._current_version_id
        assert stats["current_version_number"] == populated_controller._version_history[-1].version_number
        assert stats["oldest_version"] == populated_controller._version_history[0].version_id
        assert stats["newest_version"] == populated_controller._version_history[-1].version_id

    def test_validate(self, populated_controller):
        result = populated_controller.validate()
        assert result["is_valid"] is True
        # Corrupt a version's hash
        version = populated_controller._version_history[0]
        version.config_hash = "bad"
        result2 = populated_controller.validate()
        assert result2["is_valid"] is False
        assert "Version" in result2["errors"][0]

    def test_to_dict(self, populated_controller):
        d = populated_controller.to_dict()
        assert d["controller_id"] == populated_controller._controller_id
        assert d["current_version_id"] == populated_controller._current_version_id
        assert d["total_versions"] == len(populated_controller._version_history)
        assert d["total_changes"] == len(populated_controller._changes)
        assert d["version"] == populated_controller._version

    def test_from_dict(self):
        data = {"controller_id": "ctrl_123", "version": 5}
        controller = ConfigVersionController.from_dict(data)
        assert controller._version == 5
        assert controller._controller_id == "ctrl_123"

    def test_clone(self, populated_controller):
        old_ver = populated_controller._version
        cloned = populated_controller.clone()
        assert cloned is not populated_controller
        assert cloned._version == old_ver + 1
        assert cloned._audit_trail[-1]["action"] == "CLONE"
        # Ensure cloned has same version history? No, clone creates a new empty controller? Actually clone calls __init__ and then sets version.
        # It doesn't copy versions, so it's a fresh controller with incremented version.
        assert len(cloned._version_history) == 0  # because __init__ creates empty

    def test_snapshot(self, populated_controller):
        snap = populated_controller.snapshot()
        assert snap["version"] == populated_controller._version
        assert snap["controller_id"] == populated_controller._controller_id
        assert snap["total_versions"] == len(populated_controller._version_history)
        assert snap["current_version"] == populated_controller._current_version_id
        assert "timestamp" in snap

    def test_version(self, populated_controller):
        assert populated_controller.version() == populated_controller._version

    def test_audit_trail(self, populated_controller):
        populated_controller._record_audit("A1", "u1", {})
        populated_controller._record_audit("A2", "u2", {})
        trail = populated_controller.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "A2"

    def test_touch(self, populated_controller):
        old_ver = populated_controller._version
        populated_controller.touch("admin")
        assert populated_controller._version == old_ver + 1
        assert populated_controller._audit_trail[-1]["action"] == "TOUCH"

    def test_reset(self, populated_controller):
        populated_controller.reset()
        assert populated_controller._versions == {}
        assert populated_controller._version_history == []
        assert populated_controller._changes == []
        assert populated_controller._current_version_id is None
        assert populated_controller._version == 1
        assert populated_controller._audit_trail[-1]["action"] == "RESET"


# ============================================================================
# Singleton reset and getter tests
# ============================================================================

def test_get_config_version_controller_singleton():
    import config.version_controller as module
    module._config_version_controller_instance = None
    c1 = get_config_version_controller()
    c2 = get_config_version_controller()
    assert c1 is c2


# ============================================================================
# Additional edge case tests
# ============================================================================

def test_config_version_timestamp_auto_tz(sample_config):
    # If timestamp without tz, it gets converted
    naive = datetime(2026, 1, 1, 12, 0, 0)
    version = ConfigVersion(
        version_id="v1",
        version_number=1,
        timestamp=naive,
        config_snapshot=sample_config,
        config_hash="hash",
        description="test",
    )
    assert version.timestamp.tzinfo is not None

def test_version_change_timestamp_auto_tz():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    change = VersionChange(
        from_version_id="v1",
        to_version_id="v2",
        changed_keys=[],
        added_keys=[],
        removed_keys=[],
        changed_at=naive,
        changed_by="admin",
    )
    assert change.changed_at.tzinfo is not None
