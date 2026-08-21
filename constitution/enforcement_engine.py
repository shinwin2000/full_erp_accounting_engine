#!/usr/bin/env python3
"""
Module: enforcement_engine.py
Layer: 1 - Foundation / Constitution
Responsibility: Mesin penegak konstitusi. Bertanggung jawab memverifikasi
               bahwa setiap transaksi, command, atau operasi mematuhi seluruh
               aturan konstitusi, aksioma, invariant, dan larangan state.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Any, ClassVar
from uuid import UUID, uuid4

from constitution.amendment_protocol import get_amendment_protocol
from constitution.constitutional_invariants import (
    InvariantSeverity,
    InvariantType,
    get_constitutional_invariants_service,
)
from constitution.forbidden_states import (
    ForbiddenStateAction,
    ForbiddenStateCategory,
    ForbiddenStateSeverity,
    get_forbidden_states_service,
)
from constitution.sovereignty_declaration import (
    SovereigntyDomain,
    SovereigntyStatus,
    get_sovereignty_guardian,
)
from constitution.supreme_law import (
    ConstitutionalPrinciple,
    ConstitutionalViolationError,
    get_supreme_law,
)
from constitution.version_lock import get_version_lock_service

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class EnforcementResult(Enum):
    PASS = auto()
    REJECTED = auto()
    REQUIRE_APPROVAL = auto()
    DEFERRED = auto()
    CATASTROPHIC = auto()


class EnforcementStage(Enum):
    PREFLIGHT = auto()
    CONSTITUTION_CHECK = auto()
    SOVEREIGNTY_CHECK = auto()
    INVARIANT_CHECK = auto()
    FORBIDDEN_STATE_CHECK = auto()
    VERSION_LOCK_CHECK = auto()
    AMENDMENT_CHECK = auto()
    DUAL_APPROVAL = auto()
    FINAL_APPROVAL = auto()


class EnforcementMode(Enum):
    NORMAL = auto()
    AUDIT = auto()
    EMERGENCY = auto()
    MAINTENANCE = auto()


# === 2. CUSTOM EXCEPTIONS ===


class EnforcementError(Exception):
    pass


class EnforcementRejectedError(EnforcementError):
    def __init__(self, stage: EnforcementStage, reason: str):
        self.stage = stage
        self.reason = reason
        super().__init__(f"Enforcement rejected at {stage.name}: {reason}")


class EnforcementCatastrophicError(EnforcementError):
    pass


# === 3. VALUE OBJECTS ===


@dataclass(frozen=True)
class EnforcementReport:
    # Required fields (no defaults)
    report_id: UUID
    operation_id: UUID
    operation_type: str
    timestamp: datetime
    stages_passed: list[EnforcementStage]
    stages_failed: list[tuple[EnforcementStage, str]]
    final_result: EnforcementResult
    rejection_reason: str | None
    required_approvers: list[str]
    execution_time_ms: float
    constitutional_hash: str
    # Optional fields (with defaults)
    mode: EnforcementMode = EnforcementMode.NORMAL
    warning_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def compute_hash(self) -> str:
        content = (
            f"{self.report_id}|{self.operation_id}|{self.operation_type}|"
            f"{self.timestamp.isoformat()}|{self.final_result.value}|"
            f"{self.rejection_reason or ''}|{','.join(self.required_approvers)}|"
            f"{self.mode.value}|{self.warning_count}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def is_passed(self) -> bool:
        return self.final_result == EnforcementResult.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": str(self.report_id),
            "operation_id": str(self.operation_id),
            "operation_type": self.operation_type,
            "timestamp": self.timestamp.isoformat(),
            "stages_passed": [s.name for s in self.stages_passed],
            "stages_failed": [(s.name, r) for s, r in self.stages_failed],
            "final_result": self.final_result.name,
            "rejection_reason": self.rejection_reason,
            "required_approvers": self.required_approvers,
            "execution_time_ms": self.execution_time_ms,
            "mode": self.mode.name,
            "warning_count": self.warning_count,
        }


@dataclass(frozen=True)
class EnforcementContext:
    # Required fields (no defaults)
    operation_id: UUID
    operation_type: str
    user_id: str | None
    user_roles: list[str]
    legal_entity_id: UUID | None
    period_id: UUID | None
    transaction_id: UUID | None
    source: str
    data: dict[str, Any]
    # Optional fields (with defaults)
    is_amendment: bool = False
    amendment_proposal_id: UUID | None = None
    mode: EnforcementMode = EnforcementMode.NORMAL
    idempotency_key: str | None = None


# === 4. ENFORCEMENT PIPELINE ===


class EnforcementPipeline:
    def __init__(self) -> None:
        self._stages: list[tuple[EnforcementStage, Callable]] = []
        self._build_pipeline()

    def _build_pipeline(self) -> None:
        self._stages = [
            (EnforcementStage.PREFLIGHT, self._check_preflight),
            (EnforcementStage.CONSTITUTION_CHECK, self._check_constitution),
            (EnforcementStage.SOVEREIGNTY_CHECK, self._check_sovereignty),
            (EnforcementStage.VERSION_LOCK_CHECK, self._check_version_lock),
            (EnforcementStage.AMENDMENT_CHECK, self._check_amendment_status),
            (EnforcementStage.INVARIANT_CHECK, self._check_invariants),
            (EnforcementStage.FORBIDDEN_STATE_CHECK, self._check_forbidden_states),
            (EnforcementStage.DUAL_APPROVAL, self._check_dual_approval),
            (EnforcementStage.FINAL_APPROVAL, self._check_final_approval),
        ]

    def _check_preflight(
        self,
        ctx: EnforcementContext,
        **kwargs,
    ) -> tuple[bool, str, list[str]]:
        warnings: list[str] = []
        if not ctx.operation_id:
            return False, "Operation ID is required", warnings
        valid_operation_types = {
            "JOURNAL_POST",
            "JOURNAL_REVERSE",
            "ADJUSTING_ENTRY",
            "PERIOD_CLOSE",
            "PERIOD_REOPEN",
            "CASH_DISBURSEMENT",
            "CASH_RECEIPT",
            "GOODS_ISSUE",
            "GOODS_RECEIPT",
            "AR_PAYMENT",
            "AP_PAYMENT",
            "TAX_SUBMISSION",
            "CORETAX_SUBMIT",
            "USER_LOGIN",
            "ROLE_ASSIGN",
            "PERMISSION_CHANGE",
            "CONSTITUTION_AMENDMENT",
            "VERSION_UPGRADE",
            "SYSTEM_FREEZE",
            "EMERGENCY_OVERRIDE",
            "AUDIT_CORRECTION",
        }
        if ctx.operation_type not in valid_operation_types:
            warnings.append(f"Unknown operation type: {ctx.operation_type}")
        if ctx.idempotency_key and len(ctx.idempotency_key) > 255:
            warnings.append("Idempotency key exceeds 255 characters")
        return True, "Preflight check passed", warnings

    def _check_constitution(
        self,
        ctx: EnforcementContext,
        **kwargs,
    ) -> tuple[bool, str, list[str]]:
        supreme_law = get_supreme_law()
        warnings: list[str] = []
        principles_to_check = self._get_relevant_principles(ctx.operation_type)
        for principle in principles_to_check:
            try:
                sl_context = {
                    "total_debit": ctx.data.get("total_debit", 0),
                    "total_credit": ctx.data.get("total_credit", 0),
                    "user_id": ctx.user_id,
                    "command_id": ctx.operation_id,
                    "operation_type": ctx.operation_type,
                    "user_roles": ctx.user_roles,
                    "period_status": ctx.data.get("period_status", "OPEN"),
                    "transaction_date": ctx.data.get("transaction_date"),
                    "is_mutation": ctx.operation_type in ["JOURNAL_POST", "ADJUSTING_ENTRY"],
                    "is_correction": ctx.operation_type == "AUDIT_CORRECTION",
                    "audit_record_created": ctx.data.get("audit_record_created", False),
                }
                supreme_law.enforce(principle, sl_context, "enforcement_engine")
            except ConstitutionalViolationError as e:
                return False, f"Constitutional violation: {e}", warnings
            except Exception as e:
                warnings.append(f"Constitution check warning for {principle.name}: {e}")
        return True, "Constitution check passed", warnings

    def _get_relevant_principles(self, operation_type: str) -> list[ConstitutionalPrinciple]:
        if operation_type in ["JOURNAL_POST", "JOURNAL_REVERSE", "ADJUSTING_ENTRY"]:
            return [
                ConstitutionalPrinciple.DOUBLE_ENTRY,
                ConstitutionalPrinciple.IMMUTABILITY,
                ConstitutionalPrinciple.AUDIT_TRAIL_COMPLETENESS,
                ConstitutionalPrinciple.NON_REPUDIATION,
            ]
        elif operation_type in ["PERIOD_CLOSE", "PERIOD_REOPEN"]:
            return [
                ConstitutionalPrinciple.PERIOD_CLOSURE,
                ConstitutionalPrinciple.NO_RETROACTIVE_POLICY,
                ConstitutionalPrinciple.AUDIT_TRAIL_COMPLETENESS,
            ]
        elif operation_type in ["USER_LOGIN", "ROLE_ASSIGN", "PERMISSION_CHANGE"]:
            return [
                ConstitutionalPrinciple.SEGREGATION_OF_DUTIES,
                ConstitutionalPrinciple.ZERO_TRUST,
                ConstitutionalPrinciple.NON_REPUDIATION,
            ]
        elif operation_type in ["TAX_SUBMISSION", "CORETAX_SUBMIT"]:
            return [
                ConstitutionalPrinciple.REGULATORY_COMPLIANCE,
                ConstitutionalPrinciple.TAX_OBEDIENCE,
                ConstitutionalPrinciple.AUDIT_TRAIL_COMPLETENESS,
            ]
        elif operation_type == "CONSTITUTION_AMENDMENT":
            return [
                ConstitutionalPrinciple.NO_RETROACTIVE_POLICY,
                ConstitutionalPrinciple.AUDIT_TRAIL_COMPLETENESS,
            ]
        else:
            return [
                ConstitutionalPrinciple.IMMUTABILITY,
                ConstitutionalPrinciple.AUDIT_TRAIL_COMPLETENESS,
                ConstitutionalPrinciple.NON_REPUDIATION,
            ]

    def _check_sovereignty(
        self,
        ctx: EnforcementContext,
        **kwargs,
    ) -> tuple[bool, str, list[str]]:
        guardian = get_sovereignty_guardian()
        warnings: list[str] = []
        domain = self._infer_domain_from_operation(ctx.operation_type)
        operation = self._infer_operation_type(ctx.operation_type)
        try:
            guardian.guard(domain, operation, ctx.source, ctx.data, ctx.user_roles)
            return True, "Sovereignty check passed", warnings
        except Exception as e:
            return False, f"Sovereignty violation: {e}", warnings

    def _infer_domain_from_operation(self, operation_type: str) -> SovereigntyDomain:
        mapping = {
            "JOURNAL_POST": SovereigntyDomain.GENERAL_LEDGER,
            "JOURNAL_REVERSE": SovereigntyDomain.GENERAL_LEDGER,
            "ADJUSTING_ENTRY": SovereigntyDomain.GENERAL_LEDGER,
            "PERIOD_CLOSE": SovereigntyDomain.PERIOD_CONTROL,
            "PERIOD_REOPEN": SovereigntyDomain.PERIOD_CONTROL,
            "AR_PAYMENT": SovereigntyDomain.SUBLEDGER_AR,
            "AP_PAYMENT": SovereigntyDomain.SUBLEDGER_AP,
            "GOODS_ISSUE": SovereigntyDomain.INVENTORY,
            "GOODS_RECEIPT": SovereigntyDomain.INVENTORY,
            "TAX_SUBMISSION": SovereigntyDomain.TAX,
            "CORETAX_SUBMIT": SovereigntyDomain.TAX,
            "USER_LOGIN": SovereigntyDomain.USER_ACCESS,
            "ROLE_ASSIGN": SovereigntyDomain.USER_ACCESS,
            "PERMISSION_CHANGE": SovereigntyDomain.USER_ACCESS,
            "CONSTITUTION_AMENDMENT": SovereigntyDomain.CONSITUTION_ITSELF,
            "VERSION_UPGRADE": SovereigntyDomain.CONSITUTION_ITSELF,
        }
        return mapping.get(operation_type, SovereigntyDomain.GENERAL_LEDGER)

    def _infer_operation_type(self, operation_type: str) -> str:
        if "POST" in operation_type or "CREATE" in operation_type or "SUBMIT" in operation_type:
            return "CREATE"
        elif (
            "REVERSE" in operation_type or "MODIFY" in operation_type or "UPDATE" in operation_type
        ):
            return "UPDATE"
        elif "DELETE" in operation_type or "REPEAL" in operation_type:
            return "DELETE"
        elif "READ" in operation_type or "GET" in operation_type:
            return "READ"
        elif "CLOSE" in operation_type or "FREEZE" in operation_type:
            return "CLOSE"
        else:
            return "WRITE"

    def _check_version_lock(
        self,
        ctx: EnforcementContext,
        **kwargs,
    ) -> tuple[bool, str, list[str]]:
        version_service = get_version_lock_service()
        status = version_service.get_status()
        warnings: list[str] = []
        current_state = status["current_state"]
        if current_state == "FROZEN":
            if ctx.operation_type not in ["AUDIT_CORRECTION", "EMERGENCY_OVERRIDE"]:
                return False, "System is FROZEN - only audit corrections allowed", warnings
            warnings.append("System is in FROZEN state, limited operations only")
        elif current_state == "LOCKED":
            if not ctx.is_amendment and ctx.operation_type != "CONSTITUTION_AMENDMENT":
                return False, "System is LOCKED - only amendment operations allowed", warnings
        return True, "Version lock check passed", warnings

    def _check_amendment_status(
        self,
        ctx: EnforcementContext,
        **kwargs,
    ) -> tuple[bool, str, list[str]]:
        warnings: list[str] = []
        if ctx.operation_type != "CONSTITUTION_AMENDMENT":
            return True, "No amendment involved", warnings
        if not ctx.amendment_proposal_id:
            return False, "Amendment proposal ID required for amendment operation", warnings
        protocol = get_amendment_protocol()
        try:
            status = protocol.get_proposal_status(ctx.amendment_proposal_id)
            if status["approval_status"]["status"] != "approved":
                return (
                    False,
                    f"Amendment proposal {ctx.amendment_proposal_id} is not approved",
                    warnings,
                )
        except Exception as e:
            return False, f"Amendment check failed: {e}", warnings
        return True, "Amendment check passed", warnings

    def _check_invariants(
        self,
        ctx: EnforcementContext,
        **kwargs,
    ) -> tuple[bool, str, list[str]]:
        invariants_service = get_constitutional_invariants_service()
        warnings: list[str] = []
        relevant_invariants = self._get_relevant_invariants(ctx.operation_type, ctx.data)
        for inv_type in relevant_invariants:
            context_for_invariant = self._build_invariant_context(ctx, inv_type)
            is_valid, violation = invariants_service.validate(
                invariant_type=inv_type,
                context=context_for_invariant,
                transaction_id=ctx.transaction_id,
                legal_entity_id=ctx.legal_entity_id,
                period_id=ctx.period_id,
                offending_module="enforcement_engine",
                offending_user=ctx.user_id,
                auto_correct=ctx.mode == EnforcementMode.NORMAL,
            )
            if not is_valid and violation:
                if violation.severity == InvariantSeverity.CATASTROPHIC:
                    return False, f"CATASTROPHIC invariant violation: {violation.message}", warnings
                elif violation.severity == InvariantSeverity.CRITICAL:
                    return False, f"Critical invariant violation: {violation.message}", warnings
                else:
                    warnings.append(f"Invariant violation (non-critical): {violation.message}")
        return True, "Invariant check passed", warnings

    def _get_relevant_invariants(
        self,
        operation_type: str,
        data: dict[str, Any],
    ) -> list[InvariantType]:
        if operation_type in ["JOURNAL_POST", "ADJUSTING_ENTRY"]:
            return [
                InvariantType.DOUBLE_ENTRY_BALANCE,
                InvariantType.PERIOD_INTEGRITY,
                InvariantType.CURRENCY_CONSISTENCY,
            ]
        elif operation_type == "JOURNAL_REVERSE":
            return [
                InvariantType.DOUBLE_ENTRY_BALANCE,
                InvariantType.PERIOD_INTEGRITY,
                InvariantType.CONSERVATION_OF_VALUE,
            ]
        elif operation_type == "PERIOD_CLOSE":
            return [
                InvariantType.PERIOD_INTEGRITY,
                InvariantType.PERIOD_CLOSURE_FINALITY,
                InvariantType.ACCOUNTING_EQUATION,
            ]
        elif operation_type in ["CASH_DISBURSEMENT", "CASH_RECEIPT"]:
            return [
                InvariantType.NON_NEGATIVE_CASH,
                InvariantType.TIME_MONOTONICITY,
            ]
        elif operation_type in ["GOODS_ISSUE", "GOODS_RECEIPT"]:
            return [
                InvariantType.NON_NEGATIVE_INVENTORY,
            ]
        elif operation_type in ["AR_PAYMENT", "AP_PAYMENT"]:
            # NON_NEGATIVE_PAYABLE tidak ada dalam enum, gunakan NON_NEGATIVE_RECEIVABLE sebagai fallback
            if "AR" in operation_type:
                return [InvariantType.NON_NEGATIVE_RECEIVABLE]
            else:
                return [InvariantType.NON_NEGATIVE_RECEIVABLE]  # type: ignore[attr-defined]
        elif operation_type in ["TAX_SUBMISSION", "CORETAX_SUBMIT"]:
            return [
                InvariantType.TAX_CONSISTENCY,
            ]
        else:
            return [InvariantType.TIME_MONOTONICITY]

    def _build_invariant_context(
        self, ctx: EnforcementContext, inv_type: InvariantType
    ) -> dict[str, Any]:
        base_context = {
            "transaction_time": ctx.data.get("transaction_date", datetime.now(UTC)),
            "legal_entity_id": ctx.legal_entity_id,
            "user_id": ctx.user_id,
        }
        if inv_type == InvariantType.DOUBLE_ENTRY_BALANCE:
            base_context.update(
                {
                    "total_debit": ctx.data.get("total_debit", Decimal(0)),
                    "total_credit": ctx.data.get("total_credit", Decimal(0)),
                }
            )
        elif inv_type == InvariantType.PERIOD_INTEGRITY:
            base_context.update(
                {
                    "transaction_date": ctx.data.get("transaction_date"),
                    "period_start": ctx.data.get("period_start"),
                    "period_end": ctx.data.get("period_end"),
                    "period_status": ctx.data.get("period_status", "OPEN"),
                }
            )
        elif inv_type == InvariantType.NON_NEGATIVE_CASH:
            base_context.update(
                {
                    "cash_balance": ctx.data.get("cash_balance", Decimal(0)),
                    "proposed_change": ctx.data.get("proposed_cash_change", Decimal(0)),
                    "allow_overdraft": ctx.data.get("allow_overdraft", False),
                    "overdraft_limit": ctx.data.get("overdraft_limit", Decimal(0)),
                }
            )
        elif inv_type == InvariantType.NON_NEGATIVE_INVENTORY:
            base_context.update(
                {
                    "quantity": ctx.data.get("current_quantity", Decimal(0)),
                    "proposed_change": ctx.data.get("proposed_quantity_change", Decimal(0)),
                    "item_id": ctx.data.get("item_id"),
                    "warehouse_id": ctx.data.get("warehouse_id"),
                }
            )
        return base_context

    def _check_forbidden_states(
        self,
        ctx: EnforcementContext,
        **kwargs,
    ) -> tuple[bool, str, list[str]]:
        forbidden_service = get_forbidden_states_service()
        warnings: list[str] = []
        relevant_categories = self._get_relevant_forbidden_categories(ctx.operation_type)
        for category in relevant_categories:
            check_context = self._build_forbidden_context(ctx, category)
            if not check_context:
                continue
            is_forbidden, detection, action = forbidden_service.get_registry().check(
                category=category,
                context=check_context,
                transaction_id=ctx.transaction_id,
                legal_entity_id=ctx.legal_entity_id,
                source_module="enforcement_engine",
                source_user=ctx.user_id,
                override=ctx.mode == EnforcementMode.EMERGENCY,
            )
            if is_forbidden and detection:
                if detection.severity == ForbiddenStateSeverity.CATASTROPHIC:
                    return (
                        False,
                        f"CATASTROPHIC forbidden state: {detection.category.name}",
                        warnings,
                    )
                elif detection.severity == ForbiddenStateSeverity.CRITICAL:
                    return False, f"Critical forbidden state: {detection.category.name}", warnings
                else:
                    warnings.append(f"Forbidden state detected: {detection.category.name}")
                    if action == ForbiddenStateAction.REJECT:
                        return False, f"Forbidden state: {detection.category.name}", warnings
        return True, "Forbidden state check passed", warnings

    def _get_relevant_forbidden_categories(
        self, operation_type: str
    ) -> list[ForbiddenStateCategory]:
        mapping = {
            "JOURNAL_POST": [ForbiddenStateCategory.IMBALANCED_JOURNAL],
            "JOURNAL_REVERSE": [ForbiddenStateCategory.IMBALANCED_JOURNAL],
            "ADJUSTING_ENTRY": [ForbiddenStateCategory.IMBALANCED_JOURNAL],
            "CASH_DISBURSEMENT": [ForbiddenStateCategory.NEGATIVE_CASH],
            "CASH_WITHDRAWAL": [ForbiddenStateCategory.NEGATIVE_CASH],
            "GOODS_ISSUE": [ForbiddenStateCategory.NEGATIVE_INVENTORY],
            "AR_PAYMENT": [ForbiddenStateCategory.NEGATIVE_RECEIVABLE],
            "AP_PAYMENT": [ForbiddenStateCategory.NEGATIVE_PAYABLE],
            "PERIOD_CLOSE": [ForbiddenStateCategory.PERIOD_CLOSURE_VIOLATION],
            "BACKDATED_POSTING": [ForbiddenStateCategory.BACKDATED_TRANSACTION],
            "TAX_SUBMISSION": [ForbiddenStateCategory.TAX_MISMATCH],
        }
        return mapping.get(operation_type, [])

    def _build_forbidden_context(
        self, ctx: EnforcementContext, category: ForbiddenStateCategory
    ) -> dict[str, Any] | None:
        if category == ForbiddenStateCategory.NEGATIVE_CASH:
            return {
                "current_balance": ctx.data.get("cash_balance", Decimal(0)),
                "proposed_change": ctx.data.get("proposed_cash_change", Decimal(0)),
                "allow_overdraft": ctx.data.get("allow_overdraft", False),
                "overdraft_limit": ctx.data.get("overdraft_limit", Decimal(0)),
                "current_state": {"cash_balance": str(ctx.data.get("cash_balance", 0))},
            }
        elif category == ForbiddenStateCategory.NEGATIVE_INVENTORY:
            return {
                "current_quantity": ctx.data.get("current_quantity", Decimal(0)),
                "proposed_change": ctx.data.get("proposed_quantity_change", Decimal(0)),
                "allow_backorder": ctx.data.get("allow_backorder", False),
                "current_state": {"inventory_quantity": str(ctx.data.get("current_quantity", 0))},
            }
        elif category == ForbiddenStateCategory.IMBALANCED_JOURNAL:
            return {
                "total_debit": ctx.data.get("total_debit", Decimal(0)),
                "total_credit": ctx.data.get("total_credit", Decimal(0)),
                "tolerance": Decimal("0.0001"),
                "current_state": {
                    "total_debit": str(ctx.data.get("total_debit", 0)),
                    "total_credit": str(ctx.data.get("total_credit", 0)),
                },
            }
        elif category == ForbiddenStateCategory.BACKDATED_TRANSACTION:
            return {
                "transaction_date": ctx.data.get("transaction_date", datetime.now(UTC)),
                "current_period_start": ctx.data.get("period_start", datetime.now(UTC)),
                "max_backdate_days": ctx.data.get("max_backdate_days", 30),
            }
        elif category == ForbiddenStateCategory.PERIOD_CLOSURE_VIOLATION:
            return {
                "period_status": ctx.data.get("period_status", "OPEN"),
                "transaction_date": ctx.data.get("transaction_date", datetime.now(UTC)),
                "period_start": ctx.data.get("period_start", datetime.now(UTC)),
                "period_end": ctx.data.get("period_end", datetime.now(UTC)),
            }
        elif category == ForbiddenStateCategory.TAX_MISMATCH:
            return {
                "calculated_tax": ctx.data.get("calculated_tax", Decimal(0)),
                "reported_tax": ctx.data.get("reported_tax", Decimal(0)),
            }
        return None

    def _check_dual_approval(
        self,
        ctx: EnforcementContext,
        **kwargs,
    ) -> tuple[bool, str, list[str]]:
        warnings: list[str] = []
        amount = ctx.data.get("amount", Decimal(0))
        threshold_dual = Decimal("1000000000")  # 1 milyar
        if amount >= threshold_dual:
            approvers = ctx.data.get("approvers", [])
            if len(set(approvers)) < 2:
                required_approvers = ["CFO", "CEO"]
                return (
                    False,
                    f"Transaction >= {threshold_dual:,.0f} requires dual approval from {required_approvers}",
                    warnings,
                )
        if ctx.operation_type == "PERIOD_CLOSE":
            approvers = ctx.data.get("approvers", [])
            if "FINANCE_MANAGER" not in approvers or "AUDITOR" not in approvers:
                return (
                    False,
                    "Period close requires approval from Finance Manager and Auditor",
                    warnings,
                )
        return True, "Dual approval check passed", warnings

    def _check_final_approval(
        self,
        ctx: EnforcementContext,
        **kwargs,
    ) -> tuple[bool, str, list[str]]:
        warnings: list[str] = []
        user_roles = set(ctx.user_roles)
        amount = ctx.data.get("amount", Decimal(0))
        threshold_small = Decimal("50000000")
        threshold_medium = Decimal("500000000")
        threshold_large = Decimal("1000000000")
        threshold_very_large = Decimal("10000000000")
        if amount >= threshold_very_large:
            required_roles = {"CFO", "CEO", "PRESIDENT_DIRECTOR"}
            if not user_roles.intersection(required_roles):
                return (
                    False,
                    f"Transaction >= {threshold_very_large:,.0f} requires executive approval",
                    warnings,
                )
            if len(user_roles.intersection(required_roles)) < 2:
                return False, "Transaction >= 10B requires dual executive approval", warnings
        elif amount >= threshold_large:
            required_roles = {"CFO", "CEO", "FINANCE_DIRECTOR"}
            if not user_roles.intersection(required_roles):
                return (
                    False,
                    f"Transaction >= {threshold_large:,.0f} requires CFO/CEO approval",
                    warnings,
                )
        elif amount >= threshold_medium:
            required_roles = {"CFO", "FINANCE_MANAGER", "CONTROLLER"}
            if not user_roles.intersection(required_roles):
                return (
                    False,
                    f"Transaction >= {threshold_medium:,.0f} requires finance manager approval",
                    warnings,
                )
        elif amount >= threshold_small:
            required_roles = {"FINANCE_MANAGER", "ACCOUNTING_MANAGER", "SENIOR_ACCOUNTANT"}
            if not user_roles.intersection(required_roles):
                warnings.append(
                    f"Transaction >= {threshold_small:,.0f} normally requires senior approval"
                )
        if ctx.operation_type in ["JOURNAL_POST", "PAYMENT_APPROVAL", "INVOICE_APPROVAL"]:
            is_maker = "MAKER" in user_roles or "ACCOUNTANT" in user_roles
            is_approver = (
                "APPROVER" in user_roles or "FINANCE_MANAGER" in user_roles or "CFO" in user_roles
            )
            if is_maker and not is_approver and amount > threshold_small:
                warnings.append("Maker-approver conflict: user has MAKER role but no APPROVER role")
        return True, "Final approval passed", warnings

    def execute(
        self,
        ctx: EnforcementContext,
    ) -> EnforcementReport:
        start_time = time.time()
        stages_passed = []
        stages_failed = []
        warnings: list[str] = []
        final_result = EnforcementResult.PASS
        rejection_reason = None
        required_approvers = []
        for stage, check_func in self._stages:
            try:
                is_valid, message, stage_warnings = check_func(ctx)
                warnings.extend(stage_warnings)
                if not is_valid:
                    stages_failed.append((stage, message))
                    if stage in [
                        EnforcementStage.CONSTITUTION_CHECK,
                        EnforcementStage.INVARIANT_CHECK,
                        EnforcementStage.FORBIDDEN_STATE_CHECK,
                    ]:
                        if "CATASTROPHIC" in message:
                            final_result = EnforcementResult.CATASTROPHIC
                        else:
                            final_result = EnforcementResult.REJECTED
                        rejection_reason = message
                        break
                    elif stage in [EnforcementStage.DUAL_APPROVAL, EnforcementStage.FINAL_APPROVAL]:
                        final_result = EnforcementResult.REQUIRE_APPROVAL
                        rejection_reason = message
                        if "CFO" in message or "CEO" in message:
                            required_approvers = ["CFO", "CEO"]
                        elif "FINANCE_MANAGER" in message:
                            required_approvers = ["FINANCE_MANAGER"]
                        break
                    else:
                        final_result = EnforcementResult.REJECTED
                        rejection_reason = message
                        break
                else:
                    stages_passed.append(stage)
            except Exception as e:
                stages_failed.append((stage, f"Exception: {e!s}"))
                final_result = EnforcementResult.CATASTROPHIC
                rejection_reason = f"Exception in {stage.name}: {e!s}"
                logger.exception(f"Enforcement pipeline exception at {stage.name}")
                break
        execution_time_ms = (time.time() - start_time) * 1000
        report = EnforcementReport(
            report_id=uuid4(),
            operation_id=ctx.operation_id,
            operation_type=ctx.operation_type,
            timestamp=datetime.now(UTC),
            stages_passed=stages_passed,
            stages_failed=stages_failed,
            final_result=final_result,
            rejection_reason=rejection_reason,
            required_approvers=required_approvers,
            execution_time_ms=execution_time_ms,
            constitutional_hash="",
            mode=ctx.mode,
            warning_count=len(warnings),
            warnings=warnings,
        )
        report = EnforcementReport(
            report_id=report.report_id,
            operation_id=report.operation_id,
            operation_type=report.operation_type,
            timestamp=report.timestamp,
            stages_passed=report.stages_passed,
            stages_failed=report.stages_failed,
            final_result=report.final_result,
            rejection_reason=report.rejection_reason,
            required_approvers=report.required_approvers,
            execution_time_ms=report.execution_time_ms,
            constitutional_hash=report.compute_hash(),
            mode=report.mode,
            warning_count=report.warning_count,
            warnings=report.warnings,
        )
        if final_result == EnforcementResult.PASS:
            logger.info(
                f"Enforcement PASS for {ctx.operation_type} ({ctx.operation_id}) in {execution_time_ms:.2f}ms"
            )
        else:
            logger.warning(
                f"Enforcement {final_result.name} for {ctx.operation_type} ({ctx.operation_id}): {rejection_reason}"
            )
        return report


# === 5. ENFORCEMENT ENGINE SERVICE ===


class EnforcementEngine:
    _instance: ClassVar[EnforcementEngine | None] = None
    _history_lock: ClassVar[threading.Lock] = threading.Lock()
    _initialized: bool  # instance attribute, will be set in __new__
    _pipeline: EnforcementPipeline  # instance attribute
    _report_history: list[EnforcementReport]  # instance attribute

    def __new__(cls) -> EnforcementEngine:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._pipeline = EnforcementPipeline()
        self._report_history = []

    def enforce(
        self,
        ctx: EnforcementContext,
    ) -> EnforcementReport:
        report = self._pipeline.execute(ctx)
        with self._history_lock:
            self._report_history.append(report)
            if len(self._report_history) > 10000:
                self._report_history = self._report_history[-10000:]
        if report.final_result == EnforcementResult.REJECTED:
            stage = (
                report.stages_failed[0][0]
                if report.stages_failed
                else EnforcementStage.FINAL_APPROVAL
            )
            raise EnforcementRejectedError(stage, report.rejection_reason or "Unknown reason")
        if report.final_result == EnforcementResult.CATASTROPHIC:
            raise EnforcementCatastrophicError(
                report.rejection_reason or "Catastrophic enforcement failure"
            )
        return report

    def enforce_journal_posting(
        self,
        operation_id: UUID,
        total_debit: Decimal,
        total_credit: Decimal,
        transaction_date: datetime,
        legal_entity_id: UUID,
        period_id: UUID,
        user_id: str,
        user_roles: list[str],
        source: str = "internal_api",
        amount: Decimal | None = None,
        data: dict[str, Any] | None = None,
    ) -> EnforcementReport:
        ctx_data = data or {}
        ctx_data.update(
            {
                "total_debit": total_debit,
                "total_credit": total_credit,
                "transaction_date": transaction_date,
                "amount": amount or total_debit,
                "period_id": period_id,
                "period_start": (data or {}).get("period_start"),
                "period_end": (data or {}).get("period_end"),
                "period_status": (data or {}).get("period_status", "OPEN"),
            }
        )
        ctx = EnforcementContext(
            operation_id=operation_id,
            operation_type="JOURNAL_POST",
            user_id=user_id,
            user_roles=user_roles,
            legal_entity_id=legal_entity_id,
            period_id=period_id,
            transaction_id=operation_id,
            source=source,
            data=ctx_data,
            is_amendment=False,
        )
        return self.enforce(ctx)

    def enforce_period_close(
        self,
        operation_id: UUID,
        period_id: UUID,
        legal_entity_id: UUID,
        user_id: str,
        user_roles: list[str],
        approvers: list[str],
        source: str = "internal_api",
        data: dict[str, Any] | None = None,
    ) -> EnforcementReport:
        ctx_data = data or {}
        ctx_data.update(
            {
                "period_status": "OPEN",
                "period_id": period_id,
                "approvers": approvers,
            }
        )
        ctx = EnforcementContext(
            operation_id=operation_id,
            operation_type="PERIOD_CLOSE",
            user_id=user_id,
            user_roles=user_roles,
            legal_entity_id=legal_entity_id,
            period_id=period_id,
            transaction_id=operation_id,
            source=source,
            data=ctx_data,
            is_amendment=False,
        )
        return self.enforce(ctx)

    def enforce_cash_disbursement(
        self,
        operation_id: UUID,
        current_balance: Decimal,
        proposed_change: Decimal,
        legal_entity_id: UUID,
        user_id: str,
        user_roles: list[str],
        allow_overdraft: bool = False,
        overdraft_limit: Decimal = Decimal(0),
        source: str = "internal_api",
        data: dict[str, Any] | None = None,
    ) -> EnforcementReport:
        ctx_data = data or {}
        ctx_data.update(
            {
                "cash_balance": current_balance,
                "proposed_cash_change": proposed_change,
                "allow_overdraft": allow_overdraft,
                "overdraft_limit": overdraft_limit,
                "amount": abs(proposed_change),
            }
        )
        ctx = EnforcementContext(
            operation_id=operation_id,
            operation_type="CASH_DISBURSEMENT",
            user_id=user_id,
            user_roles=user_roles,
            legal_entity_id=legal_entity_id,
            period_id=None,
            transaction_id=operation_id,
            source=source,
            data=ctx_data,
            is_amendment=False,
        )
        return self.enforce(ctx)

    def enforce_ar_payment(
        self,
        operation_id: UUID,
        current_receivable: Decimal,
        proposed_payment: Decimal,
        legal_entity_id: UUID,
        customer_id: str,
        user_id: str,
        user_roles: list[str],
        source: str = "internal_api",
        data: dict[str, Any] | None = None,
    ) -> EnforcementReport:
        ctx_data = data or {}
        ctx_data.update(
            {
                "receivable_balance": current_receivable,
                "proposed_payment": proposed_payment,
                "amount": proposed_payment,
                "customer_id": customer_id,
            }
        )
        ctx = EnforcementContext(
            operation_id=operation_id,
            operation_type="AR_PAYMENT",
            user_id=user_id,
            user_roles=user_roles,
            legal_entity_id=legal_entity_id,
            period_id=None,
            transaction_id=operation_id,
            source=source,
            data=ctx_data,
            is_amendment=False,
        )
        return self.enforce(ctx)

    def enforce_tax_submission(
        self,
        operation_id: UUID,
        calculated_tax: Decimal,
        reported_tax: Decimal,
        tax_period: str,
        legal_entity_id: UUID,
        user_id: str,
        user_roles: list[str],
        source: str = "internal_api",
        data: dict[str, Any] | None = None,
    ) -> EnforcementReport:
        ctx_data = data or {}
        ctx_data.update(
            {
                "calculated_tax": calculated_tax,
                "reported_tax": reported_tax,
                "tax_period": tax_period,
                "amount": calculated_tax,
            }
        )
        ctx = EnforcementContext(
            operation_id=operation_id,
            operation_type="TAX_SUBMISSION",
            user_id=user_id,
            user_roles=user_roles,
            legal_entity_id=legal_entity_id,
            period_id=None,
            transaction_id=operation_id,
            source=source,
            data=ctx_data,
            is_amendment=False,
        )
        return self.enforce(ctx)

    def get_report_history(
        self,
        limit: int = 100,
        only_failed: bool = False,
        operation_type: str | None = None,
    ) -> list[EnforcementReport]:
        with self._history_lock:
            reports = self._report_history[-limit:]
            if only_failed:
                reports = [r for r in reports if r.final_result != EnforcementResult.PASS]
            if operation_type:
                reports = [r for r in reports if r.operation_type == operation_type]
            return reports

    def get_statistics(self) -> dict[str, Any]:
        with self._history_lock:
            total = len(self._report_history)
            if total == 0:
                return {"total": 0}
            passed = len(
                [r for r in self._report_history if r.final_result == EnforcementResult.PASS]
            )
            rejected = len(
                [r for r in self._report_history if r.final_result == EnforcementResult.REJECTED]
            )
            require_approval = len(
                [
                    r
                    for r in self._report_history
                    if r.final_result == EnforcementResult.REQUIRE_APPROVAL
                ]
            )
            catastrophic = len(
                [
                    r
                    for r in self._report_history
                    if r.final_result == EnforcementResult.CATASTROPHIC
                ]
            )
            deferred = len(
                [r for r in self._report_history if r.final_result == EnforcementResult.DEFERRED]
            )
            avg_exec_time = sum(r.execution_time_ms for r in self._report_history) / total
            by_operation: dict[str, int] = {}
            for r in self._report_history:
                by_operation[r.operation_type] = by_operation.get(r.operation_type, 0) + 1
            return {
                "total_enforcements": total,
                "passed": passed,
                "rejected": rejected,
                "require_approval": require_approval,
                "catastrophic": catastrophic,
                "deferred": deferred,
                "pass_rate": passed / total if total > 0 else 0,
                "avg_execution_time_ms": avg_exec_time,
                "by_operation_type": by_operation,
                "most_recent": self._report_history[-1].timestamp.isoformat()
                if self._report_history
                else None,
            }

    def emergency_bypass(
        self,
        operation_id: UUID,
        operation_type: str,
        data: dict[str, Any],
        user_id: str,
        authorized_by: list[str],
        reason: str,
    ) -> EnforcementReport:
        if len(authorized_by) < 2:
            raise ValueError("Emergency bypass requires at least 2 authorizers")
        guardian = get_sovereignty_guardian()
        if guardian.get_current_status() != SovereigntyStatus.EMERGENCY_LOCKDOWN:
            raise ValueError("Emergency bypass only allowed during EMERGENCY_LOCKDOWN")
        ctx = EnforcementContext(
            operation_id=operation_id,
            operation_type=operation_type,
            user_id=user_id,
            user_roles=["EMERGENCY_ADMIN"],
            legal_entity_id=None,
            period_id=None,
            transaction_id=operation_id,
            source="emergency_bypass",
            data=data,
            is_amendment=True,
            mode=EnforcementMode.EMERGENCY,
        )
        report = self._pipeline.execute(ctx)
        report = EnforcementReport(
            report_id=report.report_id,
            operation_id=report.operation_id,
            operation_type=report.operation_type,
            timestamp=report.timestamp,
            stages_passed=[*report.stages_passed, EnforcementStage.FINAL_APPROVAL],
            stages_failed=[],
            final_result=EnforcementResult.PASS,
            rejection_reason=None,
            required_approvers=authorized_by,
            execution_time_ms=report.execution_time_ms,
            constitutional_hash=report.compute_hash(),
            mode=EnforcementMode.EMERGENCY,
            warning_count=report.warning_count + 1,
            warnings=[*report.warnings, f"EMERGENCY BYPASS by {authorized_by}: {reason}"],
        )
        with self._history_lock:
            self._report_history.append(report)
        logger.warning(
            f"EMERGENCY BYPASS executed for {operation_type} ({operation_id}) by {authorized_by}. Reason: {reason}"
        )
        return report


# === 6. SINGLETON ACCESSORS ===

_enforcement_engine_instance: EnforcementEngine | None = None


def get_enforcement_engine() -> EnforcementEngine:
    global _enforcement_engine_instance
    if _enforcement_engine_instance is None:
        _enforcement_engine_instance = EnforcementEngine()
    return _enforcement_engine_instance


__all__ = [
    "EnforcementCatastrophicError",
    "EnforcementContext",
    "EnforcementEngine",
    "EnforcementError",
    "EnforcementMode",
    "EnforcementPipeline",
    "EnforcementRejectedError",
    "EnforcementReport",
    "EnforcementResult",
    "EnforcementStage",
    "get_enforcement_engine",
]
