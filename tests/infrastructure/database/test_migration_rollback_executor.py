# tests/infrastructure/database/test_migration_rollback_executor.py
"""
Comprehensive tests for migration_rollback_executor.py.
Covers all public methods, error handling, backup/restore, and CLI.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infrastructure.database.migration_rollback_executor import (
    BackupCreationError,
    MigrationRollbackError,
    MigrationRollbackExecutor,
    RollbackFailedError,
    cli,
    get_rollback_executor,
)


# ============================================================================
# Exceptions tests
# ============================================================================

class TestExceptions:
    def test_migration_rollback_error(self):
        with pytest.raises(MigrationRollbackError):
            raise MigrationRollbackError("test")

    def test_rollback_failed_error(self):
        with pytest.raises(RollbackFailedError):
            raise RollbackFailedError("test")

    def test_backup_creation_error(self):
        with pytest.raises(BackupCreationError):
            raise BackupCreationError("test")


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_manager():
    manager = AsyncMock()
    manager.get_current_revision = AsyncMock(return_value="abc123")
    manager.get_heads = AsyncMock(return_value=["abc123", "def456"])
    manager.show_history = AsyncMock(return_value=[
        {"revision": "abc123", "date": "2025-01-01"},
        {"revision": "xyz789", "date": "2024-12-31"},
    ])
    manager.downgrade = AsyncMock()
    return manager


@pytest.fixture
def executor():
    return MigrationRollbackExecutor()


# ============================================================================
# Tests for MigrationRollbackExecutor
# ============================================================================

class TestMigrationRollbackExecutor:
    @pytest.mark.asyncio
    async def test_initialization(self, executor):
        assert executor._backup_dir == Path("/var/backups/migration_rollbacks")
        assert executor._backup_dir.exists()
        assert executor._rollback_history == []

    @pytest.mark.asyncio
    async def test_get_manager_cached(self, executor):
        with patch(
            "infrastructure.database.migration_rollback_executor.get_migration_manager",
            new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = "manager"
            manager1 = await executor._get_manager()
            manager2 = await executor._get_manager()
            assert manager1 == "manager"
            assert manager2 == "manager"
            mock_get.assert_awaited_once()

    # --- _run_subprocess ---
    @pytest.mark.asyncio
    async def test_run_subprocess_success(self, executor):
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"stdout", b"stderr"))
        mock_process.returncode = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            code, stdout, stderr = await executor._run_subprocess(["echo", "test"])
            assert code == 0
            assert stdout == "stdout"
            assert stderr == "stderr"

    @pytest.mark.asyncio
    async def test_run_subprocess_error(self, executor):
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"", b"error"))
        mock_process.returncode = 1
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            code, stdout, stderr = await executor._run_subprocess(["false"])
            assert code == 1
            assert stderr == "error"

    # --- _delete_file ---
    @pytest.mark.asyncio
    async def test_delete_file(self, executor):
        mock_path = MagicMock(spec=Path)
        mock_path.unlink = MagicMock()
        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            await executor._delete_file(mock_path, ignore_missing=True)
            mock_to_thread.assert_awaited_once()
            # unlink is called inside thread, so not directly called here
            mock_path.unlink.assert_not_called()

    # --- _create_backup ---
    @pytest.mark.asyncio
    async def test_create_backup_success(self, executor):
        with patch(
            "infrastructure.database.migration_rollback_executor.load_yaml_config"
        ) as mock_load:
            mock_load.return_value = {
                "database": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "testdb",
                    "user": "testuser",
                    "password": "pass",
                }
            }
            with patch.object(executor, "_run_subprocess", new_callable=AsyncMock) as mock_run:
                mock_run.return_value = (0, "success", "")
                backup_path = await executor._create_backup("test description")
                assert isinstance(backup_path, Path)
                assert "pre_rollback" in backup_path.name
                assert backup_path.parent == Path("/var/backups/migration_rollbacks")

    @pytest.mark.asyncio
    async def test_create_backup_failure(self, executor):
        with patch(
            "infrastructure.database.migration_rollback_executor.load_yaml_config"
        ) as mock_load:
            mock_load.return_value = {"database": {}}
            with patch.object(executor, "_run_subprocess", new_callable=AsyncMock) as mock_run:
                mock_run.return_value = (1, "", "pg_dump error")
                with pytest.raises(BackupCreationError, match="pg_dump failed"):
                    await executor._create_backup("test")

    # --- _restore_backup ---
    @pytest.mark.asyncio
    async def test_restore_backup_success(self, executor):
        with patch(
            "infrastructure.database.migration_rollback_executor.load_yaml_config"
        ) as mock_load:
            mock_load.return_value = {"database": {}}
            with patch.object(executor, "_run_subprocess", new_callable=AsyncMock) as mock_run:
                mock_run.return_value = (0, "success", "")
                result = await executor._restore_backup(Path("/tmp/backup.sql"))
                assert result is True

    @pytest.mark.asyncio
    async def test_restore_backup_failure(self, executor):
        with patch(
            "infrastructure.database.migration_rollback_executor.load_yaml_config"
        ) as mock_load:
            mock_load.return_value = {"database": {}}
            with patch.object(executor, "_run_subprocess", new_callable=AsyncMock) as mock_run:
                mock_run.return_value = (1, "", "restore error")
                result = await executor._restore_backup(Path("/tmp/backup.sql"))
                assert result is False

    # --- _verify_integrity ---
    @pytest.mark.asyncio
    async def test_verify_integrity_success(self, executor):
        with patch(
            "infrastructure.database.migration_rollback_executor.get_session_factory",
            new_callable=AsyncMock
        ) as mock_factory:
            session = AsyncMock()
            session.bind = MagicMock()
            inspector = AsyncMock()
            inspector.get_table_names = AsyncMock(return_value=[
                "legal_entity", "account", "journal_header", "journal_line"
            ])
            with patch("sqlalchemy.inspect", return_value=inspector):
                session.execute = AsyncMock()
                session.execute.return_value = MagicMock()
                session.execute.return_value.scalar = MagicMock(return_value=5)
                factory = AsyncMock()
                factory.get_session = AsyncMock(return_value=session)
                mock_factory.return_value = factory
                result = await executor._verify_integrity()
                assert result is True

    @pytest.mark.asyncio
    async def test_verify_integrity_missing_tables(self, executor):
        with patch(
            "infrastructure.database.migration_rollback_executor.get_session_factory",
            new_callable=AsyncMock
        ) as mock_factory:
            session = AsyncMock()
            session.bind = MagicMock()
            inspector = AsyncMock()
            inspector.get_table_names = AsyncMock(return_value=["legal_entity"])
            with patch("sqlalchemy.inspect", return_value=inspector):
                factory = AsyncMock()
                factory.get_session = AsyncMock(return_value=session)
                mock_factory.return_value = factory
                result = await executor._verify_integrity()
                assert result is False

    # --- rollback ---
    @pytest.mark.asyncio
    async def test_rollback_dry_run(self, executor, mock_manager):
        with patch.object(executor, "_get_manager", new_callable=AsyncMock, return_value=mock_manager):
            # make sure show_history includes target
            mock_manager.show_history.return_value = [
                {"revision": "target"},
                {"revision": "abc123"},
            ]
            result = await executor.rollback("target", dry_run=True, create_backup=False)
            assert result["success"] is True
            assert result["dry_run"] is True
            assert result["backup_path"] is None
            mock_manager.downgrade.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rollback_success_no_backup(self, executor, mock_manager):
        with patch.object(executor, "_get_manager", new_callable=AsyncMock, return_value=mock_manager):
            with patch.object(executor, "_verify_integrity", new_callable=AsyncMock, return_value=True):
                result = await executor.rollback("head-1", dry_run=False, create_backup=False)
                assert result["success"] is True
                assert result["new_revision"] == mock_manager.get_current_revision.return_value
                assert result["integrity_verified"] is True
                mock_manager.downgrade.assert_awaited_once_with("head-1")

    @pytest.mark.asyncio
    async def test_rollback_success_with_backup(self, executor, mock_manager):
        with patch.object(executor, "_get_manager", new_callable=AsyncMock, return_value=mock_manager):
            with patch.object(executor, "_create_backup", new_callable=AsyncMock, return_value=Path("/tmp/backup.sql")):
                with patch.object(executor, "_verify_integrity", new_callable=AsyncMock, return_value=True):
                    result = await executor.rollback("head-1", dry_run=False, create_backup=True)
                    assert result["success"] is True
                    assert result["backup_path"] == "/tmp/backup.sql"
                    assert result["integrity_verified"] is True
                    mock_manager.downgrade.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rollback_backup_failure(self, executor, mock_manager):
        with patch.object(executor, "_get_manager", new_callable=AsyncMock, return_value=mock_manager):
            with patch.object(executor, "_create_backup", new_callable=AsyncMock, side_effect=BackupCreationError("no pg_dump")):
                result = await executor.rollback("head-1", dry_run=False, create_backup=True)
                assert result["success"] is False
                assert "Backup failed" in result["error"]
                mock_manager.downgrade.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rollback_revision_not_found(self, executor, mock_manager):
        with patch.object(executor, "_get_manager", new_callable=AsyncMock, return_value=mock_manager):
            mock_manager.show_history.return_value = [{"revision": "abc123"}]
            result = await executor.rollback("nonexistent", dry_run=False)
            assert result["success"] is False
            assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_rollback_current_revision_none(self, executor, mock_manager):
        mock_manager.get_current_revision = AsyncMock(return_value=None)
        with patch.object(executor, "_get_manager", new_callable=AsyncMock, return_value=mock_manager):
            result = await executor.rollback("head-1", dry_run=False)
            assert result["success"] is False
            assert "No current revision" in result["error"]

    @pytest.mark.asyncio
    async def test_rollback_failure_and_restore(self, executor, mock_manager):
        mock_manager.downgrade = AsyncMock(side_effect=Exception("downgrade failed"))
        with patch.object(executor, "_get_manager", new_callable=AsyncMock, return_value=mock_manager):
            with patch.object(executor, "_create_backup", new_callable=AsyncMock, return_value=Path("/tmp/backup.sql")):
                with patch.object(executor, "_restore_backup", new_callable=AsyncMock, return_value=True):
                    result = await executor.rollback("head-1", dry_run=False, create_backup=True)
                    assert result["success"] is False
                    assert "downgrade failed" in result["error"]
                    assert result.get("restored_from_backup") is True
                    executor._restore_backup.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rollback_integrity_failure(self, executor, mock_manager):
        with patch.object(executor, "_get_manager", new_callable=AsyncMock, return_value=mock_manager):
            with patch.object(executor, "_create_backup", new_callable=AsyncMock, return_value=Path("/tmp/backup.sql")):
                with patch.object(executor, "_verify_integrity", new_callable=AsyncMock, return_value=False):
                    result = await executor.rollback("head-1", dry_run=False, create_backup=True)
                    assert result["success"] is True
                    assert result["integrity_verified"] is False

    # --- rollback_last_migration ---
    @pytest.mark.asyncio
    async def test_rollback_last_migration_success(self, executor, mock_manager):
        with patch.object(executor, "_get_manager", new_callable=AsyncMock, return_value=mock_manager):
            with patch.object(executor, "rollback", new_callable=AsyncMock) as mock_rollback:
                mock_rollback.return_value = {"success": True}
                result = await executor.rollback_last_migration(dry_run=False)
                assert result["success"] is True
                mock_rollback.assert_awaited_once_with("xyz789", False)

    @pytest.mark.asyncio
    async def test_rollback_last_migration_no_current(self, executor, mock_manager):
        mock_manager.get_current_revision = AsyncMock(return_value=None)
        with patch.object(executor, "_get_manager", new_callable=AsyncMock, return_value=mock_manager):
            result = await executor.rollback_last_migration()
            assert result["success"] is False
            assert "No current revision" in result["error"]

    @pytest.mark.asyncio
    async def test_rollback_last_migration_no_previous(self, executor, mock_manager):
        mock_manager.show_history = AsyncMock(return_value=[{"revision": "abc123"}])
        with patch.object(executor, "_get_manager", new_callable=AsyncMock, return_value=mock_manager):
            result = await executor.rollback_last_migration()
            assert result["success"] is False
            assert "No previous migration" in result["error"]

    # --- rollback_to_base ---
    @pytest.mark.asyncio
    async def test_rollback_to_base(self, executor):
        with patch.object(executor, "rollback", new_callable=AsyncMock) as mock_rollback:
            mock_rollback.return_value = {"success": True}
            result = await executor.rollback_to_base(dry_run=True)
            assert result["success"] is True
            mock_rollback.assert_awaited_once_with("base", True)

    # --- get_rollback_history ---
    @pytest.mark.asyncio
    async def test_get_rollback_history(self, executor):
        executor._rollback_history = [{"a": 1}, {"b": 2}, {"c": 3}]
        result = await executor.get_rollback_history(limit=2)
        assert len(result) == 2
        assert result == [{"b": 2}, {"c": 3}]

    # --- list_backups ---
    @pytest.mark.asyncio
    async def test_list_backups(self, executor):
        mock_files = [
            MagicMock(spec=Path, name="pre_rollback_20250101.sql"),
            MagicMock(spec=Path, name="pre_rollback_20250102.sql"),
        ]
        executor._backup_dir.glob = MagicMock(return_value=mock_files)
        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            mock_to_thread.side_effect = [
                (1024, 1234567890.0),
                (2048, 1234567891.0),
            ]
            backups = await executor.list_backups()
            assert len(backups) == 2
            assert backups[0]["filename"] == "pre_rollback_20250101.sql"
            assert backups[0]["size_bytes"] == 1024

    # --- delete_backup ---
    @pytest.mark.asyncio
    async def test_delete_backup_exists(self, executor):
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        with patch("pathlib.Path", return_value=mock_path):
            with patch.object(executor, "_delete_file", new_callable=AsyncMock) as mock_delete:
                result = await executor.delete_backup("backup.sql")
                assert result is True
                mock_delete.assert_awaited_once_with(mock_path, ignore_missing=True)

    @pytest.mark.asyncio
    async def test_delete_backup_not_exists(self, executor):
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = False
        with patch("pathlib.Path", return_value=mock_path):
            result = await executor.delete_backup("backup.sql")
            assert result is False


# ============================================================================
# Tests for get_rollback_executor singleton
# ============================================================================

@pytest.mark.asyncio
async def test_get_rollback_executor():
    with patch(
        "infrastructure.database.migration_rollback_executor.MigrationRollbackExecutor"
    ) as mock_cls:
        mock_cls.return_value = "executor"
        result1 = await get_rollback_executor()
        result2 = await get_rollback_executor()
        assert result1 == "executor"
        assert result2 == "executor"
        mock_cls.assert_called_once()


# ============================================================================
# CLI tests (smoke)
# ============================================================================

def test_cli_smoke():
    """Test that cli() doesn't raise when called with no args (it shows help)."""
    with patch("argparse.ArgumentParser") as mock_parser:
        mock_parser.return_value.parse_args = MagicMock()
        mock_parser.return_value.parse_args.return_value = MagicMock(command="rollback", revision="head-1", dry_run=False, no_backup=False, backup_name=None)
        # mock asyncio.run to avoid actually running
        with patch("asyncio.run") as mock_run:
            cli()
            # No assertion needed, just ensure no exception
            # We can also check that asyncio.run was called
            assert mock_run.call_count > 0