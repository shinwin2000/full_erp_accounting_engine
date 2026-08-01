# tests/adapters/primary_api/test_cli_command_adapter.py
# Perbaikan kualitas assertions: mengganti semua assert True dengan
# assertion yang memeriksa nilai aktual, efek samping, dan interaksi mock.

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import typer
from typer.testing import CliRunner

from adapters.primary_api.cli_command_adapter import (
    IdempotencyManager,
    _execute_command,
    _run_async,
    app,
    check_integrity,
    export_audit_log,
    get_user_id_from_env_or_input,
    get_user_id_from_token,
    init_buses,
    period_close,
    show_trial_balance,
)


# ============================================================================
# IdempotencyManager tests
# ============================================================================
class TestIdempotencyManager:
    def test_cache_and_get(self):
        manager = IdempotencyManager()
        key = "test-key"
        cmd = "test-cmd"
        result = {"success": True, "data": "value"}
        manager.cache_result(key, cmd, result)
        cached = manager.get_cached_result(key, cmd)
        assert cached == result

    def test_get_nonexistent(self):
        manager = IdempotencyManager()
        assert manager.get_cached_result("missing", "cmd") is None

    def test_ttl_expiry(self):
        manager = IdempotencyManager()
        key = "k1"
        cmd = "c1"
        result = {"status": "ok"}
        manager.cache_result(key, cmd, result)
        storage_key = manager._get_storage_key(key, cmd)
        # Simulate TTL expiry by setting timestamp to old
        old_time = datetime.now(UTC) - timedelta(seconds=manager._ttl_seconds + 10)
        manager._storage[storage_key] = (manager._storage[storage_key][0], old_time)
        cached = manager.get_cached_result(key, cmd)
        assert cached is None
        assert storage_key not in manager._storage

    def test_cache_result_fallback_on_serialization_error(self):
        manager = IdempotencyManager()
        class Unserializable:
            pass
        manager.cache_result("key", "cmd", {"data": Unserializable()})
        cached = manager.get_cached_result("key", "cmd")
        assert cached is not None
        assert "result" in cached  # fallback wrapper


# ============================================================================
# init_buses test
# ============================================================================
def test_init_buses():
    with patch("adapters.primary_api.cli_command_adapter.CommandBusUnified") as mock_cmd_bus:
        with patch("adapters.primary_api.cli_command_adapter.QueryBusUnified") as mock_query_bus:
            with patch("adapters.primary_api.cli_command_adapter.APIKeyValidator"):
                with patch("adapters.primary_api.cli_command_adapter.JWTValidator"):
                    # Ensure global variables are reset
                    import adapters.primary_api.cli_command_adapter as module
                    module.command_bus = None
                    module.query_bus = None
                    module.api_key_validator = None
                    module.jwt_validator = None

                    init_buses()

                    assert module.command_bus is not None
                    assert module.query_bus is not None
                    assert module.api_key_validator is not None
                    assert module.jwt_validator is not None
                    mock_cmd_bus.assert_called_once()
                    mock_query_bus.assert_called_once()


# ============================================================================
# get_user_id_from_token tests
# ============================================================================
def test_get_user_id_from_token_valid():
    token = "valid.token"
    mock_payload = {"sub": "12345678-1234-5678-1234-567812345678"}
    with patch("adapters.primary_api.cli_command_adapter.jwt_validator") as mock_jwt:
        mock_jwt.validate = AsyncMock(return_value=mock_payload)
        with patch("adapters.primary_api.cli_command_adapter._run_async") as mock_run:
            mock_run.side_effect = lambda x: x() if asyncio.iscoroutine(x) else x
            # Actually we need to simulate the async call properly
            # We'll patch _run_async to call the coroutine
            async def run_async(coro):
                return await coro
            with patch("adapters.primary_api.cli_command_adapter._run_async", side_effect=run_async):
                user_id = get_user_id_from_token(token)
                assert user_id == UUID("12345678-1234-5678-1234-567812345678")

def test_get_user_id_from_token_invalid():
    with patch("adapters.primary_api.cli_command_adapter.jwt_validator") as mock_jwt:
        mock_jwt.validate = AsyncMock(side_effect=Exception("invalid"))
        user_id = get_user_id_from_token("bad")
        assert user_id is None


