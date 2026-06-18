#!/usr/bin/env python3
"""
Module: no_retroactive_policy_enforcer.py
Layer: 4 - Kernel / Immutable Laws
Responsibility: Hukum: kebijakan tidak berlaku surut.
               Memastikan bahwa perubahan kebijakan akuntansi (PSAK/IFRS)
               tidak diterapkan secara retroaktif kecuali diwajibkan oleh
               standar akuntansi atau regulasi. Ini menjaga konsistensi
               laporan keuangan antar periode.

Dependencies:
- standard library (hashlib, json, logging, dataclass, datetime, decimal, enum, typing, uuid, threading)
- kernel.context_holder (get_current_user)
- kernel.immutable_laws.law_violation_exceptions (ImmutableLawViolationError, NoRetroactivePolicyViolation)

Audit: Setiap perubahan kebijakan retroaktif dictat.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_user
from kernel.immutable_laws.law_violation_exceptions import (
    LawViolationSeverity,
    NoRetroactivePolicyViolation,
)

logger = logging.getLogger(__name__)


# === 1. FALLBACK REPOSITORIES (internal, tidak mengimpor adapters/infrastructure) ===


class _FallbackPolicyRepository:
    """Fallback policy repository dengan in-memory storage."""

    def __init__(self):
        self._policies: dict[UUID, dict[str, Any]] = {}
        self._retroactive_applications: list[dict[str, Any]] = []
        self._policy_by_name: dict[str, UUID] = {}

    async def get_by_id(self, policy_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        policy = self._policies.get(policy_id)
        if policy and policy.get("legal_entity_id") == legal_entity_id:
            return policy
        return None

    async def get_by_name(self, policy_name: str, legal_entity_id: UUID) -> dict[str, Any] | None:
        pid = self._policy_by_name.get(f"{legal_entity_id}:{policy_name}")
        if pid:
            return await self.get_by_id(pid, legal_entity_id)
        return None

    async def get_active_policies(
        self,
        legal_entity_id: UUID,
        as_of: datetime,
    ) -> list[dict[str, Any]]:
        result = []
        for policy in self._policies.values():
            if policy.get("legal_entity_id") != legal_entity_id:
                continue
            eff_date = policy.get("effective_date")
            if eff_date and eff_date <= as_of and policy.get("is_active", True):
                result.append(policy)
        return result

    async def get_all_policies(
        self,
        legal_entity_id: UUID,
    ) -> list[dict[str, Any]]:
        return [p for p in self._policies.values() if p.get("legal_entity_id") == legal_entity_id]

    async def record_retroactive_application(
        self,
        policy_id: UUID,
        legal_entity_id: UUID,
        effective_date: datetime,
        approved_by: list[str],
        reason: str,
        applied_at: datetime,
    ) -> None:
        self._retroactive_applications.append(
            {
                "policy_id": policy_id,
                "legal_entity_id": legal_entity_id,
                "effective_date": effective_date,
                "approved_by": approved_by,
                "reason": reason,
                "applied_at": applied_at,
            }
        )

    async def get_retroactive_applications(
        self,
        policy_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        result = self._retroactive_applications.copy()
        if policy_id:
            result = [a for a in result if a.get("policy_id") == policy_id]
        if legal_entity_id:
            result = [a for a in result if a.get("legal_entity_id") == legal_entity_id]
        return result

    async def create_policy(
        self,
        policy_id: UUID,
        legal_entity_id: UUID,
        policy_name: str,
        policy_type: str,
        effective_date: datetime,
        created_by: str,
        approved_by: list[str],
        description: str = "",
    ) -> None:
        self._policies[policy_id] = {
            "policy_id": policy_id,
            "legal_entity_id": legal_entity_id,
            "policy_name": policy_name,
            "policy_type": policy_type,
            "effective_date": effective_date,
            "created_by": created_by,
            "created_at": datetime.now(UTC),
            "approved_by": approved_by,
            "is_active": True,
            "description": description,
        }
        self._policy_by_name[f"{legal_entity_id}:{policy_name}"] = policy_id

    async def update_policy_status(
        self,
        policy_id: UUID,
        legal_entity_id: UUID,
        is_active: bool,
        updated_by: str,
    ) -> bool:
        policy = self._policies.get(policy_id)
        if policy and policy.get("legal_entity_id") == legal_entity_id:
            policy["is_active"] = is_active
            policy["updated_by"] = updated_by
            policy["updated_at"] = datetime.now(UTC)
            return True
        return False

    def clear(self) -> None:
        self._policies.clear()
        self._retroactive_applications.clear()
        self._policy_by_name.clear()


class _FallbackPeriodRepository:
    """Fallback period repository jika infrastructure belum tersedia."""

    def __init__(self):
        self._periods: dict[UUID, dict[str, Any]] = {}
        self._current_periods: dict[UUID, dict[str, Any]] = {}

    async def get_current_period(self, legal_entity_id: UUID) -> dict[str, Any] | None:
        return self._current_periods.get(legal_entity_id)

    async def get_by_id(self, period_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        period = self._periods.get(period_id)
        if period and period.get("legal_entity_id") == legal_entity_id:
            return period
        return None

    async def get_by_fiscal_year(
        self,
        fiscal_year: int,
        legal_entity_id: UUID,
    ) -> list[dict[str, Any]]:
        result = []
        for period in self._periods.values():
            if (
                period.get("legal_entity_id") == legal_entity_id
                and period.get("fiscal_year") == fiscal_year
            ):
                result.append(period)
        return result

    async def get_period_start_date(self, legal_entity_id: UUID) -> datetime | None:
        current = await self.get_current_period(legal_entity_id)
        if current:
            return current.get("start_date")
        return None

    def set_current_period(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        start_date: datetime,
        end_date: datetime,
        period_name: str,
    ) -> None:
        self._current_periods[legal_entity_id] = {
            "period_id": period_id,
            "legal_entity_id": legal_entity_id,
            "start_date": start_date,
            "end_date": end_date,
            "period_name": period_name,
        }
        if period_id not in self._periods:
            self._periods[period_id] = self._current_periods[legal_entity_id]

    def clear(self) -> None:
        self._periods.clear()
        self._current_periods.clear()


# === 2. CONSTANTS & ENUMS ===


class RetroactiveReason(Enum):
    """Alasan yang valid untuk kebijakan retroaktif."""

    REGULATORY_CHANGE = "REGULATORY_CHANGE"
    PSAK_IFRS_TRANSITION = "PSAK_IFRS_TRANSITION"
    ERROR_CORRECTION_MATERIAL = "ERROR_CORRECTION_MATERIAL"
    MANAGEMENT_APPROVAL = "MANAGEMENT_APPROVAL"


class PolicyType(Enum):
    """Jenis kebijakan akuntansi."""

    REVENUE_RECOGNITION = "revenue_recognition"
    ASSET_VALUATION = "asset_valuation"
    DEPRECIATION_METHOD = "depreciation_method"
    INVENTORY_VALUATION = "inventory_valuation"
    LEASE_ACCOUNTING = "lease_accounting"
    FOREIGN_CURRENCY = "foreign_currency"
    TAX_ACCOUNTING = "tax_accounting"
    CONSOLIDATION = "consolidation"


@dataclass
class AccountingPolicy:
    """Representasi kebijakan akuntansi."""

    policy_id: UUID
    legal_entity_id: UUID
    policy_name: str
    policy_type: PolicyType
    effective_date: datetime
    created_by: str
    created_at: datetime
    approved_by: list[str]
    is_active: bool = True
    description: str = ""
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.policy_id}|{self.legal_entity_id}|{self.policy_name}|"
            f"{self.policy_type.value}|{self.effective_date.isoformat()}|"
            f"{self.created_by}|{self.is_active}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def is_retroactive(self, as_of: datetime | None = None) -> bool:
        check_date = as_of or datetime.now(UTC)
        return self.effective_date < check_date

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": str(self.policy_id),
            "legal_entity_id": str(self.legal_entity_id),
            "policy_name": self.policy_name,
            "policy_type": self.policy_type.value,
            "effective_date": self.effective_date.isoformat(),
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "approved_by": self.approved_by,
            "is_active": self.is_active,
            "is_retroactive": self.is_retroactive(),
            "description": self.description[:100],
        }


@dataclass
class RetroactiveApplicationRecord:
    """Rekaman aplikasi kebijakan retroaktif."""

    record_id: UUID
    policy_id: UUID
    legal_entity_id: UUID
    effective_date: datetime
    approved_by: list[str]
    reason: str
    applied_at: datetime
    applied_by: str
    justification_document: str | None = None
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.record_id}|{self.policy_id}|{self.legal_entity_id}|"
            f"{self.effective_date.isoformat()}|{','.join(self.approved_by)}|{self.reason}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": str(self.record_id),
            "policy_id": str(self.policy_id),
            "legal_entity_id": str(self.legal_entity_id),
            "effective_date": self.effective_date.isoformat(),
            "approved_by": self.approved_by,
            "reason": self.reason,
            "applied_at": self.applied_at.isoformat(),
            "applied_by": self.applied_by,
            "justification_document": self.justification_document,
        }


# === 3. NO RETROACTIVE POLICY ENFORCER ===


class NoRetroactivePolicyEnforcer:
    """
    Enforcer untuk hukum no retroactive policy.

    Business context: Kebijakan akuntansi baru hanya berlaku untuk
    periode setelah kebijakan tersebut ditetapkan. Pengecualian hanya
    jika diwajibkan oleh standar akuntansi atau regulator.
    """

    def __init__(
        self,
        policy_repository: Any | None = None,
        period_repository: Any | None = None,
    ):
        self._policy_repo = policy_repository or _FallbackPolicyRepository()
        self._period_repo = period_repository or _FallbackPeriodRepository()
        self._retroactive_records: list[RetroactiveApplicationRecord] = []
        self._violation_history: list[NoRetroactivePolicyViolation] = []
        self._max_history = 10000
        self._lock = threading.RLock()
        self._enabled = True
        self._strict_mode = True

    def enable(self, enabled: bool = True) -> None:
        self._enabled = enabled
        logger.info(f"No retroactive policy enforcer enabled: {enabled}")

    def set_strict_mode(self, strict: bool = True) -> None:
        self._strict_mode = strict
        logger.info(f"No retroactive policy enforcer strict mode: {strict}")

    async def enforce_no_retroactive(
        self,
        policy_id: UUID,
        effective_date: datetime,
        legal_entity_id: UUID,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, NoRetroactivePolicyViolation | None]:
        if not self._enabled:
            return True, None

        if user_id is None:
            user_id = get_current_user() or "unknown"

        current_period_start = await self._period_repo.get_period_start_date(legal_entity_id)
        if not current_period_start:
            return True, None

        policy_data = await self._policy_repo.get_by_id(policy_id, legal_entity_id)
        if not policy_data:
            return True, None

        if effective_date < current_period_start:
            violation = NoRetroactivePolicyViolation(
                message=(
                    f"Policy {policy_id} cannot be applied retroactively to date {effective_date.date()}. "
                    f"This would affect periods before {current_period_start.date()}."
                ),
                policy_id=str(policy_id),
                effective_date=effective_date.isoformat(),
                severity=LawViolationSeverity.HIGH,
                details={
                    "policy_id": str(policy_id),
                    "effective_date": effective_date.isoformat(),
                    "current_period_start": current_period_start.isoformat(),
                    "user_id": user_id,
                },
            )
            self._record_violation(violation)
            if raise_on_violation:
                raise violation
            return False, violation

        today = datetime.now(UTC)
        if effective_date < today and effective_date >= current_period_start:
            logger.warning(
                f"Policy {policy_id} applied retroactively within current period by {user_id}"
            )

        return True, None

    async def enforce_policy_transition(
        self,
        old_policy_id: UUID,
        new_policy_id: UUID,
        transition_date: datetime,
        legal_entity_id: UUID,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, NoRetroactivePolicyViolation | None]:
        if not self._enabled:
            return True, None

        if user_id is None:
            user_id = get_current_user() or "unknown"

        old_policy = await self._policy_repo.get_by_id(old_policy_id, legal_entity_id)
        if not old_policy:
            return True, None

        old_effective = old_policy.get("effective_date")
        if not old_effective:
            return True, None

        if transition_date < old_effective:
            violation = NoRetroactivePolicyViolation(
                message=(
                    f"Cannot transition to new policy before old policy's effective date "
                    f"{old_effective.date()}"
                ),
                policy_id=str(new_policy_id),
                effective_date=transition_date.isoformat(),
                severity=LawViolationSeverity.HIGH,
                details={
                    "old_policy_id": str(old_policy_id),
                    "new_policy_id": str(new_policy_id),
                    "transition_date": transition_date.isoformat(),
                    "old_effective_date": old_effective.isoformat(),
                },
            )
            self._record_violation(violation)
            if raise_on_violation:
                raise violation
            return False, violation

        return True, None

    async def allow_retroactive_with_approval(
        self,
        policy_id: UUID,
        effective_date: datetime,
        legal_entity_id: UUID,
        approved_by: list[str],
        reason: str,
        regulatory_mandate: bool = False,
        justification_document: str | None = None,
        applied_by: str | None = None,
    ) -> RetroactiveApplicationRecord:
        if applied_by is None:
            applied_by = get_current_user() or "unknown"

        valid_reasons = [r.value for r in RetroactiveReason]
        if reason not in valid_reasons:
            raise NoRetroactivePolicyViolation(
                message=f"Invalid reason for retroactive policy: {reason}. Valid reasons: {valid_reasons}",
                policy_id=str(policy_id),
                effective_date=effective_date.isoformat(),
                severity=LawViolationSeverity.MEDIUM,
            )

        if regulatory_mandate:
            logger.info(f"Retroactive policy {policy_id} allowed due to regulatory mandate")
            approved_by = ["regulatory_mandate"]
        else:
            if len(approved_by) < 2:
                raise NoRetroactivePolicyViolation(
                    message=f"Retroactive policy requires at least 2 approvals (got {len(approved_by)})",
                    policy_id=str(policy_id),
                    effective_date=effective_date.isoformat(),
                    severity=LawViolationSeverity.HIGH,
                )

        record = RetroactiveApplicationRecord(
            record_id=uuid4(),
            policy_id=policy_id,
            legal_entity_id=legal_entity_id,
            effective_date=effective_date,
            approved_by=approved_by,
            reason=reason,
            applied_at=datetime.now(UTC),
            applied_by=applied_by,
            justification_document=justification_document,
            cryptographic_hash="",
        )
        record.cryptographic_hash = record.compute_hash()

        await self._policy_repo.record_retroactive_application(
            policy_id=policy_id,
            legal_entity_id=legal_entity_id,
            effective_date=effective_date,
            approved_by=approved_by,
            reason=reason,
            applied_at=record.applied_at,
        )

        with self._lock:
            self._retroactive_records.append(record)
            if len(self._retroactive_records) > self._max_history:
                self._retroactive_records = self._retroactive_records[-self._max_history :]

        logger.warning(
            f"Retroactive policy {policy_id} approved by {approved_by}. Reason: {reason}"
        )
        return record

    async def get_policy_effective_summary(
        self,
        legal_entity_id: UUID,
        as_of_date: datetime | None = None,
    ) -> dict[str, Any]:
        as_of = as_of_date or datetime.now(UTC)
        policies = await self._policy_repo.get_active_policies(
            legal_entity_id=legal_entity_id,
            as_of=as_of,
        )

        active_policies = []
        retroactive_count = 0
        for p in policies:
            eff_date = p.get("effective_date")
            if eff_date:
                is_retro = eff_date < as_of
                if is_retro:
                    retroactive_count += 1
                active_policies.append(
                    {
                        "policy_id": str(p.get("policy_id")),
                        "policy_name": p.get("policy_name"),
                        "policy_type": p.get("policy_type"),
                        "effective_date": eff_date.isoformat(),
                        "is_retroactive": is_retro,
                        "description": p.get("description", "")[:100],
                    }
                )
            else:
                active_policies.append(
                    {
                        "policy_id": str(p.get("policy_id")),
                        "policy_name": p.get("policy_name"),
                        "policy_type": p.get("policy_type"),
                        "effective_date": None,
                        "is_retroactive": False,
                    }
                )

        return {
            "as_of_date": as_of.isoformat(),
            "legal_entity_id": str(legal_entity_id),
            "active_policies": active_policies,
            "total_active": len(active_policies),
            "retroactive_count": retroactive_count,
        }

    async def get_retroactive_applications(
        self,
        policy_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        limit: int = 100,
    ) -> list[RetroactiveApplicationRecord]:
        with self._lock:
            result = self._retroactive_records[-limit:]
        if policy_id:
            result = [r for r in result if r.policy_id == policy_id]
        if legal_entity_id:
            result = [r for r in result if r.legal_entity_id == legal_entity_id]
        return result

    async def create_policy(
        self,
        legal_entity_id: UUID,
        policy_name: str,
        policy_type: PolicyType,
        effective_date: datetime,
        created_by: str,
        approved_by: list[str],
        description: str = "",
        is_active: bool = True,
    ) -> AccountingPolicy:
        policy_id = uuid4()
        policy = AccountingPolicy(
            policy_id=policy_id,
            legal_entity_id=legal_entity_id,
            policy_name=policy_name,
            policy_type=policy_type,
            effective_date=effective_date,
            created_by=created_by,
            created_at=datetime.now(UTC),
            approved_by=approved_by,
            is_active=is_active,
            description=description,
            cryptographic_hash="",
        )
        policy.cryptographic_hash = policy.compute_hash()

        await self._policy_repo.create_policy(
            policy_id=policy_id,
            legal_entity_id=legal_entity_id,
            policy_name=policy_name,
            policy_type=policy_type.value,
            effective_date=effective_date,
            created_by=created_by,
            approved_by=approved_by,
            description=description,
        )

        logger.info(
            f"Policy created: {policy_name} (type {policy_type.value}) effective {effective_date.date()}"
        )
        return policy

    async def update_policy_status(
        self,
        policy_id: UUID,
        legal_entity_id: UUID,
        is_active: bool,
        updated_by: str,
    ) -> bool:
        success = await self._policy_repo.update_policy_status(
            policy_id=policy_id,
            legal_entity_id=legal_entity_id,
            is_active=is_active,
            updated_by=updated_by,
        )
        if success:
            logger.info(
                f"Policy {policy_id} status changed to {'active' if is_active else 'inactive'} by {updated_by}"
            )
        return success

    def _record_violation(self, violation: NoRetroactivePolicyViolation) -> None:
        with self._lock:
            self._violation_history.append(violation)
            if len(self._violation_history) > self._max_history:
                self._violation_history = self._violation_history[-self._max_history :]

    def get_violations(
        self,
        limit: int = 100,
        policy_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> list[NoRetroactivePolicyViolation]:
        with self._lock:
            result = self._violation_history[-limit:]
        if policy_id:
            result = [v for v in result if v.policy_id == str(policy_id)]
        if legal_entity_id:
            result = [
                v for v in result if str(legal_entity_id) in v.details.get("legal_entity_id", "")
            ]
        return result

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_violations = len(self._violation_history)
            total_retroactive = len(self._retroactive_records)

            by_reason = {}
            for r in self._retroactive_records:
                by_reason[r.reason] = by_reason.get(r.reason, 0) + 1

            return {
                "total_violations": total_violations,
                "total_retroactive_applications": total_retroactive,
                "by_reason": by_reason,
                "enabled": self._enabled,
                "strict_mode": self._strict_mode,
                "latest_violation": self._violation_history[-1].timestamp.isoformat()
                if self._violation_history
                else None,
                "latest_retroactive": self._retroactive_records[-1].applied_at.isoformat()
                if self._retroactive_records
                else None,
            }

    def reset(self) -> None:
        with self._lock:
            self._retroactive_records = []
            self._violation_history = []
            self._enabled = True
            self._strict_mode = True
            if hasattr(self._policy_repo, "clear"):
                self._policy_repo.clear()
            if hasattr(self._period_repo, "clear"):
                self._period_repo.clear()


# === 4. SINGLETON ACCESSOR ===

_no_retroactive_policy_enforcer_instance: NoRetroactivePolicyEnforcer | None = None
_lock_instance = threading.Lock()


def get_no_retroactive_policy_enforcer() -> NoRetroactivePolicyEnforcer:
    global _no_retroactive_policy_enforcer_instance
    if _no_retroactive_policy_enforcer_instance is None:
        with _lock_instance:
            if _no_retroactive_policy_enforcer_instance is None:
                _no_retroactive_policy_enforcer_instance = NoRetroactivePolicyEnforcer()
    return _no_retroactive_policy_enforcer_instance


# === 5. EXPORTS ===

__all__ = [
    "AccountingPolicy",
    "NoRetroactivePolicyEnforcer",
    "PolicyType",
    "RetroactiveApplicationRecord",
    "RetroactiveReason",
    "get_no_retroactive_policy_enforcer",
]
