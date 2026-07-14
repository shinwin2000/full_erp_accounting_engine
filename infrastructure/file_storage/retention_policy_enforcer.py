#!/usr/bin/env python3
"""
Module: retention_policy_enforcer.py
Layer: Infrastructure (File Storage)
Responsibility: Memastikan bahwa file yang disimpan (evidence, reports, backups)
               mematuhi kebijakan retensi yang telah ditentukan.
"""

from __future__ import annotations

import asyncio
import io
from datetime import UTC, datetime
from typing import Any

from config.loader_yaml import load_yaml_config

# Internal dependencies
from infrastructure.file_storage.abstract_port import FileStoragePort
from infrastructure.file_storage.glacier_cold_storage_adapter import (
    GlacierColdStorageAdapter,
    get_glacier_cold_storage_adapter,
)
from infrastructure.file_storage.minio_evidence_adapter import (
    get_minio_evidence_adapter,
)
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_RETENTION_POLICIES = {
    "evidence": {
        "min_retention_days": 2555,
        "max_retention_days": 3650,
        "action": "archive_to_cold",
    },
    "financial_report": {
        "min_retention_days": 2555,
        "max_retention_days": 3650,
        "action": "archive_to_cold",
    },
    "tax_report": {
        "min_retention_days": 3650,
        "max_retention_days": 3650,
        "action": "keep",
    },
    "audit_log": {
        "min_retention_days": 3650,
        "max_retention_days": 3650,
        "action": "keep",
    },
    "backup": {"min_retention_days": 90, "max_retention_days": 365, "action": "delete"},
    "temp": {"min_retention_days": 1, "max_retention_days": 7, "action": "delete"},
}

SCAN_INTERVAL_HOURS = 24

# ============================================================================
# EXCEPTIONS
# ============================================================================


class RetentionPolicyError(Exception):
    pass


class RetentionViolationError(RetentionPolicyError):
    pass


# ============================================================================
# RETENTION POLICY ENFORCER
# ============================================================================


