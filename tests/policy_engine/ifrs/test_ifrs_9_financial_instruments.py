# test_ifrs_9_financial_instruments.py
# Comprehensive tests for IFRS 9 Financial Instruments implementation

from datetime import date, timedelta
from decimal import Decimal

from policy_engine.ifrs.ifrs_9_financial_instruments import (
    IFRS9,
    BusinessModel,
    CashFlow,
    ECLStage,
    ExpectedCreditLoss,
    FinancialAssetCategory,
    FinancialInstrument,
    FinancialLiabilityCategory,
    HedgeEffectivenessStatus,
    HedgeRelationship,
    HedgeType,
    IFRS9Portfolio,
    SPPITestResult,
    get_ifrs9_validator,
)


# -------------------- Enum Tests --------------------
class TestFinancialAssetCategory:
    def test_members(self):
        assert FinancialAssetCategory.AMORTIZED_COST.value == "amortized_cost"
        assert FinancialAssetCategory.FVOCI.value == "fvoci"
        assert FinancialAssetCategory.FVPL.value == "fvpl"


class TestFinancialLiabilityCategory:
    def test_members(self):
        assert FinancialLiabilityCategory.AMORTIZED_COST.value == "amortized_cost"
        assert FinancialLiabilityCategory.FVPL.value == "fvpl"


class TestBusinessModel:
    def test_members(self):
        assert BusinessModel.HOLD_TO_COLLECT.value == "hold_to_collect"
        assert BusinessModel.HOLD_TO_COLLECT_AND_SELL.value == "hold_to_collect_and_sell"
        assert BusinessModel.OTHER.value == "other"


class TestSPPITestResult:
    def test_members(self):
        assert SPPITestResult.PASS.value == "pass"
        assert SPPITestResult.FAIL.value == "fail"


class TestECLStage:
    def test_members(self):
        assert ECLStage.STAGE_1.value == 1
        assert ECLStage.STAGE_2.value == 2
        assert ECLStage.STAGE_3.value == 3


class TestHedgeType:
    def test_members(self):
        assert HedgeType.FAIR_VALUE_HEDGE.value == "fair_value_hedge"
        assert HedgeType.CASH_FLOW_HEDGE.value == "cash_flow_hedge"
        assert HedgeType.NET_INVESTMENT_HEDGE.value == "net_investment_hedge"


class TestHedgeEffectivenessStatus:
    def test_members(self):
        assert HedgeEffectivenessStatus.EFFECTIVE.value == "effective"
        assert HedgeEffectivenessStatus.INEFFECTIVE.value == "ineffective"
        assert HedgeEffectivenessStatus.PARTIALLY_EFFECTIVE.value == "partially_effective"


# -------------------- Data Class Tests --------------------
class TestCashFlow:
    def test_construction(self):
        cf = CashFlow(amount=Decimal("100.50"), date=date(2025, 1, 1))
        assert cf.amount == Decimal("100.50")
        assert cf.date == date(2025, 1, 1)


class TestExpectedCreditLoss:
    def test_construction(self):
        ecl = ExpectedCreditLoss(
            stage=ECLStage.STAGE_1,
            amount=Decimal("5000"),
            probability_default=Decimal("0.02"),
            loss_given_default=Decimal("0.5"),
            exposure_at_default=Decimal("100000"),
        )
        assert ecl.stage == ECLStage.STAGE_1
        assert ecl.amount == Decimal("5000")


class TestHedgeRelationship:
    def test_construction(self):
        hr = HedgeRelationship(
            hedge_id="H1",
            hedge_type=HedgeType.FAIR_VALUE_HEDGE,
            hedged_item_id="item1",
            hedging_instrument_id="inst1",
            designation_date=date.today(),
            effectiveness_ratio=Decimal("1.0"),
            status=HedgeEffectivenessStatus.EFFECTIVE,
            ineffectiveness_recognized=Decimal("0"),
        )
        assert hr.hedge_id == "H1"


