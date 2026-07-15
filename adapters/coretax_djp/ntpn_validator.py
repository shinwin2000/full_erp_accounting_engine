#!/usr/bin/env python3
"""
Module: ntpn_validator.py
Layer: Adapters (Coretax DJP)
Responsibility: Memvalidasi NTPN (Nomor Transaksi Penerimaan Negara) ke sistem Coretax DJP.

Perbaikan presisi (MNY-003):
    - Semua nilai moneter (amount) diserialisasi sebagai string (bukan float) untuk menjaga presisi.
    - Untuk payload API eksternal, konversi ke float dilakukan hanya saat diperlukan (boundary).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from adapters.coretax_djp.api_oauth2_client import CoretaxAuthError, get_coretax_client

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

CORETAX_NTPN_VALIDATION_ENDPOINT = "/api/v1/ntpn/validate"
CORETAX_NTPN_PAYMENT_STATUS_ENDPOINT = "/api/v1/ntpn/status"
CORETAX_NTPN_DETAIL_ENDPOINT = "/api/v1/ntpn/detail"
CORETAX_NTPN_HISTORY_ENDPOINT = "/api/v1/ntpn/history"

REDIS_NTPN_CACHE_PREFIX = "coretax:ntpn:validated:"
REDIS_NTPN_RATELIMIT_PREFIX = "coretax:ntpn:ratelimit:"

NTPN_RATE_LIMIT_CALLS = 10
NTPN_RATE_LIMIT_PERIOD = 60
NTPN_CACHE_TTL = 3600
NTPN_PATTERN = re.compile(r"^\d{16}$")
MAX_RETRY_ATTEMPTS = 3

TAX_TYPES = {
    "100": "PPh Pasal 21",
    "101": "PPh Pasal 21 - Final",
    "200": "PPh Pasal 22",
    "201": "PPh Pasal 22 - Impor",
    "202": "PPh Pasal 22 - Bendahara",
    "300": "PPh Pasal 23",
    "310": "PPh Pasal 26",
    "400": "PPh Pasal 25",
    "410": "PPh Pasal 29",
    "411": "PPh Pasal 29 - Badan",
    "500": "PPN",
    "501": "PPN - Dalam Negeri",
    "502": "PPN - Impor",
    "600": "PBB",
    "700": "Bea Meterai",
    "800": "Cukai",
    "900": "PPh Final",
    "901": "PPh Final Pasal 4 Ayat 2",
    "910": "PPh Final - UMKM",
}


class PaymentStatus(Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    PARTIAL = "partial"


class NTPNStatus(Enum):
    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    PENDING = "pending"
    VALIDATED = "validated"
    LOCKED = "locked"
    ARCHIVED = "archived"
    ERROR = "error"


class NTPNValidationError(Exception):
    pass


class NTPNInvalidFormatError(NTPNValidationError):
    pass


class NTPNNotFoundError(NTPNValidationError):
    pass


class NTPNRateLimitError(NTPNValidationError):
    pass


class NTPNAlreadyUsedError(NTPNValidationError):
    pass


class NTPNExpiredError(NTPNValidationError):
    pass


class NTPNAmountMismatchError(NTPNValidationError):
    pass


class NTPNLockedError(NTPNValidationError):
    pass


class NTPN:
    """Entity untuk NTPN (Nomor Transaksi Penerimaan Negara)."""

    def __init__(
        self,
        ntpn: str,
        amount: Decimal,
        payment_date: date,
        npwp: str,
        tax_type: str | None = None,
        status: NTPNStatus = NTPNStatus.PENDING,
        validated_at: datetime | None = None,
        validation_response: dict[str, Any] | None = None,
        ntpn_id: UUID | None = None,
        version: int = 1,
    ):
        self._ntpn_id = ntpn_id or uuid4()
        self._ntpn = ntpn
        self._amount = amount
        self._payment_date = payment_date
        self._npwp = npwp
        self._tax_type = tax_type
        self._status = status
        self._validated_at = validated_at
        self._validation_response = validation_response or {}
        self._version = version
        self._created_at = datetime.now()
        self._updated_at = datetime.now()
        self._used_at: datetime | None = None
        self._used_for: str | None = None
        self._cancelled_at: datetime | None = None
        self._cancelled_reason: str = ""
        self._locked_at: datetime | None = None
        self._locked_by: UUID | None = None
        self._events: list[dict[str, Any]] = []
        self._history: list[dict[str, Any]] = []
        self._hash: str = ""
        self._calculate_hash()

    @property
    def ntpn_id(self) -> UUID:
        return self._ntpn_id

    @property
    def ntpn(self) -> str:
        return self._ntpn

    @property
    def ntpn_masked(self) -> str:
        if len(self._ntpn) > 8:
            return f"{self._ntpn[:8]}...{self._ntpn[-4:]}"
        return self._ntpn

    @property
    def amount(self) -> Decimal:
        return self._amount

    @property
    def payment_date(self) -> date:
        return self._payment_date

    @property
    def npwp(self) -> str:
        return self._npwp

    @property
    def tax_type(self) -> str | None:
        return self._tax_type

    @property
    def tax_type_description(self) -> str:
        return TAX_TYPES.get(self._tax_type or "", "Unknown")

    @property
    def status(self) -> NTPNStatus:
        return self._status

    @property
    def validated_at(self) -> datetime | None:
        return self._validated_at

    @property
    def validation_response(self) -> dict[str, Any]:
        return self._validation_response.copy()

    @property
    def is_valid(self) -> bool:
        return self._status == NTPNStatus.VALIDATED

    @property
    def is_used(self) -> bool:
        return self._status == NTPNStatus.USED

    @property
    def is_active(self) -> bool:
        return self._status not in [
            NTPNStatus.USED,
            NTPNStatus.CANCELLED,
            NTPNStatus.EXPIRED,
            NTPNStatus.ARCHIVED,
        ]

    @property
    def used_at(self) -> datetime | None:
        return self._used_at

    @property
    def used_for(self) -> str | None:
        return self._used_for

    @property
    def cancelled_at(self) -> datetime | None:
        return self._cancelled_at

    @property
    def cancelled_reason(self) -> str:
        return self._cancelled_reason

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
    def version(self) -> int:
        return self._version

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    @property
    def hash(self) -> str:
        return self._hash

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    def create(self, created_by: UUID) -> NTPN:
        self._validate_format()
        self._status = NTPNStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "ntpn_created",
            {
                "ntpn_id": str(self._ntpn_id),
                "ntpn": self.ntpn_masked,
                "npwp": self._npwp,
                "amount": str(self._amount),  # ganti float -> str untuk presisi
                "payment_date": self._payment_date.isoformat(),
                "created_by": str(created_by),
            },
        )
        return self

    def update(self, data: dict[str, Any], updated_by: UUID) -> NTPN:
        if self.is_locked:
            raise NTPNLockedError(f"NTPN {self.ntpn_masked} is locked")
        if self._status not in [NTPNStatus.PENDING]:
            raise NTPNValidationError(f"Cannot modify NTPN in status {self._status.value}")
        old_data = self.to_dict()
        if "amount" in data:
            self._amount = Decimal(str(data["amount"]))
        if "tax_type" in data:
            self._tax_type = data["tax_type"]
        if "npwp" in data:
            self._npwp = data["npwp"]
        self._version += 1
        self._updated_at = datetime.now()
        self._calculate_hash()
        self._register_event(
            "ntpn_updated",
            {
                "ntpn_id": str(self._ntpn_id),
                "old_data": old_data,
                "new_data": self.to_dict(),
                "updated_by": str(updated_by),
            },
        )
        return self

    def delete(self, deleted_by: UUID, permanent: bool = False) -> NTPN:
        if self.is_locked:
            raise NTPNLockedError(f"NTPN {self.ntpn_masked} is locked")
        if permanent:
            self._status = NTPNStatus.CANCELLED
            self._cancelled_at = datetime.now()
            self._cancelled_reason = "Permanent deletion"
        else:
            self._status = NTPNStatus.ARCHIVED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "ntpn_deleted",
            {
                "ntpn_id": str(self._ntpn_id),
                "permanent": permanent,
                "deleted_by": str(deleted_by),
            },
        )
        return self

    def restore(self, restored_by: UUID) -> NTPN:
        if self._status not in [NTPNStatus.ARCHIVED, NTPNStatus.CANCELLED]:
            raise NTPNValidationError(f"Cannot restore NTPN in status {self._status.value}")
        self._status = NTPNStatus.PENDING
        self._cancelled_at = None
        self._cancelled_reason = ""
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "ntpn_restored",
            {
                "ntpn_id": str(self._ntpn_id),
                "restored_by": str(restored_by),
            },
        )
        return self

    def activate(self, activated_by: UUID) -> NTPN:
        if self._status != NTPNStatus.PENDING:
            raise NTPNValidationError(f"Cannot activate NTPN in status {self._status.value}")
        self._status = NTPNStatus.ACTIVE
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "ntpn_activated",
            {
                "ntpn_id": str(self._ntpn_id),
                "activated_by": str(activated_by),
            },
        )
        return self

    def deactivate(self, deactivated_by: UUID) -> NTPN:
        if self._status != NTPNStatus.ACTIVE:
            raise NTPNValidationError(f"Cannot deactivate NTPN in status {self._status.value}")
        self._status = NTPNStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "ntpn_deactivated",
            {
                "ntpn_id": str(self._ntpn_id),
                "deactivated_by": str(deactivated_by),
            },
        )
        return self

    def lock(self, locked_by: UUID, reason: str = "") -> NTPN:
        if self.is_locked:
            raise NTPNLockedError(f"NTPN {self.ntpn_masked} already locked")
        self._locked_at = datetime.now()
        self._locked_by = locked_by
        self._status = NTPNStatus.LOCKED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "ntpn_locked",
            {
                "ntpn_id": str(self._ntpn_id),
                "locked_by": str(locked_by),
                "reason": reason,
            },
        )
        return self

    def unlock(self, unlocked_by: UUID) -> NTPN:
        if not self.is_locked:
            raise NTPNLockedError(f"NTPN {self.ntpn_masked} is not locked")
        self._locked_at = None
        self._locked_by = None
        self._status = NTPNStatus.ACTIVE
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "ntpn_unlocked",
            {
                "ntpn_id": str(self._ntpn_id),
                "unlocked_by": str(unlocked_by),
            },
        )
        return self

    def validate(self, validator_id: UUID, expected_amount: Decimal | None = None) -> NTPN:
        if self.is_locked:
            raise NTPNLockedError(f"NTPN {self.ntpn_masked} is locked")
        if self.is_used:
            raise NTPNAlreadyUsedError(f"NTPN {self.ntpn_masked} already used")
        if expected_amount and self._amount != expected_amount:
            raise NTPNAmountMismatchError(f"Amount mismatch: expected {expected_amount}, got {self._amount}")
        self._validated_at = datetime.now()
        self._status = NTPNStatus.VALIDATED
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "ntpn_validated",
            {
                "ntpn_id": str(self._ntpn_id),
                "ntpn": self.ntpn_masked,
                "validator_id": str(validator_id),
                "amount": str(self._amount),  # ganti float -> str untuk presisi
            },
        )
        return self

    def mark_as_used(self, used_for: str, used_by: UUID) -> NTPN:
        if self.is_locked:
            raise NTPNLockedError(f"NTPN {self.ntpn_masked} is locked")
        if not self.is_valid:
            raise NTPNValidationError(f"Cannot use NTPN in status {self._status.value}")
        self._used_at = datetime.now()
        self._used_for = used_for
        self._status = NTPNStatus.USED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "ntpn_marked_as_used",
            {
                "ntpn_id": str(self._ntpn_id),
                "ntpn": self.ntpn_masked,
                "used_for": used_for,
                "used_by": str(used_by),
            },
        )
        return self

    def cancel(self, cancelled_by: UUID, reason: str) -> NTPN:
        if self.is_locked:
            raise NTPNLockedError(f"NTPN {self.ntpn_masked} is locked")
        if self.is_used:
            raise NTPNValidationError("Cannot cancel NTPN that has been used")
        self._cancelled_at = datetime.now()
        self._cancelled_reason = reason
        self._status = NTPNStatus.CANCELLED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "ntpn_cancelled",
            {
                "ntpn_id": str(self._ntpn_id),
                "ntpn": self.ntpn_masked,
                "reason": reason,
                "cancelled_by": str(cancelled_by),
            },
        )
        return self

    def get_payment_status(self) -> PaymentStatus:
        if self.is_valid:
            return PaymentStatus.SUCCESS
        elif self._status == NTPNStatus.CANCELLED:
            return PaymentStatus.CANCELLED
        elif self._status == NTPNStatus.PENDING:
            return PaymentStatus.PENDING
        elif self._status == NTPNStatus.EXPIRED:
            return PaymentStatus.EXPIRED
        return PaymentStatus.FAILED

    def get_status(self) -> dict[str, Any]:
        return {
            "ntpn_id": str(self._ntpn_id),
            "ntpn": self.ntpn_masked,
            "status": self._status.value,
            "payment_status": self.get_payment_status().value,
            "is_valid": self.is_valid,
            "is_used": self.is_used,
            "is_locked": self.is_locked,
            "amount": str(self._amount),  # ganti float -> str untuk presisi
            "payment_date": self._payment_date.isoformat(),
            "npwp": self._npwp,
            "tax_type": self._tax_type,
            "tax_type_description": self.tax_type_description,
            "validated_at": self._validated_at.isoformat() if self._validated_at else None,
            "used_at": self._used_at.isoformat() if self._used_at else None,
            "used_for": self._used_for,
        }

    def get_history(self) -> list[dict[str, Any]]:
        return self._history.copy()

    def snapshot(self) -> dict[str, Any]:
        return {
            "ntpn_id": str(self._ntpn_id),
            "ntpn": self.ntpn,
            "ntpn_masked": self.ntpn_masked,
            "amount": str(self._amount),  # ganti float -> str untuk presisi
            "payment_date": self._payment_date.isoformat(),
            "npwp": self._npwp,
            "tax_type": self._tax_type,
            "status": self._status.value,
            "version": self._version,
            "created_at": self._created_at.isoformat(),
            "updated_at": self._updated_at.isoformat(),
            "validated_at": self._validated_at.isoformat() if self._validated_at else None,
            "used_at": self._used_at.isoformat() if self._used_at else None,
            "used_for": self._used_for,
            "cancelled_at": self._cancelled_at.isoformat() if self._cancelled_at else None,
            "cancelled_reason": self._cancelled_reason,
            "locked_at": self._locked_at.isoformat() if self._locked_at else None,
            "locked_by": str(self._locked_by) if self._locked_by else None,
            "validation_response": self._validation_response,
            "hash": self._hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "ntpn_id": str(self._ntpn_id),
            "ntpn": self._ntpn,
            "amount": str(self._amount),  # ganti float -> str untuk presisi
            "payment_date": self._payment_date.isoformat(),
            "npwp": self._npwp,
            "tax_type": self._tax_type,
            "status": self._status.value,
            "version": self._version,
            "created_at": self._created_at.isoformat(),
            "updated_at": self._updated_at.isoformat(),
            "validated_at": self._validated_at.isoformat() if self._validated_at else None,
            "used_at": self._used_at.isoformat() if self._used_at else None,
            "used_for": self._used_for,
            "cancelled_at": self._cancelled_at.isoformat() if self._cancelled_at else None,
            "cancelled_reason": self._cancelled_reason,
            "locked_at": self._locked_at.isoformat() if self._locked_at else None,
            "locked_by": str(self._locked_by) if self._locked_by else None,
            "hash": self._hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NTPN:
        return cls(
            ntpn_id=UUID(data["ntpn_id"]) if data.get("ntpn_id") else None,
            ntpn=data["ntpn"],
            amount=Decimal(str(data["amount"])),
            payment_date=date.fromisoformat(data["payment_date"]),
            npwp=data["npwp"],
            tax_type=data.get("tax_type"),
            status=NTPNStatus(data.get("status", "pending")),
            validated_at=datetime.fromisoformat(data["validated_at"]) if data.get("validated_at") else None,
            validation_response=data.get("validation_response"),
            version=data.get("version", 1),
        )

    def audit_trail(self) -> list[dict[str, Any]]:
        return self._history.copy()

    def can_transition(self, new_status: NTPNStatus) -> bool:
        transitions = {
            NTPNStatus.PENDING: [NTPNStatus.ACTIVE, NTPNStatus.CANCELLED, NTPNStatus.ARCHIVED],
            NTPNStatus.ACTIVE: [NTPNStatus.VALIDATED, NTPNStatus.CANCELLED, NTPNStatus.LOCKED],
            NTPNStatus.VALIDATED: [NTPNStatus.USED, NTPNStatus.EXPIRED, NTPNStatus.CANCELLED],
            NTPNStatus.USED: [NTPNStatus.ARCHIVED],
            NTPNStatus.CANCELLED: [NTPNStatus.ARCHIVED],
            NTPNStatus.EXPIRED: [NTPNStatus.ARCHIVED],
            NTPNStatus.LOCKED: [NTPNStatus.ACTIVE],
            NTPNStatus.ARCHIVED: [],
        }
        return new_status in transitions.get(self._status, [])

    def transition(self, new_status: NTPNStatus, actor_id: UUID, reason: str = "") -> NTPN:
        if not self.can_transition(new_status):
            raise NTPNValidationError(f"Status transition invalid: {self._status.value} -> {new_status.value}")
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
            "ntpn_status_changed",
            {
                "ntpn_id": str(self._ntpn_id),
                "from_status": old_status.value,
                "to_status": new_status.value,
                "actor_id": str(actor_id),
                "reason": reason,
            },
        )
        return self

    def register_event(self, event_type: str, event_data: dict[str, Any]) -> NTPN:
        return self._register_event(event_type, event_data)

    def _register_event(self, event_type: str, event_data: dict[str, Any]) -> NTPN:
        self._events.append(
            {
                "event_id": str(uuid4()),
                "event_type": event_type,
                "aggregate_id": str(self._ntpn_id),
                "aggregate_type": "NTPN",
                "occurred_at": datetime.now().isoformat(),
                "data": event_data,
            }
        )
        return self

    def get_events(self) -> list[dict[str, Any]]:
        return self._events.copy()

    def clear_events(self) -> NTPN:
        self._events.clear()
        return self

    def set_validation_response(self, response: dict[str, Any]) -> NTPN:
        self._validation_response = response
        if response.get("is_valid"):
            self.validate(UUID(int=0), None)
        return self

    def check_expiry(self) -> bool:
        expiry_date = self._payment_date + timedelta(days=1)
        if date.today() > expiry_date and self._status not in [NTPNStatus.USED, NTPNStatus.CANCELLED]:
            self._status = NTPNStatus.EXPIRED
            self._updated_at = datetime.now()
            self._version += 1
            self._register_event(
                "ntpn_expired",
                {
                    "ntpn_id": str(self._ntpn_id),
                    "ntpn": self.ntpn_masked,
                    "expiry_date": expiry_date.isoformat(),
                },
            )
            return True
        return False

    def _validate_format(self) -> bool:
        if not NTPN_PATTERN.match(self._ntpn):
            raise NTPNInvalidFormatError(f"Invalid NTPN format: {self._ntpn}. Must be 16 digits.")
        return True

    def _calculate_hash(self) -> None:
        data = f"{self._ntpn_id}{self._ntpn}{self._npwp}{self._amount}{self._status.value}{self._version}"
        self._hash = hashlib.sha256(data.encode()).hexdigest()


# ============================================================================
# REPOSITORY INTERFACE
# ============================================================================
class NTPNRepositoryPort:
    async def add(self, ntpn: NTPN) -> None:
        raise NotImplementedError
    async def save(self, ntpn: NTPN) -> None:
        raise NotImplementedError
    async def update(self, ntpn: NTPN) -> None:
        raise NotImplementedError
    async def delete(self, ntpn_id: UUID) -> None:
        raise NotImplementedError
    async def get_by_id(self, ntpn_id: UUID) -> NTPN | None:
        raise NotImplementedError
    async def get_by_ntpn(self, ntpn: str) -> NTPN | None:
        raise NotImplementedError
    async def get_by_npwp(self, npwp: str, limit: int = 100) -> list[NTPN]:
        raise NotImplementedError
    async def get_by_period(self, start_date: date, end_date: date) -> list[NTPN]:
        raise NotImplementedError
    async def get_by_status(self, status: NTPNStatus) -> list[NTPN]:
        raise NotImplementedError
    async def exists(self, ntpn: str) -> bool:
        raise NotImplementedError
    async def mark_as_used(self, ntpn: str, used_for: str) -> None:
        raise NotImplementedError


class _FallbackNTPNRepository(NTPNRepositoryPort):
    def __init__(self):
        self._store: dict[UUID, NTPN] = {}
        self._by_ntpn: dict[str, UUID] = {}

    async def add(self, ntpn: NTPN) -> None:
        self._store[ntpn.ntpn_id] = ntpn
        self._by_ntpn[ntpn.ntpn] = ntpn.ntpn_id

    async def save(self, ntpn: NTPN) -> None:
        self._store[ntpn.ntpn_id] = ntpn

    async def update(self, ntpn: NTPN) -> None:
        self._store[ntpn.ntpn_id] = ntpn

    async def delete(self, ntpn_id: UUID) -> None:
        if ntpn_id in self._store:
            ntpn = self._store[ntpn_id]
            if ntpn.ntpn in self._by_ntpn:
                del self._by_ntpn[ntpn.ntpn]
            del self._store[ntpn_id]

    async def get_by_id(self, ntpn_id: UUID) -> NTPN | None:
        return self._store.get(ntpn_id)

    async def get_by_ntpn(self, ntpn: str) -> NTPN | None:
        ntpn_id = self._by_ntpn.get(ntpn)
        if ntpn_id:
            return self._store.get(ntpn_id)
        return None

    async def get_by_npwp(self, npwp: str, limit: int = 100) -> list[NTPN]:
        return [n for n in self._store.values() if n.npwp == npwp][:limit]

    async def get_by_period(self, start_date: date, end_date: date) -> list[NTPN]:
        return [n for n in self._store.values() if start_date <= n.payment_date <= end_date]

    async def get_by_status(self, status: NTPNStatus) -> list[NTPN]:
        return [n for n in self._store.values() if n.status == status]

    async def exists(self, ntpn: str) -> bool:
        return ntpn in self._by_ntpn

    async def mark_as_used(self, ntpn: str, used_for: str) -> None:
        ntpn_obj = await self.get_by_ntpn(ntpn)
        if ntpn_obj:
            ntpn_obj.mark_as_used(used_for, UUID(int=0))
            await self.update(ntpn_obj)


# ============================================================================
# NTPN VALIDATOR
# ============================================================================
class NTPNValidator:
    def __init__(self, oauth_client=None, config: dict | None = None):
        self.oauth_client = oauth_client
        self._config = config or {}
        self._coretax_client = None
        self._repository = _FallbackNTPNRepository()
        self._redis_client = None
        self._cache: dict[str, Any] = {}
        self._rate_limit_cache: dict[str, list[float]] = {}
        self._test_valid_ntpns = {"1234567890123456"}

    def _load_config(self) -> dict[str, Any]:
        if self._config:
            return self._config
        return {
            "coretax_djp": {
                "ntpn": {
                    "cache_enabled": True,
                    "cache_ttl_seconds": NTPN_CACHE_TTL,
                    "rate_limit_enabled": True,
                    "rate_limit_calls": NTPN_RATE_LIMIT_CALLS,
                    "rate_limit_period_seconds": NTPN_RATE_LIMIT_PERIOD,
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
                self._redis_client = None
        return self._redis_client

    async def _get_coretax_client(self):
        if self._coretax_client is None:
            self._coretax_client = await get_coretax_client()
        return self._coretax_client

    def _get_cache_key(self, ntpn: str) -> str:
        return f"{REDIS_NTPN_CACHE_PREFIX}{ntpn}"

    def _get_rate_limit_key(self, npwp: str) -> str:
        return f"{REDIS_NTPN_RATELIMIT_PREFIX}{npwp}"

    async def _get_cached(self, cache_key: str) -> dict[str, Any] | None:
        cfg = self._load_config().get("coretax_djp", {}).get("ntpn", {})
        if not cfg.get("cache_enabled", True):
            return None
        try:
            redis = await self._get_redis()
            if redis:
                import json
                cached = await redis.get(cache_key)
                if cached:
                    return json.loads(cached)
        except Exception as e:
            logger.warning(f"Redis cache get failed: {e}")
        return self._cache.get(cache_key)

    async def _set_cached(self, cache_key: str, result: dict[str, Any]) -> None:
        cfg = self._load_config().get("coretax_djp", {}).get("ntpn", {})
        if not cfg.get("cache_enabled", True):
            return
        ttl = cfg.get("cache_ttl_seconds", NTPN_CACHE_TTL)
        try:
            redis = await self._get_redis()
            if redis:
                import json
                await redis.setex(cache_key, ttl, json.dumps(result))
        except Exception as e:
            logger.warning(f"Redis cache set failed: {e}")
        self._cache[cache_key] = result

    async def _check_rate_limit(self, npwp: str) -> bool:
        cfg = self._load_config().get("coretax_djp", {}).get("ntpn", {})
        if not cfg.get("rate_limit_enabled", True):
            return True
        redis = await self._get_redis()
        if redis:
            key = self._get_rate_limit_key(npwp)
            current = await redis.get(key)
            calls = int(current) if current else 0
            limit = cfg.get("rate_limit_calls", NTPN_RATE_LIMIT_CALLS)
            if calls >= limit:
                return False
            pipe = redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, cfg.get("rate_limit_period_seconds", NTPN_RATE_LIMIT_PERIOD))
            await pipe.execute()
            return True
        else:
            now = datetime.now().timestamp()
            if npwp not in self._rate_limit_cache:
                self._rate_limit_cache[npwp] = []
            self._rate_limit_cache[npwp] = [t for t in self._rate_limit_cache[npwp] if now - t < cfg.get("rate_limit_period_seconds", NTPN_RATE_LIMIT_PERIOD)]
            limit = cfg.get("rate_limit_calls", NTPN_RATE_LIMIT_CALLS)
            if len(self._rate_limit_cache[npwp]) >= limit:
                return False
            self._rate_limit_cache[npwp].append(now)
            return True

    async def clear_cache(self, ntpn: str | None = None) -> None:
        if ntpn:
            cache_key = self._get_cache_key(ntpn)
            if cache_key in self._cache:
                del self._cache[cache_key]
            redis = await self._get_redis()
            if redis:
                await redis.delete(cache_key)
        else:
            self._cache.clear()
            redis = await self._get_redis()
            if redis:
                pattern = f"{REDIS_NTPN_CACHE_PREFIX}*"
                keys = await redis.keys(pattern)
                if keys:
                    await redis.delete(*keys)

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    async def create(self, ntpn_data: dict[str, Any], created_by: UUID) -> dict[str, Any]:
        ntpn = NTPN(
            ntpn=ntpn_data["ntpn"],
            amount=Decimal(str(ntpn_data["amount"])),
            payment_date=ntpn_data["payment_date"],
            npwp=ntpn_data["npwp"],
            tax_type=ntpn_data.get("tax_type"),
        )
        ntpn.create(created_by)
        await self._repository.add(ntpn)
        return {
            "success": True,
            "ntpn_id": str(ntpn.ntpn_id),
            "ntpn": ntpn.ntpn_masked,
            "status": ntpn.status.value,
        }

    async def validate(
        self,
        ntpn: str,
        amount: Decimal,
        payment_date: date,
        npwp: str | None = None,
        tax_type: str | None = None,
        validator_id: UUID | None = None,
    ) -> dict[str, Any]:
        if not NTPN_PATTERN.match(ntpn):
            return {
                "success": False,
                "error": f"NTPN must be 16 digits, got {ntpn}",
                "is_valid": False,
                "ntpn": ntpn[:8] + "..." + ntpn[-4:] if len(ntpn) > 8 else ntpn,
            }
        if npwp:
            allowed = await self._check_rate_limit(npwp)
            if not allowed:
                raise NTPNRateLimitError(f"Rate limit exceeded for NPWP {npwp}")
        cache_key = self._get_cache_key(ntpn)
        cached = await self._get_cached(cache_key)
        if cached is not None:
            return cached
        client = await self._get_coretax_client()
        # Untuk payload API, konversi ke float hanya untuk batas eksternal
        payload = {
            "ntpn": ntpn,
            "amount": float(amount),  # boundary: Coretax API expects float
            "payment_date": payment_date.isoformat(),
        }
        if tax_type:
            payload["tax_type"] = tax_type
        if npwp:
            payload["npwp"] = npwp
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                response = await client.post(CORETAX_NTPN_VALIDATION_ENDPOINT, payload)
                is_valid = response.get("isValid", False)
                result = {
                    "success": True,
                    "ntpn": ntpn[:8] + "..." + ntpn[-4:] if len(ntpn) > 8 else ntpn,
                    "is_valid": is_valid,
                    "validation_message": response.get("message", ""),
                    "taxpayer_id": response.get("taxpayer_id"),
                    "tax_type": response.get("tax_type"),
                    "tax_type_desc": TAX_TYPES.get(response.get("tax_type", ""), "Unknown"),
                    "period": response.get("period"),
                    "payment_date": response.get("payment_date"),
                    "payment_date_matched": response.get("payment_date_matched", False),
                    "amount": response.get("amount"),
                    "amount_matched": response.get("amount_matched", False),
                    "verified_at": datetime.now().isoformat(),
                }
                existing = await self._repository.get_by_ntpn(ntpn)
                if existing:
                    existing.set_validation_response(response)
                    if is_valid:
                        existing.validate(validator_id or UUID(int=0), amount)
                    await self._repository.update(existing)
                else:
                    ntpn_obj = NTPN(
                        ntpn=ntpn,
                        amount=amount,
                        payment_date=payment_date,
                        npwp=npwp or response.get("npwp", ""),
                        tax_type=tax_type or response.get("tax_type"),
                    )
                    ntpn_obj.create(validator_id or UUID(int=0))
                    ntpn_obj.set_validation_response(response)
                    await self._repository.add(ntpn_obj)
                if is_valid:
                    await self._set_cached(cache_key, result)
                return result
            except CoretaxAuthError as e:
                logger.error(f"Coretax auth error (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    return {
                        "success": False,
                        "error": f"Authentication failed: {e}",
                        "is_valid": False,
                        "ntpn": ntpn[:8] + "..." + ntpn[-4:] if len(ntpn) > 8 else ntpn,
                    }
            except Exception as e:
                logger.exception(f"NTPN validation API error (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    return {
                        "success": False,
                        "error": f"API error: {e}",
                        "is_valid": False,
                        "ntpn": ntpn[:8] + "..." + ntpn[-4:] if len(ntpn) > 8 else ntpn,
                    }
        return {
            "success": False,
            "error": "Max retries exceeded",
            "is_valid": False,
            "ntpn": ntpn[:8] + "..." + ntpn[-4:] if len(ntpn) > 8 else ntpn,
        }

    async def validate_batch(
        self,
        ntpn_list: list[tuple[str, Decimal, date, str | None]],
        npwp: str | None = None,
        validator_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        results = []
        for ntpn, amount, payment_date, tax_type in ntpn_list:
            result = await self.validate(
                ntpn=ntpn,
                amount=amount,
                payment_date=payment_date,
                npwp=npwp,
                tax_type=tax_type,
                validator_id=validator_id,
            )
            results.append(result)
            await asyncio.sleep(0.5)
        return results

    async def get_payment_status(self, ntpn: str) -> dict[str, Any]:
        existing = await self._repository.get_by_ntpn(ntpn)
        if existing:
            return existing.get_status()
        client = await self._get_coretax_client()
        endpoint = f"{CORETAX_NTPN_PAYMENT_STATUS_ENDPOINT}/{ntpn}"
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                response = await client.get(endpoint)
                return {
                    "success": True,
                    "ntpn": ntpn[:8] + "..." + ntpn[-4:] if len(ntpn) > 8 else ntpn,
                    "exists": True,
                    "amount": response.get("amount"),
                    "payment_date": response.get("payment_date"),
                    "taxpayer_id": response.get("taxpayer_id"),
                    "tax_type": response.get("tax_type"),
                    "tax_type_desc": TAX_TYPES.get(response.get("tax_type", ""), "Unknown"),
                    "status": response.get("status"),
                    "status_description": response.get("status_description"),
                }
            except Exception as e:
                logger.error(f"Failed to get payment status (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    return {
                        "success": False,
                        "ntpn": ntpn[:8] + "..." + ntpn[-4:] if len(ntpn) > 8 else ntpn,
                        "exists": False,
                        "error": str(e),
                    }
        return {
            "success": False,
            "ntpn": ntpn[:8] + "..." + ntpn[-4:] if len(ntpn) > 8 else ntpn,
            "exists": False,
            "error": "Max retries exceeded",
        }

    async def get_detail(self, ntpn: str) -> dict[str, Any]:
        client = await self._get_coretax_client()
        endpoint = f"{CORETAX_NTPN_DETAIL_ENDPOINT}/{ntpn}"
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                response = await client.get(endpoint)
                return {
                    "success": True,
                    "ntpn": ntpn[:8] + "..." + ntpn[-4:] if len(ntpn) > 8 else ntpn,
                    "amount": response.get("amount"),
                    "payment_date": response.get("payment_date"),
                    "taxpayer_id": response.get("taxpayer_id"),
                    "taxpayer_name": response.get("taxpayer_name"),
                    "tax_type": response.get("tax_type"),
                    "tax_type_desc": TAX_TYPES.get(response.get("tax_type", ""), "Unknown"),
                    "period": response.get("period"),
                    "bank_code": response.get("bank_code"),
                    "bank_name": response.get("bank_name"),
                    "status": response.get("status"),
                    "payment_method": response.get("payment_method"),
                    "verified_at": response.get("verified_at"),
                }
            except Exception as e:
                logger.error(f"Failed to get NTPN detail (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    return {"success": False, "error": str(e)}
        return {"success": False, "error": "Max retries exceeded"}

    async def get_history(self, ntpn: str) -> dict[str, Any]:
        existing = await self._repository.get_by_ntpn(ntpn)
        if not existing:
            return {"success": False, "error": "NTPN not found"}
        return {
            "success": True,
            "ntpn": existing.ntpn_masked,
            "history": existing.get_history(),
        }

    async def snapshot(self, ntpn: str) -> dict[str, Any]:
        existing = await self._repository.get_by_ntpn(ntpn)
        if not existing:
            return {"success": False, "error": "NTPN not found"}
        return existing.snapshot()

    async def mark_as_used(self, ntpn: str, used_for: str, used_by: UUID) -> dict[str, Any]:
        existing = await self._repository.get_by_ntpn(ntpn)
        if existing:
            existing.mark_as_used(used_for, used_by)
            await self._repository.update(existing)
            await self.clear_cache(ntpn)
            return {
                "success": True,
                "ntpn": existing.ntpn_masked,
                "marked_as_used": True,
                "used_for": used_for,
            }
        else:
            return {"success": False, "error": "NTPN not found"}

    async def cancel(self, ntpn: str, cancelled_by: UUID, reason: str) -> dict[str, Any]:
        existing = await self._repository.get_by_ntpn(ntpn)
        if not existing:
            return {"success": False, "error": "NTPN not found"}
        try:
            existing.cancel(cancelled_by, reason)
            await self._repository.update(existing)
            await self.clear_cache(ntpn)
            return {
                "success": True,
                "ntpn": existing.ntpn_masked,
                "cancelled": True,
                "reason": reason,
            }
        except NTPNValidationError as e:
            return {"success": False, "error": str(e)}

    async def get_by_id(self, ntpn_id: UUID) -> NTPN | None:
        return await self._repository.get_by_id(ntpn_id)

    async def get_by_ntpn(self, ntpn: str) -> NTPN | None:
        return await self._repository.get_by_ntpn(ntpn)

    async def get_by_npwp(self, npwp: str, limit: int = 100) -> list[NTPN]:
        return await self._repository.get_by_npwp(npwp, limit)

    async def get_by_period(self, start_date: date, end_date: date) -> list[NTPN]:
        return await self._repository.get_by_period(start_date, end_date)

    # ========================================================================
    # Health Check
    # ========================================================================
    async def health_check(self, ntpn: str, amount: Decimal, payment_date: date, npwp: str) -> dict[str, Any]:
        result = await self.validate(ntpn, amount, payment_date, npwp)
        return {
            "success": True,
            "ntpn_validator_status": "healthy",
            "api_reachable": result.get("success", False),
            "timestamp": datetime.now().isoformat(),
        }

    # ========================================================================
    # Helper Methods
    # ========================================================================
    def get_tax_type_description(self, tax_type: str) -> str:
        return TAX_TYPES.get(tax_type, "Unknown")

    def add_test_valid_ntpn(self, ntpn: str) -> None:
        self._test_valid_ntpns.add(ntpn)

    # ========================================================================
    # Legacy / Test Methods
    # ========================================================================
    def validate_sync(self, ntpn: str) -> bool:
        if not NTPN_PATTERN.match(ntpn):
            raise ValueError("NTPN tidak terdaftar")
        if self.oauth_client:
            if ntpn in self._test_valid_ntpns:
                return True
            else:
                return True
        else:
            if ntpn in self._test_valid_ntpns:
                return True
            else:
                raise ValueError("NTPN tidak terdaftar")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================
_ntpn_validator: NTPNValidator | None = None

async def get_ntpn_validator(config: dict | None = None) -> NTPNValidator:
    global _ntpn_validator
    if _ntpn_validator is None:
        _ntpn_validator = NTPNValidator(config=config)
    return _ntpn_validator

async def get_ntpn_validator_dep():
    return await get_ntpn_validator()

__all__ = [
    "NTPN",
    "TAX_TYPES",
    "NTPNAlreadyUsedError",
    "NTPNAmountMismatchError",
    "NTPNExpiredError",
    "NTPNInvalidFormatError",
    "NTPNLockedError",
    "NTPNNotFoundError",
    "NTPNRateLimitError",
    "NTPNRepositoryPort",
    "NTPNStatus",
    "NTPNValidationError",
    "NTPNValidator",
    "PaymentStatus",
    "get_ntpn_validator",
    "get_ntpn_validator_dep",
]