# ============================================================================
# get_user_id_from_env_or_input tests
# ============================================================================
def test_get_user_id_from_env_or_input_with_api_key(monkeypatch):
    monkeypatch.setenv("ERP_CLI_API_KEY", "api_key_123")
    mock_user_id = UUID("12345678-1234-5678-1234-567812345678")
    with patch("adapters.primary_api.cli_command_adapter.api_key_validator") as mock_validator:
        mock_validator.validate_and_get_user = AsyncMock(return_value=mock_user_id)
        with patch("adapters.primary_api.cli_command_adapter._run_async") as mock_run:
            async def run_async(coro):
                return await coro
            mock_run.side_effect = run_async
            user_id = get_user_id_from_env_or_input()
            assert user_id == mock_user_id

def test_get_user_id_from_env_or_input_without_env_prompts(monkeypatch, capsys):
    monkeypatch.delenv("ERP_CLI_API_KEY", raising=False)
    # Mock typer.prompt to return a token
    with patch("adapters.primary_api.cli_command_adapter.typer.prompt") as mock_prompt:
        mock_prompt.return_value = "some.jwt.token"
        with patch("adapters.primary_api.cli_command_adapter.get_user_id_from_token") as mock_from_token:
            mock_from_token.return_value = UUID("12345678-1234-5678-1234-567812345678")
            user_id = get_user_id_from_env_or_input()
            assert user_id == UUID("12345678-1234-5678-1234-567812345678")
            mock_prompt.assert_called_once_with("Enter JWT token (or API key)", hide_input=True)
            mock_from_token.assert_called_once_with("some.jwt.token")

def test_get_user_id_from_env_or_input_authentication_failure(monkeypatch, capsys):
    monkeypatch.delenv("ERP_CLI_API_KEY", raising=False)
    with patch("adapters.primary_api.cli_command_adapter.typer.prompt") as mock_prompt:
        mock_prompt.return_value = "bad.token"
        with patch("adapters.primary_api.cli_command_adapter.get_user_id_from_token") as mock_from_token:
            mock_from_token.return_value = None
            with pytest.raises(SystemExit):
                get_user_id_from_env_or_input()
            captured = capsys.readouterr()
            assert "Authentication failed" in captured.err or "Authentication failed" in captured.out


# ============================================================================
# CLI command tests using CliRunner
# ============================================================================
@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_buses():
    with patch("adapters.primary_api.cli_command_adapter.command_bus") as mock_cmd:
        with patch("adapters.primary_api.cli_command_adapter.query_bus") as mock_query:
            mock_cmd.dispatch = AsyncMock(return_value={"success": True})
            mock_query.dispatch = AsyncMock(return_value={"success": True})
            yield mock_cmd, mock_query


@pytest.fixture
def mock_auth(monkeypatch):
    # Mock authentication to always return a fixed user ID
    def fake_get_user():
        return UUID("12345678-1234-5678-1234-567812345678")
    with patch("adapters.primary_api.cli_command_adapter.get_user_id_from_env_or_input") as mock:
        mock.return_value = fake_get_user()
        yield mock


# ----------------------------------------------------------------------------
# post_journal command
# ----------------------------------------------------------------------------
def test_post_journal_success(runner, mock_buses, mock_auth):
    mock_cmd, _ = mock_buses
    mock_cmd.dispatch.return_value = {"success": True, "voucher_number": "JRN-001"}

    result = runner.invoke(app, [
        "post-journal",
        "12345678-1234-5678-1234-567812345678",
        "--legal-entity", "12345678-1234-5678-1234-567812345679",
        "--idempotency-key", "idem123"
    ])
    assert result.exit_code == 0
    assert "Journal JRN-001 posted successfully" in result.stdout
    mock_cmd.dispatch.assert_called_once_with({
        "type": "journal.post",
        "data": {
            "journal_id": UUID("12345678-1234-5678-1234-567812345678"),
            "posted_by": UUID("12345678-1234-5678-1234-567812345678"),  # from mock_auth
            "legal_entity_id": UUID("12345678-1234-5678-1234-567812345679"),
        }
    })