# -------------------- IFRS9 Tests --------------------
class TestIFRS9Classification:
    def test_classify_financial_asset_amortized_cost(self):
        # Hold to collect + SPPI pass => amortized cost
        result = IFRS9.classify_financial_asset(
            business_model=BusinessModel.HOLD_TO_COLLECT,
            sppi_test_result=SPPITestResult.PASS,
            fair_value_option_elected=False,
        )
        assert result == FinancialAssetCategory.AMORTIZED_COST

    def test_classify_financial_asset_fvoci(self):
        # Hold to collect and sell + SPPI pass => FVOCI
        result = IFRS9.classify_financial_asset(
            business_model=BusinessModel.HOLD_TO_COLLECT_AND_SELL,
            sppi_test_result=SPPITestResult.PASS,
        )
        assert result == FinancialAssetCategory.FVOCI

    def test_classify_financial_asset_fvpl_sppi_fail(self):
        # Hold to collect + SPPI fail => FVPL
        result = IFRS9.classify_financial_asset(
            business_model=BusinessModel.HOLD_TO_COLLECT,
            sppi_test_result=SPPITestResult.FAIL,
        )
        assert result == FinancialAssetCategory.FVPL

    def test_classify_financial_asset_fvpl_other_business_model(self):
        # Other business model => FVPL
        result = IFRS9.classify_financial_asset(
            business_model=BusinessModel.OTHER,
            sppi_test_result=SPPITestResult.PASS,
        )
        assert result == FinancialAssetCategory.FVPL

    def test_classify_financial_asset_fvpl_fair_value_option(self):
        # Fair value option elected => FVPL regardless
        result = IFRS9.classify_financial_asset(
            business_model=BusinessModel.HOLD_TO_COLLECT,
            sppi_test_result=SPPITestResult.PASS,
            fair_value_option_elected=True,
        )
        assert result == FinancialAssetCategory.FVPL

    def test_classify_financial_liability_amortized_cost(self):
        result = IFRS9.classify_financial_liability(
            is_held_for_trading=False, fair_value_option_elected=False
        )
        assert result == FinancialLiabilityCategory.AMORTIZED_COST

    def test_classify_financial_liability_fvpl_trading(self):
        result = IFRS9.classify_financial_liability(
            is_held_for_trading=True, fair_value_option_elected=False
        )
        assert result == FinancialLiabilityCategory.FVPL

    def test_classify_financial_liability_fvpl_option(self):
        result = IFRS9.classify_financial_liability(
            is_held_for_trading=False, fair_value_option_elected=True
        )
        assert result == FinancialLiabilityCategory.FVPL


class TestIFRS9SPPI:
    def test_sppi_pass_fixed_rate(self):
        # Cash flows exactly match principal + interest
        start = date(2025, 1, 1)
        flows = [
            CashFlow(amount=Decimal("50000"), date=start + timedelta(days=365)),
            CashFlow(amount=Decimal("50000"), date=start + timedelta(days=730)),
            CashFlow(amount=Decimal("1050000"), date=start + timedelta(days=1095)),
        ]
        result = IFRS9.perform_sppi_test(
            contractual_cash_flows=flows,
            principal=Decimal("1000000"),
            interest_rate=Decimal("0.05"),
            is_variable_rate=False,
        )
        assert result == SPPITestResult.PASS

    def test_sppi_fail_fixed_rate(self):
        # Cash flow too high
        start = date(2025, 1, 1)
        flows = [
            CashFlow(amount=Decimal("60000"), date=start + timedelta(days=365)),  # too much
        ]
        result = IFRS9.perform_sppi_test(
            contractual_cash_flows=flows,
            principal=Decimal("1000000"),
            interest_rate=Decimal("0.05"),
            is_variable_rate=False,
        )
        assert result == SPPITestResult.FAIL

    def test_sppi_pass_variable_rate(self):
        # Variable rate automatically passes in this implementation
        result = IFRS9.perform_sppi_test(
            contractual_cash_flows=[],
            principal=Decimal("1000"),
            interest_rate=Decimal("0.1"),
            is_variable_rate=True,
        )
        assert result == SPPITestResult.PASS


