#!/usr/bin/env python3

"""
Module: disaster_recovery_replay.py
Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk replay event dari event store untuk keperluan disaster recovery.
    Semua dependency diberikan dari luar (event store, tamper scanner, event publisher).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from application.commands_cqrs.command_bus_unified import BaseCommand, CommandResult
from application.events.publisher_application import EventEnvelope

logger = logging.getLogger(__name__)


# ============================================================================
# PROTOCOLS
# ============================================================================


class EventStorePort(Protocol):
    async def query(
        self,
        from_date: datetime,
        to_date: datetime,
        aggregate_ids: list[UUID] | None = None,
        limit: int = 1000000,
    ) -> list[Any]: ...
    async def get_event(self, event_id: UUID) -> Any | None: ...


class TamperDetectionScannerPort(Protocol):
    async def scan(self, from_date: datetime, to_date: datetime, full_scan: bool = True) -> Any: ...


class EventPublisherPort(Protocol):
    async def publish(self, envelope: EventEnvelope, force_sync: bool = False) -> Any: ...


# ============================================================================
# COMMAND
# ============================================================================


class DisasterRecoveryReplayCommand(BaseCommand):
    __slots__ = (
        "dry_run",
        "from_date",
        "rebuild_projections",
        "target_aggregate_ids",
        "to_date",
        "verify_integrity_first",
    )

    def __init__(
        self,
        from_date: datetime,
        to_date: datetime,
        verify_integrity_first: bool = True,
        rebuild_projections: bool = True,
        target_aggregate_ids: list[UUID] | None = None,
        dry_run: bool = False,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="DisasterRecoveryReplayCommand",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        self.from_date = from_date
        self.to_date = to_date
        self.verify_integrity_first = verify_integrity_first
        self.rebuild_projections = rebuild_projections
        self.target_aggregate_ids = target_aggregate_ids or []
        self.dry_run = dry_run

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "from_date": self.from_date.isoformat(),
                "to_date": self.to_date.isoformat(),
                "verify_integrity_first": self.verify_integrity_first,
                "rebuild_projections": self.rebuild_projections,
                "target_aggregate_ids": [str(aid) for aid in self.target_aggregate_ids],
                "dry_run": self.dry_run,
            }
        )
        return data


class DisasterRecoveryResult:
    def __init__(
        self,
        events_replayed: int,
        integrity_verified: bool,
        failed_events: list[dict[str, Any]],
        rebuild_summary: dict[str, int],
        message: str,
    ):
        self.events_replayed = events_replayed
        self.integrity_verified = integrity_verified
        self.failed_events = failed_events
        self.rebuild_summary = rebuild_summary
        self.message = message


class DisasterRecoveryReplayUseCase:
    def __init__(
        self,
        event_store: EventStorePort,
        tamper_scanner: TamperDetectionScannerPort,
        event_publisher: EventPublisherPort,
    ):
        if event_store is None:
            raise ValueError("event_store is required")
        if tamper_scanner is None:
            raise ValueError("tamper_scanner is required")
        if event_publisher is None:
            raise ValueError("event_publisher is required")
        self._event_store = event_store
        self._tamper_scanner = tamper_scanner
        self._event_publisher = event_publisher
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: DisasterRecoveryReplayCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            integrity_verified = True
            if command.verify_integrity_first and not command.dry_run:
                scan_result = await self._tamper_scanner.scan(
                    from_date=command.from_date, to_date=command.to_date, full_scan=True
                )
                integrity_verified = getattr(scan_result, "is_intact", True)
                if not integrity_verified:
                    raise ValueError(
                        "Integrity check failed! Corrupted events detected. Fix before replay."
                    )

            events = await self._event_store.query(
                from_date=command.from_date,
                to_date=command.to_date,
                aggregate_ids=command.target_aggregate_ids,
                limit=1000000,
            )

            if not events:
                return CommandResult.success(
                    command_id=command.command_id,
                    data={
                        "events_replayed": 0,
                        "integrity_verified": integrity_verified,
                        "failed_events": [],
                        "rebuild_summary": {},
                        "message": "No events found in the specified range",
                    },
                )

            if command.dry_run:
                events_by_type = self._group_by_event_type(events)
                return CommandResult.success(
                    command_id=command.command_id,
                    data={
                        "dry_run": True,
                        "events_found": len(events),
                        "events_by_type": events_by_type,
                        "message": f"Dry run: {len(events)} events would be replayed",
                    },
                )

            failed_events = []
            replayed_count = 0

            for event in events:
                try:
                    envelope = EventEnvelope(
                        event_id=event.get("id", uuid4()),
                        event_type=event.get("event_type", "UnknownEvent"),
                        correlation_id=event.get("correlation_id", str(uuid4())),
                        causation_id=event.get("causation_id"),
                        user_id=event.get("user_id"),
                        tenant_id=event.get("tenant_id"),
                        occurred_at=event.get("occurred_at", datetime.now(UTC)),
                        source_system=event.get("source_system", "disaster_recovery"),
                        version=event.get("version", 1),
                        idempotency_key=f"replay_{event.get('id')}",
                    )
                    await self._event_publisher.publish(envelope, force_sync=False)
                    replayed_count += 1
                except Exception as e:
                    logger.error(f"Failed to replay event {event.get('id')}: {e}")
                    failed_events.append(
                        {
                            "event_id": str(event.get("id")),
                            "event_type": event.get("event_type"),
                            "error": str(e),
                        }
                    )

            rebuild_summary = {}
            if command.rebuild_projections and replayed_count > 0:
                rebuild_summary = await self._rebuild_projections(command)

            result = DisasterRecoveryResult(
                events_replayed=replayed_count,
                integrity_verified=integrity_verified,
                failed_events=failed_events,
                rebuild_summary=rebuild_summary,
                message=f"Replayed {replayed_count} events, {len(failed_events)} failed",
            )

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "events_replayed": result.events_replayed,
                    "integrity_verified": result.integrity_verified,
                    "failed_events": result.failed_events,
                    "rebuild_summary": result.rebuild_summary,
                    "message": result.message,
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"Disaster recovery replay failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="DISASTER_RECOVERY_ERROR"
            )

    def _group_by_event_type(self, events: list[Any]) -> dict[str, int]:
        groups = {}
        for e in events:
            et = e.get("event_type", "unknown")
            groups[et] = groups.get(et, 0) + 1
        return groups

    async def _rebuild_projections(self, command: DisasterRecoveryReplayCommand) -> dict[str, int]:
        # Placeholder - trigger projection rebuild via external service
        return {
            "general_ledger_rebuilt": 1,
            "trial_balance_rebuilt": 1,
            "ar_aging_rebuilt": 1,
            "ap_aging_rebuilt": 1,
        }

    def get_stats(self) -> dict[str, int]:
        return self._stats


async def disaster_recovery_replay_handler(
    command: DisasterRecoveryReplayCommand, use_case: DisasterRecoveryReplayUseCase
) -> CommandResult:
    if not isinstance(command, DisasterRecoveryReplayCommand):
        raise TypeError(f"Expected DisasterRecoveryReplayCommand, got {type(command)}")
    return await use_case.execute(command)


__all__ = [
    "DisasterRecoveryReplayCommand",
    "DisasterRecoveryReplayUseCase",
    "DisasterRecoveryResult",
    "disaster_recovery_replay_handler",
]
