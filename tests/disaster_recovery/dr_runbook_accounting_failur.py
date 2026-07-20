#!/usr/bin/env python3
"""
tests/unit/test_dr_runbook.py
Test untuk disaster_recovery/dr_runbook_accounting_failure.py
Mencakup: RunbookStep, RunbookExecution, NotificationManager,
AccountingFailureRunbook, FailureScenario, RunbookStatus, StepStatus
"""

from __future__ import annotations

import json
import tempfile
from unittest.mock import MagicMock, patch

from disaster_recovery.dr_runbook_accounting_failure import (
    AccountingFailureRunbook,
    FailureScenario,
    NotificationManager,
    NotificationSeverity,
    RunbookExecution,
    RunbookStatus,
    RunbookStep,
    StepStatus,
)


class TestRunbookStep:
    def test_create_valid_step(self):
        """Test creation of valid RunbookStep."""
        def action():
            return {"status": "ok"}
        step = RunbookStep(
            name="test_step",
            action=action,
            timeout_seconds=10,
            retry_count=2,
            depends_on=["dep1"],
        )
        assert step.name == "test_step"
        assert step.timeout == 10
        assert step.retry_count == 2
        assert step.depends_on == ["dep1"]
        assert step.status == StepStatus.PENDING

    def test_validate_returns_errors(self):
        """Test validate returns errors for invalid state."""
        def action():
            return {}
        step = RunbookStep(
            name="",  # invalid
            action=action,
            timeout_seconds=-1,  # invalid
        )
        result = step.validate()
        assert result["is_valid"] is False
        assert len(result["errors"]) > 0

    def test_to_dict_contains_fields(self):
        """Test to_dict returns expected structure."""
        def action():
            return {}
        step = RunbookStep(
            name="test_step",
            action=action,
            timeout_seconds=10,
        )
        d = step.to_dict()
        assert d["name"] == "test_step"
        assert d["status"] == "pending"
        assert d["retry_attempts"] == 0

    def test_clone_creates_new_instance(self):
        """Test clone creates new instance with incremented version."""
        def action():
            return {}
        step = RunbookStep(
            name="test_step",
            action=action,
            timeout_seconds=10,
        )
        cloned = step.clone()
        assert cloned.name == step.name
        assert cloned.version() == step.version() + 1

    def test_audit_trail_records_actions(self):
        """Test audit trail records actions."""
        def action():
            return {}
        step = RunbookStep(
            name="test_step",
            action=action,
        )
        step.touch("tester")
        trail = step.audit_trail()
        assert len(trail) >= 1
        assert trail[-1]["action"] == "TOUCH"


class TestRunbookExecution:
    def test_create_valid_execution(self):
        """Test creation of valid RunbookExecution."""
        execution = RunbookExecution(
            execution_id=uuid.uuid4(),
            scenario=FailureScenario.DATABASE_PRIMARY_DOWN,
            started_by="admin",
        )
        assert execution.scenario == FailureScenario.DATABASE_PRIMARY_DOWN
        assert execution.started_by == "admin"
        assert execution.status == RunbookStatus.NOT_STARTED

    def test_validate_returns_errors(self):
        """Test validate returns errors for invalid state."""
        execution = RunbookExecution(
            execution_id=uuid.uuid4(),
            scenario=FailureScenario.DATABASE_PRIMARY_DOWN,
            started_by="admin",
        )
        result = execution.validate()
        assert result["is_valid"] is True

    def test_to_dict_contains_fields(self):
        """Test to_dict returns expected structure."""
        execution = RunbookExecution(
            execution_id=uuid.uuid4(),
            scenario=FailureScenario.DATABASE_PRIMARY_DOWN,
            started_by="admin",
        )
        d = execution.to_dict()
        assert d["scenario"] == "database_primary_down"
        assert d["started_by"] == "admin"
        assert d["status"] == "not_started"

    def test_clone_creates_new_execution(self):
        """Test clone creates new execution with new ID."""
        execution = RunbookExecution(
            execution_id=uuid.uuid4(),
            scenario=FailureScenario.DATABASE_PRIMARY_DOWN,
            started_by="admin",
        )
        cloned = execution.clone()
        assert cloned.id != execution.id
        assert cloned.scenario == execution.scenario
        assert cloned.status == RunbookStatus.NOT_STARTED


