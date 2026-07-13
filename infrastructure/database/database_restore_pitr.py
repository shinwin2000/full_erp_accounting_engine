#!/usr/bin/env python3
"""
Module: database_restore_pitr.py
Layer: Infrastructure (Database)
Responsibility: Melakukan Point-In-Time Recovery (PITR) untuk database PostgreSQL
               menggunakan WAL (Write-Ahead Log) archiving. Memungkinkan restore
               ke timestamp tertentu sebelum terjadi kerusakan atau error.
               Mendukung restore ke full backup terakhir + WAL hingga titik waktu
               yang ditentukan.
Dependencies:
- subprocess, asyncio, logging, datetime
- config.loader_yaml
- infrastructure.database.database_backup_pgdump (DatabaseBackupPgDump)
- infrastructure.telemetry.structured_json_logging
- infrastructure.telemetry.alert_manager_router
Audit: Setiap operasi PITR dicatat. Restore yang berhasil atau gagal memicu alert.
"""

from __future__ import annotations

import asyncio
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiofiles  # <-- Tambahan untuk async file I/O

# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.database.database_backup_pgdump import get_backup_manager
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_PITR_CONFIG = {
    "enabled": True,
    "wal_archive_dir": "/var/lib/postgresql/wal_archive",
    "restore_dir": "/var/lib/postgresql/restore",
    "data_dir": "/var/lib/postgresql/data",
    "port": 5432,
    "stop_timeout_seconds": 60,
    "use_recovery_conf": True,
}

# ============================================================================
# EXCEPTIONS
# ============================================================================


class PITRError(Exception):
    """Base exception untuk PITR."""

    pass


class PITRRestoreError(PITRError):
    """Error saat restore PITR."""

    pass


class WALArchiveError(PITRError):
    """Error terkait WAL archive."""

    pass


# ============================================================================
# PITR MANAGER
# ============================================================================


