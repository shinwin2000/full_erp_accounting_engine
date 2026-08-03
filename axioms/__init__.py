#!/usr/bin/env python3
"""
Package: axioms
Layer: 2 - Foundation / Axioms

Responsibility:
    Aksioma-aksioma fundamental akuntansi yang menjadi landasan seluruh sistem.
    Package ini mengimplementasikan 12 aksioma utama:
    - conservation_of_value: Nilai tidak bisa diciptakan atau dimusnahkan
    - double_entry: Setiap transaksi harus seimbang (debit = kredit)
    - time_irreversibility: Waktu akuntansi tidak bisa mundur
    - immutability: Data yang sudah diposting tidak bisa diubah
    - causality_chain: Setiap akibat memiliki sebab tercatat
    - monetary_unit: Pencatatan dalam satuan uang yang stabil
    - entity_isolation: Data antar entitas hukum terisolasi
    - period_bound: Setiap transaksi terikat pada periode akuntansi
    - going_concern: Entitas dianggap berkelanjutan
    - accrual_basis: Pengakuan saat terjadi, bukan saat kas
    - materiality: Informasi material wajib diungkap
    - substance_over_form: Substansi mengungguli bentuk hukum

Dependencies:
    - constitution.supreme_law (ConstitutionalPrinciple, ConstitutionalSeverity)
    - Tidak ada dependensi ke layer domain atau application

Audit:
    Setiap pelanggaran aksioma dictat dalam violation history dengan
    cryptographic hash untuk integritas audit.
"""

from __future__ import annotations

# === ACCRUAL BASIS ===
from axioms.accrual_basis import (
    AccrualBasisAxiom,
    AccrualBasisSeverity,
    AccrualBasisValidator,
    AccrualBasisViolation,
    AccrualEntry,
    AccrualType,
    ExpenseRecognitionCriteria,
    RecognitionTiming,
    RevenueRecognitionCriteria,
    create_expense_criteria,
    create_revenue_criteria,
    get_accrual_basis_axiom,
)
from axioms.axiom_violation import (
    AccrualBasisViolation as AxiomAccrualBasisViolation,
)

# === AXIOM VIOLATION (BASE) ===
from axioms.axiom_violation import (
    AxiomType,
    AxiomViolationError,
    AxiomViolationHandler,
    AxiomViolationRecord,
    AxiomViolationSeverity,
    CausalityChainViolation,
    ConservationOfValueViolation,
    DoubleEntryViolation,
    SubstanceOverFormViolation,
    get_axiom_violation_handler,
    handle_axiom_violation,
    raise_conservation_violation,
    raise_double_entry_violation,
)
from axioms.axiom_violation import (
    EntityIsolationViolation as AxiomEntityIsolationViolation,
)
from axioms.axiom_violation import (
    GoingConcernViolation as AxiomGoingConcernViolation,
)
from axioms.axiom_violation import (
    ImmutabilityViolation as AxiomImmutabilityViolation,
)
from axioms.axiom_violation import (
    MaterialityViolation as AxiomMaterialityViolation,
)
from axioms.axiom_violation import (
    MonetaryUnitViolation as AxiomMonetaryUnitViolation,
)
from axioms.axiom_violation import (
    PeriodBoundViolation as AxiomPeriodBoundViolation,
)
from axioms.axiom_violation import (
    TimeIrreversibilityViolation as AxiomTimeIrreversibilityViolation,
)

# === CAUSALITY CHAIN ===
from axioms.causality_chain import (
    CausalityChainAxiom,
    CausalityChainValidator,
    CausalityRecord,
    CausalityStrength,
    CausalityType,
    CausalityViolation,
    CausalityViolationSeverity,
    CausalLink,
    EvidenceType,
    create_causal_link_dict,
    get_causality_chain_axiom,
    get_evidence_type_from_string,
)

# === CONSERVATION OF VALUE ===
from axioms.conservation_of_value import (
    ConservationOfValueAxiom,
    ConservationOfValueValidator,
    ConservationRecord,
    ConservationViolationError,
    ConservationViolationSeverity,
    InvalidValueFlowError,
    ValueCategory,
    ValueFlow,
    ValueFlowType,
    ValueNode,
    get_conservation_axiom,
)

# === DOUBLE ENTRY ===
from axioms.double_entry import (
    DoubleEntryAxiom,
    DoubleEntryValidator,
    DoubleEntryVerificationRecord,
    DoubleEntryViolationError,
    DoubleEntryViolationSeverity,
    InvalidJournalEntryError,
    JournalEntry,
    JournalLine,
    JournalType,
    Side,
    create_credit_line,
    create_debit_line,
    create_journal_line,
    get_double_entry_axiom,
)