def test_post_journal_failure(runner, mock_buses, mock_auth):
    mock_cmd, _ = mock_buses
    mock_cmd.dispatch.return_value = {"success": False, "error": "Invalid journal"}

    result = runner.invoke(app, [
        "post-journal",
        "12345678-1234-5678-1234-567812345678",
        "--legal-entity", "12345678-1234-5678-1234-567812345679",
    ])
    assert result.exit_code == 1
    assert "Failed: Invalid journal" in result.stdout

def test_post_journal_idempotent(runner, mock_buses, mock_auth):
    mock_cmd, _ = mock_buses
    mock_cmd.dispatch.return_value = {"success": True, "voucher_number": "JRN-002"}

    # First call should execute
    result1 = runner.invoke(app, [
        "post-journal",
        "12345678-1234-5678-1234-567812345678",
        "--legal-entity", "12345678-1234-5678-1234-567812345679",
        "--idempotency-key", "idem456"
    ])
    assert result1.exit_code == 0
    assert mock_cmd.dispatch.call_count == 1

    # Second call with same key should hit cache and not dispatch
    result2 = runner.invoke(app, [
        "post-journal",
        "12345678-1234-5678-1234-567812345678",
        "--legal-entity", "12345678-1234-5678-1234-567812345679",
        "--idempotency-key", "idem456"
    ])
    assert result2.exit_code == 0
    assert mock_cmd.dispatch.call_count == 1  # no additional call
    assert "Idempotent cache hit" in result2.stdout


# ----------------------------------------------------------------------------
# create_journal command
# ----------------------------------------------------------------------------
def test_create_journal_success(runner, mock_buses, mock_auth, tmp_path):
    mock_cmd, _ = mock_buses
    mock_cmd.dispatch.return_value = {"success": True, "id": "jrn-001", "voucher_number": "JRN-001"}

    lines_file = tmp_path / "lines.json"
    lines_file.write_text(json.dumps([
        {"account_code": "101", "debit": "1000", "credit": "0", "description": "Cash"},
        {"account_code": "201", "debit": "0", "credit": "1000", "description": "Revenue"}
    ]))

    result = runner.invoke(app, [
        "create-journal",
        "--description", "Test journal",
        "--date", "2026-01-01",
        "--lines", str(lines_file),
        "--legal-entity", "12345678-1234-5678-1234-567812345679",
        "--ref", "REF001",
        "--idempotency-key", "idem789"
    ])
    assert result.exit_code == 0
    assert "Journal entry registered: ID = jrn-001, Voucher = JRN-001" in result.stdout
    mock_cmd.dispatch.assert_called_once()
    call_args = mock_cmd.dispatch.call_args[0][0]
    assert call_args["type"] == "journal.create"
    assert call_args["data"]["description"] == "Test journal"
    assert call_args["data"]["reference_number"] == "REF001"

def test_create_journal_file_not_found(runner, mock_auth):
    result = runner.invoke(app, [
        "create-journal",
        "--description", "Test",
        "--date", "2026-01-01",
        "--lines", "nonexistent.json",
        "--legal-entity", "12345678-1234-5678-1234-567812345679",
    ])
    assert result.exit_code == 1
    assert "Failed to load JSON data" in result.stdout


# ----------------------------------------------------------------------------
# period_close command
# ----------------------------------------------------------------------------
def test_period_close_success(runner, mock_buses, mock_auth):
    mock_cmd, _ = mock_buses
    mock_cmd.dispatch.return_value = {"success": True, "closing_journal_id": "clj-001"}

    result = runner.invoke(app, [
        "period-close",
        "--year", "2026",
        "--period", "12",
        "--legal-entity", "12345678-1234-5678-1234-567812345679",
        "--idempotency-key", "idem123"
    ])
    assert result.exit_code == 0
    assert "Period 12/2026 closed successfully" in result.stdout
    mock_cmd.dispatch.assert_called_once_with({
        "type": "period.close",
        "data": {
            "fiscal_year": 2026,
            "period": 12,
            "legal_entity_id": UUID("12345678-1234-5678-1234-567812345679"),
            "closed_by": UUID("12345678-1234-5678-1234-567812345678"),
        }
    })


