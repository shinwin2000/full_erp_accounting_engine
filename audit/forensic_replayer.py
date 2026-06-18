#!/usr/bin/env python3
"""
Module: forensic_replayer.py
Layer: Audit
Responsibility: Memutar ulang (replay) event dari event store untuk keperluan
               forensik dan audit. Mendukung replay per stream, per rentang waktu,
               atau per aggregate. Juga menyediakan kemampuan untuk mengekspor
               hasil replay ke file dan membandingkan state aggregate antara
               dua titik waktu untuk mendeteksi perubahan tidak sah.
Dependencies:
- asyncio, logging, datetime
- infrastructure.event_store.append_only_store (AppendOnlyStore)
- domain.* (untuk rekonstruksi aggregate)
- audit.hash_chain_builder (AuditHashChainBuilder)
- infrastructure.telemetry.structured_json_logging
Audit: Setiap replay dicatat untuk audit trail. Hasil replay dapat digunakan
       sebagai bukti forensik.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from audit.hash_chain_builder import AuditHashChainBuilder, get_audit_hash_builder

# Internal dependencies
from infrastructure.event_store.append_only_store import AppendOnlyStore, get_event_store
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_BATCH_SIZE = 1000
DEFAULT_EXPORT_DIR = Path("/var/audit/replays")

# ============================================================================
# EXCEPTIONS
# ============================================================================


class ForensicReplayError(Exception):
    """Base exception untuk forensic replayer."""

    pass


class StreamNotFoundError(ForensicReplayError):
    """Stream tidak ditemukan."""

    pass


class ReplayTimeoutError(ForensicReplayError):
    """Timeout saat replay."""

    pass


# ============================================================================
# FORENSIC REPLAYER
# ============================================================================


class ForensicReplayer:
    """
    Replayer untuk event store forensik.

    Fitur:
    - Replay event per stream
    - Replay berdasarkan rentang waktu
    - Replay per aggregate dengan rekonstruksi state
    - Export hasil replay ke file JSON
    - Compare state antara dua titik waktu
    - Hash chain verification during replay
    """

    def __init__(self):
        self._event_store: AppendOnlyStore | None = None
        self._hash_builder: AuditHashChainBuilder | None = None
        self._export_dir = DEFAULT_EXPORT_DIR
        self._export_dir.mkdir(parents=True, exist_ok=True)

    async def _get_event_store(self) -> AppendOnlyStore:
        if self._event_store is None:
            self._event_store = await get_event_store()
        return self._event_store

    async def _get_hash_builder(self) -> AuditHashChainBuilder:
        if self._hash_builder is None:
            self._hash_builder = get_audit_hash_builder()
        return self._hash_builder

    async def replay_stream(
        self,
        stream_name: str,
        from_sequence: int = 1,
        limit: int = 10000,
        verify_chain: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Replay events from a specific stream.

        Args:
            stream_name: Name of the stream
            from_sequence: Starting sequence number
            limit: Maximum number of events to replay
            verify_chain: Verify hash chain during replay

        Returns:
            List of events in chronological order
        """
        store = await self._get_event_store()
        events = await store.read_stream(stream_name, from_sequence, limit)

        if not events:
            logger.warning(f"No events found in stream {stream_name}")
            return []

        if verify_chain:
            hash_builder = await self._get_hash_builder()
            is_valid, broken_at, error = await hash_builder.verify_chain(events, stream_name)
            if not is_valid:
                logger.error(f"Hash chain verification failed for stream {stream_name}: {error}")
                await trigger_alert(
                    title="Forensic Replay: Hash Chain Verification Failed",
                    message=f"Stream {stream_name} has broken hash chain at index {broken_at}",
                    severity="critical",
                    source="ForensicReplayer",
                )
                # Still return events but flag them
                for i, event in enumerate(events):
                    event["_integrity_verified"] = (i < broken_at) if broken_at else False

        return events

    async def replay_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime,
        stream_name: str | None = None,
        limit: int = 10000,
    ) -> list[dict[str, Any]]:
        """
        Replay events within a time range.

        Args:
            start_time: Start timestamp (inclusive)
            end_time: End timestamp (inclusive)
            stream_name: Optional stream filter
            limit: Maximum number of events

        Returns:
            List of events in chronological order
        """
        store = await self._get_event_store()

        if stream_name:
            # For specific stream, read all and filter by time
            events = await store.read_stream(stream_name, limit=limit)
            filtered = [
                e
                for e in events
                if start_time <= datetime.fromisoformat(e["timestamp"]) <= end_time
            ]
            return filtered
        else:
            # Search across all streams (requires search method)
            events = await store.search_events(
                start_time=start_time, end_time=end_time, limit=limit
            )
            return events

    async def replay_aggregate(
        self, aggregate_type: str, aggregate_id: UUID, verify_chain: bool = True
    ) -> list[dict[str, Any]]:
        """
        Replay all events for a specific aggregate.

        Args:
            aggregate_type: Type of aggregate (e.g., "Journal", "ARInvoice")
            aggregate_id: UUID of the aggregate
            verify_chain: Verify hash chain

        Returns:
            List of events for the aggregate in order
        """
        stream_name = f"{aggregate_type}:{aggregate_id}"
        return await self.replay_stream(stream_name, verify_chain=verify_chain)

    async def reconstruct_aggregate_state(
        self, aggregate_type: str, aggregate_id: UUID, snapshot_store=None
    ) -> dict[str, Any]:
        """
        Reconstruct aggregate state by replaying events.

        Args:
            aggregate_type: Type of aggregate
            aggregate_id: UUID of the aggregate
            snapshot_store: Optional snapshot store to start from snapshot

        Returns:
            Reconstructed state dictionary
        """
        events = await self.replay_aggregate(aggregate_type, aggregate_id)

        if not events:
            return {"error": "No events found", "aggregate_id": str(aggregate_id)}

        # Start with empty state
        state = {}

        # Apply events in order to reconstruct state
        for event in events:
            event_type = event.get("event_type")
            data = event.get("data", {})

            # Apply event logic based on event type
            # This is simplified; in production, use aggregate's apply() method
            if event_type == "JournalCreated":
                state["journal_id"] = data.get("journal_id")
                state["status"] = "draft"
                state["lines"] = data.get("lines", [])
            elif event_type == "JournalSubmitted":
                state["status"] = "submitted"
                state["submitted_at"] = event.get("timestamp")
            elif event_type == "JournalApproved":
                state["status"] = "approved"
                state["approved_by"] = data.get("approved_by")
                state["approved_at"] = event.get("timestamp")
            elif event_type == "JournalPosted":
                state["status"] = "posted"
                state["posted_by"] = data.get("posted_by")
                state["posted_at"] = event.get("timestamp")
            elif event_type == "ARInvoiceCreated":
                state["invoice_id"] = data.get("invoice_id")
                state["status"] = "draft"
                state["total_amount"] = data.get("total_amount")
            elif event_type == "ARInvoicePaid":
                state["status"] = "paid"
                state["paid_amount"] = data.get("amount")
            # Add more event types as needed

        return {
            "aggregate_type": aggregate_type,
            "aggregate_id": str(aggregate_id),
            "state": state,
            "event_count": len(events),
            "first_event_at": events[0].get("timestamp") if events else None,
            "last_event_at": events[-1].get("timestamp") if events else None,
        }

    async def export_replay(
        self, events: list[dict[str, Any]], filename: str, format: str = "json"
    ) -> Path:
        """
        Export replayed events to file.

        Args:
            events: List of events to export
            filename: Output filename (without extension)
            format: Output format ("json" or "csv")

        Returns:
            Path to exported file
        """
        if format == "json":
            file_path = self._export_dir / f"{filename}.json"
            with open(file_path, "w") as f:
                json.dump(events, f, indent=2, default=str)
        elif format == "csv":
            import csv

            file_path = self._export_dir / f"{filename}.csv"
            with open(file_path, "w", newline="") as f:
                if events:
                    fieldnames = [
                        "id",
                        "event_type",
                        "timestamp",
                        "sequence_number",
                        "data",
                        "metadata",
                    ]
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for event in events:
                        row = {
                            "id": event.get("id"),
                            "event_type": event.get("event_type"),
                            "timestamp": event.get("timestamp"),
                            "sequence_number": event.get("sequence_number"),
                            "data": json.dumps(event.get("data", {}), default=str),
                            "metadata": json.dumps(event.get("metadata", {}), default=str),
                        }
                        writer.writerow(row)
        else:
            raise ValueError(f"Unsupported format: {format}")

        logger.info(f"Exported {len(events)} events to {file_path}")
        return file_path

    async def compare_states(
        self,
        aggregate_type: str,
        aggregate_id: UUID,
        snapshot1_time: datetime,
        snapshot2_time: datetime,
    ) -> dict[str, Any]:
        """
        Compare aggregate state between two points in time.

        Returns:
            Dictionary with differences
        """
        # Get events up to snapshot1_time
        events1 = await self.replay_aggregate(aggregate_type, aggregate_id)
        events1 = [e for e in events1 if datetime.fromisoformat(e["timestamp"]) <= snapshot1_time]

        # Get events up to snapshot2_time
        events2 = await self.replay_aggregate(aggregate_type, aggregate_id)
        events2 = [e for e in events2 if datetime.fromisoformat(e["timestamp"]) <= snapshot2_time]

        # Reconstruct states (simplified - just track events applied)
        state1 = {"event_count": len(events1), "last_event": events1[-1] if events1 else None}
        state2 = {"event_count": len(events2), "last_event": events2[-1] if events2 else None}

        # Find events that occurred between the two times
        new_events = [e for e in events2 if e not in events1]

        return {
            "aggregate_type": aggregate_type,
            "aggregate_id": str(aggregate_id),
            "snapshot1_time": snapshot1_time.isoformat(),
            "snapshot2_time": snapshot2_time.isoformat(),
            "state1": state1,
            "state2": state2,
            "new_events_count": len(new_events),
            "new_events": new_events[:100],  # Limit for output
        }

    async def get_stream_info(self, stream_name: str) -> dict[str, Any]:
        """
        Get information about a stream (for forensic investigation).
        """
        store = await self._get_event_store()
        info = await store.get_stream_info(stream_name)
        return info

    async def list_streams(self, prefix: str | None = None) -> list[str]:
        """
        List all streams in event store.
        """
        store = await self._get_event_store()
        async with store._session_factory() as session:
            from sqlalchemy import select

            from infrastructure.persistence_orm.event_store_table import EventStoreTable

            stmt = select(EventStoreTable.stream_name).distinct()
            if prefix:
                stmt = stmt.where(EventStoreTable.stream_name.like(f"{prefix}%"))
            result = await session.execute(stmt)
            streams = result.scalars().all()
            return list(streams)


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_forensic_replayer: ForensicReplayer | None = None