# === ENTITY ISOLATION ===
from axioms.entity_isolation import (
    EntityIsolationAxiom,
    EntityIsolationValidator,
    EntityIsolationViolation,
    EntityIsolationViolationSeverity,
    InterEntityAuthorization,
    InterEntityAuthorizationType,
    LegalEntityDefinition,
    create_legal_entity,
    get_entity_isolation_axiom,
)

# === GOING CONCERN ===
from axioms.going_concern import (
    GoingConcernAssessment,
    GoingConcernAxiom,
    GoingConcernEvent,
    GoingConcernIndicator,
    GoingConcernSeverity,
    GoingConcernStatus,
    GoingConcernValidator,
    GoingConcernViolation,
    create_going_concern_indicator_from_string,
    get_going_concern_axiom,
)

# === IMMUTABILITY ===
from axioms.immutability import (
    CorrectionMethod,
    CorrectionRecord,
    DataState,
    ImmutabilityAxiom,
    ImmutabilityValidator,
    ImmutabilityViolation,
    ImmutabilityViolationSeverity,
    ImmutableRecord,
    create_immutable_record,
    get_immutability_axiom,
    state_from_string,
)

# === MATERIALITY ===
from axioms.materiality import (
    MaterialityAxiom,
    MaterialityDimension,
    MaterialityJudgment,
    MaterialitySeverity,
    MaterialityThreshold,
    MaterialityThresholdType,
    MaterialityValidator,
    MaterialityViolation,
    QualitativeMaterialityFactor,
    get_materiality_axiom,
)

# === MONETARY UNIT ===
from axioms.monetary_unit import (
    CurrencyDefinition,
    CurrencyRegistry,
    CurrencyType,
    ExchangeRate,
    ExchangeRateType,
    MonetaryAmount,
    MonetaryUnitAxiom,
    MonetaryUnitStability,
    MonetaryUnitValidator,
    MonetaryUnitViolation,
    MonetaryUnitViolationSeverity,
    create_monetary_amount,
    get_monetary_unit_axiom,
)

# === PERIOD BOUND ===
from axioms.period_bound import (
    AccountingPeriod,
    FiscalYearDefinition,
    PeriodBoundAxiom,
    PeriodBoundValidator,
    PeriodBoundViolation,
    PeriodBoundViolationSeverity,
    PeriodStatus,
    PeriodType,
    create_accounting_period,
    generate_monthly_periods,
    get_period_bound_axiom,
)

# === SUBSTANCE OVER FORM ===
from axioms.substance_over_form import (
    EconomicSubstance,
    LegalForm,
    SubstanceAssessmentSeverity,
    SubstanceOverFormAssessment,
    SubstanceOverFormAxiom,
    SubstanceOverFormValidator,
    SubstanceOverrideType,
    SubstanceViolation,
    create_economic_substance,
    create_legal_form,
    get_substance_over_form_axiom,
)

# === TIME IRREVERSIBILITY ===
from axioms.time_irreversibility import (
    TimeBoundary,
    TimeFlowDirection,
    TimeIrreversibilityAxiom,
    TimeIrreversibilityValidator,
    TimeIrreversibilityViolation,
    TimeIrreversibilityViolationSeverity,
    TransactionTimeContext,
    TransactionTimestamp,
    create_time_boundary,
    create_transaction_timestamp,
    get_time_irreversibility_axiom,
)

__version__ = "1.0.0"