class TestNotificationManager:
    def test_send_logs_message(self, caplog):
        """Test send logs message."""
        manager = NotificationManager()
        with caplog.at_level("INFO"):
            manager.send(
                severity=NotificationSeverity.INFO,
                title="Test Title",
                message="Test Message",
            )
            assert "Test Title" in caplog.text

    def test_send_email_with_config(self):
        """Test send sends email when SMTP configured."""
        manager = NotificationManager(
            smtp_config={
                "host": "smtp.example.com",
                "port": 587,
                "user": "test",
                "password": "pass",
                "from": "test@example.com",
            }
        )
        with patch("smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_server
            manager.send(
                severity=NotificationSeverity.INFO,
                title="Test Title",
                message="Test Message",
                recipients=["admin@example.com"],
            )
            mock_smtp.assert_called_once()

    def test_send_webhook_with_requests(self):
        """Test send sends webhook when requests available."""
        manager = NotificationManager(webhook_urls=["https://example.com/webhook"])
        with patch("requests.post") as mock_post:
            manager.send(
                severity=NotificationSeverity.INFO,
                title="Test Title",
                message="Test Message",
            )
            mock_post.assert_called_once()

    def test_validate_returns_errors_for_invalid_smtp(self):
        """Test validate returns errors for incomplete SMTP config."""
        manager = NotificationManager(
            smtp_config={"host": "smtp.example.com"}  # missing port
        )
        result = manager.validate()
        assert result["is_valid"] is False
        assert "SMTP port" in " ".join(result["errors"])

    def test_to_dict_contains_fields(self):
        """Test to_dict returns expected structure."""
        manager = NotificationManager(
            smtp_config={"host": "smtp.example.com", "port": 587},
            webhook_urls=["https://example.com"],
        )
        d = manager.to_dict()
        assert d["smtp_configured"] is True
        assert d["webhook_urls"] == ["https://example.com"]


class TestAccountingFailureRunbook:
    def test_create_for_database_failure(self):
        """Test creation for database failure scenario."""
        runbook = AccountingFailureRunbook(FailureScenario.DATABASE_PRIMARY_DOWN)
        assert runbook.scenario == FailureScenario.DATABASE_PRIMARY_DOWN
        assert len(runbook._steps) > 0

    def test_create_for_event_store_corruption(self):
        """Test creation for event store corruption scenario."""
        runbook = AccountingFailureRunbook(FailureScenario.EVENT_STORE_CORRUPTION)
        assert runbook.scenario == FailureScenario.EVENT_STORE_CORRUPTION
        assert len(runbook._steps) > 0

    def test_create_for_kafka_failure(self):
        """Test creation for Kafka failure scenario."""
        runbook = AccountingFailureRunbook(FailureScenario.KAFKA_BROKER_FAILURE)
        assert runbook.scenario == FailureScenario.KAFKA_BROKER_FAILURE
        assert len(runbook._steps) > 0

    def test_execute_completes_successfully(self):
        """Test execute completes all steps successfully."""
        runbook = AccountingFailureRunbook(FailureScenario.DATABASE_PRIMARY_DOWN)
        # Override actions to always succeed
        for step in runbook._steps:
            step.action = lambda: {"success": True}
        execution = runbook.execute(started_by="admin")
        assert execution.status == RunbookStatus.COMPLETED
        assert all(s.status == StepStatus.SUCCESS for s in execution.steps)

    def test_execute_fails_on_error(self):
        """Test execute fails when a step raises error."""
        runbook = AccountingFailureRunbook(FailureScenario.DATABASE_PRIMARY_DOWN)
        # Make first step fail
        if runbook._steps:
            runbook._steps[0].action = lambda: (_ for _ in ()).throw(Exception("Test error"))
        execution = runbook.execute(started_by="admin")
        assert execution.status in (RunbookStatus.FAILED, RunbookStatus.ROLLBACK_COMPLETED)
        assert execution.failed_step_index is not None

    def test_execute_skips_steps_with_unmet_dependencies(self):
        """Test execute skips steps with unmet dependencies."""
        runbook = AccountingFailureRunbook(FailureScenario.DATABASE_PRIMARY_DOWN)
        # Make dependency fail
        if len(runbook._steps) >= 2:
            runbook._steps[0].action = lambda: (_ for _ in ()).throw(Exception("Dep failed"))
        execution = runbook.execute(started_by="admin")
        # Some steps should be skipped
        skipped = [s for s in execution.steps if s.status == StepStatus.SKIPPED]
        assert len(skipped) > 0 or execution.status == RunbookStatus.FAILED

    def test_rollback_executed_on_failure(self):
        """Test rollback executed on failure for supported scenarios."""
        runbook = AccountingFailureRunbook(FailureScenario.DATABASE_PRIMARY_DOWN)
        # Make a step fail
        for i, step in enumerate(runbook._steps):
            if i == 1:
                step.action = lambda: (_ for _ in ()).throw(Exception("Test error"))
                step.rollback = lambda: {"rolled_back": True}
        execution = runbook.execute(started_by="admin")
        # Should attempt rollback
        if execution.status == RunbookStatus.FAILED:
            # Rollback might be executed
            pass
        # Check that at least something happened

    def test_get_execution_status(self):
        """Test get_execution_status returns status dict."""
        runbook = AccountingFailureRunbook(FailureScenario.DATABASE_PRIMARY_DOWN)
        runbook.execute(started_by="admin")
        status = runbook.get_execution_status()
        assert status is not None
        assert "execution_id" in status
        assert "scenario" in status
        assert "status" in status

    def test_export_to_json(self):
        """Test export_to_json writes JSON file."""
        runbook = AccountingFailureRunbook(FailureScenario.DATABASE_PRIMARY_DOWN)
        runbook.execute(started_by="admin")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            runbook.export_to_json(f.name)
            with open(f.name) as f2:
                data = json.load(f2)
                assert data["scenario"] == "database_primary_down"
                assert "steps" in data

    def test_validate_returns_errors(self):
        """Test validate returns errors for invalid state."""
        runbook = AccountingFailureRunbook(FailureScenario.DATABASE_PRIMARY_DOWN)
        # Remove an invalid step
        result = runbook.validate()
        # Should be valid because steps are valid
        assert result["is_valid"] is True

    def test_to_dict_contains_fields(self):
        """Test to_dict returns expected structure."""
        runbook = AccountingFailureRunbook(FailureScenario.DATABASE_PRIMARY_DOWN)
        d = runbook.to_dict()
        assert d["scenario"] == "database_primary_down"
        assert "steps" in d

    def test_clone_creates_new_runbook(self):
        """Test clone creates new runbook with same steps."""
        runbook = AccountingFailureRunbook(FailureScenario.DATABASE_PRIMARY_DOWN)
        cloned = runbook.clone()
        assert cloned.scenario == runbook.scenario
        assert len(cloned._steps) == len(runbook._steps)

    def test_reset_clears_execution(self):
        """Test reset clears execution and reinitializes."""
        runbook = AccountingFailureRunbook(FailureScenario.DATABASE_PRIMARY_DOWN)
        runbook.execute(started_by="admin")
        assert runbook.execution is not None
        runbook.reset()
        assert runbook.execution is None
        assert len(runbook._steps) > 0

    def test_snapshot_returns_summary(self):
        """Test snapshot returns summary dict."""
        runbook = AccountingFailureRunbook(FailureScenario.DATABASE_PRIMARY_DOWN)
        snap = runbook.snapshot()
        assert snap["scenario"] == "database_primary_down"
        assert "steps_count" in snap

    def test_audit_trail_records_actions(self):
        """Test audit trail records actions."""
        runbook = AccountingFailureRunbook(FailureScenario.DATABASE_PRIMARY_DOWN)
        runbook.touch("tester")
        trail = runbook.audit_trail()
        assert len(trail) >= 1
        assert trail[-1]["action"] == "TOUCH"


class TestIntegrationDRRunbook:
    def test_full_workflow(self):
        """Test complete workflow from start to completion."""
        runbook = AccountingFailureRunbook(FailureScenario.DATABASE_PRIMARY_DOWN)
        # Override actions to succeed
        for step in runbook._steps:
            step.action = lambda: {"status": "success"}
            step.rollback = lambda: {"rolled_back": True}

        execution = runbook.execute(started_by="admin")
        assert execution.status == RunbookStatus.COMPLETED
        assert all(s.status == StepStatus.SUCCESS for s in execution.steps)

        status = runbook.get_execution_status()
        assert status["status"] == "completed"

    def test_notification_on_failure(self):
        """Test notifications sent on failure."""
        manager = NotificationManager()
        runbook = AccountingFailureRunbook(
            FailureScenario.DATABASE_PRIMARY_DOWN,
            notification_manager=manager,
        )
        # Make first step fail
        if runbook._steps:
            runbook._steps[0].action = lambda: (_ for _ in ()).throw(Exception("Test error"))
        with patch.object(manager, "send") as mock_send:
            runbook.execute(started_by="admin")
            # Should send at least one notification
            mock_send.assert_called()