class TestIFRS9Measurement:
    def test_amortized_cost_effective_interest_rate(self):
        # Simple bond: 5% coupon, 3 years, face 1,000,000, price 1,000,000
        flows = [
            CashFlow(amount=Decimal("50000"), date=date(2025, 12, 31)),
            CashFlow(amount=Decimal("50000"), date=date(2026, 12, 31)),
            CashFlow(amount=Decimal("1050000"), date=date(2027, 12, 31)),
        ]
        eir = IFRS9.amortized_cost_effective_interest_rate(
            initial_carrying_amount=Decimal("1000000"),
            cash_flows=flows,
            face_value=Decimal("1000000"),
        )
        # EIR should be around 0.05
        assert Decimal("0.049") < eir < Decimal("0.051")

    def test_amortized_cost_amortization_schedule(self):
        flows = [
            CashFlow(amount=Decimal("50000"), date=date(2025, 12, 31)),
            CashFlow(amount=Decimal("50000"), date=date(2026, 12, 31)),
            CashFlow(amount=Decimal("1050000"), date=date(2027, 12, 31)),
        ]
        eir = IFRS9.amortized_cost_effective_interest_rate(
            Decimal("1000000"), flows, Decimal("1000000")
        )
        schedule = IFRS9.amortized_cost_amortization_schedule(
            Decimal("1000000"), eir, flows
        )
        assert len(schedule) == 3
        # Check first entry
        first = schedule[0]
        assert first["date"] == date(2025, 12, 31)
        assert first["cash_received"] == Decimal("50000")
        # Interest should be about 5% of 1,000,000 = 50,000
        assert abs(first["interest_income"] - Decimal("50000")) < Decimal("1")
        # Carrying amount after should decrease
        assert first["carrying_amount_after"] < first["carrying_amount_before"]

    def test_fair_value_measurement_level1(self):
        fv = IFRS9.fair_value_measurement(quoted_price=Decimal("150.25"))
        assert fv == Decimal("150.25")

    def test_fair_value_measurement_level3_dcf(self):
        fv = IFRS9.fair_value_measurement(
            valuation_technique="discounted_cash_flow",
            inputs={
                "discount_rate": Decimal("0.1"),
                "future_cash_flows": Decimal("1100"),
            },
        )
        # 1100 / 1.1 = 1000
        assert fv == Decimal("1000")

    def test_fair_value_measurement_no_input(self):
        fv = IFRS9.fair_value_measurement()
        assert fv == Decimal("0")


