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
    EntityIsolationViolation,
    GoingConcernViolation,
    ImmutabilityViolation,
    MonetaryUnitViolation,
    PeriodBoundViolation,
    SubstanceOverFormViolation,
    TimeIrreversibilityViolation,
    get_axiom_violation_handler,
    handle_axiom_violation,
    raise_conservation_violation,
    raise_double_entry_violation,
)
from axioms.axiom_violation import (
    MaterialityViolation as AxiomMaterialityViolation,
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
    # Accrual Basis
    "RecognitionTiming",
    "AccrualType",
    "AccrualBasisSeverity",
    "RevenueRecognitionCriteria",
    "ExpenseRecognitionCriteria",
    "AccrualEntry",
    "AccrualBasisViolation",
    "AccrualBasisValidator",
    "AccrualBasisAxiom",
    "create_revenue_criteria",
    "create_expense_criteria",
    "get_accrual_basis_axiom",
    # Axiom Violation (base)
    "AxiomType",
    "AxiomViolationSeverity",
    "AxiomViolationRecord",
    "AxiomViolationError",
    "ConservationOfValueViolation",
    "DoubleEntryViolation",
    "TimeIrreversibilityViolation",
    "ImmutabilityViolation",
    "CausalityChainViolation",
    "MonetaryUnitViolation",
    "EntityIsolationViolation",
    "PeriodBoundViolation",
    "GoingConcernViolation",
    "AxiomAccrualBasisViolation",
    "AxiomMaterialityViolation",
    "SubstanceOverFormViolation",
    "AxiomViolationHandler",
    "get_axiom_violation_handler",
    "raise_conservation_violation",
    "raise_double_entry_violation",
    "handle_axiom_violation",
    # Causality Chain
    "CausalityType",
    "CausalityStrength",
    "CausalityViolationSeverity",
    "EvidenceType",
    "CausalLink",
    "CausalityRecord",
    "CausalityViolation",
    "CausalityChainValidator",
    "CausalityChainAxiom",
    "create_causal_link_dict",
    "get_evidence_type_from_string",
    "get_causality_chain_axiom",
    # Conservation of Value
    "ValueFlowType",
    "ValueCategory",
    "ConservationViolationSeverity",
    "ConservationViolationError",
    "InvalidValueFlowError",
    "ValueNode",
    "ValueFlow",
    "ConservationRecord",
    "ConservationOfValueValidator",
    "ConservationOfValueAxiom",
    "get_conservation_axiom",
    # Double Entry
    "Side",
    "JournalType",
    "DoubleEntryViolationSeverity",
    "DoubleEntryViolationError",
    "InvalidJournalEntryError",
    "JournalLine",
    "JournalEntry",
    "DoubleEntryVerificationRecord",
    "DoubleEntryValidator",
    "DoubleEntryAxiom",
    "create_journal_line",
    "create_debit_line",
    "create_credit_line",
    "get_double_entry_axiom",
    # Entity Isolation
    "EntityIsolationViolationSeverity",
    "InterEntityAuthorizationType",
    "LegalEntityDefinition",
    "InterEntityAuthorization",
    "EntityIsolationViolation",
    "EntityIsolationValidator",
    "EntityIsolationAxiom",
    "create_legal_entity",
    "get_entity_isolation_axiom",
    # Going Concern
    "GoingConcernStatus",
    "GoingConcernIndicator",
    "GoingConcernSeverity",
    "GoingConcernAssessment",
    "GoingConcernEvent",
    "GoingConcernViolation",
    "GoingConcernValidator",
    "GoingConcernAxiom",
    "create_going_concern_indicator_from_string",
    "get_going_concern_axiom",
    # Immutability
    "ImmutabilityViolationSeverity",
    "DataState",
    "CorrectionMethod",
    "ImmutableRecord",
    "ImmutabilityViolation",
    "CorrectionRecord",
    "ImmutabilityValidator",
    "ImmutabilityAxiom",
    "create_immutable_record",
    "state_from_string",
    "get_immutability_axiom",
    # Materiality
    "MaterialityDimension",
    "MaterialityThresholdType",
    "MaterialitySeverity",
    "MaterialityThreshold",
    "MaterialityJudgment",
    "MaterialityViolation",
    "QualitativeMaterialityFactor",
    "MaterialityValidator",
    "MaterialityAxiom",
    "get_materiality_axiom",
    # Monetary Unit
    "MonetaryUnitStability",
    "CurrencyType",
    "ExchangeRateType",
    "MonetaryUnitViolationSeverity",
    "CurrencyDefinition",
    "ExchangeRate",
    "MonetaryAmount",
    "MonetaryUnitViolation",
    "CurrencyRegistry",
    "MonetaryUnitValidator",
    "MonetaryUnitAxiom",
    "get_monetary_unit_axiom",
    "create_monetary_amount",
    # Period Bound
    "PeriodStatus",
    "PeriodType",
    "PeriodBoundViolationSeverity",
    "AccountingPeriod",
    "FiscalYearDefinition",
    "PeriodBoundViolation",
    "PeriodBoundValidator",
    "PeriodBoundAxiom",
    "create_accounting_period",
    "generate_monthly_periods",
    "get_period_bound_axiom",
    # Substance Over Form
    "SubstanceOverrideType",
    "SubstanceAssessmentSeverity",
    "LegalForm",
    "EconomicSubstance",
    "SubstanceOverFormAssessment",
    "SubstanceViolation",
    "SubstanceOverFormValidator",
    "SubstanceOverFormAxiom",
    "create_legal_form",
    "create_economic_substance",
    "get_substance_over_form_axiom",
    # Time Irreversibility
    "TimeIrreversibilityViolationSeverity",
    "TransactionTimeContext",
    "TimeFlowDirection",
    "TimeBoundary",
    "TransactionTimestamp",
    "TimeIrreversibilityViolation",
    "TimeIrreversibilityValidator",
    "TimeIrreversibilityAxiom",
    "create_time_boundary",
    "create_transaction_timestamp",
    "get_time_irreversibility_axiom",
    "__version__",
]
