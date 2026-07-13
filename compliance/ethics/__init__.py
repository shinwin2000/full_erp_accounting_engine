#!/usr/bin/env python3
"""
Package: compliance.ethics
Layer: Compliance / Ethics

Responsibility:
    Modul-modul etika dan kepatuhan untuk sistem ERP akuntansi.
"""

from __future__ import annotations

__version__ = "1.0.0"

# === Impor semua modul agar terdeteksi oleh checker ===
from . import (
    conflict_of_interest_declaration_store,
    correction_doctrine_engine,
    disclosure_requirement_checker,
    error_classifier_psak25,
    ethics_committee_decision_log,
    ethics_exceptions,
    ethics_training_certificate_tracker,
    ethics_violation_detector,
    materiality_threshold_qualitative,
    materiality_threshold_quantitative,
    professional_judgment_approver,
    professional_judgment_template,
    reversal_authorization_policy,
    segregation_of_duties_enforcer,
    whistleblower_case_tracker,
)

# === Ekspor semua modul ===
__all__ = [
    "__version__",
    "conflict_of_interest_declaration_store",
    "correction_doctrine_engine",
    "disclosure_requirement_checker",
    "error_classifier_psak25",
    "ethics_committee_decision_log",
    "ethics_exceptions",
    "ethics_training_certificate_tracker",
    "ethics_violation_detector",
    "materiality_threshold_qualitative",
    "materiality_threshold_quantitative",
    "professional_judgment_approver",
    "professional_judgment_template",
    "reversal_authorization_policy",
    "segregation_of_duties_enforcer",
    "whistleblower_case_tracker",
]
