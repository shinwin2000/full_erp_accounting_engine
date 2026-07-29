# tests/policy_engine/tax_indonesia/test_pph_22_calculator.py
"""
Comprehensive tests for policy_engine/tax_indonesia/pph_22_calculator.py
Covers all enums, data classes, methods, edge cases, and exceptions.
"""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4

import pytest

from policy_engine.tax_indonesia.pph_22_calculator import (
    GovernmentPurchaserType,
    ImporterType,
    PPh22CalculationResult,
    PPh22Calculator,
    PPh22Error,
    PPh22Transaction,
    PPh22Type,
    get_pph22_calculator,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_transaction_id() -> UUID:
    return uuid4()


@pytest.fixture
def sample_import_transaction(sample_transaction_id) -> PPh22Transaction:
    return PPh22Transaction(
        transaction_id=sample_transaction_id,
        transaction_type=PPh22Type.IMPORT,
        taxable_amount=Decimal("100000000"),  # 100 jt
        transaction_date=datetime(2026, 1, 15, tzinfo=UTC),
        additional_data={
            "importer_type": ImporterType.WITH_API,
            "has_masterlist": False,
        },
    )


@pytest.fixture
def sample_government_transaction(sample_transaction_id) -> PPh22Transaction:
    return PPh22Transaction(
        transaction_id=sample_transaction_id,
        transaction_type=PPh22Type.GOVERNMENT_PURCHASE,
        taxable_amount=Decimal("5000000"),  # 5 jt
        transaction_date=datetime(2026, 1, 15, tzinfo=UTC),
        additional_data={
            "purchaser_type": GovernmentPurchaserType.GENERAL_GOVERNMENT,
            "is_pkp": False,
            "has_exemption": False,
        },
    )


@pytest.fixture
def sample_producer_transaction(sample_transaction_id) -> PPh22Transaction:
    return PPh22Transaction(
        transaction_id=sample_transaction_id,
        transaction_type=PPh22Type.PRODUCER_SALES,
        taxable_amount=Decimal("20000000"),  # 20 jt
        transaction_date=datetime(2026, 1, 15, tzinfo=UTC),
        additional_data={"product_category": "general"},
    )


@pytest.fixture
def sample_auction_transaction(sample_transaction_id) -> PPh22Transaction:
    return PPh22Transaction(
        transaction_id=sample_transaction_id,
        transaction_type=PPh22Type.AUCTION,
        taxable_amount=Decimal("150000000"),  # 150 jt
        transaction_date=datetime(2026, 1, 15, tzinfo=UTC),
        additional_data={},
    )


@pytest.fixture
def calculator() -> PPh22Calculator:
    return PPh22Calculator()


# ============================================================================
# Enum Tests
# ============================================================================

class TestPPh22Type:
    def test_members(self):
        assert PPh22Type.IMPORT.value == "import"
        assert PPh22Type.GOVERNMENT_PURCHASE.value == "government_purchase"
        assert PPh22Type.PRODUCER_SALES.value == "producer_sales"
        assert PPh22Type.AUCTION.value == "auction"
        assert PPh22Type.LUXURY_GOODS.value == "luxury_goods"
        assert PPh22Type.OTHER.value == "other"


class TestImporterType:
    def test_members(self):
        assert ImporterType.WITH_API.value == "with_api"
        assert ImporterType.WITHOUT_API.value == "without_api"
        assert ImporterType.DIRECT.value == "direct"


class TestGovernmentPurchaserType:
    def test_members(self):
        assert GovernmentPurchaserType.GENERAL_GOVERNMENT.value == "general"
        assert GovernmentPurchaserType.BUMN.value == "bumn"
        assert GovernmentPurchaserType.OTHER_PURCHASER.value == "other"


# ============================================================================
# Exception Tests
# ============================================================================

class TestPPh22Error:
    def test_construction(self):
        error = PPh22Error("test message")
        assert str(error) == "test message"
        assert isinstance(error, Exception)

    def test_raise(self):
        with pytest.raises(PPh22Error, match="test"):
            raise PPh22Error("test")


# ============================================================================
# Data Class Tests
# ============================================================================

class TestPPh22Transaction:
    def test_construction(self, sample_transaction_id):
        now = datetime(2026, 1, 15, tzinfo=UTC)
        tx = PPh22Transaction(
            transaction_id=sample_transaction_id,
            transaction_type=PPh22Type.IMPORT,
            taxable_amount=Decimal("100000000"),
            transaction_date=now,
            additional_data={"key": "value"},
        )
        assert tx.transaction_id == sample_transaction_id
        assert tx.transaction_type == PPh22Type.IMPORT
        assert tx.taxable_amount == Decimal("100000000")
        assert tx.transaction_date == now
        assert tx.additional_data == {"key": "value"}


class TestPPh22CalculationResult:
    def test_construction(self, sample_transaction_id):
        due = datetime(2026, 2, 15, tzinfo=UTC)
        result = PPh22CalculationResult(
            transaction_id=sample_transaction_id,
            transaction_type=PPh22Type.IMPORT,
            taxable_amount=Decimal("100000000"),
            tariff=Decimal("2.5"),
            tax_amount=Decimal("2500000"),
            description="Test import",
            due_date=due,
        )
        assert result.transaction_id == sample_transaction_id
        assert result.transaction_type == PPh22Type.IMPORT
        assert result.tariff == Decimal("2.5")
        assert result.tax_amount == Decimal("2500000")
        assert result.due_date == due

    def test_to_dict(self, sample_transaction_id):
        due = datetime(2026, 2, 15, tzinfo=UTC)
        result = PPh22CalculationResult(
            transaction_id=sample_transaction_id,
            transaction_type=PPh22Type.IMPORT,
            taxable_amount=Decimal("100000000"),
            tariff=Decimal("2.5"),
            tax_amount=Decimal("2500000"),
            description="Test",
            due_date=due,
        )
        d = result.to_dict()
        assert d["transaction_id"] == str(sample_transaction_id)
        assert d["transaction_type"] == "import"
        assert d["taxable_amount"] == "100000000"
        assert d["tariff"] == "2.5"
        assert d["tax_amount"] == "2500000"
        assert d["description"] == "Test"
        assert d["due_date"] == "2026-02-15T00:00:00+00:00"

    def test_to_dict_due_date_none(self, sample_transaction_id):
        result = PPh22CalculationResult(
            transaction_id=sample_transaction_id,
            transaction_type=PPh22Type.IMPORT,
            taxable_amount=Decimal("100"),
            tariff=Decimal("0"),
            tax_amount=Decimal("0"),
            description="No due",
            due_date=None,
        )
        d = result.to_dict()
        assert d["due_date"] is None


# ============================================================================
# PPh22Calculator Tests
# ============================================================================

class TestPPh22Calculator:
    # ---- calculate (simple) ----
    def test_calculate_with_api(self, calculator):
        tax = calculator.calculate(cif=Decimal("100000000"), has_api=True)
        # Tariff with API = 10% (as per simple method)
        expected = Decimal("10000000")  # 100jt * 10%
        assert tax == expected

    def test_calculate_without_api(self, calculator):
        tax = calculator.calculate(cif=Decimal("100000000"), has_api=False)
        # Tariff without API = 7.5%
        expected = Decimal("7500000")  # 100jt * 7.5%
        assert tax == expected

    def test_calculate_rounding(self, calculator):
        # 100,000,123 * 7.5% = 7,500,009.225 -> rounded to 7,500,009
        tax = calculator.calculate(cif=Decimal("100000123"), has_api=False)
        expected = Decimal("7500009")
        assert tax == expected

    # ---- calculate_import ----
    @pytest.mark.parametrize("importer_type,expected_tariff", [
        (ImporterType.WITH_API, Decimal("2.5")),
        (ImporterType.WITHOUT_API, Decimal("7.5")),
        (ImporterType.DIRECT, Decimal("7.5")),
    ])
    def test_calculate_import_various_importers(self, calculator, importer_type, expected_tariff):
        import_value = Decimal("100000000")
        result = calculator.calculate_import(import_value, importer_type, has_masterlist=False)
        assert result.transaction_type == PPh22Type.IMPORT
        assert result.tariff == expected_tariff
        expected_tax = (import_value * expected_tariff / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        assert result.tax_amount == expected_tax

    def test_calculate_import_with_masterlist(self, calculator):
        import_value = Decimal("100000000")
        # WITH_API + masterlist -> tariff 0.5%
        result = calculator.calculate_import(import_value, ImporterType.WITH_API, has_masterlist=True)
        assert result.tariff == Decimal("0.5")
        expected_tax = (import_value * Decimal("0.5") / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        assert result.tax_amount == expected_tax

    def test_calculate_import_masterlist_only_applies_with_api(self, calculator):
        # WITHOUT_API + masterlist should NOT reduce tariff (still 7.5%)
        import_value = Decimal("100000000")
        result = calculator.calculate_import(import_value, ImporterType.WITHOUT_API, has_masterlist=True)
        assert result.tariff == Decimal("7.5")

    def test_calculate_import_with_transaction_id(self, calculator, sample_transaction_id):
        result = calculator.calculate_import(
            Decimal("1000"), ImporterType.WITH_API, transaction_id=sample_transaction_id
        )
        assert result.transaction_id == sample_transaction_id

    def test_calculate_import_auto_generate_id(self, calculator):
        result = calculator.calculate_import(Decimal("1000"), ImporterType.WITH_API, transaction_id=None)
        assert isinstance(result.transaction_id, UUID)

    # ---- calculate_government_purchase ----
    def test_government_purchase_below_threshold_non_pkp(self, calculator):
        # Purchase 1,000,000 <= 2,000,000 -> exempt
        purchase = Decimal("1000000")
        result = calculator.calculate_government_purchase(
            purchase, GovernmentPurchaserType.GENERAL_GOVERNMENT, is_pkp=False, has_exemption=False
        )
        assert result.tariff == Decimal(0)
        assert result.tax_amount == Decimal(0)
        assert "Exempted" in result.description

    def test_government_purchase_above_threshold_non_pkp(self, calculator):
        purchase = Decimal("3000000")
        result = calculator.calculate_government_purchase(
            purchase, GovernmentPurchaserType.GENERAL_GOVERNMENT, is_pkp=False, has_exemption=False
        )
        assert result.tariff == Decimal("1.5")
        expected_tax = (purchase * Decimal("1.5") / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        assert result.tax_amount == expected_tax

    def test_government_purchase_with_exemption(self, calculator):
        purchase = Decimal("5000000")
        result = calculator.calculate_government_purchase(
            purchase, GovernmentPurchaserType.BUMN, is_pkp=True, has_exemption=True
        )
        assert result.tariff == Decimal(0)
        assert result.tax_amount == Decimal(0)
        assert "Exempted by SKB" in result.description

    def test_government_purchase_different_purchaser_types(self, calculator):
        purchase = Decimal("5000000")
        for ptype in GovernmentPurchaserType:
            result = calculator.calculate_government_purchase(purchase, ptype, is_pkp=False, has_exemption=False)
            # All should use 1.5% tariff
            assert result.tariff == Decimal("1.5")
            # Check that tax is correctly calculated
            expected_tax = (purchase * Decimal("1.5") / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            assert result.tax_amount == expected_tax

    def test_government_purchase_is_pkp_but_below_threshold(self, calculator):
        # Even if PKP, if purchase below threshold, should exempt (as per logic: threshold exemption)
        purchase = Decimal("1500000")
        result = calculator.calculate_government_purchase(
            purchase, GovernmentPurchaserType.GENERAL_GOVERNMENT, is_pkp=True, has_exemption=False
        )
        assert result.tariff == Decimal(0)
        assert result.tax_amount == Decimal(0)

    # ---- calculate_producer_sales ----
    def test_producer_sales_general(self, calculator):
        sales = Decimal("20000000")
        result = calculator.calculate_producer_sales(sales, "general")
        assert result.transaction_type == PPh22Type.PRODUCER_SALES
        assert result.tariff == Decimal("1.5")
        expected_tax = (sales * Decimal("1.5") / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        assert result.tax_amount == expected_tax

    def test_producer_sales_luxury(self, calculator):
        sales = Decimal("20000000")
        result = calculator.calculate_producer_sales(sales, "luxury")
        assert result.tariff == Decimal("5")
        expected_tax = (sales * Decimal("5") / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        assert result.tax_amount == expected_tax

    def test_producer_sales_unknown_category_fallback(self, calculator):
        sales = Decimal("20000000")
        result = calculator.calculate_producer_sales(sales, "unknown")
        assert result.tariff == Decimal("1.5")  # fallback to general

    # ---- calculate_auction ----
    def test_calculate_auction(self, calculator):
        auction_value = Decimal("150000000")
        result = calculator.calculate_auction(auction_value)
        assert result.transaction_type == PPh22Type.AUCTION
        assert result.tariff == Decimal("3")
        expected_tax = (auction_value * Decimal("3") / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        assert result.tax_amount == expected_tax

    def test_calculate_auction_with_transaction_id(self, calculator, sample_transaction_id):
        result = calculator.calculate_auction(Decimal("1000"), transaction_id=sample_transaction_id)
        assert result.transaction_id == sample_transaction_id

    # ---- calculate_by_type ----
    def test_calculate_by_type_import(self, calculator, sample_import_transaction):
        result = calculator.calculate_by_type(sample_import_transaction)
        assert result.transaction_type == PPh22Type.IMPORT
        assert result.tariff == Decimal("2.5")  # with_api default
        expected_tax = (Decimal("100000000") * Decimal("2.5") / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        assert result.tax_amount == expected_tax

    def test_calculate_by_type_government(self, calculator, sample_government_transaction):
        result = calculator.calculate_by_type(sample_government_transaction)
        assert result.transaction_type == PPh22Type.GOVERNMENT_PURCHASE
        assert result.tariff == Decimal("1.5")
        expected_tax = (Decimal("5000000") * Decimal("1.5") / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        assert result.tax_amount == expected_tax

    def test_calculate_by_type_producer(self, calculator, sample_producer_transaction):
        result = calculator.calculate_by_type(sample_producer_transaction)
        assert result.transaction_type == PPh22Type.PRODUCER_SALES
        assert result.tariff == Decimal("1.5")
        expected_tax = (Decimal("20000000") * Decimal("1.5") / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        assert result.tax_amount == expected_tax

    def test_calculate_by_type_auction(self, calculator, sample_auction_transaction):
        result = calculator.calculate_by_type(sample_auction_transaction)
        assert result.transaction_type == PPh22Type.AUCTION
        assert result.tariff == Decimal("3")
        expected_tax = (Decimal("150000000") * Decimal("3") / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        assert result.tax_amount == expected_tax

    def test_calculate_by_type_unsupported_raises(self, calculator, sample_transaction_id):
        # Use OTHER type which is not handled
        tx = PPh22Transaction(
            transaction_id=sample_transaction_id,
            transaction_type=PPh22Type.OTHER,
            taxable_amount=Decimal("1000"),
            transaction_date=datetime.now(UTC),
            additional_data={},
        )
        with pytest.raises(PPh22Error, match="Unsupported PPh 22 type"):
            calculator.calculate_by_type(tx)

    # ---- get_requirements_summary ----
    def test_get_requirements_summary(self, calculator):
        summary = calculator.get_requirements_summary()
        assert "import_rates" in summary
        assert "government_purchase_rates" in summary
        assert "producer_sales_rates" in summary
        assert "auction_rate" in summary
        assert "exemption_threshold" in summary

    # ---- Class methods (test compatibility) ----
    def test_calculate_import_simple_with_api(self):
        tax = PPh22Calculator.calculate_import_simple(cif=Decimal("100000000"), has_api=True)
        # Tariff 10% -> 10,000,000
        assert tax == Decimal("10000000")

    def test_calculate_import_simple_without_api(self):
        tax = PPh22Calculator.calculate_import_simple(cif=Decimal("100000000"), has_api=False)
        # Tariff 7.5% -> 7,500,000
        assert tax == Decimal("7500000")

    def test_calculate_import_simple_rounding(self):
        tax = PPh22Calculator.calculate_import_simple(cif=Decimal("100000123"), has_api=False)
        # 100,000,123 * 7.5% = 7,500,009.225 -> rounded to 7,500,009
        assert tax == Decimal("7500009")

    def test_calculate_pembelian_bendahara(self):
        amount = Decimal("10000000")
        tax = PPh22Calculator.calculate_pembelian_bendahara(amount)
        # 1.5% of 10,000,000 = 150,000
        expected = (amount * Decimal("1.5") / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        assert tax == expected

    # ---- validate, get_rate, calculate_tax (checker methods) ----
    def test_validate(self, calculator):
        assert calculator.validate({}) is True

    def test_get_rate(self, calculator):
        # Default rate for WITH_API = 2.5%
        assert calculator.get_rate() == Decimal("2.5")

    def test_get_rate_with_tax_type(self, calculator):
        # get_rate ignores tax_type and returns default
        assert calculator.get_rate("import") == Decimal("2.5")

    def test_calculate_tax(self, calculator, sample_import_transaction):
        tax = calculator.calculate_tax(sample_import_transaction)
        expected = (Decimal("100000000") * Decimal("2.5") / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        assert tax == expected

    def test_calculate_tax_for_government(self, calculator, sample_government_transaction):
        tax = calculator.calculate_tax(sample_government_transaction)
        expected = (Decimal("5000000") * Decimal("1.5") / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        assert tax == expected


# ============================================================================
# Singleton Accessor
# ============================================================================

def test_get_pph22_calculator():
    c1 = get_pph22_calculator()
    c2 = get_pph22_calculator()
    assert c1 is c2
    assert isinstance(c1, PPh22Calculator)
