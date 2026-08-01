# test_loader_yaml.py
# Comprehensive tests for policy_engine/loader_yaml.py

import contextlib
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest
import yaml
from pydantic import ValidationError

from policy_engine.loader_yaml import (
    PolicyConfig,
    PolicyFileInfo,
    PolicyLoader,
    PolicyRule,
    PolicySet,
    get_policy_loader,
    load_policies,
)
from policy_engine.policy_exceptions import (
    PolicyNotFoundError,
    PolicyValidationError,
)

# ============================================================================
# FIXED DATETIME (untuk menghindari flaky tests)
# ============================================================================

FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
FIXED_PAST = FIXED_NOW - timedelta(days=10)
FIXED_FUTURE = FIXED_NOW + timedelta(days=10)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def mock_datetime():
    """Mock datetime.now and datetime.utcnow to fixed values for the module under test."""
    with patch("policy_engine.loader_yaml.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.utcnow.return_value = FIXED_NOW
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def sample_policy_rule():
    return PolicyRule(
        id="rule1",
        name="Test Rule",
        description="A test rule",
        condition="amount > 1000",
        action="approve",
        priority=10,
        enabled=True,
    )


@pytest.fixture
def sample_policy_set(sample_policy_rule):
    return PolicySet(
        id="policy1",
        name="Test Policy",
        domain="revenue",
        version=1,
        effective_from=FIXED_PAST,
        effective_to=FIXED_FUTURE,
        jurisdiction="ID",
        rules=[sample_policy_rule],
        metadata={"author": "tester"},
    )


@pytest.fixture
def sample_policy_config(sample_policy_set):
    return PolicyConfig(
        version="1.0",
        policies=[sample_policy_set],
    )


@pytest.fixture
def sample_yaml_content(sample_policy_config):
    # Generate YAML content from sample config

    data = sample_policy_config.dict()
    # Convert datetime to ISO strings for YAML serialization
    for policy in data["policies"]:
        policy["effective_from"] = policy["effective_from"].isoformat()
        if policy["effective_to"]:
            policy["effective_to"] = policy["effective_to"].isoformat()
    return yaml.dump(data)


@pytest.fixture
def temp_yaml_file(tmp_path, sample_yaml_content):
    file_path = tmp_path / "policies.yaml"
    file_path.write_text(sample_yaml_content)
    return file_path


@pytest.fixture
def temp_dir(tmp_path):
    dir_path = tmp_path / "policies"
    dir_path.mkdir()
    return dir_path


@pytest.fixture(autouse=True)
def clear_loader_singleton():
    """Clear the singleton before each test to isolate."""
    PolicyLoader._instance = None
    yield
    PolicyLoader._instance = None


# ============================================================================
# Tests for PolicyRule
# ============================================================================

class TestPolicyRule:
    def test_construction_valid(self, sample_policy_rule):
        assert sample_policy_rule.id == "rule1"
        assert sample_policy_rule.condition == "amount > 1000"
        assert sample_policy_rule.action == "approve"

    def test_condition_not_empty_validator(self):
        with pytest.raises(ValidationError) as exc:
            PolicyRule(id="r1", name="test", condition="", action="do")
        assert "Condition cannot be empty" in str(exc.value)

    def test_action_not_empty_validator(self):
        with pytest.raises(ValidationError) as exc:
            PolicyRule(id="r1", name="test", condition="true", action="")
        assert "Action cannot be empty" in str(exc.value)

    def test_validation_passes_with_none_description(self):
        rule = PolicyRule(id="r1", name="test", condition="true", action="do")
        assert rule.description is None


# ============================================================================
# Tests for PolicySet
# ============================================================================

class TestPolicySet:
    def test_construction_valid(self, sample_policy_set):
        assert sample_policy_set.id == "policy1"
        assert sample_policy_set.domain == "revenue"
        assert len(sample_policy_set.rules) == 1

    def test_parse_effective_from(self, sample_policy_set):
        # effective_from is already a datetime from fixture
        assert sample_policy_set.effective_from == FIXED_PAST
        # Test parsing from string
        data = {
            "id": "p2",
            "name": "test",
            "domain": "tax",
            "version": 1,
            "effective_from": "2026-01-01T00:00:00+00:00",
            "effective_to": None,
            "jurisdiction": "ID",
            "rules": [],
        }
        pset = PolicySet(**data)
        assert pset.effective_from == datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    def test_parse_effective_to(self):
        data = {
            "id": "p2",
            "name": "test",
            "domain": "tax",
            "version": 1,
            "effective_from": "2026-01-01T00:00:00+00:00",
            "effective_to": "2026-12-31T23:59:59+00:00",
            "jurisdiction": "ID",
            "rules": [],
        }
        pset = PolicySet(**data)
        assert pset.effective_to == datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)

    def test_parse_effective_to_none(self):
        data = {
            "id": "p2",
            "name": "test",
            "domain": "tax",
            "version": 1,
            "effective_from": "2026-01-01T00:00:00+00:00",
            "effective_to": None,
            "jurisdiction": "ID",
            "rules": [],
        }
        pset = PolicySet(**data)
        assert pset.effective_to is None

    def test_unique_rule_ids_valid(self, sample_policy_rule):
        # Same ID twice -> should raise
        data = {
            "id": "p2",
            "name": "test",
            "domain": "tax",
            "version": 1,
            "effective_from": "2026-01-01T00:00:00+00:00",
            "effective_to": None,
            "jurisdiction": "ID",
            "rules": [sample_policy_rule, sample_policy_rule],
        }
        with pytest.raises(ValidationError) as exc:
            PolicySet(**data)
        assert "Duplicate rule IDs" in str(exc.value)