# ----------------------------------------------------------------------------
# generate_report command
# ----------------------------------------------------------------------------
def test_generate_report_success(runner, mock_buses, mock_auth, tmp_path):
    mock_cmd, mock_query = mock_buses
    mock_query.dispatch.return_value = {"success": True, "file_path": str(tmp_path / "report.pdf")}

    output_file = tmp_path / "report.pdf"
    result = runner.invoke(app, [
        "generate-report",
        "--type", "trial_balance",
        "--date", "2026-01-31",
        "--output", str(output_file),
        "--format", "pdf",
        "--legal-entity", "12345678-1234-5678-1234-567812345679",
    ])
    assert result.exit_code == 0
    assert f"Report saved to {output_file}" in result.stdout
    # Check that query was dispatched
    mock_query.dispatch.assert_called_once()
    call_args = mock_query.dispatch.call_args[0][0]
    assert call_args["type"] == "report.trial_balance"
    assert call_args["data"]["as_of_date"] == date(2026, 1, 31)


# ----------------------------------------------------------------------------
# run_depreciation command
# ----------------------------------------------------------------------------
def test_run_depreciation_success(runner, mock_buses, mock_auth):
    mock_cmd, _ = mock_buses
    mock_cmd.dispatch.return_value = {
        "success": True,
        "total_assets": 5,
        "total_depreciation": "1000.00",
        "journal_ids": ["j1", "j2"]
    }

    result = runner.invoke(app, [
        "run-depreciation",
        "--date", "2026-01-31",
        "--legal-entity", "12345678-1234-5678-1234-567812345679",
        "--post",
        "--idempotency-key", "idem123"
    ])
    assert result.exit_code == 0
    assert "Depreciation completed. Total: 5 assets, Amount: 1000.00" in result.stdout
    assert "Journal IDs: j1, j2" in result.stdout


# ----------------------------------------------------------------------------
# reconcile_bank command
# ----------------------------------------------------------------------------
def test_reconcile_bank_success(runner, mock_buses, mock_auth, tmp_path):
    mock_cmd, _ = mock_buses
    mock_cmd.dispatch.return_value = {
        "success": True,
        "matched_count": 10,
        "unmatched_book": 2,
        "unmatched_statement": 1,
        "adjustment_journal_id": "adj-001"
    }

    stmt_file = tmp_path / "statement.csv"
    stmt_file.write_text("date,amount,ref\n2026-01-01,100,ref1")

    result = runner.invoke(app, [
        "reconcile-bank",
        "--account", "12345678-1234-5678-1234-567812345678",
        "--date", "2026-01-31",
        "--balance", "5000",
        "--statement", str(stmt_file),
        "--legal-entity", "12345678-1234-5678-1234-567812345679",
        "--idempotency-key", "idem123"
    ])
    assert result.exit_code == 0
    assert "Reconciliation completed. Matched: 10" in result.stdout
    assert "Adjustment journal: adj-001" in result.stdout


# ----------------------------------------------------------------------------
# show_trial_balance command
# ----------------------------------------------------------------------------
def test_show_trial_balance_success(runner, mock_buses, mock_auth):
    mock_cmd, mock_query = mock_buses
    mock_query.dispatch.return_value = {
        "success": True,
        "lines": [
            {"account_code": "101", "account_name": "Cash", "closing_balance_debit": "1000", "closing_balance_credit": "0"},
        ],
        "total_debit": "1000",
        "total_credit": "1000",
        "is_balanced": True
    }

    result = runner.invoke(app, [
        "show-trial-balance",
        "--date", "2026-01-31",
        "--legal-entity", "12345678-1234-5678-1234-567812345679",
    ])
    assert result.exit_code == 0
    assert "Trial Balance as of 2026-01-31" in result.stdout
    assert "Cash" in result.stdout
    assert "✓ Balanced" in result.stdout


# ----------------------------------------------------------------------------
# check_integrity command
# ----------------------------------------------------------------------------
def test_check_integrity_success(runner, mock_buses, mock_auth):
    mock_cmd, _ = mock_buses
    mock_cmd.dispatch.return_value = {"success": True, "is_valid": True}

    result = runner.invoke(app, [
        "check-integrity",
        "--legal-entity", "12345678-1234-5678-1234-567812345679",
        "--idempotency-key", "idem123"
    ])
    assert result.exit_code == 0
    assert "Hash chain integrity: OK" in result.stdout