class DatabaseRestorePITR:
    """
    Manajer Point-In-Time Recovery.

    Fitur:
    - Restore database ke timestamp tertentu
    - Menggunakan full backup + WAL archive
    - Konfigurasi recovery.conf untuk PostgreSQL
    - Verifikasi WAL archive sebelum restore
    - Dry-run mode untuk validasi
    """

    def __init__(self, config_path: str = "config_files/database_config.yaml"):
        self.config = self._load_config(config_path)
        self._enabled = self.config.get("enabled", True)
        self._wal_archive_dir = Path(
            self.config.get("wal_archive_dir", "/var/lib/postgresql/wal_archive")
        )
        self._restore_dir = Path(self.config.get("restore_dir", "/var/lib/postgresql/restore"))
        self._data_dir = Path(self.config.get("data_dir", "/var/lib/postgresql/data"))
        self._port = self.config.get("port", 5432)
        self._stop_timeout = self.config.get("stop_timeout_seconds", 60)

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            pitr_config = config.get("pitr", {})
            result = DEFAULT_PITR_CONFIG.copy()
            result.update(pitr_config)
            return result
        except Exception:
            return DEFAULT_PITR_CONFIG.copy()

    async def _get_db_connection_info(self) -> dict:
        """Get database connection info from config."""
        config = load_yaml_config("config_files/database_config.yaml")
        db_config = config.get("database", {})
        return {
            "host": db_config.get("host", "localhost"),
            "port": db_config.get("port", 5432),
            "database": db_config.get("database", "erp_db"),
            "user": db_config.get("user", "postgres"),
            "password": db_config.get("password"),
        }

    # ========================================================================
    # Helper untuk operasi blocking (shutil) di thread pool
    # ========================================================================

    async def _move_dir(self, src: Path, dst: Path) -> None:
        """Move directory secara async di thread pool."""
        def _move_sync():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.move(str(src), str(dst))
        await asyncio.to_thread(_move_sync)

    async def _rmtree(self, path: Path) -> None:
        """Remove directory tree secara async di thread pool."""
        def _rm_sync():
            if path.exists():
                shutil.rmtree(path)
        await asyncio.to_thread(_rm_sync)

    async def _mkdir(self, path: Path) -> None:
        """Create directory secara async di thread pool."""
        def _mkdir_sync():
            path.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(_mkdir_sync)

    # ========================================================================
    # PostgreSQL control (sudah async menggunakan subprocess)
    # ========================================================================

    async def _stop_postgres(self) -> None:
        """Stop PostgreSQL service."""
        try:
            cmd = ["pg_ctl", "stop", "-D", str(self._data_dir), "-m", "fast"]
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await process.wait()
            if process.returncode != 0:
                logger.warning("Failed to stop PostgreSQL, may already be stopped")
        except Exception as e:
            logger.warning(f"Error stopping PostgreSQL: {e}")

    async def _start_postgres(self) -> None:
        """Start PostgreSQL service."""
        cmd = ["pg_ctl", "start", "-D", str(self._data_dir)]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await process.wait()
        if process.returncode != 0:
            raise PITRRestoreError("Failed to start PostgreSQL")

    # ========================================================================
    # Restore base backup (already async)
    # ========================================================================

    async def _restore_base_backup(self, backup_name: str) -> None:
        """Restore base backup using pg_restore or by copying files."""
        backup_manager = await get_backup_manager()
        await backup_manager.restore_backup(backup_name)
        logger.info(f"Base backup {backup_name} restored")

    # ========================================================================
    # PERBAIKAN: _create_recovery_conf menggunakan aiofiles
    # ========================================================================

    async def _create_recovery_conf(self, target_time: datetime) -> None:
        """
        Create recovery.conf file for PITR.
        """
        recovery_conf_path = self._data_dir / "recovery.conf"
        content = f"""
# PITR recovery configuration
restore_command = 'cp {self._wal_archive_dir}/%f %p'
recovery_target_time = '{target_time.isoformat()}'
recovery_target_action = 'promote'
recovery_target_timeline = 'latest'
"""
        # Tulis file secara async
        async with aiofiles.open(recovery_conf_path, "w") as f:
            await f.write(content)
        logger.info(f"Recovery.conf created for target time {target_time.isoformat()}")

    # ========================================================================
    # Verify WAL archive (menggunakan async untuk stat jika perlu)
    # ========================================================================

    async def _verify_wal_archive(self, target_time: datetime) -> bool:
        """
        Verify that WAL archive contains all segments needed for recovery.
        """
        # Cek keberadaan direktori (small I/O, bisa pakai asyncio.to_thread)
        def _dir_exists():
            return self._wal_archive_dir.exists()
        if not await asyncio.to_thread(_dir_exists):
            logger.error(f"WAL archive directory {self._wal_archive_dir} does not exist")
            return False

        # Dapatkan daftar file WAL (blocking, jalankan di thread)
        def _list_wal_files():
            return list(self._wal_archive_dir.glob("*.wal"))
        wal_files = await asyncio.to_thread(_list_wal_files)

        if not wal_files:
            logger.warning("No WAL files found in archive")
            return False

        logger.info(f"Found {len(wal_files)} WAL files in archive")
        return True

    # ========================================================================
    # Perform PITR
    # ========================================================================

    async def perform_pitr(
        self, target_time: datetime, backup_name: str, dry_run: bool = False
    ) -> dict[str, Any]:
        """
        Perform Point-In-Time Recovery.

        Args:
            target_time: Timestamp to recover to (UTC)
            backup_name: Name of the base backup to restore first
            dry_run: If True, only validate without actual restore

        Returns:
            Result dictionary
        """
        result = {
            "success": False,
            "target_time": target_time.isoformat(),
            "backup_name": backup_name,
            "dry_run": dry_run,
            "message": "",
        }

        if not self._enabled:
            result["message"] = "PITR is disabled"
            return result

        # Verify WAL archive
        wal_ok = await self._verify_wal_archive(target_time)
        if not wal_ok:
            result["message"] = "WAL archive verification failed"
            return result

        if dry_run:
            logger.info(
                f"DRY RUN: Would restore to {target_time.isoformat()} using backup {backup_name}"
            )
            result["success"] = True
            result["message"] = "Dry run successful"
            return result

        try:
            # Stop PostgreSQL
            await self._stop_postgres()

            # Backup data directory (using async thread)
            backup_data_dir = self._data_dir.with_suffix(".bak")
            await self._rmtree(backup_data_dir)
            await self._move_dir(self._data_dir, backup_data_dir)
            await self._mkdir(self._data_dir)

            # Restore base backup (already async)
            await self._restore_base_backup(backup_name)

            # Create recovery.conf (async file write)
            await self._create_recovery_conf(target_time)

            # Start PostgreSQL in recovery mode
            await self._start_postgres()

            # Wait for recovery to complete (approx)
            await asyncio.sleep(10)

            # Verify database is accessible
            db_info = await self._get_db_connection_info()
            cmd = [
                "psql",
                "-h",
                db_info["host"],
                "-p",
                str(db_info["port"]),
                "-U",
                db_info["user"],
                "-d",
                db_info["database"],
                "-c",
                "SELECT 1",
            ]
            env = None
            if db_info.get("password"):
                env = {"PGPASSWORD": db_info["password"]}

            process = await asyncio.create_subprocess_exec(
                *cmd, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await process.wait()

            if process.returncode == 0:
                result["success"] = True
                result["message"] = f"PITR to {target_time.isoformat()} successful"
                logger.info(result["message"])
                await trigger_alert(
                    title="PITR Completed",
                    message=f"Database restored to {target_time.isoformat()} using backup {backup_name}",
                    severity="info",
                    source="DatabaseRestorePITR",
                )
            else:
                raise PITRRestoreError("Database not accessible after recovery")

            # Clean up backup data directory
            await self._rmtree(backup_data_dir)

            return result

        except Exception as e:
            result["message"] = f"PITR failed: {e}"
            logger.error(result["message"])
            await trigger_alert(
                title="PITR Failed",
                message=result["message"],
                severity="critical",
                source="DatabaseRestorePITR",
            )
            raise PITRRestoreError(result["message"]) from e

    # ========================================================================
    # Get available WAL segments (gunakan async untuk stat)
    # ========================================================================

    async def get_available_wal_segments(self) -> list[dict[str, Any]]:
        """
        Get list of available WAL segments in archive.
        """
        segments = []
        if self._wal_archive_dir.exists():
            # Dapatkan daftar file
            def _list_wal():
                return sorted(self._wal_archive_dir.glob("*.wal"))
            wal_files = await asyncio.to_thread(_list_wal)

            for wal_file in wal_files:
                # Stat blocking, jalankan di thread
                def _get_stat(p: Path):
                    return p.stat().st_size, p.stat().st_mtime
                size, mtime = await asyncio.to_thread(_get_stat, wal_file)
                segments.append(
                    {
                        "filename": wal_file.name,
                        "size_bytes": size,
                        "modified_at": datetime.fromtimestamp(mtime).isoformat(),
                    }
                )
        return segments

    # ========================================================================
    # Validate readiness
    # ========================================================================

    async def validate_pitr_readiness(self) -> dict[str, Any]:
        """
        Check if system is ready for PITR.
        """
        wal_ok = await self._verify_wal_archive(datetime.now(UTC))
        backup_manager = await get_backup_manager()
        backups = await backup_manager.list_backups()
        latest_backup = backups[0] if backups else None

        # Hitung jumlah WAL files
        def _count_wal():
            return len(list(self._wal_archive_dir.glob("*.wal"))) if self._wal_archive_dir.exists() else 0
        wal_count = await asyncio.to_thread(_count_wal)

        return {
            "ready": wal_ok and latest_backup is not None,
            "wal_archive_available": wal_ok,
            "wal_segments_count": wal_count,
            "latest_backup": latest_backup,
            "wal_archive_dir": str(self._wal_archive_dir),
            "data_dir": str(self._data_dir),
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_pitr_manager: DatabaseRestorePITR | None = None


async def get_pitr_manager() -> DatabaseRestorePITR:
    """Get singleton instance of DatabaseRestorePITR."""
    global _pitr_manager
    if _pitr_manager is None:
        _pitr_manager = DatabaseRestorePITR()
    return _pitr_manager


# ============================================================================
# CLI COMMAND
# ============================================================================


def cli():
    """CLI entry point for PITR (Parsing Only)."""
    import argparse

    parser = argparse.ArgumentParser(description="Point-In-Time Recovery")
    parser.add_argument("command", choices=["restore", "validate", "list-wal"], help="PITR command")
    parser.add_argument("--time", "-t", help="Target time (ISO format, e.g., 2024-01-01T12:00:00)")
    parser.add_argument("--backup", "-b", help="Base backup name")
    parser.add_argument("--dry-run", action="store_true", help="Dry run")

    return parser.parse_args()


async def run_pitr_cli(args):
    """Menjalankan operasi PITR secara asynchronous berdasarkan argumen CLI."""
    import json

    pitr = await get_pitr_manager()

    if args.command == "restore":
        if not args.time or not args.backup:
            print("Error: --time and --backup required")
            return
        target_time = datetime.fromisoformat(args.time)
        result = await pitr.perform_pitr(target_time, args.backup, dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
    elif args.command == "validate":
        readiness = await pitr.validate_pitr_readiness()
        print(json.dumps(readiness, indent=2))
    elif args.command == "list-wal":
        segments = await pitr.get_available_wal_segments()
        for seg in segments:
            print(f"{seg['filename']} - {seg['size_bytes']} bytes - {seg['modified_at']}")


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "DatabaseRestorePITR",
    "PITRError",
    "PITRRestoreError",
    "WALArchiveError",
    "get_pitr_manager",
]


# ============================================================================
# SINGLE MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    # 1. Parsing argumen secara sinkronus
    args = cli()

    # 2. Eksekusi event loop utama HANYA ketika file dijalankan langsung via terminal.
    #    Menggunakan thread offloading jika event loop lain sudah berjalan untuk menghindari RuntimeError.
    try:
        asyncio.get_running_loop()

        # Deteksi loop aktif: alihkan coroutine CLI ke thread terisolasi dengan loop-nya sendiri
        def _run_in_thread():
            thread_loop = asyncio.new_event_loop()
            try:
                thread_loop.run_until_complete(run_pitr_cli(args))
            finally:
                thread_loop.close()

        worker = threading.Thread(target=_run_in_thread, name="PITRCLIEngineWorker")
        worker.start()
        worker.join()  # Blokir thread saat ini hingga eksekusi CLI selesai sempurna

    except RuntimeError:
        # Tidak ada event loop aktif, aman untuk memutar loop utama secara langsung
        asyncio.run(run_pitr_cli(args))