# ============================================================================
# Tests for PolicyConfig
# ============================================================================

class TestPolicyConfig:
    def test_construction_valid(self, sample_policy_config):
        assert sample_policy_config.version == "1.0"
        assert len(sample_policy_config.policies) == 1

    def test_unique_policy_ids_valid(self, sample_policy_set):
        # Same ID twice -> should raise
        data = {
            "version": "1.0",
            "policies": [sample_policy_set, sample_policy_set],
        }
        with pytest.raises(ValidationError) as exc:
            PolicyConfig(**data)
        assert "Duplicate policy IDs" in str(exc.value)


# ============================================================================
# Tests for PolicyFileInfo
# ============================================================================

class TestPolicyFileInfo:
    def test_construction(self, tmp_path):
        file_path = tmp_path / "test.yaml"
        file_path.write_text("content")
        info = PolicyFileInfo(
            path=file_path,
            last_modified=file_path.stat().st_mtime,
            content_hash="abc123",
        )
        assert info.path == file_path
        assert info.content_hash == "abc123"
        assert info.loaded_at == FIXED_NOW

    def test_is_changed_no_change(self, tmp_path):
        file_path = tmp_path / "test.yaml"
        file_path.write_text("content")
        info = PolicyFileInfo(
            path=file_path,
            last_modified=file_path.stat().st_mtime,
            content_hash="abc123",
        )
        assert info.is_changed() is False

    def test_is_changed_mtime_change(self, tmp_path):
        file_path = tmp_path / "test.yaml"
        file_path.write_text("content")
        info = PolicyFileInfo(
            path=file_path,
            last_modified=file_path.stat().st_mtime,
            content_hash="abc123",
        )
        # Simulate modification
        with patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value.st_mtime = file_path.stat().st_mtime + 10
            assert info.is_changed() is True

    def test_is_changed_file_deleted(self, tmp_path):
        file_path = tmp_path / "test.yaml"
        file_path.write_text("content")
        info = PolicyFileInfo(
            path=file_path,
            last_modified=file_path.stat().st_mtime,
            content_hash="abc123",
        )
        file_path.unlink()
        assert info.is_changed() is True

    def test_update(self, tmp_path):
        file_path = tmp_path / "test.yaml"
        file_path.write_text("content")
        info = PolicyFileInfo(
            path=file_path,
            last_modified=123.0,
            content_hash="abc123",
        )
        info.update()
        assert info.last_modified == file_path.stat().st_mtime
        assert info.loaded_at == FIXED_NOW


