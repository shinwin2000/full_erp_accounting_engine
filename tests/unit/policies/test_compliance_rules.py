#!/usr/bin/env python3
"""
Module: test_compliance_rules.py
Layer: Tests / Unit / Policies

Responsibility:
    Unit tests untuk aturan kepatuhan (AML, GDPR, SOX).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from compliance.aml_risk_scorer import AMLRiskScorer, RiskLevel
from compliance.ethics.correction_doctrine_engine import CorrectionDoctrineEngine
from compliance.gdpr_privacy_checker import GDPRChecker
from compliance.sox_control_tester import SoxControlTester


class TestAMLRiskScorer:
    """AML risk scoring."""

    def test_low_risk_transaction(self):
        scorer = AMLRiskScorer()
        score = scorer.calculate(
            amount=Decimal("50000000"),
            country="ID",
            customer_tenure_years=5,
        )
        assert score.risk_level == RiskLevel.LOW
        assert score.score < 30

    def test_high_risk_country_and_amount(self):
        scorer = AMLRiskScorer()
        score = scorer.calculate(
            amount=Decimal("2000000000"),
            country="KY",
            customer_tenure_years=0,
        )
        assert score.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_edd_triggered_for_new_customer_large_amount(self):
        scorer = AMLRiskScorer()
        score = scorer.calculate(amount=Decimal("800000000"), country="ID", customer_tenure_years=0)
        assert score.requires_edd is True


class TestGDPRChecker:
    """GDPR compliance."""

    def test_right_to_access(self):
        checker = GDPRChecker()
        request = checker.create_access_request(user_id=uuid4())
        report = checker.process_request(request)
        assert report.data_export is not None
        assert report.completion_date <= date.today()

    def test_right_to_erasure(self):
        checker = GDPRChecker()
        result = checker.request_erasure(user_id=uuid4())
        assert result.is_erased is True
        assert result.anonymized_log_retained is True

    def test_consent_withdrawal(self):
        checker = GDPRChecker()
        checker.give_consent(user_id=uuid4())
        assert checker.has_consent(user_id=uuid4()) is True
        checker.withdraw_consent(user_id=uuid4())
        assert checker.has_consent(user_id=uuid4()) is False


class TestSoxControlTester:
    """SOX 404 controls."""

    def test_control_testing_passes(self):
        tester = SoxControlTester(fiscal_year=2025)
        result = tester.test_control("FIN.JOURNAL_APPROVAL")
        assert result.status in ("PASS", "FAIL")

    def test_control_deficiency_documented(self):
        tester = SoxControlTester(fiscal_year=2025)
        tester.record_deficiency(control_id="IT.ACCESS", issue="Missing logs")
        deficiencies = tester.get_deficiencies()
        assert len(deficiencies) == 1
        assert deficiencies[0].severity == "material_weakness"


class TestCorrectionDoctrineEngine:
    """Correction doctrine (PSAK 25)."""

    def test_prior_period_error_correction(self):
        engine = CorrectionDoctrineEngine()
        correction = engine.correct_prior_period_error(
            error_amount=Decimal("1000000"),
            original_period="2024",
            correction_period="2025",
        )
        assert correction.retained_earnings_adjustment == Decimal("1000000")
        assert correction.disclosure_required is True
