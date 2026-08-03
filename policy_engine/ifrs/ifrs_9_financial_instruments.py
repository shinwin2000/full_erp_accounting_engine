#!/usr/bin/env python3
"""
Module: ifrs_09_financial_instruments.py
Layer: Policy Engine / IFRS

Responsibility:
    Implementasi IFRS 9: Financial Instruments.
    Mencakup klasifikasi aset keuangan (amortized cost, FVOCI, FVPL),
    pengukuran, impairment (expected credit loss - ECL 3-stage model),
    dan hedge accounting (fair value hedge, cash flow hedge).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum

# ============================================================================
# Enums and Constants
# ============================================================================


class FinancialAssetCategory(Enum):
    """Kategori aset keuangan berdasarkan IFRS 9."""

    AMORTIZED_COST = "amortized_cost"
    FVOCI = "fvoci"  # Fair Value through Other Comprehensive Income
    FVPL = "fvpl"  # Fair Value through Profit or Loss


class FinancialLiabilityCategory(Enum):
    """Kategori liabilitas keuangan."""

    AMORTIZED_COST = "amortized_cost"
    FVPL = "fvpl"


class BusinessModel(Enum):
    """Model bisnis untuk aset keuangan."""

    HOLD_TO_COLLECT = "hold_to_collect"
    HOLD_TO_COLLECT_AND_SELL = "hold_to_collect_and_sell"
    OTHER = "other"


class SPPITestResult(Enum):
    """Hasil tes SPPI (Solely Payments of Principal and Interest)."""

    PASS = "pass"
    FAIL = "fail"


class ECLStage(Enum):
    """Stage untuk expected credit loss (IFRS 9 impairment)."""

    STAGE_1 = 1  # 12-month ECL
    STAGE_2 = 2  # Lifetime ECL (not credit-impaired)
    STAGE_3 = 3  # Lifetime ECL (credit-impaired)


class HedgeType(Enum):
    """Jenis lindung nilai (hedge accounting)."""

    FAIR_VALUE_HEDGE = "fair_value_hedge"
    CASH_FLOW_HEDGE = "cash_flow_hedge"
    NET_INVESTMENT_HEDGE = "net_investment_hedge"


class HedgeEffectivenessStatus(Enum):
    """Status efektivitas hedge."""

    EFFECTIVE = "effective"
    INEFFECTIVE = "ineffective"
    PARTIALLY_EFFECTIVE = "partially_effective"


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class CashFlow:
    """Arus kas untuk perhitungan amortized cost."""

    amount: Decimal
    date: date


@dataclass
class ExpectedCreditLoss:
    """Expected Credit Loss (ECL) untuk satu stage."""

    stage: ECLStage
    amount: Decimal
    probability_default: Decimal
    loss_given_default: Decimal
    exposure_at_default: Decimal


@dataclass
class HedgeRelationship:
    """Hubungan lindung nilai."""

    hedge_id: str
    hedge_type: HedgeType
    hedged_item_id: str
    hedging_instrument_id: str
    designation_date: date
    effectiveness_ratio: Decimal
    status: HedgeEffectivenessStatus
    ineffectiveness_recognized: Decimal = Decimal("0")


# ============================================================================
# Core IFRS 9 Implementation
# ============================================================================


class IFRS9:
    """
    Implementasi IFRS 9: Financial Instruments.
    """

    # ------------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------------

    @staticmethod
    def classify_financial_asset(
        business_model: BusinessModel,
        sppi_test_result: SPPITestResult,
        fair_value_option_elected: bool = False,
    ) -> FinancialAssetCategory:
        """
        Klasifikasi aset keuangan berdasarkan IFRS 9.
        """
        if fair_value_option_elected:
            return FinancialAssetCategory.FVPL

        if business_model == BusinessModel.HOLD_TO_COLLECT:
            if sppi_test_result == SPPITestResult.PASS:
                return FinancialAssetCategory.AMORTIZED_COST
            else:
                return FinancialAssetCategory.FVPL

        elif business_model == BusinessModel.HOLD_TO_COLLECT_AND_SELL:
            if sppi_test_result == SPPITestResult.PASS:
                return FinancialAssetCategory.FVOCI
            else:
                return FinancialAssetCategory.FVPL

        else:  # OTHER
            return FinancialAssetCategory.FVPL

    @staticmethod
    def classify_financial_liability(
        is_held_for_trading: bool = False,
        fair_value_option_elected: bool = False,
    ) -> FinancialLiabilityCategory:
        """
        Klasifikasi liabilitas keuangan.
        """
        if is_held_for_trading or fair_value_option_elected:
            return FinancialLiabilityCategory.FVPL
        return FinancialLiabilityCategory.AMORTIZED_COST

    @staticmethod
    def perform_sppi_test(
        contractual_cash_flows: list[CashFlow],
        principal: Decimal,
        interest_rate: Decimal,
        is_variable_rate: bool = False,
    ) -> SPPITestResult:
        """
        Melakukan SPPI test: apakah arus kas hanya merupakan pembayaran pokok dan bunga.
        """
        # Sederhana: jika tingkat bunga variabel dan terkait dengan pasar, biasanya SPPI passed
        # Untuk implementasi lengkap, perlu analisis kontrak
        if is_variable_rate:
            # Asumsikan variabel rate market reference memenuhi SPPI
            return SPPITestResult.PASS

        # Fixed rate: cek apakah semua arus kas sesuai dengan amortisasi pokok + bunga
        remaining_principal = principal
        for cf in sorted(contractual_cash_flows, key=lambda x: x.date):
            # Hitung bunga yang diharapkan
            days_in_period = (
                cf.date
                - (
                    sorted(contractual_cash_flows, key=lambda x: x.date)[0].date
                    if contractual_cash_flows[0].date
                    else cf.date
                )
            ).days
            expected_interest = (
                remaining_principal * interest_rate * Decimal(days_in_period) / Decimal("365")
            )
            expected_interest = expected_interest.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_EVEN
            )
            if cf.amount > remaining_principal + expected_interest + Decimal("0.01"):
                return SPPITestResult.FAIL
            # Kurangi pokok
            principal_paid = min(cf.amount - expected_interest, remaining_principal)
            remaining_principal -= principal_paid
        return SPPITestResult.PASS

    # ------------------------------------------------------------------------
    # Measurement
    # ------------------------------------------------------------------------

    @staticmethod
    def amortized_cost_effective_interest_rate(
        initial_carrying_amount: Decimal,
        cash_flows: list[CashFlow],
        face_value: Decimal,
    ) -> Decimal:
        """
        Menghitung tingkat bunga efektif (EIR) untuk amortized cost.
        """

        # Internal Rate of Return (IRR) approximation
        # Sederhana: iterasi Newton atau binary search
        def npv(rate: Decimal) -> Decimal:
            npv_value = -initial_carrying_amount
            for cf in cash_flows:
                discount = (Decimal("1") + rate) ** (
                    (cf.date - cash_flows[0].date).days / Decimal("365")
                )
                npv_value += cf.amount / discount
            return npv_value

        # Binary search for rate
        low = Decimal("0")
        high = Decimal("1")  # 100%
        for _ in range(100):
            mid = (low + high) / Decimal("2")
            if npv(mid) > 0:
                low = mid
            else:
                high = mid
        return (low + high) / Decimal("2")

    @staticmethod
    def amortized_cost_amortization_schedule(
        initial_amount: Decimal,
        effective_interest_rate: Decimal,
        cash_flows: list[CashFlow],
    ) -> list[dict]:
        """
        Menghasilkan jadwal amortisasi untuk aset/liabilitas amortized cost.
        """
        schedule = []
        carrying_amount = initial_amount
        previous_date = None
        for cf in sorted(cash_flows, key=lambda x: x.date):
            if previous_date is None:
                previous_date = cf.date
                continue
            days = (cf.date - previous_date).days
            interest = carrying_amount * effective_interest_rate * Decimal(days) / Decimal("365")
            interest = interest.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
            principal_reduction = cf.amount - interest
            schedule.append(
                {
                    "date": cf.date,
                    "interest_income": interest,
                    "cash_received": cf.amount,
                    "principal_reduction": principal_reduction,
                    "carrying_amount_before": carrying_amount,
                    "carrying_amount_after": carrying_amount - principal_reduction,
                }
            )
            carrying_amount -= principal_reduction
            previous_date = cf.date
        return schedule

    @staticmethod
    def fair_value_measurement(
        quoted_price: Decimal | None = None,
        valuation_technique: str | None = None,
        inputs: dict[str, Decimal] | None = None,
    ) -> Decimal:
        """
        Pengukuran nilai wajar (Level 1, 2, 3).
        """
        if quoted_price is not None:
            return quoted_price  # Level 1
        if valuation_technique == "discounted_cash_flow" and inputs:
            # Simulasi DCF
            discount_rate = inputs.get("discount_rate", Decimal("0.1"))
            future_cash_flows = inputs.get("future_cash_flows", Decimal("0"))
            if future_cash_flows:
                return future_cash_flows / (Decimal("1") + discount_rate)
        return Decimal("0")

    # ------------------------------------------------------------------------
    # Impairment (Expected Credit Loss - ECL)
    # ------------------------------------------------------------------------

    @staticmethod
    def determine_ecl_stage(
        days_past_due: int,
        significant_increase_in_credit_risk: bool,
        credit_impaired: bool,
        lifetime_expected_loss_trigger: bool = False,
    ) -> ECLStage:
        """
        Menentukan stage ECL berdasarkan peningkatan risiko kredit.
        """
        if credit_impaired:
            return ECLStage.STAGE_3
        if significant_increase_in_credit_risk or lifetime_expected_loss_trigger:
            return ECLStage.STAGE_2
        return ECLStage.STAGE_1

    @staticmethod
    def calculate_12_month_ecl(
        exposure_at_default: Decimal,
        probability_default_12m: Decimal,
        loss_given_default: Decimal,
    ) -> Decimal:
        """
        Perhitungan 12-month ECL (Stage 1).
        ECL = EAD * PD * LGD
        """
        return (exposure_at_default * probability_default_12m * loss_given_default).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    @staticmethod
    def calculate_lifetime_ecl(
        exposure_at_default: Decimal,
        probability_default_lifetime: Decimal,
        loss_given_default: Decimal,
    ) -> Decimal:
        """
        Perhitungan lifetime ECL (Stage 2 & 3).
        """
        return (exposure_at_default * probability_default_lifetime * loss_given_default).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    @staticmethod
    def calculate_ecl_for_portfolio(
        exposures: list[dict],
        use_lifetime: bool = False,
    ) -> Decimal:
        """
        Menghitung ECL untuk portofolio (kolektif).
        """
        total_ecl = Decimal("0")
        for item in exposures:
            ead = item.get("ead", Decimal("0"))
            pd = item.get("pd_lifetime" if use_lifetime else "pd_12m", Decimal("0"))
            lgd = item.get("lgd", Decimal("0.5"))
            if use_lifetime:
                ecl = ead * pd * lgd
            else:
                ecl = ead * pd * lgd
            total_ecl += ecl
        return total_ecl.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    # ------------------------------------------------------------------------
    # Hedge Accounting
    # ------------------------------------------------------------------------

    @staticmethod
    def hedge_effectiveness_test(
        change_in_hedged_item: Decimal,
        change_in_hedging_instrument: Decimal,
        acceptable_range: tuple[Decimal, Decimal] = (Decimal("0.8"), Decimal("1.25")),
    ) -> tuple[HedgeEffectivenessStatus, Decimal]:
        """
        Uji efektivitas hedge (dollar offset method).
        Returns (status, effectiveness_ratio).
        """
        if change_in_hedging_instrument == 0:
            return HedgeEffectivenessStatus.INEFFECTIVE, Decimal("0")
        ratio = abs(change_in_hedged_item / change_in_hedging_instrument)
        if acceptable_range[0] <= ratio <= acceptable_range[1]:
            return HedgeEffectivenessStatus.EFFECTIVE, ratio
        elif ratio < acceptable_range[0] or ratio > acceptable_range[1]:
            # Ineffective sebagian
            return HedgeEffectivenessStatus.PARTIALLY_EFFECTIVE, ratio
        return HedgeEffectivenessStatus.INEFFECTIVE, ratio

    @staticmethod
    def fair_value_hedge_accounting(
        hedged_item_fair_value_change: Decimal,
        hedging_instrument_fair_value_change: Decimal,
        existing_hedge_relationship: HedgeRelationship,
    ) -> dict[str, Decimal]:
        """
        Akuntansi lindung nilai fair value hedge.
        """
        # Hitung inefektivitas
        ineffectiveness = hedged_item_fair_value_change - hedging_instrument_fair_value_change
        # Recognized in P&L
        return {
            "gain_loss_hedged_item_pnl": hedged_item_fair_value_change,
            "gain_loss_hedging_instrument_pnl": hedging_instrument_fair_value_change,
            "ineffectiveness_pnl": ineffectiveness,
        }

    @staticmethod
    def cash_flow_hedge_accounting(
        hedging_instrument_fair_value_change: Decimal,
        expected_transaction_highly_probable: bool,
        existing_hedge_relationship: HedgeRelationship,
    ) -> dict[str, Decimal]:
        """
        Akuntansi lindung nilai cash flow hedge.
        """
        if expected_transaction_highly_probable:
            # Effective portion masuk OCI
            effective_portion = (
                hedging_instrument_fair_value_change
                - existing_hedge_relationship.ineffectiveness_recognized
            )
            return {
                "effective_portion_oci": effective_portion,
                "ineffectiveness_pnl": existing_hedge_relationship.ineffectiveness_recognized,
            }
        else:
            # Seluruh perubahan masuk P&L
            return {
                "gain_loss_pnl": hedging_instrument_fair_value_change,
                "effective_portion_oci": Decimal("0"),
            }

    @staticmethod
    def reclassify_from_oci_to_pnl(
        accumulated_oci_amount: Decimal,
        hedged_item_affects_pnl: bool,
    ) -> dict[str, Decimal]:
        """
        Reklasifikasi akumulasi OCI ke P&L saat transaksi yang dilindungi terjadi.
        """
        if hedged_item_affects_pnl:
            return {
                "reclassified_to_pnl": accumulated_oci_amount,
                "remaining_oci": Decimal("0"),
            }
        return {
            "reclassified_to_pnl": Decimal("0"),
            "remaining_oci": accumulated_oci_amount,
        }

    # ------------------------------------------------------------------------
    # Derecognition
    # ------------------------------------------------------------------------

    @staticmethod
    def derecognition_assessment(
        contractual_rights_expired: bool,
        transfer_substantially_all_risks_rewards: bool,
        transfer_control: bool,
    ) -> dict[str, bool]:
        """
        Penilaian penghentian pengakuan (derecognition) aset keuangan.
        """
        if contractual_rights_expired:
            return {"derecognize": True, "reason": "contractual_rights_expired"}
        if transfer_substantially_all_risks_rewards:
            return {"derecognize": True, "reason": "risks_rewards_transferred"}
        if transfer_control:
            return {"derecognize": True, "reason": "control_transferred"}
        return {"derecognize": False, "reason": "continuing_involvement"}

    @staticmethod
    def modification_gain_loss(
        original_carrying_amount: Decimal,
        new_present_value_of_cash_flows: Decimal,
    ) -> Decimal:
        """
        Perubahan kontrak yang tidak mengakibatkan penghentian pengakuan.
        Selisih diakui di P&L.
        """
        return (new_present_value_of_cash_flows - original_carrying_amount).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    # ========================================================================
    # TEST COMPATIBILITY METHODS (added without removing original)
    # ========================================================================

    @classmethod
    def classify_asset(cls, business_model: str, contractual_cash_flows: str) -> str:
        """
        Simplified classification for test compatibility.
        business_model: "hold_to_collect" or other strings.
        contractual_cash_flows: "solely_payments_principal_interest" or other.
        Returns: "amortized_cost", "fvoci", or "fvpl".
        """
        # Convert string inputs to enum equivalents
        if business_model == "hold_to_collect":
            bm = BusinessModel.HOLD_TO_COLLECT
        else:
            bm = BusinessModel.OTHER

        if contractual_cash_flows == "solely_payments_principal_interest":
            sppi = SPPITestResult.PASS
        else:
            sppi = SPPITestResult.FAIL

        category = cls.classify_financial_asset(bm, sppi)
        return category.value

    @classmethod
    def calculate_expected_credit_loss(
        cls,
        exposure: Decimal,
        probability_default: Decimal,
        loss_given_default: Decimal,
    ) -> Decimal:
        """
        Simplified ECL calculation for test compatibility.
        ECL = exposure * PD * LGD
        """
        return cls.calculate_12_month_ecl(exposure, probability_default, loss_given_default)

    @classmethod
    def is_hedge_effective(
        cls,
        change_in_hedged_item: Decimal,
        change_in_hedge_instrument: Decimal,
    ) -> bool:
        """
        Simplified hedge effectiveness test for test compatibility.
        Returns True if ratio is between 80% and 125%.
        """
        status, _ = cls.hedge_effectiveness_test(change_in_hedged_item, change_in_hedge_instrument)
        return status == HedgeEffectivenessStatus.EFFECTIVE


# ============================================================================
# Helper Classes for Portfolio Management
# ============================================================================


class FinancialInstrument:
    """Representasi instrumen keuangan dengan atribut IFRS 9."""

    def __init__(
        self,
        instrument_id: str,
        principal: Decimal,
        interest_rate: Decimal,
        maturity_date: date,
        business_model: BusinessModel,
        fair_value: Decimal | None = None,
        stage: ECLStage = ECLStage.STAGE_1,
    ):
        self.id = instrument_id
        self.principal = principal
        self.interest_rate = interest_rate
        self.maturity_date = maturity_date
        self.business_model = business_model
        self.fair_value = fair_value or principal
        self.stage = stage
        self.amortized_cost = principal
        self.ecl_allowance = Decimal("0")
        self.interest_income_ytd = Decimal("0")

    def update_amortized_cost(self, payment: Decimal, date_of_payment: date):
        """Update amortized cost berdasarkan pembayaran."""
        # Hitung bunga akrual
        days_since_last = (date_of_payment - date_of_payment.replace(month=1, day=1)).days
        interest_accrued = (
            self.amortized_cost * self.interest_rate * Decimal(days_since_last) / Decimal("365")
        )
        interest_accrued = interest_accrued.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        self.interest_income_ytd += interest_accrued
        self.amortized_cost += interest_accrued
        principal_paid = min(payment, self.amortized_cost)
        self.amortized_cost -= principal_paid

    def calculate_ecl(
        self, pd_12m: Decimal, pd_lifetime: Decimal, lgd: Decimal, ead: Decimal
    ) -> Decimal:
        """Hitung ECL sesuai stage."""
        if self.stage == ECLStage.STAGE_1:
            return IFRS9.calculate_12_month_ecl(ead, pd_12m, lgd)
        else:
            return IFRS9.calculate_lifetime_ecl(ead, pd_lifetime, lgd)


class IFRS9Portfolio:
    """Portofolio instrumen keuangan untuk perhitungan ECL kolektif."""

    def __init__(self):
        self.instruments: list[FinancialInstrument] = []

    def add_instrument(self, instrument: FinancialInstrument):
        self.instruments.append(instrument)

    def calculate_collective_ecl(
        self,
        probability_default_12m: Decimal,
        probability_default_lifetime: Decimal,
        loss_given_default: Decimal,
    ) -> Decimal:
        """
        Hitung ECL kolektif untuk seluruh portofolio berdasarkan stage.
        """
        total_ecl = Decimal("0")
        for inst in self.instruments:
            ead = inst.amortized_cost
            if inst.stage == ECLStage.STAGE_1:
                ecl = IFRS9.calculate_12_month_ecl(ead, probability_default_12m, loss_given_default)
            else:
                ecl = IFRS9.calculate_lifetime_ecl(
                    ead, probability_default_lifetime, loss_given_default
                )
            total_ecl += ecl
            inst.ecl_allowance = ecl
        return total_ecl.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


# ============================================================================
# Contoh Penggunaan
# ============================================================================

if __name__ == "__main__":
    # Contoh klasifikasi aset
    sppi = IFRS9.perform_sppi_test(
        contractual_cash_flows=[
            CashFlow(amount=Decimal("55000"), date=date(2025, 12, 31)),
            CashFlow(amount=Decimal("55000"), date=date(2026, 12, 31)),
            CashFlow(amount=Decimal("1055000"), date=date(2027, 12, 31)),
        ],
        principal=Decimal("1000000"),
        interest_rate=Decimal("0.05"),
    )
    print(f"SPPI Test Result: {sppi.value}")

    category = IFRS9.classify_financial_asset(
        business_model=BusinessModel.HOLD_TO_COLLECT_AND_SELL,
        sppi_test_result=sppi,
    )
    print(f"Classification: {category.value}")

    # Contoh ECL
    ecl = IFRS9.calculate_12_month_ecl(
        exposure_at_default=Decimal("1000000"),
        probability_default_12m=Decimal("0.02"),
        loss_given_default=Decimal("0.5"),
    )
    print(f"12-month ECL: {ecl}")

    # Contoh hedge effectiveness
    status, ratio = IFRS9.hedge_effectiveness_test(
        change_in_hedged_item=Decimal("1000"),
        change_in_hedging_instrument=Decimal("950"),
    )
    print(f"Hedge effectiveness: {status.value}, ratio={ratio}")

    # Test compatibility methods
    print("\nTest compatibility methods:")
    classification = IFRS9.classify_asset("hold_to_collect", "solely_payments_principal_interest")
    print(f"classify_asset: {classification}")

    ecl_test = IFRS9.calculate_expected_credit_loss(
        Decimal("100000000"), Decimal("0.02"), Decimal("0.5")
    )
    print(f"calculate_expected_credit_loss: {ecl_test}")

    effective = IFRS9.is_hedge_effective(Decimal("1000"), Decimal("950"))
    print(f"is_hedge_effective: {effective}")


# Alias untuk kompatibilitas inisialisasi package
IFRS9Validator = IFRS9


# === ACCESSED BY AGGREGATOR ===
_ifrs9_validator_instance = None


def get_ifrs9_validator():
    """Mendapatkan singleton instance untuk validasi instrumen keuangan IFRS 9."""
    global _ifrs9_validator_instance
    if _ifrs9_validator_instance is None:
        _ifrs9_validator_instance = IFRS9()
    return _ifrs9_validator_instance