# ============================================================================
# Tests for PolicyLoader - Loading
# ============================================================================

class TestPolicyLoaderLoading:
    def test_singleton(self):
        loader1 = PolicyLoader()
        loader2 = PolicyLoader()
        assert loader1 is loader2

    def test_load_from_file_success(self, temp_yaml_file):
        loader = PolicyLoader()
        config = loader.load_from_file(temp_yaml_file)
        assert isinstance(config, PolicyConfig)
        assert len(config.policies) == 1
        policy = config.policies[0]
        assert policy.id == "policy1"
        assert policy.domain == "revenue"
        assert len(policy.rules) == 1
        # Verify it was registered
        retrieved = loader.get_policy_set("policy1")
        assert retrieved is not None
        assert retrieved.id == "policy1"

    def test_load_from_file_not_found(self):
        loader = PolicyLoader()
        with pytest.raises(PolicyNotFoundError):
            loader.load_from_file("/non/existent/file.yaml")

    def test_load_from_file_yaml_error(self):
        loader = PolicyLoader()
        with patch("builtins.open", mock_open(read_data="invalid: yaml: [broken")):
            # yaml.safe_load will raise YAMLError
            with pytest.raises(PolicyValidationError) as exc:
                loader.load_from_file("file.yaml")
            assert "YAML parse error" in str(exc.value)

    def test_load_from_file_validation_error(self):
        loader = PolicyLoader()
        # Invalid data: missing required fields
        invalid_yaml = "policies: []"  # missing version and created_at? Actually PolicyConfig requires version.
        with patch("builtins.open", mock_open(read_data=invalid_yaml)):
            with pytest.raises(PolicyValidationError) as exc:
                loader.load_from_file("file.yaml")
            # Should catch ValidationError and re-raise as PolicyValidationError
            assert "validation" in str(exc.value).lower() or "ValidationError" in str(exc.value)

    def test_load_from_file_duplicate_policy_id(self, temp_yaml_file, sample_yaml_content):
        # Create YAML with duplicate policy IDs

        data = yaml.safe_load(sample_yaml_content)
        data["policies"].append(data["policies"][0])  # duplicate
        dup_yaml = yaml.dump(data)
        file_path = temp_yaml_file.parent / "dup.yaml"
        file_path.write_text(dup_yaml)
        loader = PolicyLoader()
        with pytest.raises(PolicyValidationError) as exc:
            loader.load_from_file(file_path)
        assert "Duplicate policy IDs" in str(exc.value)

    def test_load_from_directory(self, temp_dir, sample_yaml_content):
        # Create multiple files in directory
        file1 = temp_dir / "policy1.yaml"
        file1.write_text(sample_yaml_content)
        file2 = temp_dir / "policy2.yaml"
        # Create a second policy with different ID

        data = yaml.safe_load(sample_yaml_content)
        data["policies"][0]["id"] = "policy2"
        data["policies"][0]["name"] = "Policy2"
        file2.write_text(yaml.dump(data))

        loader = PolicyLoader()
        configs = loader.load_from_directory(temp_dir, recursive=False)
        assert len(configs) == 2
        # Check registration
        assert loader.get_policy_set("policy1") is not None
        assert loader.get_policy_set("policy2") is not None

    def test_load_from_directory_with_subdir(self, temp_dir, sample_yaml_content):
        subdir = temp_dir / "sub"
        subdir.mkdir()
        file1 = subdir / "policy1.yaml"
        file1.write_text(sample_yaml_content)
        loader = PolicyLoader()
        # recursive=True (default)
        configs = loader.load_from_directory(temp_dir, recursive=True)
        assert len(configs) == 1
        # recursive=False
        configs2 = loader.load_from_directory(temp_dir, recursive=False)
        assert len(configs2) == 0  # no files directly in temp_dir

    def test_load_from_directory_not_found(self):
        loader = PolicyLoader()
        with pytest.raises(PolicyNotFoundError):
            loader.load_from_directory("/non/existent")

    def test_load_from_directory_handles_errors(self, temp_dir):
        # Create a file that will cause an error (invalid YAML)
        bad_file = temp_dir / "bad.yaml"
        bad_file.write_text("invalid: [")
        loader = PolicyLoader()
        configs = loader.load_from_directory(temp_dir)
        # Should log warning but continue
        assert len(configs) == 0  # no valid files