__all__ = [
    "AccountingPeriod",
    "AccrualBasisAxiom",
    "AccrualBasisSeverity",
    "AccrualBasisValidator",
    "AccrualBasisViolation",
    "AccrualEntry",
    "AccrualType",
    "AxiomAccrualBasisViolation",
    "AxiomEntityIsolationViolation",
    "AxiomGoingConcernViolation",
    "AxiomImmutabilityViolation",
    "AxiomMaterialityViolation",
    "AxiomMonetaryUnitViolation",
    "AxiomPeriodBoundViolation",
    "AxiomTimeIrreversibilityViolation",
    "AxiomType",
    "AxiomViolationError",
    "AxiomViolationHandler",
    "AxiomViolationRecord",
    "AxiomViolationSeverity",
    "CausalLink",
    "CausalityChainAxiom",
    "CausalityChainValidator",
    "CausalityChainViolation",
    "CausalityRecord",
    "CausalityStrength",
    "CausalityType",
    "CausalityViolation",
    "CausalityViolationSeverity",
    "ConservationOfValueAxiom",
    "ConservationOfValueValidator",
    "ConservationOfValueViolation",
    "ConservationRecord",
    "ConservationViolationError",
    "ConservationViolationSeverity",
    "CorrectionMethod",
    "CorrectionRecord",
    "CurrencyDefinition",
    "CurrencyRegistry",
    "CurrencyType",
    "DataState",
    "DoubleEntryAxiom",
    "DoubleEntryValidator",
    "DoubleEntryVerificationRecord",
    "DoubleEntryViolation",
    "DoubleEntryViolationError",
    "DoubleEntryViolationSeverity",
    "EconomicSubstance",
    "EntityIsolationAxiom",
    "EntityIsolationValidator",
    "EntityIsolationViolation",
    "EntityIsolationViolationSeverity",
    "EvidenceType",
    "ExchangeRate",
    "ExchangeRateType",
    "ExpenseRecognitionCriteria",
    "FiscalYearDefinition",
    "GoingConcernAssessment",
    "GoingConcernAxiom",
    "GoingConcernEvent",
    "GoingConcernIndicator",
    "GoingConcernSeverity",
    "GoingConcernStatus",
    "GoingConcernValidator",
    "GoingConcernViolation",
    "ImmutabilityAxiom",
    "ImmutabilityValidator",
    "ImmutabilityViolation",
    "ImmutabilityViolationSeverity",
    "ImmutableRecord",
    "InterEntityAuthorization",
    "InterEntityAuthorizationType",
    "InvalidJournalEntryError",
    "InvalidValueFlowError",
    "JournalEntry",
    "JournalLine",
    "JournalType",
    "LegalEntityDefinition",
    "LegalForm",
    "MaterialityAxiom",
    "MaterialityDimension",
    "MaterialityJudgment",
    "MaterialitySeverity",
    "MaterialityThreshold",
    "MaterialityThresholdType",
    "MaterialityValidator",
    "MaterialityViolation",
    "MonetaryAmount",
    "MonetaryUnitAxiom",
    "MonetaryUnitStability",
    "MonetaryUnitValidator",
    "MonetaryUnitViolation",
    "MonetaryUnitViolationSeverity",
    "PeriodBoundAxiom",
    "PeriodBoundValidator",
    "PeriodBoundViolation",
    "PeriodBoundViolationSeverity",
    "PeriodStatus",
    "PeriodType",
    "QualitativeMaterialityFactor",
    "RecognitionTiming",
    "RevenueRecognitionCriteria",
    "Side",
    "SubstanceAssessmentSeverity",
    "SubstanceOverFormAssessment",
    "SubstanceOverFormAxiom",
    "SubstanceOverFormValidator",
    "SubstanceOverFormViolation",
    "SubstanceOverrideType",
    "SubstanceViolation",
    "TimeBoundary",
    "TimeFlowDirection",
    "TimeIrreversibilityAxiom",
    "TimeIrreversibilityValidator",
    "TimeIrreversibilityViolation",
    "TimeIrreversibilityViolationSeverity",
    "TransactionTimeContext",
    "TransactionTimestamp",
    "ValueCategory",
    "ValueFlow",
    "ValueFlowType",
    "ValueNode",
    "__version__",
    "create_accounting_period",
    "create_causal_link_dict",
    "create_credit_line",
    "create_debit_line",
    "create_economic_substance",
    "create_expense_criteria",
    "create_going_concern_indicator_from_string",
    "create_immutable_record",
    "create_journal_line",
    "create_legal_entity",
    "create_legal_form",
    "create_monetary_amount",
    "create_revenue_criteria",
    "create_time_boundary",
    "create_transaction_timestamp",
    "generate_monthly_periods",
    "get_accrual_basis_axiom",
    "get_axiom_violation_handler",
    "get_causality_chain_axiom",
    "get_conservation_axiom",
    "get_double_entry_axiom",
    "get_entity_isolation_axiom",
    "get_evidence_type_from_string",
    "get_going_concern_axiom",
    "get_immutability_axiom",
    "get_materiality_axiom",
    "get_monetary_unit_axiom",
    "get_period_bound_axiom",
    "get_substance_over_form_axiom",
    "get_time_irreversibility_axiom",
    "handle_axiom_violation",
    "raise_conservation_violation",
    "raise_double_entry_violation",
    "state_from_string",
]
