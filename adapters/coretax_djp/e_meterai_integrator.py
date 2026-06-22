#!/usr/bin/env python3
"""
Module: e_meterai_integrator.py
Layer: Adapters (Coretax DJP)
Responsibility: Mengintegrasikan e-Meterai (bea meterai elektronik) dengan sistem
               Coretax DJP. Bertanggung jawab untuk memvalidasi e-Meterai,
               mengecek status, dan melakukan pembelian e-Meterai melalui API Coretax.
"""
from __future__ import annotations

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

CORETAX_EMETERAI_VALIDATE_ENDPOINT = "/api/v1/e-meterai/validate"
CORETAX_EMETERAI_PURCHASE_ENDPOINT = "/api/v1/e-meterai/purchase"
CORETAX_EMETERAI_STOCK_ENDPOINT = "/api/v1/e-meterai/stock"
CORETAX_EMETERAI_USE_ENDPOINT = "/api/v1/e-meterai/use"
CORETAX_EMETERAI_REVOKE_ENDPOINT = "/api/v1/e-meterai/revoke"
CORETAX_EMETERAI_HISTORY_ENDPOINT = "/api/v1/e-meterai/history"

EMETERAI_PATTERN = re.compile(r"^\d{16}-\d{4}$")
METERRY_VALUE = Decimal("10000")
MAX_RETRY_ATTEMPTS = 3
CACHE_TTL_SECONDS = 3600
DEFAULT_AUTO_PURCHASE_THRESHOLD = 50
DEFAULT_AUTO_PURCHASE_QUANTITY = 200
EMETERAI_EXPIRY_DAYS = 365

REDIS_EMETERAI_CACHE_PREFIX = "coretax:e-meterai:validated:"
REDIS_EMETERAI_RATELIMIT_PREFIX = "coretax:e-meterai:ratelimit:"
REDIS_EMETERAI_STOCK_PREFIX = "coretax:e-meterai:stock:"


class EMeteraiStatus(Enum):
    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"
    REVOKED = "revoked"
    PENDING = "pending"
    PURCHASED = "purchased"
    ALLOCATED = "allocated"
    VOID = "void"
    ARCHIVED = "archived"
    LOCKED = "locked"
    ERROR = "error"


EMETERAI_STATUS = {
    "ACTIVE": EMeteraiStatus.ACTIVE.value,
    "USED": EMeteraiStatus.USED.value,
    "EXPIRED": EMeteraiStatus.EXPIRED.value,
    "REVOKED": EMeteraiStatus.REVOKED.value,
    "PENDING": EMeteraiStatus.PENDING.value,
}

METERAI_REQUIRED_DOCUMENTS = {
    "invoice": "Faktur Pajak",
    "contract": "Kontrak/Perjanjian",
    "agreement": "Perjanjian",
    "deed": "Akta Notaris",
    "court_document": "Dokumen Pengadilan",
    "share_certificate": "Sertifikat Saham",
}

METERAI_THRESHOLD = Decimal("5000000")


class EMeteraiError(Exception):
    """Base exception untuk e-Meterai."""
    pass


class EMeteraiNotFoundError(EMeteraiError):
    pass


class EMeteraiInvalidError(EMeteraiError):
    pass


class EMeteraiUsedError(EMeteraiError):
    pass


class EMeteraiExpiredError(EMeteraiError):
    pass


class EMeteraiInsufficientStockError(EMeteraiError):
    pass


class EMeteraiLockedError(EMeteraiError):
    pass


class EMeteraiAlreadyAttachedError(EMeteraiError):
    pass