# ============================================================================
# Tests for PolicyLoader - Query Methods
# ============================================================================

class TestPolicyLoaderQuery:
    def test_get_policy_set_found(self, temp_yaml_file):
        loader = PolicyLoader()
        loader.load_from_file(temp_yaml_file)
        policy = loader.get_policy_set("policy1")
        assert policy is not None
        assert policy.name == "Test Policy"

    def test_get_policy_set_not_found(self):
        loader = PolicyLoader()
        assert loader.get_policy_set("nonexistent") is None

    def test_get_policies_by_domain(self, temp_yaml_file):
        loader = PolicyLoader()
        loader.load_from_file(temp_yaml_file)
        # Load another policy in different domain

        data = yaml.safe_load(temp_yaml_file.read_text())
        data["policies"][0]["id"] = "policy2"
        data["policies"][0]["domain"] = "tax"
        file2 = temp_yaml_file.parent / "policy2.yaml"
        file2.write_text(yaml.dump(data))
        loader.load_from_file(file2)

        revenue_policies = loader.get_policies_by_domain("revenue")
        assert len(revenue_policies) == 1
        assert revenue_policies[0].id == "policy1"

        tax_policies = loader.get_policies_by_domain("tax")
        assert len(tax_policies) == 1
        assert tax_policies[0].id == "policy2"

    def test_get_policies_by_domain_with_jurisdiction(self, temp_yaml_file):
        loader = PolicyLoader()
        loader.load_from_file(temp_yaml_file)
        # Add another policy with different jurisdiction

        data = yaml.safe_load(temp_yaml_file.read_text())
        data["policies"][0]["id"] = "policy2"
        data["policies"][0]["jurisdiction"] = "SG"
        file2 = temp_yaml_file.parent / "policy2.yaml"
        file2.write_text(yaml.dump(data))
        loader.load_from_file(file2)

        policies_id = loader.get_policies_by_domain("revenue", jurisdiction="ID")
        assert len(policies_id) == 1
        assert policies_id[0].id == "policy1"

        policies_sg = loader.get_policies_by_domain("revenue", jurisdiction="SG")
        assert len(policies_sg) == 1
        assert policies_sg[0].id == "policy2"

    def test_get_policies_by_domain_filters_by_date(self, temp_yaml_file):
        loader = PolicyLoader()
        loader.load_from_file(temp_yaml_file)
        # Add a policy that is not yet effective

        data = yaml.safe_load(temp_yaml_file.read_text())
        data["policies"][0]["id"] = "policy_future"
        data["policies"][0]["effective_from"] = FIXED_FUTURE.isoformat()
        file2 = temp_yaml_file.parent / "policy_future.yaml"
        file2.write_text(yaml.dump(data))
        loader.load_from_file(file2)

        # Now query as of FIXED_NOW (which is before future effective)
        policies = loader.get_policies_by_domain("revenue", as_of=FIXED_NOW)
        # Should only return the original one (policy1)
        assert len(policies) == 1
        assert policies[0].id == "policy1"

        # Query as of future date
        policies_future = loader.get_policies_by_domain("revenue", as_of=FIXED_FUTURE + timedelta(days=1))
        assert len(policies_future) == 2
        # Both should be returned

    def test_get_active_policy(self, temp_yaml_file):
        loader = PolicyLoader()
        loader.load_from_file(temp_yaml_file)
        # Add another policy with higher version

        data = yaml.safe_load(temp_yaml_file.read_text())
        data["policies"][0]["id"] = "policy_v2"
        data["policies"][0]["version"] = 2
        data["policies"][0]["effective_from"] = FIXED_PAST.isoformat()
        file2 = temp_yaml_file.parent / "policy_v2.yaml"
        file2.write_text(yaml.dump(data))
        loader.load_from_file(file2)

        active = loader.get_active_policy("revenue", prefer_highest_version=True)
        assert active is not None
        assert active.id == "policy_v2"  # version 2

        active2 = loader.get_active_policy("revenue", prefer_highest_version=False)
        # Should pick latest effective_from (both have same, but prefer_highest_version=False uses effective_from)
        # Since both have same effective_from, the first in list is kept? Actually sorting by effective_from desc will keep the one with later effective_from; they are same, so it depends on insertion order. To avoid flakiness, we test that the method returns one.
        assert active2 is not None

    def test_get_active_policy_no_policy(self):
        loader = PolicyLoader()
        active = loader.get_active_policy("revenue")
        assert active is None

    def test_get_all_domains(self, temp_yaml_file):
        loader = PolicyLoader()
        loader.load_from_file(temp_yaml_file)
        # Load another domain

        data = yaml.safe_load(temp_yaml_file.read_text())
        data["policies"][0]["id"] = "policy2"
        data["policies"][0]["domain"] = "tax"
        file2 = temp_yaml_file.parent / "policy2.yaml"
        file2.write_text(yaml.dump(data))
        loader.load_from_file(file2)

        domains = loader.get_all_domains()
        assert set(domains) == {"revenue", "tax"}

    def test_get_all_jurisdictions(self, temp_yaml_file):
        loader = PolicyLoader()
        loader.load_from_file(temp_yaml_file)
        # Load another jurisdiction

        data = yaml.safe_load(temp_yaml_file.read_text())
        data["policies"][0]["id"] = "policy2"
        data["policies"][0]["jurisdiction"] = "SG"
        file2 = temp_yaml_file.parent / "policy2.yaml"
        file2.write_text(yaml.dump(data))
        loader.load_from_file(file2)

        jurisdictions = loader.get_all_jurisdictions()
        assert set(jurisdictions) == {"ID", "SG"}


