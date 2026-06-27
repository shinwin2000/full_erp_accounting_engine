#!/usr/bin/env python3
"""
Module: aggregate_root.py
Layer: Domain / Consolidation
Responsibility: Aggregate root untuk konsolidasi laporan keuangan grup perusahaan.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.consolidation.elimination_entry import EliminationEntry
from domain.consolidation.intercompany_transaction import IntercompanyTransaction
from domain.legal_entity.company_entity import Company

logger = logging.getLogger(__name__)


class ConsolidationStatus(Enum):
    """Status proses konsolidasi."""

    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REVERSED = "reversed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"

    def can_modify(self) -> bool:
        return self in (ConsolidationStatus.DRAFT, ConsolidationStatus.IN_PROGRESS)

    def is_terminal(self) -> bool:
        return self in (
            ConsolidationStatus.COMPLETED,
            ConsolidationStatus.ARCHIVED,
            ConsolidationStatus.CANCELLED,
        )


@dataclass
class ConsolidationGroup:
    """
    Group konsolidasi yang terdiri dari parent dan anak perusahaan.
    Aggregate root untuk proses konsolidasi.
    """

    # Identitas
    group_id: UUID
    group_code: str
    group_name: str
    parent: Company
    subsidiaries: list[Company] = field(default_factory=list)
    period: date | None = None
    status: ConsolidationStatus = ConsolidationStatus.DRAFT
    description: str = ""

    # Transaksi dan eliminasi
    intercompany_transactions: list[IntercompanyTransaction] = field(default_factory=list)
    elimination_entries: list[EliminationEntry] = field(default_factory=list)

    # Hasil konsolidasi
    consolidated_balance: Decimal = Decimal(0)
    consolidated_equity: Decimal = Decimal(0)
    total_eliminations: Decimal = Decimal(0)
    total_nci: Decimal = Decimal(0)

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    updated_by: str = "system"
    version: int = 1
    metadata: dict[str, Any] | None = None

    # Event sourcing dan audit
    _events: ClassVar[list[Any]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        if not self.group_code or len(self.group_code.strip()) < 2:
            raise ValueError("Group code must be at least 2 characters")
        if not self.group_name or len(self.group_name.strip()) < 2:
            raise ValueError("Group name must be at least 2 characters")
        if not self.parent:
            raise ValueError("Parent company is required")
        if self.period and self.period > date.today():
            raise ValueError("Period cannot be in the future")
        if self.status not in ConsolidationStatus:
            raise ValueError(f"Invalid status: {self.status}")

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "group_id": str(self.group_id),
            "status": self.status.value,
            "total_eliminations": str(self.total_eliminations),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "group_id": str(self.group_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== PROPERTIES ====================

    @property
    def period_end(self) -> date | None:
        return self.period

    @period_end.setter
    def period_end(self, value: date) -> None:
        self.period = value

    @property
    def period_end_date(self) -> date | None:
        return self.period

    @property
    def include_entities(self) -> list[UUID]:
        ids = [self.parent.company_id] if self.parent else []
        ids.extend([sub.company_id for sub in self.subsidiaries])
        return ids

    @property
    def total_intercompany_revenue(self) -> Decimal:
        return sum(t.amount for t in self.intercompany_transactions if not t.is_eliminated)

    @property
    def total_equity(self) -> Decimal:
        total = self.parent.equity if hasattr(self.parent, "equity") else Decimal(0)
        for sub in self.subsidiaries:
            total += sub.equity if hasattr(sub, "equity") else Decimal(0)
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    @property
    def nci(self) -> Decimal:
        nci_total = Decimal(0)
        for sub in self.subsidiaries:
            ownership = getattr(sub, "ownership_percentage", Decimal(100))
            nci_total += (
                (Decimal(100) - ownership)
                / Decimal(100)
                * (sub.equity if hasattr(sub, "equity") else Decimal(0))
            )
        return nci_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> ConsolidationGroup:
        self._record_audit("CREATE", created_by, {"code": self.group_code, "name": self.group_name})
        return self

    def update(self, updated_by: str, **kwargs) -> ConsolidationGroup:
        if not self.status.can_modify():
            raise ValueError(f"Cannot update consolidation in status {self.status.value}")
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("group_id", "created_at", "created_by", "version"):
                data[key] = value
        new_group = self.from_dict(data)
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = updated_by
        new_group.version = self.version + 1
        new_group._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_group

    def delete(self, deleted_by: str, reason: str | None = None) -> ConsolidationGroup:
        if self.status == ConsolidationStatus.COMPLETED:
            raise ValueError("Cannot delete completed consolidation")
        new_group = self._copy()
        new_group.status = ConsolidationStatus.CANCELLED
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = deleted_by
        new_group.version = self.version + 1
        new_group._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_group

    def restore(self, restored_by: str) -> ConsolidationGroup:
        if self.status != ConsolidationStatus.CANCELLED:
            raise ValueError(f"Cannot restore consolidation in status {self.status.value}")
        new_group = self._copy()
        new_group.status = ConsolidationStatus.DRAFT
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = restored_by
        new_group.version = self.version + 1
        new_group._record_audit("RESTORE", restored_by, {})
        return new_group

    def activate(self, activated_by: str) -> ConsolidationGroup:
        if self.status != ConsolidationStatus.DRAFT:
            raise ValueError(f"Cannot activate consolidation in status {self.status.value}")
        new_group = self._copy()
        new_group.status = ConsolidationStatus.IN_PROGRESS
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = activated_by
        new_group.version = self.version + 1
        new_group._record_audit("ACTIVATE", activated_by, {})
        return new_group

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ConsolidationGroup:
        if self.status != ConsolidationStatus.IN_PROGRESS:
            raise ValueError(f"Cannot deactivate consolidation in status {self.status.value}")
        new_group = self._copy()
        new_group.status = ConsolidationStatus.DRAFT
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = deactivated_by
        new_group.version = self.version + 1
        new_group._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_group

    def lock(self, locked_by: str, reason: str) -> ConsolidationGroup:
        if self.status not in (ConsolidationStatus.IN_PROGRESS, ConsolidationStatus.DRAFT):
            raise ValueError(f"Cannot lock consolidation in status {self.status.value}")
        new_group = self._copy()
        new_group.status = ConsolidationStatus.DRAFT  # tidak ada LOCKED khusus, gunakan DRAFT
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = locked_by
        new_group.version = self.version + 1
        new_group._record_audit("LOCK", locked_by, {"reason": reason})
        return new_group

    def unlock(self, unlocked_by: str) -> ConsolidationGroup:
        if self.status != ConsolidationStatus.DRAFT:
            raise ValueError(f"Cannot unlock consolidation in status {self.status.value}")
        new_group = self._copy()
        new_group.status = ConsolidationStatus.IN_PROGRESS
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = unlocked_by
        new_group.version = self.version + 1
        new_group._record_audit("UNLOCK", unlocked_by, {})
        return new_group

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        if not self.subsidiaries:
            errors.append("No subsidiaries defined for consolidation")
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "group_id": str(self.group_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": str(self.group_id),
            "group_code": self.group_code,
            "group_name": self.group_name,
            "parent_id": str(self.parent.company_id) if self.parent else None,
            "subsidiary_ids": [str(sub.company_id) for sub in self.subsidiaries],
            "period": self.period.isoformat() if self.period else None,
            "status": self.status.value,
            "description": self.description,
            "consolidated_balance": str(self.consolidated_balance),
            "consolidated_equity": str(self.consolidated_equity),
            "total_eliminations": str(self.total_eliminations),
            "total_nci": str(self.total_nci),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "version": self.version,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        parent_company: Company | None = None,
        subsidiaries: list[Company] | None = None,
    ) -> ConsolidationGroup:
        group = cls(
            group_id=UUID(data["group_id"]),
            group_code=data["group_code"],
            group_name=data["group_name"],
            parent=parent_company or Company(id=UUID(data.get("parent_id", "")))
            if data.get("parent_id")
            else None,
            subsidiaries=subsidiaries or [],
            period=date.fromisoformat(data["period"]) if data.get("period") else None,
            status=ConsolidationStatus(data["status"]),
            description=data.get("description", ""),
            consolidated_balance=Decimal(data.get("consolidated_balance", "0")),
            consolidated_equity=Decimal(data.get("consolidated_equity", "0")),
            total_eliminations=Decimal(data.get("total_eliminations", "0")),
            total_nci=Decimal(data.get("total_nci", "0")),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            updated_by=data.get("updated_by", "system"),
            version=data.get("version", 1),
            metadata=data.get("metadata"),
        )
        return group

    def clone(self) -> ConsolidationGroup:
        new_id = uuid4()
        cloned = self._copy()
        object.__setattr__(cloned, "group_id", new_id)
        cloned.group_code = f"{self.group_code}_COPY"
        cloned.group_name = f"{self.group_name} (COPY)"
        cloned.status = ConsolidationStatus.DRAFT
        cloned.intercompany_transactions = []
        cloned.elimination_entries = []
        cloned.consolidated_balance = Decimal(0)
        cloned.consolidated_equity = Decimal(0)
        cloned.total_eliminations = Decimal(0)
        cloned.total_nci = Decimal(0)
        cloned.created_at = datetime.now(UTC)
        cloned.updated_at = datetime.now(UTC)
        cloned.version = 1
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.group_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "group_id": str(self.group_id),
            "status": self.status.value,
            "total_eliminations": str(self.total_eliminations),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ConsolidationGroup:
        new_group = self._copy()
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = touched_by
        new_group.version = self.version + 1
        new_group._record_audit("TOUCH", touched_by, {})
        return new_group

    # ==================== AGGREGATE ROOT METHODS ====================

    def add_child(self, subsidiary: Company, added_by: str) -> ConsolidationGroup:
        """Tambah anak perusahaan."""
        if not self.status.can_modify():
            raise ValueError(f"Cannot add subsidiary in status {self.status.value}")
        if subsidiary.company_id in [s.company_id for s in self.subsidiaries]:
            raise ValueError(f"Subsidiary {subsidiary.company_id} already exists")
        new_subsidiaries = self.subsidiaries + [subsidiary]
        new_group = self._copy()
        new_group.subsidiaries = new_subsidiaries
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = added_by
        new_group.version = self.version + 1
        new_group._record_audit(
            "ADD_CHILD", added_by, {"subsidiary_id": str(subsidiary.company_id)}
        )
        return new_group

    def remove_child(self, subsidiary_id: UUID, removed_by: str) -> ConsolidationGroup:
        """Hapus anak perusahaan."""
        if not self.status.can_modify():
            raise ValueError(f"Cannot remove subsidiary in status {self.status.value}")
        new_subsidiaries = [s for s in self.subsidiaries if s.company_id != subsidiary_id]
        if len(new_subsidiaries) == len(self.subsidiaries):
            raise ValueError(f"Subsidiary {subsidiary_id} not found")
        new_group = self._copy()
        new_group.subsidiaries = new_subsidiaries
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = removed_by
        new_group.version = self.version + 1
        new_group._record_audit("REMOVE_CHILD", removed_by, {"subsidiary_id": str(subsidiary_id)})
        return new_group

    def add_intercompany_transaction(
        self, transaction: IntercompanyTransaction, added_by: str
    ) -> ConsolidationGroup:
        """Tambah transaksi antar perusahaan."""
        if not self.status.can_modify():
            raise ValueError(f"Cannot add transaction in status {self.status.value}")
        new_transactions = self.intercompany_transactions + [transaction]
        new_group = self._copy()
        new_group.intercompany_transactions = new_transactions
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = added_by
        new_group.version = self.version + 1
        self._register_event(
            IntercompanyTransactionDetected(
                transaction_id=transaction.id,
                from_entity_id=transaction.from_entity_id or UUID(int=0),
                to_entity_id=transaction.to_entity_id or UUID(int=0),
                amount=transaction.amount,
                detected_at=datetime.now(UTC),
            )
        )
        new_group._record_audit(
            "ADD_INTERCOMPANY_TX",
            added_by,
            {"id": str(transaction.id), "amount": str(transaction.amount)},
        )
        return new_group

    def can_eliminate(self) -> bool:
        """Periksa apakah eliminasi dapat dilakukan."""
        return self.status in (ConsolidationStatus.IN_PROGRESS, ConsolidationStatus.DRAFT)

    def eliminate(self, eliminated_by: str) -> ConsolidationGroup:
        """Lakukan eliminasi transaksi antar perusahaan."""
        if not self.can_eliminate():
            raise ValueError(f"Cannot eliminate in status {self.status.value}")

        total_eliminated = Decimal(0)
        new_eliminations = []
        for tx in self.intercompany_transactions:
            if not tx.is_eliminated:
                # Buat elimination entry
                elim = EliminationEntry(
                    id=uuid4(),
                    account_code=tx.account_code,
                    debit=tx.amount if tx.transaction_type.value == "sale" else Decimal(0),
                    credit=tx.amount if tx.transaction_type.value == "purchase" else Decimal(0),
                    description=f"Elimination of intercompany {tx.transaction_type.value}",
                    from_entity_id=tx.from_entity_id,
                    to_entity_id=tx.to_entity_id,
                )
                new_eliminations.append(elim)
                total_eliminated += tx.amount
                tx.is_eliminated = True

        new_group = self._copy()
        new_group.elimination_entries = self.elimination_entries + new_eliminations
        new_group.total_eliminations = self.total_eliminations + total_eliminated
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = eliminated_by
        new_group.version = self.version + 1
        new_group._record_audit("ELIMINATE", eliminated_by, {"total": str(total_eliminated)})
        for elim in new_eliminations:
            self._register_event(
                EliminationEntryCreated(
                    elimination_id=elim.id,
                    account_code=elim.account_code,
                    amount=elim.amount,
                    created_at=datetime.now(UTC),
                )
            )
        return new_group

    def can_approve(self, user_role: str = "user") -> bool:
        return self.status == ConsolidationStatus.IN_PROGRESS and user_role in (
            "finance_manager",
            "admin",
            "auditor",
        )

    def approve(self, approved_by: str) -> ConsolidationGroup:
        if not self.can_approve():
            raise ValueError("Cannot approve consolidation in current status")
        new_group = self._copy()
        new_group.status = ConsolidationStatus.COMPLETED
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = approved_by
        new_group.version = self.version + 1
        new_group._record_audit("APPROVE", approved_by, {})
        self._register_event(
            ConsolidationCompleted(
                consolidation_id=self.group_id,
                group_entity_id=self.parent.legal_entity_id if self.parent else UUID(int=0),
                period_end_date=self.period,
                total_eliminations=self.total_eliminations,
                total_nci=self.total_nci,
                user_id=UUID(int=0),
                occurred_at=datetime.now(UTC),
            )
        )
        return new_group

    def can_reject(self, user_role: str = "user") -> bool:
        return self.status == ConsolidationStatus.IN_PROGRESS and user_role in (
            "finance_manager",
            "admin",
        )

    def reject(self, rejected_by: str, reason: str) -> ConsolidationGroup:
        if not self.can_reject():
            raise ValueError("Cannot reject consolidation in current status")
        new_group = self._copy()
        new_group.status = ConsolidationStatus.DRAFT
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = rejected_by
        new_group.version = self.version + 1
        new_group._record_audit("REJECT", rejected_by, {"reason": reason})
        return new_group

    def can_cancel(self, user_role: str = "user") -> bool:
        return self.status != ConsolidationStatus.COMPLETED and user_role in ("admin",)

    def cancel(self, cancelled_by: str, reason: str) -> ConsolidationGroup:
        if not self.can_cancel():
            raise ValueError("Cannot cancel consolidation in current status")
        new_group = self._copy()
        new_group.status = ConsolidationStatus.CANCELLED
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = cancelled_by
        new_group.version = self.version + 1
        new_group._record_audit("CANCEL", cancelled_by, {"reason": reason})
        return new_group

    def can_reverse(self) -> bool:
        return self.status == ConsolidationStatus.COMPLETED

    def reverse(self, reversed_by: str, reason: str) -> ConsolidationGroup:
        if not self.can_reverse():
            raise ValueError("Cannot reverse consolidation in current status")
        new_group = self._copy()
        new_group.status = ConsolidationStatus.REVERSED
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = reversed_by
        new_group.version = self.version + 1
        new_group._record_audit("REVERSE", reversed_by, {"reason": reason})
        return new_group

    def close(self, closed_by: str) -> ConsolidationGroup:
        if self.status != ConsolidationStatus.COMPLETED:
            raise ValueError("Only completed consolidation can be closed")
        new_group = self._copy()
        new_group.status = ConsolidationStatus.ARCHIVED
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = closed_by
        new_group.version = self.version + 1
        new_group._record_audit("CLOSE", closed_by, {})
        return new_group

    def reopen(self, reopened_by: str) -> ConsolidationGroup:
        if self.status != ConsolidationStatus.ARCHIVED:
            raise ValueError("Only archived consolidation can be reopened")
        new_group = self._copy()
        new_group.status = ConsolidationStatus.IN_PROGRESS
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = reopened_by
        new_group.version = self.version + 1
        new_group._record_audit("REOPEN", reopened_by, {})
        return new_group

    def archive(self, archived_by: str, reason: str | None = None) -> ConsolidationGroup:
        if self.status != ConsolidationStatus.COMPLETED:
            raise ValueError("Only completed consolidation can be archived")
        new_group = self._copy()
        new_group.status = ConsolidationStatus.ARCHIVED
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = archived_by
        new_group.version = self.version + 1
        new_group._record_audit("ARCHIVE", archived_by, {"reason": reason})
        return new_group

    def unarchive(self, unarchived_by: str) -> ConsolidationGroup:
        if self.status != ConsolidationStatus.ARCHIVED:
            raise ValueError("Only archived consolidation can be unarchived")
        new_group = self._copy()
        new_group.status = ConsolidationStatus.COMPLETED
        new_group.updated_at = datetime.now(UTC)
        new_group.updated_by = unarchived_by
        new_group.version = self.version + 1
        new_group._record_audit("UNARCHIVE", unarchived_by, {})
        return new_group

    # ==================== EVENT METHODS ====================

    def register_event(self, event: Any) -> None:
        self._events.append(event)

    def get_events(self) -> list[Any]:
        return self._events.copy()

    def pull_events(self) -> list[Any]:
        events = self._events.copy()
        self._events.clear()
        return events

    def clear_events(self) -> None:
        self._events.clear()

    def _register_event(self, event: Any) -> None:
        self.register_event(event)

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> ConsolidationGroup:
        return ConsolidationGroup(
            group_id=self.group_id,
            group_code=self.group_code,
            group_name=self.group_name,
            parent=self.parent,
            subsidiaries=self.subsidiaries.copy(),
            period=self.period,
            status=self.status,
            description=self.description,
            intercompany_transactions=self.intercompany_transactions.copy(),
            elimination_entries=self.elimination_entries.copy(),
            consolidated_balance=self.consolidated_balance,
            consolidated_equity=self.consolidated_equity,
            total_eliminations=self.total_eliminations,
            total_nci=self.total_nci,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            updated_by=self.updated_by,
            version=self.version,
            metadata=self.metadata.copy() if self.metadata else None,
        )


# ============================================================================
# Repository Implementation
# ============================================================================


class ConsolidationGroupRepository:
    """Repository untuk ConsolidationGroup dengan implementasi in-memory."""

    _storage: ClassVar[dict[UUID, ConsolidationGroup]] = {}

    async def get_by_id(self, group_id: UUID) -> ConsolidationGroup | None:
        return self._storage.get(group_id)

    async def get_by_parent(self, parent_id: UUID) -> list[ConsolidationGroup]:
        return [g for g in self._storage.values() if g.parent and g.parent.company_id == parent_id]

    async def get_by_period(self, period: date) -> list[ConsolidationGroup]:
        return [g for g in self._storage.values() if g.period == period]

    async def get_by_status(self, status: ConsolidationStatus) -> list[ConsolidationGroup]:
        return [g for g in self._storage.values() if g.status == status]

    async def get_all(self) -> list[ConsolidationGroup]:
        return list(self._storage.values())

    async def exists(self, group_id: UUID) -> bool:
        return group_id in self._storage

    async def count(self) -> int:
        return len(self._storage)

    async def save(self, group: ConsolidationGroup) -> None:
        self._storage[group.group_id] = group

    async def update(self, group: ConsolidationGroup) -> None:
        self._storage[group.group_id] = group

    async def delete(self, group_id: UUID) -> None:
        if group_id in self._storage:
            del self._storage[group_id]

    async def clear(self) -> None:
        self._storage.clear()


# ============================================================================
# Alias for compatibility
# ============================================================================

ConsolidationAggregate = ConsolidationGroup


__all__ = [
    "ConsolidationAggregate",
    "ConsolidationGroup",
    "ConsolidationGroupRepository",
    "ConsolidationStatus",
]
