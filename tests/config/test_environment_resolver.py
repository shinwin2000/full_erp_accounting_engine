# tests/config/test_environment_resolver.py
"""
Comprehensive tests for config/environment_resolver.py.

Covers:
- Singleton behavior of EnvironmentResolver
- resolve(): strings, dicts, lists, nested structures
- _resolve_string: env var substitution, defaults, missing raises ConfigEnvResolveError
- _resolve_nested_refs: config context references
- _resolve_secret_refs: secret references (fallback)
- _get_nested_value: path traversal in dict
- _is_sensitive_var: sensitive var detection
- resolve_file: YAML loading and resolution
- resolve_env_file: .env file parsing and environment setting
- get_env, set_env, get_all_env (with masking)
- set_mask_sensitive, clear_cache
- Entity methods: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch, reset
- Module-level functions: resolve_env, load_env_file, get_env_var, get_environment_resolver
- Exception: ConfigEnvResolveError when env var missing
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.environment_resolver import (
    EnvironmentResolver,
    get_env_var,
    get_environment_resolver,
    load_env_file,
    resolve_env,
)
from config.exceptions import ConfigEnvResolveError, ConfigError


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def resolver():
    """Fresh EnvironmentResolver instance with clean state."""
    # Reset singleton for isolation
    EnvironmentResolver._instance = None
    return EnvironmentResolver()


@pytest.fixture
def temp_env_file():
    """Create a temporary .env file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("TEST_VAR=value_from_env\n")
        f.write("ANOTHER_VAR=another_value\n")
        f.write("# comment line\n")
        f.write("   SPACED_KEY = spaced_value   \n")
        f.write("EMPTY_LINE\n\n")
        f.write("WITH_QUOTES='quoted value'\n")
        f.write("PASSWORD=secret123\n")
        f.write("MULTI=line? no\n")
        temp_path = Path(f.name)
    yield temp_path
    temp_path.unlink(missing_ok=True)