class TestIFRS9Impairment:
    def test_determine_ecl_stage_stage1(self):
        stage = IFRS9.determine_ecl_stage(
            days_past_due=0,
            significant_increase_in_credit_risk=False,
            credit_impaired=False,
        )
        assert stage == ECLStage.STAGE_1

    def test_determine_ecl_stage_stage2_significant_increase(self):
        stage = IFRS9.determine_ecl_stage(
            days_past_due=30,
            significant_increase_in_credit_risk=True,
            credit_impaired=False,
        )
        assert stage == ECLStage.STAGE_2

    def test_determine_ecl_stage_stage2_lifetime_trigger(self):
        stage = IFRS9.determine_ecl_stage(
            days_past_due=0,
            significant_increase_in_credit_risk=False,
            credit_impaired=False,
            lifetime_expected_loss_trigger=True,
        )
        assert stage == ECLStage.STAGE_2

    def test_determine_ecl_stage_stage3_credit_impaired(self):
        stage = IFRS9.determine_ecl_stage(
            days_past_due=90,
            significant_increase_in_credit_risk=True,
            credit_impaired=True,
        )
        assert stage == ECLStage.STAGE_3

    def test_calculate_12_month_ecl(self):
        ecl = IFRS9.calculate_12_month_ecl(
            exposure_at_default=Decimal("1000000"),
            probability_default_12m=Decimal("0.02"),
            loss_given_default=Decimal("0.5"),
        )
        assert ecl == Decimal("10000.00")  # 1,000,000 * 0.02 * 0.5 = 10,000

    def test_calculate_lifetime_ecl(self):
        ecl = IFRS9.calculate_lifetime_ecl(
            exposure_at_default=Decimal("1000000"),
            probability_default_lifetime=Decimal("0.05"),
            loss_given_default=Decimal("0.5"),
        )
        assert ecl == Decimal("25000.00")

    def test_calculate_ecl_for_portfolio_stage1(self):
        exposures = [
            {"ead": Decimal("100000"), "pd_12m": Decimal("0.01"), "lgd": Decimal("0.4")},
            {"ead": Decimal("200000"), "pd_12m": Decimal("0.02"), "lgd": Decimal("0.5")},
        ]
        total = IFRS9.calculate_ecl_for_portfolio(exposures, use_lifetime=False)
        expected = (100000 * 0.01 * 0.4) + (200000 * 0.02 * 0.5)  # 400 + 2000 = 2400
        assert total == Decimal("2400.00")

    def test_calculate_ecl_for_portfolio_lifetime(self):
        exposures = [
            {"ead": Decimal("100000"), "pd_lifetime": Decimal("0.03"), "lgd": Decimal("0.4")},
            {"ead": Decimal("200000"), "pd_lifetime": Decimal("0.04"), "lgd": Decimal("0.5")},
        ]
        total = IFRS9.calculate_ecl_for_portfolio(exposures, use_lifetime=True)
        expected = (100000 * 0.03 * 0.4) + (200000 * 0.04 * 0.5)  # 1200 + 4000 = 5200
        assert total == Decimal("5200.00")


