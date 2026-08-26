#!/usr/bin/env python3
"""
Module: retainer_contract_entity.py
Layer: 6 - Domain / Project & Services
Responsibility: Kontrak retainer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class RetainerStatus(Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"
    EXPIRED = "expired"

    @classmethod
    def from_string(cls, value: str) -> RetainerStatus:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.DRAFT


class BillingPeriod(Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUALLY = "annually"

    @classmethod
    def from_string(cls, value: str) -> BillingPeriod:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.MONTHLY


@dataclass
class RetainerContractEntity:
    contract_id: UUID
    contract_number: str
    customer_id: UUID
    customer_name: str
    project_id: UUID | None
    project_code: str | None
    start_date: datetime
    end_date: datetime | None
    monthly_fee: Decimal
    currency: str
    allocated_hours: Decimal
    status: RetainerStatus
    billing_period: BillingPeriod
    description: str = ""
    auto_renew: bool = False
    notice_period_days: int = 30
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1
    _audit_trail: list[dict] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if not self.contract_number or len(self.contract_number.strip()) < 3:
            raise ValueError("Contract number must be at least 3 characters")
        if self.monthly_fee <= 0:
            raise ValueError(f"Monthly fee must be positive: {self.monthly_fee}")
        if self.allocated_hours <= 0:
            raise ValueError(f"Allocated hours must be positive: {self.allocated_hours}")
        if self.end_date and self.end_date <= self.start_date:
            raise ValueError("End date must be after start date")
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")
        if self.start_date.tzinfo is None:
            raise ValueError("start_date must be timezone-aware")
        if self.end_date and self.end_date.tzinfo is None:
            raise ValueError("end_date must be timezone-aware")

    def _record_audit(self, action: str, user_id: str, details: dict | None = None) -> None:
        self._audit_trail.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "user_id": user_id,
                "details": details or {},
                "version": self.version,
            }
        )

    def get_audit_trail(self) -> list[dict]:
        return self._audit_trail.copy()

    def is_active(self) -> bool:
        # Return condition directly (SIM103)
        return self.status == RetainerStatus.ACTIVE and (self.end_date is None or self.end_date >= datetime.now(UTC))

    def is_expired(self) -> bool:
        if not self.end_date:
            return False
        return datetime.now(UTC) > self.end_date

    def get_months_remaining(self) -> int:
        if not self.end_date:
            return 999
        if self.is_expired():
            return 0
        now = datetime.now(UTC)
        return max(0, (self.end_date.year - now.year) * 12 + (self.end_date.month - now.month))

    def get_total_fee(self) -> Decimal:
        if not self.end_date:
            return Decimal(0)
        months = self.get_months_remaining() + 1
        return self.monthly_fee * months

    def activate(self, activated_by: str) -> RetainerContractEntity:
        if self.status != RetainerStatus.DRAFT:
            raise ValueError(f"Cannot activate contract in status {self.status.value}")
        self._record_audit("activated", activated_by, {})
        return RetainerContractEntity(
            contract_id=self.contract_id,
            contract_number=self.contract_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            project_id=self.project_id,
            project_code=self.project_code,
            start_date=self.start_date,
            end_date=self.end_date,
            monthly_fee=self.monthly_fee,
            currency=self.currency,
            allocated_hours=self.allocated_hours,
            status=RetainerStatus.ACTIVE,
            billing_period=self.billing_period,
            description=self.description,
            auto_renew=self.auto_renew,
            notice_period_days=self.notice_period_days,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=activated_by,
            version=self.version + 1,
        )

    def suspend(self, suspended_by: str, reason: str) -> RetainerContractEntity:
        if self.status != RetainerStatus.ACTIVE:
            raise ValueError(f"Cannot suspend contract in status {self.status.value}")
        self._record_audit("suspended", suspended_by, {"reason": reason})
        return RetainerContractEntity(
            contract_id=self.contract_id,
            contract_number=self.contract_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            project_id=self.project_id,
            project_code=self.project_code,
            start_date=self.start_date,
            end_date=self.end_date,
            monthly_fee=self.monthly_fee,
            currency=self.currency,
            allocated_hours=self.allocated_hours,
            status=RetainerStatus.SUSPENDED,
            billing_period=self.billing_period,
            description=f"{self.description}\nSuspended: {reason}",
            auto_renew=self.auto_renew,
            notice_period_days=self.notice_period_days,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=suspended_by,
            version=self.version + 1,
        )

    def resume(self, resumed_by: str) -> RetainerContractEntity:
        if self.status != RetainerStatus.SUSPENDED:
            raise ValueError(f"Cannot resume contract in status {self.status.value}")
        self._record_audit("resumed", resumed_by, {})
        return RetainerContractEntity(
            contract_id=self.contract_id,
            contract_number=self.contract_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            project_id=self.project_id,
            project_code=self.project_code,
            start_date=self.start_date,
            end_date=self.end_date,
            monthly_fee=self.monthly_fee,
            currency=self.currency,
            allocated_hours=self.allocated_hours,
            status=RetainerStatus.ACTIVE,
            billing_period=self.billing_period,
            description=self.description.replace("Suspended:", "Resumed:"),
            auto_renew=self.auto_renew,
            notice_period_days=self.notice_period_days,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=resumed_by,
            version=self.version + 1,
        )

    def terminate(
        self, terminated_by: str, reason: str, effective_date: datetime | None = None
    ) -> RetainerContractEntity:
        if self.status in (RetainerStatus.TERMINATED, RetainerStatus.EXPIRED):
            raise ValueError(f"Cannot terminate contract in status {self.status.value}")
        self._record_audit(
            "terminated",
            terminated_by,
            {"reason": reason, "effective_date": (effective_date or datetime.now(UTC)).isoformat()},
        )
        return RetainerContractEntity(
            contract_id=self.contract_id,
            contract_number=self.contract_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            project_id=self.project_id,
            project_code=self.project_code,
            start_date=self.start_date,
            end_date=effective_date or datetime.now(UTC),
            monthly_fee=self.monthly_fee,
            currency=self.currency,
            allocated_hours=self.allocated_hours,
            status=RetainerStatus.TERMINATED,
            billing_period=self.billing_period,
            description=f"{self.description}\nTerminated: {reason}",
            auto_renew=self.auto_renew,
            notice_period_days=self.notice_period_days,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=terminated_by,
            version=self.version + 1,
        )

    def renew(
        self, renewed_by: str, new_end_date: datetime | None = None
    ) -> RetainerContractEntity:
        if self.status not in (RetainerStatus.ACTIVE, RetainerStatus.SUSPENDED):
            raise ValueError(f"Cannot renew contract in status {self.status.value}")
        if new_end_date:
            new_end = new_end_date
        elif self.end_date:
            new_end = self.end_date + timedelta(days=365)
        else:
            new_end = datetime.now(UTC) + timedelta(days=365)
        self._record_audit("renewed", renewed_by, {"new_end_date": new_end.isoformat()})
        return RetainerContractEntity(
            contract_id=self.contract_id,
            contract_number=self.contract_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            project_id=self.project_id,
            project_code=self.project_code,
            start_date=self.start_date,
            end_date=new_end,
            monthly_fee=self.monthly_fee,
            currency=self.currency,
            allocated_hours=self.allocated_hours,
            status=self.status,
            billing_period=self.billing_period,
            description=self.description,
            auto_renew=self.auto_renew,
            notice_period_days=self.notice_period_days,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=renewed_by,
            version=self.version + 1,
        )

    def calculate_monthly_billing(self, actual_hours: Decimal) -> dict[str, Decimal]:
        if actual_hours <= self.allocated_hours:
            return {
                "base_fee": self.monthly_fee,
                "overage_hours": Decimal(0),
                "overage_fee": Decimal(0),
                "total": self.monthly_fee,
            }
        else:
            overage_hours = actual_hours - self.allocated_hours
            overage_rate = self.monthly_fee / self.allocated_hours
            overage_fee = (overage_hours * overage_rate).quantize(Decimal("0.01"))
            return {
                "base_fee": self.monthly_fee,
                "overage_hours": overage_hours,
                "overage_fee": overage_fee,
                "total": self.monthly_fee + overage_fee,
            }

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": str(self.contract_id),
            "contract_number": self.contract_number,
            "customer_id": str(self.customer_id),
            "customer_name": self.customer_name,
            "project_id": str(self.project_id) if self.project_id else None,
            "project_code": self.project_code,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "monthly_fee": str(self.monthly_fee),
            "currency": self.currency,
            "allocated_hours": str(self.allocated_hours),
            "status": self.status.value,
            "billing_period": self.billing_period.value,
            "description": self.description,
            "auto_renew": self.auto_renew,
            "notice_period_days": self.notice_period_days,
            "is_active": self.is_active(),
            "is_expired": self.is_expired(),
            "months_remaining": self.get_months_remaining(),
            "total_fee": str(self.get_total_fee()),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetainerContractEntity:
        return cls(
            contract_id=UUID(data["contract_id"]),
            contract_number=data["contract_number"],
            customer_id=UUID(data["customer_id"]),
            customer_name=data["customer_name"],
            project_id=UUID(data["project_id"]) if data.get("project_id") else None,
            project_code=data.get("project_code"),
            start_date=datetime.fromisoformat(data["start_date"]),
            end_date=datetime.fromisoformat(data["end_date"]) if data.get("end_date") else None,
            monthly_fee=Decimal(data["monthly_fee"]),
            currency=data["currency"],
            allocated_hours=Decimal(data["allocated_hours"]),
            status=RetainerStatus.from_string(data["status"]),
            billing_period=BillingPeriod.from_string(data["billing_period"]),
            description=data.get("description", ""),
            auto_renew=data.get("auto_renew", False),
            notice_period_days=data.get("notice_period_days", 30),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )

    @classmethod
    def create(
        cls,
        contract_number: str,
        customer_id: UUID,
        customer_name: str,
        start_date: datetime,
        monthly_fee: Decimal,
        currency: str,
        allocated_hours: Decimal,
        created_by: str,
        end_date: datetime | None = None,
        project_id: UUID | None = None,
        project_code: str | None = None,
        billing_period: BillingPeriod = BillingPeriod.MONTHLY,
    ) -> RetainerContractEntity:
        return cls(
            contract_id=uuid4(),
            contract_number=contract_number,
            customer_id=customer_id,
            customer_name=customer_name,
            project_id=project_id,
            project_code=project_code,
            start_date=start_date,
            end_date=end_date,
            monthly_fee=monthly_fee,
            currency=currency,
            allocated_hours=allocated_hours,
            status=RetainerStatus.DRAFT,
            billing_period=billing_period,
            created_by=created_by,
        )


RetainerContract = RetainerContractEntity


class RetainerContractRepository:
    async def get_by_id(
        self, contract_id: UUID, legal_entity_id: UUID
    ) -> RetainerContractEntity | None:
        raise NotImplementedError

    async def get_by_number(
        self, contract_number: str, legal_entity_id: UUID
    ) -> RetainerContractEntity | None:
        raise NotImplementedError

    async def get_by_customer(
        self, customer_id: UUID, legal_entity_id: UUID, status: RetainerStatus | None = None
    ) -> list[RetainerContractEntity]:
        raise NotImplementedError

    async def get_active(self, legal_entity_id: UUID) -> list[RetainerContractEntity]:
        raise NotImplementedError

    async def get_expiring_soon(
        self, legal_entity_id: UUID, days_ahead: int = 30
    ) -> list[RetainerContractEntity]:
        raise NotImplementedError

    async def save(self, contract: RetainerContractEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, contract_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


__all__ = [
    "BillingPeriod",
    "RetainerContract",
    "RetainerContractEntity",
    "RetainerContractRepository",
    "RetainerStatus",
]