class EMeterai:
    """Entity untuk e-Meterai (Bea Meterai Elektronik)."""

    def __init__(
        self,
        meterai_code: str,
        npwp: str,
        status: EMeteraiStatus = EMeteraiStatus.PENDING,
        value: Decimal = METERRY_VALUE,
        purchased_at: datetime | None = None,
        used_at: datetime | None = None,
        used_on_document: str | None = None,
        used_on_document_type: str | None = None,
        expiry_date: date | None = None,
        transaction_id: str | None = None,
        meterai_id: UUID | None = None,
        version: int = 1,
    ):
        self._meterai_id = meterai_id or uuid4()
        self._meterai_code = meterai_code
        self._npwp = npwp
        self._value = value
        self._status = status
        self._purchased_at = purchased_at or datetime.now()
        self._used_at = used_at
        self._used_on_document = used_on_document
        self._used_on_document_type = used_on_document_type
        self._expiry_date = expiry_date or (date.today() + timedelta(days=EMETERAI_EXPIRY_DAYS))
        self._transaction_id = transaction_id
        self._version = version
        self._created_at = datetime.now()
        self._updated_at = datetime.now()
        self._validated_at: datetime | None = None
        self._revoked_at: datetime | None = None
        self._revoked_reason: str = ""
        self._locked_at: datetime | None = None
        self._locked_by: UUID | None = None
        self._validation_response: dict[str, Any] = {}
        self._purchase_response: dict[str, Any] = {}
        self._events: list[dict[str, Any]] = []
        self._history: list[dict[str, Any]] = []
        self._hash: str = ""
        self._calculate_hash()

    @property
    def meterai_id(self) -> UUID:
        return self._meterai_id

    @property
    def meterai_code(self) -> str:
        return self._meterai_code

    @property
    def meterai_code_masked(self) -> str:
        if len(self._meterai_code) > 8:
            return f"{self._meterai_code[:8]}...{self._meterai_code[-4:]}"
        return self._meterai_code

    @property
    def npwp(self) -> str:
        return self._npwp

    @property
    def value(self) -> Decimal:
        return self._value

    @property
    def status(self) -> EMeteraiStatus:
        return self._status

    @property
    def purchased_at(self) -> datetime | None:
        return self._purchased_at

    @property
    def used_at(self) -> datetime | None:
        return self._used_at

    @property
    def used_on_document(self) -> str | None:
        return self._used_on_document

    @property
    def used_on_document_type(self) -> str | None:
        return self._used_on_document_type

    @property
    def expiry_date(self) -> date:
        return self._expiry_date

    @property
    def transaction_id(self) -> str | None:
        return self._transaction_id

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
    def validated_at(self) -> datetime | None:
        return self._validated_at

    @property
    def revoked_at(self) -> datetime | None:
        return self._revoked_at

    @property
    def revoked_reason(self) -> str:
        return self._revoked_reason

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
    def is_active(self) -> bool:
        return self._status == EMeteraiStatus.ACTIVE

    @property
    def is_used(self) -> bool:
        return self._status == EMeteraiStatus.USED

    @property
    def is_expired(self) -> bool:
        return date.today() > self._expiry_date or self._status == EMeteraiStatus.EXPIRED

    @property
    def is_valid(self) -> bool:
        return self._status == EMeteraiStatus.ACTIVE and not self.is_expired

    @property
    def hash(self) -> str:
        return self._hash

    @property
    def validation_response(self) -> dict[str, Any]:
        return self._validation_response.copy()

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    def create(self, created_by: UUID) -> EMeterai:
        self._status = EMeteraiStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "e_meterai_created",
            {
                "meterai_id": str(self._meterai_id),
                "meterai_code": self.meterai_code_masked,
                "npwp": self._npwp,
                "created_by": str(created_by),
            },
        )
        return self

    def update(self, data: dict[str, Any], updated_by: UUID) -> EMeterai:
        if self.is_locked:
            raise EMeteraiLockedError(f"e-Meterai {self.meterai_code_masked} is locked")
        if self._status not in [EMeteraiStatus.PENDING, EMeteraiStatus.ACTIVE]:
            raise EMeteraiError(f"Cannot modify e-Meterai in status {self._status.value}")
        old_data = self.to_dict()
        if "npwp" in data:
            self._npwp = data["npwp"]
        if "value" in data:
            self._value = Decimal(str(data["value"]))
        self._version += 1
        self._updated_at = datetime.now()
        self._calculate_hash()
        self._register_event(
            "e_meterai_updated",
            {
                "meterai_id": str(self._meterai_id),
                "old_data": old_data,
                "new_data": self.to_dict(),
                "updated_by": str(updated_by),
            },
        )
        return self

    def delete(self, deleted_by: UUID, permanent: bool = False) -> EMeterai:
        if permanent:
            self._status = EMeteraiStatus.VOID
        else:
            self._status = EMeteraiStatus.ARCHIVED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_meterai_deleted",
            {
                "meterai_id": str(self._meterai_id),
                "permanent": permanent,
                "deleted_by": str(deleted_by),
            },
        )
        return self

    def restore(self, restored_by: UUID) -> EMeterai:
        if self._status not in [EMeteraiStatus.ARCHIVED, EMeteraiStatus.VOID]:
            raise EMeteraiError(f"Cannot restore e-Meterai in status {self._status.value}")
        self._status = EMeteraiStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_meterai_restored",
            {
                "meterai_id": str(self._meterai_id),
                "restored_by": str(restored_by),
            },
        )
        return self

    def activate(self, activated_by: UUID) -> EMeterai:
        if self._status != EMeteraiStatus.PURCHASED:
            raise EMeteraiError(f"Cannot activate e-Meterai in status {self._status.value}")
        self._status = EMeteraiStatus.ACTIVE
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_meterai_activated",
            {
                "meterai_id": str(self._meterai_id),
                "activated_by": str(activated_by),
            },
        )
        return self

    def deactivate(self, deactivated_by: UUID) -> EMeterai:
        if self._status != EMeteraiStatus.ACTIVE:
            raise EMeteraiError(f"Cannot deactivate e-Meterai in status {self._status.value}")
        self._status = EMeteraiStatus.PURCHASED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_meterai_deactivated",
            {
                "meterai_id": str(self._meterai_id),
                "deactivated_by": str(deactivated_by),
            },
        )
        return self

    def lock(self, locked_by: UUID, reason: str = "") -> EMeterai:
        if self.is_locked:
            raise EMeteraiLockedError(f"e-Meterai {self.meterai_code_masked} already locked")
        self._locked_at = datetime.now()
        self._locked_by = locked_by
        self._status = EMeteraiStatus.LOCKED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_meterai_locked",
            {
                "meterai_id": str(self._meterai_id),
                "locked_by": str(locked_by),
                "reason": reason,
            },
        )
        return self

    def unlock(self, unlocked_by: UUID) -> EMeterai:
        if not self.is_locked:
            raise EMeteraiLockedError(f"e-Meterai {self.meterai_code_masked} is not locked")
        self._locked_at = None
        self._locked_by = None
        self._status = EMeteraiStatus.ACTIVE
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_meterai_unlocked",
            {
                "meterai_id": str(self._meterai_id),
                "unlocked_by": str(unlocked_by),
            },
        )
        return self

    def validate(self, validator_id: UUID, document_id: str | None = None) -> EMeterai:
        if self.is_locked:
            raise EMeteraiLockedError(f"e-Meterai {self.meterai_code_masked} is locked")
        if self.is_expired:
            self._status = EMeteraiStatus.EXPIRED
            raise EMeteraiExpiredError(f"e-Meterai {self.meterai_code_masked} has expired")
        self._validated_at = datetime.now()
        self._status = EMeteraiStatus.ACTIVE
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "e_meterai_validated",
            {
                "meterai_id": str(self._meterai_id),
                "meterai_code": self.meterai_code_masked,
                "document_id": document_id,
                "validator_id": str(validator_id),
            },
        )
        return self

    def use(self, document_id: str, document_type: str, document_value: Decimal, used_by: UUID) -> EMeterai:
        if self.is_locked:
            raise EMeteraiLockedError(f"e-Meterai {self.meterai_code_masked} is locked")
        if not self.is_valid:
            if self.is_expired:
                raise EMeteraiExpiredError(f"e-Meterai {self.meterai_code_masked} has expired")
            raise EMeteraiInvalidError(f"e-Meterai {self.meterai_code_masked} is not valid")
        if self.is_used:
            raise EMeteraiUsedError(f"e-Meterai {self.meterai_code_masked} already used")
        if document_value < METERAI_THRESHOLD:
            raise EMeteraiError(f"Document value {document_value} below threshold {METERAI_THRESHOLD}, no meterai required")
        self._used_at = datetime.now()
        self._used_on_document = document_id
        self._used_on_document_type = document_type
        self._status = EMeteraiStatus.USED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_meterai_used",
            {
                "meterai_id": str(self._meterai_id),
                "meterai_code": self.meterai_code_masked,
                "document_id": document_id,
                "document_type": document_type,
                "document_value": float(document_value),
                "used_by": str(used_by),
            },
        )
        return self

    def purchase(self, quantity: int, purchased_by: UUID, transaction_id: str | None = None) -> EMeterai:
        self._transaction_id = transaction_id
        self._purchased_at = datetime.now()
        self._status = EMeteraiStatus.PURCHASED
        self._value = METERRY_VALUE
        self._expiry_date = date.today() + timedelta(days=EMETERAI_EXPIRY_DAYS)
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_meterai_purchased",
            {
                "meterai_id": str(self._meterai_id),
                "meterai_code": self.meterai_code_masked,
                "quantity": quantity,
                "transaction_id": transaction_id,
                "purchased_by": str(purchased_by),
            },
        )
        return self

    def revoke(self, revoked_by: UUID, reason: str) -> EMeterai:
        if self.is_locked:
            raise EMeteraiLockedError(f"e-Meterai {self.meterai_code_masked} is locked")
        if self._status != EMeteraiStatus.USED:
            raise EMeteraiError(f"Cannot revoke e-Meterai in status {self._status.value}")
        self._revoked_at = datetime.now()
        self._revoked_reason = reason
        self._status = EMeteraiStatus.REVOKED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_meterai_revoked",
            {
                "meterai_id": str(self._meterai_id),
                "meterai_code": self.meterai_code_masked,
                "reason": reason,
                "revoked_by": str(revoked_by),
            },
        )
        return self

    def get_status(self) -> dict[str, Any]:
        return {
            "meterai_id": str(self._meterai_id),
            "meterai_code": self.meterai_code_masked,
            "status": self._status.value,
            "is_valid": self.is_valid,
            "is_active": self.is_active,
            "is_used": self.is_used,
            "is_expired": self.is_expired,
            "is_locked": self.is_locked,
            "value": float(self._value),
            "expiry_date": self._expiry_date.isoformat(),
            "purchased_at": self._purchased_at.isoformat() if self._purchased_at else None,
            "used_at": self._used_at.isoformat() if self._used_at else None,
            "used_on_document": self._used_on_document,
            "used_on_document_type": self._used_on_document_type,
        }

    def get_history(self) -> list[dict[str, Any]]:
        return self._history.copy()

    def snapshot(self) -> dict[str, Any]:
        return {
            "meterai_id": str(self._meterai_id),
            "meterai_code": self.meterai_code_masked,
            "npwp": self._npwp,
            "value": float(self._value),
            "status": self._status.value,
            "version": self._version,
            "created_at": self._created_at.isoformat(),
            "updated_at": self._updated_at.isoformat(),
            "purchased_at": self._purchased_at.isoformat() if self._purchased_at else None,
            "used_at": self._used_at.isoformat() if self._used_at else None,
            "used_on_document": self._used_on_document,
            "used_on_document_type": self._used_on_document_type,
            "expiry_date": self._expiry_date.isoformat(),
            "transaction_id": self._transaction_id,
            "validated_at": self._validated_at.isoformat() if self._validated_at else None,
            "revoked_at": self._revoked_at.isoformat() if self._revoked_at else None,
            "revoked_reason": self._revoked_reason,
            "locked_at": self._locked_at.isoformat() if self._locked_at else None,
            "locked_by": str(self._locked_by) if self._locked_by else None,
            "hash": self._hash,
        }

    def clone(self) -> EMeterai:
        return EMeterai(
            meterai_code=self._meterai_code,
            npwp=self._npwp,
            value=self._value,
            status=EMeteraiStatus.PENDING,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "meterai_id": str(self._meterai_id),
            "meterai_code": self._meterai_code,
            "meterai_code_masked": self.meterai_code_masked,
            "npwp": self._npwp,
            "value": float(self._value),
            "status": self._status.value,
            "version": self._version,
            "created_at": self._created_at.isoformat(),
            "updated_at": self._updated_at.isoformat(),
            "purchased_at": self._purchased_at.isoformat() if self._purchased_at else None,
            "used_at": self._used_at.isoformat() if self._used_at else None,
            "used_on_document": self._used_on_document,
            "used_on_document_type": self._used_on_document_type,
            "expiry_date": self._expiry_date.isoformat(),
            "transaction_id": self._transaction_id,
            "validated_at": self._validated_at.isoformat() if self._validated_at else None,
            "revoked_at": self._revoked_at.isoformat() if self._revoked_at else None,
            "revoked_reason": self._revoked_reason,
            "locked_at": self._locked_at.isoformat() if self._locked_at else None,
            "locked_by": str(self._locked_by) if self._locked_by else None,
            "hash": self._hash,
            "is_valid": self.is_valid,
            "is_expired": self.is_expired,
            "is_locked": self.is_locked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EMeterai:
        return cls(
            meterai_id=UUID(data["meterai_id"]) if data.get("meterai_id") else None,
            meterai_code=data["meterai_code"],
            npwp=data["npwp"],
            status=EMeteraiStatus(data.get("status", "pending")),
            value=Decimal(str(data.get("value", METERRY_VALUE))),
            purchased_at=datetime.fromisoformat(data["purchased_at"]) if data.get("purchased_at") else None,
            used_at=datetime.fromisoformat(data["used_at"]) if data.get("used_at") else None,
            used_on_document=data.get("used_on_document"),
            used_on_document_type=data.get("used_on_document_type"),
            expiry_date=date.fromisoformat(data["expiry_date"]) if data.get("expiry_date") else None,
            transaction_id=data.get("transaction_id"),
            version=data.get("version", 1),
        )

    def audit_trail(self) -> list[dict[str, Any]]:
        return self._history.copy()

    def can_transition(self, new_status: EMeteraiStatus) -> bool:
        transitions = {
            EMeteraiStatus.PENDING: [EMeteraiStatus.PURCHASED, EMeteraiStatus.ARCHIVED, EMeteraiStatus.VOID],
            EMeteraiStatus.PURCHASED: [EMeteraiStatus.ACTIVE, EMeteraiStatus.ARCHIVED],
            EMeteraiStatus.ACTIVE: [EMeteraiStatus.USED, EMeteraiStatus.PURCHASED, EMeteraiStatus.EXPIRED, EMeteraiStatus.LOCKED],
            EMeteraiStatus.USED: [EMeteraiStatus.REVOKED, EMeteraiStatus.ARCHIVED],
            EMeteraiStatus.REVOKED: [EMeteraiStatus.ARCHIVED],
            EMeteraiStatus.EXPIRED: [EMeteraiStatus.ARCHIVED],
            EMeteraiStatus.LOCKED: [EMeteraiStatus.ACTIVE],
            EMeteraiStatus.ARCHIVED: [EMeteraiStatus.VOID],
            EMeteraiStatus.VOID: [],
        }
        return new_status in transitions.get(self._status, [])

    def transition(self, new_status: EMeteraiStatus, actor_id: UUID, reason: str = "") -> EMeterai:
        if not self.can_transition(new_status):
            raise EMeteraiError(f"Status transition invalid: {self._status.value} -> {new_status.value}")
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
            "e_meterai_status_changed",
            {
                "meterai_id": str(self._meterai_id),
                "from_status": old_status.value,
                "to_status": new_status.value,
                "actor_id": str(actor_id),
                "reason": reason,
            },
        )
        return self

    def register_event(self, event_type: str, event_data: dict[str, Any]) -> EMeterai:
        return self._register_event(event_type, event_data)

    def _register_event(self, event_type: str, event_data: dict[str, Any]) -> EMeterai:
        self._events.append(
            {
                "event_id": str(uuid4()),
                "event_type": event_type,
                "aggregate_id": str(self._meterai_id),
                "aggregate_type": "EMeterai",
                "occurred_at": datetime.now().isoformat(),
                "data": event_data,
            }
        )
        return self

    def get_events(self) -> list[dict[str, Any]]:
        return self._events.copy()

    def clear_events(self) -> EMeterai:
        self._events.clear()
        return self

    def version(self) -> int:
        return self._version

    def check_expiry(self) -> bool:
        if self.is_expired and self._status not in [EMeteraiStatus.USED, EMeteraiStatus.REVOKED, EMeteraiStatus.ARCHIVED]:
            self._status = EMeteraiStatus.EXPIRED
            self._updated_at = datetime.now()
            self._version += 1
            self._register_event(
                "e_meterai_expired",
                {
                    "meterai_id": str(self._meterai_id),
                    "meterai_code": self.meterai_code_masked,
                    "expiry_date": self._expiry_date.isoformat(),
                },
            )
            return True
        return False

    def set_validation_response(self, response: dict[str, Any]) -> EMeterai:
        self._validation_response = response
        if response.get("is_valid"):
            self.validate(UUID(int=0))
        return self

    def set_purchase_response(self, response: dict[str, Any]) -> EMeterai:
        self._purchase_response = response
        if response.get("status") == "success":
            self._status = EMeteraiStatus.PURCHASED
        return self

    def _calculate_hash(self) -> None:
        data = f"{self._meterai_id}{self._meterai_code}{self._npwp}{self._value}{self._status.value}{self._version}"
        self._hash = hashlib.sha256(data.encode()).hexdigest()