async def get_forensic_replayer() -> ForensicReplayer:
    """Get singleton instance of ForensicReplayer."""
    global _forensic_replayer
    if _forensic_replayer is None:
        _forensic_replayer = ForensicReplayer()
    return _forensic_replayer


# ============================================================================
# CLI COMMAND
# ============================================================================


def cli():
    """CLI entry point for forensic replayer."""
    import argparse

    parser = argparse.ArgumentParser(description="Forensic Event Replayer")
    parser.add_argument(
        "command",
        choices=["replay-stream", "replay-time", "replay-aggregate", "list-streams", "export"],
        help="Replay command",
    )
    parser.add_argument("--stream", "-s", help="Stream name")
    parser.add_argument("--start", help="Start time (ISO format)")
    parser.add_argument("--end", help="End time (ISO format)")
    parser.add_argument("--aggregate-type", "-t", help="Aggregate type")
    parser.add_argument("--aggregate-id", "-i", help="Aggregate ID")
    parser.add_argument("--output", "-o", help="Output file")
    parser.add_argument("--format", "-f", default="json", choices=["json", "csv"])
    parser.add_argument("--limit", "-l", type=int, default=1000, help="Event limit")

    args = parser.parse_args()

    async def run():
        replayer = await get_forensic_replayer()

        if args.command == "replay-stream":
            if not args.stream:
                print("Error: --stream required")
                return
            events = await replayer.replay_stream(args.stream, limit=args.limit)
            print(f"Replayed {len(events)} events from stream {args.stream}")
            if args.output:
                await replayer.export_replay(events, args.output, args.format)
        elif args.command == "replay-time":
            if not args.start or not args.end:
                print("Error: --start and --end required")
                return
            start = datetime.fromisoformat(args.start)
            end = datetime.fromisoformat(args.end)
            events = await replayer.replay_by_time_range(start, end, args.stream, args.limit)
            print(f"Replayed {len(events)} events between {args.start} and {args.end}")
            if args.output:
                await replayer.export_replay(events, args.output, args.format)
        elif args.command == "replay-aggregate":
            if not args.aggregate_type or not args.aggregate_id:
                print("Error: --aggregate-type and --aggregate-id required")
                return
            state = await replayer.reconstruct_aggregate_state(
                args.aggregate_type, UUID(args.aggregate_id)
            )
            print(json.dumps(state, indent=2, default=str))
        elif args.command == "list-streams":
            streams = await replayer.list_streams()
            for s in streams:
                print(s)
        elif args.command == "export":
            if not args.stream:
                print("Error: --stream required")
                return
            events = await replayer.replay_stream(args.stream, limit=args.limit)
            await replayer.export_replay(events, args.output or "export", args.format)

    try:
        asyncio.get_running_loop()
        asyncio.create_task(run())
    except RuntimeError:
        sub_loop = asyncio.new_event_loop()
        try:
            sub_loop.run_until_complete(run())
        finally:
            sub_loop.close()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "ForensicReplayError",
    "ForensicReplayer",
    "ReplayTimeoutError",
    "StreamNotFoundError",
    "get_forensic_replayer",
]

if __name__ == "__main__":
    cli()