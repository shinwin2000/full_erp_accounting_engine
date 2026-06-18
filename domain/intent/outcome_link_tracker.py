#!/usr/bin/env python3
"""
Module: outcome_link_tracker.py
Layer: 5 - Domain / Intent
Responsibility: Melacak hubungan antara intent dan outcome (event akuntansi).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.intent.audit_trail_writer import IntentAuditAction, get_audit_trail_writer
from domain.intent.immutable_record import (
    get_immutable_intent_record_service,
)

logger = logging.getLogger(__name__)


class LinkStatus(Enum):
    PENDING = auto()
    MAPPED = auto()
    EXECUTED = auto()
    FAILED = auto()
    CANCELLED = auto()


class LinkType(Enum):
    ONE_TO_ONE = auto()
    ONE_TO_MANY = auto()
    MANY_TO_ONE = auto()
    MANY_TO_MANY = auto()


@dataclass
class IntentOutcomeLink:
    link_id: UUID
    intent_id: UUID
    outcome_id: UUID
    outcome_type: str
    link_type: LinkType
    status: LinkStatus
    created_at: datetime
    created_by: str
    metadata: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    cryptographic_hash: str = ""

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())
        self._take_snapshot()
        self._record_audit("CREATE", self.created_by, {})

    def _validate(self) -> None:
        if not isinstance(self.link_id, UUID):
            raise ValueError("link_id must be UUID")
        if not isinstance(self.intent_id, UUID):
            raise ValueError("intent_id must be UUID")
        if not isinstance(self.outcome_id, UUID):
            raise ValueError("outcome_id must be UUID")
        if not self.outcome_type or not isinstance(self.outcome_type, str):
            raise ValueError("outcome_type must be a non-empty string")
        if not isinstance(self.link_type, LinkType):
            raise ValueError("link_type must be LinkType")
        if not isinstance(self.status, LinkStatus):
            raise ValueError("status must be LinkStatus")
        if not isinstance(self.created_at, datetime):
            raise ValueError("created_at must be datetime")
        if not self.created_by:
            raise ValueError("created_by cannot be empty")
        if self.version < 1:
            raise ValueError("version must be >= 1")

    def compute_hash(self) -> str:
        content = {
            "link_id": str(self.link_id),
            "intent_id": str(self.intent_id),
            "outcome_id": str(self.outcome_id),
            "outcome_type": self.outcome_type,
            "link_type": self.link_type.name,
            "status": self.status.name,
            "created_at": self.created_at.isoformat(),
            "version": self.version,
        }
        return hashlib.sha3_256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "link_id": str(self.link_id),
            "intent_id": str(self.intent_id),
            "outcome_id": str(self.outcome_id),
            "status": self.status.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "link_id": str(self.link_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> IntentOutcomeLink:
        self._record_audit("CREATE", created_by, {})
        return self

    def update(self, updated_by: str, **kwargs) -> IntentOutcomeLink:
        # Hanya metadata yang bisa diupdate
        new_metadata = self.metadata.copy()
        if "metadata" in kwargs:
            new_metadata.update(kwargs["metadata"])
        if "status" in kwargs and isinstance(kwargs["status"], LinkStatus):
            new_status = kwargs["status"]
        else:
            new_status = self.status
        new_link = IntentOutcomeLink(
            link_id=self.link_id,
            intent_id=self.intent_id,
            outcome_id=self.outcome_id,
            outcome_type=self.outcome_type,
            link_type=self.link_type,
            status=new_status,
            created_at=self.created_at,
            created_by=self.created_by,
            metadata=new_metadata,
            version=self.version + 1,
        )
        new_link._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_link

    def delete(self, deleted_by: str, reason: str | None = None) -> IntentOutcomeLink:
        # Soft delete: change status to CANCELLED
        new_link = IntentOutcomeLink(
            link_id=self.link_id,
            intent_id=self.intent_id,
            outcome_id=self.outcome_id,
            outcome_type=self.outcome_type,
            link_type=self.link_type,
            status=LinkStatus.CANCELLED,
            created_at=self.created_at,
            created_by=self.created_by,
            metadata=self.metadata,
            version=self.version + 1,
        )
        new_link._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_link

    def restore(self, restored_by: str) -> IntentOutcomeLink:
        if self.status != LinkStatus.CANCELLED:
            raise ValueError("Only cancelled links can be restored")
        new_link = IntentOutcomeLink(
            link_id=self.link_id,
            intent_id=self.intent_id,
            outcome_id=self.outcome_id,
            outcome_type=self.outcome_type,
            link_type=self.link_type,
            status=LinkStatus.MAPPED,
            created_at=self.created_at,
            created_by=self.created_by,
            metadata=self.metadata,
            version=self.version + 1,
        )
        new_link._record_audit("RESTORE", restored_by, {})
        return new_link

    def activate(self, activated_by: str) -> IntentOutcomeLink:
        if self.status == LinkStatus.PENDING:
            new_link = self.update(activated_by, status=LinkStatus.MAPPED)
            new_link._record_audit("ACTIVATE", activated_by, {})
            return new_link
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> IntentOutcomeLink:
        if self.status == LinkStatus.MAPPED:
            new_link = self.update(deactivated_by, status=LinkStatus.PENDING)
            new_link._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
            return new_link
        return self

    def lock(self, locked_by: str, reason: str) -> IntentOutcomeLink:
        return self

    def unlock(self, unlocked_by: str) -> IntentOutcomeLink:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "link_id": str(self.link_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "link_id": str(self.link_id),
            "intent_id": str(self.intent_id),
            "outcome_id": str(self.outcome_id),
            "outcome_type": self.outcome_type,
            "link_type": self.link_type.name,
            "status": self.status.name,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "metadata": self.metadata,
            "version": self.version,
            "cryptographic_hash": self.cryptographic_hash[:16] + "...",
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntentOutcomeLink:
        return cls(
            link_id=UUID(data["link_id"]),
            intent_id=UUID(data["intent_id"]),
            outcome_id=UUID(data["outcome_id"]),
            outcome_type=data["outcome_type"],
            link_type=LinkType[data["link_type"]],
            status=LinkStatus[data["status"]],
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data["created_by"],
            metadata=data.get("metadata", {}),
            version=data.get("version", 1),
            cryptographic_hash=data.get("cryptographic_hash", ""),
        )

    def clone(self) -> IntentOutcomeLink:
        new_id = uuid4()
        return IntentOutcomeLink(
            link_id=new_id,
            intent_id=self.intent_id,
            outcome_id=self.outcome_id,
            outcome_type=self.outcome_type,
            link_type=self.link_type,
            status=LinkStatus.PENDING,
            created_at=datetime.now(UTC),
            created_by=self.created_by,
            metadata=self.metadata.copy(),
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "link_id": str(self.link_id),
            "intent_id": str(self.intent_id),
            "outcome_id": str(self.outcome_id),
            "status": self.status.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> IntentOutcomeLink:
        self._record_audit("TOUCH", touched_by, {})
        return self


class OutcomeLinkTracker:
    _instance: OutcomeLinkTracker | None = None

    def __new__(cls) -> OutcomeLinkTracker:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._audit_writer = get_audit_trail_writer()
        self._record_service = get_immutable_intent_record_service()
        self._links: dict[UUID, IntentOutcomeLink] = {}
        self._intent_to_outcomes: dict[UUID, list[UUID]] = {}
        self._outcome_to_intents: dict[UUID, list[UUID]] = {}
        self._lock = threading.RLock()

    # ==================== LINK CREATION ====================
    def create_link(
        self,
        intent_id: UUID,
        outcome_id: UUID,
        outcome_type: str,
        created_by: str,
        link_type: LinkType = LinkType.ONE_TO_ONE,
        metadata: dict[str, Any] | None = None,
    ) -> IntentOutcomeLink:
        with self._lock:
            link = IntentOutcomeLink(
                link_id=uuid4(),
                intent_id=intent_id,
                outcome_id=outcome_id,
                outcome_type=outcome_type,
                link_type=link_type,
                status=LinkStatus.MAPPED,
                created_at=datetime.now(UTC),
                created_by=created_by,
                metadata=metadata or {},
            )
            self._links[link.link_id] = link
            self._intent_to_outcomes.setdefault(intent_id, []).append(outcome_id)
            self._outcome_to_intents.setdefault(outcome_id, []).append(intent_id)
            self._audit_writer.write_linked_to_outcome(intent_id, created_by, outcome_id)
            return link

    def create_multi_link(
        self,
        intent_id: UUID,
        outcome_ids: list[UUID],
        outcome_type: str,
        created_by: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[IntentOutcomeLink]:
        links = []
        for oid in outcome_ids:
            link = self.create_link(
                intent_id, oid, outcome_type, created_by, LinkType.ONE_TO_MANY, metadata
            )
            links.append(link)
        return links

    def update_link_status(
        self, link_id: UUID, new_status: LinkStatus, updated_by: str
    ) -> IntentOutcomeLink | None:
        with self._lock:
            link = self._links.get(link_id)
            if not link:
                return None
            updated = link.update(updated_by, status=new_status)
            self._links[link_id] = updated
            self._audit_writer.write(
                intent_id=link.intent_id,
                action=IntentAuditAction.UPDATED,
                changed_by=updated_by,
                notes=f"Link status changed to {new_status.name}",
            )
            return updated

    # ==================== QUERY METHODS ====================
    def get_outcomes_for_intent(
        self, intent_id: UUID, outcome_type: str | None = None
    ) -> list[tuple[IntentOutcomeLink, Any]]:
        with self._lock:
            links = [
                l
                for l in self._links.values()
                if l.intent_id == intent_id and l.status != LinkStatus.CANCELLED
            ]
            if outcome_type:
                links = [l for l in links if l.outcome_type == outcome_type]
            return [(l, None) for l in links]

    def get_intents_for_outcome(self, outcome_id: UUID) -> list[tuple[IntentOutcomeLink, Any]]:
        with self._lock:
            links = [
                l
                for l in self._links.values()
                if l.outcome_id == outcome_id and l.status != LinkStatus.CANCELLED
            ]
            return [(l, None) for l in links]

    def get_link(self, link_id: UUID) -> IntentOutcomeLink | None:
        with self._lock:
            return self._links.get(link_id)

    def get_traceability_chain(
        self, start_id: UUID, start_type: str, max_depth: int = 10
    ) -> list[dict[str, Any]]:
        chain = []
        visited = set()

        def traverse(current_id: UUID, current_type: str, depth: int):
            if depth > max_depth or (current_id, current_type) in visited:
                return
            visited.add((current_id, current_type))
            if current_type == "intent":
                for oid in self._intent_to_outcomes.get(current_id, []):
                    chain.append(
                        {
                            "from_type": "intent",
                            "from_id": str(current_id),
                            "to_type": "outcome",
                            "to_id": str(oid),
                            "depth": depth,
                        }
                    )
                    traverse(oid, "outcome", depth + 1)
            else:  # outcome
                for iid in self._outcome_to_intents.get(current_id, []):
                    chain.append(
                        {
                            "from_type": "outcome",
                            "from_id": str(current_id),
                            "to_type": "intent",
                            "to_id": str(iid),
                            "depth": depth,
                        }
                    )
                    traverse(iid, "intent", depth + 1)

        traverse(start_id, start_type, 0)
        return chain

    # ==================== REPOSITORY METHODS ====================
    def save(self, link: IntentOutcomeLink) -> None:
        with self._lock:
            self._links[link.link_id] = link
            self._intent_to_outcomes.setdefault(link.intent_id, []).append(link.outcome_id)
            self._outcome_to_intents.setdefault(link.outcome_id, []).append(link.intent_id)

    def get_all_links(self) -> list[IntentOutcomeLink]:
        with self._lock:
            return list(self._links.values())

    def delete_link(self, link_id: UUID) -> bool:
        with self._lock:
            link = self._links.get(link_id)
            if not link:
                return False
            # Remove from indexes
            if link.intent_id in self._intent_to_outcomes:
                self._intent_to_outcomes[link.intent_id] = [
                    oid
                    for oid in self._intent_to_outcomes[link.intent_id]
                    if oid != link.outcome_id
                ]
            if link.outcome_id in self._outcome_to_intents:
                self._outcome_to_intents[link.outcome_id] = [
                    iid
                    for iid in self._outcome_to_intents[link.outcome_id]
                    if iid != link.intent_id
                ]
            del self._links[link_id]
            return True

    def count_links(self) -> int:
        with self._lock:
            return len(self._links)

    def search_links_by_intent(self, intent_id: UUID) -> list[IntentOutcomeLink]:
        with self._lock:
            return [l for l in self._links.values() if l.intent_id == intent_id]

    def search_links_by_outcome(self, outcome_id: UUID) -> list[IntentOutcomeLink]:
        with self._lock:
            return [l for l in self._links.values() if l.outcome_id == outcome_id]

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_links = len(self._links)
            by_status = {}
            by_type = {}
            for l in self._links.values():
                by_status[l.status.name] = by_status.get(l.status.name, 0) + 1
                by_type[l.link_type.name] = by_type.get(l.link_type.name, 0) + 1
            return {
                "total_links": total_links,
                "by_status": by_status,
                "by_link_type": by_type,
                "total_intents_with_outcomes": len(self._intent_to_outcomes),
                "total_outcomes_with_intents": len(self._outcome_to_intents),
            }

    def reset(self) -> None:
        with self._lock:
            self._links.clear()
            self._intent_to_outcomes.clear()
            self._outcome_to_intents.clear()


def get_outcome_link_tracker() -> OutcomeLinkTracker:
    global _outcome_link_tracker_instance
    if _outcome_link_tracker_instance is None:
        _outcome_link_tracker_instance = OutcomeLinkTracker()
    return _outcome_link_tracker_instance


_outcome_link_tracker_instance: OutcomeLinkTracker | None = None

__all__ = [
    "IntentOutcomeLink",
    "LinkStatus",
    "LinkType",
    "OutcomeLinkTracker",
    "get_outcome_link_tracker",
]
