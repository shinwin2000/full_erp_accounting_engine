#!/usr/bin/env python3
"""
Module: immutable_laws.py
Layer: 4 - Kernel / Immutable Laws
Responsibility: Enforce constitutional invariants (immutability, dual approval, evidence, etc.)
               Setiap enforcer memiliki method check() untuk memvalidasi konteks,
               serta method entity dasar untuk audit, serialisasi, dan versioning.

Metode yang ditambahkan untuk setiap enforcer:
- validate(), to_dict(), from_dict(), clone(), snapshot(), version(), audit_trail(), touch()
- enforce() (alternatif check yang lebih eksplisit)
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Base Enforcer (abstract base class dengan method entity dasar)
# ============================================================================


class BaseEnforcer:
    """Base class untuk semua immutable law enforcer."""

    def __init__(self, name: str):
        self.name = name
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._version = 1

    def validate(self) -> dict[str, Any]:
        """Validate enforcer internal state."""
        errors = []
        if not self.name:
            errors.append("Enforcer name is required")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseEnforcer:
        instance = cls(data["name"])
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> BaseEnforcer:
        new_instance = self.__class__(self.name)
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self._version,
            "timestamp": datetime.now().isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> BaseEnforcer:
        self._version += 1
        self._audit_trail.append(
            {
                "action": "TOUCH",
                "performed_by": touched_by,
                "timestamp": datetime.now().isoformat(),
                "version": self._version,
            }
        )
        return self

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now().isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    # ---- Added for compliance with immutable_laws_checker ----
    def check(self, context: dict[str, Any]) -> list[str]:
        """
        Base check implementation. Returns empty list (no violations).
        Override in subclasses to enforce specific rules.
        """
        return []

    def enforce(self, context: dict[str, Any]) -> None:
        """
        Base enforce implementation. Does nothing.
        Override in subclasses to raise appropriate exceptions on violation.
        """
        pass


# ============================================================================
# ImmutabilityEnforcer
# ============================================================================


class ImmutabilityEnforcer(BaseEnforcer):
    """Enforces that immutable events cannot be modified."""

    def __init__(self):
        super().__init__("immutability_enforcer")
        self._immutable_events = set()  # track event IDs that are immutable

    def enforce_modification(self, event: dict[str, Any]) -> None:
        """Raise error if trying to modify an immutable event."""
        event_id = event.get("id")
        if event_id in self._immutable_events:
            raise ImmutabilityError("Cannot modify immutable event")

    def enforce_creation(self, event: dict[str, Any]) -> None:
        """Mark newly created event as immutable."""
        event_id = event.get("id")
        if event_id:
            self._immutable_events.add(event_id)
            self._record_audit("ENFORCE_CREATION", "system", {"event_id": event_id})

    def check(self, context: dict[str, Any]) -> list[str]:
        """Alias for compatibility with other enforcers (returns empty list)."""
        errors = []
        event_id = context.get("event_id")
        if event_id and event_id in self._immutable_events:
            errors.append(f"Event {event_id} is immutable and cannot be modified")
        return errors

    def enforce(self, context: dict[str, Any]) -> None:
        """Enforce immutability, raise error if violated."""
        errors = self.check(context)
        if errors:
            raise ImmutabilityError(errors[0])

    # Override entity methods to include state
    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["immutable_events"] = list(self._immutable_events)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImmutabilityEnforcer:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._immutable_events = set(data.get("immutable_events", []))
        if "name" in data:
            instance.name = data["name"]
        return instance

    def clone(self) -> ImmutabilityEnforcer:
        new_instance = ImmutabilityEnforcer()
        new_instance._immutable_events = self._immutable_events.copy()
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        snap = super().snapshot()
        snap["immutable_events_count"] = len(self._immutable_events)
        return snap


class ImmutabilityError(Exception):
    pass


# ============================================================================
# EvidenceMandateEnforcer
# ============================================================================


class EvidenceMandateEnforcer(BaseEnforcer):
    """Enforces that certain transactions require evidence attachments."""

    def __init__(self):
        super().__init__("evidence_mandate_enforcer")
        self._mandatory_transaction_types = [
            "WRITE_OFF",
            "ADJUSTMENT",
            "write_off",
            "REVERSAL",
            "CANCELLATION",
        ]

    def check(self, context: dict[str, Any]) -> list[str]:
        errors = []
        attachments = context.get("attachments", [])
        transaction_type = context.get("type", "")
        if transaction_type in self._mandatory_transaction_types and not attachments:
            errors.append("Write-off or adjustment requires supporting evidence")
        return errors

    def enforce(self, context: dict[str, Any]) -> None:
        errors = self.check(context)
        if errors:
            raise EvidenceMandateError(errors[0])

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["mandatory_transaction_types"] = self._mandatory_transaction_types
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceMandateEnforcer:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._mandatory_transaction_types = data.get(
            "mandatory_transaction_types", instance._mandatory_transaction_types
        )
        if "name" in data:
            instance.name = data["name"]
        return instance

    def clone(self) -> EvidenceMandateEnforcer:
        new_instance = EvidenceMandateEnforcer()
        new_instance._mandatory_transaction_types = self._mandatory_transaction_types.copy()
        new_instance._version = self._version + 1
        return new_instance


class EvidenceMandateError(Exception):
    pass


# ============================================================================
# DualApprovalEnforcer
# ============================================================================


class DualApprovalEnforcer(BaseEnforcer):
    """Enforces that journal entries require two different approvers."""

    def __init__(self):
        super().__init__("dual_approval_enforcer")
        self._require_dual_approval_for = ["JOURNAL", "PAYMENT", "WRITE_OFF"]

    def check(self, context: dict[str, Any]) -> list[str]:
        errors = []
        transaction_type = context.get("transaction_type", context.get("type", ""))
        if transaction_type in self._require_dual_approval_for:
            approvals = context.get("approvals", [])
            if len(approvals) < 2:
                errors.append("Journal requires two approvals")
            else:
                approvers = [a.get("approver") for a in approvals if a.get("approver")]
                if len(set(approvers)) < 2:
                    errors.append("Approvers must be different")
        return errors

    def enforce(self, context: dict[str, Any]) -> None:
        errors = self.check(context)
        if errors:
            raise DualApprovalError(errors[0])

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["require_dual_approval_for"] = self._require_dual_approval_for
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DualApprovalEnforcer:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._require_dual_approval_for = data.get(
            "require_dual_approval_for", instance._require_dual_approval_for
        )
        if "name" in data:
            instance.name = data["name"]
        return instance

    def clone(self) -> DualApprovalEnforcer:
        new_instance = DualApprovalEnforcer()
        new_instance._require_dual_approval_for = self._require_dual_approval_for.copy()
        new_instance._version = self._version + 1
        return new_instance


class DualApprovalError(Exception):
    pass


# ============================================================================
# ReversalConstraintEnforcer
# ============================================================================


class ReversalConstraintEnforcer(BaseEnforcer):
    """Enforces that reversals are only allowed within current open period."""

    def __init__(self):
        super().__init__("reversal_constraint_enforcer")

    def check(self, context: dict[str, Any]) -> list[str]:
        errors = []
        period = context.get("period")
        current_period = context.get("current_period")
        period_status = context.get("period_status", "open")
        if period and current_period and period == current_period and period_status == "open":
            pass  # allowed
        elif period_status == "closed":
            errors.append("Reversal not allowed in closed period")
        elif period and current_period and period != current_period:
            errors.append("Reversal only allowed in current period")
        return errors

    def enforce(self, context: dict[str, Any]) -> None:
        errors = self.check(context)
        if errors:
            raise ReversalConstraintError(errors[0])


class ReversalConstraintError(Exception):
    pass


# ============================================================================
# TraceabilityEnforcer
# ============================================================================


class TraceabilityEnforcer(BaseEnforcer):
    """Enforces that every transaction has a causation_id for traceability."""

    def __init__(self):
        super().__init__("traceability_enforcer")

    def check(self, context: dict[str, Any]) -> list[str]:
        errors = []
        if not context.get("causation_id") and not context.get("source_document_id"):
            errors.append("Missing causation_id or source_document_id for traceability")
        return errors

    def enforce(self, context: dict[str, Any]) -> None:
        errors = self.check(context)
        if errors:
            raise TraceabilityError(errors[0])


class TraceabilityError(Exception):
    pass


# ============================================================================
# PeriodClosureEnforcer
# ============================================================================


class PeriodClosureEnforcer(BaseEnforcer):
    """Enforces that transactions cannot be posted to closed periods."""

    def __init__(self):
        super().__init__("period_closure_enforcer")

    def check(self, context: dict[str, Any]) -> list[str]:
        errors = []
        period = context.get("period")
        current_period = context.get("current_period")
        period_status = context.get("period_status", "open")
        if period and current_period and period != current_period:
            if period_status == "closed":
                errors.append(f"Cannot post to closed period {period}")
            elif period_status == "locked":
                errors.append(f"Period {period} is locked")
        return errors

    def enforce(self, context: dict[str, Any]) -> None:
        errors = self.check(context)
        if errors:
            raise PeriodClosureError(errors[0])


class PeriodClosureError(Exception):
    pass


# ============================================================================
# GLSupremacyEnforcer
# ============================================================================


class GLSupremacyEnforcer(BaseEnforcer):
    """Enforces that every subledger transaction has a corresponding GL entry."""

    def __init__(self):
        super().__init__("gl_supremacy_enforcer")

    def check(self, context: dict[str, Any]) -> list[str]:
        errors = []
        gl_entries = context.get("gl_entries", [])
        if not gl_entries and context.get("requires_gl", True):
            errors.append("Missing GL entry for subledger transaction")
        return errors

    def enforce(self, context: dict[str, Any]) -> None:
        errors = self.check(context)
        if errors:
            raise GLSupremacyError(errors[0])


class GLSupremacyError(Exception):
    pass


# ============================================================================
# SegregationOfDutiesEnforcer
# ============================================================================


class SegregationOfDutiesEnforcer(BaseEnforcer):
    """Enforces segregation of duties (e.g., same user cannot create and approve)."""

    def __init__(self):
        super().__init__("segregation_of_duties_enforcer")

    def check(self, context: dict[str, Any]) -> list[str]:
        errors = []
        created_by = context.get("created_by")
        approved_by = context.get("approved_by")
        if created_by and approved_by and created_by == approved_by:
            errors.append("Same user cannot create and approve transaction")
        # Additional SOD checks
        posted_by = context.get("posted_by")
        if created_by and posted_by and created_by == posted_by:
            errors.append("Same user cannot create and post transaction")
        return errors

    def enforce(self, context: dict[str, Any]) -> None:
        errors = self.check(context)
        if errors:
            raise SegregationOfDutiesError(errors[0])


class SegregationOfDutiesError(Exception):
    pass


# ============================================================================
# NoRetroactivePolicyEnforcer
# ============================================================================


class NoRetroactivePolicyEnforcer(BaseEnforcer):
    """Enforces that policy changes cannot be applied retroactively."""

    def __init__(self):
        super().__init__("no_retroactive_policy_enforcer")

    def check(self, context: dict[str, Any]) -> list[str]:
        errors = []
        effective_date = context.get("effective_date")
        current_date = context.get("current_date", date.today())
        if effective_date and isinstance(effective_date, date) and effective_date < current_date:
            errors.append("Cannot apply policy change retroactively")
        return errors

    def enforce(self, context: dict[str, Any]) -> None:
        errors = self.check(context)
        if errors:
            raise NoRetroactivePolicyError(errors[0])


class NoRetroactivePolicyError(Exception):
    pass


# ============================================================================
# AuditTrailCompletenessEnforcer
# ============================================================================


class AuditTrailCompletenessEnforcer(BaseEnforcer):
    """Enforces that all transactions have complete audit records."""

    def __init__(self):
        super().__init__("audit_trail_completeness_enforcer")

    def check(self, context: dict[str, Any]) -> list[str]:
        errors = []
        audit_records = context.get("audit_records", [])
        if not audit_records and context.get("requires_audit", True):
            errors.append("Missing audit trail records")
        # Check minimal fields
        for record in audit_records:
            if not record.get("timestamp"):
                errors.append("Audit record missing timestamp")
            if not record.get("action"):
                errors.append("Audit record missing action")
        return errors

    def enforce(self, context: dict[str, Any]) -> None:
        errors = self.check(context)
        if errors:
            raise AuditTrailCompletenessError(errors[0])


class AuditTrailCompletenessError(Exception):
    pass


# ============================================================================
# AssetExistenceEnforcer
# ============================================================================


class AssetExistenceEnforcer(BaseEnforcer):
    """Enforces that referenced assets exist in the asset register."""

    def __init__(self):
        super().__init__("asset_existence_enforcer")
        self._asset_register: set[str] = set()

    def register_asset(self, asset_id: str) -> None:
        self._asset_register.add(asset_id)

    def check(self, context: dict[str, Any]) -> list[str]:
        errors = []
        asset_id = context.get("asset_id")
        if asset_id and asset_id not in self._asset_register:
            errors.append(f"Asset {asset_id} not found in asset register")
        return errors

    def enforce(self, context: dict[str, Any]) -> None:
        errors = self.check(context)
        if errors:
            raise AssetExistenceError(errors[0])

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["asset_register"] = list(self._asset_register)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AssetExistenceEnforcer:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._asset_register = set(data.get("asset_register", []))
        if "name" in data:
            instance.name = data["name"]
        return instance

    def clone(self) -> AssetExistenceEnforcer:
        new_instance = AssetExistenceEnforcer()
        new_instance._asset_register = self._asset_register.copy()
        new_instance._version = self._version + 1
        return new_instance


class AssetExistenceError(Exception):
    pass


# ============================================================================
# FairValueMeasurementEnforcer
# ============================================================================


class FairValueMeasurementEnforcer(BaseEnforcer):
    """Enforces fair value measurement for certain asset types."""

    def __init__(self):
        super().__init__("fair_value_measurement_enforcer")
        self._fair_value_asset_types = [
            "derivative",
            "investment_property",
            "InvestmentProperty",
            "financial_instrument",
        ]

    def check(self, context: dict[str, Any]) -> list[str]:
        errors = []
        asset_type = context.get("asset_type")
        fair_value = context.get("fair_value")
        if asset_type in self._fair_value_asset_types and fair_value is None:
            errors.append("Fair value required for this asset type")
        return errors

    def enforce(self, context: dict[str, Any]) -> None:
        errors = self.check(context)
        if errors:
            raise FairValueMeasurementError(errors[0])

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["fair_value_asset_types"] = self._fair_value_asset_types
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FairValueMeasurementEnforcer:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._fair_value_asset_types = data.get(
            "fair_value_asset_types", instance._fair_value_asset_types
        )
        if "name" in data:
            instance.name = data["name"]
        return instance

    def clone(self) -> FairValueMeasurementEnforcer:
        new_instance = FairValueMeasurementEnforcer()
        new_instance._fair_value_asset_types = self._fair_value_asset_types.copy()
        new_instance._version = self._version + 1
        return new_instance


class FairValueMeasurementError(Exception):
    pass


# ============================================================================
# Export all classes
# ============================================================================

__all__ = [
    "AssetExistenceEnforcer",
    "AssetExistenceError",
    "AuditTrailCompletenessEnforcer",
    "AuditTrailCompletenessError",
    "BaseEnforcer",
    "DualApprovalEnforcer",
    "DualApprovalError",
    "EvidenceMandateEnforcer",
    "EvidenceMandateError",
    "FairValueMeasurementEnforcer",
    "FairValueMeasurementError",
    "GLSupremacyEnforcer",
    "GLSupremacyError",
    "ImmutabilityEnforcer",
    "ImmutabilityError",
    "NoRetroactivePolicyEnforcer",
    "NoRetroactivePolicyError",
    "PeriodClosureEnforcer",
    "PeriodClosureError",
    "ReversalConstraintEnforcer",
    "ReversalConstraintError",
    "SegregationOfDutiesEnforcer",
    "SegregationOfDutiesError",
    "TraceabilityEnforcer",
    "TraceabilityError",
]
