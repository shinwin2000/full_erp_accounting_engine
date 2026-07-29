# tests/infrastructure/database/test_migration_rollback_executor.py
"""
Comprehensive tests for migration_rollback_executor.py.
Covers all public methods, error handling, backup/restore, and CLI.

Perbaikan pada file ini (dibanding versi sebelumnya) -- semuanya ditemukan
dengan benar-benar MENJALANKAN suite lama (bukan cuma membaca laporan
checker), yang menunjukkan 9 dari 32 test gagal total:

1. `_create_backup` dan `_restore_backup` mengimpor `load_yaml_config` secara
   LOKAL di dalam fungsinya (`from config.loader_yaml import load_yaml_config`),
   bukan di level modul. Akibatnya target patch lama,
   `"infrastructure.database.migration_rollback_executor.load_yaml_config"`,
   tidak pernah ada sebagai atribut modul itu -> `AttributeError` setiap kali.
   -> Diperbaiki: patch di sumber aslinya, `"config.loader_yaml.load_yaml_config"`.

2. `test_verify_integrity_*` men-set `factory.get_session = AsyncMock(...)`.
   Tapi source memanggilnya sebagai `async with factory.get_session() as session:`
   -- artinya `get_session()` sendiri dipanggil secara sinkron dan HASILnya yang
   harus berupa async context manager, bukan coroutine yang perlu di-await dulu.
   AsyncMock membuat `get_session()` mengembalikan coroutine, yang otomatis gagal
   dipakai sebagai `async with ...` ("coroutine object does not support the
   asynchronous context manager protocol").
   -> Diperbaiki dengan helper `_async_session_cm()` yang membuat context manager
      tiruan yang benar (`__aenter__`/`__aexit__` sebagai AsyncMock, tapi
      `get_session` sendiri adalah MagicMock biasa).

3. `test_rollback_failure_and_restore` mengharapkan
   `result["restored_from_backup"] is True`, tapi source hanya masuk ke jalur
   restore itu kalau `backup_path.exists()` -- dan test lama memakai
   `Path("/tmp/backup.sql")` sungguhan yang TIDAK PERNAH dibuat filenya.
   -> Diperbaiki memakai `tmp_path` dari pytest dan benar-benar menulis file
      dummy di sana, supaya `.exists()` mencerminkan kondisi nyata.

4. `test_list_backups` mencoba `executor._backup_dir.glob = MagicMock(...)`.
   `pathlib.Path` memakai `__slots__`, jadi instance atributnya read-only --
   assignment ini langsung `AttributeError`.
   `test_delete_backup_exists`/`test_delete_backup_not_exists` mencoba
   `patch("pathlib.Path", return_value=mock_path)`, tapi source membentuk path
   lewat operator `self._backup_dir / filename` (bukan memanggil `Path(...)`
   secara langsung), sehingga patch itu tidak pernah benar-benar dipakai --
   test itu lulus tapi bukan karena alasan yang benar (mengecek filesystem asli
   secara kebetulan).
   -> Diperbaiki dengan tidak memock `pathlib` sama sekali: constructor
      `MigrationRollbackExecutor()` sekarang diarahkan ke direktori sungguhan
      (`tmp_path`) lewat fixture `executor`, lalu file backup dibuat/hapus
      sungguhan di situ. Ini juga jadi lebih realistis daripada mocking stdlib.

5. Konstruktor `MigrationRollbackExecutor.__init__` memanggil
   `self._backup_dir.mkdir(parents=True, exist_ok=True)` memakai
   `ROLLBACK_BACKUP_DIR = Path("/var/backups/migration_rollbacks")` yang
   di-hardcode. Tanpa isolasi, tiap test yang membuat instance executor akan
   mencoba membuat direktori itu di filesystem sungguhan tempat test
   dijalankan -- bisa gagal dengan PermissionError di mesin/CI yang tidak
   berjalan sebagai root. Fixture `executor` sekarang me-monkeypatch
   `ROLLBACK_BACKUP_DIR` ke `tmp_path` SEBELUM membuat instance, sehingga
   semua test terisolasi dan tidak menyentuh `/var/backups/...` sungguhan.

Tambahan cakupan (fungsi/skenario yang sebelumnya tidak diuji sama sekali):
- `_verify_integrity`: kegagalan saat query `journal_header` dan kegagalan
  tak terduga saat mengambil session factory (sebelumnya hanya jalur sukses
  dan jalur "tabel hilang" yang diuji).
- Keamanan retry/idempotensi `rollback_last_migration` dan `rollback_to_base`
  saat dipanggil dua kali berturut-turut -- relevan karena ini operasi yang
  wajar untuk di-retry oleh operator kalau CLI terputus di tengah jalan.
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
# Helpers
# ============================================================================


def _async_session_cm(session):
    """Build a stand-in for `factory.get_session()`.

    The source calls it as `async with factory.get_session() as session:`,
    which means `get_session()` itself must be a *plain* (synchronous) call
    that returns an async context manager -- not a coroutine to await first.
    """
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ============================================================================
# Exceptions tests
# ============================================================================


class TestExceptions:
    @pytest.mark.parametrize(
        "exc_cls",
        [MigrationRollbackError, RollbackFailedError, BackupCreationError],
        ids=["migration_rollback_error", "rollback_failed_error", "backup_creation_error"],
    )
    def test_can_be_raised_and_caught(self, exc_cls):
        with pytest.raises(exc_cls):
            raise exc_cls("test")

    @pytest.mark.parametrize(
        "exc_cls",
        [RollbackFailedError, BackupCreationError],
        ids=["rollback_failed_error", "backup_creation_error"],
    )
    def test_is_subclass_of_migration_rollback_error(self, exc_cls):
        assert issubclass(exc_cls, MigrationRollbackError)


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
def executor(tmp_path, monkeypatch):
    # Isolate the executor's backup directory to a real, writable temp dir
    # instead of the hardcoded `/var/backups/migration_rollbacks` -- avoids
    # touching the real filesystem and avoids PermissionError on machines
    # that aren't running as root.
    monkeypatch.setattr(
        "infrastructure.database.migration_rollback_executor.ROLLBACK_BACKUP_DIR",
        tmp_path,
    )
    return MigrationRollbackExecutor()


# ============================================================================
# Tests for MigrationRollbackExecutor
# ============================================================================


class TestMigrationRollbackExecutor:
    @pytest.mark.asyncio
    async def test_initialization(self, executor, tmp_path):
        assert executor._backup_dir == tmp_path
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
            assert mock_to_thread.await_count == 1
            mock_to_thread.assert_awaited_once()
            # unlink is called inside the thread, so not directly called here
            mock_path.unlink.assert_not_called()

    # --- _create_backup ---
    @pytest.mark.asyncio
    async def test_create_backup_success(self, executor):
        with patch("config.loader_yaml.load_yaml_config") as mock_load:
            mock_load.return_value = {
                "database": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "testdb",
                    "user": "testuser",
                    "password": "pass",
                }
            }
            async def fake_pg_dump(cmd, env=None):
                # Real pg_dump writes the output file at the `-f` path; the
                # source then calls `backup_path.stat()` on it, so the fake
                # must actually create it too.
                Path(cmd[cmd.index("-f") + 1]).write_bytes(b"fake-dump")
                return (0, "success", "")

            with patch.object(executor, "_run_subprocess", side_effect=fake_pg_dump):
                backup_path = await executor._create_backup("test description")
                assert isinstance(backup_path, Path)
                assert "pre_rollback" in backup_path.name
                assert backup_path.parent == executor._backup_dir
                assert backup_path.exists()

    @pytest.mark.asyncio
    async def test_create_backup_failure(self, executor):
        with patch("config.loader_yaml.load_yaml_config") as mock_load:
            mock_load.return_value = {"database": {}}
            with patch.object(executor, "_run_subprocess", new_callable=AsyncMock) as mock_run:
                mock_run.return_value = (1, "", "pg_dump error")
                with pytest.raises(BackupCreationError, match="pg_dump failed"):
                    await executor._create_backup("test")

    # --- _restore_backup ---
    @pytest.mark.parametrize(
        "run_result, expected",
        [
            ((0, "success", ""), True),
            ((1, "", "restore error"), False),
        ],
        ids=["success", "failure"],
    )
    @pytest.mark.asyncio
    async def test_restore_backup(self, executor, run_result, expected):
        with patch("config.loader_yaml.load_yaml_config") as mock_load:
            mock_load.return_value = {"database": {}}
            with patch.object(executor, "_run_subprocess", new_callable=AsyncMock) as mock_run:
                mock_run.return_value = run_result
                result = await executor._restore_backup(Path("/tmp/backup.sql"))
                assert result is expected

    # --- _verify_integrity ---
    @pytest.mark.asyncio
    async def test_verify_integrity_success(self, executor):
        with patch(
            "infrastructure.database.migration_rollback_executor.get_session_factory",
            new_callable=AsyncMock
        ) as mock_get_factory:
            session = AsyncMock()
            session.bind = MagicMock()
            inspector = AsyncMock()
            inspector.get_table_names = AsyncMock(return_value=[
                "legal_entity", "account", "journal_header", "journal_line"
            ])
            session.execute = AsyncMock()
            session.execute.return_value = MagicMock()
            session.execute.return_value.scalar = MagicMock(return_value=5)

            factory = MagicMock()
            factory.get_session = MagicMock(return_value=_async_session_cm(session))
            mock_get_factory.return_value = factory

            with patch("sqlalchemy.inspect", return_value=inspector):
                result = await executor._verify_integrity()
                assert result is True

    @pytest.mark.asyncio
    async def test_verify_integrity_missing_tables(self, executor):
        with patch(
            "infrastructure.database.migration_rollback_executor.get_session_factory",
            new_callable=AsyncMock
        ) as mock_get_factory:
            session = AsyncMock()
            session.bind = MagicMock()
            inspector = AsyncMock()
            inspector.get_table_names = AsyncMock(return_value=["legal_entity"])

            factory = MagicMock()
            factory.get_session = MagicMock(return_value=_async_session_cm(session))
            mock_get_factory.return_value = factory

            with patch("sqlalchemy.inspect", return_value=inspector):
                result = await executor._verify_integrity()
                assert result is False

    @pytest.mark.asyncio
    async def test_verify_integrity_query_failure(self, executor):
        """Core tables all present, but the row-count query itself fails."""
        with patch(
            "infrastructure.database.migration_rollback_executor.get_session_factory",
            new_callable=AsyncMock
        ) as mock_get_factory:
            session = AsyncMock()
            session.bind = MagicMock()
            inspector = AsyncMock()
            inspector.get_table_names = AsyncMock(return_value=[
                "legal_entity", "account", "journal_header", "journal_line"
            ])
            session.execute = AsyncMock(side_effect=Exception("connection reset"))

            factory = MagicMock()
            factory.get_session = MagicMock(return_value=_async_session_cm(session))
            mock_get_factory.return_value = factory

            with patch("sqlalchemy.inspect", return_value=inspector):
                result = await executor._verify_integrity()
                assert result is False

    @pytest.mark.asyncio
    async def test_verify_integrity_session_factory_unavailable(self, executor):
        """Getting the session factory itself raises -- must not propagate."""
        with patch(
            "infrastructure.database.migration_rollback_executor.get_session_factory",
            new_callable=AsyncMock,
            side_effect=Exception("db unreachable"),
        ):
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
    async def test_rollback_success_with_backup(self, executor, mock_manager, tmp_path):
        backup_path = tmp_path / "backup.sql"
        with patch.object(executor, "_get_manager", new_callable=AsyncMock, return_value=mock_manager):
            with patch.object(executor, "_create_backup", new_callable=AsyncMock, return_value=backup_path):
                with patch.object(executor, "_verify_integrity", new_callable=AsyncMock, return_value=True):
                    result = await executor.rollback("head-1", dry_run=False, create_backup=True)
                    assert result["success"] is True
                    assert result["backup_path"] == str(backup_path)
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
    async def test_rollback_failure_and_restore(self, executor, mock_manager, tmp_path):
        # A real file so `backup_path.exists()` genuinely reflects reality --
        # the previous version used a `/tmp/backup.sql` Path that was never
        # actually created, so the restore branch this test claims to cover
        # was never reached.
        backup_path = tmp_path / "backup.sql"
        backup_path.write_text("-- dummy backup --")

        mock_manager.downgrade = AsyncMock(side_effect=Exception("downgrade failed"))
        with patch.object(executor, "_get_manager", new_callable=AsyncMock, return_value=mock_manager):
            with patch.object(executor, "_create_backup", new_callable=AsyncMock, return_value=backup_path):
                with patch.object(executor, "_restore_backup", new_callable=AsyncMock, return_value=True) as mock_restore:
                    result = await executor.rollback("head-1", dry_run=False, create_backup=True)
                    assert result["success"] is False
                    assert "downgrade failed" in result["error"]
                    assert result.get("restored_from_backup") is True
                    mock_restore.assert_awaited_once_with(backup_path)

    @pytest.mark.asyncio
    async def test_rollback_failure_restore_also_fails(self, executor, mock_manager, tmp_path):
        """When both downgrade AND the safety-net restore fail, the result
        must not claim `restored_from_backup` and a critical alert should
        fire (previously untested failure-cascade path)."""
        backup_path = tmp_path / "backup.sql"
        backup_path.write_text("-- dummy backup --")

        mock_manager.downgrade = AsyncMock(side_effect=Exception("downgrade failed"))
        with patch.object(executor, "_get_manager", new_callable=AsyncMock, return_value=mock_manager):
            with patch.object(executor, "_create_backup", new_callable=AsyncMock, return_value=backup_path):
                with patch.object(executor, "_restore_backup", new_callable=AsyncMock, return_value=False):
                    with patch(
                        "infrastructure.database.migration_rollback_executor.trigger_alert",
                        new_callable=AsyncMock,
                    ) as mock_alert:
                        result = await executor.rollback("head-1", dry_run=False, create_backup=True)
                        assert result["success"] is False
                        assert result.get("restored_from_backup") is None
                        severities = [c.kwargs.get("severity") for c in mock_alert.await_args_list]
                        assert "critical" in severities

    @pytest.mark.asyncio
    async def test_rollback_integrity_failure(self, executor, mock_manager, tmp_path):
        backup_path = tmp_path / "backup.sql"
        with patch.object(executor, "_get_manager", new_callable=AsyncMock, return_value=mock_manager):
            with patch.object(executor, "_create_backup", new_callable=AsyncMock, return_value=backup_path):
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

    @pytest.mark.asyncio
    async def test_rollback_last_migration_called_twice_is_idempotent_safe(self, executor, mock_manager):
        """An operator whose CLI call times out may re-run the same rollback
        command. Calling `rollback_last_migration` twice in a row must be
        idempotent-safe: it must not error out or corrupt `_rollback_history`
        -- each call is independent and re-reads history/current-revision
        from the migration manager."""
        with patch.object(executor, "_get_manager", new_callable=AsyncMock, return_value=mock_manager):
            with patch.object(executor, "rollback", new_callable=AsyncMock) as mock_rollback:
                mock_rollback.return_value = {"success": True}
                first = await executor.rollback_last_migration(dry_run=False)
                second = await executor.rollback_last_migration(dry_run=False)
                assert first["success"] is True
                assert second["success"] is True
                assert mock_rollback.await_count == 2
                mock_rollback.assert_awaited_with("xyz789", False)

    # --- rollback_to_base ---
    @pytest.mark.asyncio
    async def test_rollback_to_base(self, executor):
        with patch.object(executor, "rollback", new_callable=AsyncMock) as mock_rollback:
            mock_rollback.return_value = {"success": True}
            result = await executor.rollback_to_base(dry_run=True)
            assert result["success"] is True
            mock_rollback.assert_awaited_once_with("base", True)

    @pytest.mark.asyncio
    async def test_rollback_to_base_called_twice_is_idempotent_safe(self, executor):
        """Same idempotency concern as rollback_last_migration: rolling back
        to base twice in a row should simply delegate twice, not raise or
        silently no-op on the second call."""
        with patch.object(executor, "rollback", new_callable=AsyncMock) as mock_rollback:
            mock_rollback.return_value = {"success": True}
            first = await executor.rollback_to_base(dry_run=True)
            second = await executor.rollback_to_base(dry_run=True)
            assert first["success"] is True
            assert second["success"] is True
            assert mock_rollback.await_count == 2

    # --- get_rollback_history ---
    @pytest.mark.asyncio
    async def test_get_rollback_history(self, executor):
        executor._rollback_history = [{"a": 1}, {"b": 2}, {"c": 3}]
        result = await executor.get_rollback_history(limit=2)
        assert len(result) == 2
        assert result == [{"b": 2}, {"c": 3}]

    # --- list_backups ---
    @pytest.mark.asyncio
    async def test_list_backups(self, executor, tmp_path):
        # Real files in a real (isolated) directory -- no need to mock
        # pathlib itself, which was the source of the previous failure
        # (Path instances use __slots__, so `.glob = MagicMock(...)` is
        # rejected outright).
        older = tmp_path / "pre_rollback_20250101_000000_older.sql"
        newer = tmp_path / "pre_rollback_20250102_000000_newer.sql"
        older.write_bytes(b"x" * 1024)
        newer.write_bytes(b"y" * 2048)

        backups = await executor.list_backups()

        assert len(backups) == 2
        by_name = {b["filename"]: b for b in backups}
        assert by_name[older.name]["size_bytes"] == 1024
        assert by_name[newer.name]["size_bytes"] == 2048
        # sorted newest-first by creation time
        assert backups[0]["created_at"] >= backups[1]["created_at"]

    @pytest.mark.asyncio
    async def test_list_backups_empty_directory(self, executor):
        assert await executor.list_backups() == []

    # --- delete_backup ---
    @pytest.mark.asyncio
    async def test_delete_backup_exists(self, executor, tmp_path):
        backup_file = tmp_path / "backup.sql"
        backup_file.write_text("dummy")

        result = await executor.delete_backup("backup.sql")

        assert result is True
        assert not backup_file.exists()

    @pytest.mark.asyncio
    async def test_delete_backup_not_exists(self, executor):
        result = await executor.delete_backup("does_not_exist.sql")
        assert result is False


# ============================================================================
# Tests for get_rollback_executor singleton
# ============================================================================


@pytest.mark.asyncio
async def test_get_rollback_executor():
    with patch(
        "infrastructure.database.migration_rollback_executor.MigrationRollbackExecutor"
    ) as mock_cls:
        # Reset the module-level singleton so this test doesn't depend on
        # whatever order other tests happened to run in.
        import infrastructure.database.migration_rollback_executor as mod
        mod._rollback_executor = None

        mock_cls.return_value = "executor"
        result1 = await get_rollback_executor()
        result2 = await get_rollback_executor()
        assert result1 == "executor"
        assert result2 == "executor"
        mock_cls.assert_called_once()

        mod._rollback_executor = None


# ============================================================================
# CLI tests (smoke)
# ============================================================================


def test_cli_smoke():
    """Test that cli() doesn't raise when invoked with parsed 'rollback' args."""
    with patch("argparse.ArgumentParser") as mock_parser:
        mock_parser.return_value.parse_args.return_value = MagicMock(
            command="rollback", revision="head-1", dry_run=False, no_backup=False, backup_name=None
        )
        with patch("asyncio.run") as mock_run:
            cli()
            assert mock_run.call_count > 0
            # asyncio.run is mocked out, so the `run()` coroutine it was given
            # is never actually awaited -- close it explicitly to avoid a
            # spurious "coroutine was never awaited" RuntimeWarning.
            mock_run.call_args.args[0].close()
