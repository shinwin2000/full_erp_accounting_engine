#!/usr/bin/env python3
"""
Module: test_ifrs_14_standards.py
Layer: Compliance

Responsibility:
    Menguji kepatuhan terhadap IFRS 14 (Regulatory Deferral Accounts).
    Memastikan bahwa perusahaan yang menerapkan rate-regulated activities
    mencatat dan menyajikan regulatory deferral accounts dengan benar.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from compliance.ifrs_checker import IFRS14Checker
from policy_engine.ifrs.ifrs_14_deferral import RegulatoryDeferralAccount


@pytest.fixture
def deferral_account() -> RegulatoryDeferralAccount:
    return RegulatoryDeferralAccount(entity_id="ENT-001", regulatory_approval_date=date(2025, 1, 1))


class TestIFRS14Recognition:
    """Uji pengakuan regulatory deferral account."""

    def test_deferral_account_created_when_regulatory_approval_exists(self, deferral_account):
        assert deferral_account.is_active is True
        assert deferral_account.balance == Decimal("0")

    def test_deferral_asset_dicatat_saat_over_recovery(self, deferral_account):
        deferral_account.record_over_recovery(amount=Decimal("1000000"), period="2026-Q1")
        assert deferral_account.deferral_asset == Decimal("1000000")
        assert deferral_account.deferral_liability == Decimal("0")

    def test_deferral_liability_dicatat_saat_under_recovery(self, deferral_account):
        deferral_account.record_under_recovery(amount=Decimal("500000"), period="2026-Q1")
        assert deferral_account.deferral_liability == Decimal("500000")
        assert deferral_account.deferral_asset == Decimal("0")

    def test_amortization_of_deferral_asset(self, deferral_account):
        deferral_account.record_over_recovery(Decimal("1200000"))
        deferral_account.amortize(period="2026", method="straight_line", useful_life=12)
        assert deferral_account.balance == Decimal("100000")  # 1.200.000 / 12


class TestIFRS14Presentation:
    """Uji penyajian dalam laporan keuangan."""

    def test_deferral_disclosed_in_balance_sheet(self, deferral_account):
        deferral_account.record_over_recovery(Decimal("1000000"))
        fs = deferral_account.generate_financial_statement()
        assert "Regulatory deferral assets" in fs.balance_sheet
        assert fs.balance_sheet["Regulatory deferral assets"] == Decimal("1000000")

    def test_movement_schedule_disclosed(self, deferral_account):
        deferral_account.record_over_recovery(Decimal("1200000"))
        deferral_account.amortize(Decimal("100000"), period="2026-Q1")
        schedule = deferral_account.get_movement_schedule()
        assert "beginning_balance" in schedule
        assert "additions" in schedule
        assert "amortization" in schedule


class TestIFRS14Checker:
    """Uji kepatuhan IFRS 14 secara keseluruhan."""

    def test_checker_passes_if_all_criteria_met(self):
        checker = IFRS14Checker()
        data = {
            "has_regulatory_approval": True,
            "has_rate_regulated_activities": True,
            "deferral_balance": Decimal("500000"),
        }
        result = checker.validate(data)
        assert result.is_compliant is True

    def test_checker_fails_if_no_regulatory_approval(self):
        checker = IFRS14Checker()
        data = {"has_regulatory_approval": False}
        result = checker.validate(data)
        assert result.is_compliant is False
        assert "Regulatory approval required" in result.errors