def test_check_integrity_failure(runner, mock_buses, mock_auth):
    mock_cmd, _ = mock_buses
    mock_cmd.dispatch.return_value = {"success": True, "is_valid": False, "broken_segment": "seg-001"}

    result = runner.invoke(app, [
        "check-integrity",
        "--legal-entity", "12345678-1234-5678-1234-567812345679",
    ])
    assert result.exit_code == 1
    assert "Hash chain integrity: FAILED!" in result.stdout
    assert "First broken segment: seg-001" in result.stdout


# ----------------------------------------------------------------------------
# export_audit_log command
# ----------------------------------------------------------------------------
def test_export_audit_log_success(runner, mock_buses, mock_auth, tmp_path):
    mock_cmd, mock_query = mock_buses
    mock_query.dispatch.return_value = {"success": True, "data": [{"event": "test"}]}

    out_file = tmp_path / "audit.json"
    result = runner.invoke(app, [
        "export-audit-log",
        "--start", "2026-01-01",
        "--end", "2026-01-31",
        "--output", str(out_file),
        "--legal-entity", "12345678-1234-5678-1234-567812345679",
    ])
    assert result.exit_code == 0
    assert f"Audit log exported to {out_file}" in result.stdout
    assert out_file.exists()
    with open(out_file) as f:
        data = json.load(f)
        assert data == [{"event": "test"}]


# ============================================================================
# CLI help and main entry
# ============================================================================
def test_cli_help(runner):
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ERP Accounting Engine Command Line Interface" in result.stdout

def test_main_no_args(runner, capsys):
    # When running main with no args, it shows help
    with patch("sys.argv", ["cli"]):
        from adapters.primary_api.cli_command_adapter import main
        with patch("adapters.primary_api.cli_command_adapter.app") as mock_app:
            main()
            mock_app.assert_called_once()


# ============================================================================
# Additional direct tests for uncovered functions
# ============================================================================

class TestRunAsync:
    def test_run_async_success(self):
        async def sample_coro():
            return "success"
        result = _run_async(sample_coro())
        assert result == "success"

    def test_run_async_exception(self):
        async def failing_coro():
            raise ValueError("fail")
        with pytest.raises(ValueError, match="fail"):
            _run_async(failing_coro())


class TestExecuteCommand:
    def test_execute_command_no_cache(self):
        mock_cmd = AsyncMock()
        mock_cmd.dispatch.return_value = {"success": True, "data": "result"}
        with patch("adapters.primary_api.cli_command_adapter.command_bus", mock_cmd):
            with patch("adapters.primary_api.cli_command_adapter._idempotency_manager") as mock_mgr:
                mock_mgr.get_cached_result.return_value = None
                result = _execute_command("test.type", {"key": "value"}, "idem123", "progress")
                assert result == {"success": True, "data": "result"}
                mock_mgr.cache_result.assert_called_once_with("idem123", "test.type", {"success": True, "data": "result"})
                mock_cmd.dispatch.assert_called_once()

    def test_execute_command_with_cache(self):
        mock_cmd = AsyncMock()
        with patch("adapters.primary_api.cli_command_adapter.command_bus", mock_cmd):
            with patch("adapters.primary_api.cli_command_adapter._idempotency_manager") as mock_mgr:
                mock_mgr.get_cached_result.return_value = {"cached": "result"}
                result = _execute_command("test.type", {"key": "value"}, "idem123", "progress")
                assert result == {"cached": "result"}
                mock_cmd.dispatch.assert_not_called()

    def test_execute_command_auto_idempotency_key(self):
        mock_cmd = AsyncMock()
        mock_cmd.dispatch.return_value = {"success": True}
        with patch("adapters.primary_api.cli_command_adapter.command_bus", mock_cmd):
            with patch("adapters.primary_api.cli_command_adapter._idempotency_manager") as mock_mgr:
                mock_mgr.get_cached_result.return_value = None
                result = _execute_command("test.type", {"key": "value"}, None, "progress")
                assert result == {"success": True}
                mock_mgr.cache_result.assert_called_once()
                # Verify that an idempotency key was generated (we can check call args)
                call_args = mock_mgr.cache_result.call_args[0]
                assert call_args[1] == "test.type"
                assert len(call_args[0]) == 16  # generated key length