class TestIFRS9HedgeAccounting:
    def test_hedge_effectiveness_test_effective(self):
        status, ratio = IFRS9.hedge_effectiveness_test(
            change_in_hedged_item=Decimal("1000"),
            change_in_hedging_instrument=Decimal("950"),
        )
        assert status == HedgeEffectivenessStatus.EFFECTIVE
        assert ratio == Decimal("1000") / Decimal("950")  # ~1.0526

    def test_hedge_effectiveness_test_partially_effective(self):
        # ratio outside 80%-125%
        status, ratio = IFRS9.hedge_effectiveness_test(
            change_in_hedged_item=Decimal("1000"),
            change_in_hedging_instrument=Decimal("500"),
        )
        assert status == HedgeEffectivenessStatus.PARTIALLY_EFFECTIVE
        assert ratio == Decimal("2.0")

    def test_hedge_effectiveness_test_ineffective_zero_instrument(self):
        status, ratio = IFRS9.hedge_effectiveness_test(
            change_in_hedged_item=Decimal("1000"),
            change_in_hedging_instrument=Decimal("0"),
        )
        assert status == HedgeEffectivenessStatus.INEFFECTIVE
        assert ratio == Decimal("0")

    def test_fair_value_hedge_accounting(self):
        # Existing hedge relationship
        hr = HedgeRelationship(
            hedge_id="H1",
            hedge_type=HedgeType.FAIR_VALUE_HEDGE,
            hedged_item_id="item1",
            hedging_instrument_id="inst1",
            designation_date=date.today(),
            effectiveness_ratio=Decimal("1.0"),
            status=HedgeEffectivenessStatus.EFFECTIVE,
            ineffectiveness_recognized=Decimal("0"),
        )
        result = IFRS9.fair_value_hedge_accounting(
            hedged_item_fair_value_change=Decimal("1000"),
            hedging_instrument_fair_value_change=Decimal("950"),
            existing_hedge_relationship=hr,
        )
        assert result["gain_loss_hedged_item_pnl"] == Decimal("1000")
        assert result["gain_loss_hedging_instrument_pnl"] == Decimal("950")
        assert result["ineffectiveness_pnl"] == Decimal("50")  # 1000 - 950

    def test_cash_flow_hedge_accounting_effective(self):
        hr = HedgeRelationship(
            hedge_id="H1",
            hedge_type=HedgeType.CASH_FLOW_HEDGE,
            hedged_item_id="item1",
            hedging_instrument_id="inst1",
            designation_date=date.today(),
            effectiveness_ratio=Decimal("1.0"),
            status=HedgeEffectivenessStatus.EFFECTIVE,
            ineffectiveness_recognized=Decimal("0"),
        )
        result = IFRS9.cash_flow_hedge_accounting(
            hedging_instrument_fair_value_change=Decimal("1000"),
            expected_transaction_highly_probable=True,
            existing_hedge_relationship=hr,
        )
        assert result["effective_portion_oci"] == Decimal("1000")
        assert result["ineffectiveness_pnl"] == Decimal("0")

    def test_cash_flow_hedge_accounting_ineffective(self):
        hr = HedgeRelationship(
            hedge_id="H1",
            hedge_type=HedgeType.CASH_FLOW_HEDGE,
            hedged_item_id="item1",
            hedging_instrument_id="inst1",
            designation_date=date.today(),
            effectiveness_ratio=Decimal("0.9"),
            status=HedgeEffectivenessStatus.PARTIALLY_EFFECTIVE,
            ineffectiveness_recognized=Decimal("50"),
        )
        result = IFRS9.cash_flow_hedge_accounting(
            hedging_instrument_fair_value_change=Decimal("1000"),
            expected_transaction_highly_probable=True,
            existing_hedge_relationship=hr,
        )
        # effective portion = change - ineffectiveness_recognized
        assert result["effective_portion_oci"] == Decimal("950")
        assert result["ineffectiveness_pnl"] == Decimal("50")

    def test_cash_flow_hedge_accounting_not_probable(self):
        hr = HedgeRelationship(
            hedge_id="H1",
            hedge_type=HedgeType.CASH_FLOW_HEDGE,
            hedged_item_id="item1",
            hedging_instrument_id="inst1",
            designation_date=date.today(),
            effectiveness_ratio=Decimal("1.0"),
            status=HedgeEffectivenessStatus.EFFECTIVE,
            ineffectiveness_recognized=Decimal("0"),
        )
        result = IFRS9.cash_flow_hedge_accounting(
            hedging_instrument_fair_value_change=Decimal("1000"),
            expected_transaction_highly_probable=False,
            existing_hedge_relationship=hr,
        )
        assert result["gain_loss_pnl"] == Decimal("1000")
        assert result["effective_portion_oci"] == Decimal("0")

    def test_reclassify_from_oci_to_pnl_when_affects(self):
        result = IFRS9.reclassify_from_oci_to_pnl(
            accumulated_oci_amount=Decimal("5000"),
            hedged_item_affects_pnl=True,
        )
        assert result["reclassified_to_pnl"] == Decimal("5000")
        assert result["remaining_oci"] == Decimal("0")

    def test_reclassify_from_oci_to_pnl_not_affects(self):
        result = IFRS9.reclassify_from_oci_to_pnl(
            accumulated_oci_amount=Decimal("5000"),
            hedged_item_affects_pnl=False,
        )
        assert result["reclassified_to_pnl"] == Decimal("0")
        assert result["remaining_oci"] == Decimal("5000")


