# tests/architecture/test_boundary_checker.py
"""
Comprehensive unit tests for architecture/boundary_checker.py.
Covers all public methods, edge cases, and uses mocking for external dependencies.
All datetime usage is mocked to avoid flakiness.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from architecture.boundary_checker import (
    BoundaryChecker,
    ImportViolation,
    check_all_boundaries,
    get_architecture_report,
)

# ============================================================================
# Fixed datetime for deterministic tests
# ============================================================================

FIXED_NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("architecture.boundary_checker.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


# ============================================================================
# Mock layer_definitions module
# ============================================================================

@pytest.fixture(autouse=True)
def mock_layer_definitions():
    """Mock the layer_definitions module for all tests."""
    with patch("architecture.boundary_checker.layer_definitions") as mock:
        # Create mock layer objects
        class MockLayer:
            def __init__(self, name):
                self.name = name

        mock.get_layer_for_module.side_effect = lambda module: {
            "domain": MockLayer("Domain"),
            "application": MockLayer("Application"),
            "infrastructure": MockLayer("Infrastructure"),
            "adapters": MockLayer("Adapters"),
            "kernel": MockLayer("Kernel"),
            "foundation": MockLayer("Foundation"),
            "architecture": MockLayer("Architecture"),
            "unknown": None,
        }.get(module.split(".")[0] if module else "", None)

        mock.is_allowed_import.side_effect = lambda src, tgt: not (
            src.startswith("application.") and tgt.startswith("domain.") and "bad" in src
        )
        # Define LAYER_DEFINITIONS for get_statistics
        mock.LAYER_DEFINITIONS = [
            MagicMock(layer=MockLayer("Domain")),
            MagicMock(layer=MockLayer("Application")),
            MagicMock(layer=MockLayer("Infrastructure")),
        ]
        yield mock


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_violation():
    return ImportViolation(
        source_file="/project/application/module.py",
        source_module="application.module",
        target_module="domain.bad",
        line_no=10,
        reason="Bad import",
        source_layer="Application",
        target_layer="Domain",
    )


@pytest.fixture
def sample_checker(tmp_path):
    # Create a temporary directory structure
    root = tmp_path / "project"
    root.mkdir()
    (root / "domain").mkdir()
    (root / "application").mkdir()
    (root / "infrastructure").mkdir()
    # Create some Python files
    (root / "domain" / "__init__.py").touch()
    (root / "application" / "__init__.py").touch()
    (root / "infrastructure" / "__init__.py").touch()
    return BoundaryChecker(str(root))


# ============================================================================
# Tests for ImportViolation
# ============================================================================

class TestImportViolation:
    def test_construction(self):
        v = ImportViolation(
            source_file="file.py",
            source_module="mod",
            target_module="target",
            line_no=5,
            reason="test",
            source_layer="LayerA",
            target_layer="LayerB",
        )
        assert v.source_file == "file.py"
        assert v.source_module == "mod"
        assert v.target_module == "target"
        assert v.line_no == 5
        assert v.reason == "test"
        assert v.source_layer == "LayerA"
        assert v.target_layer == "LayerB"
        assert v.violation_id is not None
        assert len(v.violation_id) == 8
        assert v._version == 1

    def test_file_path_property(self, sample_violation):
        assert sample_violation.file_path == sample_violation.source_file

    def test_validation_errors(self):
        with pytest.raises(ValueError, match="source_file is required"):
            ImportViolation(
                source_file="", source_module="m", target_module="t", line_no=1, reason="r"
            )
        with pytest.raises(ValueError, match="source_module is required"):
            ImportViolation(
                source_file="f", source_module="", target_module="t", line_no=1, reason="r"
            )
        with pytest.raises(ValueError, match="target_module is required"):
            ImportViolation(
                source_file="f", source_module="m", target_module="", line_no=1, reason="r"
            )
        with pytest.raises(ValueError, match="line_no must be positive"):
            ImportViolation(
                source_file="f", source_module="m", target_module="t", line_no=0, reason="r"
            )
        with pytest.raises(ValueError, match="reason is required"):
            ImportViolation(
                source_file="f", source_module="m", target_module="t", line_no=1, reason=""
            )

    def test_validate(self, sample_violation):
        result = sample_violation.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid(self):
        v = ImportViolation(
            source_file="f", source_module="m", target_module="t", line_no=1, reason="r"
        )
        v.source_file = ""
        result = v.validate()
        assert result["is_valid"] is False
        assert "source_file is required" in result["errors"][0]

    def test_to_dict(self, sample_violation):
        d = sample_violation.to_dict()
        assert d["violation_id"] == sample_violation.violation_id
        assert d["source_file"] == sample_violation.source_file
        assert d["source_module"] == sample_violation.source_module
        assert d["target_module"] == sample_violation.target_module
        assert d["line_no"] == sample_violation.line_no
        assert d["reason"] == sample_violation.reason
        assert d["source_layer"] == sample_violation.source_layer
        assert d["target_layer"] == sample_violation.target_layer
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "source_file": "f.py",
            "source_module": "mod",
            "target_module": "tgt",
            "line_no": 3,
            "reason": "bad",
            "source_layer": "A",
            "target_layer": "B",
            "violation_id": "abc123",
            "version": 2,
        }
        v = ImportViolation.from_dict(data)
        assert v.source_file == "f.py"
        assert v.source_module == "mod"
        assert v.target_module == "tgt"
        assert v.line_no == 3
        assert v.reason == "bad"
        assert v.source_layer == "A"
        assert v.target_layer == "B"
        assert v.violation_id == "abc123"
        assert v._version == 2

    def test_clone(self, sample_violation):
        cloned = sample_violation.clone()
        assert cloned is not sample_violation
        assert cloned.source_file == sample_violation.source_file
        assert cloned._version == sample_violation._version + 1
        assert len(cloned._audit_trail) == 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self, sample_violation):
        snap = sample_violation.snapshot()
        assert snap["version"] == sample_violation._version
        assert snap["violation_id"] == sample_violation.violation_id
        assert snap["source_file"] == sample_violation.source_file
        assert snap["line_no"] == sample_violation.line_no
        assert "timestamp" in snap

    def test_version(self, sample_violation):
        assert sample_violation.version() == 1

    def test_audit_trail(self, sample_violation):
        sample_violation._record_audit("TEST", "user", {"k": "v"})
        trail = sample_violation.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test_touch(self, sample_violation):
        touched = sample_violation.touch("toucher")
        assert touched._version == sample_violation._version + 1
        trail = touched.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"

    def test_str(self, sample_violation):
        expected = "f.py:10: Bad import (application.module -> domain.bad)"
        # Note: sample_violation source_file is "/project/application/module.py", not f.py.
        # We'll use a fresh one.
        v = ImportViolation(
            source_file="f.py",
            source_module="application.module",
            target_module="domain.bad",
            line_no=10,
            reason="Bad import",
        )
        assert str(v) == "f.py:10: Bad import (application.module -> domain.bad)"


# ============================================================================
# Tests for BoundaryChecker
# ============================================================================

class TestBoundaryChecker:
    # ---- Initialization ----
    def test_construction(self, sample_checker):
        assert sample_checker.root_path.exists()
        assert isinstance(sample_checker.exclude_dirs, set)
        assert sample_checker._version == 1
        assert sample_checker._checker_id is not None

    def test_construction_with_custom_excludes(self, tmp_path):
        checker = BoundaryChecker(str(tmp_path), exclude_dirs=["custom"], exclude_patterns=["*.tmp"])
        assert "custom" in checker.exclude_dirs
        assert "*.tmp" in checker.exclude_patterns

    # ---- _should_exclude ----
    def test_should_exclude_dir(self, sample_checker):
        path = sample_checker.root_path / "__pycache__" / "cache.py"
        assert sample_checker._should_exclude(path) is True

    def test_should_exclude_pattern(self, sample_checker):
        sample_checker.exclude_patterns = ["*.tmp"]
        path = sample_checker.root_path / "file.tmp"
        assert sample_checker._should_exclude(path) is True

    def test_should_exclude_not(self, sample_checker):
        path = sample_checker.root_path / "domain" / "file.py"
        assert sample_checker._should_exclude(path) is False

    # ---- _get_module_name ----
    def test_get_module_name(self, sample_checker):
        file_path = sample_checker.root_path / "domain" / "module.py"
        # Need to create the file for relative path to work
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()
        module = sample_checker._get_module_name(file_path)
        # Should be relative path with dots, e.g., "domain.module"
        # The root_path is something like /tmp/project, so relative is domain/module.py
        # With .py removed, becomes domain.module
        assert module == "domain.module" or module.endswith(".domain.module")  # depending on tmp_path

    # ---- _is_stdlib_module ----
    def test_is_stdlib_module(self, sample_checker):
        assert sample_checker._is_stdlib_module("sys") is True
        assert sample_checker._is_stdlib_module("os.path") is True
        assert sample_checker._is_stdlib_module("numpy") is False
        assert sample_checker._is_stdlib_module("domain") is False

    # ---- _is_external_library ----
    def test_is_external_library(self, sample_checker):
        sample_checker._internal_layers = {"domain", "application", "infrastructure"}
        assert sample_checker._is_external_library("requests") is True
        assert sample_checker._is_external_library("domain") is False
        assert sample_checker._is_external_library("sys") is False  # stdlib

    # ---- _is_relative_import ----
    def test_is_relative_import(self, sample_checker):
        assert sample_checker._is_relative_import(".module") is True
        assert sample_checker._is_relative_import("..parent") is True
        assert sample_checker._is_relative_import("domain") is False

    # ---- _resolve_relative_import ----
    def test_resolve_relative_import(self, sample_checker):
        # current module: application.sub.module
        resolved = sample_checker._resolve_relative_import("application.sub.module", ".util")
        assert resolved == "application.sub.util"
        resolved2 = sample_checker._resolve_relative_import("application.sub.module", "..other")
        assert resolved2 == "application.other"
        resolved3 = sample_checker._resolve_relative_import("application.sub.module", "...base")
        assert resolved3 == "base"
        resolved4 = sample_checker._resolve_relative_import("application.sub.module", ".")
        assert resolved4 == "application.sub"

    # ---- _parse_imports ----
    def test_parse_imports(self, sample_checker, tmp_path):
        file_path = tmp_path / "test.py"
        content = """
