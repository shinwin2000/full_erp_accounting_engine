#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Package: compliance.ethics
Layer: Compliance / Ethics

Responsibility:
    Modul-modul etika dan kepatuhan untuk sistem ERP akuntansi.
"""

from __future__ import annotations

__version__ = "1.0.0"

# === Impor semua modul agar terdeteksi oleh checker ===
from . import conflict_of_interest_declaration_store
from . import correction_doctrine_engine
from . import disclosure_requirement_checker
from . import error_classifier_psak25
from . import ethics_committee_decision_log
from . import ethics_exceptions
from . import ethics_training_certificate_tracker
from . import ethics_violation_detector
from . import materiality_threshold_qualitative
from . import materiality_threshold_quantitative
from . import professional_judgment_approver
from . import professional_judgment_template
from . import reversal_authorization_policy
from . import segregation_of_duties_enforcer
from . import whistleblower_case_tracker

# === Ekspor semua modul ===
__all__ = [
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
    "__version__",
]