class TestIFRS9Derecognition:
    def test_derecognition_contractual_rights_expired(self):
        result = IFRS9.derecognition_assessment(
            contractual_rights_expired=True,
            transfer_substantially_all_risks_rewards=False,
            transfer_control=False,
        )
        assert result["derecognize"] is True
        assert result["reason"] == "contractual_rights_expired"

    def test_derecognition_risks_rewards_transferred(self):
        result = IFRS9.derecognition_assessment(
            contractual_rights_expired=False,
            transfer_substantially_all_risks_rewards=True,
            transfer_control=False,
        )
        assert result["derecognize"] is True
        assert result["reason"] == "risks_rewards_transferred"

    def test_derecognition_control_transferred(self):
        result = IFRS9.derecognition_assessment(
            contractual_rights_expired=False,
            transfer_substantially_all_risks_rewards=False,
            transfer_control=True,
        )
        assert result["derecognize"] is True
        assert result["reason"] == "control_transferred"

    def test_derecognition_no_transfer(self):
        result = IFRS9.derecognition_assessment(
            contractual_rights_expired=False,
            transfer_substantially_all_risks_rewards=False,
            transfer_control=False,
        )
        assert result["derecognize"] is False
        assert result["reason"] == "continuing_involvement"

    def test_modification_gain_loss(self):
        gain_loss = IFRS9.modification_gain_loss(
            original_carrying_amount=Decimal("1000000"),
            new_present_value_of_cash_flows=Decimal("1020000"),
        )
        assert gain_loss == Decimal("20000.00")


class TestIFRS9CompatibilityMethods:
    def test_classify_asset_amortized_cost(self):
        result = IFRS9.classify_asset(
            business_model="hold_to_collect",
            contractual_cash_flows="solely_payments_principal_interest",
        )
        assert result == "amortized_cost"

    def test_classify_asset_fvpl_other(self):
        result = IFRS9.classify_asset(
            business_model="other",
            contractual_cash_flows="solely_payments_principal_interest",
        )
        assert result == "fvpl"

    def test_calculate_expected_credit_loss(self):
        ecl = IFRS9.calculate_expected_credit_loss(
            exposure=Decimal("1000000"),
            probability_default=Decimal("0.02"),
            loss_given_default=Decimal("0.5"),
        )
        assert ecl == Decimal("10000.00")

    def test_is_hedge_effective_true(self):
        result = IFRS9.is_hedge_effective(
            change_in_hedged_item=Decimal("1000"),
            change_in_hedge_instrument=Decimal("950"),
        )
        assert result is True

    def test_is_hedge_effective_false(self):
        result = IFRS9.is_hedge_effective(
            change_in_hedged_item=Decimal("1000"),
            change_in_hedge_instrument=Decimal("500"),
        )
        assert result is False