import sys
from os import path
import domain.something
from application import module
"""
        with open(file_path, "w") as f:
            f.write(content)
        imports = sample_checker._parse_imports(file_path)
        # Expected: [('sys', 2), ('os', 3), ('domain.something', 4), ('application', 5)]
        # But line numbers may vary based on leading whitespace; ast parses line numbers from 1.
        # The content has line 1: import sys -> lineno 2? Actually ast lines start at 1.
        # We'll just check the modules.
        modules = [imp[0] for imp in imports]
        assert "sys" in modules
        assert "os" in modules
        assert "domain.something" in modules
        assert "application" in modules

    def test_parse_imports_with_syntax_error(self, sample_checker, tmp_path):
        file_path = tmp_path / "bad.py"
        with open(file_path, "w") as f:
            f.write("import invalid syntax")
        with pytest.raises(SyntaxError, match="Gagal memproses analisis AST"):
            sample_checker._parse_imports(file_path)

    # ---- check ----
    def test_check_no_violations(self, sample_checker):
        # The checker will parse all Python files in the temp directory.
        # Since we have only __init__.py files, there might be no imports.
        # But we need to ensure layer_definitions mock returns something.
        violations = sample_checker.check()
        # There should be no violations because no imports exist.
        assert len(violations) == 0

    def test_check_with_violation(self, sample_checker):
        # Create a file with a violating import
        file_path = sample_checker.root_path / "application" / "bad.py"
        file_path.write_text("import domain.something\n")
        violations = sample_checker.check()
        # The mock is_allowed_import returns False for application -> domain with "bad" in source
        # Since source module is "application.bad", it should be disallowed.
        assert len(violations) == 1
        v = violations[0]
        assert "domain.something" in v.target_module
        assert v.line_no == 1
        assert "Application" in v.source_layer
        assert "Domain" in v.target_layer

    # ---- report, report_json, report_html ----
    def test_report_no_violations(self, sample_checker):
        sample_checker.check()
        report = sample_checker.report()
        assert "✅ No architecture boundary violations found" in report

    def test_report_with_violations(self, sample_checker):
        # Add a violation manually
        v = ImportViolation(
            source_file=str(sample_checker.root_path / "application" / "bad.py"),
            source_module="application.bad",
            target_module="domain.something",
            line_no=1,
            reason="Bad import",
            source_layer="Application",
            target_layer="Domain",
        )
        sample_checker.violations = [v]
        report = sample_checker.report()
        assert "❌ Found 1 architecture violation" in report
        assert "application/bad.py" in report or "application\\bad.py" in report
        assert "domain.something" in report

    def test_report_json(self, sample_checker):
        sample_checker.violations = [
            ImportViolation("f.py", "mod", "tgt", 1, "r", "A", "B")
        ]
        json_data = sample_checker.report_json()
        assert json_data["total_violations"] == 1
        assert len(json_data["violations"]) == 1
        assert json_data["violations"][0]["source_file"] == "f.py"
        assert "timestamp" in json_data

    def test_report_html(self, sample_checker):
        sample_checker.violations = [
            ImportViolation("f.py", "mod", "tgt", 1, "r", "A", "B")
        ]
        html = sample_checker.report_html()
        assert "<h1>Architecture Boundary Check Report</h1>" in html
        assert "f.py:1" in html
        assert "mod → tgt" in html

    def test_report_html_with_output(self, sample_checker, tmp_path):
        sample_checker.violations = [
            ImportViolation("f.py", "mod", "tgt", 1, "r", "A", "B")
        ]
        output_file = tmp_path / "report.html"
        sample_checker.report_html(output_file)
        assert output_file.exists()
        content = output_file.read_text()
        assert "Architecture Boundary Check Report" in content

    # ---- get_statistics ----
    def test_get_statistics(self, sample_checker):
        # Create a file that will be counted as Domain
        (sample_checker.root_path / "domain" / "file.py").write_text("# empty")
        sample_checker.check()
        stats = sample_checker.get_statistics()
        assert stats["total_files"] >= 3  # At least domain, application, infrastructure __init__.py + domain/file.py
        assert stats["total_violations"] == 0
        assert "by_layer" in stats
        assert "Domain" in stats["by_layer"]
        assert stats["by_layer"]["Domain"]["files"] >= 1

    # ---- Entity basic methods ----
    def test_validate(self, sample_checker):
        result = sample_checker.validate()
        assert result["is_valid"] is True

    def test_validate_with_invalid_version(self, sample_checker):
        sample_checker._version = 0
        result = sample_checker.validate()
        assert result["is_valid"] is False
        assert "Version must be >= 1" in result["errors"][0]

    def test_validate_with_invalid_violation(self, sample_checker):
        v = ImportViolation("", "m", "t", 1, "r")  # invalid source_file
        sample_checker.violations = [v]
        result = sample_checker.validate()
        assert result["is_valid"] is False
        assert any("source_file is required" in e for e in result["errors"])

    def test_to_dict(self, sample_checker):
        d = sample_checker.to_dict()
        assert d["checker_id"] == sample_checker._checker_id
        assert d["root_path"] == str(sample_checker.root_path)
        assert d["total_violations"] == 0
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "root_path": "/some/path",
            "exclude_dirs": ["dir1", "dir2"],
            "exclude_patterns": ["*.tmp"],
            "version": 2,
            "checker_id": "custom-id",
        }
        checker = BoundaryChecker.from_dict(data)
        assert checker.root_path == Path("/some/path")
        assert checker.exclude_dirs == {"dir1", "dir2"}
        assert checker.exclude_patterns == ["*.tmp"]
        assert checker._version == 2
        assert checker._checker_id == "custom-id"

    def test_clone(self, sample_checker):
        cloned = sample_checker.clone()
        assert cloned is not sample_checker
        assert cloned._version == sample_checker._version + 1
        assert len(cloned._audit_trail) == 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self, sample_checker):
        snap = sample_checker.snapshot()
        assert snap["version"] == sample_checker._version
        assert snap["checker_id"] == sample_checker._checker_id
        assert snap["root_path"] == str(sample_checker.root_path)
        assert snap["violations_count"] == 0

    def test_version(self, sample_checker):
        assert sample_checker.version() == 1

    def test_audit_trail(self, sample_checker):
        sample_checker._record_audit("TEST", "user", {})
        trail = sample_checker.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test_touch(self, sample_checker):
        touched = sample_checker.touch("toucher")
        assert touched._version == sample_checker._version + 1
        trail = touched.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"

    def test_reset(self, sample_checker):
        sample_checker.violations = [MagicMock()]
        sample_checker.reset()
        assert sample_checker.violations == []
        assert sample_checker._version == 1
        assert sample_checker._audit_trail == []
        # Check that reset records audit
        assert len(sample_checker._audit_trail) == 1
        assert sample_checker._audit_trail[0]["action"] == "RESET"

    # ---- _get_stdlib_modules (indirect) ----
    def test_get_stdlib_modules_includes_builtins(self, sample_checker):
        stdlib = sample_checker._get_stdlib_modules()
        assert "sys" in stdlib
        assert "os" in stdlib
        assert "typing" in stdlib
        assert "__future__" in stdlib
        assert "numpy" not in stdlib


# ============================================================================
# Tests for convenience functions
# ============================================================================

class TestConvenienceFunctions:
    def test_check_all_boundaries(self, tmp_path):
        # Create a valid project structure with no violations
        root = tmp_path / "project"
        root.mkdir()
        (root / "domain").mkdir()
        (root / "application").mkdir()
        (root / "domain" / "__init__.py").touch()
        (root / "application" / "__init__.py").touch()
        # Create a file with a good import
        (root / "application" / "good.py").write_text("import domain.something\n")
        # But we need to ensure the mock allows this import; in our mock is_allowed_import
        # allows unless source contains "bad". So it should be allowed.
        with patch("architecture.boundary_checker.BoundaryChecker") as MockChecker:
            instance = MockChecker.return_value
            instance.check.return_value = []
            instance.report.return_value = "✅"
            result = check_all_boundaries(str(root), verbose=False)
            assert result is True
            instance.check.assert_called_once()

    def test_check_all_boundaries_with_violation(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        (root / "domain").mkdir()
        (root / "application").mkdir()
        (root / "application" / "bad.py").write_text("import domain.bad\n")
        with patch("architecture.boundary_checker.BoundaryChecker") as MockChecker:
            instance = MockChecker.return_value
            v = ImportViolation("bad.py", "app", "domain", 1, "bad")
            instance.check.return_value = [v]
            instance.report.return_value = "❌"
            result = check_all_boundaries(str(root), verbose=False)
            assert result is False

    def test_get_architecture_report_json(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        with patch("architecture.boundary_checker.BoundaryChecker") as MockChecker:
            instance = MockChecker.return_value
            instance.check.return_value = []
            instance.report_json.return_value = {"total": 0}
            result = get_architecture_report(str(root), format="json")
            assert result == {"total": 0}
            instance.check.assert_called_once()
            instance.report_json.assert_called_once()

    def test_get_architecture_report_html(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        with patch("architecture.boundary_checker.BoundaryChecker") as MockChecker:
            instance = MockChecker.return_value
            instance.check.return_value = []
            instance.report_html.return_value = "<html>"
            result = get_architecture_report(str(root), format="html")
            assert result == "<html>"

    def test_get_architecture_report_text(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        with patch("architecture.boundary_checker.BoundaryChecker") as MockChecker:
            instance = MockChecker.return_value
            instance.check.return_value = []
            instance.report.return_value = "✅"
            result = get_architecture_report(str(root), format="text")
            assert result == "✅"