# ============================================================================
# REPOSITORY INTERFACE
# ============================================================================
class EMeteraiRepositoryPort:
    async def add(self, meterai: EMeterai) -> None:
        raise NotImplementedError
    async def save(self, meterai: EMeterai) -> None:
        raise NotImplementedError
    async def update(self, meterai: EMeterai) -> None:
        raise NotImplementedError
    async def delete(self, meterai_id: UUID) -> None:
        raise NotImplementedError
    async def get_by_id(self, meterai_id: UUID) -> EMeterai | None:
        raise NotImplementedError
    async def get_by_code(self, meterai_code: str) -> EMeterai | None:
        raise NotImplementedError
    async def get_by_npwp(self, npwp: str, status: EMeteraiStatus | None = None) -> list[EMeterai]:
        raise NotImplementedError
    async def get_stock_count(self, npwp: str) -> int:
        raise NotImplementedError
    async def get_all_active(self, npwp: str) -> list[EMeterai]:
        raise NotImplementedError
    async def mark_as_used(self, meterai_id: UUID, document_id: str, document_type: str) -> None:
        raise NotImplementedError


class _FallbackEMeteraiRepository(EMeteraiRepositoryPort):
    def __init__(self):
        self._store: dict[UUID, EMeterai] = {}
        self._by_code: dict[str, UUID] = {}

    async def add(self, meterai: EMeterai) -> None:
        self._store[meterai.meterai_id] = meterai
        self._by_code[meterai.meterai_code] = meterai.meterai_id

    async def save(self, meterai: EMeterai) -> None:
        self._store[meterai.meterai_id] = meterai

    async def update(self, meterai: EMeterai) -> None:
        self._store[meterai.meterai_id] = meterai

    async def delete(self, meterai_id: UUID) -> None:
        if meterai_id in self._store:
            del self._store[meterai_id]

    async def get_by_id(self, meterai_id: UUID) -> EMeterai | None:
        return self._store.get(meterai_id)

    async def get_by_code(self, meterai_code: str) -> EMeterai | None:
        meterai_id = self._by_code.get(meterai_code)
        if meterai_id:
            return self._store.get(meterai_id)
        return None

    async def get_by_npwp(self, npwp: str, status: EMeteraiStatus | None = None) -> list[EMeterai]:
        result = []
        for meterai in self._store.values():
            if meterai.npwp == npwp:
                if status is None or meterai.status == status:
                    result.append(meterai)
        return result

    async def get_stock_count(self, npwp: str) -> int:
        count = 0
        for meterai in self._store.values():
            if meterai.npwp == npwp and meterai.is_valid and not meterai.is_used:
                count += 1
        return count

    async def get_all_active(self, npwp: str) -> list[EMeterai]:
        return await self.get_by_npwp(npwp, EMeteraiStatus.ACTIVE)

    async def mark_as_used(self, meterai_id: UUID, document_id: str, document_type: str) -> None:
        meterai = self._store.get(meterai_id)
        if meterai:
            meterai.use(document_id, document_type, METERAI_THRESHOLD, UUID(int=0))


