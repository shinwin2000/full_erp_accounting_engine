#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: 6 - Domain / System Settings
Responsibility: Event: SettingChanged, SettingReset.
               Mendefinisikan domain events yang dihasilkan oleh perubahan
               pengaturan sistem, termasuk perubahan nilai dan reset ke default.

Dependencies:
- standard library (uuid, datetime, dataclass, json)
- domain.system_settings.setting_definition_entity (SettingDefinitionEntity)
- domain.system_settings.setting_value_vo (SettingValueVO)

Audit: Setiap perubahan pengaturan dictat.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.system_settings.setting_definition_entity import SettingDefinitionEntity
from domain.system_settings.setting_value_vo import SettingValueVO

# === 1. DOMAIN EVENT BASE ===


class DomainEventType(Enum):
    """Tipe domain event untuk System Settings."""

    SETTING_CHANGED = "setting_changed"
    SETTING_RESET = "setting_reset"
    SETTING_ADDED = "setting_added"
    SETTING_REMOVED = "setting_removed"
    SETTINGS_LOCKED = "settings_locked"
    SETTINGS_UNLOCKED = "settings_unlocked"
    SETTINGS_BULK_UPDATED = "settings_bulk_updated"


@dataclass
class DomainEvent:
    """
    Base class untuk semua domain events System Settings.
    """

    event_id: UUID
    event_type: DomainEventType
    aggregate_id: UUID
    aggregate_version: int
    occurred_at: datetime
    event_data: dict[str, Any]
    user_id: str | None = None
    correlation_id: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "event_id": str(self.event_id),
                "event_type": self.event_type.value,
                "aggregate_id": str(self.aggregate_id),
                "aggregate_version": self.aggregate_version,
                "occurred_at": self.occurred_at.isoformat(),
                "user_id": self.user_id,
                "correlation_id": self.correlation_id,
                "event_data": self.event_data,
            },
            default=str,
        )

    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        data = json.loads(json_str)
        return cls(
            event_id=UUID(data["event_id"]),
            event_type=DomainEventType(data["event_type"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_version=data["aggregate_version"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data["event_data"],
            user_id=data.get("user_id"),
            correlation_id=data.get("correlation_id"),
        )


# === 2. CONCRETE DOMAIN EVENTS ===


@dataclass
class SettingChangedEvent(DomainEvent):
    """Event ketika nilai pengaturan berubah."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        key: str,
        old_value: SettingValueVO | None,
        new_value: SettingValueVO,
        changed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "key": key,
            "old_value": old_value.to_dict() if old_value else None,
            "new_value": new_value.to_dict(),
            "changed_by": changed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SETTING_CHANGED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class SettingResetEvent(DomainEvent):
    """Event ketika pengaturan direset ke default."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        key: str,
        old_value: SettingValueVO,
        default_value: SettingValueVO,
        reset_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "key": key,
            "old_value": old_value.to_dict(),
            "default_value": default_value.to_dict(),
            "reset_by": reset_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SETTING_RESET,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class SettingAddedEvent(DomainEvent):
    """Event ketika definisi pengaturan baru ditambahkan."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        definition: SettingDefinitionEntity,
        added_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "key": definition.key,
            "definition": definition.to_dict(),
            "added_by": added_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SETTING_ADDED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class SettingRemovedEvent(DomainEvent):
    """Event ketika definisi pengaturan dihapus."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        key: str,
        removed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "key": key,
            "removed_by": removed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SETTING_REMOVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class SettingsLockedEvent(DomainEvent):
    """Event ketika sistem pengaturan dikunci."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        locked_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "locked_by": locked_by,
            "previous_status": "active",
            "new_status": "locked",
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SETTINGS_LOCKED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class SettingsUnlockedEvent(DomainEvent):
    """Event ketika sistem pengaturan dibuka kuncinya."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        unlocked_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "unlocked_by": unlocked_by,
            "previous_status": "locked",
            "new_status": "active",
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SETTINGS_UNLOCKED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class SettingsBulkUpdatedEvent(DomainEvent):
    """Event ketika multiple pengaturan diupdate sekaligus."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        updated_keys: list[str],
        updated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "updated_keys": updated_keys,
            "updated_by": updated_by,
            "count": len(updated_keys),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SETTINGS_BULK_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


# === 3. DOMAIN EVENT PUBLISHER PROTOCOL ===


class DomainEventPublisher:
    """
    Protocol untuk publish domain events System Settings.
    """

    async def publish(self, event: DomainEvent) -> None:
        raise NotImplementedError

    async def publish_many(self, events: list[DomainEvent]) -> None:
        for event in events:
            await self.publish(event)


# === 4. EXPORTS ===

__all__ = [
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "SettingAddedEvent",
    "SettingChangedEvent",
    "SettingRemovedEvent",
    "SettingResetEvent",
    "SettingsBulkUpdatedEvent",
    "SettingsLockedEvent",
    "SettingsUnlockedEvent",
]
