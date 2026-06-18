#!/usr/bin/env python3
"""
Module: nsfp_manager.py
Layer: Adapters (Coretax DJP)
Responsibility: Mengelola Nomor Seri Faktur Pajak (NSFP) yang diminta dari DJP.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from adapters.coretax_djp.api_oauth2_client import CoretaxAuthError, get_coretax_client

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

CORETAX_NSFP_REQUEST_ENDPOINT = "/api/v1/nsfp/request"
CORETAX_NSFP_QUOTA_ENDPOINT = "/api/v1/nsfp/quota"
CORETAX_NSFP_VALIDATE_ENDPOINT = "/api/v1/nsfp/validate"
CORETAX_NSFP_USAGE_ENDPOINT = "/api/v1/nsfp/usage"
CORETAX_NSFP_SYNC_ENDPOINT = "/api/v1/nsfp/sync"

REDIS_NSFP_PREFIX = "coretax:nsfp:"
REDIS_NSFP_AVAILABLE_PREFIX = "coretax:nsfp:available:"
REDIS_NSFP_ALLOCATED_PREFIX = "coretax:nsfp:allocated:"
REDIS_NSFP_USED_PREFIX = "coretax:nsfp:used:"

DEFAULT_NSFP_REQUEST_BATCH_SIZE = 100
DEFAULT_NSFP_LOW_WATERMARK = 50
DEFAULT_NSFP_HIGH_WATERMARK = 500
DEFAULT_NSFP_CRITICAL_WATERMARK = 10
MAX_RETRY_ATTEMPTS = 3
CACHE_TTL_SECONDS = 86400
NSFP_LENGTH = 8
NSFP_PATTERN = r"^\d{8}$"


class NSFStatus(Enum):
    AVAILABLE = "available"
    ALLOCATED = "allocated"
    USED = "used"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    RELEASED = "released"
    PENDING = "pending"
    LOCKED = "locked"
    ARCHIVED = "archived"
    ERROR = "error"


class NSFError(Exception):
    pass


class NSFNotFoundError(NSFError):
    pass


class NSFNotAvailableError(NSFError):
    pass


class NSFDuplicateError(NSFError):
    pass


class NSFInvalidFormatError(NSFError):
    pass


class NSFQuotaExhaustedError(NSFError):
    pass


class NSFAllocationError(NSFError):
    pass


class NSFExpiredError(NSFError):
    pass


class NSFP:
    """Entity untuk Nomor Seri Faktur Pajak (NSFP)."""

    def __init__(
        self,
        nsfp_number: str,
        npwp: str,
        tahun: int,
        bulan: int,
        status: NSFStatus = NSFStatus.AVAILABLE,
        allocated_to_faktur_id: UUID | None = None,
        used_at: datetime | None = None,
        expiry_date: date | None = None,
        nsfp_id: UUID | None = None,
        version: int = 1,
    ):
        self._nsfp_id = nsfp_id or uuid4()
        self._nsfp_number = nsfp_number
        self._npwp = npwp
        self._tahun = tahun
        self._bulan = bulan
        self._status = status
        self._allocated_to_faktur_id = allocated_to_faktur_id
        self._used_at = used_at
        self._expiry_date = expiry_date or self._calculate_expiry_date(tahun, bulan)
        self._version = version
        self._created_at = datetime.now()
        self._updated_at = datetime.now()
        self._allocated_at: datetime | None = None
        self._released_at: datetime | None = None
        self._cancelled_at: datetime | None = None
        self._locked_at: datetime | None = None
        self._locked_by: UUID | None = None
        self._events: list[dict[str, Any]] = []
        self._history: list[dict[str, Any]] = []
        self._hash: str = ""
        self._calculate_hash()

    # ========================================================================
    # Property Accessors
    # ========================================================================
    @property
    def nsfp_id(self) -> UUID:
        return self._nsfp_id

    @property
    def nsfp_number(self) -> str:
        return self._nsfp_number

    @property
    def nsfp_number_masked(self) -> str:
        if len(self._nsfp_number) > 4:
            return f"{self._nsfp_number[:4]}...{self._nsfp_number[-4:]}"
        return self._nsfp_number

    @property
    def npwp(self) -> str:
        return self._npwp

    @property
    def tahun(self) -> int:
        return self._tahun

    @property
    def bulan(self) -> int:
        return self._bulan

    @property
    def status(self) -> NSFStatus:
        return self._status

    @property
    def allocated_to_faktur_id(self) -> UUID | None:
        return self._allocated_to_faktur_id

    @property
    def used_at(self) -> datetime | None:
        return self._used_at

    @property
    def expiry_date(self) -> date:
        return self._expiry_date

    @property
    def is_expired(self) -> bool:
        return date.today() > self._expiry_date

    @property
    def is_available(self) -> bool:
        return self._status == NSFStatus.AVAILABLE and not self.is_expired

    @property
    def is_allocated(self) -> bool:
        return self._status == NSFStatus.ALLOCATED

    @property
    def is_used(self) -> bool:
        return self._status == NSFStatus.USED

    @property
    def version(self) -> int:
        return self._version

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    @property
    def allocated_at(self) -> datetime | None:
        return self._allocated_at

    @property
    def released_at(self) -> datetime | None:
        return self._released_at

    @property
    def cancelled_at(self) -> datetime | None:
        return self._cancelled_at

    @property
    def locked_at(self) -> datetime | None:
        return self._locked_at

    @property
    def locked_by(self) -> UUID | None:
        return self._locked_by

    @property
    def is_locked(self) -> bool:
        return self._locked_at is not None

    @property
    def hash(self) -> str:
        return self._hash

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    def create(self, created_by: UUID) -> NSFP:
        self._validate_format()
        self._status = NSFStatus.AVAILABLE
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "nsfp_created",
            {
                "nsfp_id": str(self._nsfp_id),
                "nsfp_number": self.nsfp_number_masked,
                "npwp": self._npwp,
                "tahun": self._tahun,
                "bulan": self._bulan,
                "created_by": str(created_by),
            },
        )
        return self

    def update(self, data: dict[str, Any], updated_by: UUID) -> NSFP:
        if self.is_locked:
            raise NSFError(f"NSFP {self.nsfp_number_masked} is locked")
        if self._status not in [NSFStatus.AVAILABLE, NSFStatus.PENDING]:
            raise NSFError(f"Cannot modify NSFP in status {self._status.value}")
        old_data = self.to_dict()
        if "npwp" in data:
            self._npwp = data["npwp"]
        if "tahun" in data:
            self._tahun = data["tahun"]
        if "bulan" in data:
            self._bulan = data["bulan"]
        self._version += 1
        self._updated_at = datetime.now()
        self._calculate_hash()
        self._register_event(
            "nsfp_updated",
            {
                "nsfp_id": str(self._nsfp_id),
                "old_data": old_data,
                "new_data": self.to_dict(),
                "updated_by": str(updated_by),
            },
        )
        return self

    def delete(self, deleted_by: UUID, permanent: bool = False) -> NSFP:
        if self.is_locked:
            raise NSFError(f"NSFP {self.nsfp_number_masked} is locked")
        if permanent:
            self._status = NSFStatus.CANCELLED
            self._cancelled_at = datetime.now()
        else:
            self._status = NSFStatus.ARCHIVED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "nsfp_deleted",
            {
                "nsfp_id": str(self._nsfp_id),
                "permanent": permanent,
                "deleted_by": str(deleted_by),
            },
        )
        return self

    def restore(self, restored_by: UUID) -> NSFP:
        if self._status not in [NSFStatus.ARCHIVED, NSFStatus.CANCELLED]:
            raise NSFError(f"Cannot restore NSFP in status {self._status.value}")
        self._status = NSFStatus.AVAILABLE
        self._cancelled_at = None
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "nsfp_restored",
            {
                "nsfp_id": str(self._nsfp_id),
                "restored_by": str(restored_by),
            },
        )
        return self

    def activate(self, activated_by: UUID) -> NSFP:
        if self._status != NSFStatus.PENDING:
            raise NSFError(f"Cannot activate NSFP in status {self._status.value}")
        self._status = NSFStatus.AVAILABLE
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "nsfp_activated",
            {
                "nsfp_id": str(self._nsfp_id),
                "activated_by": str(activated_by),
            },
        )
        return self

    def deactivate(self, deactivated_by: UUID) -> NSFP:
        if self._status != NSFStatus.AVAILABLE:
            raise NSFError(f"Cannot deactivate NSFP in status {self._status.value}")
        self._status = NSFStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "nsfp_deactivated",
            {
                "nsfp_id": str(self._nsfp_id),
                "deactivated_by": str(deactivated_by),
            },
        )
        return self

    def lock(self, locked_by: UUID, reason: str = "") -> NSFP:
        if self.is_locked:
            raise NSFError(f"NSFP {self.nsfp_number_masked} already locked")
        self._locked_at = datetime.now()
        self._locked_by = locked_by
        self._status = NSFStatus.LOCKED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "nsfp_locked",
            {
                "nsfp_id": str(self._nsfp_id),
                "locked_by": str(locked_by),
                "reason": reason,
            },
        )
        return self

    def unlock(self, unlocked_by: UUID) -> NSFP:
        if not self.is_locked:
            raise NSFError(f"NSFP {self.nsfp_number_masked} is not locked")
        self._locked_at = None
        self._locked_by = None
        self._status = NSFStatus.AVAILABLE
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "nsfp_unlocked",
            {
                "nsfp_id": str(self._nsfp_id),
                "unlocked_by": str(unlocked_by),
            },
        )
        return self

    def allocate(self, faktur_id: UUID, allocated_by: UUID) -> NSFP:
        if self.is_locked:
            raise NSFAllocationError(f"NSFP {self.nsfp_number_masked} is locked")
        if not self.is_available:
            raise NSFAllocationError(f"NSFP {self.nsfp_number_masked} is not available (status: {self._status.value})")
        if self.is_expired:
            self._status = NSFStatus.EXPIRED
            raise NSFExpiredError(f"NSFP {self.nsfp_number_masked} has expired")
        self._allocated_to_faktur_id = faktur_id
        self._allocated_at = datetime.now()
        self._status = NSFStatus.ALLOCATED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "nsfp_allocated",
            {
                "nsfp_id": str(self._nsfp_id),
                "nsfp_number": self.nsfp_number_masked,
                "faktur_id": str(faktur_id),
                "allocated_by": str(allocated_by),
            },
        )
        return self

    def release(self, released_by: UUID, reason: str = "") -> NSFP:
        if self.is_locked:
            raise NSFError(f"NSFP {self.nsfp_number_masked} is locked")
        if self._status != NSFStatus.ALLOCATED:
            raise NSFError(f"Cannot release NSFP in status {self._status.value}")
        self._allocated_to_faktur_id = None
        self._released_at = datetime.now()
        self._status = NSFStatus.AVAILABLE
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "nsfp_released",
            {
                "nsfp_id": str(self._nsfp_id),
                "nsfp_number": self.nsfp_number_masked,
                "released_by": str(released_by),
                "reason": reason,
            },
        )
        return self

    def mark_as_used(self, used_by: UUID) -> NSFP:
        if self.is_locked:
            raise NSFError(f"NSFP {self.nsfp_number_masked} is locked")
        if self._status != NSFStatus.ALLOCATED:
            raise NSFError(f"Cannot mark NSFP as used in status {self._status.value}")
        self._used_at = datetime.now()
        self._status = NSFStatus.USED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "nsfp_marked_as_used",
            {
                "nsfp_id": str(self._nsfp_id),
                "nsfp_number": self.nsfp_number_masked,
                "used_by": str(used_by),
            },
        )
        return self

    def request_nsfp(self, requested_by: UUID, quantity: int) -> NSFP:
        self._status = NSFStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "nsfp_requested",
            {
                "nsfp_id": str(self._nsfp_id),
                "quantity": quantity,
                "requested_by": str(requested_by),
            },
        )
        return self

    def get_status(self) -> dict[str, Any]:
        return {
            "nsfp_id": str(self._nsfp_id),
            "nsfp_number": self.nsfp_number_masked,
            "status": self._status.value,
            "is_available": self.is_available,
            "is_allocated": self.is_allocated,
            "is_used": self.is_used,
            "is_expired": self.is_expired,
            "is_locked": self.is_locked,
            "allocated_to_faktur_id": str(self._allocated_to_faktur_id) if self._allocated_to_faktur_id else None,
            "expiry_date": self._expiry_date.isoformat(),
            "allocated_at": self._allocated_at.isoformat() if self._allocated_at else None,
            "used_at": self._used_at.isoformat() if self._used_at else None,
        }

    def get_history(self) -> list[dict[str, Any]]:
        return self._history.copy()

    def snapshot(self) -> dict[str, Any]:
        return {
            "nsfp_id": str(self._nsfp_id),
            "nsfp_number": self.nsfp_number,
            "nsfp_number_masked": self.nsfp_number_masked,
            "npwp": self._npwp,
            "tahun": self._tahun,
            "bulan": self._bulan,
            "status": self._status.value,
            "version": self._version,
            "created_at": self._created_at.isoformat(),
            "updated_at": self._updated_at.isoformat(),
            "allocated_at": self._allocated_at.isoformat() if self._allocated_at else None,
            "released_at": self._released_at.isoformat() if self._released_at else None,
            "used_at": self._used_at.isoformat() if self._used_at else None,
            "cancelled_at": self._cancelled_at.isoformat() if self._cancelled_at else None,
            "locked_at": self._locked_at.isoformat() if self._locked_at else None,
            "allocated_to_faktur_id": str(self._allocated_to_faktur_id) if self._allocated_to_faktur_id else None,
            "expiry_date": self._expiry_date.isoformat(),
            "hash": self._hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "nsfp_id": str(self._nsfp_id),
            "nsfp_number": self._nsfp_number,
            "npwp": self._npwp,
            "tahun": self._tahun,
            "bulan": self._bulan,
            "status": self._status.value,
            "version": self._version,
            "created_at": self._created_at.isoformat(),
            "updated_at": self._updated_at.isoformat(),
            "allocated_at": self._allocated_at.isoformat() if self._allocated_at else None,
            "released_at": self._released_at.isoformat() if self._released_at else None,
            "used_at": self._used_at.isoformat() if self._used_at else None,
            "cancelled_at": self._cancelled_at.isoformat() if self._cancelled_at else None,
            "locked_at": self._locked_at.isoformat() if self._locked_at else None,
            "allocated_to_faktur_id": str(self._allocated_to_faktur_id) if self._allocated_to_faktur_id else None,
            "expiry_date": self._expiry_date.isoformat(),
            "hash": self._hash,
            "is_expired": self.is_expired,
            "is_locked": self.is_locked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NSFP:
        return cls(
            nsfp_id=UUID(data["nsfp_id"]) if data.get("nsfp_id") else None,
            nsfp_number=data["nsfp_number"],
            npwp=data["npwp"],
            tahun=data["tahun"],
            bulan=data["bulan"],
            status=NSFStatus(data.get("status", "available")),
            allocated_to_faktur_id=UUID(data["allocated_to_faktur_id"]) if data.get("allocated_to_faktur_id") else None,
            used_at=datetime.fromisoformat(data["used_at"]) if data.get("used_at") else None,
            expiry_date=date.fromisoformat(data["expiry_date"]) if data.get("expiry_date") else None,
            version=data.get("version", 1),
        )

    def audit_trail(self) -> list[dict[str, Any]]:
        return self._history.copy()

    def can_transition(self, new_status: NSFStatus) -> bool:
        transitions = {
            NSFStatus.PENDING: [NSFStatus.AVAILABLE, NSFStatus.CANCELLED, NSFStatus.ARCHIVED],
            NSFStatus.AVAILABLE: [NSFStatus.ALLOCATED, NSFStatus.PENDING, NSFStatus.LOCKED, NSFStatus.EXPIRED, NSFStatus.ARCHIVED],
            NSFStatus.ALLOCATED: [NSFStatus.USED, NSFStatus.AVAILABLE, NSFStatus.CANCELLED],
            NSFStatus.USED: [NSFStatus.ARCHIVED],
            NSFStatus.EXPIRED: [NSFStatus.ARCHIVED],
            NSFStatus.CANCELLED: [NSFStatus.ARCHIVED],
            NSFStatus.LOCKED: [NSFStatus.AVAILABLE],
            NSFStatus.ARCHIVED: [],
        }
        return new_status in transitions.get(self._status, [])

    def transition(self, new_status: NSFStatus, actor_id: UUID, reason: str = "") -> NSFP:
        if not self.can_transition(new_status):
            raise NSFError(f"Status transition invalid: {self._status.value} -> {new_status.value}")
        old_status = self._status
        self._status = new_status
        self._updated_at = datetime.now()
        self._version += 1
        self._history.append(
            {
                "from_status": old_status.value,
                "to_status": new_status.value,
                "actor_id": str(actor_id),
                "reason": reason,
                "timestamp": datetime.now().isoformat(),
            }
        )
        self._register_event(
            "nsfp_status_changed",
            {
                "nsfp_id": str(self._nsfp_id),
                "from_status": old_status.value,
                "to_status": new_status.value,
                "actor_id": str(actor_id),
                "reason": reason,
            },
        )
        return self

    def register_event(self, event_type: str, event_data: dict[str, Any]) -> NSFP:
        return self._register_event(event_type, event_data)

    def _register_event(self, event_type: str, event_data: dict[str, Any]) -> NSFP:
        self._events.append(
            {
                "event_id": str(uuid4()),
                "event_type": event_type,
                "aggregate_id": str(self._nsfp_id),
                "aggregate_type": "NSFP",
                "occurred_at": datetime.now().isoformat(),
                "data": event_data,
            }
        )
        return self

    def get_events(self) -> list[dict[str, Any]]:
        return self._events.copy()

    def clear_events(self) -> NSFP:
        self._events.clear()
        return self

    def version(self) -> int:
        return self._version

    def validate_nsfp(self) -> bool:
        return self._validate_format()

    def is_available_for_period(self, tahun: int, bulan: int) -> bool:
        return self.is_available and self._tahun == tahun and self._bulan == bulan

    def check_expiry(self) -> bool:
        if self.is_expired and self._status not in [NSFStatus.USED, NSFStatus.CANCELLED, NSFStatus.ARCHIVED]:
            self._status = NSFStatus.EXPIRED
            self._updated_at = datetime.now()
            self._version += 1
            self._register_event(
                "nsfp_expired",
                {
                    "nsfp_id": str(self._nsfp_id),
                    "nsfp_number": self.nsfp_number_masked,
                    "expiry_date": self._expiry_date.isoformat(),
                },
            )
            return True
        return False

    def _validate_format(self) -> bool:
        import re
        if not re.match(NSFP_PATTERN, self._nsfp_number):
            raise NSFInvalidFormatError(f"Invalid NSFP format: {self._nsfp_number}. Must be 8 digits.")
        return True

    def _calculate_expiry_date(self, tahun: int, bulan: int) -> date:
        if bulan + 2 > 12:
            expiry_year = tahun + 1
            expiry_month = bulan + 2 - 12
        else:
            expiry_year = tahun
            expiry_month = bulan + 2
        if expiry_month == 12:
            last_day = 31
        elif expiry_month in [4, 6, 9, 11]:
            last_day = 30
        elif expiry_month == 2:
            if expiry_year % 4 == 0 and (expiry_year % 100 != 0 or expiry_year % 400 == 0):
                last_day = 29
            else:
                last_day = 28
        else:
            last_day = 31
        return date(expiry_year, expiry_month, last_day)

    def _calculate_hash(self) -> None:
        data = f"{self._nsfp_id}{self._nsfp_number}{self._npwp}{self._tahun}{self._bulan}{self._status.value}{self._version}"
        self._hash = hashlib.sha256(data.encode()).hexdigest()


# ============================================================================
# REPOSITORY INTERFACE
# ============================================================================
class NSFPRepositoryPort:
    async def add(self, nsfp: NSFP) -> None:
        raise NotImplementedError
    async def save(self, nsfp: NSFP) -> None:
        raise NotImplementedError
    async def update(self, nsfp: NSFP) -> None:
        raise NotImplementedError
    async def delete(self, nsfp_id: UUID) -> None:
        raise NotImplementedError
    async def get_by_id(self, nsfp_id: UUID) -> NSFP | None:
        raise NotImplementedError
    async def get_by_number(self, nsfp_number: str) -> NSFP | None:
        raise NotImplementedError
    async def get_by_npwp_period(self, npwp: str, tahun: int, bulan: int) -> list[NSFP]:
        raise NotImplementedError
    async def get_available_by_period(self, npwp: str, tahun: int, bulan: int) -> list[NSFP]:
        raise NotImplementedError
    async def get_by_status(self, status: NSFStatus) -> list[NSFP]:
        raise NotImplementedError
    async def get_allocated_by_faktur(self, faktur_id: UUID) -> NSFP | None:
        raise NotImplementedError
    async def count_available(self, npwp: str, tahun: int, bulan: int) -> int:
        raise NotImplementedError
    async def mark_as_used(self, nsfp_id: UUID, used_at: datetime) -> None:
        raise NotImplementedError
    async def batch_add(self, nsfp_list: list[NSFP]) -> None:
        raise NotImplementedError


class _FallbackNSFPRepository(NSFPRepositoryPort):
    def __init__(self):
        self._store: dict[UUID, NSFP] = {}
        self._by_number: dict[str, UUID] = {}
        self._by_faktur: dict[UUID, UUID] = {}

    async def add(self, nsfp: NSFP) -> None:
        self._store[nsfp.nsfp_id] = nsfp
        self._by_number[nsfp.nsfp_number] = nsfp.nsfp_id

    async def save(self, nsfp: NSFP) -> None:
        self._store[nsfp.nsfp_id] = nsfp

    async def update(self, nsfp: NSFP) -> None:
        self._store[nsfp.nsfp_id] = nsfp

    async def delete(self, nsfp_id: UUID) -> None:
        if nsfp_id in self._store:
            nsfp = self._store[nsfp_id]
            if nsfp.nsfp_number in self._by_number:
                del self._by_number[nsfp.nsfp_number]
            del self._store[nsfp_id]

    async def get_by_id(self, nsfp_id: UUID) -> NSFP | None:
        return self._store.get(nsfp_id)

    async def get_by_number(self, nsfp_number: str) -> NSFP | None:
        nsfp_id = self._by_number.get(nsfp_number)
        if nsfp_id:
            return self._store.get(nsfp_id)
        return None

    async def get_by_npwp_period(self, npwp: str, tahun: int, bulan: int) -> list[NSFP]:
        return [n for n in self._store.values() if n.npwp == npwp and n.tahun == tahun and n.bulan == bulan]

    async def get_available_by_period(self, npwp: str, tahun: int, bulan: int) -> list[NSFP]:
        return [n for n in self._store.values() if n.npwp == npwp and n.tahun == tahun and n.bulan == bulan and n.is_available]

    async def get_by_status(self, status: NSFStatus) -> list[NSFP]:
        return [n for n in self._store.values() if n.status == status]

    async def get_allocated_by_faktur(self, faktur_id: UUID) -> NSFP | None:
        nsfp_id = self._by_faktur.get(faktur_id)
        if nsfp_id:
            return self._store.get(nsfp_id)
        return None

    async def count_available(self, npwp: str, tahun: int, bulan: int) -> int:
        return len([n for n in self._store.values() if n.npwp == npwp and n.tahun == tahun and n.bulan == bulan and n.is_available])

    async def mark_as_used(self, nsfp_id: UUID, used_at: datetime) -> None:
        nsfp = self._store.get(nsfp_id)
        if nsfp:
            nsfp.mark_as_used(UUID(int=0))

    async def batch_add(self, nsfp_list: list[NSFP]) -> None:
        for nsfp in nsfp_list:
            await self.add(nsfp)


# ============================================================================
# NSFP MANAGER
# ============================================================================
class NSFPManager:
    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._coretax_client = None
        self._repository = _FallbackNSFPRepository()
        self._redis_client = None
        self._lock = asyncio.Lock()
        self._cache: dict[str, Any] = {}
        self._test_stock: dict[str, list[str]] = {}
        self._test_used: dict[str, set[str]] = {}
        self._test_next_number = 1

    def _load_config(self) -> dict[str, Any]:
        if self._config:
            return self._config
        return {
            "coretax_djp": {
                "nsfp": {
                    "request_batch_size": DEFAULT_NSFP_REQUEST_BATCH_SIZE,
                    "low_watermark": DEFAULT_NSFP_LOW_WATERMARK,
                    "critical_watermark": DEFAULT_NSFP_CRITICAL_WATERMARK,
                    "high_watermark": DEFAULT_NSFP_HIGH_WATERMARK,
                    "auto_request_enabled": True,
                    "cache_ttl_seconds": CACHE_TTL_SECONDS,
                    "max_retry_attempts": MAX_RETRY_ATTEMPTS,
                }
            }
        }

    async def _get_redis(self):
        if self._redis_client is None:
            try:
                from infrastructure.caching.redis_manager import get_redis_client
                self._redis_client = await get_redis_client()
            except ImportError:
                logger.warning("Redis not available, using in-memory storage for NSFP")
                self._redis_client = None
        return self._redis_client

    async def _get_coretax_client(self):
        if self._coretax_client is None:
            self._coretax_client = await get_coretax_client()
        return self._coretax_client

    def _get_redis_available_key(self, npwp: str, tahun: int, bulan: int) -> str:
        return f"{REDIS_NSFP_AVAILABLE_PREFIX}{npwp}:{tahun}:{bulan:02d}"

    def _get_redis_allocated_key(self, faktur_id: UUID) -> str:
        return f"{REDIS_NSFP_ALLOCATED_PREFIX}{faktur_id}"

    def _get_test_key(self, npwp: str, tahun: int, bulan: int) -> str:
        return f"{npwp}:{tahun}:{bulan:02d}"

    def _get_cache_key(self, npwp: str, tahun: int, bulan: int) -> str:
        return f"nsfp_quota:{npwp}:{tahun}:{bulan:02d}"

    async def _get_cached(self, cache_key: str) -> dict[str, Any] | None:
        ttl = self._load_config().get("coretax_djp", {}).get("nsfp", {}).get("cache_ttl_seconds", CACHE_TTL_SECONDS)
        return self._cache.get(cache_key)

    async def _set_cached(self, cache_key: str, data: dict[str, Any]) -> None:
        ttl = self._load_config().get("coretax_djp", {}).get("nsfp", {}).get("cache_ttl_seconds", CACHE_TTL_SECONDS)
        self._cache[cache_key] = data

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    async def create(self, nsfp_data: dict[str, Any], created_by: UUID) -> dict[str, Any]:
        nsfp = NSFP(
            nsfp_number=nsfp_data["nsfp_number"],
            npwp=nsfp_data["npwp"],
            tahun=nsfp_data["tahun"],
            bulan=nsfp_data["bulan"],
            status=NSFStatus.AVAILABLE,
        )
        nsfp.create(created_by)
        await self._repository.add(nsfp)
        return {
            "success": True,
            "nsfp_id": str(nsfp.nsfp_id),
            "nsfp_number": nsfp.nsfp_number_masked,
            "status": nsfp.status.value,
        }

    async def allocate_nsfp(self, npwp: str, tahun: int, bulan: int, faktur_id: UUID, allocated_by: UUID) -> dict[str, Any]:
        async with self._lock:
            redis = await self._get_redis()
            key = self._get_redis_available_key(npwp, tahun, bulan)
            nsfp_number = None
            if redis:
                nsfp_bytes = await redis.lpop(key)
                if nsfp_bytes is None:
                    await self.refill_nsfp_stock(npwp, tahun, bulan)
                    nsfp_bytes = await redis.lpop(key)
                if nsfp_bytes:
                    nsfp_number = nsfp_bytes.decode()
                else:
                    raise NSFNotAvailableError(f"No NSFP available for {npwp} {tahun}-{bulan:02d}")
            else:
                test_key = self._get_test_key(npwp, tahun, bulan)
                stock = self._test_stock.get(test_key, [])
                if not stock:
                    await self.refill_nsfp_stock(npwp, tahun, bulan)
                    stock = self._test_stock.get(test_key, [])
                if stock:
                    nsfp_number = stock.pop(0)
                else:
                    raise NSFNotAvailableError(f"No NSFP available for {npwp} {tahun}-{bulan:02d}")
            nsfp = await self._repository.get_by_number(nsfp_number)
            if nsfp:
                nsfp.allocate(faktur_id, allocated_by)
                await self._repository.update(nsfp)
            else:
                nsfp = NSFP(
                    nsfp_number=nsfp_number,
                    npwp=npwp,
                    tahun=tahun,
                    bulan=bulan,
                )
                nsfp.create(allocated_by)
                nsfp.allocate(faktur_id, allocated_by)
                await self._repository.add(nsfp)
            if redis:
                allocated_key = self._get_redis_allocated_key(faktur_id)
                await redis.setex(allocated_key, 86400 * 30, nsfp_number)
            logger.info(f"Allocated NSFP {nsfp_number} for faktur {faktur_id}")
            return {
                "success": True,
                "nsfp_number": nsfp_number,
                "nsfp_number_masked": nsfp.nsfp_number_masked,
                "faktur_id": str(faktur_id),
            }

    async def release_nsfp(self, nsfp_number: str, npwp: str, tahun: int, bulan: int, released_by: UUID, reason: str = "") -> dict[str, Any]:
        async with self._lock:
            redis = await self._get_redis()
            key = self._get_redis_available_key(npwp, tahun, bulan)
            if redis:
                await redis.lpush(key, nsfp_number)
            else:
                test_key = self._get_test_key(npwp, tahun, bulan)
                self._test_stock.setdefault(test_key, []).insert(0, nsfp_number)
            nsfp = await self._repository.get_by_number(nsfp_number)
            if nsfp:
                nsfp.release(released_by, reason)
                await self._repository.update(nsfp)
            logger.info(f"Released NSFP {nsfp_number[:8]}... back to stock")
            return {"success": True, "nsfp_number": nsfp_number, "released": True}

    async def get_next_nsfp(self, npwp: str, tahun: int, bulan: int, faktur_id: UUID, allocated_by: UUID) -> dict[str, Any]:
        return await self.allocate_nsfp(npwp, tahun, bulan, faktur_id, allocated_by)

    async def request_nsfp_from_djp(self, npwp: str, tahun: int, bulan: int, jumlah: int, requested_by: UUID) -> dict[str, Any]:
        client = await self._get_coretax_client()
        payload = {"npwp": npwp, "tahun": tahun, "bulan": bulan, "jumlah": jumlah}
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                response = await client.post(CORETAX_NSFP_REQUEST_ENDPOINT, payload)
                if response.get("status") == "success":
                    nsfp_list = response.get("nsfp_list", [])
                    for nsfp_number in nsfp_list:
                        nsfp = NSFP(
                            nsfp_number=nsfp_number,
                            npwp=npwp,
                            tahun=tahun,
                            bulan=bulan,
                            status=NSFStatus.AVAILABLE,
                        )
                        nsfp.request_nsfp(requested_by, jumlah)
                        await self._repository.add(nsfp)
                    cache_key = self._get_cache_key(npwp, tahun, bulan)
                    if cache_key in self._cache:
                        del self._cache[cache_key]
                    return {
                        "success": True,
                        "nsfp_list": [n[:8] + "..." + n[-4:] for n in nsfp_list],
                        "jumlah": len(nsfp_list),
                        "request_id": response.get("request_id"),
                    }
                else:
                    return {"success": False, "error": response.get("message", "Request failed")}
            except CoretaxAuthError as e:
                logger.error(f"Coretax auth error (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    return {"success": False, "error": f"Authentication failed: {e}"}
            except Exception as e:
                logger.exception(f"Failed to request NSFP (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    return {"success": False, "error": str(e)}
        return {"success": False, "error": "Max retries exceeded"}

    async def refill_nsfp_stock(self, npwp: str, tahun: int, bulan: int, force: bool = False) -> dict[str, Any]:
        async with self._lock:
            current_stock = await self.get_available_count(npwp, tahun, bulan)
            low = self._load_config().get("coretax_djp", {}).get("nsfp", {}).get("low_watermark", DEFAULT_NSFP_LOW_WATERMARK)
            high = self._load_config().get("coretax_djp", {}).get("nsfp", {}).get("high_watermark", DEFAULT_NSFP_HIGH_WATERMARK)
            critical = self._load_config().get("coretax_djp", {}).get("nsfp", {}).get("critical_watermark", DEFAULT_NSFP_CRITICAL_WATERMARK)
            batch = self._load_config().get("coretax_djp", {}).get("nsfp", {}).get("request_batch_size", DEFAULT_NSFP_REQUEST_BATCH_SIZE)
            status = "critical" if current_stock <= critical else "low" if current_stock <= low else "sufficient"
            if current_stock <= low or force:
                needed = max(high - current_stock, batch)
                request_count = min(needed, batch)
                logger.info(f"Refilling NSFP for {npwp} {tahun}-{bulan:02d}: current={current_stock}, requesting={request_count}, status={status}")
                try:
                    result = await self.request_nsfp_from_djp(npwp, tahun, bulan, request_count, UUID(int=0))
                    if result.get("success"):
                        nsfp_list = result.get("nsfp_list", [])
                        nsfp_numbers = [n.replace("...", "").replace("-", "") for n in nsfp_list]
                        redis = await self._get_redis()
                        key = self._get_redis_available_key(npwp, tahun, bulan)
                        if redis:
                            await redis.rpush(key, *nsfp_numbers)
                            if bulan + 2 > 12:
                                expiry_year = tahun + 1
                                expiry_month = bulan + 2 - 12
                            else:
                                expiry_year = tahun
                                expiry_month = bulan + 2
                            await redis.expireat(key, datetime(expiry_year, expiry_month, 1))
                        else:
                            test_key = self._get_test_key(npwp, tahun, bulan)
                            self._test_stock.setdefault(test_key, []).extend(nsfp_numbers)
                        return {"success": True, "added_count": len(nsfp_numbers), "requested_count": request_count, "status": status}
                    else:
                        return {"success": False, "error": result.get("error", "Refill failed"), "status": status}
                except Exception as e:
                    logger.error(f"NSFP refill failed: {e}")
                    return {"success": False, "error": str(e), "status": status}
            return {"success": True, "message": f"Stock sufficient: {current_stock}", "status": status, "current_stock": current_stock}

    async def get_available_count(self, npwp: str, tahun: int, bulan: int) -> int:
        redis = await self._get_redis()
        if redis:
            key = self._get_redis_available_key(npwp, tahun, bulan)
            return await redis.llen(key)
        else:
            test_key = self._get_test_key(npwp, tahun, bulan)
            return len(self._test_stock.get(test_key, []))

    async def get_quota_info(self, npwp: str, tahun: int, bulan: int, refresh: bool = False) -> dict[str, Any]:
        cache_key = self._get_cache_key(npwp, tahun, bulan)
        if not refresh:
            cached = await self._get_cached(cache_key)
            if cached:
                return cached
        client = await self._get_coretax_client()
        endpoint = f"{CORETAX_NSFP_QUOTA_ENDPOINT}/{npwp}/{tahun}/{bulan:02d}"
        try:
            response = await client.get(endpoint)
            available_in_cache = await self.get_available_count(npwp, tahun, bulan)
            result = {
                "success": True,
                "total_quota": response.get("total_quota", 0),
                "used": response.get("used", 0),
                "remaining": response.get("remaining", 0),
                "available_in_cache": available_in_cache,
                "low_watermark": self._load_config().get("coretax_djp", {}).get("nsfp", {}).get("low_watermark", DEFAULT_NSFP_LOW_WATERMARK),
                "critical_watermark": self._load_config().get("coretax_djp", {}).get("nsfp", {}).get("critical_watermark", DEFAULT_NSFP_CRITICAL_WATERMARK),
                "high_watermark": self._load_config().get("coretax_djp", {}).get("nsfp", {}).get("high_watermark", DEFAULT_NSFP_HIGH_WATERMARK),
                "is_low": available_in_cache <= DEFAULT_NSFP_LOW_WATERMARK,
                "is_critical": available_in_cache <= DEFAULT_NSFP_CRITICAL_WATERMARK,
            }
            await self._set_cached(cache_key, result)
            return result
        except Exception as e:
            logger.error(f"Failed to get quota info: {e}")
            return {"success": False, "error": str(e)}

    async def preload_nsfp_for_upcoming_months(self, npwp: str, months_ahead: int = 3) -> dict[str, Any]:
        today = date.today()
        results = []
        for month_offset in range(1, months_ahead + 1):
            target_date = today.replace(day=1) + timedelta(days=32 * month_offset)
            tahun = target_date.year
            bulan = target_date.month
            result = await self.refill_nsfp_stock(npwp, tahun, bulan)
            results.append({"tahun": tahun, "bulan": bulan, "status": result.get("status", "unknown"), "added_count": result.get("added_count", 0)})
        return {"success": True, "npwp": npwp, "preloaded_months": results}

    async def sync_with_coretax(self, npwp: str, tahun: int, bulan: int) -> dict[str, Any]:
        client = await self._get_coretax_client()
        endpoint = f"{CORETAX_NSFP_SYNC_ENDPOINT}/{npwp}/{tahun}/{bulan:02d}"
        try:
            response = await client.get(endpoint)
            remote_quota = response.get("remaining_quota", 0)
            local_count = await self.get_available_count(npwp, tahun, bulan)
            cache_key = self._get_cache_key(npwp, tahun, bulan)
            if cache_key in self._cache:
                del self._cache[cache_key]
            return {
                "success": True,
                "npwp": npwp,
                "tahun": tahun,
                "bulan": bulan,
                "remote_quota": remote_quota,
                "local_available": local_count,
                "is_synced": abs(remote_quota - local_count) < 100,
                "synced_at": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Failed to sync NSFP: {e}")
            return {"success": False, "error": str(e)}

    async def validate_nsfp(self, nsfp_number: str, npwp: str) -> dict[str, Any]:
        client = await self._get_coretax_client()
        endpoint = f"{CORETAX_NSFP_VALIDATE_ENDPOINT}/{npwp}/{nsfp_number}"
        try:
            response = await client.get(endpoint)
            return {
                "success": True,
                "nsfp_number": nsfp_number,
                "is_valid": response.get("is_valid", False),
                "is_used": response.get("is_used", False),
                "message": response.get("message", ""),
            }
        except Exception as e:
            logger.error(f"Failed to validate NSFP: {e}")
            return {"success": False, "error": str(e)}

    async def mark_nsfp_as_used(self, nsfp_number: str, faktur_id: UUID, used_by: UUID) -> dict[str, Any]:
        nsfp = await self._repository.get_by_number(nsfp_number)
        if nsfp:
            nsfp.mark_as_used(used_by)
            await self._repository.update(nsfp)
            client = await self._get_coretax_client()
            payload = {"nsfp_number": nsfp_number, "faktur_id": str(faktur_id)}
            try:
                await client.post(CORETAX_NSFP_USAGE_ENDPOINT, payload)
            except Exception as e:
                logger.warning(f"Failed to mark NSFP as used in Coretax: {e}")
            return {"success": True, "nsfp_number": nsfp_number, "marked_as_used": True}
        else:
            return {"success": False, "error": "NSFP not found"}

    async def get_status(self, nsfp_number: str) -> dict[str, Any]:
        nsfp = await self._repository.get_by_number(nsfp_number)
        if not nsfp:
            return {"success": False, "error": "NSFP not found"}
        return nsfp.get_status()

    async def get_history(self, nsfp_number: str) -> dict[str, Any]:
        nsfp = await self._repository.get_by_number(nsfp_number)
        if not nsfp:
            return {"success": False, "error": "NSFP not found"}
        return {"success": True, "nsfp_number": nsfp.nsfp_number_masked, "history": nsfp.get_history()}

    async def get_by_id(self, nsfp_id: UUID) -> NSFP | None:
        return await self._repository.get_by_id(nsfp_id)

    async def get_by_number(self, nsfp_number: str) -> NSFP | None:
        return await self._repository.get_by_number(nsfp_number)

    async def get_allocated_by_faktur(self, faktur_id: UUID) -> NSFP | None:
        return await self._repository.get_allocated_by_faktur(faktur_id)

    # ========================================================================
    # Batch Operations
    # ========================================================================
    async def batch_allocate(self, allocations: list[dict[str, Any]], allocated_by: UUID) -> list[dict[str, Any]]:
        results = []
        for alloc in allocations:
            result = await self.allocate_nsfp(
                npwp=alloc["npwp"],
                tahun=alloc["tahun"],
                bulan=alloc["bulan"],
                faktur_id=alloc["faktur_id"],
                allocated_by=allocated_by,
            )
            results.append(result)
        return results

    async def auto_refill_all(self, npwp_list: list[str], tahun: int, bulan: int) -> dict[str, Any]:
        results = {}
        for npwp in npwp_list:
            result = await self.refill_nsfp_stock(npwp, tahun, bulan)
            results[npwp] = result
        return {"success": True, "results": results, "refilled_at": datetime.now().isoformat()}

    # ========================================================================
    # Health Check
    # ========================================================================
    async def health_check(self, npwp: str, tahun: int, bulan: int) -> dict[str, Any]:
        available = await self.get_available_count(npwp, tahun, bulan)
        quota_info = await self.get_quota_info(npwp, tahun, bulan, refresh=True)
        low = self._load_config().get("coretax_djp", {}).get("nsfp", {}).get("low_watermark", DEFAULT_NSFP_LOW_WATERMARK)
        critical = self._load_config().get("coretax_djp", {}).get("nsfp", {}).get("critical_watermark", DEFAULT_NSFP_CRITICAL_WATERMARK)
        status = "critical" if available <= critical else "warning" if available <= low else "healthy"
        return {
            "success": True,
            "npwp": npwp,
            "tahun": tahun,
            "bulan": bulan,
            "available_count": available,
            "status": status,
            "low_watermark": low,
            "critical_watermark": critical,
            "quota_info": quota_info,
            "timestamp": datetime.now().isoformat(),
        }

    # ========================================================================
    # Legacy / Test Methods
    # ========================================================================
    def request_new_range(self, quantity: int) -> Any:
        from types import SimpleNamespace
        start = self._test_next_number
        end = start + quantity - 1
        self._test_next_number = end + 1
        today = date.today()
        npwp = "123456789012345"
        test_key = self._get_test_key(npwp, today.year, today.month)
        nsfp_list = [str(i).zfill(8) for i in range(start, end + 1)]
        self._test_stock.setdefault(test_key, []).extend(nsfp_list)
        return SimpleNamespace(start=start, end=end)

    def get_next(self) -> str:
        today = date.today()
        npwp = "123456789012345"
        test_key = self._get_test_key(npwp, today.year, today.month)
        stock = self._test_stock.get(test_key, [])
        if not stock:
            self.request_new_range(10)
            stock = self._test_stock.get(test_key, [])
        if not stock:
            raise NSFNotAvailableError("No NSFP available")
        return stock.pop(0)

    def use(self, nsfp: str) -> bool:
        if not hasattr(self, "_test_used_set"):
            self._test_used_set = set()
        if nsfp in self._test_used_set:
            raise NSFDuplicateError("NSFP sudah digunakan")
        self._test_used_set.add(nsfp)
        return True


# ============================================================================
# SINGLETON
# ============================================================================
_nsfp_manager: NSFPManager | None = None

async def get_nsfp_manager(config: dict | None = None) -> NSFPManager:
    global _nsfp_manager
    if _nsfp_manager is None:
        _nsfp_manager = NSFPManager(config=config)
    return _nsfp_manager

async def get_nsfp():
    return await get_nsfp_manager()

__all__ = [
    "NSFP",
    "NSFAllocationError",
    "NSFDuplicateError",
    "NSFError",
    "NSFExpiredError",
    "NSFInvalidFormatError",
    "NSFNotAvailableError",
    "NSFNotFoundError",
    "NSFPManager",
    "NSFPRepositoryPort",
    "NSFQuotaExhaustedError",
    "NSFStatus",
    "get_nsfp",
    "get_nsfp_manager",
]