# ============================================================================
# E-METERAI INTEGRATOR
# ============================================================================
class EMeteraiIntegrator:
    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._coretax_client = None
        self._repository = _FallbackEMeteraiRepository()
        self._redis_client = None
        self._cache: dict[str, Any] = {}
        self._used_documents: set[str] = set()

    def _load_config(self) -> dict[str, Any]:
        if self._config:
            return self._config
        return {
            "coretax_djp": {
                "e_meterai": {
                    "cache_enabled": True,
                    "cache_ttl_seconds": 3600,
                    "auto_purchase_threshold": DEFAULT_AUTO_PURCHASE_THRESHOLD,
                    "auto_purchase_quantity": DEFAULT_AUTO_PURCHASE_QUANTITY,
                    "meterai_value": float(METERRY_VALUE),
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
                logger.warning("Redis not available, using in-memory cache")
                self._redis_client = None
        return self._redis_client

    async def _get_coretax_client(self):
        if self._coretax_client is None:
            self._coretax_client = await get_coretax_client()
        return self._coretax_client

    def _get_cache_key(self, meterai_code: str) -> str:
        return f"{REDIS_EMETERAI_CACHE_PREFIX}{hashlib.sha256(meterai_code.encode()).hexdigest()}"

    def _get_stock_key(self, npwp: str) -> str:
        return f"{REDIS_EMETERAI_STOCK_PREFIX}{npwp}"

    async def _get_cached(self, cache_key: str) -> dict[str, Any] | None:
        cfg = self._load_config().get("coretax_djp", {}).get("e_meterai", {})
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
        cfg = self._load_config().get("coretax_djp", {}).get("e_meterai", {})
        if not cfg.get("cache_enabled", True):
            return
        ttl = cfg.get("cache_ttl_seconds", CACHE_TTL_SECONDS)
        try:
            redis = await self._get_redis()
            if redis:
                import json
                await redis.setex(cache_key, ttl, json.dumps(result))
        except Exception as e:
            logger.warning(f"Redis cache set failed: {e}")
        self._cache[cache_key] = result

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    async def create(self, meterai_data: dict[str, Any], created_by: UUID) -> dict[str, Any]:
        meterai_code = meterai_data.get("meterai_code")
        if not meterai_code or not EMETERAI_PATTERN.match(meterai_code):
            return {"success": False, "error": "Invalid e-Meterai format"}
        existing = await self._repository.get_by_code(meterai_code)
        if existing:
            return {"success": False, "error": "e-Meterai already registered"}
        meterai = EMeterai(
            meterai_code=meterai_code,
            npwp=meterai_data["npwp"],
            status=EMeteraiStatus.PENDING,
            value=Decimal(str(meterai_data.get("value", METERRY_VALUE))),
        )
        meterai.create(created_by)
        await self._repository.add(meterai)
        return {
            "success": True,
            "meterai_id": str(meterai.meterai_id),
            "meterai_code": meterai.meterai_code_masked,
            "status": meterai.status.value,
        }

    async def validate(
        self,
        meterai_code: str,
        document_id: str | None = None,
        document_type: str = "invoice",
        validator_id: UUID | None = None,
    ) -> dict[str, Any]:
        if not EMETERAI_PATTERN.match(meterai_code):
            return {
                "success": False,
                "error": f"Invalid e-Meterai format: {meterai_code}",
                "is_valid": False,
            }
        cache_key = self._get_cache_key(meterai_code)
        cached = await self._get_cached(cache_key)
        if cached:
            logger.debug(f"e-Meterai {meterai_code[:8]}... found in cache")
            return cached
        client = await self._get_coretax_client()
        payload = {
            "meterai_code": meterai_code,
            "document_id": document_id,
            "document_type": document_type,
        }
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                response = await client.post(CORETAX_EMETERAI_VALIDATE_ENDPOINT, payload)
                is_valid = response.get("isValid", False)
                status = response.get("status")
                result = {
                    "success": True,
                    "meterai_code": meterai_code[:8] + "..." + meterai_code[-4:],
                    "is_valid": is_valid,
                    "status": status,
                    "value": float(Decimal(str(response.get("value", METERRY_VALUE)))),
                    "message": response.get("message"),
                    "used_at": response.get("used_at"),
                    "used_on_document": response.get("document_id"),
                    "validated_at": datetime.now().isoformat(),
                }
                if is_valid:
                    await self._set_cached(cache_key, result)
                    existing = await self._repository.get_by_code(meterai_code)
                    if existing:
                        existing.validate(validator_id or UUID(int=0), document_id)
                        await self._repository.update(existing)
                    else:
                        meterai = EMeterai(
                            meterai_code=meterai_code,
                            npwp=response.get("npwp", ""),
                            status=EMeteraiStatus.ACTIVE,
                        )
                        meterai.create(validator_id or UUID(int=0))
                        meterai.set_validation_response(response)
                        await self._repository.add(meterai)
                if not is_valid and status == EMETERAI_STATUS["USED"]:
                    result["error"] = f"e-Meterai already used on document {response.get('document_id')}"
                return result
            except CoretaxAuthError as e:
                logger.error(f"Coretax auth error (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    return {
                        "success": False,
                        "error": f"Authentication failed: {e}",
                        "is_valid": False,
                    }
            except Exception as e:
                logger.exception(f"e-Meterai validation API error (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    return {"success": False, "error": f"API error: {e}", "is_valid": False}
        return {"success": False, "error": "Max retries exceeded", "is_valid": False}

    async def use(
        self,
        meterai_code: str,
        document_id: str,
        document_type: str,
        document_value: Decimal,
        used_by: UUID,
    ) -> dict[str, Any]:
        validation = await self.validate(meterai_code, document_id, document_type, used_by)
        if not validation.get("is_valid"):
            return {
                "success": False,
                "error": f"e-Meterai invalid: {validation.get('message', 'Unknown error')}",
            }
        if document_value < METERAI_THRESHOLD:
            return {
                "success": False,
                "error": f"Document value {document_value} below threshold {METERAI_THRESHOLD}, no meterai required",
            }
        existing = await self._repository.get_by_code(meterai_code)
        if existing:
            try:
                existing.use(document_id, document_type, document_value, used_by)
                await self._repository.update(existing)
            except (EMeteraiUsedError, EMeteraiExpiredError, EMeteraiInvalidError) as e:
                return {"success": False, "error": str(e)}
        client = await self._get_coretax_client()
        payload = {
            "meterai_code": meterai_code,
            "document_id": document_id,
            "document_type": document_type,
            "document_value": float(document_value),
        }
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                response = await client.post(CORETAX_EMETERAI_USE_ENDPOINT, payload)
                if response.get("status") == "success":
                    return {
                        "success": True,
                        "meterai_code": meterai_code[:8] + "..." + meterai_code[-4:],
                        "document_id": document_id,
                        "used_at": datetime.now().isoformat(),
                        "message": "e-Meterai attached successfully",
                    }
                else:
                    return {"success": False, "error": response.get("message", "Use failed")}
            except Exception as e:
                logger.error(f"Failed to use e-Meterai (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    return {"success": False, "error": str(e)}
        return {"success": False, "error": "Max retries exceeded"}

    async def purchase(
        self, quantity: int, npwp: str, purpose: str = "invoice", purchased_by: UUID | None = None
    ) -> dict[str, Any]:
        client = await self._get_coretax_client()
        payload = {
            "quantity": quantity,
            "npwp": npwp,
            "purpose": purpose,
            "value": float(METERRY_VALUE),
        }
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                response = await client.post(CORETAX_EMETERAI_PURCHASE_ENDPOINT, payload)
                if response.get("status") == "success":
                    meterai_list = response.get("meterai_list", [])
                    purchase_id = uuid4()
                    transaction_id = response.get("transaction_id")
                    for meterai_code in meterai_list:
                        meterai = EMeterai(
                            meterai_code=meterai_code,
                            npwp=npwp,
                            status=EMeteraiStatus.PURCHASED,
                            transaction_id=transaction_id,
                        )
                        meterai.purchase(quantity, purchased_by or UUID(int=0), transaction_id)
                        await self._repository.add(meterai)
                    stock_key = self._get_stock_key(npwp)
                    await self._set_cached(stock_key, {"available_quantity": len(meterai_list)})
                    return {
                        "success": True,
                        "purchase_id": str(purchase_id),
                        "quantity": quantity,
                        "meterai_list": [c[:8] + "..." + c[-4:] for c in meterai_list],
                        "total_amount": float(quantity * METERRY_VALUE),
                        "transaction_id": transaction_id,
                    }
                else:
                    return {"success": False, "error": response.get("message", "Purchase failed")}
            except Exception as e:
                logger.exception(f"Failed to purchase e-Meterai (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    return {"success": False, "error": str(e)}
        return {"success": False, "error": "Max retries exceeded"}

    async def get_stock(self, npwp: str) -> dict[str, Any]:
        client = await self._get_coretax_client()
        endpoint = f"{CORETAX_EMETERAI_STOCK_ENDPOINT}/{npwp}"
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                response = await client.get(endpoint)
                available = response.get("available_quantity", 0)
                used = response.get("used_quantity", 0)
                expired = response.get("expired_quantity", 0)
                stock_key = self._get_stock_key(npwp)
                await self._set_cached(
                    stock_key,
                    {
                        "available_quantity": available,
                        "used_quantity": used,
                        "expired_quantity": expired,
                    },
                )
                return {
                    "success": True,
                    "npwp": npwp,
                    "available_quantity": available,
                    "used_quantity": used,
                    "expired_quantity": expired,
                    "total_quantity": available + used + expired,
                    "meterai_list": response.get("meterai_list", []),
                    "as_of_date": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Failed to get e-Meterai stock (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    return {"success": False, "error": str(e), "available_quantity": 0}
        return {"success": False, "error": "Max retries exceeded", "available_quantity": 0}

    async def get_status(self, meterai_code: str) -> dict[str, Any]:
        existing = await self._repository.get_by_code(meterai_code)
        if existing:
            return existing.get_status()
        return await self.validate(meterai_code)

    async def get_history(self, meterai_code: str) -> dict[str, Any]:
        existing = await self._repository.get_by_code(meterai_code)
        if not existing:
            return {"success": False, "error": "e-Meterai not found"}
        return {
            "success": True,
            "meterai_code": existing.meterai_code_masked,
            "history": existing.get_history(),
        }

    async def revoke(self, meterai_code: str, reason: str, revoked_by: UUID) -> dict[str, Any]:
        existing = await self._repository.get_by_code(meterai_code)
        if not existing:
            return {"success": False, "error": "e-Meterai not found"}
        client = await self._get_coretax_client()
        payload = {
            "meterai_code": meterai_code,
            "reason": reason,
        }
        try:
            response = await client.post(CORETAX_EMETERAI_REVOKE_ENDPOINT, payload)
            if response.get("status") == "success":
                existing.revoke(revoked_by, reason)
                await self._repository.update(existing)
                cache_key = self._get_cache_key(meterai_code)
                if cache_key in self._cache:
                    del self._cache[cache_key]
                return {
                    "success": True,
                    "meterai_code": existing.meterai_code_masked,
                    "revoked": True,
                    "message": "e-Meterai revoked successfully",
                }
            else:
                return {"success": False, "error": response.get("message", "Revoke failed")}
        except Exception as e:
            logger.error(f"Failed to revoke e-Meterai: {e}")
            return {"success": False, "error": str(e)}

    async def auto_purchase_if_low(
        self,
        npwp: str,
        threshold: int = DEFAULT_AUTO_PURCHASE_THRESHOLD,
        purchase_quantity: int = DEFAULT_AUTO_PURCHASE_QUANTITY,
    ) -> dict[str, Any]:
        stock = await self.get_stock(npwp)
        available = stock.get("available_quantity", 0)
        if available < threshold:
            logger.info(f"e-Meterai stock low: {available} < {threshold}, auto-purchasing {purchase_quantity}")
            purchase = await self.purchase(purchase_quantity, npwp, "auto_replenish")
            if purchase.get("success"):
                try:
                    from infrastructure.telemetry.alert_manager_router import trigger_alert
                    await trigger_alert(
                        title="e-Meterai Auto-Purchased",
                        message=f"Purchased {purchase_quantity} e-Meterai due to low stock ({available})",
                        severity="info",
                        source="EMeteraiIntegrator",
                    )
                except ImportError:
                    pass
                return purchase
            else:
                try:
                    from infrastructure.telemetry.alert_manager_router import trigger_alert
                    await trigger_alert(
                        title="e-Meterai Auto-Purchase Failed",
                        message=f"Failed to auto-purchase: {purchase.get('error')}",
                        severity="critical",
                        source="EMeteraiIntegrator",
                    )
                except ImportError:
                    pass
                return {"success": False, "error": "Auto-purchase failed"}
        return {
            "success": True,
            "message": f"Stock sufficient: {available}",
            "auto_purchased": False,
            "available_quantity": available,
        }

    async def attach_to_document(
        self,
        meterai_code: str,
        document_id: str,
        document_type: str,
        document_value: Decimal,
        attached_by: UUID,
    ) -> dict[str, Any]:
        return await self.use(meterai_code, document_id, document_type, document_value, attached_by)

    async def snapshot(self, meterai_code: str) -> dict[str, Any]:
        existing = await self._repository.get_by_code(meterai_code)
        if not existing:
            return {"success": False, "error": "e-Meterai not found"}
        return existing.snapshot()

    async def to_dict(self, meterai_code: str) -> dict[str, Any]:
        existing = await self._repository.get_by_code(meterai_code)
        if not existing:
            return {"success": False, "error": "e-Meterai not found"}
        return existing.to_dict()

    async def audit_trail(self, meterai_code: str) -> dict[str, Any]:
        existing = await self._repository.get_by_code(meterai_code)
        if not existing:
            return {"success": False, "error": "e-Meterai not found"}
        return {
            "success": True,
            "meterai_code": existing.meterai_code_masked,
            "audit_trail": existing.audit_trail(),
        }

    async def can_transition(self, meterai_code: str, new_status: str) -> dict[str, Any]:
        existing = await self._repository.get_by_code(meterai_code)
        if not existing:
            return {"success": False, "error": "e-Meterai not found"}
        can = existing.can_transition(EMeteraiStatus(new_status))
        return {
            "success": True,
            "meterai_code": existing.meterai_code_masked,
            "current_status": existing.status.value,
            "target_status": new_status,
            "can_transition": can,
        }

    async def transition(
        self, meterai_code: str, new_status: str, actor_id: UUID, reason: str = ""
    ) -> dict[str, Any]:
        existing = await self._repository.get_by_code(meterai_code)
        if not existing:
            return {"success": False, "error": "e-Meterai not found"}
        try:
            existing.transition(EMeteraiStatus(new_status), actor_id, reason)
            await self._repository.update(existing)
            return {
                "success": True,
                "meterai_code": existing.meterai_code_masked,
                "new_status": new_status,
            }
        except EMeteraiError as e:
            return {"success": False, "error": str(e)}

    async def version(self, meterai_code: str) -> dict[str, Any]:
        existing = await self._repository.get_by_code(meterai_code)
        if not existing:
            return {"success": False, "error": "e-Meterai not found"}
        return {
            "success": True,
            "meterai_code": existing.meterai_code_masked,
            "version": existing.version(),
        }

    async def register_event(
        self, meterai_code: str, event_type: str, event_data: dict[str, Any]
    ) -> dict[str, Any]:
        existing = await self._repository.get_by_code(meterai_code)
        if not existing:
            return {"success": False, "error": "e-Meterai not found"}
        existing.register_event(event_type, event_data)
        await self._repository.update(existing)
        return {
            "success": True,
            "meterai_code": existing.meterai_code_masked,
            "events": existing.get_events(),
        }

    async def get_events(self, meterai_code: str) -> dict[str, Any]:
        existing = await self._repository.get_by_code(meterai_code)
        if not existing:
            return {"success": False, "error": "e-Meterai not found"}
        return {
            "success": True,
            "meterai_code": existing.meterai_code_masked,
            "events": existing.get_events(),
        }

    async def clear_events(self, meterai_code: str) -> dict[str, Any]:
        existing = await self._repository.get_by_code(meterai_code)
        if not existing:
            return {"success": False, "error": "e-Meterai not found"}
        existing.clear_events()
        await self._repository.update(existing)
        return {
            "success": True,
            "meterai_code": existing.meterai_code_masked,
            "events_cleared": True,
        }

    # ========================================================================
    # Batch Operations
    # ========================================================================
    async def validate_batch(self, meterai_codes: list[str], document_id: str | None = None) -> list[dict[str, Any]]:
        results = []
        for code in meterai_codes:
            result = await self.validate(code, document_id)
            results.append(result)
        return results

    async def purchase_batch(self, purchases: list[dict[str, Any]], purchased_by: UUID) -> list[dict[str, Any]]:
        results = []
        for purchase in purchases:
            result = await self.purchase(
                quantity=purchase["quantity"],
                npwp=purchase["npwp"],
                purpose=purchase.get("purpose", "batch"),
                purchased_by=purchased_by,
            )
            results.append(result)
        return results

    async def sync_stock_all(self, npwp_list: list[str]) -> dict[str, Any]:
        results = {}
        for npwp in npwp_list:
            stock = await self.get_stock(npwp)
            results[npwp] = stock
        return {
            "success": True,
            "results": results,
            "synced_at": datetime.now().isoformat(),
        }

    # ========================================================================
    # Legacy / Test Methods
    # ========================================================================
    def terapkan(self, dokumen: dict[str, Any]) -> Any:
        doc_id = dokumen.get("id")
        if hasattr(self, "_used_documents"):
            if doc_id in self._used_documents:
                raise ValueError("Dokumen sudah bermeterai")
        else:
            self._used_documents = set()
        self._used_documents.add(doc_id)
        class MeteraiDummy:
            def __init__(self):
                self.kode_unik = f"EMT-{uuid4().hex[:12].upper()}"
                self.nominal = METERRY_VALUE
                self.status = "ACTIVE"
        return MeteraiDummy()

    async def get_by_id(self, meterai_id: UUID) -> EMeterai | None:
        return await self._repository.get_by_id(meterai_id)

    async def get_by_code(self, meterai_code: str) -> EMeterai | None:
        return await self._repository.get_by_code(meterai_code)

    async def get_all_active(self, npwp: str) -> list[EMeterai]:
        return await self._repository.get_all_active(npwp)


# ============================================================================
# SINGLETON
# ============================================================================
_e_meterai_integrator: EMeteraiIntegrator | None = None

async def get_e_meterai_integrator(config: dict | None = None) -> EMeteraiIntegrator:
    global _e_meterai_integrator
    if _e_meterai_integrator is None:
        _e_meterai_integrator = EMeteraiIntegrator(config=config)
    return _e_meterai_integrator

__all__ = [
    "EMETERAI_STATUS",
    "METERAI_THRESHOLD",
    "EMeterai",
    "EMeteraiError",
    "EMeteraiExpiredError",
    "EMeteraiInsufficientStockError",
    "EMeteraiIntegrator",
    "EMeteraiInvalidError",
    "EMeteraiLockedError",
    "EMeteraiNotFoundError",
    "EMeteraiStatus",
    "EMeteraiUsedError",
    "get_e_meterai_integrator",
]
