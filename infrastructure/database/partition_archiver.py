#!/usr/bin/env python3
"""
Module: partition_archiver.py
Layer: Infrastructure (Database)
Responsibility: Mengarsipkan partisi lama ke cold storage (S3/Glacier) untuk
               mengurangi ukuran database aktif sambil tetap mempertahankan
               data untuk compliance. Mendukung detach partisi, kompresi,
               upload ke cold storage, dan kemampuan restore kembali.
Dependencies:
- asyncpg, asyncio, logging, subprocess
- infrastructure.database.session_factory_sqlalchemy (get_session_factory)
- infrastructure.file_storage.glacier_cold_storage_adapter (optional)
- config.loader_yaml
- infrastructure.telemetry.structured_json_logging
Audit: Setiap arsip partisi dicatat. Restore partisi juga dicatat.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# PERBAIKAN: import DropTable dari sqlalchemy.schema
from sqlalchemy import DDL, MetaData, Table
from sqlalchemy.schema import DropTable

from config.loader_yaml import load_yaml_config

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

# Optional file storage
try:
    from infrastructure.file_storage.glacier_cold_storage_adapter import (
        get_glacier_cold_storage_adapter,
    )
    from infrastructure.file_storage.s3_adapter import get_s3_storage_adapter

    FILE_STORAGE_AVAILABLE = True
except ImportError:
    FILE_STORAGE_AVAILABLE = False

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_ARCHIVE_CONFIG = {
    "enabled": True,
    "archive_after_days": 730,  # Archive partitions older than 2 years
    "archive_storage": "glacier",  # glacier, s3, local
    "archive_bucket": "erp-archive",
    "archive_prefix": "partitions/",
    "compress": True,
    "retain_local_backup_days": 7,
    "tables": [
        {
            "name": "ledger_entry",
            "partition_column": "posting_date",
            "archive_after_days": 730,
            "enabled": True,
        },
        {
            "name": "journal_line",
            "partition_column": "created_at",
            "archive_after_days": 365,
            "enabled": True,
        },
        {
            "name": "event_store",
            "partition_column": "timestamp",
            "archive_after_days": 3650,
            "enabled": True,
        },
    ],
}

# ============================================================================
# EXCEPTIONS
# ============================================================================


class PartitionArchiverError(Exception):
    """Base exception untuk partition archiver."""

    pass


class ArchiveCreateError(PartitionArchiverError):
    """Error saat membuat arsip."""

    pass


class ArchiveRestoreError(PartitionArchiverError):
    """Error saat restore arsip."""

    pass


# ============================================================================
# PARTITION ARCHIVER
# ============================================================================


class PartitionArchiver:
    """
    Archiver untuk partisi database.

    Fitur:
    - Detach partisi yang sudah tua
    - Ekspor data partisi ke file (pg_dump)
    - Kompresi file
    - Upload ke cold storage (S3/Glacier)
    - Restore partisi dari arsip
    - Metadata tracking untuk arsip
    """

    def __init__(self, config_path: str = "config_files/database_config.yaml"):
        self.config = self._load_config(config_path)
        self._archive_tables = self.config.get("tables", [])
        self._enabled = self.config.get("enabled", True)
        self._archive_storage = self.config.get("archive_storage", "glacier")
        self._archive_bucket = self.config.get("archive_bucket", "erp-archive")
        self._archive_prefix = self.config.get("archive_prefix", "partitions/")
        self._compress = self.config.get("compress", True)
        self._archive_metadata: dict[str, dict] = {}

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            archive_config = config.get("partition_archive", {})
            result = DEFAULT_ARCHIVE_CONFIG.copy()
            result.update(archive_config)
            return result
        except Exception:
            return DEFAULT_ARCHIVE_CONFIG.copy()

    async def _get_db_connection_info(self) -> dict:
        """Get database connection info from config."""
        from config.loader_yaml import load_yaml_config

        config = load_yaml_config("config_files/database_config.yaml")
        db_config = config.get("database", {})
        return {
            "host": db_config.get("host", "localhost"),
            "port": db_config.get("port", 5432),
            "database": db_config.get("database", "erp_db"),
            "user": db_config.get("user", "postgres"),
            "password": db_config.get("password"),
        }

    async def _get_old_partitions(self, table_config: dict) -> list[dict]:
        """
        Get list of partitions older than archive_after_days.
        """
        table_name = table_config["name"]
        archive_days = table_config.get(
            "archive_after_days", self.config.get("archive_after_days", 730)
        )
        cutoff_date = datetime.now(UTC) - timedelta(days=archive_days)

        session_factory = await get_session_factory()
        async with session_factory.get_session() as session:
            # Get partitions from pg_inherits - menggunakan parameter binding (aman)
            query = """
            SELECT 
                inhrelid::regclass::text as partition_name,
                pg_get_expr(c.relpartbound, inhrelid) as partition_range
            FROM pg_inherits
            JOIN pg_class c ON inhrelid = c.oid
            WHERE inhparent = :parent::regclass
            """
            result = await session.execute(query, {"parent": table_name})
            partitions = []
            for row in result:
                part_name = row[0]
                part_range = row[1]
                # Extract date from partition name or range
                try:
                    # Assume partition name format: table_YYYY_MM
                    if "_" in part_name:
                        part_date_str = part_name.split("_")[-1]  # YYYY_MM or YYYY_MM_DD
                        if len(part_date_str) == 7:  # YYYY_MM
                            part_date = datetime.strptime(part_date_str, "%Y_%m")
                        else:
                            part_date = datetime.strptime(part_date_str, "%Y_%m_%d")
                        if part_date < cutoff_date:
                            partitions.append(
                                {"name": part_name, "range": part_range, "date": part_date}
                            )
                except (ValueError, IndexError):
                    continue
            return partitions

    async def _detach_partition(self, table_name: str, partition_name: str) -> None:
        """
        Detach partition from parent table (convert to standalone).
        """
        session_factory = await get_session_factory()
        async with session_factory.get_session() as session, session.begin():
            # Menggunakan DDL dengan placeholder untuk menghindari concatenation
            stmt = DDL("ALTER TABLE %(table)s DETACH PARTITION %(partition)s")
            await session.execute(stmt, {"table": table_name, "partition": partition_name})
            logger.info(f"Detached partition {partition_name} from {table_name}")

    async def _export_partition(self, partition_name: str, output_path: Path) -> None:
        """
        Export partition data using pg_dump.
        """
        db_info = await self._get_db_connection_info()
        cmd = [
            "pg_dump",
            "-h",
            db_info["host"],
            "-p",
            str(db_info["port"]),
            "-U",
            db_info["user"],
            "-d",
            db_info["database"],
            "-t",
            partition_name,
            "-F",
            "c",  # custom format
            "-f",
            str(output_path),
            "--no-owner",
            "--no-privileges",
        ]

        env = None
        if db_info.get("password"):
            env = {"PGPASSWORD": db_info["password"]}

        process = await asyncio.create_subprocess_exec(
            *cmd, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise ArchiveCreateError(f"pg_dump failed: {stderr.decode()}")

        logger.info(f"Exported partition {partition_name} to {output_path}")

    async def _compress_file(self, file_path: Path) -> Path:
        """
        Compress file using gzip.
        """
        compressed_path = file_path.with_suffix(file_path.suffix + ".gz")
        with open(file_path, "rb") as f_in, gzip.open(compressed_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        logger.info(f"Compressed {file_path} to {compressed_path}")
        return compressed_path

    async def _upload_to_storage(self, file_path: Path, archive_key: str) -> str:
        """
        Upload file to configured cold storage.

        Returns:
            Storage URI
        """
        if not FILE_STORAGE_AVAILABLE:
            # Fallback: keep local file
            logger.warning("File storage not available, keeping local copy")
            return f"local://{file_path}"

        uri = None
        if self._archive_storage == "glacier":
            storage = await get_glacier_cold_storage_adapter()
            uri = await storage.upload(
                file_content=open(file_path, "rb"),
                file_name=file_path.name,
                metadata={"archive_key": archive_key},
            )
        elif self._archive_storage == "s3":
            storage = await get_s3_storage_adapter()
            uri = await storage.upload(
                file_content=open(file_path, "rb"),
                file_name=file_path.name,
                bucket=self._archive_bucket,
            )
        else:
            # Local storage
            archive_dir = Path("/var/archives")
            archive_dir.mkdir(parents=True, exist_ok=True)
            dest = archive_dir / file_path.name
            shutil.copy(file_path, dest)
            uri = f"local://{dest}"

        logger.info(f"Uploaded archive to {uri}")
        return uri

    async def _drop_partition(self, partition_name: str) -> None:
        """
        Drop partition after successful archiving.
        """
        session_factory = await get_session_factory()
        async with session_factory.get_session() as session, session.begin():
            # PERBAIKAN: Gunakan DDL untuk DROP TABLE IF EXISTS karena DropTable tidak selalu punya if_exists
            await session.execute(DDL(f"DROP TABLE IF EXISTS {partition_name}"))
            logger.info(f"Dropped partition {partition_name}")

    async def archive_partition(self, table_config: dict, partition: dict) -> dict[str, Any]:
        """
        Archive a single partition.

        Returns:
            Archive metadata
        """
        table_name = table_config["name"]
        partition_name = partition["name"]
        archive_key = f"{self._archive_prefix}{table_name}/{partition_name}.dump"

        result = {
            "partition": partition_name,
            "table": table_name,
            "status": "pending",
            "archive_uri": None,
            "error": None,
        }

        try:
            # Detach partition
            await self._detach_partition(table_name, partition_name)

            # Export data
            with tempfile.NamedTemporaryFile(suffix=".dump", delete=False) as tmp:
                dump_path = Path(tmp.name)
            await self._export_partition(partition_name, dump_path)

            # Compress if enabled
            file_to_upload = dump_path
            if self._compress:
                file_to_upload = await self._compress_file(dump_path)
                dump_path.unlink()  # Remove original uncompressed

            # Upload to storage
            uri = await self._upload_to_storage(file_to_upload, archive_key)
            result["archive_uri"] = uri

            # Drop partition from database
            await self._drop_partition(partition_name)

            # Clean up temp file
            file_to_upload.unlink()

            result["status"] = "archived"
            result["archived_at"] = datetime.now(UTC).isoformat()
            logger.info(f"Successfully archived partition {partition_name}")

            # Store metadata
            self._archive_metadata[archive_key] = result

        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            logger.error(f"Failed to archive partition {partition_name}: {e}")
            await trigger_alert(
                title="Partition Archive Failed",
                message=f"Failed to archive partition {partition_name}: {e}",
                severity="warning",
                source="PartitionArchiver",
            )

        return result

    async def archive_old_partitions(self, dry_run: bool = False) -> dict[str, Any]:
        """
        Archive all old partitions for all configured tables.

        Args:
            dry_run: If True, only report what would be archived

        Returns:
            Summary of archive operations
        """
        if not self._enabled:
            logger.info("Partition archiving is disabled")
            return {"enabled": False}

        results = {}
        for table_config in self._archive_tables:
            if not table_config.get("enabled", True):
                continue

            table_name = table_config["name"]
            partitions = await self._get_old_partitions(table_config)
            results[table_name] = {
                "partitions_found": len(partitions),
                "archived": [],
                "failed": [],
            }

            for partition in partitions:
                if dry_run:
                    results[table_name]["archived"].append(
                        {"partition": partition["name"], "dry_run": True}
                    )
                else:
                    archive_result = await self.archive_partition(table_config, partition)
                    if archive_result["status"] == "archived":
                        results[table_name]["archived"].append(archive_result)
                    else:
                        results[table_name]["failed"].append(archive_result)

        return results

    async def restore_partition(self, archive_key: str, target_table: str) -> bool:
        """
        Restore a partition from archive.

        Args:
            archive_key: Archive key from previous archive operation
            target_table: Table to restore partition to (must be parent table)

        Returns:
            True if restore successful
        """
        try:
            # Download from storage
            if self._archive_storage == "glacier":
                storage = await get_glacier_cold_storage_adapter()
                # For Glacier, need to initiate retrieval first
                # This is simplified; in production, handle async retrieval
                content = await storage.download(archive_key)
            elif self._archive_storage == "s3":
                storage = await get_s3_storage_adapter()
                content = await storage.download(archive_key)
            else:
                # Local file
                local_path = Path(archive_key.replace("local://", ""))
                with open(local_path, "rb") as f:
                    content = f.read()

            # Decompress if needed
            if archive_key.endswith(".gz"):
                content = gzip.decompress(content)

            # Save to temporary file
            with tempfile.NamedTemporaryFile(suffix=".dump", delete=False) as tmp:
                tmp.write(content)
                dump_path = Path(tmp.name)

            # Restore using pg_restore
            db_info = await self._get_db_connection_info()
            cmd = [
                "pg_restore",
                "-h",
                db_info["host"],
                "-p",
                str(db_info["port"]),
                "-U",
                db_info["user"],
                "-d",
                db_info["database"],
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                str(dump_path),
            ]

            env = None
            if db_info.get("password"):
                env = {"PGPASSWORD": db_info["password"]}

            process = await asyncio.create_subprocess_exec(
                *cmd, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise ArchiveRestoreError(f"pg_restore failed: {stderr.decode()}")

            dump_path.unlink()
            logger.info(f"Successfully restored partition from {archive_key}")
            return True

        except Exception as e:
            logger.error(f"Failed to restore partition: {e}")
            await trigger_alert(
                title="Partition Restore Failed",
                message=f"Failed to restore partition from {archive_key}: {e}",
                severity="error",
                source="PartitionArchiver",
            )
            return False

    async def list_archives(self, table_name: str | None = None) -> list[dict]:
        """
        List archived partitions.
        """
        archives = []
        for key, metadata in self._archive_metadata.items():
            if table_name and metadata.get("table") != table_name:
                continue
            archives.append(metadata)
        return archives

    async def get_archive_stats(self) -> dict[str, Any]:
        """
        Get archive statistics.
        """
        total_archived = sum(
            1 for m in self._archive_metadata.values() if m.get("status") == "archived"
        )
        return {
            "total_archives": len(self._archive_metadata),
            "successful_archives": total_archived,
            "failed_archives": len(self._archive_metadata) - total_archived,
            "tables_configured": len(self._archive_tables),
            "archive_storage": self._archive_storage,
            "archive_bucket": self._archive_bucket,
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_partition_archiver: PartitionArchiver | None = None


async def get_partition_archiver() -> PartitionArchiver:
    """Get singleton instance of PartitionArchiver."""
    global _partition_archiver
    if _partition_archiver is None:
        _partition_archiver = PartitionArchiver()
    return _partition_archiver


# ============================================================================
# CLI COMMAND
# ============================================================================


def cli():
    """CLI entry point for partition archiver."""
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Partition archiver")
    parser.add_argument(
        "command", choices=["archive", "list", "stats", "restore"], help="Archive command"
    )
    parser.add_argument("--table", "-t", help="Table name")
    parser.add_argument("--dry-run", action="store_true", help="Dry run")
    parser.add_argument("--archive-key", help="Archive key for restore")

    args = parser.parse_args()

    async def run():
        archiver = await get_partition_archiver()

        if args.command == "archive":
            result = await archiver.archive_old_partitions(dry_run=args.dry_run)
            print(json.dumps(result, indent=2, default=str))
        elif args.command == "list":
            archives = await archiver.list_archives(args.table)
            for a in archives:
                print(f"{a['partition']}: {a['status']} - {a.get('archive_uri', 'N/A')}")
        elif args.command == "stats":
            stats = await archiver.get_archive_stats()
            print(json.dumps(stats, indent=2))
        elif args.command == "restore":
            if not args.archive_key:
                print("Error: --archive-key required for restore")
                return
            success = await archiver.restore_partition(args.archive_key, args.table or "unknown")
            print(f"Restore {'successful' if success else 'failed'}")

    asyncio.run(run())


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "ArchiveCreateError",
    "ArchiveRestoreError",
    "PartitionArchiver",
    "PartitionArchiverError",
    "get_partition_archiver",
]

if __name__ == "__main__":
    cli()