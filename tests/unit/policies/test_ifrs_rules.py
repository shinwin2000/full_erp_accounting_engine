#!/usr/bin/env python3
"""
Module: test_ifrs_rules.py
Layer: Tests / Unit / Policies

Responsibility:
    Unit tests untuk aturan IFRS (International Financial Reporting Standards)
    yang diadopsi oleh perusahaan (IFRS 9, 15, 16, dll).
"""

from __future__ import annotations

from decimal import Decimal

from policy_engine.ifrs.ias_36_impairment import IAS36
from policy_engine.ifrs.ias_37_provisions import IAS37
from policy_engine.ifrs.ifrs_9_financial_instruments import IFRS9
from policy_engine.ifrs.ifrs_15_revenue import IFRS15
from policy_engine.ifrs.ifrs_16_leases import IFRS16


class TestIFRS9:
    """IFRS 9: Financial Instruments."""

    def test_classification_of_financial_assets(self):
        classification = IFRS9.classify_asset(
            business_model="hold_to_collect",
            contractual_cash_flows="solely_payments_principal_interest",
        )
        assert classification == "amortized_cost"

    def test_expected_credit_loss_calculation(self):
        ecl = IFRS9.calculate_expected_credit_loss(
            exposure=Decimal("100000000"),
            probability_default=Decimal("0.02"),
            loss_given_default=Decimal("0.5"),
        )
        assert ecl == Decimal("1000000")

    def test_hedge_effectiveness_threshold(self):
        is_effective = IFRS9.is_hedge_effective(
            change_in_hedged_item=Decimal("1000"),
            change_in_hedge_instrument=Decimal("950"),
        )
        assert is_effective is True  # 95% in 80-125% range


class TestIFRS15:
    """IFRS 15: Revenue from Contracts with Customers."""

    def test_five_step_model_allocation(self):
        transaction_price = Decimal("1000000")
        standalone_prices = [Decimal("600000"), Decimal("400000")]
        allocated = IFRS15.allocate_transaction_price(transaction_price, standalone_prices)
        assert allocated[0] == Decimal("600000")
        assert allocated[1] == Decimal("400000")

    def test_revenue_recognized_over_time(self):
        criteria = IFRS15.recognize_over_time(
            asset_has_alternative_use=False,
            entity_has_enforceable_right_to_payment=True,
        )
        assert criteria is True


class TestIFRS16:
    """IFRS 16: Leases."""

    def test_lessee_right_of_use_asset(self):
        lease = IFRS16.calculate_right_of_use_asset(
            lease_payments=[Decimal("10000")] * 5,
            discount_rate=Decimal("0.05"),
            initial_direct_costs=Decimal("500"),
        )
        assert lease.asset > Decimal("0")
        assert lease.liability > Decimal("0")

    def test_lease_term_reassessment(self):
        reassessed = IFRS16.reassess_lease_term(
            original_term=5, renewal_option_reasonably_certain=True
        )
        assert reassessed > 5


class TestIAS36:
    """IAS 36: Impairment of Assets."""

    def test_recoverable_amount_higher_of_fair_value_and_value_in_use(self):
        fair_value_less_cost = Decimal("800000")
        value_in_use = Decimal("750000")
        recoverable = IAS36.get_recoverable_amount(fair_value_less_cost, value_in_use)
        assert recoverable == Decimal("800000")

    def test_impairment_loss_calculation(self):
        carrying = Decimal("1000000")
        recoverable = Decimal("750000")
        loss = IAS36.calculate_impairment_loss(carrying, recoverable)
        assert loss == Decimal("250000")


class TestIAS37:
    """IAS 37: Provisions, Contingent Liabilities and Contingent Assets."""

    def test_provision_recognition_criteria(self):
        should_recognize = IAS37.should_recognize_provision(
            present_obligation=True,
            probable_outflow=True,
            reliable_estimate=True,
        )
        assert should_recognize is True

    def test_best_estimate_of_provision(self):
        estimate = IAS37.best_estimate(
            possible_outcomes=[Decimal("1000"), Decimal("2000")],
            probabilities=[Decimal("0.7"), Decimal("0.3")],
        )
        assert estimate == Decimal("1300")