class TestPeriodCloseDirect:
    def test_period_close_success(self):
        with patch("adapters.primary_api.cli_command_adapter.init_buses"):
            with patch("adapters.primary_api.cli_command_adapter.get_user_id_from_env_or_input") as mock_user:
                mock_user.return_value = UUID("12345678-1234-5678-1234-567812345678")
                with patch("adapters.primary_api.cli_command_adapter._execute_command") as mock_exec:
                    mock_exec.return_value = {"success": True, "closing_journal_id": "clj-001"}
                    with patch("adapters.primary_api.cli_command_adapter.typer.prompt") as mock_prompt:
                        mock_prompt.return_value = "12345678-1234-5678-1234-567812345679"
                        with patch("adapters.primary_api.cli_command_adapter.set_request_id_for_task"):
                            # Call period_close directly
                            period_close(2026, 12, None, None, "idem123")
                            mock_exec.assert_called_once_with(
                                command_type="period.close",
                                command_data={
                                    "fiscal_year": 2026,
                                    "period": 12,
                                    "legal_entity_id": UUID("12345678-1234-5678-1234-567812345679"),
                                    "closed_by": UUID("12345678-1234-5678-1234-567812345678"),
                                },
                                idempotency_key="idem123",
                                progress_description="Processing...",
                            )

    def test_period_close_failure_raises_exit(self):
        with patch("adapters.primary_api.cli_command_adapter.init_buses"):
            with patch("adapters.primary_api.cli_command_adapter.get_user_id_from_env_or_input") as mock_user:
                mock_user.return_value = UUID("12345678-1234-5678-1234-567812345678")
                with patch("adapters.primary_api.cli_command_adapter._execute_command") as mock_exec:
                    mock_exec.return_value = {"success": False, "error": "Period already closed"}
                    with patch("adapters.primary_api.cli_command_adapter.typer.prompt") as mock_prompt:
                        mock_prompt.return_value = "12345678-1234-5678-1234-567812345679"
                        with patch("adapters.primary_api.cli_command_adapter.set_request_id_for_task"):
                            with pytest.raises(typer.Exit) as exc:
                                period_close(2026, 12, None, None, None)
                            assert exc.value.code == 1


class TestShowTrialBalanceDirect:
    def test_show_trial_balance_success(self):
        with patch("adapters.primary_api.cli_command_adapter.init_buses"):
            with patch("adapters.primary_api.cli_command_adapter.get_user_id_from_env_or_input") as mock_user:
                mock_user.return_value = UUID("12345678-1234-5678-1234-567812345678")
                with patch("adapters.primary_api.cli_command_adapter.query_bus") as mock_query:
                    mock_query.dispatch.return_value = {
                        "success": True,
                        "lines": [
                            {"account_code": "101", "account_name": "Cash", "closing_balance_debit": 1000, "closing_balance_credit": 0}
                        ],
                        "total_debit": 1000,
                        "total_credit": 1000,
                        "is_balanced": True
                    }
                    with patch("adapters.primary_api.cli_command_adapter.typer.prompt") as mock_prompt:
                        mock_prompt.return_value = "12345678-1234-5678-1234-567812345679"
                        with patch("adapters.primary_api.cli_command_adapter.set_request_id_for_task"):
                            with patch("adapters.primary_api.cli_command_adapter.console.print") as mock_print:
                                show_trial_balance("2026-01-31", None, None)
                                mock_query.dispatch.assert_called_once()
                                # Check that print was called at least once
                                assert mock_print.call_count > 0

    def test_show_trial_balance_failure_raises_exit(self):
        with patch("adapters.primary_api.cli_command_adapter.init_buses"):
            with patch("adapters.primary_api.cli_command_adapter.get_user_id_from_env_or_input") as mock_user:
                mock_user.return_value = UUID("12345678-1234-5678-1234-567812345678")
                with patch("adapters.primary_api.cli_command_adapter.query_bus") as mock_query:
                    mock_query.dispatch.return_value = {"success": False, "error": "DB error"}
                    with patch("adapters.primary_api.cli_command_adapter.typer.prompt") as mock_prompt:
                        mock_prompt.return_value = "12345678-1234-5678-1234-567812345679"
                        with patch("adapters.primary_api.cli_command_adapter.set_request_id_for_task"):
                            with pytest.raises(typer.Exit) as exc:
                                show_trial_balance("2026-01-31", None, None)
                            assert exc.value.code == 1