# -------------------- FinancialInstrument Tests --------------------
class TestFinancialInstrument:
    def test_construction(self):
        inst = FinancialInstrument(
            instrument_id="FI1",
            principal=Decimal("100000"),
            interest_rate=Decimal("0.06"),
            maturity_date=date(2026, 12, 31),
            business_model=BusinessModel.HOLD_TO_COLLECT,
            fair_value=Decimal("105000"),
            stage=ECLStage.STAGE_1,
        )
        assert inst.id == "FI1"
        assert inst.principal == Decimal("100000")
        assert inst.interest_rate == Decimal("0.06")
        assert inst.maturity_date == date(2026, 12, 31)
        assert inst.business_model == BusinessModel.HOLD_TO_COLLECT
        assert inst.fair_value == Decimal("105000")
        assert inst.stage == ECLStage.STAGE_1
        assert inst.amortized_cost == Decimal("100000")
        assert inst.ecl_allowance == Decimal("0")
        assert inst.interest_income_ytd == Decimal("0")

    def test_update_amortized_cost(self):
        inst = FinancialInstrument(
            instrument_id="FI1",
            principal=Decimal("100000"),
            interest_rate=Decimal("0.06"),
            maturity_date=date(2026, 12, 31),
            business_model=BusinessModel.HOLD_TO_COLLECT,
        )
        # Simulate payment after 6 months
        payment_date = date(2025, 7, 1)
        # Days from Jan 1 to July 1 = 181 (approx)
        inst.update_amortized_cost(payment=Decimal("3000"), date_of_payment=payment_date)
        # Interest accrued = 100000 * 0.06 * 181/365 ≈ 2975.34
        expected_interest = Decimal("100000") * Decimal("0.06") * Decimal("181") / Decimal("365")
        expected_interest = expected_interest.quantize(Decimal("0.01"))
        assert inst.interest_income_ytd == expected_interest
        # Carrying amount becomes 100000 + interest - payment (3000)
        expected_carrying = Decimal("100000") + expected_interest - Decimal("3000")
        assert inst.amortized_cost == expected_carrying

    def test_calculate_ecl_stage1(self):
        inst = FinancialInstrument(
            instrument_id="FI1",
            principal=Decimal("100000"),
            interest_rate=Decimal("0.06"),
            maturity_date=date(2026, 12, 31),
            business_model=BusinessModel.HOLD_TO_COLLECT,
            stage=ECLStage.STAGE_1,
        )
        ecl = inst.calculate_ecl(
            pd_12m=Decimal("0.02"),
            pd_lifetime=Decimal("0.05"),
            lgd=Decimal("0.5"),
            ead=Decimal("100000"),
        )
        assert ecl == Decimal("1000.00")  # 100000 * 0.02 * 0.5

    def test_calculate_ecl_stage2(self):
        inst = FinancialInstrument(
            instrument_id="FI1",
            principal=Decimal("100000"),
            interest_rate=Decimal("0.06"),
            maturity_date=date(2026, 12, 31),
            business_model=BusinessModel.HOLD_TO_COLLECT,
            stage=ECLStage.STAGE_2,
        )
        ecl = inst.calculate_ecl(
            pd_12m=Decimal("0.02"),
            pd_lifetime=Decimal("0.05"),
            lgd=Decimal("0.5"),
            ead=Decimal("100000"),
        )
        assert ecl == Decimal("2500.00")  # 100000 * 0.05 * 0.5


# -------------------- IFRS9Portfolio Tests --------------------
class TestIFRS9Portfolio:
    def test_add_and_collective_ecl(self):
        portfolio = IFRS9Portfolio()
        inst1 = FinancialInstrument(
            instrument_id="I1",
            principal=Decimal("100000"),
            interest_rate=Decimal("0.05"),
            maturity_date=date(2026, 1, 1),
            business_model=BusinessModel.HOLD_TO_COLLECT,
            stage=ECLStage.STAGE_1,
        )
        inst2 = FinancialInstrument(
            instrument_id="I2",
            principal=Decimal("200000"),
            interest_rate=Decimal("0.05"),
            maturity_date=date(2026, 1, 1),
            business_model=BusinessModel.HOLD_TO_COLLECT,
            stage=ECLStage.STAGE_2,
        )
        portfolio.add_instrument(inst1)
        portfolio.add_instrument(inst2)

        total_ecl = portfolio.calculate_collective_ecl(
            probability_default_12m=Decimal("0.01"),
            probability_default_lifetime=Decimal("0.03"),
            loss_given_default=Decimal("0.4"),
        )
        # Expected: inst1 (stage1) => 100000 * 0.01 * 0.4 = 400
        # inst2 (stage2) => 200000 * 0.03 * 0.4 = 2400
        # total = 2800
        assert total_ecl == Decimal("2800.00")
        assert inst1.ecl_allowance == Decimal("400.00")
        assert inst2.ecl_allowance == Decimal("2400.00")


# -------------------- Singleton getter --------------------
def test_get_ifrs9_validator():
    validator1 = get_ifrs9_validator()
    validator2 = get_ifrs9_validator()
    assert validator1 is validator2
    assert isinstance(validator1, IFRS9)
