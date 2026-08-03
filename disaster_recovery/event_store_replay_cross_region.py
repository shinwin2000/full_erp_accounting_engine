#!/usr/bin/env python3
"""
Module: event_store_replay_cross_region.py
Layer: Disaster Recovery

Responsibility:
    Replay event store dari region utama ke region secondary (cross-region DR).
    Mendukung incremental replay, checkpoint di target region, verifikasi integritas,
    dan metrik replay (events per second, total duration, failed events).

Metode yang ditambahkan:
- Untuk ReplayCheckpoint: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk ReplayMetrics: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk CrossRegionEventStoreReplayer: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


# ============================================================================
# ReplayCheckpoint (dengan entity dasar)
# ============================================================================
@dataclass(kw_only=True)
class ReplayCheckpoint:
    stream_name: str
    last_event_id: UUID
    replayed_at: datetime
    region_source: str
    region_target: str
    last_event_sequence: int = 0
    total_events_replayed: int = 0
    checksum: str = ""

    # Fields untuk audit dan versioning
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._take_snapshot()
        if not self.checksum:
            object.__setattr__(self, "checksum", self._compute_checksum())

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "stream_name": self.stream_name,
                "last_event_sequence": self.last_event_sequence,
                "region_source": self.region_source,
                "region_target": self.region_target,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "stream_name": self.stream_name,
                "details": details,
            }
        )

    def _compute_checksum(self) -> str:
        data = f"{self.stream_name}:{self.last_event_sequence}:{self.last_event_id}:{self.replayed_at.isoformat()}"
        return hashlib.sha256(data.encode()).hexdigest()

    def to_dynamodb_item(self) -> dict:
        return {
            "pk": f"CHECKPOINT#{self.stream_name}",
            "sk": "LATEST",
            "last_sequence": self.last_event_sequence,
            "last_event_id": str(self.last_event_id),
            "replayed_at": self.replayed_at.isoformat(),
            "region_source": self.region_source,
            "region_target": self.region_target,
            "total_events_replayed": self.total_events_replayed,
            "checksum": self.checksum,
            "version": self._version,
        }

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.stream_name:
            errors.append("stream_name is required")
        if not self.last_event_id:
            errors.append("last_event_id is required")
        if self.last_event_sequence < 0:
            errors.append("last_event_sequence cannot be negative")
        if not self.region_source:
            errors.append("region_source is required")
        if not self.region_target:
            errors.append("region_target is required")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "stream_name": self.stream_name,
            "last_event_id": str(self.last_event_id),
            "replayed_at": self.replayed_at.isoformat(),
            "region_source": self.region_source,
            "region_target": self.region_target,
            "last_event_sequence": self.last_event_sequence,
            "total_events_replayed": self.total_events_replayed,
            "checksum": self.checksum,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReplayCheckpoint:
        instance = cls(
            stream_name=data["stream_name"],
            last_event_id=UUID(data["last_event_id"]),
            replayed_at=datetime.fromisoformat(data["replayed_at"]),
            region_source=data["region_source"],
            region_target=data["region_target"],
            last_event_sequence=data.get("last_event_sequence", 0),
            total_events_replayed=data.get("total_events_replayed", 0),
            checksum=data.get("checksum", ""),
        )
        instance._version = data.get("version", 1)
        return instance

    @classmethod
    def from_dynamodb_item(cls, item: dict) -> ReplayCheckpoint:
        instance = cls(
            stream_name=item["pk"].replace("CHECKPOINT#", ""),
            last_event_sequence=int(item["last_sequence"]),
            last_event_id=UUID(item["last_event_id"]),
            replayed_at=datetime.fromisoformat(item["replayed_at"]),
            region_source=item["region_source"],
            region_target=item["region_target"],
            total_events_replayed=int(item.get("total_events_replayed", 0)),
            checksum=item.get("checksum", ""),
        )
        instance._version = int(item.get("version", 1))
        return instance

    def clone(self) -> ReplayCheckpoint:
        new = ReplayCheckpoint(
            stream_name=self.stream_name,
            last_event_id=self.last_event_id,
            replayed_at=datetime.now(UTC),
            region_source=self.region_source,
            region_target=self.region_target,
            last_event_sequence=self.last_event_sequence,
            total_events_replayed=self.total_events_replayed,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source_stream": self.stream_name})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "stream_name": self.stream_name,
            "last_event_sequence": self.last_event_sequence,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ReplayCheckpoint:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# ReplayMetrics (dengan entity dasar)
# ============================================================================
@dataclass(kw_only=True)
class ReplayMetrics:
    stream_name: str
    total_events_read: int
    total_events_written: int
    failed_events: int
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    events_per_second: float
    checkpoint_updates: int

    # Fields untuk audit dan versioning
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "stream_name": self.stream_name,
                "total_events_written": self.total_events_written,
                "duration_seconds": self.duration_seconds,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "stream_name": self.stream_name,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.stream_name:
            errors.append("stream_name is required")
        if self.total_events_read < 0:
            errors.append("total_events_read cannot be negative")
        if self.total_events_written < 0:
            errors.append("total_events_written cannot be negative")
        if self.failed_events < 0:
            errors.append("failed_events cannot be negative")
        if self.duration_seconds < 0:
            errors.append("duration_seconds cannot be negative")
        if self.events_per_second < 0:
            errors.append("events_per_second cannot be negative")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "stream_name": self.stream_name,
            "total_events_read": self.total_events_read,
            "total_events_written": self.total_events_written,
            "failed_events": self.failed_events,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_seconds": self.duration_seconds,
            "events_per_second": self.events_per_second,
            "checkpoint_updates": self.checkpoint_updates,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReplayMetrics:
        instance = cls(
            stream_name=data["stream_name"],
            total_events_read=data["total_events_read"],
            total_events_written=data["total_events_written"],
            failed_events=data["failed_events"],
            start_time=datetime.fromisoformat(data["start_time"]),
            end_time=datetime.fromisoformat(data["end_time"]),
            duration_seconds=data["duration_seconds"],
            events_per_second=data["events_per_second"],
            checkpoint_updates=data["checkpoint_updates"],
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> ReplayMetrics:
        new = ReplayMetrics(
            stream_name=self.stream_name,
            total_events_read=self.total_events_read,
            total_events_written=self.total_events_written,
            failed_events=self.failed_events,
            start_time=self.start_time,
            end_time=self.end_time,
            duration_seconds=self.duration_seconds,
            events_per_second=self.events_per_second,
            checkpoint_updates=self.checkpoint_updates,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source_stream": self.stream_name})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "stream_name": self.stream_name,
            "total_events_written": self.total_events_written,
            "duration_seconds": self.duration_seconds,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ReplayMetrics:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# CrossRegionEventStoreReplayer Core (dengan entity dasar)
# ============================================================================
class CrossRegionEventStoreReplayer:
    """
    Replayer untuk event store antar region.
    """

    def __init__(
        self,
        source_region: str,
        target_region: str,
        source_table_name: str = "event_store",
        target_table_name: str = "event_store_replica",
        use_dynamodb: bool = True,
        use_s3_archive: bool = True,
        s3_bucket_archive: str | None = None,
        s3_prefix: str = "events/",
        batch_size: int = 100,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
    ):
        self.source_region = source_region
        self.target_region = target_region
        self.source_table_name = source_table_name
        self.target_table_name = target_table_name
        self.use_dynamodb = use_dynamodb
        self.use_s3_archive = use_s3_archive
        self.s3_bucket = s3_bucket_archive
        self.s3_prefix = s3_prefix.rstrip("/") + "/"
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.backoff = backoff_seconds

        self.dynamodb_source = (
            boto3.resource("dynamodb", region_name=source_region) if use_dynamodb else None
        )
        self.dynamodb_target = (
            boto3.resource("dynamodb", region_name=target_region) if use_dynamodb else None
        )
        self.table_source = (
            self.dynamodb_source.Table(source_table_name) if self.dynamodb_source else None
        )
        self.table_target = (
            self.dynamodb_target.Table(target_table_name) if self.dynamodb_target else None
        )
        self.s3_client = (
            boto3.client("s3", region_name=source_region)
            if (use_s3_archive and s3_bucket_archive)
            else None
        )

        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "source_region": self.source_region,
                "target_region": self.target_region,
                "source_table": self.source_table_name,
                "target_table": self.target_table_name,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    # ------------------------------------------------------------------------
    # Checkpoint Management
    # ------------------------------------------------------------------------
    def get_last_checkpoint(self, stream_name: str) -> ReplayCheckpoint | None:
        if not self.use_dynamodb:
            return None
        try:
            response = self.table_target.get_item(
                Key={"pk": f"CHECKPOINT#{stream_name}", "sk": "LATEST"}
            )
            item = response.get("Item")
            if item:
                cp = ReplayCheckpoint.from_dynamodb_item(item)
                if cp.checksum and cp.checksum != cp._compute_checksum():
                    logger.warning(f"Checkpoint checksum mismatch for {stream_name}, ignoring")
                    return None
                return cp
        except ClientError as e:
            logger.error(f"Failed to get checkpoint for {stream_name}: {e}")
        return None

    def save_checkpoint(self, checkpoint: ReplayCheckpoint) -> bool:
        if not self.use_dynamodb:
            return False
        try:
            item = checkpoint.to_dynamodb_item()
            self.table_target.put_item(Item=item)
            logger.info(
                f"Checkpoint saved for {checkpoint.stream_name} at sequence {checkpoint.last_event_sequence}"
            )
            self._record_audit(
                "SAVE_CHECKPOINT",
                "system",
                {"stream_name": checkpoint.stream_name, "sequence": checkpoint.last_event_sequence},
            )
            return True
        except ClientError as e:
            logger.error(f"Failed to save checkpoint: {e}")
            return False

    # ------------------------------------------------------------------------
    # Event Query from Source
    # ------------------------------------------------------------------------
    def _query_events_from_dynamodb(
        self, stream_name: str, start_sequence: int = 0, limit: int = 100
    ) -> list[dict]:
        try:
            response = self.table_source.query(
                IndexName="stream_sequence_index",
                KeyConditionExpression=Key("stream_name").eq(stream_name)
                & Key("sequence").gte(start_sequence),
                Limit=limit,
                ScanIndexForward=True,
            )
            return response.get("Items", [])
        except ClientError:
            logger.warning(f"GSI not available, using scan for {stream_name}")
            response = self.table_source.scan(
                FilterExpression="stream_name = :sn AND sequence >= :seq",
                ExpressionAttributeValues={":sn": stream_name, ":seq": start_sequence},
                Limit=limit,
            )
            return response.get("Items", [])

    def _query_events_from_s3(
        self, stream_name: str, start_sequence: int = 0, limit: int = 100
    ) -> list[dict]:
        if not self.s3_client:
            return []
        events = []
        prefix = f"{self.s3_prefix}{stream_name}/"
        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.s3_bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    response = self.s3_client.get_object(Bucket=self.s3_bucket, Key=key)
                    data = json.loads(response["Body"].read().decode())
                    batch_events = data.get("events", [])
                    batch_events = [
                        e for e in batch_events if e.get("sequence", 0) >= start_sequence
                    ]
                    events.extend(batch_events)
                    if len(events) >= limit:
                        break
                if len(events) >= limit:
                    break
        except Exception as e:
            logger.error(f"Failed to read from S3 for {stream_name}: {e}")
        return sorted(events, key=lambda e: e["sequence"])[:limit]

    def _query_events_from_source(
        self, stream_name: str, start_sequence: int = 0, limit: int = 100
    ) -> list[dict]:
        if self.use_dynamodb:
            events = self._query_events_from_dynamodb(stream_name, start_sequence, limit)
            if events:
                return events
        if self.use_s3_archive and self.s3_bucket:
            return self._query_events_from_s3(stream_name, start_sequence, limit)
        return []

    # ------------------------------------------------------------------------
    # Write to Target
    # ------------------------------------------------------------------------
    def _write_batch_to_target(self, stream_name: str, events: list[dict]) -> tuple[int, int]:
        if not self.table_target:
            return 0, len(events)
        written = 0
        failed = 0
        with self.table_target.batch_writer() as batch:
            for ev in events:
                try:
                    item = {
                        "pk": f"EVENT#{stream_name}",
                        "sk": str(ev["sequence"]),
                        "event_id": ev["event_id"],
                        "event_type": ev["event_type"],
                        "payload": json.dumps(ev.get("payload", {})),
                        "timestamp": ev.get("timestamp", datetime.now(UTC).isoformat()),
                        "version": ev.get("version", 1),
                    }
                    batch.put_item(Item=item)
                    written += 1
                except Exception as e:
                    logger.error(f"Failed to write event {ev.get('event_id')}: {e}")
                    failed += 1
        return written, failed

    # ------------------------------------------------------------------------
    # Main Replay Logic
    # ------------------------------------------------------------------------
    def replay_stream(
        self,
        stream_name: str,
        limit: int | None = None,
        batch_size: int | None = None,
        dry_run: bool = False,
    ) -> ReplayMetrics:
        start_time = datetime.now(UTC)
        checkpoint = self.get_last_checkpoint(stream_name)
        start_seq = checkpoint.last_event_sequence + 1 if checkpoint else 0
        batch_sz = batch_size or self.batch_size
        total_read = 0
        total_written = 0
        total_failed = 0
        checkpoint_updates = 0
        last_checkpoint_seq = start_seq - 1 if start_seq > 0 else 0
        last_event_id = checkpoint.last_event_id if checkpoint else None

        logger.info(f"Starting replay for stream {stream_name} from sequence {start_seq}")
        self._record_audit(
            "REPLAY_STREAM_START", "system", {"stream_name": stream_name, "start_seq": start_seq}
        )

        while True:
            events = self._query_events_from_source(stream_name, start_seq, batch_sz)
            if not events:
                break
            total_read += len(events)
            if not dry_run:
                written, failed = self._write_batch_to_target(stream_name, events)
                total_written += written
                total_failed += failed
            else:
                total_written += len(events)
            last_event = events[-1]
            start_seq = last_event["sequence"] + 1
            last_event_id = UUID(last_event["event_id"]) if "event_id" in last_event else None
            # Save checkpoint periodically, but only if not dry_run
            if (total_written % (batch_sz * 10) == 0 or (limit and total_written >= limit)) and not dry_run:
                cp = ReplayCheckpoint(
                    stream_name=stream_name,
                    last_event_sequence=last_event["sequence"],
                    last_event_id=last_event_id,
                    replayed_at=datetime.now(UTC),
                    region_source=self.source_region,
                    region_target=self.target_region,
                    total_events_replayed=total_written,
                )
                if self.save_checkpoint(cp):
                    checkpoint_updates += 1
                    last_checkpoint_seq = last_event["sequence"]
            if limit and total_written >= limit:
                break

        if total_written > 0 and not dry_run:
            final_cp = ReplayCheckpoint(
                stream_name=stream_name,
                last_event_sequence=last_checkpoint_seq
                if last_checkpoint_seq > 0
                else start_seq - 1,
                last_event_id=last_event_id,
                replayed_at=datetime.now(UTC),
                region_source=self.source_region,
                region_target=self.target_region,
                total_events_replayed=total_written,
            )
            self.save_checkpoint(final_cp)

        duration = (datetime.now(UTC) - start_time).total_seconds()
        eps = total_written / duration if duration > 0 else 0
        metrics = ReplayMetrics(
            stream_name=stream_name,
            total_events_read=total_read,
            total_events_written=total_written,
            failed_events=total_failed,
            start_time=start_time,
            end_time=datetime.now(UTC),
            duration_seconds=duration,
            events_per_second=eps,
            checkpoint_updates=checkpoint_updates,
        )
        self._record_audit(
            "REPLAY_STREAM_END",
            "system",
            {"stream_name": stream_name, "written": total_written, "failed": total_failed},
        )
        logger.info(
            f"Replay for {stream_name} completed: {total_written} events written, {total_failed} failed, {eps:.2f} eps, duration {duration:.2f}s"
        )
        return metrics

    def replay_all_streams(
        self, stream_names: list[str], limit_per_stream: int | None = None, dry_run: bool = False
    ) -> dict[str, ReplayMetrics | None]:
        results = {}
        for stream in stream_names:
            try:
                metrics = self.replay_stream(stream, limit=limit_per_stream, dry_run=dry_run)
                results[stream] = metrics
            except Exception as e:
                logger.error(f"Failed to replay stream {stream}: {e}")
                results[stream] = None
        self._record_audit("REPLAY_ALL_STREAMS", "system", {"streams": len(stream_names)})
        return results

    def verify_cross_region_consistency(self, stream_name: str) -> tuple[bool, dict]:
        source_events = self._query_events_from_source(stream_name, 0, 10000)
        if not self.table_target:
            return False, {"error": "Target DynamoDB not available"}
        target_items = []
        try:
            response = self.table_target.query(
                KeyConditionExpression=Key("pk").eq(f"EVENT#{stream_name}"),
                Limit=10000,
            )
            target_items = response.get("Items", [])
        except ClientError as e:
            return False, {"error": str(e)}
        source_map = {e["sequence"]: e for e in source_events}
        target_map = {int(i["sk"]): i for i in target_items}
        missing_sequences = set(source_map.keys()) - set(target_map.keys())
        extra_sequences = set(target_map.keys()) - set(source_map.keys())
        if missing_sequences:
            return False, {
                "missing_sequences": sorted(missing_sequences),
                "total_missing": len(missing_sequences),
            }
        if extra_sequences:
            return False, {
                "extra_sequences": sorted(extra_sequences),
                "total_extra": len(extra_sequences),
            }
        return True, {
            "message": "Consistent",
            "source_count": len(source_events),
            "target_count": len(target_items),
        }

    def list_streams_in_source(self) -> list[str]:
        if not self.table_source:
            return []
        streams = set()
        try:
            response = self.table_source.scan(
                ProjectionExpression="pk",
                FilterExpression="begins_with(pk, :prefix)",
                ExpressionAttributeValues={":prefix": "EVENT#"},
            )
            for item in response.get("Items", []):
                pk = item["pk"]
                stream_name = pk.replace("EVENT#", "")
                streams.add(stream_name)
            return sorted(streams)
        except ClientError as e:
            logger.error(f"Failed to list streams: {e}")
            return []

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.source_region:
            errors.append("source_region is required")
        if not self.target_region:
            errors.append("target_region is required")
        if self.batch_size <= 0:
            errors.append("batch_size must be positive")
        if self.max_retries < 0:
            errors.append("max_retries cannot be negative")
        if self.backoff <= 0:
            errors.append("backoff_seconds must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_region": self.source_region,
            "target_region": self.target_region,
            "source_table_name": self.source_table_name,
            "target_table_name": self.target_table_name,
            "use_dynamodb": self.use_dynamodb,
            "use_s3_archive": self.use_s3_archive,
            "s3_bucket_archive": self.s3_bucket,
            "s3_prefix": self.s3_prefix,
            "batch_size": self.batch_size,
            "max_retries": self.max_retries,
            "backoff_seconds": self.backoff,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CrossRegionEventStoreReplayer:
        instance = cls(
            source_region=data["source_region"],
            target_region=data["target_region"],
            source_table_name=data.get("source_table_name", "event_store"),
            target_table_name=data.get("target_table_name", "event_store_replica"),
            use_dynamodb=data.get("use_dynamodb", True),
            use_s3_archive=data.get("use_s3_archive", True),
            s3_bucket_archive=data.get("s3_bucket_archive"),
            s3_prefix=data.get("s3_prefix", "events/"),
            batch_size=data.get("batch_size", 100),
            max_retries=data.get("max_retries", 3),
            backoff_seconds=data.get("backoff_seconds", 1.0),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> CrossRegionEventStoreReplayer:
        new = CrossRegionEventStoreReplayer(
            source_region=self.source_region,
            target_region=self.target_region,
            source_table_name=self.source_table_name,
            target_table_name=self.target_table_name,
            use_dynamodb=self.use_dynamodb,
            use_s3_archive=self.use_s3_archive,
            s3_bucket_archive=self.s3_bucket,
            s3_prefix=self.s3_prefix,
            batch_size=self.batch_size,
            max_retries=self.max_retries,
            backoff_seconds=self.backoff,
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "source_region": self.source_region,
            "target_region": self.target_region,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CrossRegionEventStoreReplayer:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._record_audit("RESET", "system", {})


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    replayer = CrossRegionEventStoreReplayer(
        source_region="ap-southeast-1",
        target_region="ap-southeast-2",
        source_table_name="event_store",
        target_table_name="event_store_replica",
    )
    streams = replayer.list_streams_in_source()
    print(f"Streams found: {streams}")
    if streams:
        metrics = replayer.replay_stream(streams[0], dry_run=True)
        print(f"Dry run metrics: {metrics.total_events_written} events would be replayed")
        consistent, details = replayer.verify_cross_region_consistency(streams[0])
        print(f"Consistent: {consistent}, details: {details}")