class RetentionPolicyEnforcer:
    def __init__(self, config_path: str = "config_files/retention_config.yaml"):
        self.config = self._load_config(config_path)
        self._policies = self._load_policies()
        self._hot_storage: FileStoragePort | None = None
        self._cold_storage: GlacierColdStorageAdapter | None = None
        self._scan_task: asyncio.Task | None = None
        self._running = False
        self._compliance_log: list[dict] = []

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            return load_yaml_config(config_path)
        except Exception:
            return {}

    def _load_policies(self) -> dict[str, dict]:
        policies = self.config.get("retention_policies", {})
        result = DEFAULT_RETENTION_POLICIES.copy()
        result.update(policies)
        return result

    async def _get_hot_storage(self) -> FileStoragePort:
        if self._hot_storage is None:
            self._hot_storage = await get_minio_evidence_adapter()
        return self._hot_storage

    async def _get_cold_storage(self) -> GlacierColdStorageAdapter:
        if self._cold_storage is None:
            self._cold_storage = await get_glacier_cold_storage_adapter()
        return self._cold_storage

    def _parse_upload_date(self, metadata: dict) -> datetime | None:
        for key in ["uploaded_at", "created_at", "archived_at", "last_modified"]:
            if key in metadata:
                try:
                    return datetime.fromisoformat(metadata[key])
                except (ValueError, TypeError):
                    pass
        if "last_modified" in metadata:
            try:
                return datetime.fromisoformat(metadata["last_modified"])
            except (ValueError, TypeError):
                pass
        return None

    def _get_file_category(self, metadata: dict, uri: str) -> str:
        if "category" in metadata:
            return metadata["category"]
        if "report_type" in metadata:
            return metadata["report_type"]
        if "evidence" in uri:
            return "evidence"
        elif "report" in uri:
            return "financial_report"
        elif "backup" in uri:
            return "backup"
        elif "temp" in uri:
            return "temp"
        elif "audit" in uri:
            return "audit_log"
        return "evidence"

    async def enforce_policy_for_file(self, uri: str, metadata: dict[str, Any]) -> dict[str, Any]:
        upload_date = self._parse_upload_date(metadata)
        if not upload_date:
            logger.warning(f"Cannot determine upload date for {uri}, skipping")
            return {"action": "skipped", "reason": "no_date"}

        age_days = (datetime.now(UTC) - upload_date).days
        category = self._get_file_category(metadata, uri)
        policy = self._policies.get(category, self._policies["evidence"])

        result = {
            "uri": uri,
            "category": category,
            "age_days": age_days,
            "policy": policy,
            "action": "keep",
        }

        if age_days > policy.get("max_retention_days", float("inf")):
            action = policy.get("action", "delete")
            if action == "archive_to_cold":
                try:
                    hot_storage = await self._get_hot_storage()
                    cold_storage = await self._get_cold_storage()
                    content = await hot_storage.download(uri)
                    content_bytes = content.read()
                    cold_uri = await cold_storage.upload(
                        file_content=io.BytesIO(content_bytes),
                        file_name=uri.split("/")[-1],
                        metadata=metadata,
                    )
                    await hot_storage.delete(uri)
                    result["action"] = "archived_to_cold"
                    result["cold_uri"] = cold_uri
                    logger.info(f"File {uri} archived to cold storage: {cold_uri}")
                except Exception as e:
                    logger.error(f"Failed to archive {uri} to cold storage: {e}")
                    result["action"] = "archive_failed"
                    result["error"] = str(e)
            elif action == "delete":
                try:
                    storage = await self._get_hot_storage()
                    await storage.delete(uri)
                    result["action"] = "deleted"
                    logger.info(f"File {uri} deleted due to retention policy (age: {age_days} days)")
                except Exception as e:
                    logger.error(f"Failed to delete {uri}: {e}")
                    result["action"] = "delete_failed"
                    result["error"] = str(e)
            elif action == "keep":
                result["action"] = "kept"
                logger.debug(f"File {uri} kept (age: {age_days} days, policy: keep)")

        elif age_days < policy.get("min_retention_days", 0):
            result["action"] = "warning_min_not_reached"
            result["days_remaining"] = policy["min_retention_days"] - age_days
            logger.debug(f"File {uri} has {result['days_remaining']} days until minimum retention")

        self._compliance_log.append(result)
        if len(self._compliance_log) > 10000:
            self._compliance_log = self._compliance_log[-5000:]

        return result

    async def scan_and_enforce(self, prefix: str = "", dry_run: bool = False) -> dict[str, Any]:
        storage = await self._get_hot_storage()
        try:
            files = await storage.list_files(prefix=prefix, limit=10000)
            results = {
                "total_files_scanned": len(files),
                "actions": {
                    "kept": 0,
                    "deleted": 0,
                    "archived_to_cold": 0,
                    "skipped": 0,
                    "warning": 0,
                    "errors": 0,
                },
                "details": [],
            }

            for file_info in files:
                uri = file_info["uri"]
                metadata = await storage.get_metadata(uri)
                if dry_run:
                    upload_date = self._parse_upload_date(metadata)
                    age_days = (datetime.now(UTC) - upload_date).days if upload_date else None
                    category = self._get_file_category(metadata, uri)
                    policy = self._policies.get(category, self._policies["evidence"])
                    results["details"].append(
                        {
                            "uri": uri,
                            "category": category,
                            "age_days": age_days,
                            "would_action": "delete"
                            if age_days
                            and age_days > policy.get("max_retention_days", float("inf"))
                            else "keep",
                        }
                    )
                else:
                    result = await self.enforce_policy_for_file(uri, metadata)
                    results["details"].append(result)
                    if result["action"] in results["actions"]:
                        results["actions"][result["action"]] += 1
                    else:
                        results["actions"]["skipped"] += 1

            await self._generate_compliance_report(results)

            if results["actions"].get("deleted", 0) > 100:
                await trigger_alert(
                    title="Large Number of Files Deleted by Retention Policy",
                    message=f"{results['actions']['deleted']} files were deleted during retention scan",
                    severity="warning",
                    source="RetentionPolicyEnforcer",
                )

            return results

        except Exception as e:
            logger.error(f"Retention scan failed: {e}")
            raise RetentionPolicyError(f"Scan failed: {e}") from e

    async def start_periodic_scan(self, interval_hours: int = SCAN_INTERVAL_HOURS) -> None:
        if self._running:
            logger.warning("Periodic scan already running")
            return
        self._running = True
        self._scan_task = asyncio.create_task(self._scan_loop(interval_hours))
        logger.info(f"Retention policy enforcer started (scan every {interval_hours} hours)")

    async def _scan_loop(self, interval_hours: int) -> None:
        while self._running:
            try:
                await asyncio.sleep(interval_hours * 3600)
                await self.scan_and_enforce()
            except asyncio.CancelledError:
                logger.debug("Retention scan loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in retention scan: {e}")

    async def stop_periodic_scan(self) -> None:
        self._running = False
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                logger.debug("Retention scan task cancelled during stop")
            self._scan_task = None
        logger.info("Retention policy enforcer stopped")

    async def _generate_compliance_report(self, scan_results: dict) -> None:
        try:
            # Impor lokal
            from infrastructure.event_store.append_only_store import get_event_store
            store = await get_event_store()
            await store.append(
                stream_name="compliance_retention",
                event_data={
                    "scan_timestamp": datetime.now(UTC).isoformat(),
                    "total_files": scan_results["total_files_scanned"],
                    "deleted": scan_results["actions"].get("deleted", 0),
                    "archived": scan_results["actions"].get("archived_to_cold", 0),
                    "summary": scan_results["actions"],
                },
                event_type="retention.scan.completed",
                metadata={"source": "RetentionPolicyEnforcer"},
            )
        except Exception as e:
            logger.warning(f"Failed to generate compliance report: {e}")

    async def get_compliance_status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "policies": self._policies,
            "scan_interval_hours": SCAN_INTERVAL_HOURS,
            "compliance_log_size": len(self._compliance_log),
            "recent_violations": [
                log
                for log in self._compliance_log[-20:]
                if log.get("action") in ["deleted", "archived_to_cold"]
            ],
        }

    async def update_policy(self, category: str, policy: dict) -> None:
        self._policies[category] = policy
        logger.info(f"Retention policy updated for category: {category}")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_retention_enforcer: RetentionPolicyEnforcer | None = None

async def get_retention_policy_enforcer() -> RetentionPolicyEnforcer:
    global _retention_enforcer
    if _retention_enforcer is None:
        _retention_enforcer = RetentionPolicyEnforcer()
    return _retention_enforcer

async def get_retention_enforcer_dep():
    return await get_retention_policy_enforcer()

__all__ = [
    "RetentionPolicyEnforcer",
    "RetentionPolicyError",
    "RetentionViolationError",
    "get_retention_enforcer_dep",
    "get_retention_policy_enforcer",
]