# ============================================================================
# Tests for PolicyLoader - Reload and Cache
# ============================================================================

class TestPolicyLoaderReload:
    def test_register_policy_set(self, sample_policy_set):
        loader = PolicyLoader()
        loader.register_policy_set(sample_policy_set)
        assert loader.get_policy_set(sample_policy_set.id) == sample_policy_set

    def test_clear_cache(self, temp_yaml_file):
        loader = PolicyLoader()
        loader.load_from_file(temp_yaml_file)
        assert len(loader._policies) > 0
        loader.clear_cache()
        assert len(loader._policies) == 0
        assert len(loader._file_infos) == 0

    def test_reload_on_change_flag(self, temp_yaml_file):
        loader = PolicyLoader()
        # Load with reload_on_change=True
        loader.load_from_file(temp_yaml_file, reload_on_change=True)
        # Should have started monitor thread? Actually _start_reload_monitor is called in load_from_file only if reload_on_change.
        # But it also requires that the file is in a directory that is being monitored? The code adds parent to _loaded_directories.
        # However, _start_reload_monitor is not called in load_from_file; it's only called in load_from_directory with reload_on_change.
        # Let's verify: In load_from_file, if reload_on_change, it adds path.parent to _loaded_directories, but does NOT call _start_reload_monitor.
        # So we need to test separately.
        assert temp_yaml_file.parent in loader._loaded_directories

    def test_reload_monitor_start_stop(self):
        loader = PolicyLoader()
        # Start monitor
        loader._start_reload_monitor()
        assert loader._running is True
        assert loader._reload_thread is not None
        assert loader._reload_thread.is_alive() is True
        # Stop
        loader.stop_reload_monitor()
        assert loader._running is False
        # Wait for thread to finish
        if loader._reload_thread:
            loader._reload_thread.join(timeout=1)
            assert not loader._reload_thread.is_alive()

    def test_reload_monitor_loop_checks_changes(self, temp_yaml_file, sample_yaml_content):
        loader = PolicyLoader()
        # Load file and register
        loader.load_from_file(temp_yaml_file)
        # Manually set file info
        info = PolicyFileInfo(
            path=temp_yaml_file,
            last_modified=temp_yaml_file.stat().st_mtime,
            content_hash=hashlib.sha256(sample_yaml_content.encode()).hexdigest(),
        )
        loader._file_infos[temp_yaml_file] = info

        # Simulate file change by updating mtime
        with patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value.st_mtime = info.last_modified + 10
            # Also need to mock the reload logic to avoid actual file reads?
            # We'll mock _check_and_reload_changed_files to verify it calls remove and reload.
            with patch.object(loader, "_remove_policies_from_file") as mock_remove:
                with patch.object(loader, "load_from_file") as mock_load:
                    loader._check_and_reload_changed_files()
                    # _remove_policies_from_file should be called
                    mock_remove.assert_called_once_with(temp_yaml_file)
                    mock_load.assert_called_once_with(temp_yaml_file, reload_on_change=True)

    def test_reload_monitor_loop_no_changes(self, temp_yaml_file):
        loader = PolicyLoader()
        info = PolicyFileInfo(
            path=temp_yaml_file,
            last_modified=temp_yaml_file.stat().st_mtime,
            content_hash="abc",
        )
        loader._file_infos[temp_yaml_file] = info
        with patch.object(loader, "_remove_policies_from_file") as mock_remove:
            with patch.object(loader, "load_from_file") as mock_load:
                loader._check_and_reload_changed_files()
                mock_remove.assert_not_called()
                mock_load.assert_not_called()

    def test_remove_policies_from_file_rebuild(self, temp_yaml_file, sample_yaml_content):
        loader = PolicyLoader()
        # Load two files: one that we will remove, and another that stays.
        file1 = temp_yaml_file
        loader.load_from_file(file1)  # policy1
        # Create second file

        data = yaml.safe_load(sample_yaml_content)
        data["policies"][0]["id"] = "policy2"
        file2 = file1.parent / "policy2.yaml"
        file2.write_text(yaml.dump(data))
        loader.load_from_file(file2)  # policy2

        # Now remove policy1 file
        file1.unlink()
        # But the file info still exists; call _remove_policies_from_file with file1
        # This will rebuild index from remaining files.
        loader._remove_policies_from_file(file1)
        # Only policy2 should remain
        assert loader.get_policy_set("policy1") is None
        assert loader.get_policy_set("policy2") is not None

    def test_rebuild_index_from_remaining_files(self, temp_yaml_file, sample_yaml_content):
        loader = PolicyLoader()
        # Load two files
        file1 = temp_yaml_file
        loader.load_from_file(file1)

        data = yaml.safe_load(sample_yaml_content)
        data["policies"][0]["id"] = "policy2"
        file2 = file1.parent / "policy2.yaml"
        file2.write_text(yaml.dump(data))
        loader.load_from_file(file2)

        # Rebuild excluding file1
        loader._rebuild_index_from_remaining_files(file1)
        # Only policy2 should remain
        assert loader.get_policy_set("policy1") is None
        assert loader.get_policy_set("policy2") is not None

    def test_reload_default(self, tmp_path):
        # Mock default path to exist
        default_path = Path(__file__).parent.parent / "config_files" / "application.yaml"
        with patch("pathlib.Path.exists") as mock_exists:
            with patch("policy_engine.loader_yaml.PolicyLoader.load_from_file") as mock_load:
                mock_exists.return_value = True
                loader = PolicyLoader()
                loader.reload_default()
                mock_load.assert_called_once_with(default_path)

    def test_reload_default_not_found(self, tmp_path, caplog):
        Path(__file__).parent.parent / "config_files" / "application.yaml"
        with patch("pathlib.Path.exists") as mock_exists:
            mock_exists.return_value = False
            loader = PolicyLoader()
            with caplog.at_level("WARNING"):
                loader.reload_default()
            assert "Default policy file not found" in caplog.text