@pytest.fixture
def temp_yaml_file():
    """Create a temporary YAML file with env references."""
    content = """
database:
  host: ${DB_HOST:localhost}
  port: ${DB_PORT:5432}
  user: ${DB_USER}
  password: ${DB_PASS:defaultpass}
nested:
  config: ${config:app.settings.timeout}
secret:
  key: ${secret:api_key}
list:
  - ${ENV_ITEM:default_item}
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(content)
        temp_path = Path(f.name)
    yield temp_path
    temp_path.unlink(missing_ok=True)


# ============================================================================
# Tests for singleton
# ============================================================================

class TestSingleton:
    def test_singleton_instance(self):
        EnvironmentResolver._instance = None
        r1 = EnvironmentResolver()
        r2 = EnvironmentResolver()
        assert r1 is r2

    def test_get_environment_resolver(self):
        EnvironmentResolver._instance = None
        r1 = get_environment_resolver()
        r2 = get_environment_resolver()
        assert r1 is r2


# ============================================================================
# Tests for EnvironmentResolver methods
# ============================================================================

class TestEnvironmentResolver:
    def test_init_defaults(self, resolver):
        assert resolver._mask_sensitive is True
        assert resolver._version == 1
        assert resolver._resolved_cache == {}
        assert resolver._audit_trail == []
        assert resolver._snapshots != []
        assert len(resolver._snapshots) == 1  # taken in __post_init__

    def test_validate(self, resolver):
        result = resolver.validate()
        assert result["is_valid"] is True
        # Invalid case: set _mask_sensitive to non-boolean
        resolver._mask_sensitive = "not_bool"
        with pytest.raises(ValueError, match="must be boolean"):
            resolver._validate()

    # ---- resolve ----
    def test_resolve_string_with_env_var(self, resolver):
        with patch.dict(os.environ, {"MY_VAR": "hello"}):
            result = resolver.resolve("Value: ${MY_VAR}")
            assert result == "Value: hello"

    def test_resolve_string_with_default(self, resolver):
        result = resolver.resolve("Value: ${MISSING_VAR:default_value}")
        assert result == "Value: default_value"

    def test_resolve_string_missing_raises(self, resolver):
        with pytest.raises(ConfigEnvResolveError, match="MISSING_VAR"):
            resolver.resolve("${MISSING_VAR}")

    def test_resolve_dict(self, resolver):
        with patch.dict(os.environ, {"HOST": "localhost"}):
            data = {"host": "${HOST}", "port": "${PORT:8080}"}
            result = resolver.resolve(data)
            assert result == {"host": "localhost", "port": "8080"}

    def test_resolve_list(self, resolver):
        with patch.dict(os.environ, {"ITEM": "value"}):
            data = ["${ITEM}", "static", "${OTHER:default}"]
            result = resolver.resolve(data)
            assert result == ["value", "static", "default"]

    def test_resolve_nested(self, resolver):
        with patch.dict(os.environ, {"A": "1", "B": "2"}):
            data = {"nested": {"a": "${A}", "b": "${B}"}}
            result = resolver.resolve(data)
            assert result["nested"]["a"] == "1"
            assert result["nested"]["b"] == "2"

    def test_resolve_with_config_context(self, resolver):
        context = {"app": {"settings": {"timeout": 30}}}
        value = "Timeout: ${config:app.settings.timeout}"
        result = resolver._resolve_string(value, context)
        assert result == "Timeout: 30"

        # Missing path raises
        with pytest.raises(ConfigError, match="not found"):
            resolver._resolve_string("${config:missing.path}", context)

    def test_resolve_secret_refs(self, resolver):
        with patch.dict(os.environ, {"API_KEY": "abcd1234"}):
            value = "Key: ${secret:api_key}"
            result = resolver._resolve_secret_refs(value)
            assert result == "Key: abcd1234"

        # Missing secret returns placeholder
        value2 = "Key: ${secret:missing_key}"
        result2 = resolver._resolve_secret_refs(value2)
        assert result2 == "Key: {SECRET:missing_key}"

    # ---- resolve_file ----
    def test_resolve_file_success(self, resolver, temp_yaml_file):
        with patch.dict(os.environ, {"DB_HOST": "prod-db", "DB_USER": "admin"}):
            config = resolver.resolve_file(temp_yaml_file)
            assert config["database"]["host"] == "prod-db"
            assert config["database"]["port"] == "5432"  # default
            assert config["database"]["user"] == "admin"
            assert config["database"]["password"] == "defaultpass"
            # nested config: expects context but no config_context passed, so ${config:...} will raise
            # In resolve_file, resolve is called without config_context, so nested refs won't be resolved.
            # That's okay; we test that nested refs are left as is or raise.
            # Actually resolve_file calls self.resolve(raw_config) without context, so nested refs won't be processed.
            # We can test that it doesn't raise and leaves the string.
            # However, our test YAML has ${config:...} which would cause error if resolved, but resolve_file doesn't pass context,
            # so _resolve_nested_refs won't be called because config_context is None in _resolve_string.
            # So it will remain as "${config:app.settings.timeout}"? Actually _resolve_string only calls _resolve_nested_refs if config_context is provided.
            # In resolve_file, resolve is called with config_context=None, so nested refs are not processed.
            # So the value remains "${config:app.settings.timeout}".
            # That's expected; we'll check it.
            assert config["nested"]["config"] == "${config:app.settings.timeout}"
            # secret refs are processed regardless
            assert config["secret"]["key"] == "{SECRET:api_key}"  # since no env var
            # list
            assert config["list"] == ["default_item"]

    def test_resolve_file_not_found(self, resolver):
        with pytest.raises(ConfigError, match="File not found"):
            resolver.resolve_file("/non/existent/file.yaml")

    # ---- resolve_env_file ----
    def test_resolve_env_file(self, resolver, temp_env_file):
        env_vars = resolver.resolve_env_file(temp_env_file)
        # Check that env vars are set and returned
        assert env_vars["TEST_VAR"] == "value_from_env"
        assert env_vars["ANOTHER_VAR"] == "another_value"
        assert env_vars["SPACED_KEY"] == "spaced_value"
        assert env_vars["WITH_QUOTES"] == "'quoted value'"
        assert env_vars["PASSWORD"] == "secret123"
        # MULTI=line? no -> we need to check line with '=' but no special handling for multiline; our fixture has MULTI=line? no
        # Actually the line "MULTI=line? no" will be split at first '=', so value = "line? no"
        assert env_vars["MULTI"] == "line? no"
        # Check os.environ was updated
        assert os.environ.get("TEST_VAR") == "value_from_env"
        # Comments and empty lines ignored

    def test_resolve_env_file_not_found(self, resolver):
        result = resolver.resolve_env_file("/non/existent.env")
        assert result == {}

    def test_resolve_env_file_with_resolution_in_value(self, resolver):
        with patch.dict(os.environ, {"BASE": "base_value"}):
            with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
                f.write("COMPOSED=${BASE}/suffix\n")
                temp_path = Path(f.name)
            env_vars = resolver.resolve_env_file(temp_path)
            assert env_vars["COMPOSED"] == "base_value/suffix"
            temp_path.unlink()

    # ---- get_env, set_env, get_all_env ----
    def test_get_env(self, resolver):
        with patch.dict(os.environ, {"KEY": "value"}):
            assert resolver.get_env("KEY") == "value"
            assert resolver.get_env("MISSING", "default") == "default"
            assert resolver.get_env("MISSING") is None

    def test_set_env(self, resolver):
        resolver.set_env("NEW_KEY", "new_value")
        assert os.environ["NEW_KEY"] == "new_value"
        # Check audit trail
        assert any(entry["action"] == "SET_ENV" for entry in resolver._audit_trail)

    def test_get_all_env(self, resolver):
        with patch.dict(os.environ, {"PUBLIC": "visible", "SECRET_KEY": "hidden"}):
            all_env = resolver.get_all_env()
            # sensitive vars should be masked
            assert all_env["PUBLIC"] == "visible"
            assert all_env["SECRET_KEY"] == "***MASKED***"

        # With masking disabled
        resolver.set_mask_sensitive(False)
        with patch.dict(os.environ, {"SECRET_KEY": "hidden"}):
            all_env2 = resolver.get_all_env()
            assert all_env2["SECRET_KEY"] == "hidden"

    # ---- set_mask_sensitive ----
    def test_set_mask_sensitive(self, resolver):
        resolver.set_mask_sensitive(False)
        assert resolver._mask_sensitive is False
        assert any(entry["action"] == "SET_MASK_SENSITIVE" for entry in resolver._audit_trail)

    # ---- clear_cache ----
    def test_clear_cache(self, resolver):
        resolver._resolved_cache["key"] = "value"
        resolver.clear_cache()
        assert resolver._resolved_cache == {}
        assert any(entry["action"] == "CLEAR_CACHE" for entry in resolver._audit_trail)

    # ---- to_dict, from_dict ----
    def test_to_dict(self, resolver):
        d = resolver.to_dict()
        assert "resolver_id" in d
        assert d["mask_sensitive"] == resolver._mask_sensitive
        assert d["version"] == resolver._version
        assert "cache_size" in d

    def test_from_dict(self):
        data = {"mask_sensitive": False, "version": 5, "resolver_id": "test-id"}
        resolver = EnvironmentResolver.from_dict(data)
        assert resolver._mask_sensitive is False
        assert resolver._version == 5
        assert resolver._resolver_id == "test-id"

    # ---- clone ----
    def test_clone(self, resolver):
        clone = resolver.clone()
        assert clone is not resolver
        assert clone._mask_sensitive == resolver._mask_sensitive
        assert clone._version == resolver._version + 1
        assert clone._resolver_id != resolver._resolver_id
        assert any(entry["action"] == "CLONE" for entry in clone._audit_trail)

    # ---- snapshot ----
    def test_snapshot(self, resolver):
        snap = resolver.snapshot()
        assert snap["version"] == resolver._version
        assert snap["resolver_id"] == resolver._resolver_id
        assert snap["mask_sensitive"] == resolver._mask_sensitive
        assert "timestamp" in snap

    # ---- version ----
    def test_version(self, resolver):
        assert resolver.version() == resolver._version

    # ---- audit_trail ----
    def test_audit_trail(self, resolver):
        resolver._record_audit("TEST", "user", {"foo": "bar"})
        trail = resolver.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    # ---- touch ----
    def test_touch(self, resolver):
        old_version = resolver._version
        resolver.touch("tester")
        assert resolver._version == old_version + 1
        assert any(entry["action"] == "TOUCH" for entry in resolver._audit_trail)

    # ---- reset ----
    def test_reset(self, resolver):
        resolver._resolved_cache["key"] = "value"
        resolver._version = 10
        resolver._mask_sensitive = False
        old_id = resolver._resolver_id
        resolver.reset()
        assert resolver._resolved_cache == {}
        assert resolver._version == 1
        assert resolver._mask_sensitive is True
        assert resolver._resolver_id != old_id
        assert resolver._audit_trail == []
        assert any(entry["action"] == "RESET" for entry in resolver._audit_trail)

    # ---- _is_sensitive_var ----
    def test_is_sensitive_var(self, resolver):
        assert resolver._is_sensitive_var("PASSWORD") is True
        assert resolver._is_sensitive_var("MY_SECRET") is True
        assert resolver._is_sensitive_var("API_KEY") is True
        assert resolver._is_sensitive_var("AUTH_TOKEN") is True
        assert resolver._is_sensitive_var("PUBLIC") is False
        assert resolver._is_sensitive_var("USERNAME") is False

    # ---- _get_nested_value ----
    def test_get_nested_value(self, resolver):
        config = {"a": {"b": {"c": 42}}}
        assert resolver._get_nested_value(config, "a.b.c") == 42
        assert resolver._get_nested_value(config, "a.b") == {"c": 42}
        assert resolver._get_nested_value(config, "a.b.d") is None
        assert resolver._get_nested_value(config, "x.y.z") is None
        # Non-dict intermediate
        assert resolver._get_nested_value({"a": 1}, "a.b") is None


# ============================================================================
# Tests for module-level functions
# ============================================================================

class TestModuleFunctions:
    def test_resolve_env(self):
        with patch.dict(os.environ, {"KEY": "value"}):
            result = resolve_env("${KEY}")
            assert result == "value"
            # With context
            context = {"app": {"timeout": 30}}
            result2 = resolve_env("${config:app.timeout}", config_context=context)
            assert result2 == "30"

    def test_load_env_file(self, temp_env_file):
        result = load_env_file(temp_env_file)
        assert "TEST_VAR" in result
        assert result["TEST_VAR"] == "value_from_env"

    def test_get_env_var(self):
        with patch.dict(os.environ, {"KEY": "value"}):
            assert get_env_var("KEY") == "value"
            assert get_env_var("MISSING", "default") == "default"

    def test_get_environment_resolver(self):
        r1 = get_environment_resolver()
        r2 = get_environment_resolver()
        assert r1 is r2