class TestCheckIntegrityDirect:
    def test_check_integrity_success(self):
        with patch("adapters.primary_api.cli_command_adapter.init_buses"):
            with patch("adapters.primary_api.cli_command_adapter.get_user_id_from_env_or_input") as mock_user:
                mock_user.return_value = UUID("12345678-1234-5678-1234-567812345678")
                with patch("adapters.primary_api.cli_command_adapter._execute_command") as mock_exec:
                    mock_exec.return_value = {"success": True, "is_valid": True}
                    with patch("adapters.primary_api.cli_command_adapter.typer.prompt") as mock_prompt:
                        mock_prompt.return_value = "12345678-1234-5678-1234-567812345679"
                        with patch("adapters.primary_api.cli_command_adapter.set_request_id_for_task"):
                            with patch("adapters.primary_api.cli_command_adapter.console.print"):
                                check_integrity(None, None, "idem123")
                                mock_exec.assert_called_once_with(
                                    command_type="audit.verify_integrity",
                                    command_data={
                                        "legal_entity_id": UUID("12345678-1234-5678-1234-567812345679"),
                                        "verified_by": UUID("12345678-1234-5678-1234-567812345678"),
                                    },
                                    idempotency_key="idem123",
                                    progress_description="Verifying hash chain...",
                                )

    def test_check_integrity_failure_raises_exit(self):
        with patch("adapters.primary_api.cli_command_adapter.init_buses"):
            with patch("adapters.primary_api.cli_command_adapter.get_user_id_from_env_or_input") as mock_user:
                mock_user.return_value = UUID("12345678-1234-5678-1234-567812345678")
                with patch("adapters.primary_api.cli_command_adapter._execute_command") as mock_exec:
                    mock_exec.return_value = {"success": True, "is_valid": False, "broken_segment": "seg-001"}
                    with patch("adapters.primary_api.cli_command_adapter.typer.prompt") as mock_prompt:
                        mock_prompt.return_value = "12345678-1234-5678-1234-567812345679"
                        with patch("adapters.primary_api.cli_command_adapter.set_request_id_for_task"):
                            with pytest.raises(typer.Exit) as exc:
                                check_integrity(None, None, None)
                            assert exc.value.code == 1


class TestExportAuditLogDirect:
    def test_export_audit_log_success(self, tmp_path):
        with patch("adapters.primary_api.cli_command_adapter.init_buses"):
            with patch("adapters.primary_api.cli_command_adapter.get_user_id_from_env_or_input") as mock_user:
                mock_user.return_value = UUID("12345678-1234-5678-1234-567812345678")
                with patch("adapters.primary_api.cli_command_adapter.query_bus") as mock_query:
                    mock_query.dispatch.return_value = {"success": True, "data": [{"event": "test"}]}
                    with patch("adapters.primary_api.cli_command_adapter.typer.prompt") as mock_prompt:
                        mock_prompt.return_value = "12345678-1234-5678-1234-567812345679"
                        with patch("adapters.primary_api.cli_command_adapter.set_request_id_for_task"):
                            out_file = tmp_path / "audit.json"
                            export_audit_log("2026-01-01", "2026-01-31", out_file, None, None)
                            assert out_file.exists()
                            with open(out_file) as f:
                                data = json.load(f)
                                assert data == [{"event": "test"}]

    def test_export_audit_log_failure_raises_exit(self, tmp_path):
        with patch("adapters.primary_api.cli_command_adapter.init_buses"):
            with patch("adapters.primary_api.cli_command_adapter.get_user_id_from_env_or_input") as mock_user:
                mock_user.return_value = UUID("12345678-1234-5678-1234-567812345678")
                with patch("adapters.primary_api.cli_command_adapter.query_bus") as mock_query:
                    mock_query.dispatch.return_value = {"success": False, "error": "No data"}
                    with patch("adapters.primary_api.cli_command_adapter.typer.prompt") as mock_prompt:
                        mock_prompt.return_value = "12345678-1234-5678-1234-567812345679"
                        with patch("adapters.primary_api.cli_command_adapter.set_request_id_for_task"):
                            out_file = tmp_path / "audit.json"
                            with pytest.raises(typer.Exit) as exc:
                                export_audit_log("2026-01-01", "2026-01-31", out_file, None, None)
                            assert exc.value.code == 1