# ============================================================================
# Tests for Statistics and Requirements
# ============================================================================

class TestPolicyLoaderStats:
    def test_get_statistics(self, temp_yaml_file):
        loader = PolicyLoader()
        loader.load_from_file(temp_yaml_file)
        stats = loader.get_statistics()
        assert stats["total_policies"] == 1
        assert stats["total_domains"] == 1
        assert stats["total_jurisdictions"] == 1
        assert stats["loaded_files"] == 1
        assert stats["directories_monitored"] == 0
        assert stats["reload_monitor_running"] is False

    def test_get_requirements_summary(self, temp_yaml_file):
        loader = PolicyLoader()
        loader.load_from_file(temp_yaml_file)
        summary = loader.get_requirements_summary()
        assert summary["total_policies"] == 1
        assert summary["domains"] == ["revenue"]
        assert summary["jurisdictions"] == ["ID"]
        assert summary["supported_formats"] == ["YAML"]
        assert summary["schema_version"] == "1.0"


# ============================================================================
# Tests for Module-level Functions
# ============================================================================

class TestModuleFunctions:
    def test_get_policy_loader_singleton(self):
        loader1 = get_policy_loader()
        loader2 = get_policy_loader()
        assert loader1 is loader2

    def test_load_policies_with_path_file(self, temp_yaml_file):
        result = load_policies(temp_yaml_file)
        assert isinstance(result, PolicyConfig)
        # Also verify that the loader has the policy
        loader = get_policy_loader()
        assert loader.get_policy_set("policy1") is not None

    def test_load_policies_with_path_directory(self, temp_dir, sample_yaml_content):
        file1 = temp_dir / "policy1.yaml"
        file1.write_text(sample_yaml_content)
        result = load_policies(temp_dir)
        # load_policies with directory returns list of configs
        assert isinstance(result, list)
        assert len(result) == 1

    def test_load_policies_with_none_path(self):
        # Should call reload_default
        loader = get_policy_loader()
        with patch.object(loader, "reload_default") as mock_reload:
            load_policies(None)
            mock_reload.assert_called_once()

    def test_load_policies_with_kwargs(self, temp_yaml_file):
        # Test passing kwargs (recursive, reload_on_change)
        with patch.object(PolicyLoader, "load_from_file") as mock_load_file:
            load_policies(temp_yaml_file, reload_on_change=True)
            mock_load_file.assert_called_once_with(temp_yaml_file, reload_on_change=True)


