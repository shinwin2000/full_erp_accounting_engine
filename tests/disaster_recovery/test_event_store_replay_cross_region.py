# tests/disaster_recovery/test_event_store_replay_cross_region.py
"""
Comprehensive tests for disaster_recovery/event_store_replay_cross_region.py.

Covers:
- ReplayCheckpoint: all entity methods, compute checksum, to/from DynamoDB
- ReplayMetrics: all entity methods
- CrossRegionEventStoreReplayer:
  - __init__, validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch, reset
  - get_last_checkpoint, save_checkpoint
  - _query_events_from_dynamodb, _query_events_from_s3, _query_events_from_source
  - _write_batch_to_target
  - replay_stream, replay_all_streams, verify_cross_region_consistency, list_streams_in_source
- All AWS dependencies are mocked (boto3, DynamoDB, S3).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import boto3
import pytest
from botocore.exceptions import ClientError

from disaster_recovery.event_store_replay_cross_region import (
    CrossRegionEventStoreReplayer,
    ReplayCheckpoint,
    ReplayMetrics,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_dynamodb_resource():
    """Mock boto3.resource('dynamodb') with table mocks."""
    with patch("boto3.resource") as mock_resource:
        # Mock source table
        mock_source_table = MagicMock()
        mock_source_table.get_item = MagicMock()
        mock_source_table.put_item = MagicMock()
        mock_source_table.query = MagicMock()
        mock_source_table.scan = MagicMock()
        mock_source_table.batch_writer = MagicMock()

        # Mock target table
        mock_target_table = MagicMock()
        mock_target_table.get_item = MagicMock()
        mock_target_table.put_item = MagicMock()
        mock_target_table.query = MagicMock()
        mock_target_table.scan = MagicMock()
        mock_target_table.batch_writer = MagicMock()

        # Mock DynamoDB resource
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.side_effect = lambda name: (
            mock_source_table if name == "event_store" else mock_target_table
        )
        mock_resource.return_value = mock_dynamodb

        yield {
            "resource": mock_resource,
            "source_table": mock_source_table,
            "target_table": mock_target_table,
        }


@pytest.fixture
def mock_s3_client():
    """Mock boto3.client('s3')."""
    with patch("boto3.client") as mock_client:
        mock_s3 = MagicMock()
        mock_client.return_value = mock_s3
        yield mock_s3


@pytest.fixture
def replayer(mock_dynamodb_resource, mock_s3_client):
    """CrossRegionEventStoreReplayer with mocked AWS clients."""
    return CrossRegionEventStoreReplayer(
        source_region="us-east-1",
        target_region="us-west-2",
        source_table_name="event_store",
        target_table_name="event_store_replica",
        use_dynamodb=True,
        use_s3_archive=True,
        s3_bucket_archive="test-bucket",
        s3_prefix="events/",
        batch_size=10,
        max_retries=2,
        backoff_seconds=0.5,
    )


@pytest.fixture
def sample_checkpoint():
    return ReplayCheckpoint(
        stream_name="test-stream",
        last_event_id=uuid4(),
        replayed_at=datetime.now(UTC),
        region_source="us-east-1",
        region_target="us-west-2",
        last_event_sequence=100,
        total_events_replayed=150,
    )


@pytest.fixture
def sample_metrics():
    start = datetime.now(UTC)
    end = start + timedelta(seconds=5)
    return ReplayMetrics(
        stream_name="test-stream",
        total_events_read=100,
        total_events_written=95,
        failed_events=5,
        start_time=start,
        end_time=end,
        duration_seconds=5.0,
        events_per_second=19.0,
        checkpoint_updates=2,
    )


# ============================================================================
# Tests for ReplayCheckpoint
# ============================================================================

class TestReplayCheckpoint:
    def test_construction(self, sample_checkpoint):
        assert sample_checkpoint.stream_name == "test-stream"
        assert sample_checkpoint.last_event_sequence == 100
        assert sample_checkpoint.checksum != ""
        assert sample_checkpoint._version == 1

    def test_compute_checksum(self, sample_checkpoint):
        checksum = sample_checkpoint._compute_checksum()
        assert isinstance(checksum, str)
        assert len(checksum) == 64  # SHA256 hex length

        # Same data should yield same checksum
        cp2 = ReplayCheckpoint(
            stream_name=sample_checkpoint.stream_name,
            last_event_id=sample_checkpoint.last_event_id,
            replayed_at=sample_checkpoint.replayed_at,
            region_source=sample_checkpoint.region_source,
            region_target=sample_checkpoint.region_target,
            last_event_sequence=sample_checkpoint.last_event_sequence,
        )
        assert cp2._compute_checksum() == checksum

    def test_to_dynamodb_item(self, sample_checkpoint):
        item = sample_checkpoint.to_dynamodb_item()
        assert item["pk"] == f"CHECKPOINT#{sample_checkpoint.stream_name}"
        assert item["sk"] == "LATEST"
        assert item["last_sequence"] == sample_checkpoint.last_event_sequence
        assert item["last_event_id"] == str(sample_checkpoint.last_event_id)
        assert item["region_source"] == sample_checkpoint.region_source
        assert item["region_target"] == sample_checkpoint.region_target
        assert "version" in item

    def test_from_dynamodb_item(self):
        event_id = uuid4()
        now = datetime.now(UTC)
        item = {
            "pk": "CHECKPOINT#test-stream",
            "sk": "LATEST",
            "last_sequence": 200,
            "last_event_id": str(event_id),
            "replayed_at": now.isoformat(),
            "region_source": "us-east-1",
            "region_target": "us-west-2",
            "total_events_replayed": 300,
            "checksum": "abc123",
            "version": 5,
        }
        cp = ReplayCheckpoint.from_dynamodb_item(item)
        assert cp.stream_name == "test-stream"
        assert cp.last_event_sequence == 200
        assert cp.last_event_id == event_id
        assert cp.replayed_at == now
        assert cp.region_source == "us-east-1"
        assert cp.region_target == "us-west-2"
        assert cp.total_events_replayed == 300
        assert cp.checksum == "abc123"
        assert cp._version == 5

    def test_validate(self, sample_checkpoint):
        result = sample_checkpoint.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

        # Invalid cases
        invalid = ReplayCheckpoint(
            stream_name="",
            last_event_id=uuid4(),
            replayed_at=datetime.now(UTC),
            region_source="",
            region_target="",
            last_event_sequence=-1,
        )
        result2 = invalid.validate()
        assert result2["is_valid"] is False
        assert "stream_name is required" in result2["errors"]
        assert "region_source is required" in result2["errors"]
        assert "region_target is required" in result2["errors"]
        assert "last_event_sequence cannot be negative" in result2["errors"]

    def test_to_dict(self, sample_checkpoint):
        d = sample_checkpoint.to_dict()
        assert d["stream_name"] == sample_checkpoint.stream_name
        assert d["last_event_id"] == str(sample_checkpoint.last_event_id)
        assert d["last_event_sequence"] == sample_checkpoint.last_event_sequence
        assert "replayed_at" in d
        assert "checksum" in d
        assert d["version"] == sample_checkpoint._version

    def test_from_dict(self, sample_checkpoint):
        d = sample_checkpoint.to_dict()
        cp2 = ReplayCheckpoint.from_dict(d)
        assert cp2.stream_name == sample_checkpoint.stream_name
        assert cp2.last_event_id == sample_checkpoint.last_event_id
        assert cp2.last_event_sequence == sample_checkpoint.last_event_sequence
        assert cp2.replayed_at == sample_checkpoint.replayed_at
        assert cp2.checksum == sample_checkpoint.checksum
        assert cp2._version == sample_checkpoint._version

    def test_clone(self, sample_checkpoint):
        clone = sample_checkpoint.clone()
        assert clone is not sample_checkpoint
        assert clone.stream_name == sample_checkpoint.stream_name
        assert clone._version == sample_checkpoint._version + 1
        assert clone._audit_trail[-1]["action"] == "CLONE"

    def test_snapshot(self, sample_checkpoint):
        snap = sample_checkpoint.snapshot()
        assert snap["stream_name"] == sample_checkpoint.stream_name
        assert snap["last_event_sequence"] == sample_checkpoint.last_event_sequence
        assert "timestamp" in snap

    def test_version(self, sample_checkpoint):
        assert sample_checkpoint.version() == sample_checkpoint._version

    def test_audit_trail(self, sample_checkpoint):
        sample_checkpoint._record_audit("TEST", "user", {"foo": "bar"})
        trail = sample_checkpoint.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test_touch(self, sample_checkpoint):
        old_version = sample_checkpoint._version
        touched = sample_checkpoint.touch("tester")
        assert touched._version == old_version + 1
        assert touched._audit_trail[-1]["action"] == "TOUCH"


# ============================================================================
# Tests for ReplayMetrics
# ============================================================================

class TestReplayMetrics:
    def test_construction(self, sample_metrics):
        assert sample_metrics.stream_name == "test-stream"
        assert sample_metrics.total_events_written == 95
        assert sample_metrics.duration_seconds == 5.0

    def test_validate(self, sample_metrics):
        result = sample_metrics.validate()
        assert result["is_valid"] is True

        invalid = ReplayMetrics(
            stream_name="",
            total_events_read=-1,
            total_events_written=-1,
            failed_events=-1,
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC),
            duration_seconds=-1,
            events_per_second=-1,
            checkpoint_updates=-1,
        )
        result2 = invalid.validate()
        assert result2["is_valid"] is False
        assert "stream_name is required" in result2["errors"]
        assert "total_events_read cannot be negative" in result2["errors"]
        assert "duration_seconds cannot be negative" in result2["errors"]

    def test_to_dict(self, sample_metrics):
        d = sample_metrics.to_dict()
        assert d["stream_name"] == sample_metrics.stream_name
        assert d["total_events_written"] == sample_metrics.total_events_written
        assert "start_time" in d
        assert "end_time" in d
        assert d["version"] == sample_metrics._version

    def test_from_dict(self, sample_metrics):
        d = sample_metrics.to_dict()
        m2 = ReplayMetrics.from_dict(d)
        assert m2.stream_name == sample_metrics.stream_name
        assert m2.total_events_written == sample_metrics.total_events_written
        assert m2.start_time == sample_metrics.start_time
        assert m2._version == sample_metrics._version

    def test_clone(self, sample_metrics):
        clone = sample_metrics.clone()
        assert clone is not sample_metrics
        assert clone.stream_name == sample_metrics.stream_name
        assert clone._version == sample_metrics._version + 1
        assert clone._audit_trail[-1]["action"] == "CLONE"

    def test_snapshot(self, sample_metrics):
        snap = sample_metrics.snapshot()
        assert snap["stream_name"] == sample_metrics.stream_name
        assert snap["total_events_written"] == sample_metrics.total_events_written

    def test_version(self, sample_metrics):
        assert sample_metrics.version() == sample_metrics._version

    def test_audit_trail(self, sample_metrics):
        sample_metrics._record_audit("TEST", "user", {"foo": "bar"})
        trail = sample_metrics.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test_touch(self, sample_metrics):
        old_version = sample_metrics._version
        touched = sample_metrics.touch("tester")
        assert touched._version == old_version + 1
        assert touched._audit_trail[-1]["action"] == "TOUCH"


# ============================================================================
# Tests for CrossRegionEventStoreReplayer (with mocks)
# ============================================================================

class TestCrossRegionEventStoreReplayer:
    def test_init(self, replayer):
        assert replayer.source_region == "us-east-1"
        assert replayer.target_region == "us-west-2"
        assert replayer.batch_size == 10
        assert replayer.max_retries == 2
        assert replayer.backoff == 0.5
        assert replayer._version == 1

    def test_validate(self, replayer):
        result = replayer.validate()
        assert result["is_valid"] is True

        # Invalid
        replayer.batch_size = 0
        replayer.backoff = 0
        result2 = replayer.validate()
        assert result2["is_valid"] is False
        assert "batch_size must be positive" in result2["errors"]
        assert "backoff_seconds must be positive" in result2["errors"]

    def test_to_dict(self, replayer):
        d = replayer.to_dict()
        assert d["source_region"] == "us-east-1"
        assert d["target_region"] == "us-west-2"
        assert d["batch_size"] == 10
        assert "version" in d

    def test_from_dict(self):
        data = {
            "source_region": "ap-southeast-1",
            "target_region": "ap-southeast-2",
            "source_table_name": "my_source",
            "target_table_name": "my_target",
            "batch_size": 50,
            "max_retries": 5,
            "backoff_seconds": 0.2,
            "version": 3,
        }
        with patch("boto3.resource") as mock_resource:
            with patch("boto3.client") as mock_client:
                replayer = CrossRegionEventStoreReplayer.from_dict(data)
                assert replayer.source_region == "ap-southeast-1"
                assert replayer.target_region == "ap-southeast-2"
                assert replayer.batch_size == 50
                assert replayer._version == 3

    def test_clone(self, replayer):
        clone = replayer.clone()
        assert clone is not replayer
        assert clone.source_region == replayer.source_region
        assert clone._version == replayer._version + 1

    def test_snapshot(self, replayer):
        snap = replayer.snapshot()
        assert snap["source_region"] == replayer.source_region
        assert snap["target_region"] == replayer.target_region
        assert "timestamp" in snap

    def test_version(self, replayer):
        assert replayer.version() == replayer._version

    def test_audit_trail(self, replayer):
        replayer._record_audit("TEST", "user", {"foo": "bar"})
        trail = replayer.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test_touch(self, replayer):
        old_version = replayer._version
        replayer.touch("tester")
        assert replayer._version == old_version + 1
        assert replayer._audit_trail[-1]["action"] == "TOUCH"

    def test_reset(self, replayer):
        replayer._version = 5
        replayer._audit_trail = [{"foo": "bar"}]
        replayer.reset()
        assert replayer._version == 1
        assert replayer._audit_trail == []
        assert replayer._audit_trail[-1]["action"] == "RESET"

    # ---- Checkpoint tests ----
    def test_get_last_checkpoint_success(self, replayer):
        event_id = uuid4()
        now = datetime.now(UTC)
        item = {
            "pk": "CHECKPOINT#test-stream",
            "sk": "LATEST",
            "last_sequence": 50,
            "last_event_id": str(event_id),
            "replayed_at": now.isoformat(),
            "region_source": "us-east-1",
            "region_target": "us-west-2",
            "total_events_replayed": 60,
            "checksum": "",  # will be computed
            "version": 1,
        }
        # Need to compute correct checksum for the checkpoint
        cp = ReplayCheckpoint(
            stream_name="test-stream",
            last_event_id=event_id,
            replayed_at=now,
            region_source="us-east-1",
            region_target="us-west-2",
            last_event_sequence=50,
            total_events_replayed=60,
        )
        item["checksum"] = cp.checksum

        replayer.table_target.get_item.return_value = {"Item": item}
        result = replayer.get_last_checkpoint("test-stream")
        assert result is not None
        assert result.last_event_sequence == 50
        assert result.last_event_id == event_id

    def test_get_last_checkpoint_not_found(self, replayer):
        replayer.table_target.get_item.return_value = {"Item": None}
        result = replayer.get_last_checkpoint("test-stream")
        assert result is None

    def test_get_last_checkpoint_checksum_mismatch(self, replayer):
        event_id = uuid4()
        now = datetime.now(UTC)
        item = {
            "pk": "CHECKPOINT#test-stream",
            "sk": "LATEST",
            "last_sequence": 50,
            "last_event_id": str(event_id),
            "replayed_at": now.isoformat(),
            "region_source": "us-east-1",
            "region_target": "us-west-2",
            "total_events_replayed": 60,
            "checksum": "wronghash",
            "version": 1,
        }
        replayer.table_target.get_item.return_value = {"Item": item}
        result = replayer.get_last_checkpoint("test-stream")
        assert result is None  # checksum mismatch, ignore

    def test_save_checkpoint(self, replayer):
        cp = ReplayCheckpoint(
            stream_name="test-stream",
            last_event_id=uuid4(),
            replayed_at=datetime.now(UTC),
            region_source="us-east-1",
            region_target="us-west-2",
            last_event_sequence=100,
        )
        replayer.table_target.put_item.return_value = {"ResponseMetadata": {"HTTPStatusCode": 200}}
        success = replayer.save_checkpoint(cp)
        assert success is True
        replayer.table_target.put_item.assert_called_once()

        # If DynamoDB fails
        replayer.table_target.put_item.side_effect = ClientError(
            {"Error": {"Code": "InternalServerError"}}, "PutItem"
        )
        success2 = replayer.save_checkpoint(cp)
        assert success2 is False

    # ---- Query events from DynamoDB ----
    def test_query_events_from_dynamodb(self, replayer):
        items = [
            {"stream_name": "test", "sequence": 1, "event_id": str(uuid4()), "payload": "{}"},
            {"stream_name": "test", "sequence": 2, "event_id": str(uuid4()), "payload": "{}"},
        ]
        replayer.table_source.query.return_value = {"Items": items}
        result = replayer._query_events_from_dynamodb("test", start_sequence=0, limit=10)
        assert len(result) == 2
        replayer.table_source.query.assert_called_once()

        # If query fails, fallback to scan
        replayer.table_source.query.side_effect = ClientError(
            {"Error": {"Code": "InternalServerError"}}, "Query"
        )
        replayer.table_source.scan.return_value = {"Items": items}
        result2 = replayer._query_events_from_dynamodb("test", start_sequence=0, limit=10)
        assert len(result2) == 2
        replayer.table_source.scan.assert_called()

    def test_query_events_from_s3(self, replayer):
        # Mock S3 response with one object
        replayer.s3_client.get_paginator.return_value.paginate.return_value = [
            {"Contents": [{"Key": "events/test/001.json"}]}
        ]
        replayer.s3_client.get_object.return_value = {
            "Body": MagicMock(read=lambda: json.dumps({"events": [{"sequence": 1, "event_id": str(uuid4())}]}).encode())
        }
        result = replayer._query_events_from_s3("test", start_sequence=0, limit=10)
        assert len(result) == 1

        # If no S3 client
        replayer.s3_client = None
        result2 = replayer._query_events_from_s3("test", start_sequence=0, limit=10)
        assert result2 == []

    def test_query_events_from_source(self, replayer):
        # Should try DynamoDB first
        replayer._query_events_from_dynamodb = MagicMock(return_value=[{"seq": 1}])
        result = replayer._query_events_from_source("test", start_sequence=0, limit=10)
        assert len(result) == 1
        replayer._query_events_from_dynamodb.assert_called_once()

        # If DynamoDB returns empty, try S3
        replayer._query_events_from_dynamodb.return_value = []
        replayer._query_events_from_s3 = MagicMock(return_value=[{"seq": 2}])
        result2 = replayer._query_events_from_source("test", start_sequence=0, limit=10)
        assert len(result2) == 1

    # ---- Write batch to target ----
    def test_write_batch_to_target(self, replayer):
        events = [
            {"sequence": 1, "event_id": str(uuid4()), "event_type": "TEST", "payload": {}, "timestamp": datetime.now(UTC).isoformat()},
            {"sequence": 2, "event_id": str(uuid4()), "event_type": "TEST", "payload": {}},
        ]
        # Mock batch writer
        mock_batch = MagicMock()
        mock_batch.__enter__ = MagicMock(return_value=mock_batch)
        mock_batch.__exit__ = MagicMock(return_value=False)
        replayer.table_target.batch_writer.return_value = mock_batch

        written, failed = replayer._write_batch_to_target("test", events)
        assert written == 2
        assert failed == 0
        assert mock_batch.put_item.call_count == 2

        # If an exception occurs during batch writing
        mock_batch.put_item.side_effect = Exception("Write error")
        written2, failed2 = replayer._write_batch_to_target("test", events)
        assert written2 == 0
        assert failed2 == 2

    # ---- replay_stream ----
    def test_replay_stream(self, replayer):
        # Mock checkpoint (start from sequence 0)
        replayer.get_last_checkpoint = MagicMock(return_value=None)

        # Mock query to return two batches
        events_batch1 = [
            {"sequence": 1, "event_id": str(uuid4()), "event_type": "T1", "payload": {}},
            {"sequence": 2, "event_id": str(uuid4()), "event_type": "T1", "payload": {}},
        ]
        events_batch2 = [
            {"sequence": 3, "event_id": str(uuid4()), "event_type": "T1", "payload": {}},
        ]
        replayer._query_events_from_source = MagicMock(side_effect=[events_batch1, events_batch2, []])

        # Mock write batch
        replayer._write_batch_to_target = MagicMock(return_value=(2, 0))

        # Mock save checkpoint
        replayer.save_checkpoint = MagicMock(return_value=True)

        metrics = replayer.replay_stream("test-stream", batch_size=2, dry_run=False)
        assert metrics.total_events_read == 3
        assert metrics.total_events_written == 3
        assert metrics.failed_events == 0
        assert metrics.checkpoint_updates >= 1
        assert metrics.duration_seconds > 0
        assert metrics.events_per_second > 0

        # Dry run
        replayer._query_events_from_source = MagicMock(return_value=[{"sequence": 1}])
        replayer._write_batch_to_target = MagicMock()
        metrics2 = replayer.replay_stream("test-stream", dry_run=True)
        assert metrics2.total_events_written == 1
        replayer._write_batch_to_target.assert_not_called()

    # ---- replay_all_streams ----
    def test_replay_all_streams(self, replayer):
        replayer.replay_stream = MagicMock(side_effect=[
            ReplayMetrics(
                stream_name="s1",
                total_events_read=10,
                total_events_written=10,
                failed_events=0,
                start_time=datetime.now(UTC),
                end_time=datetime.now(UTC),
                duration_seconds=1.0,
                events_per_second=10.0,
                checkpoint_updates=1,
            ),
            ReplayMetrics(
                stream_name="s2",
                total_events_read=5,
                total_events_written=5,
                failed_events=0,
                start_time=datetime.now(UTC),
                end_time=datetime.now(UTC),
                duration_seconds=0.5,
                events_per_second=10.0,
                checkpoint_updates=1,
            ),
        ])
        results = replayer.replay_all_streams(["s1", "s2"], limit_per_stream=100, dry_run=False)
        assert "s1" in results
        assert "s2" in results
        assert results["s1"].total_events_written == 10
        assert results["s2"].total_events_written == 5

        # If one stream fails
        replayer.replay_stream = MagicMock(side_effect=Exception("Fail"))
        results2 = replayer.replay_all_streams(["fail"], limit_per_stream=10)
        assert results2["fail"] is None

    # ---- verify_cross_region_consistency ----
    def test_verify_cross_region_consistency(self, replayer):
        source_events = [
            {"sequence": 1, "event_id": str(uuid4()), "event_type": "T1"},
            {"sequence": 2, "event_id": str(uuid4()), "event_type": "T1"},
        ]
        target_items = [
            {"pk": "EVENT#test", "sk": "1", "event_id": "e1"},
            {"pk": "EVENT#test", "sk": "2", "event_id": "e2"},
        ]
        replayer._query_events_from_source = MagicMock(return_value=source_events)
        replayer.table_target.query = MagicMock(return_value={"Items": target_items})

        consistent, details = replayer.verify_cross_region_consistency("test")
        assert consistent is True
        assert details["message"] == "Consistent"

        # Missing sequence
        target_items2 = [{"pk": "EVENT#test", "sk": "1"}]
        replayer.table_target.query.return_value = {"Items": target_items2}
        consistent2, details2 = replayer.verify_cross_region_consistency("test")
        assert consistent2 is False
        assert "missing_sequences" in details2

        # Extra sequence
        target_items3 = [
            {"pk": "EVENT#test", "sk": "1"},
            {"pk": "EVENT#test", "sk": "2"},
            {"pk": "EVENT#test", "sk": "3"},
        ]
        replayer.table_target.query.return_value = {"Items": target_items3}
        consistent3, details3 = replayer.verify_cross_region_consistency("test")
        assert consistent3 is False
        assert "extra_sequences" in details3

        # Target table not available
        replayer.table_target = None
        consistent4, details4 = replayer.verify_cross_region_consistency("test")
        assert consistent4 is False
        assert details4["error"] == "Target DynamoDB not available"

    # ---- list_streams_in_source ----
    def test_list_streams_in_source(self, replayer):
        items = [
            {"pk": "EVENT#stream1"},
            {"pk": "EVENT#stream2"},
            {"pk": "EVENT#stream3"},
        ]
        replayer.table_source.scan.return_value = {"Items": items}
        streams = replayer.list_streams_in_source()
        assert streams == ["stream1", "stream2", "stream3"]

        # If scan fails
        replayer.table_source.scan.side_effect = ClientError(
            {"Error": {"Code": "InternalServerError"}}, "Scan"
        )
        streams2 = replayer.list_streams_in_source()
        assert streams2 == []

        # If no table source
        replayer.table_source = None
        streams3 = replayer.list_streams_in_source()
        assert streams3 == []