# ============================================================================
# Tests for PolicyLoader.load (simplified test compatibility method)
# ============================================================================

class TestPolicyLoaderLoadCompat:
    def test_load_method(self, temp_yaml_file, sample_yaml_content):
        loader = PolicyLoader()
        result = loader.load(temp_yaml_file)
        assert hasattr(result, "policy_id")
        assert result.policy_id == "policy1"
        assert hasattr(result, "rules")
        assert len(result.rules) == 1

    def test_load_method_file_not_found(self):
        loader = PolicyLoader()
        with pytest.raises(FileNotFoundError):
            loader.load("/non/existent.yaml")

    def test_load_method_invalid_yaml(self):
        loader = PolicyLoader()
        with patch("builtins.open", mock_open(read_data="invalid: [broken")):
            with pytest.raises(ValueError, match="YAML parse error"):
                loader.load("file.yaml")

    def test_load_method_not_dict(self):
        loader = PolicyLoader()
        with patch("builtins.open", mock_open(read_data="just a string")):
            with pytest.raises(ValueError, match="YAML root must be a dictionary"):
                loader.load("file.yaml")


# ============================================================================
# Additional Edge Cases
# ============================================================================

class TestPolicyLoaderEdgeCases:
    def test_load_from_file_with_empty_yaml(self, tmp_path):
        file_path = tmp_path / "empty.yaml"
        file_path.write_text("")
        loader = PolicyLoader()
        # Empty YAML -> safe_load returns None, which becomes {"policies": []}
        config = loader.load_from_file(file_path)
        assert len(config.policies) == 0

    def test_load_from_file_with_only_policies_key(self, tmp_path):
        file_path = tmp_path / "empty_policies.yaml"
        file_path.write_text("policies: []")
        loader = PolicyLoader()
        config = loader.load_from_file(file_path)
        assert len(config.policies) == 0

    def test_register_policy_set_with_existing(self, sample_policy_set):
        loader = PolicyLoader()
        loader.register_policy_set(sample_policy_set)
        # Registering with same ID should overwrite? It will just add to dict, but we don't have duplicate check.
        # It will replace the existing.
        another = sample_policy_set.copy(update={"name": "Overwritten"})
        loader.register_policy_set(another)
        retrieved = loader.get_policy_set(sample_policy_set.id)
        assert retrieved.name == "Overwritten"

    def test_get_policies_by_domain_with_no_domain(self):
        loader = PolicyLoader()
        result = loader.get_policies_by_domain("nonexistent")
        assert result == []

    def test_get_active_policy_with_multiple_versions(self, temp_yaml_file):
        loader = PolicyLoader()
        loader.load_from_file(temp_yaml_file)

        data = yaml.safe_load(temp_yaml_file.read_text())
        # Add higher version but later effective date
        data["policies"][0]["id"] = "policy_v3"
        data["policies"][0]["version"] = 3
        data["policies"][0]["effective_from"] = FIXED_FUTURE.isoformat()
        file2 = temp_yaml_file.parent / "policy_v3.yaml"
        file2.write_text(yaml.dump(data))
        loader.load_from_file(file2)

        # As of FIXED_NOW, policy_v3 is not yet effective, so active should be policy1
        active = loader.get_active_policy("revenue", as_of=FIXED_NOW, prefer_highest_version=True)
        assert active.id == "policy1"

        # As of future, policy_v3 should be active
        active2 = loader.get_active_policy("revenue", as_of=FIXED_FUTURE + timedelta(days=1), prefer_highest_version=True)
        assert active2.id == "policy_v3"

    def test_stop_reload_monitor_when_not_running(self):
        loader = PolicyLoader()
        # Should not raise
        loader.stop_reload_monitor()
        # Ensure _running is False
        assert loader._running is False

    def test_reload_monitor_loop_handles_exception(self, caplog):
        loader = PolicyLoader()
        loader._running = True
        # Simulate an exception in _check_and_reload_changed_files
        with patch.object(loader, "_check_and_reload_changed_files", side_effect=Exception("Simulated error")):
            with patch("time.sleep", return_value=None):  # avoid sleeping
                # We need to run the loop once; we can call it directly or start thread and wait.
                # We'll call the loop method directly with a break condition.
                # To avoid infinite loop, we can set _running False after one iteration.
                def run_once():
                    with contextlib.suppress(Exception):
                        loader._reload_monitor_loop()
                # We'll set _running False to stop after first iteration
                loader._running = False
                with caplog.at_level("ERROR"):
                    # We need to simulate the loop; but since _running is False, it will not enter the while loop.
                    # We'll set _running True, run one iteration, then set False.
                    loader._running = True
                    # Patch time.sleep to return immediately
                    with patch("time.sleep", return_value=None):
                        # We'll call _reload_monitor_loop in a separate thread to avoid blocking
                        import threading
                        thread = threading.Thread(target=loader._reload_monitor_loop)
                        thread.start()
                        thread.join(timeout=1)
                        # The loop should have caught the exception and logged it
                        assert "Error in reload monitor" in caplog.text

    def test_clear_cache_clears_all(self, temp_yaml_file):
        loader = PolicyLoader()
        loader.load_from_file(temp_yaml_file)
        loader._loaded_directories.add(temp_yaml_file.parent)
        loader.clear_cache()
        assert len(loader._policies) == 0
        assert len(loader._policies_by_domain) == 0
        assert len(loader._policies_by_jurisdiction) == 0
        assert len(loader._policies_by_domain_jurisdiction) == 0
        assert len(loader._file_infos) == 0
        assert len(loader._loaded_directories) == 0

    def test_load_from_file_with_reload_on_change(self, temp_yaml_file):
        loader = PolicyLoader()
        loader.load_from_file(temp_yaml_file, reload_on_change=True)
        assert temp_yaml_file.parent in loader._loaded_directories

    def test_load_from_directory_with_reload_on_change(self, temp_dir, sample_yaml_content):
        file1 = temp_dir / "policy1.yaml"
        file1.write_text(sample_yaml_content)
        loader = PolicyLoader()
        # reload_on_change=True should start the monitor thread
        with patch.object(loader, "_start_reload_monitor") as mock_start:
            loader.load_from_directory(temp_dir, reload_on_change=True)
            mock_start.assert_called_once()
        assert temp_dir in loader._loaded_directories
